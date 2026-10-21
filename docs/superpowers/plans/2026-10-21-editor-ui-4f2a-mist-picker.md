# Editor UI 4f-2a: the Mist picker — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Revision 1, 2026-10-21.** Nothing is built before the owner accepts this plan. Nothing is pushed and no PR is
opened without the owner's OK in chat.

**Goal:** The first half of the Mist step design: the Mist plugin says how the editor shows its steps (each step's
group, the widget its config takes, every body setting's title); the add-step picker shows Mist as its resources, then
a resource's actions; a path id with live choices takes values from earlier steps and shows its choices as a list.

**Architecture:**
- **Display metadata from the plugin** (§4): `plugins/mist/display.py` puts `x-group` (the step's plugin and resource,
  in words) at every config's root, `x-widget` ("update", "create") at the root of the updates and creates, and a
  `title` on every body setting's own entry. All three are annotations the contract hash drops: no step changes
  version, and a test pins the 294 hashes as main computes them.
- **Groups in the picker** (§5.1): `lib/stepGroups.ts` reads `x-group` and matches what's typed; `StepPicker` shows a
  plugin's groups between Flow and Actions, a group's steps on its own view, and filters itself (cmdk's own score for
  the steps no group holds). The drawer names a step's group under its title.
- **Values and choices in a path id** (§5.2): a field with live choices takes pills (`takesPills`), so the drawer
  draws it as text with values; its choices (`LiveOptions.tsx`: one hook for loading, a list, the pick's name) go
  under it. A field that can't take pills keeps its input, with the same list.

**Tech Stack:** Python 3.12 (the backend task); React 19, TanStack Query 5, cmdk 1.1.1, Tailwind v4 tokens; Vitest and
Testing Library (no jest-dom); Playwright against the Compose stack, with axe.

**Spec:** `docs/superpowers/specs/2026-10-21-editor-4f2-mist-step-design.md` (committed 615a43eb on
`docs/editor-ui-4f2-spec`): §3 (the corrections), §4 (the backend), §5.1, §5.2, §5.10, §5.11 (this plan's UI), §6, §8.
4f-2b (Changes, Settings, a device's kind: §5.3–§5.9) is the next plan. The boards: "4f-2 Mist Step Mockups" v8
(Picker, Main's Site ID, States' choices, MoreStates' step found by name, Narrow320Light and Narrow320Dark's picker),
signed off at v7.

## How this plan was checked

The plan's code was checked before review on a scratch checkout of main at 5882c682, never on a branch. Each
task's diffs were applied as written, in order:
- the test diff alone (in Task 2, with the hashes its command wrote from the base first), then the task's tests: they
  failed as its "Run them" step says;
- then the implementation diff and the same tests: they passed;
- after every task, its side's static checks: the type check (`tsc -b --noEmit`) and ESLint, or ruff, the format
  check and mypy: silent;
- after the last, the tree matched the prototype the diffs were cut from, file for file (tree d5750742), the hashes
  file the command wrote included;
- the 10 diff blocks, taken from this file's own text, are the diffs applied, byte for byte, in order, and Task 2's
  command is the one the check ran;
- on the final tree: the whole frontend suite (1517 passed, 110 files; main has 1498 in 108), the build, `check:api`;
  the Mist suite (565 passed); and CodeQL (CLI 2.27.2, CI's filter; python-queries 1.8.13, javascript-queries 2.4.8):
  no finding.

The build and `check:api` were run as their scripts' own commands (`tsc -b && vite build`; `openapi-typescript …
--check`): the scratch checkout borrows its packages through a link, which pnpm refuses to run scripts from. The e2e
spec (Task 6) was type-checked and linted, not run: it needs the Compose stack, which Task 6 asks the owner about. The
executor still runs every step: the check is evidence, not a substitute.

## Global Constraints

- **No step changes version.** Every addition is display metadata the contract hash drops (`x-group`, `x-widget`,
  `title`): the 294 Mist hashes stay as they are on main, pinned in Task 2's test. No route, no migration, no ABI
  change (§4.4).
- **No new dependency.** No npm or Python package is added; no third-party JavaScript or CDN asset: everything is
  bundled, under the strict CSP, with no inline script or style.
- **No real Mist call, no real data (D24).** The unit tests stub `fetch` and use made-up node types (`acme.*`); the
  browser spec writes Mist steps without a connection, so no choice loads, and publishes nothing.
- **Choices load on request only** (ruling 109): never on render, each answer for its scope's era.
- **Words first, the boards' copy** as the spec corrects it (§3). Where neither has words, the rulings below give
  them.
- **No AI tells.** No left-border accents, halos, tinted icon tiles or eyebrows (`src/test/aiTells.test.ts`).
- **WCAG 2.2 AA**, light and dark, at 1280 and 320 px: the picker a dialog named by what it shows; the choices a
  listbox with an active descendant; targets at least 24 px, 44 px below 640 px for the picker's Back and Show
  choices.
- **Verify, don't remember.** Checked in the installed packages: cmdk 1.1.1 exports `defaultFilter` and filters
  nothing with `shouldFilter={false}`; the registry stores a display-only change in place (`registry.py`); a template
  in a uuid path id passes validate and publish (`engine/graph/validate.py`).
- **CI.** Every check runs locally first. Commits and PRs carry no skip marker. Nothing is pushed and no PR is opened
  without the owner's OK in chat. Ask before any local run expected over 10 minutes (the e2e spec on a local Compose
  stack).

## Review Focus

The inputs and conditions most likely to bite a person using this that the design implies but its own lists don't
name. Each is pinned by the test named, in the task that owns the code.

1. **A pick in a path id that holds a value from an earlier step.** The pick replaces it whole, never writes beside
   the pill. Task 5: `takes a value from an earlier step, and then asks for every choice`.
2. **Inserting mid-edge, where a group's steps all end the flow.** The group isn't offered, as a step that can't
   continue isn't. Task 4: `leaves out a group mid-edge when none of its steps continues the flow`.
3. **Backspace in a group's view with text typed.** It deletes the character; only Backspace in the empty search goes
   back. Task 4: `opens a group's steps by title, and goes back with Back or Backspace`.
4. **The connection types can't be read** (a 404 or a 500). The picker names the connection by its key rather than
   saying nothing. Task 4: `offers every active type after a port, in Flow and Actions, with what an action changes
   and needs`.
5. **A choice whose name is its id** (a provider without names). It shows once, not "s9 s9". Task 5: `shows a choice
   known only by its id once`.

## Rulings (proposed; they join the ledger as 324 onward when the owner accepts the plan)

Each says what was decided, why, and what it costs if wrong. Found while building the prototype the diffs come from.

1. **Milestone pauses** after Task 2 (the backend) and Task 5 (the picker and the path ids); then Tasks 6–7 and a
   fresh reviewer. Cost: none.
2. **A step's group** (§4.1, call 1): `"x-group": {"plugin": "Mist", "title": …}` at the root of every config, the
   two generic API steps' included ("API"). The title is `title()` of the resource's name, so it carries its scope
   ("Site settings", "Org WLANs"); four are written: `api` "API", `const_webhook_topics` "Webhook topics",
   `org_aamw_profiles` "Org AAMW profiles", `org_secintel_profiles` "Org SecIntel profiles" (the rule lowercases what
   only the operation ids capitalise). 85 distinct titles. Cost: copy.
3. **Every body setting titled** (§4.2, call 3): on each property entry, at every depth, of the curated and utility
   steps' bodies and their `$defs` (`setdefault`: a title the OAS gives is kept). Not the generic API write's: its
   body is any operation's, its `$defs` only marks secrets. Cost: about 240 kB more in the catalogue, before gzip.
4. **A body's own terms** (§4.2): `BODY_TERMS`, `titles`' terms plus SSID, VLAN, ACL, IP, IPv6, SNMP, NTP, MTU, STP,
   PoE, VRF, RADIUS, LACP, LAN, NAT, QoS, IKE, IPsec and the like, each reached by some setting's name (tested).
   `title()` takes a table, its default unchanged: node and path titles keep the signed-off spellings ("Vlan ID",
   "Get site radius config"). Cost: copy.
5. **A device's kinds** (§4.2): a union whose every branch allows one `type` value titles each branch, on the branch's
   own entry beside its `$ref` ("AP", "Switch", "Gateway"); the unions `mist_device` and `deviceprofile` get "Device"
   and "Device profile", the only components that gain a title (tested against the OAS). 4f-2b reads them. Cost:
   none.
6. **The widgets** (§4.3, call 4): "update" where a config has `body`, `mode` and `clear` (40); "create" where a POST
   whose operation id starts with "create" requires a body (36). 4f-2b draws them; until then the drawer falls back to
   the generic form (ruling 100). Cost: none.
7. **The hashes pinned** (§4.4): `tests/plugins/mist/contract_hashes.json`, 294 lines, written from the base by Task
   2's first step (a command, not a diff), so the test holds the hashes main computes. Cost: none.
8. **The picker's order** (§5.1): Flow, then each plugin's groups (plugins by name), then Actions (the steps no group
   holds), then Or. Groups by title; a group's steps by title ("Create, Delete, Get, List, Update", not the spec's
   example order "List, Get, …": the plugin gives no order). Cost: CRUD read alphabetically.
9. **The picker's search** (§5.1, call 11): cmdk filters nothing (`shouldFilter={false}`); the steps no group holds
   are ranked by cmdk's own `defaultFilter`, as before. A group is found when each word typed is in its title or in
   one of its steps' refs. A grouped step is listed above the groups ("Mist step", "Mist steps") when its title starts
   with what's typed, or when a ref is typed (it has a dot) and its ref holds it: "wlan" finds the groups, not fifteen
   steps whose refs hold it. Matched groups are headed "Mist resources". Cost: a step's middle words don't find it
   ("org wlan" finds the groups).
10. **A group's row** (§5.1): its title; "4 actions" in the code face; its steps' titles' first words, each once, in
    title order, cut after six with "…" (Site devices: "Arp, Bounce, …"). No scope word: the title has it (§3.4).
    Cost: copy.
11. **A group's view** (§5.1): the dialog is named "Add a step: Org WLANs"; above the search, "← Back" (named "Back to
    every step", 44 px below 640 px) and "Mist · **Org WLANs**"; the search's placeholder "Type an action's name";
    Backspace in the empty search goes back too; going back selects the group's row again. Cost: none.
12. **A connection named by its type's label** in each action row ("Uses a Mist connection"), from `GET
    /api/v1/connection-types`, read only when an offered step takes a connection; the key until the label is known,
    or when it can't be read. Cost: one cached read per session.
13. **The drawer names a step's group** under its title line: "Mist · Site settings" (§5.10, §3.5). Cost: none.
14. **A path id with choices takes values** (§5.2; ruling 127 amended): `takesPills` takes the "options" widget, so
    the field is "Text" with "＋ Data" and Formula, as any text field. "Show choices" goes under the field (44 px below
    640 px); the hint adds "A value from an earlier step, or one of the connection's choices: Show choices lists
    them."; the query is the field's text when it holds no value from a step, else empty. A field that can't take
    pills (literal-only) keeps its input with the button beside. Cost: a typed id and a pick look like any text.
15. **The choices as a list under the field** (§5.2, call 12): a listbox named "Choices for Site ID", focused when it
    shows; Up, Down, Home, End, Enter, Escape (Escape closes it, not the drawer); "2 choices" in the status line; each
    row the choice's name and its id's first eight characters ("5c1e0b1a…"; whole when 12 or shorter, left out when
    it's the name); 320 px tall at most, then it scrolls. Cost: none.
16. **A pick** (§5.2) writes the value as text, releases what a refused write held, redraws the field, and gives focus
    back to it; "HQ Paris, picked from the choices." shows while the field holds that value, until the drawer closes.
    Escape gives focus back too. Cost: the name is gone on reopening (the config keeps the id).
17. **The checks:** each task's tests red, then green, with its static checks; on the final tree the frontend suite,
    the Mist suite (`tests/plugins/mist`), ruff, mypy, the build, `check:api` and CodeQL. The browser spec runs in CI's
    e2e job, or locally on the owner's word. Cost: none.

Mid-slice rulings start at M113.

## File structure

| File | Responsibility |
|---|---|
| `backend/src/dewpoint/plugins/mist/display.py` | a step's group, its config's widget, its body's setting titles: display metadata (Task 2) |
| `backend/src/dewpoint/plugins/mist/titles.py` | `title` takes a table of terms; node and path titles keep theirs (Task 2) |
| `backend/src/dewpoint/plugins/mist/nodes.py`, `utilities.py`, `api.py` | each config titled and marked as it's built (Task 2) |
| `backend/tests/plugins/mist/test_display.py`, `contract_hashes.json` | the metadata, and the 294 hashes as main computes them (Task 2) |
| `frontend/src/lib/stepGroups.ts` | a step's group; the groups offered; what's typed matched to a group or a step (Task 3) |
| `frontend/src/routes/editor/drawer/StepDrawer.tsx` | the group's line under the step's title (Task 3) |
| `frontend/src/test/nodeTypes.ts` | `GROUPED`, made-up steps in groups (Task 3) |
| `frontend/src/routes/editor/StepPicker.tsx` | the picker: groups, a group's view, its own search, connections by label (Task 4) |
| `frontend/src/lib/schemaForm.ts` | `takesPills`: a field with live choices takes values (Task 5) |
| `frontend/src/routes/editor/drawer/LiveOptions.tsx` | choices loaded on request, listed under the field, a pick named (Task 5) |
| `frontend/src/routes/editor/drawer/FieldView.tsx` | the choices under a field with values; their hint (Task 5) |
| `frontend/e2e/mist.spec.ts`, `frontend/e2e/fixtures/mist.dewpoint.json`, `frontend/playwright.config.ts` | the browser spec (Task 6) |
| `docs/superpowers/plans/2026-10-05-editor-ui-4-ledger.md` | the plan's acceptance, each milestone, the final checkpoint (Tasks 1, 2, 5, 7) |

## Milestones

1. **Tasks 1–2:** the ledger; the plugin's display metadata. Pause for the owner's review.
2. **Tasks 3–5:** the groups and the drawer's group line; the picker; path ids with values and choices. Pause for the
   owner's review.
3. **Tasks 6–7:** the browser spec, every check, the final checkpoint. Then the final review.

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

# Milestone 1 — The ledger, and the plugin's display metadata

### Task 1: The ledger: 4f-1 merged, 4f-2 designed, this plan accepted

**Files:**
- Modify: `docs/superpowers/plans/2026-10-05-editor-ui-4-ledger.md` (appended at the end)

**Interfaces:**
- Consumes: nothing.
- Produces: the ledger section later tasks append to (`### 4f-2a, milestone N`).

- [ ] **Step 1: Write the plan's status**

Run this task only once the owner has accepted the plan. Apply:

```diff
diff --git a/docs/superpowers/plans/2026-10-05-editor-ui-4-ledger.md b/docs/superpowers/plans/2026-10-05-editor-ui-4-ledger.md
index 42da1dc4..5dd9122c 100644
--- a/docs/superpowers/plans/2026-10-05-editor-ui-4-ledger.md
+++ b/docs/superpowers/plans/2026-10-05-editor-ui-4-ledger.md
@@ -3754,3 +3754,45 @@ reading the scheme only (§5.3); a computed title or text quoted in the webhook'
 types are read (ruling 321); a field value's Slack limit against a computed label (§5.5); ↑ and ↓ keeping the offset
 within a text, and Home and End passing pills (ruling 307); a private-use character of a person's own drawn as a value
 (ruling 316); "shortened first" when both tighten at once (ruling 317); the e2e spec proved in CI's job on #134.
+
+### 4f-1 merged; 4f-2 designed; the 4f-2a plan accepted (2026-10-21)
+
+The owner merged the certifi fix as #135 (squash 795d9896) and 4f-1 as #134 (squash 5882c682), every check green
+("green and merged"); its six deferred minors are issue #136.
+
+4f-2 was researched (notes R4 and R5 in `~/4_dev/mist_dewpoint-4f-notes`), then proposed. The owner's answers
+(2026-10-21): the add-step picker chooses a Mist step, never a change of type in the drawer; a create's body is the
+same list as an update's, Set only, its required settings first; settings are labelled in the plugin's words, their
+name beside; a device's body asks for its kind first. The boards ("4f-2 Mist Step Mockups") were approved at round 1
+("looks good") and signed off at v7 (D8); v8 put the drawer's own descriptions back on two boards. The design,
+`docs/superpowers/specs/2026-10-21-editor-4f2-mist-step-design.md` (615a43eb), corrects some of the boards' words
+(§3: replace keeps the settings not listed; read-only settings aren't offered; no object is named); it amends ruling
+127 (a field with live choices takes values from earlier steps: 4f-2a) and ruling 98 for an update's and a create's
+body (4f-2b). Two plans: 4f-2a, the plugin's display metadata, the picker and the path ids; then 4f-2b, Changes,
+Settings and a device's kind.
+
+`docs/superpowers/plans/2026-10-21-editor-ui-4f2a-mist-picker.md`, revision 1, with milestone pauses. The owner
+accepted it: its rulings 1–17 join this ledger as 324–340. No step changes version: everything the plugin adds is
+display metadata, outside the contract hash (the 294 hashes pinned); no route, no migration, no ABI change. Mid-slice
+rulings start at M113.
+
+324. **Accepted. Milestone pauses after the backend and after the UI** (plan ruling 1).
+325. **Accepted. A step's group at its config's root: `x-group`, its plugin and its resource's title** (plan ruling 2).
+326. **Accepted. Every setting of a body titled, on its own entry** (plan ruling 3).
+327. **Accepted. A body's own terms, which node and path titles don't take** (plan ruling 4).
+328. **Accepted. A device's kinds titled on the union's branches; two unions titled** (plan ruling 5).
+329. **Accepted. `x-widget`: "update" where a config has a body, a mode and a clear; "create" where a create requires
+     a body** (plan ruling 6).
+330. **Accepted. The 294 hashes pinned in a file a command writes from the base** (plan ruling 7).
+331. **Accepted. The picker: Flow, each plugin's groups, then Actions; groups and their steps by title** (plan
+     ruling 8).
+332. **Accepted. The picker's own search: a group by each word, a grouped step by its title's start or a typed ref**
+     (plan ruling 9).
+333. **Accepted. A group's row: its title, how many actions, their first words** (plan ruling 10).
+334. **Accepted. A group's view, and Back** (plan ruling 11).
+335. **Accepted. A connection named by its type's label in the picker** (plan ruling 12).
+336. **Accepted. The drawer names a step's group under its title** (plan ruling 13).
+337. **Accepted. A path id with choices takes values: Text, ＋ Data, Show choices under it** (plan ruling 14).
+338. **Accepted. The choices as a list under the field** (plan ruling 15).
+339. **Accepted. A pick written as text, named while the field holds it** (plan ruling 16).
+340. **Accepted. The checks; the browser spec in CI, or locally on the owner's word** (plan ruling 17).
```

- [ ] **Step 2: Commit**

```bash
git add docs/superpowers/plans/2026-10-05-editor-ui-4-ledger.md
git commit -m "docs(editor-4): 4f-1 merged, 4f-2 designed, the 4f-2a plan accepted

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: The Mist plugin's display metadata

**Spec:** §4.1–§4.4; §6 (the backend's tests).

**Files:**
- Create: `backend/src/dewpoint/plugins/mist/display.py`, `backend/tests/plugins/mist/test_display.py`,
  `backend/tests/plugins/mist/contract_hashes.json` (written by Step 1's command)
- Modify: `backend/src/dewpoint/plugins/mist/titles.py` (`title` takes a table),
  `backend/src/dewpoint/plugins/mist/nodes.py` (`_widget`; `build` titles and marks each config),
  `backend/src/dewpoint/plugins/mist/utilities.py`, `backend/src/dewpoint/plugins/mist/api.py` (each config marked)

**Interfaces:**
- Consumes: `contract_hash` (`engine/registry/catalog.py`); `SCHEMA_ONE`, `SCHEMA_LIST`, `SCHEMA_MAP`
  (`plugins/mist/schemas.py`); `TERMS`, `title`, `words` (`plugins/mist/titles.py`).
- Produces:
  - every Mist config's root holds `"x-group": {"plugin": "Mist", "title": <the resource's title>}` (Tasks 3 and 4
    read it); the 40 updates' `"x-widget": "update"`, the 36 creates' `"x-widget": "create"` (4f-2b);
  - every body setting's entry has a `title`; a device union's branches are titled "AP", "Switch", "Gateway", its union
    "Device" or "Device profile" (4f-2b);
  - `display.py`: `PLUGIN_TITLE`, `GROUP_TITLES`, `BODY_TERMS`, `UNION_TITLES`; `group_title(resource: str) -> str`,
    `setting_title(name: str) -> str`, `displayed(type_: str, schema: dict, widget: str | None = None) -> dict`,
    `titled(schema: dict) -> dict`;
  - `titles.title(name: str, terms: Mapping[str, str] = TERMS) -> str`.

The metadata is added while each config is built: `nodes.build` titles a config's body (`display.titled`), then marks
its root (`display.displayed`, with `_widget`'s answer); `utilities.build` does both, without a widget; `api.build`
marks the two generic steps' roots only. Every key added is one the contract hash drops, so the test pins the 294
hashes main computes, written from the base by the first step, before anything changes.

- [ ] **Step 1: Pin the hashes, and write the failing tests**

From `$WT/backend`, before any change to `src`, write the base's hashes:

```bash
UV_FROZEN=1 UV_NO_SYNC=1 uv run python -c 'import json; from dewpoint.engine.registry.catalog import contract_hash; from dewpoint.plugins.mist import PLUGIN; print(json.dumps({f"{n["type"]}@{n["version"]}": contract_hash(n) for n in PLUGIN.manifest()["nodes"]}, indent=1, sort_keys=True))' > tests/plugins/mist/contract_hashes.json
```

Expected: a file of 296 lines, from `"mist.api.read@1"` to `"mist.site_wxrules.update@1"`. Then apply:

```diff
diff --git a/backend/tests/plugins/mist/test_display.py b/backend/tests/plugins/mist/test_display.py
new file mode 100644
index 00000000..f0b10d38
--- /dev/null
+++ b/backend/tests/plugins/mist/test_display.py
@@ -0,0 +1,160 @@
+# SPDX-License-Identifier: Apache-2.0
+"""What the editor shows of a Mist step beyond its rules (editor 4f-2, the Mist step design §4): each config's group
+and widget at its root, its body's setting titles. All display metadata, so no contract hash moves: the pinned values
+were computed on origin/main 5882c682, before any of it."""
+
+import json
+import pathlib
+import re
+from collections.abc import Iterator
+from typing import Any
+
+import pytest
+
+from dewpoint.engine.registry.catalog import contract_hash
+from dewpoint.plugins.mist import PLUGIN, oas
+from dewpoint.plugins.mist.display import BODY_TERMS, UNION_TITLES, setting_title
+from dewpoint.plugins.mist.schemas import SCHEMA_LIST, SCHEMA_MAP, SCHEMA_ONE
+from dewpoint.plugins.mist.titles import TERMS, title, words
+
+NODES = {f"{n['type']}@{n['version']}": n for n in PLUGIN.manifest()["nodes"]}
+CONFIGS = {ref: n["config_schema"] for ref, n in NODES.items()}
+PINNED = json.loads((pathlib.Path(__file__).parent / "contract_hashes.json").read_text())
+
+
+def _entries(node: Any) -> Iterator[tuple[str, Any]]:
+    """Each property entry under `node`, at every depth, with its name."""
+    if isinstance(node, list):
+        for sub in node:
+            yield from _entries(sub)
+    elif isinstance(node, dict):
+        for key, value in node.items():
+            if key == "properties" and isinstance(value, dict):
+                yield from value.items()
+            if key in SCHEMA_MAP and isinstance(value, dict):
+                yield from _entries(list(value.values()))
+            elif key in SCHEMA_ONE or key in SCHEMA_LIST:
+                yield from _entries(value)
+
+
+def _bodies() -> Iterator[tuple[str, Any]]:
+    """Each curated or utility config's body and its `$defs`: the generic API steps' are left out (their body is any
+    operation's)."""
+    for ref, config in CONFIGS.items():
+        if "body" in config["properties"] and not ref.startswith("mist.api."):
+            yield ref, [config["properties"]["body"], *config.get("$defs", {}).values()]
+
+
+def test_the_display_metadata_moves_no_contract_hash() -> None:
+    assert {ref: contract_hash(n) for ref, n in NODES.items()} == PINNED
+
+
+def test_every_step_names_its_group() -> None:
+    groups = {ref: config["x-group"] for ref, config in CONFIGS.items()}
+    assert {g["plugin"] for g in groups.values()} == {"Mist"}
+    assert len({g["title"] for g in groups.values()}) == 85
+    assert groups["mist.site_settings.update@1"]["title"] == "Site settings"
+    assert groups["mist.org_wlans.create@1"]["title"] == "Org WLANs"
+    assert groups["mist.org_wlan_templates.list@1"]["title"] == "Org WLAN templates"
+    assert groups["mist.site_devices.bounce_port@1"]["title"] == "Site devices"
+    assert groups["mist.const_webhook_topics.list@1"]["title"] == "Webhook topics"
+    assert groups["mist.api.read@1"]["title"] == "API"
+
+
+def test_each_step_of_a_resource_shares_its_group() -> None:
+    by_resource: dict[str, set[str]] = {}
+    for ref, config in CONFIGS.items():
+        by_resource.setdefault(ref.split(".")[1], set()).add(config["x-group"]["title"])
+    assert len(by_resource) == 85
+    assert all(len(titles) == 1 for titles in by_resource.values())
+
+
+def test_updates_and_creates_name_their_widget() -> None:
+    widgets = {ref: config.get("x-widget") for ref, config in CONFIGS.items()}
+    updates = {ref for ref, w in widgets.items() if w == "update"}
+    creates = {ref for ref, w in widgets.items() if w == "create"}
+    assert len(updates) == 40 and len(creates) == 36
+    assert {w for w in widgets.values()} == {None, "update", "create"}
+    assert all({"body", "mode", "clear"} <= set(CONFIGS[ref]["properties"]) for ref in updates)
+    assert all("body" in CONFIGS[ref]["required"] for ref in creates)
+    assert {"mist.site_settings.update@1", "mist.site_devices.update@1", "mist.org_wlans.update@1"} <= updates
+    assert {"mist.org_wlans.create@1", "mist.org_device_profiles.create@1"} <= creates
+    assert widgets["mist.site_devices.bounce_port@1"] is None
+    assert widgets["mist.api.write@1"] is None
+
+
+@pytest.mark.parametrize(
+    ("name", "expected"),
+    [
+        ("ssid", "SSID"),
+        ("vlan_id", "VLAN ID"),
+        ("allowed_vlan_ids", "Allowed VLAN IDs"),
+        ("min_rogue_rssi", "Min rogue RSSI"),
+        ("acl_tags", "ACL tags"),
+        ("auto_upgrade", "Auto upgrade"),
+        ("allow_mist", "Allow Mist"),
+        ("ap_matching", "AP matching"),
+        ("poe_disabled", "PoE disabled"),
+        ("dns_servers", "DNS servers"),
+        ("ip6", "IPv6"),
+        ("radius_config", "RADIUS config"),
+        ("use_dot1x", "Use dot1x"),  # as Mist writes it
+    ],
+)
+def test_a_setting_is_titled_by_its_name_in_words(name: str, expected: str) -> None:
+    assert setting_title(name) == expected
+
+
+def test_node_and_path_titles_keep_their_own_terms() -> None:
+    """The body's terms stay out of the signed-off titles: `radius` and `vlan` stay lower case there."""
+    assert title("vlan_id") == "Vlan ID"
+    assert title("getSiteRadiusConfig") == "Get site radius config"
+    assert set(TERMS) < set(BODY_TERMS)
+
+
+def test_every_setting_of_a_body_has_a_title() -> None:
+    untitled = sorted({f"{ref}: {name}" for ref, body in _bodies() for name, e in _entries(body) if "title" not in e})
+    assert untitled == []
+
+
+def test_site_settings_titles() -> None:
+    config = CONFIGS["mist.site_settings.update@1"]
+    rogue = config["$defs"]["site_rogue"]["properties"]
+    assert rogue["min_rogue_rssi"]["title"] == "Min rogue RSSI"
+    assert rogue["whitelisted_ssids"]["title"] == "Whitelisted SSIDs"
+
+
+def test_a_device_body_offers_titled_kinds() -> None:
+    for ref, union in (
+        ("mist.site_devices.update@1", "mist_device"),
+        ("mist.org_device_profiles.update@1", "deviceprofile"),
+        ("mist.org_device_profiles.create@1", "deviceprofile"),
+    ):
+        defs = CONFIGS[ref]["$defs"]
+        branches = defs[union].get("anyOf") or defs[union]["oneOf"]
+        assert defs[union]["title"] == UNION_TITLES[union]
+        assert sorted(b["title"] for b in branches) == ["AP", "Gateway", "Switch"]
+
+
+def test_no_shared_component_gains_a_title() -> None:
+    """A title on a component would label every setting reaching it: only the two unions get one."""
+    components = oas.document()["components"]["schemas"]
+    gained = sorted(
+        {
+            f"{ref}: {name}"
+            for ref, config in CONFIGS.items()
+            for name, schema in config.get("$defs", {}).items()
+            if name not in UNION_TITLES and schema.get("title") != components.get(name, {}).get("title")
+        }
+    )
+    assert gained == []
+
+
+def test_every_body_term_is_reached_by_a_setting() -> None:
+    """Reachability only, against a misspelled or dead key: the table above pins how each term is written."""
+    found = {" ".join(w.lower() for w in words(name)) for _, body in _bodies() for name, _ in _entries(body)}
+
+    def reached(key: str) -> bool:
+        return any(re.search(rf"(?:^| ){re.escape(key)}s?(?: |$)", text) for text in found)
+
+    assert [key for key in BODY_TERMS if key not in TERMS and not reached(key)] == []
```

- [ ] **Step 2: Run them**

Run: `UV_FROZEN=1 UV_NO_SYNC=1 uv run pytest -q tests/plugins/mist/test_display.py tests/plugins/mist/test_titles.py`
Expected: FAIL: the test can't import its module (`ModuleNotFoundError: No module named
'dewpoint.plugins.mist.display'`; 1 error during collection, so no test runs).

- [ ] **Step 3: Implement the metadata**

Apply:

```diff
diff --git a/backend/src/dewpoint/plugins/mist/api.py b/backend/src/dewpoint/plugins/mist/api.py
index 01da1980..c134f85c 100644
--- a/backend/src/dewpoint/plugins/mist/api.py
+++ b/backend/src/dewpoint/plugins/mist/api.py
@@ -27,6 +27,7 @@ from pydantic import BaseModel
 
 from dewpoint.plugins.mist import fixtures, oas, policy, routing
 from dewpoint.plugins.mist.client import SEGMENT, InvalidPathValue, MistClient
+from dewpoint.plugins.mist.display import displayed
 from dewpoint.plugins.mist.nodes import OperationUnavailable, _example
 from dewpoint.plugins.mist.routing import UUID, Route, filled, matched, reaches, value_pattern
 from dewpoint.plugins.mist.schemas import converted, resolved, secret_fields, with_defs
@@ -219,7 +220,7 @@ def build() -> tuple[type[Node], ...]:
         {
             "__module__": __name__, "__qualname__": "MistApiRead", "type": READ, "version": 1, "title": "Mist API read",
             "description": "A GET of any operation the policy map allows, inside the connection's org.",
-            "Config": declared_model("MistApiReadConfig", _config(READ, write=False), formats=()),
+            "Config": declared_model("MistApiReadConfig", displayed(READ, _config(READ, write=False)), formats=()),
             "Output": declared_model("MistApiReadOutput", OUTPUT, formats=()),
             "side_effect": SideEffect.NONE, "capabilities": frozenset({"mist.read"}), "fixed_method": "GET",
             "timeout": timedelta(minutes=1),
@@ -233,7 +234,7 @@ def build() -> tuple[type[Node], ...]:
             "title": "Mist API write",
             "description": "A POST, PUT or DELETE of any operation the policy map allows, inside the connection's org; "
             "never retried once sent.",
-            "Config": declared_model("MistApiWriteConfig", _config(WRITE, write=True), formats=()),
+            "Config": declared_model("MistApiWriteConfig", displayed(WRITE, _config(WRITE, write=True)), formats=()),
             "Output": declared_model("MistApiWriteOutput", OUTPUT, formats=()),
             "side_effect": SideEffect.AMBIGUOUS, "capabilities": frozenset({"mist.write"}),
             "timeout": timedelta(minutes=1),
diff --git a/backend/src/dewpoint/plugins/mist/display.py b/backend/src/dewpoint/plugins/mist/display.py
new file mode 100644
index 00000000..bdc74d46
--- /dev/null
+++ b/backend/src/dewpoint/plugins/mist/display.py
@@ -0,0 +1,114 @@
+# SPDX-License-Identifier: Apache-2.0
+"""What the editor shows of a Mist step beyond its schema's rules (editor 4f-2, the Mist step design §4): its group in
+the add-step picker, the widget its config takes, and its settings' titles. All of it is display metadata the contract
+hash drops (`x-group`, `x-widget`, `title`), so no step's version changes.
+
+- The group is the step's resource (`mist.<resource>.<action>`), titled; it sits at the config's root, the one place a
+  plugin can put it without moving the hash.
+- A setting's title is its name in words: Mist's terms as `titles` writes them, and the terms only a body uses (SSID,
+  VLAN…), which node and path titles don't take (they stay as signed off: `radius`, `dot1x`). It goes on the setting's
+  own entry, never on a shared `$defs` component that other settings reach too.
+- A union whose every branch allows one `type` (a device's AP, switch or gateway) titles each branch by that value."""
+
+from collections.abc import Mapping
+from typing import Any
+
+from dewpoint.plugins.mist.schemas import SCHEMA_LIST, SCHEMA_MAP, SCHEMA_ONE
+from dewpoint.plugins.mist.titles import TERMS, title
+
+PLUGIN_TITLE = "Mist"
+# A resource whose name, in words, isn't how the picker should say it.
+GROUP_TITLES = {
+    "api": "API",
+    "const_webhook_topics": "Webhook topics",
+    "org_aamw_profiles": "Org AAMW profiles",
+    "org_secintel_profiles": "Org SecIntel profiles",
+}
+# A body's terms, beyond `titles`' own: how Mist writes them.
+BODY_TERMS: dict[str, str] = {
+    **TERMS,
+    **{a: a.upper() for a in (
+        "acl bfd cli dscp fqdn http igmp ike ip lacp lan lte mqtt mtu nas nat ntp oob radius sla snmp ssdp ssid stp"
+        " tacacs tls ttl usb uuid uwb vlan vrf vrrp wds wpa3"
+    ).split()},
+    "coa": "CoA",
+    "ip6": "IPv6",
+    "ipsec": "IPsec",
+    "ipv6": "IPv6",
+    "mdns": "mDNS",
+    "poe": "PoE",
+    "pppoe": "PPPoE",
+    "qos": "QoS",
+    "radsec": "RadSec",
+    "voip": "VoIP",
+}  # fmt: skip
+# A union a body is, titled for the kind it offers ("Kind of device").
+UNION_TITLES = {"mist_device": "Device", "deviceprofile": "Device profile"}
+
+
+def group_title(resource: str) -> str:
+    return GROUP_TITLES.get(resource) or title(resource)
+
+
+def setting_title(name: str) -> str:
+    return title(name, BODY_TERMS)
+
+
+def displayed(type_: str, schema: dict[str, Any], widget: str | None = None) -> dict[str, Any]:
+    """`schema`, a step's config, with its group at its root, and its widget when it takes one."""
+    schema["x-group"] = {"plugin": PLUGIN_TITLE, "title": group_title(type_.split(".")[1])}
+    if widget is not None:
+        schema["x-widget"] = widget
+    return schema
+
+
+def titled(schema: dict[str, Any]) -> dict[str, Any]:
+    """`schema`, a step's config, with a title on each of its body's settings, at every depth, and on the branches and
+    unions of a body that offers kinds."""
+    defs = schema.get("$defs", {})
+    for name, union in UNION_TITLES.items():
+        if name in defs:
+            defs[name]["title"] = union
+    for node in [schema["properties"].get("body"), *defs.values()]:
+        _titled(node, defs)
+    return schema
+
+
+def _titled(node: Any, defs: Mapping[str, Any]) -> None:
+    if isinstance(node, list):
+        for sub in node:
+            _titled(sub, defs)
+        return
+    if not isinstance(node, dict):
+        return
+    for key, value in node.items():
+        if key == "properties" and isinstance(value, dict):
+            for name, sub in value.items():
+                if isinstance(sub, dict):
+                    sub.setdefault("title", setting_title(name))
+        if key in ("anyOf", "oneOf") and isinstance(value, list):
+            kinds = [kind for branch in value if (kind := _kind(branch, defs)) is not None]
+            if kinds and len(kinds) == len(value):
+                for branch, kind in zip(value, kinds, strict=True):
+                    branch.setdefault("title", setting_title(kind))
+        if key in SCHEMA_ONE or key in SCHEMA_LIST or key in SCHEMA_MAP:
+            _titled(list(value.values()) if key in SCHEMA_MAP and isinstance(value, dict) else value, defs)
+
+
+def _kind(branch: Any, defs: Mapping[str, Any]) -> str | None:
+    """The one value a union's branch allows its `type`, if it allows one."""
+    target = _target(branch, defs)
+    kind = _target(target.get("properties", {}).get("type"), defs) if isinstance(target, Mapping) else None
+    values = kind.get("enum") if isinstance(kind, Mapping) else None
+    return values[0] if isinstance(values, list) and len(values) == 1 and isinstance(values[0], str) else None
+
+
+def _target(node: Any, defs: Mapping[str, Any]) -> Any:
+    seen: set[str] = set()
+    while isinstance(node, Mapping) and isinstance(node.get("$ref"), str) and node["$ref"].startswith("#/$defs/"):
+        name = node["$ref"][len("#/$defs/") :]
+        if name in seen or name not in defs:
+            break
+        seen.add(name)
+        node = defs[name]
+    return node
diff --git a/backend/src/dewpoint/plugins/mist/nodes.py b/backend/src/dewpoint/plugins/mist/nodes.py
index 53c3c585..b445db63 100644
--- a/backend/src/dewpoint/plugins/mist/nodes.py
+++ b/backend/src/dewpoint/plugins/mist/nodes.py
@@ -19,7 +19,7 @@ from typing import Any, ClassVar
 
 from pydantic import BaseModel
 
-from dewpoint.plugins.mist import fixtures, oas, policy, routing
+from dewpoint.plugins.mist import display, fixtures, oas, policy, routing
 from dewpoint.plugins.mist.client import SEGMENT, InvalidAnswer, InvalidPathValue, MistClient, NotFound, may_have_more
 from dewpoint.plugins.mist.schemas import converted, resolved, top_properties, with_defs
 from dewpoint.plugins.mist.titles import title
@@ -393,6 +393,16 @@ def _class_name(type_: str) -> str:
     return "".join(part.title() for part in re.split(r"[._]", type_))
 
 
+def _widget(op: oas.Operation, config: Mapping[str, Any]) -> str | None:
+    """The editor's widget for a config (4f-2): an update's changes (`body`, `mode`, `clear`), a create's settings (a
+    required `body`)."""
+    if {"body", "mode", "clear"} <= set(config["properties"]):
+        return "update"
+    if op.method == "POST" and op.id.startswith("create") and "body" in config["required"]:
+        return "create"
+    return None
+
+
 def build() -> tuple[type[Node], ...]:
     """Every allowed operation's curated node, in the map's order; a device utility's node is its own (`utilities`)."""
     doc, ops, entries = oas.document(), oas.operations(), policy.load().entries
@@ -410,6 +420,7 @@ def build() -> tuple[type[Node], ...]:
         merge_with = merge_with if merge_with in entry.reads else None  # the map lists every read (O2)
         pickers = {f: o for f, o in routing.pickers(op.path, entry.scope, lists).items() if o in entry.reads}
         name = _class_name(type_)
+        config = display.titled(config_schema(doc, op, shape, paging, merge_with is not None, pickers))
         attrs: dict[str, Any] = {
             "__module__": __name__,
             "__qualname__": name,
@@ -418,10 +429,7 @@ def build() -> tuple[type[Node], ...]:
             "title": title(op_id),
             "description": _description(op) + (RACE if merge_with is not None else ""),
             "Config": declared_model(
-                f"{name}Config",
-                config_schema(doc, op, shape, paging, merge_with is not None, pickers),
-                formats=(),
-                checked=False,
+                f"{name}Config", display.displayed(type_, config, _widget(op, config)), formats=(), checked=False
             ),
             "Output": declared_model(f"{name}Output", output_schema(doc, answer, shape), formats=(), checked=False),
             "side_effect": SideEffect(entry.side_effect),
diff --git a/backend/src/dewpoint/plugins/mist/titles.py b/backend/src/dewpoint/plugins/mist/titles.py
index 59f7333c..a39eb149 100644
--- a/backend/src/dewpoint/plugins/mist/titles.py
+++ b/backend/src/dewpoint/plugins/mist/titles.py
@@ -4,6 +4,7 @@ through reviewed Mist terminology (the plugins-3 ruling): a term the id writes a
 Mist writes it ("NAC", "wxtag"); any other word keeps the id's acronym ("WLAN") or is lowercase."""
 
 import re
+from collections.abc import Mapping
 
 ACRONYMS = (
     "ap api arp atp ble bgp bpdu bssid crl dhcp dns esl evpn fips fpc0 fpga gbp gw ha id idp jse jsi led mac ml msp nac"
@@ -50,14 +51,14 @@ def words(name: str) -> list[str]:
     return re.findall(r"[A-Z]{2,}s?(?![a-z])|[A-Z]?[a-z0-9]+|[A-Z]", name)
 
 
-def title(name: str) -> str:
+def title(name: str, terms: Mapping[str, str] = TERMS) -> str:
     split = words(name)
     lower = [w.lower() for w in split]
     out: list[str] = []
     i = 0
     while i < len(split):
         for n in (2, 1):
-            term = _term(" ".join(lower[i : i + n])) if i + n <= len(split) else None
+            term = _term(" ".join(lower[i : i + n]), terms) if i + n <= len(split) else None
             if term is not None:
                 out.append(term)
                 i += n
@@ -69,10 +70,10 @@ def title(name: str) -> str:
     return text[:1].upper() + text[1:]
 
 
-def _term(key: str) -> str | None:
+def _term(key: str, terms: Mapping[str, str]) -> str | None:
     """How Mist writes these words, the last one maybe plural ("psks": "PSKs")."""
-    if key in TERMS:
-        return TERMS[key]
-    if key.endswith("s") and key[:-1] in TERMS:
-        return TERMS[key[:-1]] + "s"
+    if key in terms:
+        return terms[key]
+    if key.endswith("s") and key[:-1] in terms:
+        return terms[key[:-1]] + "s"
     return None
diff --git a/backend/src/dewpoint/plugins/mist/utilities.py b/backend/src/dewpoint/plugins/mist/utilities.py
index 22d5d1a8..c064fe98 100644
--- a/backend/src/dewpoint/plugins/mist/utilities.py
+++ b/backend/src/dewpoint/plugins/mist/utilities.py
@@ -18,7 +18,7 @@ from typing import Any, ClassVar
 
 from pydantic import BaseModel
 
-from dewpoint.plugins.mist import oas, policy, routing, stream
+from dewpoint.plugins.mist import display, oas, policy, routing, stream
 from dewpoint.plugins.mist.client import InvalidAnswer, MistClient
 from dewpoint.plugins.mist.nodes import MistOperation, OperationUnavailable, _class_name, _description
 from dewpoint.plugins.mist.schemas import converted, with_defs
@@ -282,7 +282,10 @@ def build() -> tuple[type[Node], ...]:
             "title": title(op_id),
             "description": _description(op) + CONTRACT_TEXT[review.contract],
             "Config": declared_model(
-                f"{name}Config", config_schema(doc, op, review, pickers, default), formats=(), checked=False
+                f"{name}Config",
+                display.displayed(type_, display.titled(config_schema(doc, op, review, pickers, default))),
+                formats=(),
+                checked=False,
             ),
             "Output": declared_model(f"{name}Output", output_schema(review, answers), formats=(), checked=False),
             "side_effect": SideEffect(entry.side_effect),
```

- [ ] **Step 4: Run them again, and the backend's static checks**

Run: the same tests. Expected: PASS, 57 passed (`test_display.py`'s 23, `test_titles.py`'s 34: node and path titles
unchanged). Then the backend's static checks of "How to run things": clean.

- [ ] **Step 5: Commit**

```bash
git add backend/src/dewpoint/plugins/mist backend/tests/plugins/mist/test_display.py backend/tests/plugins/mist/contract_hashes.json
git commit -m "feat(mist): each step's group, its config's widget and its settings' titles, as display metadata (4f-2a)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

Milestone 1 ends here: append `### 4f-2a, milestone 1 (<date>)` to the ledger (each task's commit, its red and green
as run, the static checks, mid-slice rulings, nothing pushed), commit it, and pause for the owner's review.

# Milestone 2 — The picker, and path ids

### Task 3: A step's group, and the drawer's line for it

**Spec:** §4.1; §5.10 (the drawer's header).

**Files:**
- Create: `frontend/src/lib/stepGroups.ts`, `frontend/src/lib/stepGroups.test.ts`,
  `frontend/src/routes/editor/drawer/StepDrawer.test.tsx`
- Modify: `frontend/src/routes/editor/drawer/StepDrawer.tsx` (the group's line), `frontend/src/test/nodeTypes.ts`
  (`GROUPED`: six made-up steps in three groups)

**Interfaces:**
- Consumes: `NodeType` (`lib/workflows.ts`); `typeWith` (`test/nodeTypes.ts`); `showDrawer`, `fakeApi` (the drawer's
  harness).
- Produces (`lib/stepGroups.ts`):
  - `type GroupKey = { plugin: string; title: string }`; `type StepGroup = GroupKey & { types: NodeType[] }`;
    `type Grouped = { plugins: { plugin: string; groups: StepGroup[] }[]; loose: NodeType[] }`;
  - `groupOf(type: NodeType): GroupKey | null` (both words non-blank strings, else null);
  - `grouped(types: NodeType[]): Grouped` (plugins by name, groups and their steps by title, the rest in order);
  - `actionWords(group: StepGroup): string`; `groupMatches(group: StepGroup, query: string): boolean`;
    `stepMatches(type: NodeType, query: string): boolean` (rulings 9, 10);
  - `GROUPED` (`test/nodeTypes.ts`): plugin "Acme"; "Org WLANs" (List, Create, Update, Delete), "Site WLANs" (List),
    "Site settings" (Update); each takes an `acme` connection.

- [ ] **Step 1: Write the failing tests**

Apply:

```diff
diff --git a/frontend/src/lib/stepGroups.test.ts b/frontend/src/lib/stepGroups.test.ts
new file mode 100644
index 00000000..a519a7da
--- /dev/null
+++ b/frontend/src/lib/stepGroups.test.ts
@@ -0,0 +1,64 @@
+// SPDX-License-Identifier: Apache-2.0
+import { describe, expect, it } from "vitest";
+import { GROUPED, IF, typeWith } from "../test/nodeTypes";
+import { actionWords, groupMatches, groupOf, grouped, stepMatches, type StepGroup } from "./stepGroups";
+
+const group = (title: string): StepGroup => grouped(GROUPED).plugins[0]!.groups.find((g) => g.title === title)!;
+
+describe("groupOf", () => {
+  it("reads the group at a config's root", () => {
+    expect(groupOf(GROUPED[0]!)).toEqual({ plugin: "Acme", title: "Org WLANs" });
+  });
+
+  it("finds none without one, or without its words", () => {
+    expect(groupOf(IF)).toBeNull();
+    expect(groupOf(typeWith({ "x-group": "Org WLANs" }))).toBeNull();
+    expect(groupOf(typeWith({ "x-group": { plugin: "Acme" } }))).toBeNull();
+    expect(groupOf(typeWith({ "x-group": { plugin: "Acme", title: " " } }))).toBeNull();
+  });
+});
+
+describe("grouped", () => {
+  it("puts a plugin's steps in its groups, each by title, and leaves the others in their order", () => {
+    const { plugins, loose } = grouped([IF, ...GROUPED]);
+    expect(loose).toEqual([IF]);
+    expect(plugins.map((p) => p.plugin)).toEqual(["Acme"]);
+    expect(plugins[0]!.groups.map((g) => g.title)).toEqual(["Org WLANs", "Site settings", "Site WLANs"]);
+    expect(plugins[0]!.groups[0]!.types.map((t) => t.title)).toEqual(["Create org WLAN", "Delete org WLAN", "List org WLANs", "Update org WLAN"]);
+  });
+});
+
+describe("actionWords", () => {
+  it("says what a group's steps do, by their titles' first words", () => {
+    expect(actionWords(group("Org WLANs"))).toBe("Create, Delete, List, Update");
+  });
+
+  it("cuts after six", () => {
+    const many = ["Arp", "Bounce", "Clear", "Get", "List", "Ping", "Restart"].map((w, i) => typeWith({}, { ref: `acme.d.${i}@1`, title: `${w} device` }));
+    expect(actionWords({ plugin: "Acme", title: "Devices", types: many })).toBe("Arp, Bounce, Clear, Get, List, Ping…");
+  });
+});
+
+describe("groupMatches", () => {
+  it("finds a group by each word typed, in its title or a step's ref", () => {
+    expect(groupMatches(group("Org WLANs"), "wlan")).toBe(true);
+    expect(groupMatches(group("Site WLANs"), "WLAN")).toBe(true);
+    expect(groupMatches(group("Site settings"), "wlan")).toBe(false);
+    expect(groupMatches(group("Org WLANs"), "org  wlan")).toBe(true);
+    expect(groupMatches(group("Site WLANs"), "org wlan")).toBe(false);
+    expect(groupMatches(group("Site settings"), "site_settings")).toBe(true);
+    expect(groupMatches(group("Org WLANs"), "  ")).toBe(false);
+  });
+});
+
+describe("stepMatches", () => {
+  const update = GROUPED[2]!;
+  it("finds a step when its title starts with what's typed, or when its ref holds a ref typed", () => {
+    expect(stepMatches(update, "update org wlan")).toBe(true);
+    expect(stepMatches(update, "Update  org")).toBe(true);
+    expect(stepMatches(update, "wlan")).toBe(false); // in its ref, but no ref was typed
+    expect(stepMatches(update, "org_wlans")).toBe(false);
+    expect(stepMatches(update, "acme.org_wlans.update")).toBe(true);
+    expect(stepMatches(update, "")).toBe(false);
+  });
+});
diff --git a/frontend/src/routes/editor/drawer/StepDrawer.test.tsx b/frontend/src/routes/editor/drawer/StepDrawer.test.tsx
new file mode 100644
index 00000000..23456f30
--- /dev/null
+++ b/frontend/src/routes/editor/drawer/StepDrawer.test.tsx
@@ -0,0 +1,19 @@
+// SPDX-License-Identifier: Apache-2.0
+import { screen } from "@testing-library/react";
+import { expect, it } from "vitest";
+import { GROUPED, REMOTE } from "../../../test/nodeTypes";
+import { fakeApi, showDrawer } from "./harness";
+
+it("names a step's group under its title", () => {
+  fakeApi({});
+  showDrawer(GROUPED[2]!);
+  expect(screen.getByText("Update org WLAN · acme.org_wlans.update@1")).toBeTruthy();
+  expect(screen.getByText("Acme · Org WLANs")).toBeTruthy();
+});
+
+it("names none for a step outside a group", () => {
+  fakeApi({ "GET /api/v1/t/t1/connections": () => new Response("[]", { headers: { "content-type": "application/json" } }) });
+  showDrawer(REMOTE);
+  expect(screen.getByText("Sites · acme.sites@1")).toBeTruthy();
+  expect(screen.queryByText(/^Acme · /)).toBeNull();
+});
diff --git a/frontend/src/test/nodeTypes.ts b/frontend/src/test/nodeTypes.ts
index 88172881..b4365402 100644
--- a/frontend/src/test/nodeTypes.ts
+++ b/frontend/src/test/nodeTypes.ts
@@ -96,6 +96,21 @@ export const REMOTE = typeWith({
   },
 }, { ref: "acme.sites@1", type: "acme.sites", title: "Sites", options: ["site_id"], credentials: ["acme"] });  // prettier-ignore
 
+/** A made-up plugin's steps in groups (4f-2: `x-group` at the config's root), as Mist's are by resource. */
+const inGroup = (ref: string, title: string, group: string, more: Partial<NodeType> = {}) =>
+  typeWith(
+    { type: "object", additionalProperties: false, properties: {}, "x-group": { plugin: "Acme", title: group } },
+    { ref, type: ref.split("@")[0], title, credentials: ["acme"], side_effect: "idempotent", ...more },
+  );
+export const GROUPED = [
+  inGroup("acme.org_wlans.list@1", "List org WLANs", "Org WLANs", { side_effect: "none" }),
+  inGroup("acme.org_wlans.create@1", "Create org WLAN", "Org WLANs", { side_effect: "ambiguous" }),
+  inGroup("acme.org_wlans.update@1", "Update org WLAN", "Org WLANs"),
+  inGroup("acme.org_wlans.delete@1", "Delete org WLAN", "Org WLANs"),
+  inGroup("acme.site_wlans.list@1", "List site WLANs", "Site WLANs", { side_effect: "none" }),
+  inGroup("acme.site_settings.update@1", "Update site settings", "Site settings"),
+];
+
 const MESSAGE_DEFS = {
   MessageField: {
     type: "object", additionalProperties: false, title: "MessageField", required: ["label", "value"],
```

- [ ] **Step 2: Run them**

Run: `npx --offline pnpm@12.6.0 exec vitest run src/lib/stepGroups.test.ts src/routes/editor/drawer/StepDrawer.test.tsx`
Expected: FAIL, 1 failed and 1 passed: `stepGroups.test.ts` can't import its module (`Failed to resolve import
"./stepGroups"`; none of its tests runs), and the drawer names no group (`Unable to find an element with the text: Acme
· Org WLANs`). "names none for a step outside a group" passes at once: it pins the header as it is.

- [ ] **Step 3: Implement the groups and the line**

Apply:

```diff
diff --git a/frontend/src/lib/stepGroups.ts b/frontend/src/lib/stepGroups.ts
new file mode 100644
index 00000000..12563c60
--- /dev/null
+++ b/frontend/src/lib/stepGroups.ts
@@ -0,0 +1,70 @@
+// SPDX-License-Identifier: Apache-2.0
+// The groups a plugin puts its steps in (4f-2, the Mist step design §4.1, §5.1): `x-group` at a config's root, a
+// display annotation outside the contract hash. The add-step picker shows a plugin's groups instead of its steps (Mist's
+// 85 resources, not its 294 steps); the drawer names a step's group under its title.
+import type { NodeType } from "./workflows";
+
+export type GroupKey = { plugin: string; title: string };
+/** A plugin's group and its steps, by title. */
+export type StepGroup = GroupKey & { types: NodeType[] };
+/** The steps offered: each plugin's groups, by title, and the steps no group holds, in the order given. */
+export type Grouped = { plugins: { plugin: string; groups: StepGroup[] }[]; loose: NodeType[] };
+
+const WORDS_SHOWN = 6;
+
+const byTitle = (a: { title: string }, b: { title: string }) => a.title.localeCompare(b.title);
+const normal = (text: string) => text.trim().toLowerCase().replace(/\s+/g, " ");
+
+/** A step's group, when its config's root names one with words. */
+export function groupOf(type: NodeType): GroupKey | null {
+  const group = (type.config_schema as Record<string, unknown>)["x-group"];
+  if (typeof group !== "object" || group === null) return null;
+  const { plugin, title } = group as Record<string, unknown>;
+  return typeof plugin === "string" && plugin.trim() !== "" && typeof title === "string" && title.trim() !== ""
+    ? { plugin, title }
+    : null;
+}
+
+export function grouped(types: NodeType[]): Grouped {
+  const plugins = new Map<string, Map<string, NodeType[]>>();
+  const loose: NodeType[] = [];
+  for (const type of types) {
+    const group = groupOf(type);
+    if (group === null) {
+      loose.push(type);
+      continue;
+    }
+    const groups = plugins.get(group.plugin) ?? new Map<string, NodeType[]>();
+    plugins.set(group.plugin, groups);
+    groups.set(group.title, [...(groups.get(group.title) ?? []), type]);
+  }
+  return {
+    plugins: [...plugins]
+      .map(([plugin, groups]) => ({
+        plugin,
+        groups: [...groups].map(([title, members]) => ({ plugin, title, types: [...members].sort(byTitle) })).sort(byTitle),
+      }))
+      .sort((a, b) => a.plugin.localeCompare(b.plugin)),
+    loose,
+  };
+}
+
+/** What a group's steps do, by their titles' first words, each once: "Create, Delete, Get, List, Update". */
+export function actionWords(group: StepGroup): string {
+  const words = [...new Set(group.types.map((t) => t.title.split(" ")[0]!).filter((w) => w !== ""))];
+  return words.length > WORDS_SHOWN ? `${words.slice(0, WORDS_SHOWN).join(", ")}…` : words.join(", ");
+}
+
+/** A group is found by each word typed, in its title or in one of its steps' refs ("wlan", "site_settings"). */
+export function groupMatches(group: StepGroup, query: string): boolean {
+  const words = normal(query).split(" ").filter((w) => w !== "");
+  const title = group.title.toLowerCase();
+  return words.length > 0 && words.every((w) => title.includes(w) || group.types.some((t) => t.ref.toLowerCase().includes(w)));
+}
+
+/** A grouped step is found by itself when its title starts with what's typed, or when a ref is typed (it has a dot) and
+ * its ref holds it: "wlan" alone finds the groups, not every WLAN step. */
+export function stepMatches(type: NodeType, query: string): boolean {
+  const q = normal(query);
+  return q !== "" && (type.title.toLowerCase().startsWith(q) || (q.includes(".") && type.ref.toLowerCase().includes(q)));
+}
diff --git a/frontend/src/routes/editor/drawer/StepDrawer.tsx b/frontend/src/routes/editor/drawer/StepDrawer.tsx
index 19e4f1ba..e6594f81 100644
--- a/frontend/src/routes/editor/drawer/StepDrawer.tsx
+++ b/frontend/src/routes/editor/drawer/StepDrawer.tsx
@@ -10,6 +10,7 @@ import { Button } from "../../../components/Button";
 import { Tabs } from "../../../components/Tabs";
 import { optionsLine, targetOf } from "../../../lib/composer";
 import { fieldsOf, settingsOf, type FieldSpec } from "../../../lib/schemaForm";
+import { groupOf } from "../../../lib/stepGroups";
 import type { UnappliedKind } from "../../../lib/unapplied";
 import type { Diagnostic, Expression, GraphNode, NodeType } from "../../../lib/workflows";
 import type { ItemAction } from "../items";
@@ -111,6 +112,7 @@ export function StepDrawer({
     if (!focusField) heading.current?.focus();
   }, [node.id]);
   const fields = useMemo(() => (type ? fieldsOf(type) : []), [type]);
+  const group = type ? groupOf(type) : null; // its plugin's group: "Mist · Site settings" (4f-2)
   const { setup, message, options } = type ? settingsOf(type, fields) : { setup: [], message: null, options: [] };
   const onSetup = [...setup, ...(message ?? [])]; // what Setup shows: a message's parts too
   const [tab, setTab] = useState<Tab>(result ? "result" : test && testAt ? "test" : onSetup.length > 0 ? "setup" : "options");
@@ -211,6 +213,7 @@ export function StepDrawer({
             <KeyField onRenamed={() => requestAnimationFrame(() => heading.current?.focus())} />
             {note !== null && <p role="status" className="text-small">{note}</p>}
             <p className="text-small text-muted">{type ? `${type.title} · ${type.ref}` : `Unknown step type ${node.type}`}</p>
+            {group && <p className="text-small text-muted">{`${group.plugin} · ${group.title}`}</p>}
             {type && (
               <p className="text-small text-muted">
                 {type.kind === "control" ? "Runs in the engine" : `Runs as its own step · ${EFFECTS[type.side_effect]}`}
```

- [ ] **Step 4: Run them again, and the static checks**

Run: the same tests. Expected: PASS, 9 passed. Then the frontend's static checks: no output.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/stepGroups.ts frontend/src/lib/stepGroups.test.ts frontend/src/routes/editor/drawer/StepDrawer.tsx frontend/src/routes/editor/drawer/StepDrawer.test.tsx frontend/src/test/nodeTypes.ts
git commit -m "feat(editor): a step's group, read from its config, named under the drawer's title (4f-2a)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: The picker: Mist as its resources, then a resource's actions

**Spec:** §5.1; §3.4 (labels carry their scope); §5.11 (320 px).

**Files:**
- Modify: `frontend/src/routes/editor/StepPicker.tsx`, `frontend/src/routes/editor/StepPicker.test.tsx`

**Interfaces:**
- Consumes: Task 3's `grouped`, `actionWords`, `groupMatches`, `stepMatches`, `StepGroup`, `GROUPED`;
  `connectionTypesQuery` (`routes/editor/drawer/pickers.tsx`); cmdk's `Command` and `defaultFilter`.
- Produces: `StepPicker`'s props unchanged (`mode`, `types`, `onPick`, `onConnect`, `onClose`); it now needs a
  `QueryClient` above it, as the editor has.

The picker filters what it shows itself (`shouldFilter={false}`): Flow and Actions as before, ranked by cmdk's own
score; each plugin's groups between them; a group's view in place of the list. Its tests render it under a
`QueryClientProvider` and fake the API (`fakeApi`), so the connection types are read or refused as the test says.

- [ ] **Step 1: Write the failing tests**

Apply:

```diff
diff --git a/frontend/src/routes/editor/StepPicker.test.tsx b/frontend/src/routes/editor/StepPicker.test.tsx
index ec2bcb33..be469e93 100644
--- a/frontend/src/routes/editor/StepPicker.test.tsx
+++ b/frontend/src/routes/editor/StepPicker.test.tsx
@@ -1,8 +1,15 @@
 // SPDX-License-Identifier: Apache-2.0
-import { render, screen } from "@testing-library/react";
+import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
+import { render, screen, within } from "@testing-library/react";
 import userEvent from "@testing-library/user-event";
-import { expect, it, vi } from "vitest";
-import { StepPicker } from "./StepPicker";
+import { afterEach, expect, it, vi } from "vitest";
+import { GROUPED, IF, typeWith } from "../../test/nodeTypes";
+import { fakeApi, json } from "./drawer/harness";
+import { StepPicker, type PickMode } from "./StepPicker";
+
+afterEach(() => {
+  vi.restoreAllMocks();
+});
 
 const t = (ref: string, kind: "control" | "action", ports: string[], extra = {}) => ({
   ref, type: ref.split("@")[0], version: 1, kind, state: "active", title: ref.split("@")[0]!.split(".").pop(), description: `does ${ref}`,
@@ -16,29 +23,103 @@ const TYPES = [
   t("testkit.http_call@1", "action", ["out"], { side_effect: "idempotent", credentials: ["testkit"] }),
 ];
 const EDGE = { from: { node: "a", port: "out" }, to: { node: "b" } };
+const AFTER: PickMode = { kind: "after", from: { node: "a", port: "out" } };
+const KINDS = "GET /api/v1/connection-types";
+
+function show(mode: PickMode, types: unknown[], more: { onPick?: () => void; onConnect?: () => void } = {}) {
+  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
+  render(
+    <QueryClientProvider client={client}>
+      <StepPicker mode={mode} types={types as never} onPick={more.onPick ?? vi.fn()} onConnect={more.onConnect} onClose={vi.fn()} />
+    </QueryClientProvider>,
+  );
+}
 
 it("offers every active type after a port, in Flow and Actions, with what an action changes and needs", async () => {
+  fakeApi({});
   const onPick = vi.fn();
-  render(<StepPicker mode={{ kind: "after", from: { node: "a", port: "out" } }} types={TYPES} onPick={onPick} onConnect={vi.fn()} onClose={vi.fn()} />);
+  show(AFTER, TYPES, { onPick, onConnect: vi.fn() });
   expect(screen.getByRole("dialog", { name: "Add a step" })).toBeTruthy();
   expect(screen.queryByRole("option", { name: /flow\.old@1/ })).toBeNull(); // deprecated: new versions shouldn't use it
   const call = screen.getByRole("option", { name: /testkit\.http_call@1/ });
   expect(call.textContent).toContain("Changes things; safe to repeat");
-  expect(call.textContent).toContain("Uses a testkit connection");
+  expect(call.textContent).toContain("Uses a testkit connection"); // its type's label unknown: its key
   await userEvent.click(screen.getByRole("option", { name: /flow\.if@1/ }));
   expect(onPick).toHaveBeenCalledWith(TYPES[1]);
 });
 
+it("names a step's connection by its type's label", async () => {
+  fakeApi({ [KINDS]: () => json([{ key: "testkit", label: "Test Kit", config_schema: {}, secret_fields: [], clouds: null }]) });
+  show(AFTER, TYPES);
+  const call = screen.getByRole("option", { name: /testkit\.http_call@1/ });
+  await vi.waitFor(() => expect(call.textContent).toContain("Uses a Test Kit connection"));
+});
+
 it("offers only steps that continue the flow mid-edge, and says why", () => {
-  render(<StepPicker mode={{ kind: "insert", edge: EDGE }} types={TYPES} onPick={vi.fn()} onClose={vi.fn()} />);
+  fakeApi({});
+  show({ kind: "insert", edge: EDGE }, TYPES);
   expect(screen.queryByRole("option", { name: /flow\.if@1/ })).toBeNull();
   expect(screen.getByRole("option", { name: /flow\.transform@1/ })).toBeTruthy();
   expect(screen.getByText("Only steps that continue the flow can go here.")).toBeTruthy();
 });
 
 it("offers to connect an existing step instead, after a port", async () => {
+  fakeApi({});
   const onConnect = vi.fn();
-  render(<StepPicker mode={{ kind: "after", from: { node: "a", port: "out" } }} types={TYPES} onPick={vi.fn()} onConnect={onConnect} onClose={vi.fn()} />);
+  show(AFTER, TYPES, { onConnect });
   await userEvent.click(screen.getByRole("option", { name: "Connect to an existing step…" }));
   expect(onConnect).toHaveBeenCalled();
 });
+
+it("shows a plugin's groups in place of its steps, with how many and what they do", () => {
+  fakeApi({});
+  show(AFTER, [IF, ...GROUPED]);
+  expect(screen.getByText("Acme: 3 resources, type to find one")).toBeTruthy();
+  expect(screen.getByPlaceholderText("Type a step's name or a Acme resource")).toBeTruthy();
+  const wlans = screen.getByRole("option", { name: /^Org WLANs/ });
+  expect(wlans.textContent).toContain("4 actions");
+  expect(wlans.textContent).toContain("Create, Delete, List, Update");
+  expect(screen.getAllByRole("option").map((o) => o.textContent?.split(/\d+ actions?|flow\./)[0])).toEqual(["If", "Org WLANs", "Site settings", "Site WLANs"]);
+  expect(screen.queryByRole("option", { name: /Update org WLAN/ })).toBeNull();
+});
+
+it("finds groups by each word typed, and a step by the start of its title", async () => {
+  fakeApi({});
+  show(AFTER, [IF, ...GROUPED]);
+  const search = screen.getByRole("combobox");
+  await userEvent.type(search, "wlan");
+  expect(screen.getAllByRole("option").map((o) => o.textContent?.split(/\d+ actions?/)[0])).toEqual(["Org WLANs", "Site WLANs"]);
+  expect(screen.getByText("Acme resources")).toBeTruthy();
+  await userEvent.clear(search);
+  await userEvent.type(search, "update org wlan");
+  const step = within(screen.getByRole("group", { name: "Acme step" })).getByRole("option");
+  expect(step.textContent).toContain("Update org WLAN");
+  expect(within(screen.getByRole("group", { name: "Acme resources" })).getByRole("option", { name: /^Org WLANs/ })).toBeTruthy();
+});
+
+it("leaves out a group mid-edge when none of its steps continues the flow", () => {
+  fakeApi({});
+  const ends = typeWith({ "x-group": { plugin: "Acme", title: "Org alarms" } }, { ref: "acme.org_alarms.ack@1", title: "Ack org alarm", ports: [] });
+  show({ kind: "insert", edge: EDGE }, [...GROUPED, ends]);
+  expect(screen.getByText("Acme: 3 resources, type to find one")).toBeTruthy();
+  expect(screen.queryByRole("option", { name: /^Org alarms/ })).toBeNull();
+});
+
+it("opens a group's steps by title, and goes back with Back or Backspace", async () => {
+  fakeApi({});
+  const onPick = vi.fn();
+  show(AFTER, [IF, ...GROUPED], { onPick });
+  await userEvent.click(screen.getByRole("option", { name: /^Org WLANs/ }));
+  expect(screen.getByRole("dialog", { name: "Add a step: Org WLANs" })).toBeTruthy();
+  expect(screen.getAllByRole("option").map((o) => o.textContent?.split("acme.")[0])).toEqual(["Create org WLAN", "Delete org WLAN", "List org WLANs", "Update org WLAN"]);
+  await userEvent.click(screen.getByRole("button", { name: "Back to every step" }));
+  expect(screen.getByRole("dialog", { name: "Add a step" })).toBeTruthy();
+  await userEvent.click(screen.getByRole("option", { name: /^Org WLANs/ }));
+  await userEvent.type(screen.getByRole("combobox"), "u{Backspace}"); // a character typed goes first, the group stays
+  expect(screen.getByRole("dialog", { name: "Add a step: Org WLANs" })).toBeTruthy();
+  await userEvent.keyboard("{Backspace}");
+  expect(screen.getByRole("dialog", { name: "Add a step" })).toBeTruthy();
+  await userEvent.click(screen.getByRole("option", { name: /^Org WLANs/ }));
+  await userEvent.type(screen.getByRole("combobox"), "upd{Enter}");
+  expect(onPick).toHaveBeenCalledWith(GROUPED[2]);
+});
```

- [ ] **Step 2: Run them**

Run: `npx --offline pnpm@12.6.0 exec vitest run src/routes/editor/StepPicker.test.tsx`
Expected: FAIL, 5 failed and 3 passed: no group is shown (`Unable to find an element with the text: Acme: 3 resources,
type to find one`, two tests; `Unable to find an accessible element with the role "option" and name /^Org WLANs/`),
typing "wlan" lists the steps (`expected [ …(5) ] to deeply equal [ 'Org WLANs', 'Site WLANs' ]`), and a connection is
named by its key (`expected '…' to contain 'Uses a Test Kit connection'`). The three tests of Flow, Actions, mid-edge
and Connect pass at once: they pin the picker as it was.

- [ ] **Step 3: Implement the picker**

Apply:

```diff
diff --git a/frontend/src/routes/editor/StepPicker.tsx b/frontend/src/routes/editor/StepPicker.tsx
index 20c169cf..60d517ae 100644
--- a/frontend/src/routes/editor/StepPicker.tsx
+++ b/frontend/src/routes/editor/StepPicker.tsx
@@ -1,12 +1,18 @@
 // SPDX-License-Identifier: Apache-2.0
 // Choosing a step's type (`A`, and every "+"): a native modal dialog around cmdk, as the palette (D23). Only active
 // types: a deprecated one stays drawn where it's used, but new versions shouldn't add it. Mid-edge, only types that
-// continue the flow (4b ruling 10).
-import { Command } from "cmdk";
-import { useEffect, useRef } from "react";
+// continue the flow (4b ruling 10). A plugin's steps in groups show as their groups (4f-2, the Mist step design §5.1:
+// Mist as its 85 resources, not its 294 steps); a group chosen lists its steps, and Back (or Backspace in the empty
+// search) returns. What's shown is filtered here, not by cmdk: a group, and a grouped step, match by their own rules.
+import { useQuery } from "@tanstack/react-query";
+import { Command, defaultFilter } from "cmdk";
+import { Fragment, useEffect, useRef, useState } from "react";
+import { Button } from "../../components/Button";
 import { PALETTE_GROUP, PALETTE_ITEM } from "../../components/CommandPalette";
 import { continuationPort, type PortRef } from "../../lib/graph";
+import { actionWords, groupMatches, grouped, stepMatches, type StepGroup } from "../../lib/stepGroups";
 import type { GraphEdge, NodeType } from "../../lib/workflows";
+import { connectionTypesQuery } from "./drawer/pickers";
 
 export type PickMode = { kind: "after"; from: PortRef | null } | { kind: "insert"; edge: GraphEdge } | { kind: "before"; entry: string };
 
@@ -18,10 +24,21 @@ const EFFECTS: Record<NodeType["side_effect"], string> = {
   ambiguous: "Changes things; a retry may repeat it",
 };
 
-function Choice({ type, onSelect }: { type: NodeType; onSelect: () => void }) {
+/** cmdk's own search, for what no group holds: its score, best first; nothing typed keeps the order given. */
+function ranked(types: NodeType[], query: string): NodeType[] {
+  if (query.trim() === "") return types;
+  return types
+    .map((type, i) => ({ type, i, score: defaultFilter(`${type.title} ${type.ref}`, query) }))
+    .filter((x) => x.score > 0)
+    .sort((a, b) => b.score - a.score || a.i - b.i)
+    .map((x) => x.type);
+}
+
+function Choice({ type, labels, onSelect }: { type: NodeType; labels: ReadonlyMap<string, string>; onSelect: () => void }) {
   return (
-    <Command.Item value={`${type.title} ${type.ref}`} onSelect={onSelect} className={`${PALETTE_ITEM} flex-col items-start`}>
-      <span className="flex w-full items-baseline justify-between gap-3">
+    <Command.Item value={type.ref} onSelect={onSelect} className={`${PALETTE_ITEM} flex-col items-start`}>
+      {/* At 320 px its ref goes under its title. */}
+      <span className="flex w-full flex-wrap items-baseline justify-between gap-x-3">
         <span className="font-medium">{type.title}</span>
         <span className="font-mono text-meta text-muted">{type.ref}</span>
       </span>
@@ -29,68 +46,152 @@ function Choice({ type, onSelect }: { type: NodeType; onSelect: () => void }) {
       {type.kind === "action" && (
         <span className="text-small text-muted">
           {EFFECTS[type.side_effect]}
-          {type.credentials.map((c) => `. Uses a ${c} connection`).join("")}
+          {/* Named by its label ("Mist"), never its key (4f-2, as 4f-1's connection words). */}
+          {type.credentials.map((c) => `. Uses a ${labels.get(c) ?? c} connection`).join("")}
         </span>
       )}
     </Command.Item>
   );
 }
 
+function GroupChoice({ group, onSelect }: { group: StepGroup; onSelect: () => void }) {
+  const count = group.types.length === 1 ? "1 action" : `${group.types.length} actions`;
+  return (
+    <Command.Item value={`group ${group.plugin} ${group.title}`} onSelect={onSelect} className={`${PALETTE_ITEM} flex-col items-start`}>
+      <span className="flex w-full items-baseline justify-between gap-3">
+        <span className="font-medium">{group.title}</span>
+        <span className="font-mono text-meta text-muted">{count}</span>
+      </span>
+      <span className="text-small text-muted">{actionWords(group)}</span>
+    </Command.Item>
+  );
+}
+
 export function StepPicker({
   mode, types, onPick, onConnect, onClose,
 }: { mode: PickMode; types: NodeType[]; onPick: (type: NodeType) => void; onConnect?: () => void; onClose: () => void }) {  // prettier-ignore
   const dialog = useRef<HTMLDialogElement>(null);
+  const input = useRef<HTMLInputElement>(null);
+  const [query, setQuery] = useState("");
+  const [open, setOpen] = useState<StepGroup | null>(null);
+  const [selected, setSelected] = useState("");
   useEffect(() => {
     const d = dialog.current;
     if (d && !d.open) {
       d.showModal();
-      d.querySelector<HTMLInputElement>("[cmdk-input]")?.focus();
+      input.current?.focus();
     }
   }, []);
   const continuing = mode.kind !== "after";
   const offered = types.filter((t) => t.state === "active" && (!continuing || continuationPort(t) !== null));
+  const { plugins, loose } = grouped(offered);
+  const takes = offered.some((t) => t.credentials.length > 0);
+  const kinds = useQuery({ ...connectionTypesQuery(), enabled: takes });
+  const labels = new Map((kinds.data ?? []).map((k) => [k.key, k.label]));
   const pick = (type: NodeType) => {
     dialog.current?.close();
     onPick(type);
   };
+  const enter = (group: StepGroup) => {
+    setOpen(group);
+    setQuery("");
+    setSelected("");
+    input.current?.focus();
+  };
+  const back = () => {
+    if (open !== null) setSelected(`group ${open.plugin} ${open.title}`);
+    setOpen(null);
+    setQuery("");
+    input.current?.focus();
+  };
+  const typed = query.trim() !== "";
+  const flow = ranked(loose.filter((t) => t.kind === "control"), query);
+  const actions = ranked(loose.filter((t) => t.kind === "action"), query);
+  const plural = plugins.map((p) => p.plugin).join(" or ");
   return (
     <dialog
       ref={dialog}
-      aria-label="Add a step"
+      aria-label={open ? `Add a step: ${open.title}` : "Add a step"}
       onClose={onClose}
       className="mx-auto mt-20 w-[560px] max-w-[calc(100vw-32px)] rounded-dialog border border-line bg-surface p-0 text-ink shadow-dialog backdrop:bg-overlay"
     >
-      <Command label="Add a step" loop>
+      <Command label="Add a step" loop shouldFilter={false} value={selected} onValueChange={setSelected}>
+        {open && (
+          <div className="flex items-center gap-3 border-b border-line px-3 py-2">
+            <Button size="sm" aria-label="Back to every step" className="max-sm:min-h-[44px]" onClick={back}>← Back</Button>
+            <span className="text-small">
+              {open.plugin} · <strong className="font-semibold">{open.title}</strong>
+            </span>
+          </div>
+        )}
         <Command.Input
-          placeholder="Type a step's name"
-          className="w-full rounded-t-dialog border-b border-line bg-transparent px-4 py-3 text-body-lg text-ink placeholder:text-muted focus-visible:-outline-offset-2"
+          ref={input}
+          value={query}
+          onValueChange={setQuery}
+          onKeyDown={(e) => {
+            if (e.key === "Backspace" && query === "" && open !== null) {
+              e.preventDefault();
+              back();
+            }
+          }}
+          placeholder={open ? "Type an action's name" : plugins.length > 0 ? `Type a step's name or a ${plural} resource` : "Type a step's name"}
+          className="w-full border-b border-line bg-transparent px-4 py-3 text-body-lg text-ink placeholder:text-muted focus-visible:-outline-offset-2 [&:first-child]:rounded-t-dialog"
         />
         <Command.List className="max-h-96 overflow-y-auto p-1">
           {continuing && <p className="px-3 pt-2 text-small text-muted">Only steps that continue the flow can go here.</p>}
           <Command.Empty className="px-3 py-2 text-body text-muted">No step type matches.</Command.Empty>
-          {offered.some((t) => t.kind === "control") && (
-            <Command.Group heading="Flow" className={PALETTE_GROUP}>
-              {offered.filter((t) => t.kind === "control").map((t) => <Choice key={t.ref} type={t} onSelect={() => pick(t)} />)}
-            </Command.Group>
-          )}
-          {offered.some((t) => t.kind === "action") && (
-            <Command.Group heading="Actions" className={PALETTE_GROUP}>
-              {offered.filter((t) => t.kind === "action").map((t) => <Choice key={t.ref} type={t} onSelect={() => pick(t)} />)}
-            </Command.Group>
-          )}
-          {mode.kind === "after" && mode.from && onConnect && (
-            <Command.Group heading="Or" className={PALETTE_GROUP}>
-              <Command.Item
-                value="Connect to an existing step…"
-                className={PALETTE_ITEM}
-                onSelect={() => {
-                  dialog.current?.close();
-                  onConnect();
-                }}
-              >
-                Connect to an existing step…
-              </Command.Item>
+          {open ? (
+            <Command.Group heading={open.title} className={PALETTE_GROUP}>
+              {ranked(open.types, query).map((t) => <Choice key={t.ref} type={t} labels={labels} onSelect={() => pick(t)} />)}
             </Command.Group>
+          ) : (
+            <>
+              {flow.length > 0 && (
+                <Command.Group heading="Flow" className={PALETTE_GROUP}>
+                  {flow.map((t) => <Choice key={t.ref} type={t} labels={labels} onSelect={() => pick(t)} />)}
+                </Command.Group>
+              )}
+              {plugins.map(({ plugin, groups }) => {
+                const steps = typed ? groups.flatMap((g) => g.types).filter((t) => stepMatches(t, query)).sort((a, b) => a.title.localeCompare(b.title)) : [];
+                const found = typed ? groups.filter((g) => groupMatches(g, query)) : groups;
+                return (
+                  <Fragment key={plugin}>
+                    {steps.length > 0 && (
+                      <Command.Group heading={steps.length === 1 ? `${plugin} step` : `${plugin} steps`} className={PALETTE_GROUP}>
+                        {steps.map((t) => <Choice key={t.ref} type={t} labels={labels} onSelect={() => pick(t)} />)}
+                      </Command.Group>
+                    )}
+                    {found.length > 0 && (
+                      <Command.Group
+                        heading={typed ? `${plugin} resources` : `${plugin}: ${groups.length} resources, type to find one`}
+                        className={PALETTE_GROUP}
+                      >
+                        {found.map((g) => <GroupChoice key={g.title} group={g} onSelect={() => enter(g)} />)}
+                      </Command.Group>
+                    )}
+                  </Fragment>
+                );
+              })}
+              {actions.length > 0 && (
+                <Command.Group heading="Actions" className={PALETTE_GROUP}>
+                  {actions.map((t) => <Choice key={t.ref} type={t} labels={labels} onSelect={() => pick(t)} />)}
+                </Command.Group>
+              )}
+              {mode.kind === "after" && mode.from && onConnect && (!typed || defaultFilter("Connect to an existing step…", query) > 0) && (
+                <Command.Group heading="Or" className={PALETTE_GROUP}>
+                  <Command.Item
+                    value="Connect to an existing step…"
+                    className={PALETTE_ITEM}
+                    onSelect={() => {
+                      dialog.current?.close();
+                      onConnect();
+                    }}
+                  >
+                    Connect to an existing step…
+                  </Command.Item>
+                </Command.Group>
+              )}
+            </>
           )}
         </Command.List>
       </Command>
```

- [ ] **Step 4: Run them again, the editor's tests, and the static checks**

Run: the same tests, then `npx --offline pnpm@12.6.0 exec vitest run src/routes/editor/Editor.test.tsx` (the editor
mounts the picker). Expected: PASS, 8 passed; the editor's 169 passed. Then the frontend's static checks: no output.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/routes/editor/StepPicker.tsx frontend/src/routes/editor/StepPicker.test.tsx
git commit -m "feat(editor): the add-step picker shows a plugin's groups, then a group's steps (4f-2a)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: A path id takes values, and lists its choices under it

**Spec:** §5.2 (ruling 127 amended); §5.11.

**Files:**
- Modify: `frontend/src/lib/schemaForm.ts` (`takesPills`), `frontend/src/lib/schemaForm.test.ts`,
  `frontend/src/routes/editor/drawer/LiveOptions.tsx`, `frontend/src/routes/editor/drawer/LiveOptions.test.tsx`,
  `frontend/src/routes/editor/drawer/FieldView.tsx` (the choices under a field with pills; `CHOICES_NOTE`)

**Interfaces:**
- Consumes: `segmentsOf` (`lib/pills.ts`); `FieldView`'s `write`-family and `refocus`; `REMOTE` (`test/nodeTypes.ts`,
  whose `site_id` has live choices); `showFields`, `fakeApi`, `json` (the drawer's harness).
- Produces:
  - `takesPills(f)` is true for the "options" widget too (a literal-only field still false);
  - `LiveOptions.tsx`: `ChoicesBelow({ spec, query, current, disabled, onPick, onDone })`, where
    `onPick(value: string) => string | null` writes and says why it couldn't, and `onDone()` is called after a pick
    or Escape; `OptionsControl` keeps its props (`ControlProps`);
  - `FieldView.tsx`: `CHOICES_NOTE`.

Loading stays what it was (one hook, `useChoices`, for both fields: scope, era, the connection's revision, the API's
reasons); what changes is where the choices go (a listbox under the field) and that a pick is named while the field
holds it. In a field with pills, the pick is written as the field's text, what a refused write held is released, and
the pill editor is redrawn from the new value.

- [ ] **Step 1: Write the failing tests**

Apply:

```diff
diff --git a/frontend/src/lib/schemaForm.test.ts b/frontend/src/lib/schemaForm.test.ts
index 2149b37a..d04c306a 100644
--- a/frontend/src/lib/schemaForm.test.ts
+++ b/frontend/src/lib/schemaForm.test.ts
@@ -159,6 +159,13 @@ describe("4c-2b's field kinds", () => {
     });
     expect([text, secret, choice, cel, refs, plain].map((f) => takesPills(f!))).toEqual([true, false, false, false, true, false]);
   });
+  it("takes data pills in a field with live choices (4f-2), never a literal-only one", () => {
+    const type = typeWith(
+      { type: "object", properties: { site: { type: "string" }, fixed: { type: "string", "x-dewpoint-literal": true } } },
+      { options: ["site", "fixed"] },
+    );
+    expect(fieldsOf(type).map((f) => [f.widget, takesPills(f)])).toEqual([["options", true], ["options", false]]);
+  });
   it("labels a field by its parts' labels", () => {
     expect(fieldLabel(SWITCH, "/cases/1/when")).toBe("Cases, item 2 › Condition");
     expect(fieldLabel(IF, "/condition")).toBe("Condition");
diff --git a/frontend/src/routes/editor/drawer/LiveOptions.test.tsx b/frontend/src/routes/editor/drawer/LiveOptions.test.tsx
index a7e882e3..6fd5a451 100644
--- a/frontend/src/routes/editor/drawer/LiveOptions.test.tsx
+++ b/frontend/src/routes/editor/drawer/LiveOptions.test.tsx
@@ -1,5 +1,5 @@
 // SPDX-License-Identifier: Apache-2.0
-import { act, screen } from "@testing-library/react";
+import { act, screen, within } from "@testing-library/react";
 import userEvent from "@testing-library/user-event";
 import { afterEach, expect, it, vi } from "vitest";
 import { literal } from "../../../lib/config";
@@ -42,9 +42,9 @@ it("loads the choices on request, with the connection and the text typed, and se
   await screen.findByRole("option", { name: "Prod · verified" }); // its revision known: the scope is settled
   await userEvent.type(screen.getByLabelText("Site"), "h");
   await userEvent.click(screen.getByRole("button", { name: "Show choices: Site" }));
-  const choices = await screen.findByLabelText<HTMLSelectElement>("Choices for Site");
+  const choices = await screen.findByRole("listbox", { name: "Choices for Site" });
   expect(sent.find((r) => r.path.endsWith("/options"))!.body).toEqual({ field: "site_id", connection_id: C1, query: "h" });
-  await userEvent.selectOptions(choices, "HQ (s1)");
+  await userEvent.click(within(choices).getByRole("option", { name: /^HQ/ }));
   expect(config().site_id).toBe("s1");
 });
 
@@ -113,7 +113,7 @@ it("releases text a write turned away once a choice is written", async () => {
   await userEvent.type(screen.getByLabelText("Site"), "old-text"); // held, never written
   refuse(null);
   await userEvent.click(screen.getByRole("button", { name: "Show choices: Site" }));
-  await userEvent.selectOptions(await screen.findByLabelText("Choices for Site"), "HQ (s1)");
+  await userEvent.click(within(await screen.findByRole("listbox", { name: "Choices for Site" })).getByRole("option", { name: /^HQ/ }));
   expect(config().site_id).toBe("s1");
   expect(screen.getByLabelText<HTMLInputElement>("Site").value).toBe("s1");
   expect(held()).toEqual([]);
@@ -148,3 +148,67 @@ it("names each Show choices button by its field, its visible text first (#73)",
   expect(buttons.map((b) => b.getAttribute("aria-label"))).toEqual(["Show choices: Site", "Show choices: Device"]);
   expect(buttons.map((b) => b.textContent)).toEqual(["Show choices", "Show choices"]);
 });
+
+const ID = "5c1e0b1a-3f7d-4a1e-9b8c-2d4e6f8a0b1c";
+const sites = () => json({ options: [{ value: ID, label: "HQ Paris" }, { value: "s2", label: "Lab" }] });
+
+it("takes a value from an earlier step, and then asks for every choice", async () => {
+  const sent = fakeApi({ [CONNECTIONS]: both, [OPTIONS]: sites });
+  const site = { $value: { kind: "template", parts: [{ ref: "steps.get_site.output.id" }] } };
+  const { config } = showFields(REMOTE, { config: { connection: C1, site_id: site } });
+  await screen.findByRole("option", { name: "Prod · verified" });
+  const field = within(document.querySelector<HTMLElement>('[data-pointer="/site_id"]')!);
+  expect(field.getByRole("button", { name: "Text" }).getAttribute("aria-pressed")).toBe("true");
+  expect(field.getByRole("button", { name: "＋ Data" })).toBeTruthy();
+  expect(screen.getByText(/A value from an earlier step, or one of the connection's choices: Show choices lists them\./)).toBeTruthy();
+  await userEvent.click(screen.getByRole("button", { name: "Show choices: Site" }));
+  const list = await screen.findByRole("listbox", { name: "Choices for Site" });
+  expect(sent.find((r) => r.path.endsWith("/options"))!.body).toEqual({ field: "site_id", connection_id: C1, query: "" });
+  await userEvent.click(within(list).getByRole("option", { name: /^HQ Paris/ }));
+  expect(config().site_id).toBe(ID); // the pick replaces the value from the step
+});
+
+it("shows a choice known only by its id once", async () => {
+  fakeApi({ [CONNECTIONS]: both, [OPTIONS]: () => json({ options: [{ value: "s9", label: "s9" }] }) });
+  showFields(REMOTE, { config: { connection: C1 } });
+  await screen.findByRole("option", { name: "Prod · verified" });
+  await userEvent.click(screen.getByRole("button", { name: "Show choices: Site" }));
+  const list = await screen.findByRole("listbox", { name: "Choices for Site" });
+  expect(within(list).getByRole("option").textContent).toBe("s9");
+  expect(screen.getByRole("status").textContent).toBe("1 choice");
+});
+
+it("shows each choice's name and the start of its id, and names a pick until the value changes", async () => {
+  fakeApi({ [CONNECTIONS]: both, [OPTIONS]: sites });
+  const { config } = showFields(REMOTE, { config: { connection: C1 } });
+  await screen.findByRole("option", { name: "Prod · verified" });
+  await userEvent.click(screen.getByRole("button", { name: "Show choices: Site" }));
+  const list = await screen.findByRole("listbox", { name: "Choices for Site" });
+  expect(screen.getByRole("status").textContent).toBe("2 choices");
+  const hq = within(list).getByRole("option", { name: /^HQ Paris/ });
+  expect(hq.textContent).toBe("HQ Paris5c1e0b1a…");
+  await userEvent.click(hq);
+  expect(config().site_id).toBe(ID);
+  expect(screen.queryByRole("listbox")).toBeNull();
+  expect(screen.getByText("HQ Paris, picked from the choices.")).toBeTruthy();
+  await userEvent.type(screen.getByLabelText("Site"), "x");
+  expect(screen.queryByText("HQ Paris, picked from the choices.")).toBeNull();
+});
+
+it("moves through the choices by keyboard, and Escape closes them without a pick", async () => {
+  fakeApi({ [CONNECTIONS]: both, [OPTIONS]: sites });
+  const { config } = showFields(REMOTE, { config: { connection: C1 } });
+  await screen.findByRole("option", { name: "Prod · verified" });
+  await userEvent.click(screen.getByRole("button", { name: "Show choices: Site" }));
+  const list = await screen.findByRole("listbox", { name: "Choices for Site" });
+  expect(document.activeElement).toBe(list);
+  await userEvent.keyboard("{Escape}");
+  expect(screen.queryByRole("listbox")).toBeNull();
+  expect(config().site_id).toBeUndefined();
+  await vi.waitFor(() => expect(document.activeElement).toBe(screen.getByLabelText("Site")));
+  await userEvent.click(screen.getByRole("button", { name: "Show choices: Site" }));
+  await screen.findByRole("listbox", { name: "Choices for Site" });
+  await userEvent.keyboard("{ArrowDown}{Enter}");
+  expect(config().site_id).toBe("s2");
+  expect(screen.getByText("Lab, picked from the choices.")).toBeTruthy();
+});
```

- [ ] **Step 2: Run them**

Run: `npx --offline pnpm@12.6.0 exec vitest run src/routes/editor/drawer/LiveOptions.test.tsx
src/lib/schemaForm.test.ts`
Expected: FAIL, 7 failed and 28 passed: a field with live choices takes no pills (`expected [ [ 'options', false ], …(1)
] to deeply equal [ [ 'options', true ], …(1) ]`; and `Unable to find an accessible element with the role "button" and
name "Text"`), and the choices are a select, not a list (`Unable to find role="listbox" and name "Choices for Site"`,
five tests). The tests of loading on request, eras, failures and the buttons' names pass at once: loading is unchanged.

- [ ] **Step 3: Implement values and choices in a path id**

Apply:

```diff
diff --git a/frontend/src/lib/schemaForm.ts b/frontend/src/lib/schemaForm.ts
index 922212e7..6cb2c407 100644
--- a/frontend/src/lib/schemaForm.ts
+++ b/frontend/src/lib/schemaForm.ts
@@ -216,9 +216,10 @@ export function settingsOf(type: NodeType, fields: FieldSpec[]): { setup: FieldS
 export const canFixed = (f: FieldSpec): boolean => !f.sensitive && (f.kinds === null || f.kinds.includes("literal"));
 
 /** Where text with data pills is its fixed value (4c-2b): text the engine takes as a template, never a sensitive
- * field's (a secret is never typed, M25), a port's name or one written only as a literal. */
+ * field's (a secret is never typed, M25), a port's name or one written only as a literal. A field with live choices
+ * takes them too, its choices under it (4f-2: ruling 127 amended). */
 export const takesPills = (f: FieldSpec): boolean =>
-  (f.widget === "text" || f.widget === "datetime") && !f.sensitive && !f.port && !f.literalOnly &&
+  (f.widget === "text" || f.widget === "datetime" || f.widget === "options") && !f.sensitive && !f.port && !f.literalOnly &&
   !f.holdsLiteral && (f.kinds === null || f.kinds.includes("template"));
 
 /** Where it takes a formula: no literal-only marker on the path or inside (value.literal_only), `cel` among its kinds. */
diff --git a/frontend/src/routes/editor/drawer/FieldView.tsx b/frontend/src/routes/editor/drawer/FieldView.tsx
index 99324c33..2fb2cb24 100644
--- a/frontend/src/routes/editor/drawer/FieldView.tsx
+++ b/frontend/src/routes/editor/drawer/FieldView.tsx
@@ -12,7 +12,7 @@ import { STALE, type UnappliedKind } from "../../../lib/unapplied";
 import { problemsAt, useDrawer, useSession } from "./context";
 import { FieldFrame, GroupFrame, type Described } from "./FieldFrame";
 import { FormulaControl, ModeSwitch, ReferenceView, SensitiveView, runsText, type Mode } from "./Formula";
-import { OptionsControl } from "./LiveOptions";
+import { ChoicesBelow, OptionsControl } from "./LiveOptions";
 import { ConnectionControl, WorkflowControl } from "./pickers";
 import {
   BooleanControl, CUT_NOTE, EnumControl, JSON_NOTE, JsonControl, LITERAL_NOTE, NumberControl, TextControl,
@@ -28,6 +28,8 @@ const NEITHER = "This field takes only references or text with references, which
 export const PILLS_NOTE = "Press / or ＋ Data to insert data from earlier steps. A dashed pill may be missing when this runs: give it a default.";
 /** What a text on several lines says, under the message's text (4f-1). */
 export const LINES_NOTE = "Press / or ＋ Data to add a value; Enter starts a new line.";
+/** Under a field that takes values and has choices (4f-2, ruling 127 amended). */
+export const CHOICES_NOTE = "A value from an earlier step, or one of the connection's choices: Show choices lists them.";
 /** What a viewer and a version's view are told: they can't insert data or give a default (#85). */
 export const PILLS_SEEN = "A dashed pill may be missing when this runs.";
 
@@ -333,7 +335,28 @@ export function FieldView({ spec, drawn = {} }: { spec: FieldSpec; drawn?: Drawn
     // Text with data pills: what's held, or the value, as text and pills (4c-2b).
     // "/" and "＋ Data" work where the person may edit the draft: the note says them only there (#85).
     const pillsNote = drawn.quiet ? null : disabled || drawer.revision === null ? PILLS_SEEN : drawn.lines ? LINES_NOTE : PILLS_NOTE;
-    body = frame(textPills, joined(hint, (held?.literal ?? kind === "literal") ? LITERAL_NOTE : null, pillsNote));
+    const choosing = spec.widget === "options";
+    // Its choices under it: a pick replaces what's there, as text (4f-2). The query is its written text, if it's only that.
+    const written = segmentsOf(value);
+    const choices = choosing && (
+      <ChoicesBelow
+        spec={spec} query={written !== null && written.pills.length === 0 ? written.texts.join("") : ""} current={value} disabled={disabled}
+        onDone={refocus}
+        onPick={(choice) => {
+          const why = writeFixed(choice, false);
+          if (why === null) {
+            drawer.release("template", spec.pointer);
+            setGeneration((g) => g + 1);
+          }
+          return why;
+        }}
+      />
+    );  // prettier-ignore
+    body = frame(
+      textPills,
+      joined(hint, (held?.literal ?? kind === "literal") ? LITERAL_NOTE : null, choosing ? CHOICES_NOTE : null, pillsNote),
+      choices ? <>{drawn.below}{choices}</> : drawn.below,
+    );
   } else if (held && Held) {
     // What's held shows first, before what the value under it has become (a reference, a hidden secret, another
     // mode): it stays visible, and recoverable, until it's applied or discarded (the review of revision 3).
diff --git a/frontend/src/routes/editor/drawer/LiveOptions.tsx b/frontend/src/routes/editor/drawer/LiveOptions.tsx
index 8d4ffc5b..dcbfeff5 100644
--- a/frontend/src/routes/editor/drawer/LiveOptions.tsx
+++ b/frontend/src/routes/editor/drawer/LiveOptions.tsx
@@ -3,15 +3,17 @@
 // choices load only when the person asks, through the step's connection: an options call reaches the plugin's
 // service, so it's never a side effect of opening a drawer (D24). Choices belong to their scope (tenant, type, field,
 // the connection's id and revision), and each change of scope is a new era: shown choices go, and an answer from an
-// older era is ignored, even when the scope comes back. They help; they never gate what's typed.
+// older era is ignored, even when the scope comes back. They help; they never gate what's typed. They show as a list
+// under the field (4f-2, the Mist step design §5.2; ruling 126: in the drawer's flow); a pick replaces the value and is
+// named until the drawer closes or the value changes: the config keeps only the value.
 import { useQuery } from "@tanstack/react-query";
-import { useRef, useState } from "react";
+import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";
 import { Button } from "../../../components/Button";
 import { controlClass } from "../../../components/Field";
 import { ApiError, client, ok, type Schemas } from "../../../lib/client";
 import { valueAt } from "../../../lib/config";
 import { idKey, sameId } from "../../../lib/graph";
-import { fieldsOf } from "../../../lib/schemaForm";
+import { fieldsOf, type FieldSpec } from "../../../lib/schemaForm";
 import { useDrawer } from "./context";
 import { connectionsQuery } from "./pickers";
 import type { ControlProps } from "./scalars";
@@ -41,11 +43,15 @@ const WHY: Record<string, string> = {
 function said(choices: Choices): string {
   if (choices.status === "loading") return "Loading choices…";
   if (choices.status === "failed") return choices.why;
-  if (choices.status === "done" && choices.options.length === 0) return "No choices match.";
+  if (choices.status === "done") return choices.options.length === 0 ? "No choices match." : choices.options.length === 1 ? "1 choice" : `${choices.options.length} choices`;
   return "";
 }
 
-export function OptionsControl({ spec, value, literal, id, describedBy, invalid, disabled, onChange }: ControlProps) {
+/** A choice's id, shortened when it's long: its name says the rest. */
+const idStart = (value: string) => (value.length > 12 ? `${value.slice(0, 8)}…` : value);
+
+/** A field's choices, loaded on request through the step's connection (ruling 109), each answer for its era only. */
+function useChoices(spec: FieldSpec) {
   const drawer = useDrawer();
   const type = spec.type;
   const takes = type.credentials.length > 0;
@@ -73,16 +79,14 @@ export function OptionsControl({ spec, value, literal, id, describedBy, invalid,
   // Its scope isn't known until the connection's revision is: while the list loads, when it fails, when it doesn't
   // name the connection (the review of revision 2).
   const unsettled = takes && chosen !== null && (revision === null || listed.isError); // a failed refresh keeps old data
-  const typed = drawer.held("text", spec.pointer); // what a refused write turned away (ruling 18)
-  const text = typed?.text ?? (typeof value === "string" ? value : "");
-  async function load() {
+  async function load(query: string) {
     const asked = era;
     setChoices({ era: asked, state: { status: "loading" } });
     try {
       const answer = await ok(
         client.POST("/api/v1/t/{tenant_id}/node-types/{ref}/options", {
           params: { path: { tenant_id: drawer.tenantId, ref: type.ref } },
-          body: { field: spec.name, connection_id: chosen, query: text.slice(0, 200) },
+          body: { field: spec.name, connection_id: chosen, query: query.slice(0, 200) },
         }),
       );
       if (eraNow.current === asked) setChoices({ era: asked, state: { status: "done", options: answer.options } });
@@ -91,54 +95,156 @@ export function OptionsControl({ spec, value, literal, id, describedBy, invalid,
       if (eraNow.current === asked) setChoices({ era: asked, state: { status: "failed", why } });
     }
   }
+  const close = () => setChoices({ era, state: { status: "idle" } });
+  return { shown, load, close, blocked, unsettled, listed };
+}
+
+type Choosing = ReturnType<typeof useChoices>;
+
+/** Why the choices can't load yet, and what loading said. */
+function ChoiceWords({ choosing }: { choosing: Choosing }) {
+  const { shown, blocked, unsettled, listed } = choosing;
+  return (
+    <>
+      {blocked && <p className="text-small text-muted">Choose the step&apos;s connection first: the choices come from it.</p>}
+      {unsettled && !listed.isPending && (
+        <p className="text-small text-muted">
+          {listed.isError ? "Connections couldn't load, so the choices can't either." : "The step's connection isn't in this tenant's list, so its choices can't load."}
+        </p>
+      )}
+      <p role="status" className={`text-small ${shown.status === "failed" ? "text-danger" : "text-muted"}`}>{said(shown)}</p>
+    </>
+  );  // prettier-ignore
+}
+
+/** The choices, as a list under the field: Up and Down move, Enter picks, Escape closes; it scrolls past ten. */
+function ChoiceList({ label, options, onPick, onClose }: { label: string; options: Option[]; onPick: (o: Option) => void; onClose: () => void }) {
+  const id = useId();
+  const list = useRef<HTMLUListElement>(null);
+  const [active, setActive] = useState(0);
+  useEffect(() => list.current?.focus(), []);
+  useEffect(() => document.getElementById(`${id}-${active}`)?.scrollIntoView?.({ block: "nearest" }), [active, id]);
+  const onKeyDown = (e: KeyboardEvent) => {
+    const move = { ArrowDown: active + 1, ArrowUp: active - 1, Home: 0, End: options.length - 1 }[e.key];
+    if (move !== undefined) setActive(Math.max(0, Math.min(options.length - 1, move)));
+    else if (e.key === "Enter") onPick(options[active]!);
+    else if (e.key === "Escape") onClose();
+    else return;
+    e.preventDefault();
+    e.stopPropagation(); // Escape closes the list, not the drawer
+  };
+  return (
+    <ul
+      ref={list} role="listbox" tabIndex={0} aria-label={`Choices for ${label}`} aria-activedescendant={`${id}-${active}`} onKeyDown={onKeyDown}
+      className="max-h-[320px] overflow-y-auto rounded-control border border-line p-1"
+    >
+      {options.map((o, i) => (
+        <li
+          key={`${i}:${o.value}`} id={`${id}-${i}`} role="option" aria-selected={i === active}
+          onMouseDown={(e) => e.preventDefault()} onClick={() => onPick(o)}
+          className="flex min-h-[32px] cursor-pointer items-center justify-between gap-3 rounded-control px-2.5 text-body aria-selected:bg-accent-soft"
+        >
+          <span className="min-w-0 truncate">{o.label}</span>
+          {o.label !== o.value && <span className="shrink-0 font-mono text-meta text-muted">{idStart(o.value)}</span>}
+        </li>
+      ))}
+    </ul>
+  );  // prettier-ignore
+}
+
+/** A pick, named while the field still holds it: the config keeps only its value. */
+function usePicked(current: unknown) {
+  const [picked, setPicked] = useState<Option | null>(null);
+  const note = picked !== null && current === picked.value ? `${picked.label}, picked from the choices.` : null;
+  return { note, setPicked };
+}
+
+/** Under a field that takes values from earlier steps (4f-2: ruling 127 amended): Show choices, what's said of them,
+ * their list, and the pick's name. The query is the field's written text when it holds no value from a step. */
+export function ChoicesBelow({ spec, query, current, disabled, onPick, onDone }: {
+  spec: FieldSpec; query: string; current: unknown; disabled: boolean; onPick: (value: string) => string | null; onDone: () => void;
+}) {  // prettier-ignore
+  const choosing = useChoices(spec);
+  const { shown, blocked, unsettled } = choosing;
+  const { note, setPicked } = usePicked(current);
+  return (
+    <div className="flex min-w-0 flex-col gap-2">
+      <div>
+        <Button
+          size="sm" aria-label={`Show choices: ${spec.label}`} className="max-sm:min-h-[44px]"
+          disabled={disabled || blocked || unsettled || shown.status === "loading"} onClick={() => void choosing.load(query)}
+        >
+          Show choices
+        </Button>
+      </div>
+      <ChoiceWords choosing={choosing} />
+      {shown.status === "done" && shown.options.length > 0 && !disabled && (
+        <ChoiceList
+          label={spec.label} options={shown.options}
+          onClose={() => {
+            choosing.close();
+            onDone();
+          }}
+          onPick={(o) => {
+            if (onPick(o.value) === null) setPicked(o);
+            choosing.close();
+            onDone();
+          }}
+        />
+      )}
+      {note && <p className="text-small">{note}</p>}
+    </div>
+  );  // prettier-ignore
+}
+
+export function OptionsControl({ spec, value, literal, id, describedBy, invalid, disabled, onChange }: ControlProps) {
+  const drawer = useDrawer();
+  const choosing = useChoices(spec);
+  const { shown, blocked, unsettled } = choosing;
+  const { note, setPicked } = usePicked(value);
+  const typed = drawer.held("text", spec.pointer); // what a refused write turned away (ruling 18)
+  const text = typed?.text ?? (typeof value === "string" ? value : "");
+  const write = (next: string, typing: boolean): string | null => {
+    const why = onChange(next === "" ? undefined : next, typing);
+    if (why === null) drawer.release("text", spec.pointer);
+    // The edit keeps the reading it began with, a literal's or not (the review of revision 4).
+    else drawer.hold("text", spec.pointer, { path: spec.path, label: spec.label, text: next, why, literal: typed?.literal ?? literal, entry: spec.entry });
+    return why;
+  };
   return (
     <div className="flex min-w-0 flex-col gap-2">
       <div className="flex min-w-0 gap-2">
         <input
           id={id} type="text" value={text} disabled={disabled} spellCheck={false}
           aria-describedby={describedBy} aria-invalid={invalid} aria-required={spec.required && !spec.entry}
-          onChange={(e) => {
-            const next = e.target.value;
-            const why = onChange(next === "" ? undefined : next, true);
-            if (why === null) drawer.release("text", spec.pointer);
-            // The edit keeps the reading it began with, a literal's or not (the review of revision 4).
-            else drawer.hold("text", spec.pointer, { path: spec.path, label: spec.label, text: next, why, literal: typed?.literal ?? literal, entry: spec.entry });
-          }}
+          onChange={(e) => void write(e.target.value, true)}
           className={controlClass(invalid)}
         />
         {/* Named by its field, its visible text first (WCAG 2.5.3): a list of buttons tells them apart (#73). */}
         <Button
           className="shrink-0" aria-label={`Show choices: ${spec.label}`}
-          disabled={disabled || blocked || unsettled || shown.status === "loading"} onClick={() => void load()}
+          disabled={disabled || blocked || unsettled || shown.status === "loading"} onClick={() => void choosing.load(text)}
         >
           Show choices
         </Button>
       </div>
-      {blocked && <p className="text-small text-muted">Choose the step&apos;s connection first: the choices come from it.</p>}
-      {unsettled && !listed.isPending && (
-        <p className="text-small text-muted">
-          {listed.isError ? "Connections couldn't load, so the choices can't either." : "The step's connection isn't in this tenant's list, so its choices can't load."}
-        </p>
-      )}
-      <p role="status" className={`text-small ${shown.status === "failed" ? "text-danger" : "text-muted"}`}>{said(shown)}</p>
-      {shown.status === "done" && shown.options.length > 0 && (
-        <select
-          aria-label={`Choices for ${spec.label}`} value="" disabled={disabled} className={controlClass(false)}
-          onChange={(e) => {
+      <ChoiceWords choosing={choosing} />
+      {shown.status === "done" && shown.options.length > 0 && !disabled && (
+        <ChoiceList
+          label={spec.label} options={shown.options}
+          onClose={() => {
+            choosing.close();
+            document.getElementById(id)?.focus();
+          }}
+          onPick={(o) => {
             // A choice writes as typing does: written, the text held before it goes; refused, it's held, with why.
-            const choice = e.target.value;
-            const why = onChange(choice, false);
-            if (why === null) drawer.release("text", spec.pointer);
-            else drawer.hold("text", spec.pointer, { path: spec.path, label: spec.label, text: choice, why, literal: typed?.literal ?? literal, entry: spec.entry });
+            if (write(o.value, false) === null) setPicked(o);
+            choosing.close();
             document.getElementById(id)?.focus();
           }}
-        >
-          <option value="">{shown.options.length === 1 ? "1 choice" : `${shown.options.length} choices`}</option>
-          {shown.options.map((o, i) => (
-            <option key={`${i}:${o.value}`} value={o.value}>{o.label === o.value ? o.label : `${o.label} (${o.value})`}</option>
-          ))}
-        </select>
+        />
       )}
+      {note && <p className="text-small">{note}</p>}
     </div>
   );  // prettier-ignore
 }
```

- [ ] **Step 4: Run them again, and the static checks**

Run: the same tests. Expected: PASS, 35 passed. Then the frontend's static checks: no output.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/schemaForm.ts frontend/src/lib/schemaForm.test.ts frontend/src/routes/editor/drawer/LiveOptions.tsx frontend/src/routes/editor/drawer/LiveOptions.test.tsx frontend/src/routes/editor/drawer/FieldView.tsx
git commit -m "feat(editor): a path id with choices takes values, its choices a list under it (4f-2a)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

Milestone 2 ends here: append `### 4f-2a, milestone 2 (<date>)` to the ledger, commit it, and pause for the owner's
review.

# Milestone 3 — Close

### Task 6: In the browser

**Spec:** §6 (the e2e: no Mist call; a real `mist.site_settings.update@1` step placed without a connection, the
picker by resource, with axe, light and dark, at 1280 and 320 px); §5.11.

**Files:**
- Create: `frontend/e2e/mist.spec.ts`, `frontend/e2e/fixtures/mist.dewpoint.json`
- Modify: `frontend/playwright.config.ts` (the workflows project runs `mist.spec.ts`)

**Interfaces:**
- Consumes: `test`, `expect`, `expectAccessible` (`e2e/gate.ts`); the admin's saved state (the foundations project);
  the server's own Mist steps, synced from the plugin with Task 2's metadata.
- Produces: nothing later tasks use.

"Mist" holds one Mist step, `get_site` (`mist.site_settings.get@1`), without a connection. The specs import it, add a
step after it through the picker and, at 1280 px: Mist's 85 resources, "site settings" found, its two actions, "Uses
a Mist connection", the new step's drawer with "Mist · Site settings", its Site ID in Text with ＋ Data, Show choices
disabled for want of a connection, the draft saved; at 320 px: Back and the action rows 44 px, a ref under its title,
Show choices 44 px. Both light and dark with axe. Nothing is published and Mist is never called.

- [ ] **Step 1: Write the specs**

Apply:

```diff
diff --git a/frontend/e2e/fixtures/mist.dewpoint.json b/frontend/e2e/fixtures/mist.dewpoint.json
new file mode 100644
index 00000000..797982f5
--- /dev/null
+++ b/frontend/e2e/fixtures/mist.dewpoint.json
@@ -0,0 +1,22 @@
+{
+  "format": "dewpoint.workflow",
+  "format_version": 1,
+  "name": "Mist",
+  "graph": {
+    "graph_format": 1,
+    "nodes": [
+      {
+        "id": "4f200001-0000-4000-8000-000000000001",
+        "key": "get_site",
+        "type": "mist.site_settings.get@1",
+        "config": {},
+        "position": { "x": 0, "y": 140 }
+      }
+    ],
+    "edges": [],
+    "settings": {
+      "input_schema": { "type": "object", "properties": {}, "additionalProperties": false }
+    }
+  },
+  "bindings": []
+}
diff --git a/frontend/e2e/mist.spec.ts b/frontend/e2e/mist.spec.ts
new file mode 100644
index 00000000..2189c4ae
--- /dev/null
+++ b/frontend/e2e/mist.spec.ts
@@ -0,0 +1,78 @@
+// SPDX-License-Identifier: Apache-2.0
+// Editor 4f-2a in the browser: a Mist step added through the picker by its resource, and its site's id, which takes a
+// value from an earlier step and offers the connection's choices. Behind nginx, under the served CSP, with axe, light
+// and dark, at 1280 and 320 px. Nothing is published and Mist is never called (D24): the steps have no connection, so
+// their choices can't load.
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
+/** The Mist fixture imported as a new workflow and opened on its canvas; the picker opened after its step. */
+async function openPicker(page: Page, name: string) {
+  await page.goto(`/t/${await tenantId(page)}/workflows`);
+  await page.getByTestId("workflow-new").click();
+  const dialog = page.getByRole("dialog", { name: "New workflow" });
+  await dialog.getByLabel("Name").fill(name);
+  await dialog.getByRole("radio", { name: /Import from file/ }).check();
+  await dialog.getByLabel("Workflow file").setInputFiles("e2e/fixtures/mist.dewpoint.json");
+  await dialog.getByRole("button", { name: "Import and open" }).click();
+  await expect(page).toHaveURL(/\/workflows\/[0-9a-f-]{36}\?triggers=true$/);
+  await page.goto(new URL(page.url()).pathname);
+  await page.getByRole("button", { name: "Add a step after get_site" }).click();
+  return page.getByRole("dialog", { name: /^Add a step/ });
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
+test("a Mist step is found by its resource, and its site's id takes a value or a choice", async ({ page }) => {
+  const picker = await openPicker(page, "Mist step");
+  await expect(picker.getByText("Mist: 85 resources, type to find one")).toBeVisible();
+  await accessibleBothWays(page, "picker: Mist's resources");
+  await picker.getByRole("combobox").fill("site settings");
+  await expect(picker.getByRole("option", { name: /^Site settings/ })).toContainText("2 actions");
+  await page.keyboard.press("Enter");
+  await expect(page.getByRole("dialog", { name: "Add a step: Site settings" })).toBeVisible();
+  await expect(picker.getByRole("option", { name: /^Update site settings/ })).toContainText("Uses a Mist connection");
+  await accessibleBothWays(page, "picker: a resource's actions");
+  await picker.getByRole("option", { name: /^Update site settings/ }).click();
+  await page.getByRole("button", { name: /^update, Update site settings/ }).click();
+  const drawer = page.getByRole("complementary", { name: "update" });
+  await expect(drawer.getByText("Mist · Site settings")).toBeVisible();
+  const site = drawer.locator('[data-pointer="/site_id"]');
+  await expect(site.getByRole("button", { name: "Text" })).toHaveAttribute("aria-pressed", "true");
+  await expect(site.getByRole("button", { name: "＋ Data" })).toBeVisible();
+  await expect(site.getByRole("button", { name: "Show choices: Site ID" })).toBeDisabled();
+  await expect(site.getByText("Choose the step's connection first: the choices come from it.")).toBeVisible();
+  await expect(page.getByText("Saved · not published")).toBeVisible({ timeout: 10_000 });
+  await accessibleBothWays(page, "drawer: a Mist step's site id");
+});
+
+test("at 320 px the picker's targets are 44 px and a step's ref goes under its title", async ({ page }) => {
+  await page.setViewportSize({ width: 320, height: 720 });
+  const picker = await openPicker(page, "Mist step narrow");
+  await picker.getByRole("combobox").fill("site settings");
+  await page.keyboard.press("Enter");
+  expect((await picker.getByRole("button", { name: "Back to every step" }).boundingBox())!.height).toBeGreaterThanOrEqual(44);
+  const update = picker.getByRole("option", { name: /^Update site settings/ });
+  const [title, ref] = [(await update.getByText("Update site settings", { exact: true }).boundingBox())!, (await update.getByText("mist.site_settings.update@1").boundingBox())!];
+  expect(ref.y).toBeGreaterThan(title.y);
+  expect((await update.boundingBox())!.height).toBeGreaterThanOrEqual(44);
+  await accessibleBothWays(page, "picker at 320 px");
+  await update.click();
+  await page.getByRole("button", { name: /^update, Update site settings/ }).click();
+  const drawer = page.getByRole("complementary", { name: "update" });
+  expect((await drawer.getByRole("button", { name: "Show choices: Site ID" }).boundingBox())!.height).toBeGreaterThanOrEqual(44);
+  await accessibleBothWays(page, "drawer at 320 px");
+});
diff --git a/frontend/playwright.config.ts b/frontend/playwright.config.ts
index e512df15..d5da68fe 100644
--- a/frontend/playwright.config.ts
+++ b/frontend/playwright.config.ts
@@ -7,7 +7,7 @@ export default defineConfig({
     { name: "foundations", testMatch: /(foundations|gate)\.spec\.ts/, use: { ...devices["Desktop Chrome"] } },
     {
       name: "workflows",
-      testMatch: /(workflows|triggers|simulation|runs|runForm|composer)\.spec\.ts/,
+      testMatch: /(workflows|triggers|simulation|runs|runForm|composer|mist)\.spec\.ts/,
       dependencies: ["foundations"],
       use: { ...devices["Desktop Chrome"], storageState: "test-results/admin-state.json" },
     },
```

- [ ] **Step 2: Type check and lint them**

Run: the frontend's static checks of "How to run things". Expected: no output (the type check covers `e2e/`, and
ESLint lints it).

- [ ] **Step 3: Run them in the browser**

They need the Compose stack, as CI's e2e job brings it up (`deploy/compose`, the development override, a generated
`.env` that's never printed, `dewpoint admin init`). Locally, building it takes long: ask the owner first. Then, from
`$WT/frontend`: `npx --offline pnpm@12.6.0 exec playwright test` (the foundations project signs the admin in first).
Expected: every spec passes, the two of `mist.spec.ts` among them. A failure is read and fixed test-first. If the
owner prefers, the specs run in CI's e2e job on the PR instead, and the summary says they weren't run locally.

- [ ] **Step 4: Commit**

```bash
git add frontend/e2e frontend/playwright.config.ts
git commit -m "test(e2e): the Mist picker and a path id in the browser, light and dark, at 1280 and 320 px (4f-2a)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Every check, the ledger, the final checkpoint

**Files:**
- Modify: `docs/superpowers/plans/2026-10-05-editor-ui-4-ledger.md`

- [ ] **Step 1: Every check, and CodeQL**

From `$WT/frontend`:
- `npx --offline pnpm@12.6.0 exec vitest run`: the whole suite (about a minute);
- `npx --offline pnpm@12.6.0 exec eslint .`; `npx --offline pnpm@12.6.0 build` (the type check, then Vite);
- `npx --offline pnpm@12.6.0 check:api`: the API's schema, unchanged.

From `$WT/backend`:
- `UV_FROZEN=1 UV_NO_SYNC=1 uv run pytest -q -n 6 tests/plugins/mist`;
- the backend's static checks of "How to run things".

Then local CodeQL on the head: CI's python and javascript-typescript analyses on a `git archive` of it.

Expected, as on the plan's own check (at the top): the frontend suite, 1517 passed in 110 files (main has 1498 in 108);
ESLint silent; the build done, the entry 650.0 kB, the editor's script 149.1 kB; `check:api` passes; the Mist suite 565
passed; ruff, the format check and mypy clean; CodeQL, no finding in either language.

A failure is read and fixed test-first, or reported as it is: never a claim that every check passes when one didn't.

- [ ] **Step 2: The ledger**

Append `### 4f-2a, milestone 3 and the final checkpoint (<date>)`: the tasks' commits, each check's result as run
(the suites' counts), whether the e2e spec ran locally or waits for CI, every mid-slice ruling, anything deferred.
Commit it (`docs(editor-4): 4f-2a final checkpoint`), with the trailer.

- [ ] **Step 3: The final review and the pause**

A fresh reviewer, on the most capable model, reviews the whole branch:
- against this plan (its Review Focus first) and the spec's §3, §4, §5.1, §5.2, §5.10, §5.11 and §6, with the boards;
- with the ledger's rulings in view.

Critical and important findings are fixed test-first, once; minor ones are listed. Then **stop**. The summary to the
owner lists the commits, the checks as run, the rulings made mid-slice, the review's findings and what was deferred.
Nothing is pushed and no PR is opened without the owner's word.
