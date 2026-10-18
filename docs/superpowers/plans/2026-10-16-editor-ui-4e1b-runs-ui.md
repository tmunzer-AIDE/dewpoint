# Editor UI 4e-1b: the Runs page, a run's page and cancel (the UI) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Revision 1, 2026-10-16.** Nothing is built before the owner approves this plan. Nothing is pushed and no PR is
opened without the owner's OK in chat.

The plan's code was checked before review on a scratch checkout of main at cb7425db, never on a branch. Each
task's diffs were applied as written, in order:
- the test diff alone, then the task's tests: they failed as its "Run them" step says;
- then the implementation diff and the same tests: they passed;
- after every task, the type check (`tsc -b --noEmit`) and ESLint: silent;
- after the last, the tree matched the prototype the diffs were cut from, file for file (tree 135e9b8d);
- the 27 diff blocks, taken from this file's own text, are the diffs applied, byte for byte, in order;
- on the final tree: the whole frontend suite (1277 passed, 98 files; main has 1184 in 90), the build, `check:api`,
  and CodeQL (javascript-typescript, CLI 2.27.2, javascript-queries 2.4.7, CI's filter: no finding).

The e2e specs (Task 15) were type-checked and linted, not run: they need the Compose stack, which Task 15 asks the
owner about. The executor still runs every step: the check is evidence, not a substitute.

**Goal:** The screens of the runs design §5, against the signed-off D8 boards: the rail's Runs, the Runs page with
its filters and its reading, a run's page laid out like the editor (its bar, its banner, the read-only canvas with each
step's result, the step drawer's Result tab, a loop's iterations, the Start drawer), cancel, and the runs that didn't
run, in one status vocabulary, at 1280 and 320 px.

**Architecture:**
- **One vocabulary** (`lib/runStatus.ts`): each status's word and look, a run's name and durations, and the words for
  why a request didn't start; the Workflows list and the Simulation panel take it too ("Ran out of time").
- **The API layer** (`lib/runs.ts`): 4e-1a's typed routes as query factories, the filters kept in the address, the
  list's paging and merge (`listed`), cancel.
- **The Runs page** (`routes/runs/RunsPage.tsx`, lazy): the filters as "Label · Value ▾" menus, the table (a list below
  640 px), the first page read every 5 s while visible, older pages loaded on and never read again.
- **A run's page** (`routes/runs/RunPage.tsx`, lazy, beside the compact rail): the editor's canvas read only, its
  keyboard moved into a hook both share (`useCanvasNav`), 4d-1c's tags generalised to any run, the editor's step drawer
  with a Result tab first, the iterations and picker 4d-1c drew, shared through one instances read (`InstancePages`);
  read every second while it runs, backing off to 5 s; cancel; the Start drawer.

**Tech Stack:** React 19, TanStack Query 5 (query-core 5.103.2), TanStack Router, openapi-fetch over the generated
`schema.d.ts`, Radix (dropdown menu, tabs), cmdk, Tailwind v4 tokens; Vitest and Testing Library (no jest-dom);
Playwright against the Compose stack, with axe.

**Spec:** `docs/superpowers/specs/2026-10-15-editor-4e1-runs-design.md`: §5 (the UI), with §3 and §8 (the owner's
answers), §6 (4e-1b's tests) and §4 (the API 4e-1a built, merged as #116). The boards: "4e-1 Runs Mockups" v9 (Main,
ListStates, RunFailed, RunRunning, RunLoop, RunOther, Narrow320Light, Narrow320Dark).

## Global Constraints

- **The frontend only.** No backend change, no migration, no ABI change. The API is 4e-1a's (#116): `check:api` passes
  as it is.
- **No new dependency.** No npm package is added, and there's no third-party JavaScript or CDN asset: everything is
  bundled, under the strict CSP, with no inline script or style.
- **Words first.** Every state is said in words; colour and the hatch only repeat them (§5.5). Live is orange (D3), a
  simulation slate with the hatch (D2). The boards' copy is used where it exists; the rulings below say where it isn't.
- **No AI tells.** No left-border accents, halos, tinted icon tiles or eyebrows (`src/test/aiTells.test.ts` enforces
  them). No green edges and no halo on a run's canvas (§5.3).
- **WCAG 2.2 AA**, light and dark, at 1280 and 320 px: axe in the e2e specs (Task 15); every control named, every
  state in text; one persistent live region, the shell's (§5.6).
- **No real Mist or SaaS call.** Unit tests stub `fetch`. The e2e specs run control steps only, on the Compose stack;
  nothing leaves the stack (D24: the gate fails a request to another origin).
- **Verify, don't remember.** Each library behaviour relied on was checked in the installed package:
  - query-core 5.103.2: `refetchInterval` as a function, skipped while `focusManager` says the tab isn't focused;
    `keepPreviousData`; `isRefetchError` keeps `data`; `QueryClient.query` (its `fetchQuery` is deprecated, same code
    path).
  - TanStack Router: a route's validated search is laid over the address's raw search (`validateRunsSearch` names
    every key so an unknown value is dropped).
  - cmdk 1.1.1: `Command.Input` is named by the `Command`'s label (`aria-labelledby`).
  - ICU (Node 26, Chrome): `dateStyle: "full"` in en-GB reads "Friday, 16 October 2026 at …".
- **The chunks.** The run pages load lazily, each in its own chunk; the canvas they share with the editor moves into a
  shared chunk and doesn't grow the editor's code (ruling 21's evidence).
- **CI.**
  - Every check runs locally first. Commits and PRs carry no skip marker.
  - Nothing is pushed and no PR is opened without the owner's OK in chat.
  - Ask before any local run expected over 10 minutes (the e2e specs on a local Compose stack).

## Review Focus

These are the inputs and conditions most likely to bite a person using this that the design implies but its own
lists don't name. Each is pinned by the test named, in the task that owns the code.

- **A run whose read fails while it runs** (a dropped connection, a proxy's 502, a restart). The page keeps what it
  showed, says "Couldn't be refreshed · as of …" with Try again, and goes on: never "The run couldn't be read" over a
  run already on screen. Task 9: `keeps the run when a read fails while it runs, says as of when, and tries again`.
- **A filter changed after older runs were loaded.** The list starts afresh under the new filters: no run of the old
  ones below the new first page, and Load more offered again. Task 6: `starts the list afresh when a filter changes
  after older runs were loaded`.
- **A run cancelled while it waited.** Cancel answers `cancelled` at once: the page reads it cancelled and says the run
  ended, never "Cancel requested". Task 12: `reads a run cancelled while it waited as cancelled, never as a cancel
  requested`.
- **A step whose type the server no longer knows** (a plugin removed since the run). Its result still shows; Setup says
  why its settings can't be. Task 10: `shows the result of a step whose type the server no longer knows, and says why
  its settings can't be shown`.
- **A failed run whose failed step ran in a loop.** It opens on that step, its instances' totals and the iteration
  picker, not a single instance it doesn't have. Task 11: `opens a failed run on its failed step in a loop, one of its
  iterations at a time`.

## Rulings this plan proposes

They join the ledger as 230 onward only when the owner accepts the plan; mid-slice rulings start at M104. Each follows
the spec where the boards or the spec are silent, or says where it departs from a board, with what it costs if wrong.

1. **One plan with milestone pauses**, as for 4d-1c: the four milestones below. Cost: none.
2. **One vocabulary module** (`lib/runStatus.ts`): each status's word and tone; `duration` and `runId` move there from
   the Simulation panel's `lifecycle.ts`. The panel's status chip takes the vocabulary's look (running in the accent,
   waiting dashed) and its words, but keeps "Not simulated" for its refusals (§5.5); its "Simulated" chip is unchanged.
   Cost: the panel's running chip changes colour.
3. **Why a request didn't start is worded here, from its code** (`reasonWords`): 4e-1a's ruling 213 keeps only the
   code, so the spec's "the server's messages (up to 5)" can't be shown. A code these words don't know is shown alone,
   with "Nothing ran." Cost: a new server code needs its words added here.
4. **The list pages on from its last run's `(queued_at, id)`**, the server's order; a run with no queue time (from
   before 2b-2) ends the paging. **`listed`** shows the first page as last read, then the runs read earlier that sort
   after a full first page, the latest read of each; nothing read earlier when the first page holds every match (§5.2:
   "de-duplicated by id across pages"). Cost: a run pushed off the first page keeps its last read state until it's
   loaded again.
5. **An empty list says what was asked.** At the default window, "No runs in the last 24 hours.", with Show all kept;
   "No runs yet. A run starts…" (the board's) only when every run kept was asked for; the end of paging names the
   window ("No older runs in the last 7 days.") or "No older runs are kept." Why: under the default 24 hours, the
   board's "No runs yet" would say that no run ever ran. Cost: copy beyond the board.
6. **The Mode menu's items say what they hold** ("Simulated: of a published version", "Draft simulations: made in the
   editor") in place of the board's caption under the menu: a menu may hold only items and groups (ARIA). Cost: copy.
7. **The Workflow filter is a native modal dialog around cmdk** ("Choose a workflow", its input's placeholder "Find a
   workflow"), as the palette and the step picker are (D23): a Radix menu takes typed keys for its typeahead. Cost: a
   dialog where the board drew a drop-down.
8. **Below 640 px the list is a list, in place of the table** (`useNarrow`, a media query followed with
   `useSyncExternalStore`), never both in the DOM; jsdom gets a `matchMedia` stand-in (`src/test/setup.ts`). Cost:
   none.
9. **One lazy loader** (`components/LazyPage.tsx`) generalises the editor's: `LazyEditor` keeps its API and its tests;
   the Runs page and a run's page each load in their own chunk (§5.1). Cost: none.
10. **Times** (`lib/when.ts`): "today 10:02:09", "yesterday 02:00:01", else "14 Oct 17:40:02", in the person's zone;
    the hover's full date is ICU's ("Friday, 16 October 2026 at 10:02:09 CEST"), in a `<time>`'s title (the owner's
    answer 8). Cost: none.
11. **Changes are said through the shell's one live region** (`announce`): "Updated" when the list's first page
    changed (TanStack keeps an equal answer's reference, so an unchanged poll says nothing), "The runs couldn't be
    refreshed.", "Run ended: failed", "Cancel requested. It's shown as cancelled once the server confirms it.",
    "Copied the run's id". "Updates every 5 s" is plain text (§5.6). Cost: none.
12. **One-off reads use `queryClient.query`** (load more, the iterations' pages): query-core 5.103.2 deprecates
    `fetchQuery`, which runs the same code. Cost: none.
13. **A trigger's words:** `dev` is "Development"; a schedule's timing is the app's own `timingTitle` ("Weekdays at
    06:00"; a weekly cron reads "At 0 2 * * 1", not the board's "Mondays at 02:00"); a re-run is "of <its id>". Cost:
    copy.
14. **The filters' validation names every filter**, a value it doesn't allow as undefined: TanStack Router lays a
    route's validated search over the address's raw one, which would keep the unknown value. Cost: none.
15. **The canvas's keyboard moves into `useCanvasNav`** (D16), the editor's and a run's page's; the editor keeps its
    behaviour and its 186 tests. Cost: none.
16. **4d-1c's tags serve any run** (`tagsOf`'s `run: { action }`): a live step's "sent" (live outline) or "may have
    been sent" (the warning's colour, dashed); a live control step says its port alone; an action says how long it took
    (to the tenth of a second under 10 s); a failure says its code in place of its time (the RunFailed board). A
    simulation's tags in the editor are unchanged. Cost: none.
17. **The canvas's `simulated` prop becomes `results`**, with `resultsLabel` ("result" on a run's page, "simulated
    result" by default); the start card takes a `label`, as on a run's page it opens the run's start, not the Triggers
    panel. Cost: a rename in the editor and its test stand-in.
18. **The banner's tense follows the run:** "It acts for real" and "Nothing is sent" while it runs (the RunRunning
    board), the past once it ended (the spec's words). "Ended: failed at notify_noc · today 09:41:50" sits under the
    banner; the board draws it at the canvas's foot, where React Flow would cover it. Cost: copy.
19. **Reading a run:** its state on a simulation's schedule (`pollEvery`: 1 s, backing off to 5 s), its steps every 5 s;
    an end seen on the page reads its steps at once and both once more 5 s later; a run already ended when opened is
    read again only on focus. A read that fails after one succeeded keeps the page and says "Couldn't be refreshed · as
    of …", with Try again (the list's words, §5.2). Cost: none.
20. **Copy id is named by its words** ("Copy id"): the board's label "Copy the run's id" wouldn't contain them (WCAG
    2.5.3, label in name). Cost: none.
21. **The editor's chunk:** the canvas it shares with a run's page (and, from Task 10, the step drawer) moves into a
    chunk Rollup names. Built from main cb7425db the editor was one 504.0 kB script (158.7 kB gzipped) and a 12.1 kB
    stylesheet. On this plan's final tree its script is 149.5 kB (44.9 kB) and the shared chunk 356.6 kB (115.9 kB)
    with that stylesheet: 506.1 kB together, 2.1 kB more, the code the editor runs too (the keyboard hook, the tags,
    the picker). A run's page is 19.0 kB of its own, the Runs page 11.0 kB; the entry grew 632.4 to 641.5 kB (the
    routes, the filters' validation, the loader). The e2e asset test now asserts by meaning: one Editor script, and
    nothing the editor fetches was in the list's or sign-in's load. Cost: none (§5.1 foresaw it).
22. **A step's drawer is the editor's**, read only (`READ_ONLY_ACTIONS`, moved to the drawer's context), with a Result
    tab first (the default) and Setup listing every setting, required then optional, read only, or saying that the
    server doesn't know the step's type. Cost: the editor's header lines (the type, how it runs, what a failure does)
    show on a run's drawer too.
23. **A failed run opens on its first failed step, once, when it's first read** (the owner's answer 6); Close gives
    focus back to its card. Cost: none.
24. **An instance shows its attempts read's last attempt** (fresher than the summary while the run runs); its times
    once when both fall in the same second ("14:02:31 · 0.9 s", the RunLoop board); a value wholly redacted or cut
    shows the bare mark (`PillDetails`' chip, exported), others as the preview keeps them. Cost: none.
25. **Loops:** a loop's iterations are listed once it has ended, and a step in a loop is picked from once the run has
    ended (4d-1c's ruling 4, ledger 194: pages would move under the reader). The picker's caption adds "Open any other
    from each_ap's list." `Iterations` and the picker (`IterationPicker`, from 4d-1c's `LatestResult`) read through
    `InstancePages`, a key and a read, shared with the Simulation panel and the Test tab. Cost: no iterations while a
    loop runs.
26. **Cancel:** a live run asks in an alert dialog (`ConfirmDialog` gains `alert`, its words the description); once
    it's sent, focus goes to the run's name (Cancel is gone) and "Cancel requested" stands for the status until the
    server confirms it. Cost: none.
27. **A request that never started shows its graph without tags** (nothing ran), and its state in place of the banner:
    waiting, cancelled before it started ("Cancelled before it started · queued …. Nothing ran."), or its code and
    words. Cost: copy for the cancelled case, which no board draws.
28. **The Start drawer's words:** an input `unreadable` says "Its input can't be read back: it doesn't open, or the
    tenant's key is gone during an erasure." (the spec names the state, not its words); a step test's values stand for
    its input; a CSV's columns read "header → column". Cost: copy.
29. **The Simulation panel's run id links through a `runOf` render prop** the editor gives it: the panel's tests render
    it without a router. Cost: none.
30. **The browser specs seed their runs through the API** with the session's CSRF token: a published workflow of
    control steps run live and simulated, one failing at a `fail` step, a loop, and one held by a 10-minute delay to be
    cancelled. A refused run isn't seeded (a refusal by hand isn't recorded), nor a waiting one (it starts at once):
    both are unit-tested. Cost: those two boards' states are checked in jsdom only.

## File Structure

New, under `frontend/src/`:
- `lib/runStatus.ts`: the vocabulary (Task 2; `took`, Task 8; `STEP_STATUS`, Task 10).
- `lib/runs.ts`: the API's run routes, the filters, the list's paging and merge, cancel (Task 3; the filters'
  validation, Task 4).
- `lib/when.ts`: when, in the person's zone (Task 3; `timeOf`, Task 6). `lib/media.ts`: `useNarrow` (Task 4).
- `components/RunChips.tsx`: a status chip, Live and Simulated (Task 2). `components/LazyPage.tsx`: the lazy loader,
  `components/When.tsx`: a time (Task 4).
- `routes/runs/`:
  - `LazyRuns.tsx`, `trigger.tsx`, `RunsPage.tsx` (Task 4), `Filters.tsx` (Task 5);
  - `RunPage.tsx` (Task 4, grown by Tasks 9–13), `useRunReads.ts`, `RunBar.tsx` (Task 9), `RunResult.tsx` (Task 10,
    grown by Tasks 11 and 13), `useCancel.ts` (Task 12), `StartDrawer.tsx` (Task 13).
- `routes/editor/useCanvasNav.ts` (Task 7); `routes/editor/simulation/IterationPicker.tsx` (Task 11).
- `test/runs.ts`: runs for tests (Task 3, grown by Tasks 9 and 11).
- Each with its test beside it. `e2e/runs.spec.ts` and three fixtures (Task 15).

Changed:
- `router.tsx`, `components/Shell.tsx` (Task 4); `components/Button.tsx` (Tasks 4, 14); `components/ConfirmDialog.tsx`
  (Task 12).
- `routes/Workflows.tsx` (Tasks 2, 14).
- `routes/editor/`: `LazyEditor.tsx` (Task 4); `Editor.tsx` (Tasks 7, 9, 10, 14); `Canvas.tsx`, `StepCard.tsx`,
  `StartCard.tsx` (Task 9); `drawer/StepDrawer.tsx`, `drawer/context.ts`, `drawer/PillDetails.tsx` (Task 10).
- `routes/editor/simulation/`: `lifecycle.ts` (Tasks 2, 9), `chips.tsx`, `StepResult.tsx` (Task 2); `results.ts`,
  `SimTags.tsx`
  (Task 8); `loopBody.ts`, `Iterations.tsx`, `SimulationResult.tsx`, `LatestResult.tsx` (Task 11);
  `SimulationPanel.tsx` (Tasks 2, 14).
- `test/setup.ts` (Task 4); `e2e/workflows.spec.ts` (Task 9); `playwright.config.ts` (Task 15).
- Docs: the ledger.

## Milestones

1. **The list** (Tasks 1–6): the ledger, the vocabulary, the API layer, the routes and the list, the filters, its
   reading. **Pause:** the owner's review.
2. **A run's page** (Tasks 7–11): the shared keyboard, a run's tags, the page, its step's result, a loop. **Pause:**
   the owner's review.
3. **Cancel, other runs, the ways in** (Tasks 12–14). **Pause:** the owner's review.
4. **Close** (Tasks 15–16): the e2e specs, every check, the final checkpoint. **Pause:** a fresh reviewer, the
   summary; then stop.

## How to run things

Every command runs from the plan's worktree. `$WT` is that worktree's root. Each command is written out whole.

- **The frontend's locked packages.** From `$WT/frontend`, `npx --offline pnpm@12.6.0 install --frozen-lockfile
  --offline` restores them from the local store, the lockfile untouched. It installs packages, so the owner's OK is
  asked at the start.
- **Tests.** From `$WT/frontend`: `npx --offline pnpm@12.6.0 exec vitest run <files>`. The editor's test file takes
  about 35 s; a task's run, under a minute.
- **A diff.** Copy the block, between its fences, to a file in the plan's workspace. Then, from `$WT`:
  `git apply --check <file> && git apply <file>`. Expected: no output. A diff that doesn't apply means the tree
  differs from what the previous task left: stop and compare, never apply by hand.
- **Static checks.** From `$WT/frontend`: `npx --offline pnpm@12.6.0 exec tsc -b --noEmit` and
  `npx --offline pnpm@12.6.0 exec eslint .`. Expected: no output from either.
- **The whole frontend suite**, at the end: `npx --offline pnpm@12.6.0 exec vitest run` (about 2 minutes), then
  `npx --offline pnpm@12.6.0 build`.
- **The e2e specs** run against the Compose stack, as CI's e2e job does. Locally, building the stack takes long: the
  owner is asked first.
- **Local CodeQL**, at the end: `scratchpad/codeql/scan-js.sh <name> <dir>` on a `git archive` of the head (CLI 2.27.2,
  javascript-queries 2.4.7, CI's query filter; about a minute).

## Executing this plan

- **Inline**, by one implementing agent in one session, with the owner's reviews at the milestone pauses, and a fresh
  independent review at the end. Test-first, as each task's steps say. The owner chooses.
- **The branch** is settled with the owner at the start. The default proposed: `feat/editor-4e1b` from `origin/main`
  (cb7425db, or later), in its own worktree (`~/4_dev/mist_dewpoint-4e1b`), with the docs branch
  `docs/editor-ui-4e1b-plan` (this plan) merged into it first. A later main is merged in, never rebased.
- **Where the code base differs from a step**, the executor stops at the diff that doesn't apply, adapts it test-first
  and records the difference as a mid-slice ruling in the ledger (M104 onward).
- **The rulings above** join the ledger only when the owner accepts the plan; until then the ledger says they're
  proposed.

---

# Milestone 1 — The list

### Task 1: The ledger: 4e-1a merged, this plan proposed

**Files:**
- Modify: `docs/superpowers/plans/2026-10-05-editor-ui-4-ledger.md` (append at the end)

**Interfaces:**
- Consumes: nothing.
- Produces: the ledger sections later tasks append to (`### 4e-1b, milestone N`).

- [ ] **Step 1: Append the plan's status**

Append exactly:

```markdown
### 4e-1a merged; the 4e-1b plan proposed (2026-10-16)

The owner merged 4e-1a as #116 (squash cb7425db), CI green ("green and merged"); its three deferred minors are issue
#117. `docs/superpowers/plans/2026-10-16-editor-ui-4e1b-runs-ui.md`, revision 1: the UI of the runs design §5, one
plan with milestone pauses, as 4d-1c's. Its rulings (1–30) are proposed, and join this ledger as 230 onward only when
the owner accepts the plan. Mid-slice rulings start at M104. The frontend only: no backend change, no migration, no
ABI change; the API is 4e-1a's.
```

- [ ] **Step 2: Commit**

```bash
git add docs/superpowers/plans/2026-10-05-editor-ui-4-ledger.md
git commit -m "docs(editor-4): 4e-1a merged, the 4e-1b plan proposed

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: One status vocabulary

**Spec:** §5.5 (the words), §3's answer 5 ("Ran out of time" everywhere); the Main board's chips.

**Files:**
- Create: `frontend/src/lib/runStatus.ts`, `frontend/src/lib/runStatus.test.ts`
- Create: `frontend/src/components/RunChips.tsx`, `frontend/src/components/RunChips.test.tsx`
- Modify: `frontend/src/routes/editor/simulation/lifecycle.ts`,
  `frontend/src/routes/editor/simulation/lifecycle.test.ts`
- Modify: `frontend/src/routes/editor/simulation/chips.tsx`,
  `frontend/src/routes/editor/simulation/SimulationPanel.tsx`,
  `frontend/src/routes/editor/simulation/StepResult.tsx`
- Modify: `frontend/src/routes/Workflows.tsx`

**Interfaces:**
- Consumes: `Schemas["RunItemOut"]["status"]` (4e-1a's client).
- Produces:
  - `lib/runStatus.ts`: `type RunStatus`; `type Tone = "waiting" | "running" | "ok" | "danger" | "neutral"`;
    `RUN_STATUS: Record<RunStatus, { word: string; tone: Tone }>`; `duration(from, to): string | null` and
    `runId(id): string` (moved from `lifecycle.ts`); `reasonWords(code: string | null): string | null`.
  - `components/RunChips.tsx`: `ToneChip({ tone, children })`, `RunStatusChip({ status })`, `ModeChip({ mode, draft })`
    (Live in orange; Simulated or Draft simulation, hatched).
  - `lifecycle.ts`'s `STATUS` built from `RUN_STATUS`, "Not simulated" kept for a refusal (ruling 2).

One module words every run's status and says how it looks: queued and starting dashed, running in the accent,
succeeded and failed in their colours, "Ran out of time" for a deadline, "Couldn't start" and "Refused". A request that
didn't start is worded from its code (ruling 3). The Workflows list and the Simulation panel take it: the panel says
"Ran out of time" (the owner's answer 5).

- [ ] **Step 1: Write the failing tests**

Apply:

```diff
diff --git a/frontend/src/components/RunChips.test.tsx b/frontend/src/components/RunChips.test.tsx
new file mode 100644
index 00000000..5bdc5920
--- /dev/null
+++ b/frontend/src/components/RunChips.test.tsx
@@ -0,0 +1,30 @@
+// SPDX-License-Identifier: Apache-2.0
+import { render, screen } from "@testing-library/react";
+import { expect, it } from "vitest";
+import { ModeChip, RunStatusChip } from "./RunChips";
+
+it("says a run's status in words, its look only repeating them: dashed while it waits, the accent while it runs", () => {
+  render(
+    <p>
+      <RunStatusChip status="queued" />
+      <RunStatusChip status="running" />
+      <RunStatusChip status="deadline_exceeded" />
+    </p>,
+  );
+  expect(screen.getByText("Queued").className).toContain("border-dashed");
+  expect(screen.getByText("Running").className).toContain("border-accent");
+  expect(screen.getByText("Ran out of time").className).toContain("border-danger");
+});
+
+it("says what a run was: live in orange, a simulation hatched in slate, a draft's said so (D2, D3)", () => {
+  render(
+    <p>
+      <ModeChip mode="live" draft={false} />
+      <ModeChip mode="simulate" draft={false} />
+      <ModeChip mode="simulate" draft />
+    </p>,
+  );
+  expect(screen.getByText("Live").className).toContain("text-live");
+  expect(screen.getByText("Simulated").className).toContain("hatch-sim");
+  expect(screen.getByText("Draft simulation").className).toContain("hatch-sim");
+});
diff --git a/frontend/src/lib/runStatus.test.ts b/frontend/src/lib/runStatus.test.ts
new file mode 100644
index 00000000..ea89c806
--- /dev/null
+++ b/frontend/src/lib/runStatus.test.ts
@@ -0,0 +1,39 @@
+// SPDX-License-Identifier: Apache-2.0
+import { describe, expect, it } from "vitest";
+import { RUN_STATUS, duration, reasonWords, runId } from "./runStatus";
+
+describe("a run's status, in one vocabulary (the runs design §5.5)", () => {
+  it("words each status, and says how it looks, as every screen that shows a run does", () => {
+    expect(Object.fromEntries(Object.entries(RUN_STATUS).map(([k, v]) => [k, [v.word, v.tone]]))).toEqual({
+      queued: ["Queued", "waiting"],
+      starting: ["Starting", "waiting"],
+      running: ["Running", "running"],
+      succeeded: ["Succeeded", "ok"],
+      failed: ["Failed", "danger"],
+      deadline_exceeded: ["Ran out of time", "danger"],
+      cancelled: ["Cancelled", "neutral"],
+      dead: ["Couldn't start", "danger"],
+      refused: ["Refused", "danger"],
+    });
+  });
+
+  it("gives a run's duration as a person reads it", () => {
+    expect(duration("2026-10-15T10:42:05Z", "2026-10-15T10:42:19Z")).toBe("14 s");
+    expect(duration("2026-10-15T10:42:05Z", "2026-10-15T10:45:25Z")).toBe("3 min 20 s");
+    expect(duration("2026-10-15T10:00:00Z", "2026-10-15T11:02:00Z")).toBe("1 h 2 min");
+    expect(duration("2026-10-15T10:42:05Z", "2026-10-15T10:42:05.300Z")).toBe("under 1 s");
+    expect(duration(null, "2026-10-15T10:42:05Z")).toBeNull();
+  });
+
+  it("names a run by its id's first eight characters", () => {
+    expect(runId("7c1e9a40-3b2d-4e5f-9a1b-2c3d4e5f6a7b")).toBe("7c1e9a40");
+  });
+
+  it("words why a run didn't start, from its code, and has no words for a code it doesn't know", () => {
+    expect(reasonWords("start_throttled")).toBe("Too many runs were starting at once.");
+    expect(reasonWords("input_invalid")).toBe("Its input didn't fit the workflow's input.");
+    expect(reasonWords("schedule_paused")).toBe("Its schedule was disabled.");
+    expect(reasonWords("a_code_from_later")).toBeNull();
+    expect(reasonWords(null)).toBeNull();
+  });
+});
diff --git a/frontend/src/routes/editor/simulation/lifecycle.test.ts b/frontend/src/routes/editor/simulation/lifecycle.test.ts
index 756e8236..ac910a85 100644
--- a/frontend/src/routes/editor/simulation/lifecycle.test.ts
+++ b/frontend/src/routes/editor/simulation/lifecycle.test.ts
@@ -1,7 +1,7 @@
 // SPDX-License-Identifier: Apache-2.0
 import { describe, expect, it } from "vitest";
 import type { StepSummary } from "../../../lib/simulations";
-import { duration, endedWhat, runId, stepsEnded } from "./lifecycle";
+import { STATUS, endedWhat, stepsEnded } from "./lifecycle";
 
 const step = (key: string, statuses: Record<string, number>, origin: StepSummary["origin"] = "evaluated"): StepSummary => ({
   step_id: `id-${key}`, key, type: "flow.transform@1", origin, instances: Object.values(statuses).reduce((a, b) => a + b, 0),
@@ -9,16 +9,11 @@ const step = (key: string, statuses: Record<string, number>, origin: StepSummary
 });  // prettier-ignore
 
 describe("a simulation's lifecycle, in words (§7.2, §7.5; the Lifecycle board)", () => {
-  it("gives a run's duration as a person reads it", () => {
-    expect(duration("2026-10-15T10:42:05Z", "2026-10-15T10:42:19Z")).toBe("14 s");
-    expect(duration("2026-10-15T10:42:05Z", "2026-10-15T10:45:25Z")).toBe("3 min 20 s");
-    expect(duration("2026-10-15T10:00:00Z", "2026-10-15T11:02:00Z")).toBe("1 h 2 min");
-    expect(duration("2026-10-15T10:42:05Z", "2026-10-15T10:42:05.300Z")).toBe("under 1 s");
-    expect(duration(null, "2026-10-15T10:42:05Z")).toBeNull();
-  });
-
-  it("names a run by its id's first eight characters", () => {
-    expect(runId("7c1e9a40-3b2d-4e5f-9a1b-2c3d4e5f6a7b")).toBe("7c1e9a40");
+  it("words a simulation's status as every run's, keeping \"Not simulated\" for its own refusals (the runs design §5.5)", () => {
+    expect(STATUS.deadline_exceeded).toBe("Ran out of time");
+    expect(STATUS.dead).toBe("Couldn't start");
+    expect(STATUS.refused).toBe("Not simulated");
+    expect(STATUS.cancel_requested).toBe("Running");
   });
 
   it("counts the steps that have ended while it runs", () => {
```

- [ ] **Step 2: Run them**

Run: `npx --offline pnpm@12.6.0 exec vitest run src/lib/runStatus.test.ts src/components/RunChips.test.tsx
src/routes/editor/simulation/lifecycle.test.ts src/routes/Workflows.test.tsx
src/routes/editor/simulation/SimulationPanel.test.tsx`

Expected: FAIL, 1 failed and 22 passed: `runStatus.test.ts` and `RunChips.test.tsx` can't import their modules; the
panel's words still say "Deadline exceeded" (`expected 'Deadline exceeded' to be 'Ran out of time'`). The Workflows
list's and the panel's tests pass: their words for a status don't change.

- [ ] **Step 3: Implement**

Apply:

```diff
diff --git a/frontend/src/components/RunChips.tsx b/frontend/src/components/RunChips.tsx
new file mode 100644
index 00000000..56ba605a
--- /dev/null
+++ b/frontend/src/components/RunChips.tsx
@@ -0,0 +1,32 @@
+// SPDX-License-Identifier: Apache-2.0
+// A run's status and what it was, as chips (editor 4e-1; the runs design §5.5; the Main and RunFailed boards): words
+// first, the look only repeating them. Live is orange (D3); a simulation is slate with the hatch (D2), which sits only
+// behind slate text (`text-sim`), at 4.5:1 over it.
+import type { ReactNode } from "react";
+import { RUN_STATUS, type RunStatus, type Tone } from "../lib/runStatus";
+
+const TONE: Record<Tone, string> = {
+  waiting: "border-dashed border-line-control text-muted",
+  running: "border-accent text-accent-ink",
+  ok: "border-ok text-ok",
+  danger: "border-danger text-danger",
+  neutral: "border-line-strong text-muted",
+};
+
+export function ToneChip({ tone, children }: { tone: Tone; children: ReactNode }) {
+  return <span className={`rounded-md border px-1.5 text-meta whitespace-nowrap ${TONE[tone]}`}>{children}</span>;
+}
+
+export function RunStatusChip({ status }: { status: RunStatus }) {
+  return <ToneChip tone={RUN_STATUS[status].tone}>{RUN_STATUS[status].word}</ToneChip>;
+}
+
+/** Live, or a simulation of a published version, or of a draft. */
+export function ModeChip({ mode, draft }: { mode: "live" | "simulate"; draft: boolean }) {
+  if (mode === "live") return <span className="rounded-md border border-live bg-live-bg px-1.5 text-meta whitespace-nowrap text-live">Live</span>;
+  return (
+    <span className="hatch-sim rounded-md border border-sim bg-sim-bg px-1.5 text-meta whitespace-nowrap text-sim">
+      {draft ? "Draft simulation" : "Simulated"}
+    </span>
+  );
+}
diff --git a/frontend/src/lib/runStatus.ts b/frontend/src/lib/runStatus.ts
new file mode 100644
index 00000000..ca5a9442
--- /dev/null
+++ b/frontend/src/lib/runStatus.ts
@@ -0,0 +1,69 @@
+// SPDX-License-Identifier: Apache-2.0
+// A run's status in words (editor 4e-1; the runs design §5.5): one vocabulary for the Runs page, a run's page, the
+// Workflows list and the Simulation panel. Each status has its word and its look; the look only repeats the word. And
+// what a run's facts read as everywhere: its name, how long it ran, why it didn't start.
+import type { Schemas } from "./client";
+
+export type RunStatus = Schemas["RunItemOut"]["status"];
+
+/** How a status looks: dashed and neutral while it waits, the accent while it runs, ok, danger, or neutral. */
+export type Tone = "waiting" | "running" | "ok" | "danger" | "neutral";
+
+export const RUN_STATUS: Record<RunStatus, { word: string; tone: Tone }> = {
+  queued: { word: "Queued", tone: "waiting" },
+  starting: { word: "Starting", tone: "waiting" },
+  running: { word: "Running", tone: "running" },
+  succeeded: { word: "Succeeded", tone: "ok" },
+  failed: { word: "Failed", tone: "danger" },
+  deadline_exceeded: { word: "Ran out of time", tone: "danger" },
+  cancelled: { word: "Cancelled", tone: "neutral" },
+  dead: { word: "Couldn't start", tone: "danger" },
+  refused: { word: "Refused", tone: "danger" },
+};
+
+/** How long a run ran, as a person reads it: "14 s", "3 min 20 s", "1 h 2 min"; null when either end is unknown. */
+export function duration(from: string | null, to: string | null): string | null {
+  if (from === null || to === null) return null;
+  const s = Math.round((Date.parse(to) - Date.parse(from)) / 1000);
+  if (s < 1) return "under 1 s";
+  if (s < 60) return `${s} s`;
+  if (s < 3600) return `${Math.floor(s / 60)} min${s % 60 ? ` ${s % 60} s` : ""}`;
+  return `${Math.floor(s / 3600)} h${Math.floor((s % 3600) / 60) ? ` ${Math.floor((s % 3600) / 60)} min` : ""}`;
+}
+
+/** A run named by its id's first eight characters (a run's id is its request's). */
+export const runId = (id: string) => id.slice(0, 8);
+
+// Why a request never started (admission's refusals, the dispatcher's dead starts): the request keeps only its code
+// (4e-1a ruling 4), so the code is worded here. A code from a later server has no words: its code is shown alone.
+const REASONS: Record<string, string> = {
+  input_invalid: "Its input didn't fit the workflow's input.",
+  tenant_erasing: "The tenant is being erased: it starts no run.",
+  production_runs_disabled: "Production runs are off in this deployment.",
+  environment_not_recorded: "This deployment's environment isn't recorded, so it starts no live run.",
+  workflow_disabled: "The workflow is disabled.",
+  not_active: "The workflow has no published version.",
+  no_current_build: "No current build was recorded, so its version couldn't be checked.",
+  version_unusable: "Its version can't run on the current build.",
+  node_type_retired: "A step type it uses has been retired.",
+  cel_profile_retired: "The formula profile it was checked against has been retired.",
+  csv_not_declared: "The workflow takes no CSV file.",
+  csv_mapping_invalid: "The CSV file's columns didn't map to the workflow's.",
+  upload_not_found: "Its CSV upload wasn't found.",
+  upload_expired: "Its CSV upload had expired.",
+  upload_consumed: "Its CSV upload had already started a run.",
+  target_invalid: "The step it tested can't run alone.",
+  csv_not_simulated: "A CSV file can't be simulated yet.",
+  schedule_paused: "Its schedule was disabled.",
+  schedule_deleted: "Its schedule was deleted.",
+  schedule_catchup_expired: "Its tick was past its schedule's catch-up window.",
+  envelope_unreadable: "Its input couldn't be opened to start it.",
+  id_collision: "Another run held its id.",
+  start_check_unavailable: "Its start couldn't be checked: an infrastructure failure.",
+  start_throttled: "Too many runs were starting at once.",
+  start_refused: "Its start was refused.",
+  start_abandoned: "An operator ended it before it started.",
+};
+
+/** Why a request didn't start, in words; null for no code, or one these words don't know. */
+export const reasonWords = (code: string | null): string | null => (code === null ? null : (REASONS[code] ?? null));
diff --git a/frontend/src/routes/Workflows.tsx b/frontend/src/routes/Workflows.tsx
index c524976d..3c1ca80d 100644
--- a/frontend/src/routes/Workflows.tsx
+++ b/frontend/src/routes/Workflows.tsx
@@ -15,6 +15,7 @@ import { Table, Td, Th } from "../components/Table";
 import { announce } from "../lib/announce";
 import { ApiError, client, ok } from "../lib/client";
 import { downloadJson, fileName } from "../lib/download";
+import { RUN_STATUS, type Tone } from "../lib/runStatus";
 import { useDocumentTitle } from "../lib/title";
 import { attentionWords, triggerColumn } from "../lib/triggers";
 import { canEdit, canPublish, notPortable, since, tenantQuery, workflowsQuery, type PortableProblem, type WorkflowRow } from "../lib/workflows";
@@ -30,13 +31,8 @@ const FILTERS: { value: Filter; label: string; keep: (w: WorkflowRow) => boolean
   { value: "attention", label: "Needs attention", keep: (w) => w.needs_attention.length > 0 },
 ];
 
-const STATUS: Record<NonNullable<WorkflowRow["last_run"]>["status"], { text: string; dot: string }> = {
-  running: { text: "Running", dot: "bg-accent" },
-  succeeded: { text: "Succeeded", dot: "bg-ok" },
-  failed: { text: "Failed", dot: "bg-danger" },
-  cancelled: { text: "Cancelled", dot: "bg-line-strong" },
-  deadline_exceeded: { text: "Ran out of time", dot: "bg-danger" },
-};
+// A run's status in every run's words (the runs design §5.5), its dot repeating them.
+const DOT: Record<Tone, string> = { waiting: "bg-line-strong", running: "bg-accent", ok: "bg-ok", danger: "bg-danger", neutral: "bg-line-strong" };
 
 function Version({ w }: { w: WorkflowRow }) {
   if (w.active_version_number === null) return <span className="text-muted">Not published</span>;
@@ -57,13 +53,13 @@ function LastRun({ w }: { w: WorkflowRow }) {
     <span className="flex flex-col gap-0.5 text-small">
       {live ? (
         <span className="inline-flex items-center gap-2">
-          <span aria-hidden="true" className={`size-2 rounded-sm ${STATUS[live.status].dot}`} />
-          {STATUS[live.status].text} · {since(live.at)}
+          <span aria-hidden="true" className={`size-2 rounded-sm ${DOT[RUN_STATUS[live.status].tone]}`} />
+          {RUN_STATUS[live.status].word} · {since(live.at)}
         </span>
       ) : (
         <span className="text-muted">No live runs yet</span>
       )}
-      {simulated && <span className="text-sim">Simulated: {STATUS[simulated.status].text} · {since(simulated.at)}</span>}
+      {simulated && <span className="text-sim">Simulated: {RUN_STATUS[simulated.status].word} · {since(simulated.at)}</span>}
     </span>
   );
 }
diff --git a/frontend/src/routes/editor/simulation/SimulationPanel.tsx b/frontend/src/routes/editor/simulation/SimulationPanel.tsx
index 3bef4523..0dcfe20f 100644
--- a/frontend/src/routes/editor/simulation/SimulationPanel.tsx
+++ b/frontend/src/routes/editor/simulation/SimulationPanel.tsx
@@ -5,10 +5,11 @@
 // banner, the checks on the server, the steps, the input used) come in below the lifecycle as `children`.
 import { useEffect, useRef, type ReactNode } from "react";
 import { Button } from "../../../components/Button";
+import { duration, runId } from "../../../lib/runStatus";
 import { ENDED } from "../../../lib/simulations";
 import { SIDE } from "../side";
 import { SimulatedChip, StatusChip } from "./chips";
-import { clock, duration, endedWhat, lineOf, runId } from "./lifecycle";
+import { clock, endedWhat, lineOf } from "./lifecycle";
 import type { SimulationSession } from "./useSimulation";
 
 export function SimulationPanel({ session, onSimulateAgain, onClose, children }: {
diff --git a/frontend/src/routes/editor/simulation/StepResult.tsx b/frontend/src/routes/editor/simulation/StepResult.tsx
index 79271e86..6eebaab4 100644
--- a/frontend/src/routes/editor/simulation/StepResult.tsx
+++ b/frontend/src/routes/editor/simulation/StepResult.tsx
@@ -5,10 +5,11 @@
 // redacted) and its output.
 import type { ReactNode } from "react";
 import { Button } from "../../../components/Button";
+import { runId } from "../../../lib/runStatus";
 import { ENDED, type StepSummary } from "../../../lib/simulations";
 import { StatusChip } from "./chips";
 import { Failure } from "./Failure";
-import { lineOf, runId } from "./lifecycle";
+import { lineOf } from "./lifecycle";
 import { field, originTag } from "./results";
 import { SimBanner } from "./SimBanner";
 import { InlineTags } from "./SimTags";
diff --git a/frontend/src/routes/editor/simulation/chips.tsx b/frontend/src/routes/editor/simulation/chips.tsx
index 6db8fb32..b53b97ba 100644
--- a/frontend/src/routes/editor/simulation/chips.tsx
+++ b/frontend/src/routes/editor/simulation/chips.tsx
@@ -1,19 +1,15 @@
 // SPDX-License-Identifier: Apache-2.0
 // A simulation's status and what it is, as chips (4d-1c; the Lifecycle and ResultPanel boards): words first, the
-// colour only repeating them (§7.4). Simulated results are slate (D2), never live orange (D3).
+// colour only repeating them (§7.4), in every run's vocabulary (4e-1). Simulated results are slate (D2), never live
+// orange (D3).
+import { ToneChip } from "../../../components/RunChips";
+import { RUN_STATUS } from "../../../lib/runStatus";
 import type { Phase } from "../../../lib/simulations";
 import { STATUS } from "./lifecycle";
 
-const TONE: Partial<Record<Phase, string>> = {
-  succeeded: "border-ok text-ok",
-  failed: "border-danger text-danger",
-  deadline_exceeded: "border-danger text-danger",
-  dead: "border-danger text-danger",
-  refused: "border-danger text-danger",
-};
-
+/** Its status, looking as every run's does (the runs design §5.5); a cancel asked for, as running. */
 export function StatusChip({ phase }: { phase: Phase }) {
-  return <span className={`rounded-md border px-1.5 text-meta ${TONE[phase] ?? "border-line-strong text-muted"}`}>{STATUS[phase]}</span>;
+  return <ToneChip tone={phase === "cancel_requested" ? "running" : RUN_STATUS[phase].tone}>{STATUS[phase]}</ToneChip>;
 }
 
 export function SimulatedChip() {
diff --git a/frontend/src/routes/editor/simulation/lifecycle.ts b/frontend/src/routes/editor/simulation/lifecycle.ts
index be71655f..009864e9 100644
--- a/frontend/src/routes/editor/simulation/lifecycle.ts
+++ b/frontend/src/routes/editor/simulation/lifecycle.ts
@@ -2,35 +2,18 @@
 // A simulation's lifecycle in words (4d-1c; the simulation design §7.2, §7.5; the Lifecycle, Running and ResultPanel
 // boards): its status, how long it ran, which run it is, how far it got, and how it ended, naming the step that
 // decided it, from the server's per-step summary in run order.
+import { RUN_STATUS } from "../../../lib/runStatus";
 import type { Phase, StepSummary } from "../../../lib/simulations";
 import type { SimulationSession } from "./useSimulation";
 
+/** Every run's words (the runs design §5.5), but a simulation the server refused, which is "Not simulated", and one
+ * whose cancel is asked, still running until the server says it's cancelled. */
 export const STATUS: Record<Phase, string> = {
-  queued: "Queued",
-  starting: "Starting",
-  running: "Running",
-  cancel_requested: "Running", // still going: it's cancelled once the server says so
-  succeeded: "Succeeded",
-  failed: "Failed",
-  cancelled: "Cancelled",
-  deadline_exceeded: "Deadline exceeded",
+  ...(Object.fromEntries(Object.entries(RUN_STATUS).map(([status, s]) => [status, s.word])) as Record<keyof typeof RUN_STATUS, string>),
+  cancel_requested: "Running",
   refused: "Not simulated",
-  dead: "Couldn't start",
 };
 
-/** How long a run ran, as a person reads it: "14 s", "3 min 20 s", "1 h 2 min"; null when either end is unknown. */
-export function duration(from: string | null, to: string | null): string | null {
-  if (from === null || to === null) return null;
-  const s = Math.round((Date.parse(to) - Date.parse(from)) / 1000);
-  if (s < 1) return "under 1 s";
-  if (s < 60) return `${s} s`;
-  if (s < 3600) return `${Math.floor(s / 60)} min${s % 60 ? ` ${s % 60} s` : ""}`;
-  return `${Math.floor(s / 3600)} h${Math.floor((s % 3600) / 60) ? ` ${Math.floor((s % 3600) / 60)} min` : ""}`;
-}
-
-/** A run named by its id's first eight characters (a run's id is its request's). */
-export const runId = (id: string) => id.slice(0, 8);
-
 /** The time of day an instant was, to the second, as the person's clock says it. */
 export const clock = (iso: string) => new Date(iso).toLocaleTimeString("en-GB");
 
```

- [ ] **Step 4: Run them again**

Run: the same command.

Expected: PASS, 29 passed.

- [ ] **Step 5: Static checks**

Run: the two of "How to run things". Expected: no output.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib frontend/src/components frontend/src/routes
git commit -m "feat(editor): one status vocabulary for every run, \"Ran out of time\" everywhere (4e-1b)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: The runs, from the API

**Spec:** §4 (4e-1a's routes), §5.1 (the filters in the address), §5.2 (the filters, the paging), §3's answer 8 (times).

**Files:**
- Create: `frontend/src/lib/runs.ts`, `frontend/src/lib/runs.test.ts`
- Create: `frontend/src/lib/when.ts`, `frontend/src/lib/when.test.ts`
- Create: `frontend/src/test/runs.ts`

**Interfaces:**
- Consumes: `client`, `ok`, `Schemas` (`lib/client.ts`).
- Produces:
  - `lib/runs.ts`: the types `RunItem`, `Run`, `RunSteps`, `RunStepSummary`, `RunStep`, `RunInput`, `Cancel`,
    `RunOrigin`; `PAGE = 50`; `RunFilters { workflow?, status?, trigger?, mode?, started? }` and their value types;
    `validateRunsSearch(search)`, `searchOf(filters)`, `paramsOf(filters, now)`; `runsQuery(tenantId, filters,
  cursor?)`;
    `listed(first, earlier)`, `cursorOf(items)`, `type Cursor`; `isEnded(status)`; `runQuery`, `runStepsQuery`,
    `runInstancesQuery(tenantId, runId, stepId, { offset, limit, within? })`, `runAttemptsQuery(tenantId, runId,
    stepId, iteration)`, `runInputQuery`; `cancelRun(tenantId, requestId): Promise<Cancel>`; `canCancel(role)`.
  - `lib/when.ts`: `when(iso, now?)`, `whenFull(iso)`.
  - `test/runs.ts`: `item(id, queuedAt, over?)`, a list item for tests.

The filters live in the address, each value one it allows, the defaults left out ("Live and simulated", the last 24
hours); `paramsOf` says what each asks of the API (§4.2's five modes, the window counted from now). A page of runs
reads after a cursor; `listed` keeps the first page as last read and the runs read earlier that sort after it, each once
(ruling 4). Times say "today", "yesterday" or the date, to the second, in the person's zone.

- [ ] **Step 1: Write the failing tests**

Apply:

```diff
diff --git a/frontend/src/lib/runs.test.ts b/frontend/src/lib/runs.test.ts
new file mode 100644
index 00000000..66b17fb8
--- /dev/null
+++ b/frontend/src/lib/runs.test.ts
@@ -0,0 +1,100 @@
+// SPDX-License-Identifier: Apache-2.0
+import { QueryClient } from "@tanstack/react-query";
+import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
+import { item } from "../test/runs";
+import {
+  PAGE, canCancel, cancelRun, cursorOf, isEnded, listed, paramsOf, runsQuery, searchOf, validateRunsSearch, type RunItem,
+} from "./runs";  // prettier-ignore
+
+const at = (minute: number) => `2026-10-16T10:${String(minute).padStart(2, "0")}:00Z`;
+/** A full first page, newest first: minutes 59 down. */
+const firstPage = (from = 59) => Array.from({ length: PAGE }, (_, i) => item(`n${from - i}`, at(from - i)));
+
+let sent: URL[];
+beforeEach(() => {
+  sent = [];
+  vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
+    const request = input as Request;
+    sent.push(new URL(request.url));
+    const answer = request.method === "POST" ? { cancel: "requested", request: { id: "r1", status: "starting" } } : [];
+    return Promise.resolve(new Response(JSON.stringify(answer)));
+  });
+});
+afterEach(() => vi.restoreAllMocks());
+
+describe("the Runs page's filters, in the address (the runs design §5.1, §5.2)", () => {
+  it("reads each filter from the address, keeping only a value it allows", () => {
+    expect(validateRunsSearch({ workflow: "w1", status: "failed", trigger: "rerun", mode: "drafts", started: "7d" })).toEqual({
+      workflow: "w1", status: "failed", trigger: "rerun", mode: "drafts", started: "7d",
+    });  // prettier-ignore
+    expect(validateRunsSearch({ status: "awaiting_approval", trigger: "dev", mode: "all", started: "1y", workflow: 3 })).toEqual({});
+  });
+
+  it("writes only the filters that aren't their default, so the plain list has a plain address", () => {
+    expect(searchOf({ mode: "both", started: "24h" })).toEqual({});
+    expect(searchOf({ workflow: "w1", status: "running", mode: "live", started: "all" })).toEqual({
+      workflow: "w1", status: "running", mode: "live", started: "all",
+    });  // prettier-ignore
+  });
+
+  it("asks the API for what each filter means, the start of its window counted from now", () => {
+    const now = Date.parse("2026-10-16T12:00:00Z");
+    expect(paramsOf({}, now)).toEqual({ draft: "exclude", since: "2026-10-15T12:00:00.000Z" });
+    expect(paramsOf({ mode: "live", started: "1h" }, now)).toEqual({ mode: "live", draft: "exclude", since: "2026-10-16T11:00:00.000Z" });
+    expect(paramsOf({ mode: "simulated", started: "30d" }, now)).toEqual({ mode: "simulate", draft: "exclude", since: "2026-09-16T12:00:00.000Z" });
+    expect(paramsOf({ mode: "drafts", started: "all", status: "didnt_start", trigger: "schedule", workflow: "w1" }, now)).toEqual({
+      draft: "only", status: "didnt_start", source: "schedule", workflow_id: "w1",
+    });  // prettier-ignore
+    expect(paramsOf({ mode: "everything", started: "all" }, now)).toEqual({ draft: "include" });
+  });
+});
+
+describe("reading the list (§5.2)", () => {
+  it("reads a page of runs, newest first, after a cursor when one is given", async () => {
+    await new QueryClient().query(runsQuery("t1", { status: "failed", started: "all" }, { before: at(1), before_id: "n1" }));
+    const url = sent[0]!;
+    expect(url.pathname).toBe("/api/v1/t/t1/runs");
+    expect(Object.fromEntries(url.searchParams)).toEqual({ status: "failed", draft: "exclude", before: at(1), before_id: "n1", limit: String(PAGE) });
+  });
+
+  it("lists the first page alone when it holds every match: a run read earlier and gone from it no longer matches", () => {
+    const first = [item("a", at(5)), item("b", at(4))];
+    expect(listed(first, [item("c", at(3)), item("x", at(4), { status: "running" })]).map((i) => i.id)).toEqual(["a", "b"]);
+  });
+
+  it("keeps the runs read earlier that sort after a full first page, each once, newest first", () => {
+    const first = firstPage(); // n59 … n10
+    const earlier = [item("n12", at(12), { status: "running" }), item("n9", at(9)), item("n8", at(8)), item("n9", at(9), { status: "failed" }), item("n7", at(7))];
+    const shown = listed(first, earlier);
+    expect(shown.map((i) => i.id)).toEqual([...first.map((i) => i.id), "n9", "n8", "n7"]);
+    expect(shown.find((i) => i.id === "n12")!.status).toBe("succeeded"); // the first page's read wins
+    expect(shown.find((i) => i.id === "n9")!.status).toBe("failed"); // the later of two earlier reads
+  });
+
+  it("drops a run read earlier that sorts within the first page and isn't on it any more", () => {
+    const earlier = [item("gone", at(30), { status: "running" })];
+    expect(listed(firstPage(), earlier).some((i) => i.id === "gone")).toBe(false);
+  });
+
+  it("pages on from the last run listed, and not past one with no queue time", () => {
+    expect(cursorOf([item("a", at(5)), item("b", at(4))])).toEqual({ before: at(4), before_id: "b" });
+    expect(cursorOf([item("a", at(5)), item("old", null)])).toBeNull();
+    expect(cursorOf([])).toBeNull();
+  });
+});
+
+describe("a run's end and its cancel (§5.3)", () => {
+  it("knows an ended run from one still going", () => {
+    expect(["queued", "starting", "running"].map((s) => isEnded(s as RunItem["status"]))).toEqual([false, false, false]);
+    expect(["succeeded", "failed", "cancelled", "deadline_exceeded", "refused", "dead"].every((s) => isEnded(s as RunItem["status"]))).toBe(true);
+  });
+
+  it("cancels through the run's own route, answering what the server did", async () => {
+    expect((await cancelRun("t1", "r1")).cancel).toBe("requested");
+    expect(sent[0]!.pathname).toBe("/api/v1/t/t1/runs/r1/cancel");
+  });
+
+  it("shows Cancel to the roles that hold run.cancel: operators and up", () => {
+    expect(["viewer", "operator", "editor", "admin", "owner", undefined].map(canCancel)).toEqual([false, true, true, true, true, false]);
+  });
+});
diff --git a/frontend/src/lib/when.test.ts b/frontend/src/lib/when.test.ts
new file mode 100644
index 00000000..ea6ed6a7
--- /dev/null
+++ b/frontend/src/lib/when.test.ts
@@ -0,0 +1,18 @@
+// SPDX-License-Identifier: Apache-2.0
+import { expect, it } from "vitest";
+import { when, whenFull } from "./when";
+
+// Instants built from the person's own clock: what they read doesn't depend on the zone the tests run in.
+const local = (day: number, h: number, m: number, s: number) => new Date(2026, 9, day, h, m, s).toISOString();
+const NOW = new Date(2026, 9, 16, 12, 0, 0).getTime();
+
+it("says when, in the person's own zone: today, yesterday, else the date, each to the second (the owner's answer 8)", () => {
+  expect(when(local(16, 10, 2, 9), NOW)).toBe("today 10:02:09");
+  expect(when(local(15, 2, 0, 1), NOW)).toBe("yesterday 02:00:01");
+  expect(when(local(14, 17, 40, 2), NOW)).toBe("14 Oct 17:40:02");
+  expect(when(local(16, 0, 0, 0), NOW)).toBe("today 00:00:00");
+});
+
+it("gives the full date and time for the hover", () => {
+  expect(whenFull(local(16, 10, 2, 9))).toMatch(/^Friday, 16 October 2026 at 10:02:09 \S+/);
+});
diff --git a/frontend/src/test/runs.ts b/frontend/src/test/runs.ts
new file mode 100644
index 00000000..64578e3d
--- /dev/null
+++ b/frontend/src/test/runs.ts
@@ -0,0 +1,11 @@
+// SPDX-License-Identifier: Apache-2.0
+// Runs for tests, as the API serves them (editor 4e-1): a list item, made up, never a real tenant's (D24).
+import type { RunItem } from "../lib/runs";
+
+/** A live run a webhook started, succeeded, queued and started at `queuedAt`. */
+export const item = (id: string, queuedAt: string | null, over: Partial<RunItem> = {}): RunItem => ({
+  id, workflow_id: "w1", workflow_name: "AP offline triage", version_id: "v2", draft_snapshot_id: null, target_step_id: null,
+  mode: "live", status: "succeeded", queued_at: queuedAt, started_at: queuedAt, ended_at: null, error: null, iterations: 0,
+  kind: "run", parent_run_id: null, request: { status: "started", source: "webhook", reason: null }, started_by: null,
+  cancel_requested_at: null, trigger: { source: "webhook", schedule: null, endpoint: "Mist events", rerun_of: null }, ...over,
+});  // prettier-ignore
```

- [ ] **Step 2: Run them**

Run: `npx --offline pnpm@12.6.0 exec vitest run src/lib/runs.test.ts src/lib/when.test.ts`

Expected: FAIL: `runs.test.ts` and `when.test.ts` can't import their modules (no test runs).

- [ ] **Step 3: Implement**

Apply:

```diff
diff --git a/frontend/src/lib/runs.ts b/frontend/src/lib/runs.ts
new file mode 100644
index 00000000..8dce8bf9
--- /dev/null
+++ b/frontend/src/lib/runs.ts
@@ -0,0 +1,171 @@
+// SPDX-License-Identifier: Apache-2.0
+// A tenant's runs (editor 4e-1; the runs design §4, §5): the API's run routes as the generated schema types them (B1).
+// The Runs page's filters, kept in its address; the list as read again and paged; a run, its steps, their instances
+// and attempts, its input read back; its cancel.
+import { queryOptions } from "@tanstack/react-query";
+import { client, ok, type Schemas } from "./client";
+
+export type RunItem = Schemas["RunItemOut"];
+export type Run = Schemas["RunOut"];
+export type RunSteps = Schemas["RunStepsOut"];
+export type RunStepSummary = Schemas["RunStepSummaryOut"];
+export type RunStep = Schemas["RunStepOut"];
+export type RunInput = Schemas["RunInputOut"];
+export type Cancel = Schemas["CancelOut"];
+export type RunOrigin = RunStepSummary["origin"];
+
+/** The runs a page holds. */
+export const PAGE = 50;
+
+// The filters, one value each (§5.2). Each has a default the address leaves out: any workflow, status and trigger,
+// live runs and simulations of a published version, the last 24 hours.
+const STATUSES = ["waiting", "running", "succeeded", "failed", "deadline_exceeded", "cancelled", "didnt_start"] as const;
+const TRIGGERS = ["manual", "rerun", "schedule", "webhook"] as const;
+const MODES = ["both", "live", "simulated", "drafts", "everything"] as const;
+const STARTED = ["1h", "24h", "7d", "30d", "all"] as const;
+export type StatusFilter = (typeof STATUSES)[number];
+export type TriggerFilter = (typeof TRIGGERS)[number];
+export type ModeFilter = (typeof MODES)[number];
+export type StartedFilter = (typeof STARTED)[number];
+export interface RunFilters {
+  workflow?: string;
+  status?: StatusFilter;
+  trigger?: TriggerFilter;
+  mode?: ModeFilter;
+  started?: StartedFilter;
+}
+
+const one = <T extends string>(allowed: readonly T[], v: unknown): T | undefined => (allowed.includes(v as T) ? (v as T) : undefined);
+
+/** The filters an address holds, each value one it allows: a link keeps them (§5.1). */
+export function validateRunsSearch(search: Record<string, unknown>): RunFilters {
+  const filters: RunFilters = {
+    workflow: typeof search.workflow === "string" && search.workflow !== "" ? search.workflow : undefined,
+    status: one(STATUSES, search.status),
+    trigger: one(TRIGGERS, search.trigger),
+    mode: one(MODES, search.mode),
+    started: one(STARTED, search.started),
+  };
+  return searchOf(filters);
+}
+
+/** The filters as an address writes them: those at their default left out. */
+export function searchOf(f: RunFilters): RunFilters {
+  const kept: RunFilters = { ...f, mode: f.mode === "both" ? undefined : f.mode, started: f.started === "24h" ? undefined : f.started };
+  return Object.fromEntries(Object.entries(kept).filter(([, v]) => v !== undefined));
+}
+
+const SPAN: Record<StartedFilter, number | null> = { "1h": 3_600_000, "24h": 86_400_000, "7d": 7 * 86_400_000, "30d": 30 * 86_400_000, all: null };
+const MODE: Record<ModeFilter, { mode?: "live" | "simulate"; draft: "exclude" | "only" | "include" }> = {
+  both: { draft: "exclude" },
+  live: { mode: "live", draft: "exclude" },
+  simulated: { mode: "simulate", draft: "exclude" },
+  drafts: { draft: "only" },
+  everything: { draft: "include" },
+};
+
+/** What the filters ask of the API (§4.2); the window starts `now` less its span. */
+export function paramsOf(f: RunFilters, now: number) {
+  const span = SPAN[f.started ?? "24h"];
+  const params = {
+    workflow_id: f.workflow,
+    status: f.status,
+    source: f.trigger,
+    ...MODE[f.mode ?? "both"],
+    since: span === null ? undefined : new Date(now - span).toISOString(),
+  };
+  return Object.fromEntries(Object.entries(params).filter(([, v]) => v !== undefined)) as typeof params;
+}
+
+export interface Cursor {
+  before: string;
+  before_id: string;
+}
+
+/** A page of runs, newest first, after `cursor` when given. Its window is counted from when it's read. */
+export const runsQuery = (tenantId: string, filters: RunFilters, cursor: Cursor | null = null) =>
+  queryOptions({
+    queryKey: ["runs", tenantId, searchOf(filters), cursor],
+    queryFn: () =>
+      ok(client.GET("/api/v1/t/{tenant_id}/runs", {
+        params: { path: { tenant_id: tenantId }, query: { ...paramsOf(filters, Date.now()), ...cursor, limit: PAGE } },
+      })),
+  });  // prettier-ignore
+
+// The list's order (§4.2): newest queued first, then by id; a run with no queue time (from before 2b-2) first.
+const at = (i: RunItem) => (i.queued_at === null ? Infinity : Date.parse(i.queued_at));
+const newer = (a: RunItem, b: RunItem) => at(b) - at(a) || (a.id < b.id ? 1 : a.id > b.id ? -1 : 0);
+
+/** The list shown (§5.2): the first page as last read, then the runs read earlier that sort after its last, each
+ * once, the latest read of each. Those come from "Load more", or were pushed off the first page by newer runs: they're
+ * no longer read again. A first page that isn't full holds every match, so nothing read earlier is kept; nor is a run
+ * that sorts within the first page and isn't on it any more (it no longer matches). */
+export function listed(first: RunItem[], earlier: RunItem[]): RunItem[] {
+  const last = first.at(-1);
+  if (first.length < PAGE || last === undefined) return first;
+  const onFirst = new Set(first.map((i) => i.id));
+  const kept = new Map<string, RunItem>();
+  for (const i of earlier) if (!onFirst.has(i.id) && newer(last, i) < 0) kept.set(i.id, i);
+  return [...first, ...[...kept.values()].sort(newer)];
+}
+
+/** Where the next page starts: after the last run listed. None after a run with no queue time: nothing sorts after it. */
+export function cursorOf(items: RunItem[]): Cursor | null {
+  const last = items.at(-1);
+  return last?.queued_at ? { before: last.queued_at, before_id: last.id } : null;
+}
+
+const ENDED = new Set<RunItem["status"]>(["succeeded", "failed", "cancelled", "deadline_exceeded", "refused", "dead"]);
+export const isEnded = (status: RunItem["status"]) => ENDED.has(status);
+
+const path = (tenantId: string, runId: string) => ({ tenant_id: tenantId, run_id: runId });
+
+/** A run, or a request that hasn't started, as itself (§4.3, §4.5). */
+export const runQuery = (tenantId: string, runId: string) =>
+  queryOptions({
+    queryKey: ["run", tenantId, runId],
+    queryFn: () => ok(client.GET("/api/v1/t/{tenant_id}/runs/{run_id}", { params: { path: path(tenantId, runId) } })),
+  });
+
+/** A run's steps in run order, summarized (§4.4). */
+export const runStepsQuery = (tenantId: string, runId: string) =>
+  queryOptions({
+    queryKey: ["run-steps", tenantId, runId],
+    queryFn: () => ok(client.GET("/api/v1/t/{tenant_id}/runs/{run_id}/steps", { params: { path: path(tenantId, runId) } })),
+  });
+
+/** A page of a step's instances in a run, in iteration order, under an iteration when `within` names one (§4.4). */
+export const runInstancesQuery = (tenantId: string, runId: string, stepId: string, page: { offset: number; limit: number; within?: string }) =>
+  queryOptions({
+    queryKey: ["run-instances", tenantId, runId, stepId, page.offset, page.limit, page.within ?? null],
+    queryFn: () =>
+      ok(client.GET("/api/v1/t/{tenant_id}/runs/{run_id}/steps/{step_id}/instances", {
+        params: { path: { ...path(tenantId, runId), step_id: stepId }, query: { offset: page.offset, limit: page.limit, within: page.within } },
+      })),
+  });  // prettier-ignore
+
+/** One instance's attempts, first to last (§4.4): at most 20. */
+export const runAttemptsQuery = (tenantId: string, runId: string, stepId: string, iteration: string) =>
+  queryOptions({
+    queryKey: ["run-attempts", tenantId, runId, stepId, iteration],
+    queryFn: () =>
+      ok(client.GET("/api/v1/t/{tenant_id}/runs/{run_id}/steps/{step_id}/attempts", {
+        params: { path: { ...path(tenantId, runId), step_id: stepId }, query: { iteration } },
+      })),
+  });  // prettier-ignore
+
+/** What a run was admitted with, read back, redacted (§4.3). */
+export const runInputQuery = (tenantId: string, runId: string) =>
+  queryOptions({
+    queryKey: ["run-input", tenantId, runId],
+    queryFn: () => ok(client.GET("/api/v1/t/{tenant_id}/runs/{run_id}/input", { params: { path: path(tenantId, runId) } })),
+  });
+
+/** Cancels a run through its own route: `cancelled` when it was only queued, else `requested` (§5.3). */
+export const cancelRun = (tenantId: string, requestId: string): Promise<Cancel> =>
+  ok(client.POST("/api/v1/t/{tenant_id}/runs/{request_id}/cancel", { params: { path: { tenant_id: tenantId, request_id: requestId } } }));
+
+// The roles that hold run.cancel (backend/src/dewpoint/core/authz/permissions.py: operator and above). The UI only
+// hides what the API would refuse.
+const CANCELLERS = new Set(["owner", "admin", "editor", "operator"]);
+export const canCancel = (role?: string | null) => !!role && CANCELLERS.has(role);
diff --git a/frontend/src/lib/when.ts b/frontend/src/lib/when.ts
new file mode 100644
index 00000000..fb755415
--- /dev/null
+++ b/frontend/src/lib/when.ts
@@ -0,0 +1,19 @@
+// SPDX-License-Identifier: Apache-2.0
+// When a run happened, as the person reads it (editor 4e-1; the owner's answer 8): in their own zone, to the second,
+// "today" and "yesterday" by their calendar, else the date; the full date and zone on hover.
+const TIME = new Intl.DateTimeFormat("en-GB", { hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23" });
+const DATE = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short" });
+const FULL = new Intl.DateTimeFormat("en-GB", { dateStyle: "full", timeStyle: "long" });
+
+const dayOf = (t: Date) => new Date(t.getFullYear(), t.getMonth(), t.getDate()).getTime();
+
+/** "today 10:02:09", "yesterday 02:00:01", else "14 Oct 17:40:02". */
+export function when(iso: string, now: number = Date.now()): string {
+  const t = new Date(iso);
+  const days = Math.round((dayOf(new Date(now)) - dayOf(t)) / 86_400_000);
+  const day = days === 0 ? "today" : days === 1 ? "yesterday" : DATE.format(t);
+  return `${day} ${TIME.format(t)}`;
+}
+
+/** "Friday 16 October 2026 at 10:02:09 CEST": the full date, the time and the zone. */
+export const whenFull = (iso: string) => FULL.format(new Date(iso));
```

- [ ] **Step 4: Run them again**

Run: the same command.

Expected: PASS, 13 passed.

- [ ] **Step 5: Static checks**

Run: the two of "How to run things". Expected: no output.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib frontend/src/test
git commit -m "feat(editor): the runs from the API: filters in the address, paging, the merged list, cancel (4e-1b)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Runs on the rail, the list's rows, and a run gone

**Spec:** §5.1 (the routes, lazy chunks, the rail), §5.2 (the columns, the states), §5.4 (a run not kept), §5.6 (a
list below 640 px); the Main, ListStates, RunOther and Narrow boards.

**Files:**
- Create: `frontend/src/components/LazyPage.tsx`, `frontend/src/components/LazyPage.test.tsx`,
  `frontend/src/components/When.tsx`, `frontend/src/lib/media.ts`
- Create: `frontend/src/routes/runs/LazyRuns.tsx`, `frontend/src/routes/runs/trigger.tsx`
- Create: `frontend/src/routes/runs/RunsPage.tsx`, `frontend/src/routes/runs/RunsPage.test.tsx`
- Create: `frontend/src/routes/runs/RunPage.tsx`, `frontend/src/routes/runs/RunPage.test.tsx`
- Modify: `frontend/src/router.tsx`, `frontend/src/router.test.tsx`, `frontend/src/components/Shell.tsx`,
  `frontend/src/components/Shell.test.tsx`, `frontend/src/components/Button.tsx`, `frontend/src/lib/runs.ts`
- Modify: `frontend/src/routes/editor/LazyEditor.tsx`, `frontend/src/test/setup.ts`

**Interfaces:**
- Consumes: `RUN_STATUS`, `duration`, `runId`, `reasonWords` (Task 2); `RunStatusChip`, `ModeChip` (Task 2);
  `runsQuery`, `runQuery`, `validateRunsSearch`, `isEnded` (Task 3); `when`, `whenFull` (Task 3).
- Produces:
  - `LazyPage({ load, what, props })`; `LazyRunsPage({ tenantId, filters })`, `LazyRunPage({ tenantId, runId })`.
  - the routes `/t/$tenantId/runs` (its search validated by `validateRunsSearch`) and `/t/$tenantId/runs/$runId`
    (`staticData.compactRail`); Runs on the rail after Workflows.
  - `RunsPage({ tenantId, filters })`; `RunPage({ tenantId, runId })`.
  - `triggerOf(run): { kind, detail }`; `When({ iso })`; `useNarrow(): boolean`; `LINK_BUTTON` (a link that looks like
    a small secondary button).

Runs joins the rail after Workflows. Its page lists each run: the short id, a link; its workflow; its status, and
"Simulated" or "Draft simulation"; its trigger and what says more of it; when it started (else was queued), with the
full date on hover; how long; its error, or a request's reason and "Nothing ran." It says when it's reading, when none
ran yet, and when the first read failed, with Try again. Below 640 px the rows are a list. A run's page names the run
with the way back to Runs, and says when the run isn't kept any more, or the tenant is being erased. Both pages load
in their own chunks.

- [ ] **Step 1: Write the failing tests**

Apply:

```diff
diff --git a/frontend/src/components/LazyPage.test.tsx b/frontend/src/components/LazyPage.test.tsx
new file mode 100644
index 00000000..ba543d10
--- /dev/null
+++ b/frontend/src/components/LazyPage.test.tsx
@@ -0,0 +1,35 @@
+// SPDX-License-Identifier: Apache-2.0
+import { act, render, screen } from "@testing-library/react";
+import userEvent from "@testing-library/user-event";
+import { expect, it, vi } from "vitest";
+import { LazyPage } from "./LazyPage";
+
+const Page = ({ tenantId }: { tenantId: string }) => <p>runs of {tenantId}</p>;
+
+/** A load of a page's code that answers when the test says. */
+function held() {
+  let answer!: (ok: boolean) => void;
+  const load = vi.fn(() => new Promise<typeof Page>((resolve, reject) => (answer = (ok) => (ok ? resolve(Page) : reject(new Error("chunk"))))));
+  return { load, answer: (ok: boolean) => act(async () => { answer(ok); await Promise.resolve(); }) };
+}
+
+it("says a page's code is loading, then shows the page", async () => {
+  const { load, answer } = held();
+  render(<LazyPage load={load} what="the runs" props={{ tenantId: "t1" }} />);
+  expect(screen.getByRole("status").textContent).toBe("Loading the runs…");
+  await answer(true);
+  expect(await screen.findByText("runs of t1")).toBeTruthy();
+});
+
+it("says when a page's code can't be loaded, and tries again when asked", async () => {
+  const first = held();
+  const second = held();
+  const load = vi.fn().mockImplementationOnce(first.load).mockImplementationOnce(second.load);
+  render(<LazyPage load={load} what="the runs" props={{ tenantId: "t1" }} />);
+  await first.answer(false);
+  expect((await screen.findByRole("alert")).textContent).toContain("The runs couldn't be loaded. Check your connection, then try again.");
+  await userEvent.click(screen.getByRole("button", { name: "Try again" }));
+  await second.answer(true);
+  expect(await screen.findByText("runs of t1")).toBeTruthy();
+  expect(load).toHaveBeenCalledTimes(2);
+});
diff --git a/frontend/src/components/Shell.test.tsx b/frontend/src/components/Shell.test.tsx
index 10960178..fb723281 100644
--- a/frontend/src/components/Shell.test.tsx
+++ b/frontend/src/components/Shell.test.tsx
@@ -36,7 +36,7 @@ beforeEach(() => {
 async function renderAt(path: string) {
   const root = createRootRoute({ component: Shell });
   const page = () => <p>page</p>;
-  const children = ["/t/$tenantId/workflows", "/t/$tenantId/connections", "/t/$tenantId/settings/members", "/tenants", "/account/security"].map((p) =>
+  const children = ["/t/$tenantId/workflows", "/t/$tenantId/runs", "/t/$tenantId/connections", "/t/$tenantId/settings/members", "/tenants", "/account/security"].map((p) =>
     createRoute({ getParentRoute: () => root, path: p, component: page }),
   );
   const router = createRouter({
@@ -120,10 +120,16 @@ it("offers a theme choice in the header: the OS's, light or dark (D6)", async ()
 it("offers Workflows first on the rail, current on its pages", async () => {
   await renderAt("/t/t1/workflows");
   const links = screen.getAllByRole("link").filter((l) => l.closest("nav"));
-  expect(links.map((l) => l.textContent)).toEqual(["Workflows", "Connections", "Settings"]);
+  expect(links.map((l) => l.textContent)).toEqual(["Workflows", "Runs", "Connections", "Settings"]);
   expect(screen.getByRole("link", { name: "Workflows" }).getAttribute("aria-current")).toBe("page");
 });
 
+it("offers Runs after Workflows, current on its pages (the runs design §5.1)", async () => {
+  await renderAt("/t/t1/runs");
+  expect(screen.getByRole("link", { name: "Runs" }).getAttribute("aria-current")).toBe("page");
+  expect(screen.getByRole("link", { name: "Workflows" }).getAttribute("aria-current")).toBeNull();
+});
+
 it("keeps the editor's rail to icons at every width (outline §2)", async () => {
   const root = createRootRoute({ component: Shell });
   const editor = createRoute({
diff --git a/frontend/src/router.test.tsx b/frontend/src/router.test.tsx
index 8c2bcd31..c7262182 100644
--- a/frontend/src/router.test.tsx
+++ b/frontend/src/router.test.tsx
@@ -7,6 +7,7 @@ import userEvent from "@testing-library/user-event";
 import { beforeEach, expect, it, vi } from "vitest";
 import { guardLeaving } from "./lib/leaving";
 import { routeTree } from "./router";
+import { item } from "./test/runs";
 
 const SESSION = {
   auth_methods: ["password", "totp"],
@@ -18,6 +19,9 @@ const TENANTS = [
   { id: "t1", name: "Acme Retail", slug: "acme-retail", role: "owner", require_passkey: false },
   { id: "t2", name: "Acme Lab", slug: "acme-lab", role: "owner", require_passkey: false },
 ];
+const RUN = {
+  ...item("r1", "2026-10-16T09:41:12Z", { status: "failed" }), draft_revision: null, outcomes_recorded: true, parent: null, csv: null,
+};  // prettier-ignore
 const TYPES = [{ key: "mist", label: "Mist", config_schema: {}, secret_fields: ["api_token"], clouds: { global_01: "api.mist.com" } }];
 
 let sent: { method: string; path: string; body: unknown }[];
@@ -49,6 +53,8 @@ beforeEach(() => {
     if (/^GET \/api\/v1\/t\/t[12]\/webhook-endpoints$/.test(key)) return json({ endpoints: [] });
     if (key === "GET /api/v1/trigger-types") return json([]);
     if (key === "GET /api/v1/node-types") return json([]);
+    if (key === "GET /api/v1/t/t1/runs") return json([]);
+    if (key === "GET /api/v1/t/t1/runs/r1") return json(RUN);
     const tenant = TENANTS.find((t) => key === `GET /api/v1/t/${t.id}`);
     if (tenant) return json(tenant);
     return json({ error: "unexpected" }, 500);
@@ -178,3 +184,22 @@ it("opens Settings → Webhook endpoints from its tab (4c-3b)", async () => {
   expect(await screen.findByRole("heading", { name: "Webhook endpoints" })).toBeTruthy();
   expect(router.state.location.pathname).toBe("/t/t1/settings/webhooks");
 });
+
+it("opens the Runs page from the rail (the runs design §5.1)", async () => {
+  const router = showApp("/t/t1/workflows");
+  await userEvent.click(await screen.findByRole("link", { name: "Runs" }));
+  expect(await screen.findByRole("heading", { level: 1, name: "Runs" })).toBeTruthy();
+  expect(router.state.location.pathname).toBe("/t/t1/runs");
+});
+
+it("keeps a link's filters, dropping a value it doesn't know (§5.1)", async () => {
+  const router = showApp("/t/t1/runs?status=failed&mode=bogus");
+  expect(await screen.findByRole("heading", { level: 1, name: "Runs" })).toBeTruthy();
+  expect(router.state.matches.at(-1)!.search).toEqual({ status: "failed" });
+});
+
+it("opens a run's page beside the compact rail, as the editor's (§5.1; the owner's answer 6)", async () => {
+  const router = showApp("/t/t1/runs/r1");
+  expect(await screen.findByRole("heading", { level: 1, name: "AP offline triage" })).toBeTruthy();
+  expect(router.state.matches.some((m) => m.staticData.compactRail === true)).toBe(true);
+});
diff --git a/frontend/src/routes/runs/RunPage.test.tsx b/frontend/src/routes/runs/RunPage.test.tsx
new file mode 100644
index 00000000..a654a6bc
--- /dev/null
+++ b/frontend/src/routes/runs/RunPage.test.tsx
@@ -0,0 +1,71 @@
+// SPDX-License-Identifier: Apache-2.0
+import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
+import { RouterProvider, createMemoryHistory, createRootRoute, createRoute, createRouter } from "@tanstack/react-router";
+import { render, screen } from "@testing-library/react";
+import userEvent from "@testing-library/user-event";
+import { beforeEach, expect, it, vi } from "vitest";
+import type { Run } from "../../lib/runs";
+import { item } from "../../test/runs";
+import { RunPage } from "./RunPage";
+
+const RUN: Run = {
+  ...item("4a2b17e0-3b2d-4e5f-9a1b-2c3d4e5f6a7b", "2026-10-16T09:41:12Z", { status: "failed", ended_at: "2026-10-16T09:41:50Z" }),
+  draft_revision: null, outcomes_recorded: true, parent: null, csv: null,
+};  // prettier-ignore
+
+let answers: Map<string, () => Response>;
+
+beforeEach(() => {
+  answers = new Map();
+  vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
+    const path = new URL((input as Request).url).pathname;
+    const answer = answers.get(path);
+    return Promise.resolve(answer ? answer() : new Response(JSON.stringify({ error: "not_found" }), { status: 404 }));
+  });
+});
+
+const json = (body: unknown, status = 200) => () => new Response(JSON.stringify(body), { status });
+
+function show(runId = RUN.id) {
+  const root = createRootRoute({ component: () => <RunPage tenantId="t1" runId={runId} /> });
+  const runs = createRoute({ getParentRoute: () => root, path: "/t/$tenantId/runs", component: () => <p>the Runs page</p> });
+  const router = createRouter({ routeTree: root.addChildren([runs]), history: createMemoryHistory({ initialEntries: ["/"] }) });
+  render(
+    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
+      <RouterProvider router={router} />
+    </QueryClientProvider>,
+  );
+  return router;
+}
+
+it("names the run by its workflow and its short id, with the way back to Runs (§5.3)", async () => {
+  answers.set(`/api/v1/t/t1/runs/${RUN.id}`, json(RUN));
+  const router = show();
+  expect(await screen.findByRole("heading", { level: 1, name: "AP offline triage" })).toBeTruthy();
+  expect(screen.getByText("run 4a2b17e0")).toBeTruthy();
+  await userEvent.click(screen.getByRole("link", { name: "← Runs" }));
+  expect(router.state.location.pathname).toBe("/t/t1/runs");
+});
+
+it("says a run that isn't kept any more, or never was, is neither, with Back to Runs (§5.4; the RunOther board)", async () => {
+  const router = show("0d4f9b2a-0000-4000-8000-000000000000");
+  expect(await screen.findByRole("heading", { level: 1, name: "Run 0d4f9b2a" })).toBeTruthy();
+  expect(screen.getByText("This run isn't kept any more, or it never existed here.")).toBeTruthy();
+  await userEvent.click(screen.getByRole("link", { name: "Back to Runs" }));
+  expect(router.state.location.pathname).toBe("/t/t1/runs");
+});
+
+it("says a run can't be read while its tenant is erased (§5.5)", async () => {
+  answers.set(`/api/v1/t/t1/runs/${RUN.id}`, json({ error: "key_unusable" }, 503));
+  show();
+  expect((await screen.findByRole("alert")).textContent).toBe("This run can't be read while the tenant is being erased.");
+});
+
+it("says the run couldn't be read, and reads it again when asked", async () => {
+  answers.set(`/api/v1/t/t1/runs/${RUN.id}`, json({ error: "internal_error" }, 500));
+  show();
+  expect((await screen.findByRole("alert")).textContent).toBe("The run couldn't be read.");
+  answers.set(`/api/v1/t/t1/runs/${RUN.id}`, json(RUN));
+  await userEvent.click(screen.getByRole("button", { name: "Try again" }));
+  expect(await screen.findByRole("heading", { level: 1, name: "AP offline triage" })).toBeTruthy();
+});
diff --git a/frontend/src/routes/runs/RunsPage.test.tsx b/frontend/src/routes/runs/RunsPage.test.tsx
new file mode 100644
index 00000000..387445fe
--- /dev/null
+++ b/frontend/src/routes/runs/RunsPage.test.tsx
@@ -0,0 +1,150 @@
+// SPDX-License-Identifier: Apache-2.0
+import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
+import { RouterProvider, createMemoryHistory, createRootRoute, createRoute, createRouter } from "@tanstack/react-router";
+import { render, screen, within } from "@testing-library/react";
+import userEvent from "@testing-library/user-event";
+import { beforeEach, expect, it, vi } from "vitest";
+import type { RunFilters, RunItem } from "../../lib/runs";
+import { item } from "../../test/runs";
+import { RunsPage } from "./RunsPage";
+
+// Instants from the person's own clock: what the page says doesn't depend on the zone the tests run in.
+const local = (h: number, m: number, s: number, day = 16) => new Date(2026, 9, day, h, m, s).toISOString();
+const NOW = new Date(2026, 9, 16, 10, 2, 19).getTime();
+const schedule = (cron: string) => ({ source: "schedule" as const, schedule: { cron, every_s: null, offset_s: 0, time_zone: "Europe/Paris" }, endpoint: null, rerun_of: null });
+const scheduled = { source: "schedule" as const, status: "started" as const, reason: null };
+
+// The Main board's runs, newest first.
+const BOARD: RunItem[] = [
+  item("a14b2e9c-0001", local(10, 2, 9), { status: "queued", started_at: null, request: { status: "queued", source: "webhook", reason: null } }),
+  item("9f3c2a71-0002", local(10, 2, 7), { status: "running" }),
+  item("4a2b17e0-0003", local(9, 41, 12), { status: "failed", ended_at: local(9, 41, 50), error: { code: "channel_not_found", message: "The channel wasn't found." } }),
+  item("c81d0e55-0004", local(6, 0, 3), { workflow_name: "Daily device report", ended_at: local(6, 1, 55), trigger: schedule("0 6 * * 1-5"), request: scheduled }),
+  item("77e0b9d2-0005", local(5, 47, 40), {
+    workflow_name: "Bulk site creation", mode: "simulate", ended_at: local(5, 48, 9), started_by: "nadia@example.com",
+    trigger: { source: "manual", schedule: null, endpoint: null, rerun_of: null }, request: { ...scheduled, source: "manual" },
+  }),
+  item("0be41f3c-0006", local(2, 0, 1, 15), {
+    workflow_name: "Weekly PSK rotation", status: "deadline_exceeded", ended_at: local(2, 30, 1, 15),
+    error: { code: "deadline_exceeded", message: "The run passed its deadline." }, trigger: schedule("0 2 * * *"), request: scheduled,
+  }),
+  item("5d9a7c10-0007", local(17, 40, 2, 15), {
+    workflow_name: "Enforce auto-upgrade", status: "cancelled", ended_at: local(17, 43, 12, 15), started_by: "nadia@example.com",
+    trigger: { source: "rerun", schedule: null, endpoint: null, rerun_of: "2c4f8e91-0000" }, request: { ...scheduled, source: "rerun" },
+  }),
+  item("e2f7a6b4-0008", local(6, 0, 0, 15), {
+    workflow_name: "Daily device report", status: "dead", started_at: null, ended_at: local(6, 0, 40, 15), trigger: schedule("0 6 * * 1-5"),
+    request: { status: "dead", source: "schedule", reason: "start_throttled" },
+  }),
+  item("3c6d1f08-0009", local(1, 0, 0, 15), {
+    workflow_name: "Nightly site check", status: "refused", started_at: null, ended_at: local(1, 0, 0, 15), trigger: schedule("0 1 * * *"),
+    request: { status: "refused", source: "schedule", reason: "input_invalid" },
+  }),
+];  // prettier-ignore
+
+let answers: (() => Response)[];
+let sent: URL[];
+
+beforeEach(() => {
+  answers = [];
+  sent = [];
+  vi.spyOn(Date, "now").mockReturnValue(NOW);
+  vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
+    const url = new URL((input as Request).url);
+    sent.push(url);
+    return Promise.resolve(answers.shift()?.() ?? new Response(JSON.stringify(BOARD)));
+  });
+});
+
+function show(filters: RunFilters = {}) {
+  const root = createRootRoute({ component: () => <RunsPage tenantId="t1" filters={filters} /> });
+  const run = createRoute({ getParentRoute: () => root, path: "/t/$tenantId/runs/$runId" });
+  const router = createRouter({ routeTree: root.addChildren([run]), history: createMemoryHistory({ initialEntries: ["/"] }) });
+  render(
+    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
+      <RouterProvider router={router} />
+    </QueryClientProvider>,
+  );
+  return router;
+}
+
+const cells = (id: string) => within(screen.getByRole("link", { name: id }).closest("tr")!).getAllByRole("cell").map((c) => c.textContent);
+
+it("lists each run: its name, workflow, status, trigger, start, duration and error, as the Main board (§5.2)", async () => {
+  show();
+  await screen.findByRole("link", { name: "a14b2e9c" });
+  expect(screen.getAllByRole("columnheader").map((h) => h.textContent)).toEqual(["Run", "Workflow", "Status", "Trigger", "Started", "Duration", "Error"]);
+  expect(cells("a14b2e9c")).toEqual(["a14b2e9c", "AP offline triage", "Queued", "WebhookMist events", "today 10:02:09", "—", ""]);
+  expect(cells("9f3c2a71")).toEqual(["9f3c2a71", "AP offline triage", "Running", "WebhookMist events", "today 10:02:07", "12 s", ""]);
+  expect(cells("4a2b17e0")).toEqual(["4a2b17e0", "AP offline triage", "Failed", "WebhookMist events", "today 09:41:12", "38 s", "channel_not_foundThe channel wasn't found."]);
+  expect(cells("c81d0e55")).toEqual(["c81d0e55", "Daily device report", "Succeeded", "ScheduleWeekdays at 06:00", "today 06:00:03", "1 min 52 s", ""]);
+  expect(cells("77e0b9d2")).toEqual(["77e0b9d2", "Bulk site creation", "SucceededSimulated", "By handnadia@example.com", "today 05:47:40", "29 s", ""]);
+  expect(cells("0be41f3c")).toEqual([
+    "0be41f3c", "Weekly PSK rotation", "Ran out of time", "ScheduleEvery day at 02:00", "yesterday 02:00:01", "30 min", "deadline_exceededThe run passed its deadline.",
+  ]);  // prettier-ignore
+  expect(cells("5d9a7c10")).toEqual(["5d9a7c10", "Enforce auto-upgrade", "Cancelled", "Re-runof 2c4f8e91", "yesterday 17:40:02", "3 min 10 s", ""]);
+  expect(cells("e2f7a6b4")).toEqual([
+    "e2f7a6b4", "Daily device report", "Couldn't start", "ScheduleWeekdays at 06:00", "yesterday 06:00:00", "—", "start_throttledToo many runs were starting at once. Nothing ran.",
+  ]);  // prettier-ignore
+  expect(cells("3c6d1f08")[6]).toBe("input_invalidIts input didn't fit the workflow's input. Nothing ran.");
+});
+
+it("gives each start's full date and zone on hover (the owner's answer 8)", async () => {
+  show();
+  const started = within((await screen.findByRole("link", { name: "4a2b17e0" })).closest("tr")!).getByText("today 09:41:12");
+  expect(started.tagName).toBe("TIME");
+  expect(started.getAttribute("title")).toMatch(/^Friday, 16 October 2026 at 09:41:12 /);
+});
+
+it("says a draft simulation is one, and a run whose code it doesn't know by its code alone", async () => {
+  answers.push(() => new Response(JSON.stringify([
+    item("7c1e9a40-0001", local(10, 0, 0), { mode: "simulate", draft_snapshot_id: "s1" }),
+    item("1e8a3f27-0002", local(9, 0, 0), { status: "refused", started_at: null, request: { status: "refused", source: "manual", reason: "a_code_from_later" } }),
+  ])));  // prettier-ignore
+  show({ mode: "drafts" });
+  await screen.findByRole("link", { name: "7c1e9a40" });
+  expect(cells("7c1e9a40")[2]).toBe("SucceededDraft simulation");
+  expect(cells("1e8a3f27")[6]).toBe("a_code_from_laterNothing ran.");
+});
+
+it("asks for the runs its filters choose", async () => {
+  show({ status: "failed", workflow: "w1", started: "all" });
+  await screen.findByRole("link", { name: "a14b2e9c" });
+  expect(Object.fromEntries(sent[0]!.searchParams)).toEqual({ status: "failed", workflow_id: "w1", draft: "exclude", limit: "50" });
+});
+
+it("opens a run's page from its name", async () => {
+  const router = show();
+  await userEvent.click(await screen.findByRole("link", { name: "4a2b17e0" }));
+  await vi.waitFor(() => expect(router.state.location.pathname).toBe("/t/t1/runs/4a2b17e0-0003"));
+});
+
+it("says it's reading the runs, then that none ran yet (the ListStates board)", async () => {
+  let answer!: (r: Response) => void;
+  vi.mocked(globalThis.fetch).mockImplementationOnce(() => new Promise((resolve) => (answer = resolve)));
+  show();
+  expect((await screen.findByText("Reading the runs…")).getAttribute("role")).toBe("status");
+  answer(new Response("[]"));
+  expect(await screen.findByText("No runs yet. A run starts by hand from a workflow, on a schedule, or from a webhook.")).toBeTruthy();
+});
+
+it("says the runs couldn't be read, and reads them again when asked", async () => {
+  answers.push(() => new Response(JSON.stringify({ error: "internal_error" }), { status: 500 }));
+  show();
+  expect((await screen.findByRole("alert")).textContent).toBe("The runs couldn't be read.");
+  await userEvent.click(screen.getByRole("button", { name: "Try again" }));
+  expect(await screen.findByRole("link", { name: "a14b2e9c" })).toBeTruthy();
+});
+
+it("lists the runs as a list below 640 px, each one's facts on its lines (§5.6; the Narrow boards)", async () => {
+  const wide = window.matchMedia.bind(window);
+  vi.spyOn(window, "matchMedia").mockImplementation((query) => ({ ...wide(query), matches: true }));
+  show();
+  const list = await screen.findByRole("list", { name: "Runs" });
+  expect(screen.queryByRole("table")).toBeNull();
+  const runs = within(list).getAllByRole("listitem");
+  expect(runs).toHaveLength(BOARD.length);
+  expect(runs[1]!.textContent).toBe("9f3c2a71RunningAP offline triageWebhook, Mist events · today 10:02:07 · 12 s");
+  expect(runs[2]!.textContent).toBe("4a2b17e0FailedAP offline triageWebhook, Mist events · today 09:41:12 · 38 schannel_not_foundThe channel wasn't found.");
+  expect(runs[4]!.textContent).toBe("77e0b9d2SucceededSimulatedBulk site creationBy hand, nadia@example.com · today 05:47:40 · 29 s");
+});
diff --git a/frontend/src/test/setup.ts b/frontend/src/test/setup.ts
index e9d9513d..b7e49f30 100644
--- a/frontend/src/test/setup.ts
+++ b/frontend/src/test/setup.ts
@@ -25,6 +25,14 @@ globalThis.ResizeObserver ??= class {
 if (!("scrollIntoView" in Element.prototype)) {
   Object.defineProperty(Element.prototype, "scrollIntoView", { value: () => undefined, configurable: true, writable: true });
 }
+// jsdom has no media queries: each answers false, the wide layout (a test that asks for a narrow one says so).
+if (typeof window.matchMedia !== "function") {
+  const matchMedia = (query: string): MediaQueryList => ({
+    matches: false, media: query, onchange: null, dispatchEvent: () => false,
+    addEventListener: () => undefined, removeEventListener: () => undefined, addListener: () => undefined, removeListener: () => undefined,
+  });  // prettier-ignore
+  Object.defineProperty(window, "matchMedia", { value: matchMedia, configurable: true, writable: true });
+}
 // The router restores scroll on navigation; jsdom only reports that it has no scrolling.
 window.scrollTo = () => undefined;
 // Node 26's own (experimental) localStorage global wins over jsdom's and is undefined without a storage file: an
```

- [ ] **Step 2: Run them**

Run: `npx --offline pnpm@12.6.0 exec vitest run src/components/Shell.test.tsx src/router.test.tsx
src/components/LazyPage.test.tsx src/routes/editor/LazyEditor.test.tsx src/routes/runs/RunsPage.test.tsx
src/routes/runs/RunPage.test.tsx`

Expected: FAIL, 5 failed and 24 passed: `LazyPage.test.tsx`, `RunsPage.test.tsx` and `RunPage.test.tsx` can't import
their modules; the rail has no Runs (`expected [ 'Workflows', 'Connections', …(1) ] to deeply equal [ 'Workflows',
'Runs', …(2) ]`), and the app has no Runs page nor a run's page (`Unable to find role="heading" and name "Runs"`). The
editor's lazy load passes: its words don't change.

- [ ] **Step 3: Implement**

Apply:

```diff
diff --git a/frontend/src/components/Button.tsx b/frontend/src/components/Button.tsx
index 066e9a23..64df182f 100644
--- a/frontend/src/components/Button.tsx
+++ b/frontend/src/components/Button.tsx
@@ -41,6 +41,11 @@ const SIZES = {
 
 const DISABLED = "disabled:bg-disabled-bg disabled:border-disabled-line disabled:text-disabled-ink";
 
+/** A link that looks like a small secondary button: an action that goes to another page ("Back to Runs"). */
+export const LINK_BUTTON =
+  "inline-flex min-h-8 items-center justify-center gap-2 rounded-lg border border-line-strong bg-surface px-3 text-small " +
+  "font-medium text-ink hover:bg-surface-hover active:bg-surface-pressed";
+
 export function Button({
   variant = "secondary",
   size = "lg",
diff --git a/frontend/src/components/LazyPage.tsx b/frontend/src/components/LazyPage.tsx
new file mode 100644
index 00000000..6a96f154
--- /dev/null
+++ b/frontend/src/components/LazyPage.tsx
@@ -0,0 +1,62 @@
+// SPDX-License-Identifier: Apache-2.0
+// A page's code, loaded when the page is opened (the owner's ruling on milestone 3 of 4b): the editor's, the Runs
+// page's and a run's page's stay out of the list's and sign-in's first load. While it loads the page says so; if it
+// can't be loaded the page says that, with Try again (a new load: React keeps a failed one).
+import { Component, Suspense, lazy, useState, type ComponentType, type ReactNode } from "react";
+import { Button } from "./Button";
+
+/** A failure to fetch a page's code, told apart from an error inside the page (the router's to show). */
+class PageLoadError extends Error {}
+
+function lazyPage<P extends object>(load: () => Promise<ComponentType<P>>) {
+  return lazy(() =>
+    load().then(
+      (Page) => ({ default: Page }),
+      (e: unknown) => {
+        throw new PageLoadError(e instanceof Error ? e.message : "the page couldn't be loaded");
+      },
+    ),
+  );
+}
+
+class LoadBoundary extends Component<{ what: string; onRetry: () => void; children: ReactNode }, { failed: boolean }> {
+  state = { failed: false };
+
+  static getDerivedStateFromError(error: unknown): { failed: boolean } | null {
+    if (error instanceof PageLoadError) return { failed: true };
+    throw error; // the page's own error: the router's boundary shows it
+  }
+
+  render() {
+    if (!this.state.failed) return this.props.children;
+    const what = this.props.what;
+    return (
+      <section className="p-6">
+        <div role="alert" className="flex flex-wrap items-center gap-3 rounded-lg border border-danger bg-danger-bg px-3 py-2 text-body text-ink">
+          <span>{`${what.charAt(0).toUpperCase()}${what.slice(1)} couldn't be loaded. Check your connection, then try again.`}</span>
+          <Button
+            size="sm"
+            onClick={() => {
+              this.setState({ failed: false });
+              this.props.onRetry();
+            }}
+          >
+            Try again
+          </Button>
+        </div>
+      </section>
+    );
+  }
+}
+
+/** `what`: the page's code as a person reads it ("the editor", "the runs"). */
+export function LazyPage<P extends object>({ load, what, props }: { load: () => Promise<ComponentType<P>>; what: string; props: P }) {
+  const [Page, setPage] = useState(() => lazyPage(load));
+  return (
+    <LoadBoundary what={what} onRetry={() => setPage(() => lazyPage(load))}>
+      <Suspense fallback={<p role="status" className="p-6 text-body text-muted">{`Loading ${what}…`}</p>}>
+        <Page {...props} />
+      </Suspense>
+    </LoadBoundary>
+  );
+}
diff --git a/frontend/src/components/Shell.tsx b/frontend/src/components/Shell.tsx
index 860f6386..6985dbac 100644
--- a/frontend/src/components/Shell.tsx
+++ b/frontend/src/components/Shell.tsx
@@ -12,7 +12,7 @@ import { authenticatePasskey } from "../lib/webauthn";
 import { Announcer } from "./Announcer";
 import { Button } from "./Button";
 import { CommandPalette } from "./CommandPalette";
-import { ConnectionsIcon, SettingsIcon, WorkflowsIcon } from "./icons";
+import { ConnectionsIcon, RunsIcon, SettingsIcon, WorkflowsIcon } from "./icons";
 import { Mark, Wordmark } from "./Mark";
 import { TenantSwitcher } from "./TenantSwitcher";
 import { ThemeSelect } from "./ThemeSelect";
@@ -109,6 +109,18 @@ export function Shell({ sessionEnded = false }: { sessionEnded?: boolean }) {
               <span className={label}>Workflows</span>
             </Link>
           )}
+          {params.tenantId && (
+            <Link
+              to="/t/$tenantId/runs"
+              params={{ tenantId: params.tenantId }}
+              className={item}
+              activeProps={{ className: current }}
+              inactiveProps={{ className: INACTIVE }}
+            >
+              <RunsIcon />
+              <span className={label}>Runs</span>
+            </Link>
+          )}
           {params.tenantId && (
             <Link
               to="/t/$tenantId/connections"
diff --git a/frontend/src/components/When.tsx b/frontend/src/components/When.tsx
new file mode 100644
index 00000000..fa2efeb5
--- /dev/null
+++ b/frontend/src/components/When.tsx
@@ -0,0 +1,11 @@
+// SPDX-License-Identifier: Apache-2.0
+// When something happened, in the person's own zone, with the full date and zone on hover (the owner's answer 8).
+import { when, whenFull } from "../lib/when";
+
+export function When({ iso }: { iso: string }) {
+  return (
+    <time dateTime={iso} title={whenFull(iso)}>
+      {when(iso)}
+    </time>
+  );
+}
diff --git a/frontend/src/lib/media.ts b/frontend/src/lib/media.ts
new file mode 100644
index 00000000..ac2cf35c
--- /dev/null
+++ b/frontend/src/lib/media.ts
@@ -0,0 +1,15 @@
+// SPDX-License-Identifier: Apache-2.0
+// The viewport's width where a layout changes with it, not only its look (the runs design §5.6: a table's rows become
+// a list below 640 px, Tailwind's `sm`): followed as it changes.
+import { useSyncExternalStore } from "react";
+
+const NARROW = "(width < 40rem)";
+
+function subscribe(changed: () => void) {
+  const query = window.matchMedia(NARROW);
+  query.addEventListener("change", changed);
+  return () => query.removeEventListener("change", changed);
+}
+
+/** Whether the viewport is narrower than 640 px. */
+export const useNarrow = () => useSyncExternalStore(subscribe, () => window.matchMedia(NARROW).matches);
diff --git a/frontend/src/lib/runs.ts b/frontend/src/lib/runs.ts
index 8dce8bf9..b7e47857 100644
--- a/frontend/src/lib/runs.ts
+++ b/frontend/src/lib/runs.ts
@@ -37,16 +37,16 @@ export interface RunFilters {
 
 const one = <T extends string>(allowed: readonly T[], v: unknown): T | undefined => (allowed.includes(v as T) ? (v as T) : undefined);
 
-/** The filters an address holds, each value one it allows: a link keeps them (§5.1). */
+/** The filters an address holds, each value one it allows: a link keeps them (§5.1). Every filter is named, a value
+ * it doesn't allow as undefined: the router lays a route's search over the address's own, which would keep it. */
 export function validateRunsSearch(search: Record<string, unknown>): RunFilters {
-  const filters: RunFilters = {
+  return {
     workflow: typeof search.workflow === "string" && search.workflow !== "" ? search.workflow : undefined,
     status: one(STATUSES, search.status),
     trigger: one(TRIGGERS, search.trigger),
     mode: one(MODES, search.mode),
     started: one(STARTED, search.started),
   };
-  return searchOf(filters);
 }
 
 /** The filters as an address writes them: those at their default left out. */
diff --git a/frontend/src/router.tsx b/frontend/src/router.tsx
index 07dc2088..2283aecf 100644
--- a/frontend/src/router.tsx
+++ b/frontend/src/router.tsx
@@ -5,11 +5,13 @@ import { unsavedWork } from "./lib/leaving";
 import { useSession } from "./lib/session";
 import { useAfterAuth } from "./lib/useAfterAuth";
 import { ConnectionsPage } from "./routes/Connections";
+import { validateRunsSearch } from "./lib/runs";
 import { LazyEditor } from "./routes/editor/LazyEditor";
 import { EnrollPage } from "./routes/Enroll";
 import { LoginPage } from "./routes/Login";
 import { MembersPage } from "./routes/Members";
 import { MfaPage } from "./routes/Mfa";
+import { LazyRunPage, LazyRunsPage } from "./routes/runs/LazyRuns";
 import { SecurityPage } from "./routes/Security";
 import { SettingsLayout } from "./routes/Settings";
 import { TenantsPage } from "./routes/Tenants";
@@ -62,6 +64,17 @@ function Editor() {
   return <LazyEditor key={`${tenantId}:${workflowId}`} tenantId={tenantId} workflowId={workflowId} openTriggers={search.triggers === true} />;
 }
 
+function Runs() {
+  const { tenantId } = useParams({ from: "/app/t/$tenantId/runs" });
+  const filters = runsRoute.useSearch();
+  return <LazyRunsPage key={tenantId} tenantId={tenantId} filters={filters} />;
+}
+
+function Run() {
+  const { tenantId, runId } = useParams({ from: "/app/t/$tenantId/runs/$runId" });
+  return <LazyRunPage key={`${tenantId}:${runId}`} tenantId={tenantId} runId={runId} />;
+}
+
 function Connections() {
   const { tenantId } = useParams({ from: "/app/t/$tenantId/connections" });
   return <ConnectionsPage key={tenantId} tenantId={tenantId} />;
@@ -112,6 +125,15 @@ const editorRoute = createRoute({
   validateSearch: (search: Record<string, unknown>): { triggers?: true } =>
     search.triggers === true || search.triggers === "true" ? { triggers: true } : {},
 });
+// The Runs page keeps its filters in its address, so a link keeps them (the runs design §5.1); a run's page is laid out
+// like the editor, beside the compact rail (the owner's answer 6).
+const runsRoute = createRoute({ getParentRoute: () => appRoute, path: "/t/$tenantId/runs", component: Runs, validateSearch: validateRunsSearch });
+const runRoute = createRoute({
+  getParentRoute: () => appRoute,
+  path: "/t/$tenantId/runs/$runId",
+  component: Run,
+  staticData: { compactRail: true },
+});
 const connectionsRoute = createRoute({
   getParentRoute: () => appRoute,
   path: "/t/$tenantId/connections",
@@ -135,6 +157,8 @@ export const routeTree = rootRoute.addChildren([
     tenantHomeRoute,
     workflowsRoute,
     editorRoute,
+    runsRoute,
+    runRoute,
     connectionsRoute,
     settingsRoute.addChildren([settingsIndexRoute, membersRoute, webhooksRoute]),
   ]),
diff --git a/frontend/src/routes/editor/LazyEditor.tsx b/frontend/src/routes/editor/LazyEditor.tsx
index 66aec03a..23dc6982 100644
--- a/frontend/src/routes/editor/LazyEditor.tsx
+++ b/frontend/src/routes/editor/LazyEditor.tsx
@@ -1,65 +1,14 @@
 // SPDX-License-Identifier: Apache-2.0
 // The editor's code, loaded when a workflow is opened (the owner's ruling on milestone 3): React Flow and dagre stay
-// out of the list's and sign-in's first load. While it loads the page says so; if it can't be loaded the page says
-// that, with Try again (a new load: React keeps a failed one).
-import { Component, Suspense, lazy, useState, type ComponentType, type ReactNode } from "react";
-import { Button } from "../../components/Button";
+// out of the list's and sign-in's first load.
+import type { ComponentType } from "react";
+import { LazyPage } from "../../components/LazyPage";
 
 type Props = { tenantId: string; workflowId: string; openTriggers?: boolean };
 export type EditorModule = { EditorPage: ComponentType<Props> };
 
-/** A failure to fetch the editor's code, told apart from an error inside the editor (the router's to show). */
-class EditorLoadError extends Error {}
-
 const loadEditor = (): Promise<EditorModule> => import("./Editor");
 
-function lazyEditor(load: () => Promise<EditorModule>) {
-  return lazy(() =>
-    load().then(
-      (m) => ({ default: m.EditorPage }),
-      (e: unknown) => {
-        throw new EditorLoadError(e instanceof Error ? e.message : "the editor couldn't be loaded");
-      },
-    ),
-  );
-}
-
-class LoadBoundary extends Component<{ onRetry: () => void; children: ReactNode }, { failed: boolean }> {
-  state = { failed: false };
-
-  static getDerivedStateFromError(error: unknown): { failed: boolean } | null {
-    if (error instanceof EditorLoadError) return { failed: true };
-    throw error; // the editor's own error: the router's boundary shows it
-  }
-
-  render() {
-    if (!this.state.failed) return this.props.children;
-    return (
-      <section className="p-6">
-        <div role="alert" className="flex flex-wrap items-center gap-3 rounded-lg border border-danger bg-danger-bg px-3 py-2 text-body text-ink">
-          <span>The editor couldn&apos;t be loaded. Check your connection, then try again.</span>
-          <Button
-            size="sm"
-            onClick={() => {
-              this.setState({ failed: false });
-              this.props.onRetry();
-            }}
-          >
-            Try again
-          </Button>
-        </div>
-      </section>
-    );
-  }
-}
-
 export function LazyEditor({ load = loadEditor, ...props }: Props & { load?: () => Promise<EditorModule> }) {
-  const [Page, setPage] = useState(() => lazyEditor(load));
-  return (
-    <LoadBoundary onRetry={() => setPage(() => lazyEditor(load))}>
-      <Suspense fallback={<p role="status" className="p-6 text-body text-muted">Loading the editor…</p>}>
-        <Page {...props} />
-      </Suspense>
-    </LoadBoundary>
-  );
+  return <LazyPage what="the editor" load={() => load().then((m) => m.EditorPage)} props={props} />;
 }
diff --git a/frontend/src/routes/runs/LazyRuns.tsx b/frontend/src/routes/runs/LazyRuns.tsx
new file mode 100644
index 00000000..e6c81f36
--- /dev/null
+++ b/frontend/src/routes/runs/LazyRuns.tsx
@@ -0,0 +1,16 @@
+// SPDX-License-Identifier: Apache-2.0
+// The Runs page's code and a run's page's, each loaded when it's opened, in its own chunk (the runs design §5.1).
+import type { ComponentType } from "react";
+import { LazyPage } from "../../components/LazyPage";
+import type { RunFilters } from "../../lib/runs";
+
+type RunsProps = { tenantId: string; filters: RunFilters };
+type RunProps = { tenantId: string; runId: string };
+
+export function LazyRunsPage(props: RunsProps) {
+  return <LazyPage what="the runs" load={(): Promise<ComponentType<RunsProps>> => import("./RunsPage").then((m) => m.RunsPage)} props={props} />;
+}
+
+export function LazyRunPage(props: RunProps) {
+  return <LazyPage what="the run" load={(): Promise<ComponentType<RunProps>> => import("./RunPage").then((m) => m.RunPage)} props={props} />;
+}
diff --git a/frontend/src/routes/runs/RunPage.tsx b/frontend/src/routes/runs/RunPage.tsx
new file mode 100644
index 00000000..0f8fcf8c
--- /dev/null
+++ b/frontend/src/routes/runs/RunPage.tsx
@@ -0,0 +1,53 @@
+// SPDX-License-Identifier: Apache-2.0
+// A run's page (editor 4e-1; the runs design §5.3, §5.4; the RunFailed and RunOther boards), laid out like the editor
+// (the owner's answer 6): the compact rail, and a bar naming the run, its workflow and its short id, with the way back
+// to Runs. A run past its tenant's retention, or an id that never was, is said to be neither, with Back to Runs; a run
+// read while its tenant is erased says why it can't be (§5.5).
+import { useQuery } from "@tanstack/react-query";
+import { Link } from "@tanstack/react-router";
+import { Button, LINK_BUTTON } from "../../components/Button";
+import { ApiError } from "../../lib/client";
+import { runQuery } from "../../lib/runs";
+import { runId } from "../../lib/runStatus";
+import { useDocumentTitle } from "../../lib/title";
+
+/** Why a run couldn't be read: gone, the tenant's key gone during an erasure, or the read failed. */
+function Unread({ tenantId, id, error, retry }: { tenantId: string; id: string; error: Error; retry: () => void }) {
+  if (error instanceof ApiError && error.status === 404) {
+    return (
+      <section className="flex flex-col items-start gap-3 p-6">
+        <h1 className="text-h1 font-semibold">
+          Run <span className="font-mono">{runId(id)}</span>
+        </h1>
+        <p className="text-body">This run isn&apos;t kept any more, or it never existed here.</p>
+        <Link to="/t/$tenantId/runs" params={{ tenantId }} className={LINK_BUTTON}>Back to Runs</Link>
+      </section>
+    );
+  }
+  if (error instanceof ApiError && error.code === "key_unusable") {
+    return <p role="alert" className="p-6 text-body text-danger">This run can&apos;t be read while the tenant is being erased.</p>;
+  }
+  return (
+    <p className="flex flex-wrap items-center gap-3 p-6">
+      <span role="alert" className="text-body text-danger">The run couldn&apos;t be read.</span>
+      <Button size="sm" onClick={retry}>Try again</Button>
+    </p>
+  );
+}
+
+export function RunPage({ tenantId, runId: id }: { tenantId: string; runId: string }) {
+  useDocumentTitle(`Run ${runId(id)}`);
+  const run = useQuery(runQuery(tenantId, id));
+  const r = run.data;
+  // Only a run never read says why it isn't shown: a read that fails later keeps what was read.
+  if (!r) return run.isError ? <Unread tenantId={tenantId} id={id} error={run.error} retry={() => void run.refetch()} /> : <p role="status" className="p-6 text-body text-muted">Reading the run…</p>;
+  return (
+    <div className="flex min-h-0 flex-1 flex-col">
+      <div className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-line bg-surface px-5 py-2.5">
+        <Link to="/t/$tenantId/runs" params={{ tenantId }} className="text-small text-muted hover:text-ink">← Runs</Link>
+        <h1 className="min-w-0 truncate text-body-lg font-semibold">{r.workflow_name ?? "—"}</h1>
+        <span className="font-mono text-small">{`run ${runId(r.id)}`}</span>
+      </div>
+    </div>
+  );
+}
diff --git a/frontend/src/routes/runs/RunsPage.tsx b/frontend/src/routes/runs/RunsPage.tsx
new file mode 100644
index 00000000..b9fb92e7
--- /dev/null
+++ b/frontend/src/routes/runs/RunsPage.tsx
@@ -0,0 +1,138 @@
+// SPDX-License-Identifier: Apache-2.0
+// The Runs page (editor 4e-1; the runs design §5.2; the Main and ListStates boards): a tenant's runs, newest first,
+// each named by its id's first eight characters, a link to its page, with its workflow, its status (and a simulation
+// said so), what started it, when, how long it ran and its error. A request that never started gives its reason's code
+// and words. Below 640 px the rows become a list, each run's facts on its lines (§5.6; the Narrow boards).
+import { useQuery } from "@tanstack/react-query";
+import { Link } from "@tanstack/react-router";
+import { Button } from "../../components/Button";
+import { ModeChip, RunStatusChip } from "../../components/RunChips";
+import { Table, Td, Th } from "../../components/Table";
+import { When } from "../../components/When";
+import { useNarrow } from "../../lib/media";
+import { isEnded, runsQuery, type RunFilters, type RunItem } from "../../lib/runs";
+import { duration, reasonWords, runId } from "../../lib/runStatus";
+import { useDocumentTitle } from "../../lib/title";
+import { triggerOf } from "./trigger";
+
+/** When it started, else when it was queued. */
+const startOf = (r: RunItem) => r.started_at ?? r.queued_at;
+/** How long it ran, or has so far. */
+const lasted = (r: RunItem) => duration(r.started_at, isEnded(r.status) ? r.ended_at : new Date(Date.now()).toISOString());
+
+function RunLink({ tenantId, run }: { tenantId: string; run: RunItem }) {
+  return (
+    <Link to="/t/$tenantId/runs/$runId" params={{ tenantId, runId: run.id }} className="font-mono text-small font-medium text-accent-ink underline underline-offset-2">
+      {runId(run.id)}
+    </Link>
+  );
+}
+
+function Status({ run }: { run: RunItem }) {
+  return (
+    <span className="inline-flex flex-wrap gap-1">
+      <RunStatusChip status={run.status} />
+      {run.mode === "simulate" && <ModeChip mode="simulate" draft={run.draft_snapshot_id !== null} />}
+    </span>
+  );
+}
+
+/** Its error's code and message; a request that never started, its reason's code and words, and that nothing ran. */
+function Problem({ run }: { run: RunItem }) {
+  const reason = run.status === "refused" || run.status === "dead" ? (run.request?.reason ?? null) : null;
+  const code = run.error?.code ?? reason;
+  if (!code) return null;
+  const words = run.error ? run.error.message : `${reasonWords(reason) ?? ""} Nothing ran.`.trim();
+  return (
+    <>
+      <span className="block font-mono text-meta text-danger">{code}</span>
+      {words && <span className="block text-small text-muted">{words}</span>}
+    </>
+  );
+}
+
+function RunTable({ tenantId, runs }: { tenantId: string; runs: RunItem[] }) {
+  return (
+    <Table label="Runs">
+      <thead>
+        <tr>
+          <Th>Run</Th><Th>Workflow</Th><Th>Status</Th><Th>Trigger</Th><Th>Started</Th><Th>Duration</Th><Th>Error</Th>
+        </tr>
+      </thead>
+      <tbody>
+        {runs.map((r) => {
+          const trigger = triggerOf(r);
+          const start = startOf(r);
+          return (
+            <tr key={r.id}>
+              <Td className="align-top whitespace-nowrap"><RunLink tenantId={tenantId} run={r} /></Td>
+              <Td className="align-top">{r.workflow_name ?? "—"}</Td>
+              <Td className="align-top"><Status run={r} /></Td>
+              <Td className="align-top">
+                {trigger.kind}
+                {trigger.detail && <span className="block text-small text-muted">{trigger.detail}</span>}
+              </Td>
+              <Td className="align-top text-small whitespace-nowrap">{start ? <When iso={start} /> : "—"}</Td>
+              <Td className="align-top font-mono text-small whitespace-nowrap">{lasted(r) ?? "—"}</Td>
+              <Td className="align-top"><Problem run={r} /></Td>
+            </tr>
+          );
+        })}
+      </tbody>
+    </Table>
+  );
+}
+
+function RunList({ tenantId, runs }: { tenantId: string; runs: RunItem[] }) {
+  return (
+    <ul aria-label="Runs" className="flex flex-col">
+      {runs.map((r) => {
+        const trigger = triggerOf(r);
+        const start = startOf(r);
+        const took = lasted(r);
+        return (
+          <li key={r.id} className="flex flex-col gap-0.5 border-t border-line py-2.5 first:border-t-0">
+            <span className="flex flex-wrap items-center gap-2">
+              <RunLink tenantId={tenantId} run={r} />
+              <Status run={r} />
+            </span>
+            <span>{r.workflow_name ?? "—"}</span>
+            <span className="text-small text-muted">
+              {trigger.kind}
+              {trigger.detail && <>, {trigger.detail}</>}
+              {start && <> · <When iso={start} /></>}
+              {took && ` · ${took}`}
+            </span>
+            <Problem run={r} />
+          </li>
+        );
+      })}
+    </ul>
+  );
+}
+
+export function RunsPage({ tenantId, filters }: { tenantId: string; filters: RunFilters }) {
+  useDocumentTitle("Runs");
+  const first = useQuery(runsQuery(tenantId, filters));
+  const narrow = useNarrow();
+  const runs = first.data ?? [];
+  return (
+    <section className="flex flex-col gap-4 p-6">
+      <h1 className="text-h1 font-semibold">Runs</h1>
+      {first.isPending ? (
+        <p role="status" className="text-body text-muted">Reading the runs…</p>
+      ) : first.isError ? (
+        <p className="flex flex-wrap items-center gap-3">
+          <span role="alert" className="text-body text-danger">The runs couldn&apos;t be read.</span>
+          <Button size="sm" onClick={() => void first.refetch()}>Try again</Button>
+        </p>
+      ) : runs.length === 0 ? (
+        <p className="text-body text-muted">No runs yet. A run starts by hand from a workflow, on a schedule, or from a webhook.</p>
+      ) : narrow ? (
+        <RunList tenantId={tenantId} runs={runs} />
+      ) : (
+        <RunTable tenantId={tenantId} runs={runs} />
+      )}
+    </section>
+  );
+}
diff --git a/frontend/src/routes/runs/trigger.tsx b/frontend/src/routes/runs/trigger.tsx
new file mode 100644
index 00000000..25c9616c
--- /dev/null
+++ b/frontend/src/routes/runs/trigger.tsx
@@ -0,0 +1,29 @@
+// SPDX-License-Identifier: Apache-2.0
+// What started a run, in words (editor 4e-1; the runs design §5.2): its kind, then the person who asked (by hand), the
+// schedule's timing, the endpoint's name, or the run a re-run repeats. A run from before its request recorded these
+// says what it can.
+import type { ReactNode } from "react";
+import type { RunItem } from "../../lib/runs";
+import { runId } from "../../lib/runStatus";
+import { timingTitle } from "../../lib/timing";
+
+const KIND: Record<NonNullable<RunItem["trigger"]>["source"], string> = {
+  manual: "By hand",
+  rerun: "Re-run",
+  schedule: "Schedule",
+  webhook: "Webhook",
+  dev: "Development",
+};
+
+/** Its kind ("By hand"), and what says more about it, when known. */
+export function triggerOf(run: RunItem): { kind: string; detail: ReactNode } {
+  const t = run.trigger;
+  if (t === null) return { kind: "—", detail: null };
+  const detail =
+    t.source === "manual" ? run.started_by
+    : t.source === "rerun" ? t.rerun_of && <>of <span className="font-mono">{runId(t.rerun_of)}</span></>
+    : t.source === "schedule" ? t.schedule && timingTitle(t.schedule)
+    : t.source === "webhook" ? t.endpoint
+    : null;  // prettier-ignore
+  return { kind: KIND[t.source], detail: detail ?? null };
+}
```

- [ ] **Step 4: Run them again**

Run: the same command.

Expected: PASS, 43 passed.

- [ ] **Step 5: Static checks**

Run: the two of "How to run things". Expected: no output.

- [ ] **Step 6: Commit**

```bash
git add frontend/src
git commit -m "feat(editor): Runs on the rail, each run's row, and a run's page that knows a run gone (4e-1b)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: The filters

**Spec:** §5.2 (the filters), §5.1 (in the address); the ListStates board.

**Files:**
- Create: `frontend/src/routes/runs/Filters.tsx`
- Modify: `frontend/src/routes/runs/RunsPage.tsx`, `frontend/src/routes/runs/RunsPage.test.tsx`

**Interfaces:**
- Consumes: `RunFilters`, `searchOf` (Task 3); `workflowsQuery` (`lib/workflows.ts`); `PALETTE_ITEM`
  (`components/CommandPalette.tsx`).
- Produces: `Filters({ tenantId, filters, onChange })`.

Five "Label · Value ▾" menus, one choice each, a set one outlined in the accent: Workflow (a list that can be
searched, ruling 7), Status, Trigger, Mode (its items saying what they hold, ruling 6) and Started. A choice is written
in the address, a default left out of it. An empty list says what was asked (ruling 5): no match, with Clear the
filters; none in the window, with Show all kept; none yet.

- [ ] **Step 1: Write the failing tests**

Apply:

```diff
diff --git a/frontend/src/routes/runs/RunsPage.test.tsx b/frontend/src/routes/runs/RunsPage.test.tsx
index 387445fe..c31ad21d 100644
--- a/frontend/src/routes/runs/RunsPage.test.tsx
+++ b/frontend/src/routes/runs/RunsPage.test.tsx
@@ -1,10 +1,10 @@
 // SPDX-License-Identifier: Apache-2.0
 import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
-import { RouterProvider, createMemoryHistory, createRootRoute, createRoute, createRouter } from "@tanstack/react-router";
+import { RouterProvider, createMemoryHistory, createRootRoute, createRoute, createRouter, useSearch } from "@tanstack/react-router";
 import { render, screen, within } from "@testing-library/react";
 import userEvent from "@testing-library/user-event";
 import { beforeEach, expect, it, vi } from "vitest";
-import type { RunFilters, RunItem } from "../../lib/runs";
+import { validateRunsSearch, type RunItem } from "../../lib/runs";
 import { item } from "../../test/runs";
 import { RunsPage } from "./RunsPage";
 
@@ -42,6 +42,8 @@ const BOARD: RunItem[] = [
   }),
 ];  // prettier-ignore
 
+const WORKFLOWS = [{ id: "w1", name: "AP offline triage" }, { id: "w2", name: "Bulk AP rename" }];
+
 let answers: (() => Response)[];
 let sent: URL[];
 
@@ -51,15 +53,22 @@ beforeEach(() => {
   vi.spyOn(Date, "now").mockReturnValue(NOW);
   vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
     const url = new URL((input as Request).url);
+    if (url.pathname === "/api/v1/t/t1/workflows") return Promise.resolve(new Response(JSON.stringify(WORKFLOWS)));
     sent.push(url);
     return Promise.resolve(answers.shift()?.() ?? new Response(JSON.stringify(BOARD)));
   });
 });
 
-function show(filters: RunFilters = {}) {
-  const root = createRootRoute({ component: () => <RunsPage tenantId="t1" filters={filters} /> });
+function Runs() {
+  return <RunsPage tenantId="t1" filters={useSearch({ strict: false })} />;
+}
+
+/** The Runs page at `path`, its filters in the address as the app's route keeps them. */
+function show(path = "/t/t1/runs") {
+  const root = createRootRoute();
+  const runs = createRoute({ getParentRoute: () => root, path: "/t/$tenantId/runs", validateSearch: validateRunsSearch, component: Runs });
   const run = createRoute({ getParentRoute: () => root, path: "/t/$tenantId/runs/$runId" });
-  const router = createRouter({ routeTree: root.addChildren([run]), history: createMemoryHistory({ initialEntries: ["/"] }) });
+  const router = createRouter({ routeTree: root.addChildren([runs, run]), history: createMemoryHistory({ initialEntries: [path] }) });
   render(
     <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
       <RouterProvider router={router} />
@@ -101,14 +110,14 @@ it("says a draft simulation is one, and a run whose code it doesn't know by its
     item("7c1e9a40-0001", local(10, 0, 0), { mode: "simulate", draft_snapshot_id: "s1" }),
     item("1e8a3f27-0002", local(9, 0, 0), { status: "refused", started_at: null, request: { status: "refused", source: "manual", reason: "a_code_from_later" } }),
   ])));  // prettier-ignore
-  show({ mode: "drafts" });
+  show("/t/t1/runs?mode=drafts");
   await screen.findByRole("link", { name: "7c1e9a40" });
   expect(cells("7c1e9a40")[2]).toBe("SucceededDraft simulation");
   expect(cells("1e8a3f27")[6]).toBe("a_code_from_laterNothing ran.");
 });
 
 it("asks for the runs its filters choose", async () => {
-  show({ status: "failed", workflow: "w1", started: "all" });
+  show("/t/t1/runs?status=failed&workflow=w1&started=all");
   await screen.findByRole("link", { name: "a14b2e9c" });
   expect(Object.fromEntries(sent[0]!.searchParams)).toEqual({ status: "failed", workflow_id: "w1", draft: "exclude", limit: "50" });
 });
@@ -120,11 +129,14 @@ it("opens a run's page from its name", async () => {
 });
 
 it("says it's reading the runs, then that none ran yet (the ListStates board)", async () => {
-  let answer!: (r: Response) => void;
-  vi.mocked(globalThis.fetch).mockImplementationOnce(() => new Promise((resolve) => (answer = resolve)));
-  show();
+  let open!: () => void;
+  const held = new Promise<void>((resolve) => (open = resolve));
+  const answer = vi.mocked(globalThis.fetch).getMockImplementation()!;
+  vi.mocked(globalThis.fetch).mockImplementation((input) => held.then(() => answer(input)));
+  answers.push(() => new Response("[]"));
+  show("/t/t1/runs?started=all");
   expect((await screen.findByText("Reading the runs…")).getAttribute("role")).toBe("status");
-  answer(new Response("[]"));
+  open();
   expect(await screen.findByText("No runs yet. A run starts by hand from a workflow, on a schedule, or from a webhook.")).toBeTruthy();
 });
 
@@ -148,3 +160,83 @@ it("lists the runs as a list below 640 px, each one's facts on its lines (§5.6;
   expect(runs[2]!.textContent).toBe("4a2b17e0FailedAP offline triageWebhook, Mist events · today 09:41:12 · 38 schannel_not_foundThe channel wasn't found.");
   expect(runs[4]!.textContent).toBe("77e0b9d2SucceededSimulatedBulk site creationBy hand, nadia@example.com · today 05:47:40 · 29 s");
 });
+
+const filter = (name: string) => screen.getByRole("button", { name });
+const search = (router: ReturnType<typeof show>) => router.state.matches.at(-1)!.search;
+
+it("offers each filter as a menu showing its value, a set one outlined in the accent (§5.2; the ListStates board)", async () => {
+  show("/t/t1/runs?status=failed");
+  await screen.findByRole("link", { name: "a14b2e9c" });
+  const group = screen.getByRole("group", { name: "Filters" });
+  expect(within(group).getAllByRole("button").map((b) => b.textContent)).toEqual([
+    "Workflow · Any ▾", "Status · Failed ▾", "Trigger · Any ▾", "Mode · Live and simulated ▾", "Started · Last 24 hours ▾",
+  ]);  // prettier-ignore
+  expect(filter("Status · Failed").className).toContain("border-accent");
+  expect(filter("Trigger · Any").className).not.toContain("border-accent");
+});
+
+it("filters by one status from its menu, keeping the others, in the address (§5.1, §5.2)", async () => {
+  const router = show("/t/t1/runs?trigger=schedule");
+  await screen.findByRole("link", { name: "a14b2e9c" });
+  await userEvent.click(filter("Status · Any"));
+  const menu = await screen.findByRole("menu");
+  expect(within(menu).getAllByRole("menuitemradio").map((i) => i.textContent)).toEqual([
+    "✓Any", "Waiting: queued or starting", "Running", "Succeeded", "Failed", "Ran out of time", "Cancelled", "Didn't start: couldn't start or refused",
+  ]);  // prettier-ignore
+  await userEvent.click(within(menu).getByRole("menuitemradio", { name: "Didn't start: couldn't start or refused" }));
+  await vi.waitFor(() => expect(search(router)).toEqual({ trigger: "schedule", status: "didnt_start" }));
+  await vi.waitFor(() => expect(sent.at(-1)!.searchParams.get("status")).toBe("didnt_start"));
+  expect(filter("Status · Didn't start").className).toContain("border-accent");
+});
+
+it("says which runs each mode lists, draft simulations only when chosen (§5.2)", async () => {
+  const router = show();
+  await screen.findByRole("link", { name: "a14b2e9c" });
+  await userEvent.click(filter("Mode · Live and simulated"));
+  const menu = await screen.findByRole("menu");
+  expect(within(menu).getAllByRole("menuitemradio").map((i) => i.textContent)).toEqual([
+    "✓Live and simulated", "Live", "Simulated: of a published version", "Draft simulations: made in the editor", "Everything",
+  ]);  // prettier-ignore
+  await userEvent.click(within(menu).getByRole("menuitemradio", { name: "Draft simulations: made in the editor" }));
+  await vi.waitFor(() => expect(search(router)).toEqual({ mode: "drafts" }));
+  expect(sent.at(-1)!.searchParams.get("draft")).toBe("only");
+});
+
+it("goes back to a filter's default, leaving it out of the address", async () => {
+  const router = show("/t/t1/runs?started=7d");
+  await screen.findByRole("link", { name: "a14b2e9c" });
+  await userEvent.click(filter("Started · Last 7 days"));
+  await userEvent.click(await screen.findByRole("menuitemradio", { name: "Last 24 hours" }));
+  await vi.waitFor(() => expect(search(router)).toEqual({}));
+});
+
+it("chooses a workflow from a list it can search (§5.2; the ListStates board)", async () => {
+  const router = show();
+  await screen.findByRole("link", { name: "a14b2e9c" });
+  await userEvent.click(filter("Workflow · Any"));
+  const chooser = await screen.findByRole("dialog", { name: "Choose a workflow" });
+  const find = within(chooser).getByRole("combobox", { name: "Choose a workflow" });
+  expect(find.getAttribute("placeholder")).toBe("Find a workflow");
+  await userEvent.type(find, "bulk");
+  expect(within(chooser).getAllByRole("option").map((o) => o.textContent)).toEqual(["Bulk AP rename"]);
+  await userEvent.click(within(chooser).getByRole("option", { name: "Bulk AP rename" }));
+  await vi.waitFor(() => expect(search(router)).toEqual({ workflow: "w2" }));
+  expect(filter("Workflow · Bulk AP rename").className).toContain("border-accent");
+  expect(screen.queryByRole("dialog")).toBeNull();
+});
+
+it("says when no run matches the filters, and clears them (the ListStates board)", async () => {
+  answers.push(() => new Response("[]"));
+  const router = show("/t/t1/runs?status=failed&trigger=webhook");
+  expect(await screen.findByText("No runs match these filters in the last 24 hours.")).toBeTruthy();
+  await userEvent.click(screen.getByRole("button", { name: "Clear the filters" }));
+  await vi.waitFor(() => expect(search(router)).toEqual({}));
+});
+
+it("says no run started in the last 24 hours, never that none ran, and offers every run kept", async () => {
+  answers.push(() => new Response("[]"));
+  const router = show();
+  expect(await screen.findByText("No runs in the last 24 hours.")).toBeTruthy();
+  await userEvent.click(screen.getByRole("button", { name: "Show all kept" }));
+  await vi.waitFor(() => expect(search(router)).toEqual({ started: "all" }));
+});
```

- [ ] **Step 2: Run them**

Run: `npx --offline pnpm@12.6.0 exec vitest run src/routes/runs/RunsPage.test.tsx`

Expected: FAIL, 7 failed and 8 passed: there are no filters (`Unable to find an accessible element with the role "group"
and name "Filters"`, no "Status · Any"), and an empty list still says "No runs yet". Task 4's tests pass on the route
that now keeps the filters in the address.

- [ ] **Step 3: Implement**

Apply:

```diff
diff --git a/frontend/src/routes/runs/Filters.tsx b/frontend/src/routes/runs/Filters.tsx
new file mode 100644
index 00000000..b9b8b222
--- /dev/null
+++ b/frontend/src/routes/runs/Filters.tsx
@@ -0,0 +1,165 @@
+// SPDX-License-Identifier: Apache-2.0
+// The Runs page's filters (editor 4e-1; the runs design §5.2; the ListStates board): "Label · Value ▾" menus, one
+// choice each, a set one outlined in the accent. The workflow is chosen from a list that can be searched: a native
+// modal dialog around cmdk, as the palette and the step picker are (D23).
+import * as Dropdown from "@radix-ui/react-dropdown-menu";
+import { useQuery } from "@tanstack/react-query";
+import { Command } from "cmdk";
+import { useEffect, useRef, useState, type ComponentProps, type ReactNode } from "react";
+import { PALETTE_ITEM } from "../../components/CommandPalette";
+import type { ModeFilter, RunFilters, StartedFilter, StatusFilter, TriggerFilter } from "../../lib/runs";
+import { workflowsQuery, type WorkflowRow } from "../../lib/workflows";
+
+/** A choice: its value ("any" for no filter), its word on the button, and on the menu when it says more. */
+type Choice<T extends string> = { value: T; word: string; item?: string };
+
+const STATUS: Choice<StatusFilter | "any">[] = [
+  { value: "any", word: "Any" },
+  { value: "waiting", word: "Waiting", item: "Waiting: queued or starting" },
+  { value: "running", word: "Running" },
+  { value: "succeeded", word: "Succeeded" },
+  { value: "failed", word: "Failed" },
+  { value: "deadline_exceeded", word: "Ran out of time" },
+  { value: "cancelled", word: "Cancelled" },
+  { value: "didnt_start", word: "Didn't start", item: "Didn't start: couldn't start or refused" },
+];
+// A run from `dewpoint dev` is listed under Any only.
+const TRIGGER: Choice<TriggerFilter | "any">[] = [
+  { value: "any", word: "Any" },
+  { value: "manual", word: "By hand" },
+  { value: "rerun", word: "Re-run" },
+  { value: "schedule", word: "Schedule" },
+  { value: "webhook", word: "Webhook" },
+];
+const MODE: Choice<ModeFilter>[] = [
+  { value: "both", word: "Live and simulated" },
+  { value: "live", word: "Live" },
+  { value: "simulated", word: "Simulated", item: "Simulated: of a published version" },
+  { value: "drafts", word: "Draft simulations", item: "Draft simulations: made in the editor" },
+  { value: "everything", word: "Everything" },
+];
+const STARTED: Choice<StartedFilter>[] = [
+  { value: "1h", word: "Last hour" },
+  { value: "24h", word: "Last 24 hours" },
+  { value: "7d", word: "Last 7 days" },
+  { value: "30d", word: "Last 30 days" },
+  { value: "all", word: "All kept" },
+];
+
+const FILTER = "inline-flex min-h-9 items-center gap-1.5 rounded-lg border bg-surface px-3 text-small whitespace-nowrap hover:bg-surface-hover";
+const look = (set: boolean) => `${FILTER} ${set ? "border-accent text-accent-ink" : "border-line-control text-ink"}`;
+
+function Label({ label, value }: { label: string; value: string }) {
+  return (
+    <>
+      {label} · <b className="font-semibold">{value}</b> <span aria-hidden="true">▾</span>
+    </>
+  );
+}
+
+function Menu<T extends string>({ label, choices, value, onChange }: { label: string; choices: Choice<T>[]; value: T; onChange: (v: T) => void }) {
+  const current = choices.find((c) => c.value === value) ?? choices[0]!;
+  return (
+    <Dropdown.Root modal={false}>
+      <Dropdown.Trigger className={look(current !== choices[0])}>
+        <Label label={label} value={current.word} />
+      </Dropdown.Trigger>
+      <Dropdown.Portal>
+        <Dropdown.Content align="start" sideOffset={4} className="min-w-48 rounded-lg border border-line bg-surface p-1 shadow-dialog">
+          <Dropdown.RadioGroup value={current.value} onValueChange={(v) => onChange(v as T)}>
+            {choices.map((c) => (
+              <Dropdown.RadioItem
+                key={c.value}
+                value={c.value}
+                className="flex cursor-pointer items-center gap-2 rounded-md px-3 py-2 text-body data-[highlighted]:bg-accent-soft data-[highlighted]:text-accent-ink"
+              >
+                <span className="w-4">
+                  <Dropdown.ItemIndicator>✓</Dropdown.ItemIndicator>
+                </span>
+                {c.item ?? c.word}
+              </Dropdown.RadioItem>
+            ))}
+          </Dropdown.RadioGroup>
+        </Dropdown.Content>
+      </Dropdown.Portal>
+    </Dropdown.Root>
+  );
+}
+
+function Chooser({ workflows, value, onPick, onClose }: {
+  workflows: WorkflowRow[]; value: string | undefined; onPick: (id: string | undefined) => void; onClose: () => void;
+}) {  // prettier-ignore
+  const dialog = useRef<HTMLDialogElement>(null);
+  useEffect(() => {
+    const d = dialog.current;
+    if (d && !d.open) {
+      d.showModal();
+      d.querySelector<HTMLInputElement>("[cmdk-input]")?.focus();
+    }
+  }, []);
+  const pick = (id: string | undefined) => {
+    dialog.current?.close();
+    onPick(id);
+  };
+  const chosen = (yes: boolean): ReactNode => (
+    <span aria-hidden="true" className="w-4">
+      {yes ? "✓" : ""}
+    </span>
+  );
+  return (
+    <dialog
+      ref={dialog}
+      aria-label="Choose a workflow"
+      onClose={onClose}
+      className="mx-auto mt-20 w-[480px] max-w-[calc(100vw-32px)] rounded-dialog border border-line bg-surface p-0 text-ink shadow-dialog backdrop:bg-overlay"
+    >
+      <Command label="Choose a workflow" loop>
+        <Command.Input
+          placeholder="Find a workflow"
+          className="w-full rounded-t-dialog border-b border-line bg-transparent px-4 py-3 text-body-lg text-ink placeholder:text-muted focus-visible:-outline-offset-2"
+        />
+        <Command.List className="max-h-96 overflow-y-auto p-1">
+          <Command.Empty className="px-3 py-2 text-body text-muted">No workflow matches.</Command.Empty>
+          <Command.Item value="Any" onSelect={() => pick(undefined)} className={`${PALETTE_ITEM} justify-start`}>
+            {chosen(value === undefined)}Any
+          </Command.Item>
+          {workflows.map((w) => (
+            <Command.Item key={w.id} value={`${w.name} ${w.id}`} onSelect={() => pick(w.id)} className={`${PALETTE_ITEM} justify-start`}>
+              {chosen(value === w.id)}
+              {w.name}
+            </Command.Item>
+          ))}
+        </Command.List>
+      </Command>
+    </dialog>
+  );
+}
+
+function WorkflowFilter({ tenantId, value, onChange }: { tenantId: string; value: string | undefined; onChange: (id: string | undefined) => void }) {
+  const workflows = useQuery(workflowsQuery(tenantId));
+  const [open, setOpen] = useState(false);
+  const name = value === undefined ? "Any" : (workflows.data?.find((w) => w.id === value)?.name ?? "A workflow");
+  const props: ComponentProps<"button"> = { type: "button", "aria-haspopup": "dialog", onClick: () => setOpen(true) };
+  return (
+    <>
+      <button {...props} className={look(value !== undefined)}>
+        <Label label="Workflow" value={name} />
+      </button>
+      {open && <Chooser workflows={workflows.data ?? []} value={value} onPick={onChange} onClose={() => setOpen(false)} />}
+    </>
+  );
+}
+
+export function Filters({ tenantId, filters, onChange }: { tenantId: string; filters: RunFilters; onChange: (next: RunFilters) => void }) {
+  const set = (change: RunFilters) => onChange({ ...filters, ...change });
+  const any = <T extends string>(v: T | "any") => (v === "any" ? undefined : v);
+  return (
+    <div role="group" aria-label="Filters" className="flex flex-wrap items-center gap-2">
+      <WorkflowFilter tenantId={tenantId} value={filters.workflow} onChange={(workflow) => set({ workflow })} />
+      <Menu label="Status" choices={STATUS} value={filters.status ?? "any"} onChange={(v) => set({ status: any(v) })} />
+      <Menu label="Trigger" choices={TRIGGER} value={filters.trigger ?? "any"} onChange={(v) => set({ trigger: any(v) })} />
+      <Menu label="Mode" choices={MODE} value={filters.mode ?? "both"} onChange={(mode) => set({ mode })} />
+      <Menu label="Started" choices={STARTED} value={filters.started ?? "24h"} onChange={(started) => set({ started })} />
+    </div>
+  );
+}
diff --git a/frontend/src/routes/runs/RunsPage.tsx b/frontend/src/routes/runs/RunsPage.tsx
index b9fb92e7..3721f9c6 100644
--- a/frontend/src/routes/runs/RunsPage.tsx
+++ b/frontend/src/routes/runs/RunsPage.tsx
@@ -2,19 +2,29 @@
 // The Runs page (editor 4e-1; the runs design §5.2; the Main and ListStates boards): a tenant's runs, newest first,
 // each named by its id's first eight characters, a link to its page, with its workflow, its status (and a simulation
 // said so), what started it, when, how long it ran and its error. A request that never started gives its reason's code
-// and words. Below 640 px the rows become a list, each run's facts on its lines (§5.6; the Narrow boards).
+// and words. Below 640 px the rows become a list, each run's facts on its lines (§5.6; the Narrow boards). Its filters
+// live in its address (§5.1); an empty list says what was asked, never that no run ever ran when the window hides them.
 import { useQuery } from "@tanstack/react-query";
-import { Link } from "@tanstack/react-router";
+import { Link, useNavigate } from "@tanstack/react-router";
 import { Button } from "../../components/Button";
 import { ModeChip, RunStatusChip } from "../../components/RunChips";
 import { Table, Td, Th } from "../../components/Table";
 import { When } from "../../components/When";
 import { useNarrow } from "../../lib/media";
-import { isEnded, runsQuery, type RunFilters, type RunItem } from "../../lib/runs";
+import { isEnded, runsQuery, searchOf, type RunFilters, type RunItem } from "../../lib/runs";
 import { duration, reasonWords, runId } from "../../lib/runStatus";
 import { useDocumentTitle } from "../../lib/title";
+import { Filters } from "./Filters";
 import { triggerOf } from "./trigger";
 
+const WINDOW: Record<NonNullable<RunFilters["started"]>, string> = {
+  "1h": "in the last hour",
+  "24h": "in the last 24 hours",
+  "7d": "in the last 7 days",
+  "30d": "in the last 30 days",
+  all: "",
+};
+
 /** When it started, else when it was queued. */
 const startOf = (r: RunItem) => r.started_at ?? r.queued_at;
 /** How long it ran, or has so far. */
@@ -111,14 +121,40 @@ function RunList({ tenantId, runs }: { tenantId: string; runs: RunItem[] }) {
   );
 }
 
+/** What an empty list says: no match for the filters set; none in the window; else none yet (the ListStates board). */
+function Empty({ filters, onChange }: { filters: RunFilters; onChange: (next: RunFilters) => void }) {
+  const started = filters.started ?? "24h";
+  const within = WINDOW[started];
+  if (Object.keys(searchOf({ ...filters, started: undefined })).length > 0) {
+    return (
+      <p className="flex flex-wrap items-center gap-3 text-body text-muted">
+        {`No runs match these filters${within ? ` ${within}` : ""}.`}
+        <Button size="sm" onClick={() => onChange({})}>Clear the filters</Button>
+      </p>
+    );
+  }
+  if (started !== "all") {
+    return (
+      <p className="flex flex-wrap items-center gap-3 text-body text-muted">
+        {`No runs ${within}.`}
+        <Button size="sm" onClick={() => onChange({ started: "all" })}>Show all kept</Button>
+      </p>
+    );
+  }
+  return <p className="text-body text-muted">No runs yet. A run starts by hand from a workflow, on a schedule, or from a webhook.</p>;
+}
+
 export function RunsPage({ tenantId, filters }: { tenantId: string; filters: RunFilters }) {
   useDocumentTitle("Runs");
+  const navigate = useNavigate();
   const first = useQuery(runsQuery(tenantId, filters));
   const narrow = useNarrow();
   const runs = first.data ?? [];
+  const setFilters = (next: RunFilters) => void navigate({ to: "/t/$tenantId/runs", params: { tenantId }, search: searchOf(next) });
   return (
     <section className="flex flex-col gap-4 p-6">
       <h1 className="text-h1 font-semibold">Runs</h1>
+      <Filters tenantId={tenantId} filters={filters} onChange={setFilters} />
       {first.isPending ? (
         <p role="status" className="text-body text-muted">Reading the runs…</p>
       ) : first.isError ? (
@@ -127,7 +163,7 @@ export function RunsPage({ tenantId, filters }: { tenantId: string; filters: Run
           <Button size="sm" onClick={() => void first.refetch()}>Try again</Button>
         </p>
       ) : runs.length === 0 ? (
-        <p className="text-body text-muted">No runs yet. A run starts by hand from a workflow, on a schedule, or from a webhook.</p>
+        <Empty filters={filters} onChange={setFilters} />
       ) : narrow ? (
         <RunList tenantId={tenantId} runs={runs} />
       ) : (
```

- [ ] **Step 4: Run them again**

Run: the same command.

Expected: PASS, 15 passed.

- [ ] **Step 5: Static checks**

Run: the two of "How to run things". Expected: no output.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/routes/runs
git commit -m "feat(editor): the Runs page's filters, in its address (4e-1b)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Reading the list

**Spec:** §5.2 (reading: every 5 s while visible, Load more, de-duplicated, a failed refresh), §5.6 (one live region);
the Main and ListStates boards.

**Files:**
- Modify: `frontend/src/routes/runs/RunsPage.tsx`, `frontend/src/routes/runs/RunsPage.test.tsx`
- Modify: `frontend/src/lib/when.ts`

**Interfaces:**
- Consumes: `PAGE`, `listed`, `cursorOf`, `runsQuery` (Task 3); `announce` (`lib/announce.ts`).
- Produces: `timeOf(ms)` (`lib/when.ts`).

The first page is read every 5 s while the page is visible, and says so by the title ("Updates every 5 s"); a change
is said once. A refresh that fails keeps the list and says "Couldn't be refreshed · as of 10:02:07", with Try again.
Load more reads the next page once, after the last run listed; past the last, the list says no older run is kept (in
the window). Each run is listed once (`listed`); a filter changed starts it afresh.

- [ ] **Step 1: Write the failing tests**

Apply:

```diff
diff --git a/frontend/src/routes/runs/RunsPage.test.tsx b/frontend/src/routes/runs/RunsPage.test.tsx
index c31ad21d..3b7b06ef 100644
--- a/frontend/src/routes/runs/RunsPage.test.tsx
+++ b/frontend/src/routes/runs/RunsPage.test.tsx
@@ -1,10 +1,11 @@
 // SPDX-License-Identifier: Apache-2.0
-import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
+import { QueryClient, QueryClientProvider, focusManager } from "@tanstack/react-query";
 import { RouterProvider, createMemoryHistory, createRootRoute, createRoute, createRouter, useSearch } from "@tanstack/react-router";
-import { render, screen, within } from "@testing-library/react";
+import { act, render, screen, within } from "@testing-library/react";
 import userEvent from "@testing-library/user-event";
-import { beforeEach, expect, it, vi } from "vitest";
-import { validateRunsSearch, type RunItem } from "../../lib/runs";
+import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
+import { onAnnounce } from "../../lib/announce";
+import { PAGE, validateRunsSearch, type RunItem } from "../../lib/runs";
 import { item } from "../../test/runs";
 import { RunsPage } from "./RunsPage";
 
@@ -58,6 +59,7 @@ beforeEach(() => {
     return Promise.resolve(answers.shift()?.() ?? new Response(JSON.stringify(BOARD)));
   });
 });
+afterEach(() => vi.restoreAllMocks());
 
 function Runs() {
   return <RunsPage tenantId="t1" filters={useSearch({ strict: false })} />;
@@ -240,3 +242,105 @@ it("says no run started in the last 24 hours, never that none ran, and offers ev
   await userEvent.click(screen.getByRole("button", { name: "Show all kept" }));
   await vi.waitFor(() => expect(search(router)).toEqual({ started: "all" }));
 });
+
+const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
+const shownIds = () => within(screen.getByRole("region", { name: "Runs" })).getAllByRole("link").map((l) => l.textContent);
+
+describe("reading the list again (§5.2)", () => {
+  // Timers the test moves on, and real time besides, so the page's own waits still pass.
+  beforeEach(() => void vi.useFakeTimers({ toFake: ["setTimeout", "setInterval", "clearTimeout", "clearInterval"], shouldAdvanceTime: true }));
+  afterEach(() => void vi.useRealTimers());
+
+  it("reads the first page again every 5 s, saying so by the title, new runs at the top, and says it was updated (§5.6)", async () => {
+    const said: string[] = [];
+    const stop = onAnnounce((m) => said.push(m));
+    show();
+    await screen.findByRole("link", { name: "a14b2e9c" });
+    expect(screen.getByText("Updates every 5 s")).toBeTruthy();
+    const reads = sent.length;
+    answers.push(() => json(BOARD)); // the same: nothing to say
+    await act(() => vi.advanceTimersByTimeAsync(5000));
+    expect(sent.length).toBe(reads + 1);
+    answers.push(() => json([item("b7d0c3e1-0010", local(10, 2, 15), { status: "queued", started_at: null }), ...BOARD]));
+    await act(() => vi.advanceTimersByTimeAsync(5000));
+    await vi.waitFor(() => expect(shownIds().slice(0, 2)).toEqual(["b7d0c3e1", "a14b2e9c"]));
+    expect(said).toEqual(["Updated"]);
+    stop();
+  });
+
+  it("isn't read again while the tab is hidden, and is at once when it's shown", async () => {
+    show();
+    await screen.findByRole("link", { name: "a14b2e9c" });
+    const reads = sent.length;
+    try {
+      act(() => focusManager.setFocused(false));
+      await act(() => vi.advanceTimersByTimeAsync(12_000));
+      expect(sent.length).toBe(reads);
+      act(() => focusManager.setFocused(true));
+      await vi.waitFor(() => expect(sent.length).toBeGreaterThan(reads));
+    } finally {
+      focusManager.setFocused(undefined);
+    }
+  });
+
+  it("keeps the list when a refresh fails, says as of when, and tries again (the ListStates board)", async () => {
+    const said: string[] = [];
+    const stop = onAnnounce((m) => said.push(m));
+    show();
+    await screen.findByRole("link", { name: "a14b2e9c" });
+    answers.push(() => json({ error: "internal_error" }, 500));
+    await act(() => vi.advanceTimersByTimeAsync(5000));
+    expect(await screen.findByText("Couldn't be refreshed · as of 10:02:19")).toBeTruthy();
+    expect(screen.getByRole("link", { name: "a14b2e9c" })).toBeTruthy();
+    expect(said).toEqual(["The runs couldn't be refreshed."]);
+    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
+    expect(await screen.findByText("Updates every 5 s")).toBeTruthy();
+    stop();
+  });
+});
+
+/** `n` runs from minute `from` down, a minute apart, newest first. */
+const runsFrom = (from: number, n: number) => Array.from({ length: n }, (_, i) => item(`run${String(from - i).padStart(4, "0")}x-0`, new Date(NOW - (NOW % 60_000) - (1000 - from + i) * 60_000).toISOString()));
+
+it("loads older runs on from the last listed, never reading them again, each once, until none older is kept (§5.2)", async () => {
+  const first = runsFrom(1000, PAGE);
+  const second = [first.at(-1)!, ...runsFrom(1000 - PAGE, PAGE - 1)]; // the boundary's run read again: listed once
+  const third = runsFrom(1000 - 2 * PAGE + 1, 3);
+  answers.push(() => json(first));
+  show("/t/t1/runs?started=7d");
+  await screen.findByRole("link", { name: "run1000x" });
+  expect(screen.getByText("The 50 most recent first. New runs appear at the top as they're found.")).toBeTruthy();
+  answers.push(() => json(second));
+  await userEvent.click(screen.getByRole("button", { name: "Load more" }));
+  await screen.findByRole("link", { name: `run${String(1000 - 2 * PAGE + 2).padStart(4, "0")}x` });
+  expect(Object.fromEntries(sent.at(-1)!.searchParams)).toMatchObject({ before: first.at(-1)!.queued_at, before_id: first.at(-1)!.id });
+  expect(shownIds()).toHaveLength(2 * PAGE - 1);
+  expect(new Set(shownIds()).size).toBe(2 * PAGE - 1);
+  answers.push(() => json(third));
+  await userEvent.click(screen.getByRole("button", { name: "Load more" }));
+  expect(await screen.findByText("No older runs in the last 7 days.")).toBeTruthy();
+  expect(screen.queryByRole("button", { name: "Load more" })).toBeNull();
+  expect(shownIds()).toHaveLength(2 * PAGE + 2);
+});
+
+it("says no older run is kept at all once every run kept is listed", async () => {
+  answers.push(() => json(runsFrom(1000, PAGE)), () => json([]));
+  show("/t/t1/runs?started=all");
+  await screen.findByRole("link", { name: "run1000x" });
+  await userEvent.click(screen.getByRole("button", { name: "Load more" }));
+  expect(await screen.findByText("No older runs are kept.")).toBeTruthy();
+});
+
+it("starts the list afresh when a filter changes after older runs were loaded", async () => {
+  const newer = runsFrom(2000, PAGE).map((r) => ({ ...r, status: "failed" as const }));
+  answers.push(() => json(runsFrom(1000, PAGE)), () => json(runsFrom(1000 - PAGE, 3)), () => json(newer));
+  const router = show();
+  await screen.findByRole("link", { name: "run1000x" });
+  await userEvent.click(screen.getByRole("button", { name: "Load more" }));
+  expect(await screen.findByText("No older runs in the last 24 hours.")).toBeTruthy();
+  await act(() => router.navigate({ to: "/t/$tenantId/runs", params: { tenantId: "t1" }, search: { status: "failed" } }));
+  await screen.findByRole("link", { name: "run2000x" });
+  expect(shownIds()).toHaveLength(PAGE); // none of the earlier filters' runs below them
+  expect(screen.queryByText("No older runs in the last 24 hours.")).toBeNull();
+  expect(screen.getByRole("button", { name: "Load more" })).toBeTruthy();
+});
```

- [ ] **Step 2: Run them**

Run: `npx --offline pnpm@12.6.0 exec vitest run src/routes/runs/RunsPage.test.tsx`

Expected: FAIL, 5 failed and 16 passed: nothing says "Updates every 5 s" or "Couldn't be refreshed", and there's no Load
more. "isn't read again while the tab is hidden" passes at once: nothing reads the list again yet, and showing the tab
reads it on focus; it pins the pause once the interval exists.

- [ ] **Step 3: Implement**

Apply:

```diff
diff --git a/frontend/src/lib/when.ts b/frontend/src/lib/when.ts
index fb755415..02b41a63 100644
--- a/frontend/src/lib/when.ts
+++ b/frontend/src/lib/when.ts
@@ -15,5 +15,8 @@ export function when(iso: string, now: number = Date.now()): string {
   return `${day} ${TIME.format(t)}`;
 }
 
+/** The time of day an instant (in ms) was, to the second: "10:02:07". */
+export const timeOf = (ms: number) => TIME.format(new Date(ms));
+
 /** "Friday 16 October 2026 at 10:02:09 CEST": the full date, the time and the zone. */
 export const whenFull = (iso: string) => FULL.format(new Date(iso));
diff --git a/frontend/src/routes/runs/RunsPage.tsx b/frontend/src/routes/runs/RunsPage.tsx
index 3721f9c6..bf220d92 100644
--- a/frontend/src/routes/runs/RunsPage.tsx
+++ b/frontend/src/routes/runs/RunsPage.tsx
@@ -4,16 +4,22 @@
 // said so), what started it, when, how long it ran and its error. A request that never started gives its reason's code
 // and words. Below 640 px the rows become a list, each run's facts on its lines (§5.6; the Narrow boards). Its filters
 // live in its address (§5.1); an empty list says what was asked, never that no run ever ran when the window hides them.
-import { useQuery } from "@tanstack/react-query";
+// The first page is read again every 5 s while the page is visible; older pages, loaded on, aren't; each run is listed
+// once (`listed`). A refresh that fails keeps the list and says since when; a change is said once, through the shell's
+// live region (§5.6).
+import { useQuery, useQueryClient } from "@tanstack/react-query";
 import { Link, useNavigate } from "@tanstack/react-router";
+import { useEffect, useRef, useState } from "react";
 import { Button } from "../../components/Button";
 import { ModeChip, RunStatusChip } from "../../components/RunChips";
 import { Table, Td, Th } from "../../components/Table";
 import { When } from "../../components/When";
+import { announce } from "../../lib/announce";
 import { useNarrow } from "../../lib/media";
-import { isEnded, runsQuery, searchOf, type RunFilters, type RunItem } from "../../lib/runs";
+import { PAGE, cursorOf, isEnded, listed, runsQuery, searchOf, type RunFilters, type RunItem } from "../../lib/runs";
 import { duration, reasonWords, runId } from "../../lib/runStatus";
 import { useDocumentTitle } from "../../lib/title";
+import { timeOf } from "../../lib/when";
 import { Filters } from "./Filters";
 import { triggerOf } from "./trigger";
 
@@ -25,6 +31,11 @@ const WINDOW: Record<NonNullable<RunFilters["started"]>, string> = {
   all: "",
 };
 
+const EVERY = 5000; // the first page is read again this often (§5.2)
+
+/** Every run read so far, the latest read of each: the first page's reads and the older pages'. */
+const remember = (seen: Map<string, RunItem>, runs: RunItem[]) => new Map([...seen, ...runs.map((r): [string, RunItem] => [r.id, r])]);
+
 /** When it started, else when it was queued. */
 const startOf = (r: RunItem) => r.started_at ?? r.queued_at;
 /** How long it ran, or has so far. */
@@ -147,17 +158,57 @@ function Empty({ filters, onChange }: { filters: RunFilters; onChange: (next: Ru
 export function RunsPage({ tenantId, filters }: { tenantId: string; filters: RunFilters }) {
   useDocumentTitle("Runs");
   const navigate = useNavigate();
-  const first = useQuery(runsQuery(tenantId, filters));
+  const qc = useQueryClient();
+  const first = useQuery({ ...runsQuery(tenantId, filters), refetchInterval: EVERY });
   const narrow = useNarrow();
-  const runs = first.data ?? [];
+  // What was read under these filters: begun again when they change (React's "adjusting state when a prop changes").
+  const asked = JSON.stringify(searchOf(filters));
+  const [read, setRead] = useState({ asked, seen: new Map<string, RunItem>(), older: "idle" as "idle" | "reading" | "failed" | "end" });
+  if (read.asked !== asked) setRead({ asked, seen: new Map(), older: "idle" });
+  useEffect(() => {
+    if (first.data) setRead((r) => ({ ...r, seen: remember(r.seen, first.data) }));
+  }, [first.data]);
+  // A change is said once: an answer equal to the last keeps its reference (structural sharing), so says nothing.
+  const said = useRef(first.data);
+  useEffect(() => {
+    if (said.current !== undefined && first.data !== said.current) announce("Updated");
+    said.current = first.data;
+  }, [first.data]);
+  useEffect(() => {
+    if (first.isRefetchError) announce("The runs couldn't be refreshed.");
+  }, [first.isRefetchError]);
+  const runs = first.data ? listed(first.data, [...read.seen.values()]) : [];
+  const cursor = cursorOf(runs);
+  const more = first.data?.length === PAGE && read.older !== "end" && cursor !== null;
+  async function loadMore() {
+    if (cursor === null) return;
+    setRead((r) => ({ ...r, older: "reading" }));
+    try {
+      const page = await qc.query(runsQuery(tenantId, filters, cursor)); // read once: an older page isn't read again
+      setRead((r) => (r.asked === asked ? { ...r, seen: remember(r.seen, page), older: page.length < PAGE ? "end" : "idle" } : r));
+    } catch {
+      setRead((r) => (r.asked === asked ? { ...r, older: "failed" } : r));
+    }
+  }
   const setFilters = (next: RunFilters) => void navigate({ to: "/t/$tenantId/runs", params: { tenantId }, search: searchOf(next) });
+  const started = filters.started ?? "24h";
   return (
     <section className="flex flex-col gap-4 p-6">
-      <h1 className="text-h1 font-semibold">Runs</h1>
+      <div className="flex flex-wrap items-baseline justify-between gap-3">
+        <h1 className="text-h1 font-semibold">Runs</h1>
+        {first.isRefetchError ? (
+          <p className="flex flex-wrap items-center gap-2 text-small text-muted">
+            {`Couldn't be refreshed · as of ${timeOf(first.dataUpdatedAt)}`}
+            <Button size="sm" onClick={() => void first.refetch()}>Try again</Button>
+          </p>
+        ) : (
+          <p className="text-small text-muted">Updates every 5 s</p>
+        )}
+      </div>
       <Filters tenantId={tenantId} filters={filters} onChange={setFilters} />
       {first.isPending ? (
         <p role="status" className="text-body text-muted">Reading the runs…</p>
-      ) : first.isError ? (
+      ) : first.isLoadingError ? (
         <p className="flex flex-wrap items-center gap-3">
           <span role="alert" className="text-body text-danger">The runs couldn&apos;t be read.</span>
           <Button size="sm" onClick={() => void first.refetch()}>Try again</Button>
@@ -169,6 +220,18 @@ export function RunsPage({ tenantId, filters }: { tenantId: string; filters: Run
       ) : (
         <RunTable tenantId={tenantId} runs={runs} />
       )}
+      {read.older === "end" ? (
+        <p className="text-small text-muted">{started === "all" ? "No older runs are kept." : `No older runs ${WINDOW[started]}.`}</p>
+      ) : (
+        more && (
+          <div className="flex flex-wrap items-center gap-3">
+            <Button size="md" disabled={read.older === "reading"} onClick={() => void loadMore()}>Load more</Button>
+            <span className="text-small text-muted">
+              {read.older === "failed" ? "Older runs couldn't be read. Try again." : "The 50 most recent first. New runs appear at the top as they're found."}
+            </span>
+          </div>
+        )
+      )}
     </section>
   );
 }
```

- [ ] **Step 4: Run them again**

Run: the same command.

Expected: PASS, 21 passed.

- [ ] **Step 5: Static checks**

Run: the two of "How to run things". Expected: no output.

- [ ] **Step 6: Commit, and the milestone**

```bash
git add frontend/src/routes/runs frontend/src/lib/when.ts
git commit -m "feat(editor): the Runs page read every 5 s while visible, older runs loaded on, each once (4e-1b)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

Append `### 4e-1b, milestone 1 (date)` to the ledger: the tasks' commits, each task's test counts as run, every
mid-slice ruling. Commit it (`docs(editor-4): 4e-1b milestone 1`). **Pause** for the owner's review.

---

# Milestone 2 — A run's page

### Task 7: The canvas's keyboard, shared

**Spec:** §5.3 (the canvas: "the keyboard of D16, moved out of `Editor.tsx` into a hook both use"); §7's risk (the
hook's extraction under the editor's tests).

**Files:**
- Create: `frontend/src/routes/editor/useCanvasNav.ts`, `frontend/src/routes/editor/useCanvasNav.test.tsx`
- Modify: `frontend/src/routes/editor/Editor.tsx`

**Interfaces:**
- Consumes: `navModel`, `isPath`, `pathTo`, `step`, `type NavKey` (`canvasNav.ts`).
- Produces: `useCanvasNav(doc, portsOf, editable): { nav, focusId, shown, focusRequest, trail, focus(id, path?),
  onFocusItem(id), walk(key) }`; `portsOf` kept stable by its caller (the editor's `portsByStep`).

The editor's roving tab stop, its focus requests, the path the keys came by and the walk move into a hook; the editor
keeps its own keys (nudge, add, delete, connect) and its undo's focus. Its behaviour is unchanged: the editor's tests
pass as they are.

- [ ] **Step 1: Write the failing test**

Apply:

```diff
diff --git a/frontend/src/routes/editor/useCanvasNav.test.tsx b/frontend/src/routes/editor/useCanvasNav.test.tsx
new file mode 100644
index 00000000..b4e43a08
--- /dev/null
+++ b/frontend/src/routes/editor/useCanvasNav.test.tsx
@@ -0,0 +1,33 @@
+// SPDX-License-Identifier: Apache-2.0
+import { act, renderHook } from "@testing-library/react";
+import { expect, it } from "vitest";
+import type { GraphDoc } from "../../lib/workflows";
+import { useCanvasNav } from "./useCanvasNav";
+
+const node = (id: string, x = 0) => ({ id, key: id, type: "flow.transform@1", position: { x, y: 0 } });
+const edge = (from: string, to: string, port = "out") => ({ from: { node: from, port }, to: { node: to } });
+// A branch whose two ways join again: `end` is reached from `yes` and from `no`.
+const DOC: GraphDoc = {
+  graph_format: 1,
+  nodes: [node("if"), node("yes", 0), node("no", 300), node("end")],
+  edges: [edge("if", "yes", "true"), edge("if", "no", "false"), edge("yes", "end"), edge("no", "end")],
+};
+const ports = (id: string) => (id === "if" ? ["true", "false"] : ["out"]);
+
+it("walks a read-only canvas with the arrow keys from its one tab stop, back the way the keys came (D16)", () => {
+  const { result } = renderHook(() => useCanvasNav(DOC, ports, false));
+  expect(result.current.shown).toBe("start");
+  for (const key of ["ArrowDown", "ArrowDown", "ArrowRight", "ArrowDown"] as const) act(() => result.current.walk(key));
+  expect(result.current.shown).toBe("node:end");
+  act(() => result.current.walk("ArrowUp"));
+  expect(result.current.shown).toBe("node:no"); // the way it came, not the first way to it
+  expect(result.current.focusRequest).toEqual({ id: "node:no", n: 5 });
+});
+
+it("takes the tab stop where focus went, and falls back to the start card when its item is gone", () => {
+  const { result, rerender } = renderHook(({ doc }) => useCanvasNav(doc, ports, false), { initialProps: { doc: DOC } });
+  act(() => result.current.onFocusItem("node:end"));
+  expect(result.current.shown).toBe("node:end");
+  rerender({ doc: { ...DOC, nodes: DOC.nodes!.filter((n) => n.id !== "end"), edges: DOC.edges!.filter((e) => e.to.node !== "end") } });
+  expect(result.current.shown).toBe("start");
+});
```

- [ ] **Step 2: Run it, with the editor's**

Run: `npx --offline pnpm@12.6.0 exec vitest run src/routes/editor/useCanvasNav.test.tsx
src/routes/editor/Editor.test.tsx src/routes/editor/canvasNav.test.ts`

Expected: FAIL: `useCanvasNav.test.tsx` can't import its module; the editor's and the model's tests pass (184 passed).

- [ ] **Step 3: Implement**

Apply:

```diff
diff --git a/frontend/src/routes/editor/Editor.tsx b/frontend/src/routes/editor/Editor.tsx
index b38c9dbe..cf07a152 100644
--- a/frontend/src/routes/editor/Editor.tsx
+++ b/frontend/src/routes/editor/Editor.tsx
@@ -34,7 +34,7 @@ import {
   type WorkflowDetail,
 } from "../../lib/workflows";  // prettier-ignore
 import { Canvas } from "./Canvas";
-import { NAV_KEYS, isPath, navModel, pathTo, step, type NavKey } from "./canvasNav";
+import { NAV_KEYS, navModel, pathTo, type NavKey } from "./canvasNav";
 import { checkLabel, checkState, lastOf, type Check } from "./check";
 import { ConnectDialog } from "./ConnectDialog";
 import type { DrawerActions } from "./drawer/context";
@@ -56,6 +56,7 @@ import { StepPicker, type PickMode } from "./StepPicker";
 import { READ_ONLY, type PanelActions } from "./triggers/context";
 import { TriggersPanel } from "./triggers/TriggersPanel";
 import { UnappliedPanel } from "./UnappliedPanel";
+import { useCanvasNav } from "./useCanvasNav";
 import { VersionsPanel } from "./VersionsPanel";
 import { Toolbar } from "./Toolbar";
 
@@ -318,9 +319,6 @@ function Editor({
     setLeaveQuestion(null);
   };
   const [reloading, setReloading] = useState(false);
-  const [focusId, setFocusId] = useState<string>(START);
-  const [focusRequest, setFocusRequest] = useState<{ id: string; n: number } | null>(null);
-  const [trail, setTrail] = useState<string[] | null>(null); // the path the keys came by to the focused item
   const [picker, setPicker] = useState<PickMode | null>(null);
   // Steps by identity (`idKey`, `findNode`): an item names a step's canonical id, the document its authored one.
   const keyOf = (id: string) => (id === TRIGGERS ? "Triggers" : (findNode(doc, id)?.key ?? "a step"));
@@ -329,11 +327,8 @@ function Editor({
     () => new Map(nodesOf(shownDoc).map((n) => [idKey(n.id), portsOf(n, typeMap.get(n.type))])),
     [shownDoc, typeMap],
   );
-  const nav = useMemo(
-    () => navModel(shownDoc, (id) => portMap.get(idKey(id)) ?? [], editable),
-    [shownDoc, portMap, editable],
-  );
-  const shown = nav.order.includes(focusId) ? focusId : START; // a deleted item's tab stop falls back to the start card
+  const portsByStep = useCallback((id: string) => portMap.get(idKey(id)) ?? [], [portMap]);
+  const { nav, focusId, shown, focusRequest, trail, focus, onFocusItem, walk } = useCanvasNav(shownDoc, portsByStep, editable);
   const [connecting, setConnecting] = useState<PortRef | null>(null);
   const [asking, setAsking] = useState<Asking | null>(null);
   // What's typed in the drawer but not in the draft (ruling 18): the editor's, never a control's, so a tab, a toggle
@@ -782,12 +777,6 @@ function Editor({
     return step !== null && nav.order.includes(step) ? step : START;
   }
 
-  function focus(id: string, path: string[] | null = null) {
-    setFocusId(id);
-    setTrail(path);
-    setFocusRequest((r) => ({ id, n: (r?.n ?? 0) + 1 }));
-  }
-
   /** One edit: recorded (edits sharing a field's mark are one undo step, ruling 8), saved, and said, unless `message`
    * is null: a field's edits aren't announced, its control says what it holds. Whether it landed. */
   function change(next: GraphDoc, message: string | null, then?: string, mark?: string): boolean {
@@ -1092,11 +1081,7 @@ function Editor({
     if (NAV_KEYS.includes(e.key) && plain) {
       e.preventDefault();
       if (e.shiftKey && editable && id.startsWith("node:")) return nudge(id.slice(5), e.key as NavKey);
-      // The path the keys came by while it still holds (at a join, the branch taken); else the walk's own path.
-      const path = trail && trail.at(-1) === id && isPath(nav, trail) ? trail : pathTo(nav, id);
-      const next = step(nav, path, e.key as NavKey);
-      if (next.at(-1) !== id) focus(next.at(-1)!, next);
-      return;
+      return walk(e.key as NavKey);
     }
     if (!editable || !plain) return;
     if (e.key === "a" || e.key === "A") {
@@ -1364,10 +1349,7 @@ function Editor({
           current={panel}
           focusId={shown}
           focusRequest={focusRequest}
-          onFocusItem={(id) => {
-            setFocusId(id);
-            setTrail((t) => (t?.at(-1) === id ? t : null));
-          }}
+          onFocusItem={onFocusItem}
           onItem={onItem}
           onMove={(positions) => change(moveNodes(doc, positions), "Moved")}
           onConnect={onConnect}
diff --git a/frontend/src/routes/editor/useCanvasNav.ts b/frontend/src/routes/editor/useCanvasNav.ts
new file mode 100644
index 00000000..a8d56293
--- /dev/null
+++ b/frontend/src/routes/editor/useCanvasNav.ts
@@ -0,0 +1,41 @@
+// SPDX-License-Identifier: Apache-2.0
+// The canvas's keyboard (D16; 4b ruling 15): one roving tab stop, and the arrow keys walking the graph's items along
+// the path they came by (canvasNav.ts). The editor's and a run's page's (editor 4e-1; the runs design §5.3): the tab
+// stop's item, a focus request the canvas carries out once it has drawn it, and the walk.
+import { useCallback, useMemo, useState } from "react";
+import { START } from "../../lib/graph";
+import type { GraphDoc } from "../../lib/workflows";
+import { isPath, navModel, pathTo, step, type NavKey } from "./canvasNav";
+
+/** `portsOf` (a step's ports, by its id) is kept stable by the caller: the model is built again when it changes. */
+export function useCanvasNav(doc: GraphDoc, portsOf: (nodeId: string) => string[], editable: boolean) {
+  const [focusId, setFocusId] = useState<string>(START);
+  const [focusRequest, setFocusRequest] = useState<{ id: string; n: number } | null>(null);
+  const [trail, setTrail] = useState<string[] | null>(null); // the path the keys came by to the focused item
+  const nav = useMemo(() => navModel(doc, portsOf, editable), [doc, portsOf, editable]);
+  const shown = nav.order.includes(focusId) ? focusId : START; // a deleted item's tab stop falls back to the start card
+
+  /** Focus moves to `id`, by `path` when the keys took it there. */
+  const focus = useCallback((id: string, path: string[] | null = null) => {
+    setFocusId(id);
+    setTrail(path);
+    setFocusRequest((r) => ({ id, n: (r?.n ?? 0) + 1 }));
+  }, []);
+
+  /** The item that took focus, by a click, Tab or a key, becomes the tab stop; the keys' path holds while it ends there. */
+  const onFocusItem = useCallback((id: string) => {
+    setFocusId(id);
+    setTrail((t) => (t?.at(-1) === id ? t : null));
+  }, []);
+
+  /** A key's move from the tab stop's item: from the item focus is meant to be on, as a key moves focus a frame later
+   * (the canvas draws it first), and a key pressed before then starts where the last one left it. The path the keys
+   * came by while it still holds (at a join, the branch taken); else the walk's own path. */
+  function walk(key: NavKey) {
+    const path = trail && trail.at(-1) === shown && isPath(nav, trail) ? trail : pathTo(nav, shown);
+    const next = step(nav, path, key);
+    if (next.at(-1) !== shown) focus(next.at(-1)!, next);
+  }
+
+  return { nav, focusId, shown, focusRequest, trail, focus, onFocusItem, walk };
+}
```

- [ ] **Step 4: Run them again**

Run: the same command.

Expected: PASS, 186 passed.

- [ ] **Step 5: Static checks**

Run: the two of "How to run things". Expected: no output.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/routes/editor
git commit -m "refactor(editor): the canvas's keyboard in a hook the editor and a run's page share (4e-1b)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: A run's tags

**Spec:** §5.3 (the tags), §5.5 (the origins' words and looks), §8's answer 4 ("sent" on every live action that
called its connection); the RunFailed, RunRunning and RunLoop boards.

**Files:**
- Modify: `frontend/src/routes/editor/simulation/results.ts`, `frontend/src/routes/editor/simulation/results.test.ts`
- Modify: `frontend/src/routes/editor/simulation/SimTags.tsx`, `frontend/src/routes/editor/simulation/SimTags.test.tsx`
- Modify: `frontend/src/lib/runStatus.ts`, `frontend/src/lib/runStatus.test.ts`

**Interfaces:**
- Consumes: `RunOrigin`, `RunStepSummary` (Task 3); `duration` (Task 2).
- Produces:
  - `took(from, to): string | null` (`lib/runStatus.ts`).
  - `results.ts`: `SimTagKind` gains `sent`, `maybe`, `code`; `ORIGIN` gains `sent` and `may_have_been_sent`;
    `interface Summary` (a simulation's step or any run's); `tagsOf(summary, { maxAttempts, ended, run?: { action } })`.
  - `SimTags({ label, tags, place?, what? })`: `what` names the tags ("simulated result" by default).

The tags 4d-1c drew serve any run (ruling 16): "sent" in the live outline, "may have been sent" dashed in the
warning's colour; a live control step, which says no origin, its port alone; an action's time; a failure's code. A
simulation's tags in the editor stay as they are.

- [ ] **Step 1: Write the failing tests**

Apply:

```diff
diff --git a/frontend/src/lib/runStatus.test.ts b/frontend/src/lib/runStatus.test.ts
index ea89c806..508c7c9b 100644
--- a/frontend/src/lib/runStatus.test.ts
+++ b/frontend/src/lib/runStatus.test.ts
@@ -1,6 +1,6 @@
 // SPDX-License-Identifier: Apache-2.0
 import { describe, expect, it } from "vitest";
-import { RUN_STATUS, duration, reasonWords, runId } from "./runStatus";
+import { RUN_STATUS, duration, reasonWords, runId, took } from "./runStatus";
 
 describe("a run's status, in one vocabulary (the runs design §5.5)", () => {
   it("words each status, and says how it looks, as every screen that shows a run does", () => {
@@ -25,6 +25,13 @@ describe("a run's status, in one vocabulary (the runs design §5.5)", () => {
     expect(duration(null, "2026-10-15T10:42:05Z")).toBeNull();
   });
 
+  it("gives a step's time to the tenth of a second while it's short", () => {
+    expect(took("2026-10-16T09:41:12Z", "2026-10-16T09:41:12.400Z")).toBe("0.4 s");
+    expect(took("2026-10-16T09:41:12Z", "2026-10-16T09:41:13.849Z")).toBe("1.8 s");
+    expect(took("2026-10-16T09:41:12Z", "2026-10-16T09:41:42Z")).toBe("30 s");
+    expect(took("2026-10-16T09:41:12Z", null)).toBeNull();
+  });
+
   it("names a run by its id's first eight characters", () => {
     expect(runId("7c1e9a40-3b2d-4e5f-9a1b-2c3d4e5f6a7b")).toBe("7c1e9a40");
   });
diff --git a/frontend/src/routes/editor/simulation/SimTags.test.tsx b/frontend/src/routes/editor/simulation/SimTags.test.tsx
index 1c882edc..2a0f71a7 100644
--- a/frontend/src/routes/editor/simulation/SimTags.test.tsx
+++ b/frontend/src/routes/editor/simulation/SimTags.test.tsx
@@ -48,3 +48,25 @@ it("goes under its card on one line, cut short, where another card is beside it;
   expect(screen.getByRole("list", { name: "notify: simulated result" }).className).toMatch(/@max-3xl:truncate/);
 });
 
+
+it("names a run's tags for what they are, and draws its origins: sent in live orange, may have been sent dashed (the runs design §5.5)", () => {
+  render(
+    <SimTags
+      label="notify_noc"
+      what="result"
+      tags={[
+        { text: "sent", kind: "sent" },
+        { text: "may have been sent", kind: "maybe" },
+        { text: "channel_not_found", kind: "code" },
+      ]}
+    />,
+  );
+  const list = screen.getByRole("list", { name: "notify_noc: result" });
+  const tag = (text: string) => within(list).getByText(text).className;
+  expect(tag("sent")).toMatch(/border-live/);
+  expect(tag("sent")).toMatch(/text-live/);
+  expect(tag("may have been sent")).toMatch(/border-dashed/);
+  expect(tag("may have been sent")).toMatch(/text-warn-ink/);
+  expect(tag("channel_not_found")).toMatch(/font-mono/);
+  expect(tag("channel_not_found")).toMatch(/text-danger/);
+});
diff --git a/frontend/src/routes/editor/simulation/results.test.ts b/frontend/src/routes/editor/simulation/results.test.ts
index ac102a34..4098d514 100644
--- a/frontend/src/routes/editor/simulation/results.test.ts
+++ b/frontend/src/routes/editor/simulation/results.test.ts
@@ -1,5 +1,6 @@
 // SPDX-License-Identifier: Apache-2.0
 import { describe, expect, it } from "vitest";
+import type { RunStepSummary } from "../../../lib/runs";
 import type { StepSummary } from "../../../lib/simulations";
 import { tagsFitBeside, tagsOf, words } from "./results";
 
@@ -54,6 +55,56 @@ describe("a step's result on the canvas (§7.3, §7.4; the ResultCanvas and Runn
   });
 });
 
+describe("a run's step on its page (the runs design §5.3; the RunFailed, RunRunning and RunLoop boards)", () => {
+  type RunFinal = NonNullable<RunStepSummary["final"]>;
+  const at = (s: number) => `2026-10-16T09:41:${String(Math.floor(s)).padStart(2, "0")}.${String(Math.round((s % 1) * 1000)).padStart(3, "0")}Z`;
+  const ran = (over: Partial<RunFinal> = {}): RunFinal => ({
+    step_id: "id-a", key: "a", iteration_key: "", attempt: 1, status: "succeeded", started_at: at(12), ended_at: at(12.4),
+    input: null, output: null, error: null, outcome: null, cel_mode: null, effect: null, ...over,
+  });  // prettier-ignore
+  const step = (over: Partial<RunStepSummary>): RunStepSummary => ({
+    step_id: "id-a", key: "a", type: "mist.get_device@1", origin: "sent", instances: 1, statuses: { succeeded: 1 }, ports: {}, final: ran(), ...over,
+  });  // prettier-ignore
+  const action = { maxAttempts: 3, ended: true, run: { action: true } };
+
+  it("says a live step sent, and how long it took", () => {
+    const tags = tagsOf(step({}), action);
+    expect(words(tags)).toEqual(["succeeded", "sent", "0.4 s"]);
+    expect(tags.map((t) => t.kind)).toEqual(["ok", "sent", "note"]);
+    expect(words(tagsOf(step({ final: ran({ ended_at: at(13.8) }) }), action))).toEqual(["succeeded", "sent", "1.8 s"]);
+  });
+
+  it("says a failed step's attempt and its error's code, in place of its time", () => {
+    const failed = step({ origin: null, statuses: { failed: 1 }, final: ran({ attempt: 3, status: "failed", error: { code: "channel_not_found", message: "The channel wasn't found." } }) });
+    const tags = tagsOf(failed, action);
+    expect(words(tags)).toEqual(["failed", "attempt 3 of 3", "channel_not_found"]);
+    expect(tags.map((t) => t.kind)).toEqual(["fail", "note", "code"]);
+  });
+
+  it("says a step whose answer was lost may have been sent, dashed in the warning's colour", () => {
+    const lost = tagsOf(step({ origin: "may_have_been_sent", statuses: { failed: 1 }, final: ran({ status: "failed", error: { code: "outcome_unknown", message: null } }) }), action);
+    expect(words(lost)).toEqual(["failed", "may have been sent", "outcome_unknown"]);
+    expect(lost[1]!.kind).toBe("maybe");
+  });
+
+  it("gives a live control step its port and nothing else: it ran in the engine, and says no origin", () => {
+    const branch = step({ type: "flow.if@1", origin: null, final: ran({ effect: { port: "true" } }), ports: { true: 1 } });
+    expect(words(tagsOf(branch, { ...action, run: { action: false } }))).toEqual(["succeeded", "→ true"]);
+  });
+
+  it("says a running step's attempt, and no time until it ends", () => {
+    const running = step({ origin: null, statuses: { running: 1 }, final: ran({ attempt: 2, status: "running", ended_at: null }) });
+    expect(words(tagsOf(running, { ...action, ended: false }))).toEqual(["running", "attempt 2 of 3"]);
+  });
+
+  it("totals a live loop's step over its instances, and says it sent", () => {
+    const notify = step({ instances: 120, statuses: { succeeded: 14, failed: 3, skipped: 103 }, final: null });
+    expect(words(tagsOf(notify, action))).toEqual(["120 instances: 14 succeeded · 3 failed · 103 skipped", "sent"]);
+    const branch = step({ type: "flow.if@1", origin: null, instances: 120, statuses: { succeeded: 120 }, ports: { true: 17, false: 103 }, final: null });
+    expect(words(tagsOf(branch, { ...action, run: { action: false } }))).toEqual(["120 instances: 120 succeeded", "→ true ×17", "→ false ×103"]);
+  });
+});
+
 describe("where a step's tags go (the review's 1, the owner's choice: beside, else under)", () => {
   it("go beside a card wherever no other card is there, and under it where one is", () => {
     expect(tagsFitBeside({ x: 0, y: 0 }, [{ x: 0, y: 140 }, { x: 600, y: 0 }])).toBe(true); // the next rank, a far card
```

- [ ] **Step 2: Run them**

Run: `npx --offline pnpm@12.6.0 exec vitest run src/routes/editor/simulation/results.test.ts
src/routes/editor/simulation/SimTags.test.tsx src/lib/runStatus.test.ts`

Expected: FAIL, 8 failed and 14 passed: `took` doesn't exist (`TypeError: (0 , took) is not a function`); a live step's
origin reads `undefined` (`expected [ 'succeeded', 'undefined' ] to deeply equal [ 'succeeded', 'sent', '0.4 s' ]`),
with no time or code; a run's tags have no name of their own ("notify_noc: result"). 4d-1c's tags pass, unchanged.

- [ ] **Step 3: Implement**

Apply:

```diff
diff --git a/frontend/src/lib/runStatus.ts b/frontend/src/lib/runStatus.ts
index ca5a9442..63419e76 100644
--- a/frontend/src/lib/runStatus.ts
+++ b/frontend/src/lib/runStatus.ts
@@ -31,6 +31,13 @@ export function duration(from: string | null, to: string | null): string | null
   return `${Math.floor(s / 3600)} h${Math.floor((s % 3600) / 60) ? ` ${Math.floor((s % 3600) / 60)} min` : ""}`;
 }
 
+/** How long a step took, to the tenth of a second under 10 s ("0.4 s", "1.8 s"), else as a run's duration. */
+export function took(from: string | null, to: string | null): string | null {
+  if (from === null || to === null) return null;
+  const ms = Date.parse(to) - Date.parse(from);
+  return ms < 10_000 ? `${(Math.floor(ms / 100) / 10).toFixed(1)} s` : duration(from, to);
+}
+
 /** A run named by its id's first eight characters (a run's id is its request's). */
 export const runId = (id: string) => id.slice(0, 8);
 
diff --git a/frontend/src/routes/editor/simulation/SimTags.tsx b/frontend/src/routes/editor/simulation/SimTags.tsx
index 1daee68e..e98c1e50 100644
--- a/frontend/src/routes/editor/simulation/SimTags.tsx
+++ b/frontend/src/routes/editor/simulation/SimTags.tsx
@@ -3,7 +3,8 @@
 // beside it, under it at narrow widths, never on it, so the card and its problem and "may not run" badges stay as they
 // are. Where another card is beside it, under it (`place`); under, they take one line, cut short, every word still read
 // out (the review's 1). Each tag is drawn as what it is: a status, values a person gave (slate outline), a fixture (hatched slate), an
-// evaluation, an absence (dashed), a note; the words carry it, the look only repeats them (§7.4).
+// evaluation, an absence (dashed), a note; on a run's page (4e-1), a request sent (live orange), maybe sent (the
+// warning's, dashed) and an error's code (mono); the words carry it, the look only repeats them (§7.4).
 import type { SimTag, SimTagKind } from "./results";
 
 const LOOK: Record<SimTagKind, string> = {
@@ -15,6 +16,9 @@ const LOOK: Record<SimTagKind, string> = {
   evaluated: "rounded-sm border border-line-strong bg-surface px-1.5 text-muted",
   absent: "rounded-sm border border-dashed border-line-strong bg-surface px-1.5 text-muted",
   note: "bg-surface text-muted",
+  sent: "rounded-sm border border-live bg-surface px-1.5 text-live",
+  maybe: "rounded-sm border border-dashed border-warn-line bg-surface px-1.5 text-warn-ink",
+  code: "bg-surface font-mono text-danger",
 };
 
 const PLACE = {
@@ -24,10 +28,13 @@ const PLACE = {
   under: "top-full left-0 mt-[56px] block w-[260px] truncate",
 } as const;
 
-export function SimTags({ label, tags, place = "beside" }: { label: string; tags: SimTag[]; place?: keyof typeof PLACE }) {
+/** `what` the tags are: a simulated result (the editor's), or a run's result (its page's). */
+export function SimTags({ label, tags, place = "beside", what = "simulated result" }: {
+  label: string; tags: SimTag[]; place?: keyof typeof PLACE; what?: string;
+}) {  // prettier-ignore
   if (tags.length === 0) return null;
   return (
-    <ul aria-label={`${label}: simulated result`} className={`pointer-events-none absolute text-meta ${PLACE[place]}`}>
+    <ul aria-label={`${label}: ${what}`} className={`pointer-events-none absolute text-meta ${PLACE[place]}`}>
       {tags.map((t, i) => (
         // Inline, so a line cut short ends in "…"; a flex item when beside.
         <li key={i} className={`inline leading-[18px] whitespace-nowrap ${place === "under" ? "me-1" : "@max-3xl:me-1"} ${LOOK[t.kind]}`}>{t.text}</li>
diff --git a/frontend/src/routes/editor/simulation/results.ts b/frontend/src/routes/editor/simulation/results.ts
index 1377918a..3c11676d 100644
--- a/frontend/src/routes/editor/simulation/results.ts
+++ b/frontend/src/routes/editor/simulation/results.ts
@@ -1,14 +1,19 @@
 // SPDX-License-Identifier: Apache-2.0
-// A simulated step's result, as tags beside its card (4d-1c; the simulation design §7.3, §7.4; the ResultCanvas and
-// Running boards), from the server's per-step summary, never a partial page. A step that ran once shows its final
-// attempt; a loop's step totals its instances, one per opened iteration, skipped ones included, its ports apart; a
-// step with none says why, in the server's tag. Always words: the colour and the hatch only repeat them.
+// A step's result, as tags beside its card (4d-1c; the simulation design §7.3, §7.4; the ResultCanvas and Running
+// boards), from the server's per-step summary, never a partial page. A step that ran once shows its final attempt; a
+// loop's step totals its instances, one per opened iteration, skipped ones included, its ports apart; a step with none
+// says why, in the server's tag. Always words: the colour and the hatch only repeat them. A run's page (editor 4e-1;
+// the runs design §5.3, §5.5) says the same of any run: a live step's origin (sent, may have been sent; a control step
+// says none, its port alone), how long an action took, and a failure's code.
 import { CARD } from "../../../lib/layout";
-import type { Origin, StepSummary } from "../../../lib/simulations";
+import type { RunOrigin } from "../../../lib/runs";
+import { took } from "../../../lib/runStatus";
+
+type Origin = NonNullable<RunOrigin>;
 
 /** What a tag is: a status (ok, failed or other), values a person gave, a plugin's fixture, an evaluation, an absence,
- * or a note (an attempt, a loop's iterations). */
-export type SimTagKind = "ok" | "fail" | "status" | "given" | "fixture" | "evaluated" | "absent" | "note";
+ * a note (an attempt, a loop's iterations, a time), a live step's request sent or maybe sent, or an error's code. */
+export type SimTagKind = "ok" | "fail" | "status" | "given" | "fixture" | "evaluated" | "absent" | "note" | "sent" | "maybe" | "code";
 export interface SimTag {
   text: string;
   kind: SimTagKind;
@@ -16,6 +21,8 @@ export interface SimTag {
 
 /** §7.4's tags, in the server's code and the words the editor shows. */
 export const ORIGIN: Record<Origin | "input" | "seeded", string> = {
+  sent: "sent",
+  may_have_been_sent: "may have been sent",
   input: "input",
   seeded: "seeded",
   evaluated: "evaluated",
@@ -29,6 +36,8 @@ export const ORIGIN: Record<Origin | "input" | "seeded", string> = {
   not_reached_yet: "not reached yet",
 };
 const ORIGIN_KIND: Record<Origin, SimTagKind> = {
+  sent: "sent",
+  may_have_been_sent: "maybe",
   evaluated: "evaluated",
   evaluated_not_waited: "evaluated",
   fixture_not_sent: "fixture",
@@ -47,6 +56,7 @@ const ORDER = ["succeeded", "failed", "cancelled", "skipped", "not_started", "ru
 const said = (status: string) => status.replace("_", " ");
 const statusKind = (status: string): SimTagKind => (status === "succeeded" ? "ok" : status === "failed" ? "fail" : "status");
 export const field = (v: unknown, key: string): unknown => (typeof v === "object" && v !== null && !Array.isArray(v) ? (v as Record<string, unknown>)[key] : undefined);
+const strOf = (v: unknown) => (typeof v === "string" ? v : null);
 
 export const words = (tags: SimTag[]) => tags.map((t) => t.text);
 
@@ -61,10 +71,23 @@ export function tagsFitBeside(at: At, others: At[]): boolean {
   return !others.some((o) => o.x < box.x + box.width && box.x < o.x + CARD.width && o.y < box.y + box.height && box.y < o.y + CARD.height);
 }
 
-/** A step's tags. `maxAttempts`: its own, or its type's (an attempt is said "of" it); `ended`: whether the
- * simulation has (while it runs, a loop's step says what it has so far). */
-export function tagsOf(s: StepSummary, { maxAttempts, ended }: { maxAttempts: number | null; ended: boolean }): SimTag[] {
-  if (s.instances === 0) return [{ text: ORIGIN[s.origin], kind: ORIGIN_KIND[s.origin] }];
+/** A step's summary, a simulation's or any run's: a live one's origin may be none. */
+export interface Summary {
+  type: string;
+  origin: RunOrigin;
+  instances: number;
+  statuses: Record<string, number>;
+  ports: Record<string, number>;
+  final?: unknown;
+}
+
+const originTags = (origin: RunOrigin): SimTag[] => (origin === null ? [] : [originTag(origin)]);
+
+/** A step's tags. `maxAttempts`: its own, or its type's (an attempt is said "of" it); `ended`: whether the run has
+ * (while it runs, a loop's step says what it has so far). `run`, on a run's page: whether the step is an action, whose
+ * time is said; a control step's is the engine's own. A failure says its code there, in place of its time. */
+export function tagsOf(s: Summary, { maxAttempts, ended, run }: { maxAttempts: number | null; ended: boolean; run?: { action: boolean } }): SimTag[] {
+  if (s.instances === 0) return originTags(s.origin);
   const loop = s.type.startsWith("flow.loop@");
   if (s.instances === 1) {
     const status = typeof field(s.final, "status") === "string" ? (field(s.final, "status") as string) : (Object.keys(s.statuses)[0] ?? "running");
@@ -80,14 +103,21 @@ export function tagsOf(s: StepSummary, { maxAttempts, ended }: { maxAttempts: nu
       return tags;
     }
     const port = field(field(s.final, "effect"), "port");
-    const origin = ORIGIN[s.origin] + (typeof port === "string" && s.origin === "evaluated" ? ` · → ${port}` : "");
-    return [...tags, { text: origin, kind: ORIGIN_KIND[s.origin] }];
+    if (s.origin === "evaluated" && typeof port === "string") tags.push({ text: `${ORIGIN.evaluated} · → ${port}`, kind: "evaluated" });
+    else if (s.origin === null && typeof port === "string") tags.push({ text: `→ ${port}`, kind: "evaluated" });
+    else tags.push(...originTags(s.origin));
+    if (!run) return tags;
+    const code = field(field(s.final, "error"), "code");
+    const time = run.action ? took(strOf(field(s.final, "started_at")), strOf(field(s.final, "ended_at"))) : null;
+    if (status === "failed" && typeof code === "string") tags.push({ text: code, kind: "code" });
+    else if (time !== null) tags.push({ text: time, kind: "note" });
+    return tags;
   }
   const counts = ORDER.filter((k) => (s.statuses[k] ?? 0) > 0).map((k) => `${s.statuses[k]} ${said(k)}`).join(" · ");
   const total = `${s.instances} instances: ${counts}`;
   return [
     { text: ended ? total : `So far, ${total}`, kind: "status" },
-    ...(loop ? [] : [{ text: ORIGIN[s.origin], kind: ORIGIN_KIND[s.origin] }]),
+    ...(loop ? [] : originTags(s.origin)),
     ...Object.entries(s.ports).map(([port, n]): SimTag => ({ text: `→ ${port} ×${n}`, kind: "evaluated" })),
   ];
 }
```

- [ ] **Step 4: Run them again**

Run: the same command.

Expected: PASS, 22 passed.

- [ ] **Step 5: Static checks**

Run: the two of "How to run things". Expected: no output.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/routes/editor/simulation frontend/src/lib
git commit -m "feat(editor): a run's tags: sent, may have been sent, an action's time, a failure's code (4e-1b)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: A run's page

**Spec:** §5.3 (the bar, the banner, the canvas, the tags, reading), §5.6 (the live region), §3's answers 4 and 6, §5.1
(the shared canvas and the editor's chunk); the RunFailed and RunRunning boards, and RunOther's draft simulation.

**Files:**
- Create: `frontend/src/routes/runs/RunBar.tsx`, `frontend/src/routes/runs/useRunReads.ts`
- Modify: `frontend/src/routes/runs/RunPage.tsx`, `frontend/src/routes/runs/RunPage.test.tsx`,
  `frontend/src/routes/runs/trigger.tsx`, `frontend/src/test/runs.ts`
- Modify: `frontend/src/routes/editor/Canvas.tsx`, `frontend/src/routes/editor/StepCard.tsx`,
  `frontend/src/routes/editor/StartCard.tsx`, `frontend/src/routes/editor/Editor.tsx`,
  `frontend/src/routes/editor/Editor.test.tsx`, `frontend/src/routes/editor/simulation/lifecycle.ts`
- Modify: `frontend/e2e/workflows.spec.ts`

**Interfaces:**
- Consumes: `useCanvasNav` (Task 7); `tagsOf`, `SimTag` (Task 8); `runQuery`, `runStepsQuery`, `isEnded` (Task 3);
  `pollEvery`, `draftSnapshotQuery` (`lib/simulations.ts`); `versionQuery` (`lib/triggers.ts`); `nodeTypesQuery`;
  `endedWhat` (`lifecycle.ts`, its steps typed by key and statuses only).
- Produces:
  - `useRunReads(tenantId, runId): { run, steps }`.
  - `RunBar({ tenantId, run, version, children? })` (its heading's id `run-title`), `RunBanner({ run })`.
  - `triggerOf` gains `words` (plain text); `triggerWords(run)` ("webhook, Mist events").
  - `CanvasProps.results` (was `simulated`) and `resultsLabel`; `start.label`; `StepData.results`, `resultsPlace`,
    `resultsLabel`; `StartData.label`, `resultsLabel`.
  - `test/runs.ts`: `local(h, m, s, ms?, day?)`, `FAILED_RUN`, `FAILED_GRAPH`, `FAILED_STEPS`, `RUN_TYPES`,
    `attempt(key, over?)`.

A run's page, laid out like the editor: the bar (← Runs, the workflow, "run 4a2b17e0", Copy id, the status chip, Live
or Simulated, its version or a draft's revision, trigger, start and duration, Open the workflow); the banner, live in
orange or a simulation hatched, in the present while it runs (ruling 18); how it ended; the graph it ran (its version's,
or the draft a draft simulation froze), read only, each step's result beside its card, walked with the editor's keys.
It's read every second while it runs, backing off to 5 s, its steps every 5 s; its end is said, and both are read once
more 5 s later (ruling 19). A read that fails later keeps the page and says so. The editor's e2e asset test asserts by
meaning (ruling 21).

- [ ] **Step 1: Write the failing tests**

Apply:

```diff
diff --git a/frontend/e2e/workflows.spec.ts b/frontend/e2e/workflows.spec.ts
index 0a6704c3..f10810c5 100644
--- a/frontend/e2e/workflows.spec.ts
+++ b/frontend/e2e/workflows.spec.ts
@@ -214,7 +214,7 @@ async function assetsFetched(page: Page, act: () => Promise<void>): Promise<Map<
   return seen;
 }
 
-const EDITOR_CHUNK = /^\/assets\/Editor-[\w-]+\.(?:js|css)$/;
+const EDITOR_CHUNK = /^\/assets\/Editor-[\w-]+\.js$/;
 
 test("the list and sign-in load without the editor's code, which loads when a workflow opens", async ({ page, browser }) => {
   const total = (m: Map<string, number>) => [...m.values()].reduce((a, b) => a + b, 0);
@@ -235,7 +235,11 @@ test("the list and sign-in load without the editor's code, which loads when a wo
     await page.getByRole("link", { name: "Cycle" }).click();
     await expect(page.getByRole("button", { name: /^Start: by hand/ })).toBeVisible();
   });
-  expect([...opened.keys()].filter((p) => EDITOR_CHUNK.test(p)).length).toBe(2); // its script and its stylesheet
+  // Its script, and the canvas it shares with a run's page (React Flow and the cards, with their stylesheet), in a chunk
+  // Rollup names: none of it was in the list's or sign-in's load (the runs design §5.1).
+  expect([...opened.keys()].filter((p) => EDITOR_CHUNK.test(p))).toHaveLength(1);
+  expect([...opened.keys()].some((p) => p.endsWith(".css"))).toBe(true);
+  expect([...opened.keys()].filter((p) => list.has(p) || login.has(p))).toEqual([]);
   console.log(`first load: list ${total(list)} bytes, sign-in ${total(login)} bytes; the editor adds ${total(opened)} bytes`);
 });
 
diff --git a/frontend/src/routes/editor/Editor.test.tsx b/frontend/src/routes/editor/Editor.test.tsx
index 9ccb5368..ef4a5783 100644
--- a/frontend/src/routes/editor/Editor.test.tsx
+++ b/frontend/src/routes/editor/Editor.test.tsx
@@ -40,7 +40,7 @@ vi.mock("./Canvas", async () => {
           data-problems={String(props.problems.size)}
           data-problem-steps={[...props.problems.keys()].join(",")}
           data-conditional={[...props.conditional].join(",")}
-          data-simulated={JSON.stringify((props.simulated ? [...props.simulated.entries()] : []).map(([k, tags]) => [k, tags.map((t) => t.text)]))}
+          data-simulated={JSON.stringify((props.results ? [...props.results.entries()] : []).map(([k, tags]) => [k, tags.map((t) => t.text)]))}
           data-start-tags={(props.start.tags ?? []).map((t) => t.text).join(",")}
         >
           <button data-item="start" data-summary={props.start.summary} aria-expanded={props.start.open} onClick={props.start.onOpen}>Start</button>
diff --git a/frontend/src/routes/runs/RunPage.test.tsx b/frontend/src/routes/runs/RunPage.test.tsx
index a654a6bc..0df1036e 100644
--- a/frontend/src/routes/runs/RunPage.test.tsx
+++ b/frontend/src/routes/runs/RunPage.test.tsx
@@ -1,35 +1,86 @@
 // SPDX-License-Identifier: Apache-2.0
 import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
 import { RouterProvider, createMemoryHistory, createRootRoute, createRoute, createRouter } from "@tanstack/react-router";
-import { render, screen } from "@testing-library/react";
+import { act, render, screen, within } from "@testing-library/react";
 import userEvent from "@testing-library/user-event";
-import { beforeEach, expect, it, vi } from "vitest";
-import type { Run } from "../../lib/runs";
-import { item } from "../../test/runs";
+import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
+import { onAnnounce } from "../../lib/announce";
+import type { Run, RunSteps } from "../../lib/runs";
+import { FAILED_GRAPH, FAILED_RUN, FAILED_STEPS, RUN_TYPES, local } from "../../test/runs";
+import type { CanvasProps } from "../editor/Canvas";
 import { RunPage } from "./RunPage";
 
-const RUN: Run = {
-  ...item("4a2b17e0-3b2d-4e5f-9a1b-2c3d4e5f6a7b", "2026-10-16T09:41:12Z", { status: "failed", ended_at: "2026-10-16T09:41:50Z" }),
-  draft_revision: null, outcomes_recorded: true, parent: null, csv: null,
-};  // prettier-ignore
+// The canvas stands in as the editor's tests have it: React Flow isn't drawn in jsdom. It shows what it was given.
+vi.mock("../editor/Canvas", async () => {
+  const { useEffect } = await import("react");
+  return {
+    Canvas: (props: CanvasProps) => {
+      useEffect(() => {
+        if (props.focusRequest) document.querySelector<HTMLElement>(`[data-item="${props.focusRequest.id}"]`)?.focus();
+      }, [props.focusRequest]);
+      return (
+        <div
+          role="group"
+          aria-label="Workflow steps"
+          onKeyDown={props.onKeyDown}
+          onFocus={(e) => {
+            const id = (e.target as HTMLElement).dataset.item;
+            if (id) props.onFocusItem(id);
+          }}
+          data-editable={String(props.editable)}
+          data-current={props.current ?? ""}
+          data-results-label={props.resultsLabel ?? ""}
+          data-results={JSON.stringify((props.results ? [...props.results.entries()] : []).map(([k, tags]) => [k, tags.map((t) => t.text)]))}
+          data-start-tags={(props.start.tags ?? []).map((t) => t.text).join(",")}
+        >
+          <button data-item="start" tabIndex={props.focusId === "start" ? 0 : -1} aria-label={props.start.label} onClick={props.start.onOpen}>
+            {props.start.summary}
+          </button>
+          {(props.doc.nodes ?? []).map((n) => (
+            <button key={n.id} data-item={`node:${n.id}`} tabIndex={props.focusId === `node:${n.id}` ? 0 : -1} onClick={() => props.onItem({ kind: "open", node: n.id })}>
+              {n.key}
+            </button>
+          ))}
+        </div>
+      );
+    },
+  };
+});
+
+const RUN: Run = FAILED_RUN;
+const NOW = Date.parse(local(10, 2, 19));
+const VERSION = { id: "v2", number: 2, graph: FAILED_GRAPH, active: true, blocked_by: [], cel_profile: "p", engine_abi: 9, executable: true,
+  expressions: [], graph_hash: "h", node_refs: [], published_at: local(8, 0, 0), published_by: null, version_hash: "vh" };  // prettier-ignore
 
 let answers: Map<string, () => Response>;
+let reads: string[];
 
 beforeEach(() => {
-  answers = new Map();
+  answers = new Map([
+    ["/api/v1/node-types", json(RUN_TYPES)],
+    ["/api/v1/t/t1/workflows/w1/versions/v2", json(VERSION)],
+    [`/api/v1/t/t1/runs/${RUN.id}/steps`, json(FAILED_STEPS)],
+  ]);
+  reads = [];
+  vi.spyOn(Date, "now").mockReturnValue(NOW);
   vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
     const path = new URL((input as Request).url).pathname;
+    reads.push(path);
     const answer = answers.get(path);
     return Promise.resolve(answer ? answer() : new Response(JSON.stringify({ error: "not_found" }), { status: 404 }));
   });
 });
+afterEach(() => vi.restoreAllMocks());
 
-const json = (body: unknown, status = 200) => () => new Response(JSON.stringify(body), { status });
+function json(body: unknown, status = 200) {
+  return () => new Response(JSON.stringify(body), { status });
+}
 
 function show(runId = RUN.id) {
   const root = createRootRoute({ component: () => <RunPage tenantId="t1" runId={runId} /> });
-  const runs = createRoute({ getParentRoute: () => root, path: "/t/$tenantId/runs", component: () => <p>the Runs page</p> });
-  const router = createRouter({ routeTree: root.addChildren([runs]), history: createMemoryHistory({ initialEntries: ["/"] }) });
+  const runs = createRoute({ getParentRoute: () => root, path: "/t/$tenantId/runs" });
+  const editor = createRoute({ getParentRoute: () => root, path: "/t/$tenantId/workflows/$workflowId" });
+  const router = createRouter({ routeTree: root.addChildren([runs, editor]), history: createMemoryHistory({ initialEntries: ["/"] }) });
   render(
     <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
       <RouterProvider router={router} />
@@ -69,3 +120,149 @@ it("says the run couldn't be read, and reads it again when asked", async () => {
   await userEvent.click(screen.getByRole("button", { name: "Try again" }));
   expect(await screen.findByRole("heading", { level: 1, name: "AP offline triage" })).toBeTruthy();
 });
+
+const canvas = () => screen.getByRole("group", { name: "Workflow steps" });
+const bar = () => screen.getByRole("heading", { level: 1 }).parentElement!;
+
+describe("a run's page (§5.3; the RunFailed board)", () => {
+  it("shows a failed live run: its bar, the live banner, and each step's result on its version's canvas, read only", async () => {
+    answers.set(`/api/v1/t/t1/runs/${RUN.id}`, json(RUN));
+    const router = show();
+    await vi.waitFor(() => expect(canvas().dataset.results).not.toBe("[]"));
+    expect(within(bar()).getByText("Failed").className).toContain("border-danger");
+    expect(within(bar()).getByText("Live").className).toContain("text-live");
+    expect(within(bar()).getByText(/^version 2 · webhook, Mist events · started/).textContent).toBe("version 2 · webhook, Mist events · started today 09:41:12 · 38 s");
+    expect(screen.getByRole("note").textContent).toBe("Live run. It acted for real: steps marked sent called their connections.");
+    expect(screen.getByText(/^Ended: failed at notify_noc/).textContent).toBe("Ended: failed at notify_noc · today 09:41:50");
+    expect(canvas().dataset.editable).toBe("false");
+    expect(canvas().dataset.resultsLabel).toBe("result");
+    expect(JSON.parse(canvas().dataset.results!)).toEqual([
+      ["id-get_device", ["succeeded", "sent", "0.4 s"]],
+      ["id-is_down", ["succeeded", "→ true"]],
+      ["id-open_case", ["succeeded", "sent", "1.8 s"]],
+      ["id-notify_noc", ["failed", "attempt 3 of 3", "channel_not_found"]],
+      ["id-log_recovery", ["skipped"]],
+    ]);
+    expect(canvas().dataset.startTags).toBe("input");
+    expect(screen.getByRole("button", { name: "Start: webhook, Mist events. Open the run's start" })).toBeTruthy();
+    await userEvent.click(screen.getByRole("link", { name: "Open the workflow" }));
+    expect(router.state.location.pathname).toBe("/t/t1/workflows/w1");
+  });
+
+  it("copies the run's whole id, and says so", async () => {
+    const said: string[] = [];
+    const stop = onAnnounce((m) => said.push(m));
+    const writeText = vi.fn(() => Promise.resolve());
+    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
+    answers.set(`/api/v1/t/t1/runs/${RUN.id}`, json(RUN));
+    show();
+    await userEvent.click(await screen.findByRole("button", { name: "Copy id" }));
+    expect(writeText).toHaveBeenCalledWith(RUN.id);
+    await vi.waitFor(() => expect(said).toEqual(["Copied the run's id"]));
+    stop();
+  });
+
+  it("says when the browser refuses to copy the id", async () => {
+    const said: string[] = [];
+    const stop = onAnnounce((m) => said.push(m));
+    Object.defineProperty(navigator, "clipboard", { value: { writeText: () => Promise.reject(new Error("denied")) }, configurable: true });
+    answers.set(`/api/v1/t/t1/runs/${RUN.id}`, json(RUN));
+    show();
+    await userEvent.click(await screen.findByRole("button", { name: "Copy id" }));
+    await vi.waitFor(() => expect(said).toEqual(["The run's id couldn't be copied"]));
+    stop();
+  });
+
+  it("walks the read-only canvas with the arrow keys (D16)", async () => {
+    answers.set(`/api/v1/t/t1/runs/${RUN.id}`, json(RUN));
+    show();
+    await vi.waitFor(() => expect(canvas().dataset.results).not.toBe("[]"));
+    within(canvas()).getByRole("button", { name: "Start: webhook, Mist events. Open the run's start" }).focus();
+    await userEvent.keyboard("{ArrowDown}");
+    expect(document.activeElement?.textContent).toBe("get_device");
+    await userEvent.keyboard("{ArrowDown}{ArrowDown}");
+    expect(document.activeElement?.textContent).toBe("open_case");
+  });
+
+  it("says a draft simulation is one, names its revision, reads the draft it ran and opens in the editor (the RunOther board)", async () => {
+    const draft: Run = { ...RUN, status: "succeeded", mode: "simulate", version_id: null, draft_snapshot_id: "s1", draft_revision: 14, error: null,
+      started_by: "nadia@example.com", trigger: { source: "manual", schedule: null, endpoint: null, rerun_of: null } };  // prettier-ignore
+    answers.set(`/api/v1/t/t1/runs/${RUN.id}`, json(draft));
+    answers.set("/api/v1/t/t1/workflows/w1/draft/snapshots/s1", json({ id: "s1", revision: 14, graph: FAILED_GRAPH }));
+    show();
+    await vi.waitFor(() => expect(canvas().dataset.results).not.toBe("[]"));
+    expect(within(bar()).getByText("Draft simulation").className).toContain("hatch-sim");
+    expect(within(bar()).getByText(/^draft revision 14/).textContent).toBe("draft revision 14 · by hand, nadia@example.com · started today 09:41:12 · 38 s");
+    expect(screen.getByText(/^Simulated\./).closest("[class*=hatch-sim]")!.textContent).toBe("Simulated. Nothing was sent. The draft's revision 14 ran, not a published version.");
+    expect(screen.getByRole("link", { name: "Open in the editor" })).toBeTruthy();
+    expect(reads).not.toContain("/api/v1/t/t1/workflows/w1/versions/v2");
+  });
+});
+
+describe("reading a run while it runs (§5.3)", () => {
+  // Timers the test moves on, and real time besides, so the page's own waits still pass.
+  beforeEach(() => void vi.useFakeTimers({ toFake: ["setTimeout", "setInterval", "clearTimeout", "clearInterval"], shouldAdvanceTime: true }));
+  afterEach(() => void vi.useRealTimers());
+
+  const running: Run = { ...RUN, status: "running", ended_at: null, error: null };
+  const runningSteps: RunSteps = { ...FAILED_STEPS, steps: FAILED_STEPS.steps.slice(0, 3) };
+  const count = (path: string) => reads.filter((r) => r === path).length;
+  const RUN_PATH = `/api/v1/t/t1/runs/${RUN.id}`;
+  const STEPS_PATH = `${RUN_PATH}/steps`;
+
+  it("says a live run acts for real while it runs, and how long so far", async () => {
+    answers.set(RUN_PATH, json(running));
+    show();
+    await vi.waitFor(() => expect(screen.getByRole("note").textContent).toBe("Live run. It acts for real: steps marked sent called their connections."));
+    expect(within(bar()).getByText(/^version 2/).textContent).toBe("version 2 · webhook, Mist events · started today 09:41:12 · 21 min 7 s so far");
+  });
+
+  it("reads it every second at first, backing off; its steps at most every 5 s", async () => {
+    answers.set(RUN_PATH, json(running));
+    answers.set(STEPS_PATH, json(runningSteps));
+    show();
+    await vi.waitFor(() => expect(count(STEPS_PATH)).toBe(1));
+    await act(() => vi.advanceTimersByTimeAsync(1000));
+    expect(count(RUN_PATH)).toBe(2);
+    expect(count(STEPS_PATH)).toBe(1);
+    await act(() => vi.advanceTimersByTimeAsync(4000));
+    expect(count(RUN_PATH)).toBe(3); // at 0, 1 and 3 s: a second, then two, then three… (as a simulation, pollEvery)
+    expect(count(STEPS_PATH)).toBe(2);
+  });
+
+  it("keeps the run when a read fails while it runs, says as of when, and tries again", async () => {
+    answers.set(RUN_PATH, json(running));
+    answers.set(STEPS_PATH, json(runningSteps));
+    show();
+    await vi.waitFor(() => expect(count(STEPS_PATH)).toBe(1));
+    answers.set(RUN_PATH, json({ error: "internal_error" }, 500));
+    await act(() => vi.advanceTimersByTimeAsync(1000));
+    expect(await screen.findByText("Couldn't be refreshed · as of 10:02:19")).toBeTruthy();
+    expect(screen.getByRole("heading", { level: 1, name: "AP offline triage" })).toBeTruthy();
+    expect(canvas().dataset.results).not.toBe("[]");
+    answers.set(RUN_PATH, json(running));
+    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
+    await vi.waitFor(() => expect(screen.queryByText(/^Couldn't be refreshed/)).toBeNull());
+  });
+
+  it("says when it ends, reads its steps then and once more 5 s later, and then no more", async () => {
+    const said: string[] = [];
+    const stop = onAnnounce((m) => said.push(m));
+    answers.set(RUN_PATH, json(running));
+    answers.set(STEPS_PATH, json(runningSteps));
+    show();
+    await vi.waitFor(() => expect(count(STEPS_PATH)).toBe(1));
+    answers.set(RUN_PATH, json(RUN));
+    answers.set(STEPS_PATH, json(FAILED_STEPS));
+    await act(() => vi.advanceTimersByTimeAsync(1000));
+    await vi.waitFor(() => expect(said).toEqual(["Run ended: failed"]));
+    await vi.waitFor(() => expect(count(STEPS_PATH)).toBe(2));
+    const [run, steps] = [count(RUN_PATH), count(STEPS_PATH)];
+    await act(() => vi.advanceTimersByTimeAsync(5000));
+    expect([count(RUN_PATH), count(STEPS_PATH)]).toEqual([run + 1, steps + 1]);
+    await act(() => vi.advanceTimersByTimeAsync(30_000));
+    expect([count(RUN_PATH), count(STEPS_PATH)]).toEqual([run + 1, steps + 1]);
+    expect(said).toEqual(["Run ended: failed"]);
+    stop();
+  });
+});
diff --git a/frontend/src/test/runs.ts b/frontend/src/test/runs.ts
index 64578e3d..69515754 100644
--- a/frontend/src/test/runs.ts
+++ b/frontend/src/test/runs.ts
@@ -1,6 +1,13 @@
 // SPDX-License-Identifier: Apache-2.0
-// Runs for tests, as the API serves them (editor 4e-1): a list item, made up, never a real tenant's (D24).
-import type { RunItem } from "../lib/runs";
+// Runs for tests, as the API serves them (editor 4e-1): a list item; the RunFailed board's run, its graph and its
+// steps. Made up, never a real tenant's (D24).
+import type { Run, RunItem, RunStep, RunStepSummary, RunSteps } from "../lib/runs";
+import type { GraphDoc, NodeType } from "../lib/workflows";
+import { IF, TRANSFORM, typeWith } from "./nodeTypes";
+
+/** An instant on the person's own clock, today (16 October 2026) unless `day` says: what a page says of it doesn't
+ * depend on the zone the tests run in. */
+export const local = (h: number, m: number, s: number, ms = 0, day = 16) => new Date(2026, 9, day, h, m, s, ms).toISOString();
 
 /** A live run a webhook started, succeeded, queued and started at `queuedAt`. */
 export const item = (id: string, queuedAt: string | null, over: Partial<RunItem> = {}): RunItem => ({
@@ -9,3 +16,58 @@ export const item = (id: string, queuedAt: string | null, over: Partial<RunItem>
   kind: "run", parent_run_id: null, request: { status: "started", source: "webhook", reason: null }, started_by: null,
   cancel_requested_at: null, trigger: { source: "webhook", schedule: null, endpoint: "Mist events", rerun_of: null }, ...over,
 });  // prettier-ignore
+
+/** The RunFailed board: a live run a webhook started on version 2, which failed at `notify_noc`. */
+export const FAILED_RUN: Run = {
+  ...item("4a2b17e0-3b2d-4e5f-9a1b-2c3d4e5f6a7b", local(9, 41, 12), { status: "failed", ended_at: local(9, 41, 50) }),
+  error: { code: "channel_not_found", message: "The channel wasn't found." },
+  draft_revision: null, outcomes_recorded: true, parent: null, csv: null,
+};  // prettier-ignore
+
+/** Its steps' types: three actions of a made-up service (D24), an If and a Transform. */
+export const RUN_TYPES: NodeType[] = [
+  typeWith({}, { ref: "acme.get_device@1", type: "acme.get_device", title: "Get a device" }),
+  typeWith({}, { ref: "acme.send_request@1", type: "acme.send_request", title: "Send a request" }),
+  typeWith({}, { ref: "acme.post_message@1", type: "acme.post_message", title: "Post a message" }),
+  IF,
+  TRANSFORM,
+];
+
+const step = (key: string, type: string, y: number, x = 0) => ({ id: `id-${key}`, key, type, position: { x, y } });
+const to = (from: string, target: string, port = "out") => ({ from: { node: `id-${from}`, port }, to: { node: `id-${target}` } });
+/** Version 2's graph: get_device, then is_down; true: open_case then notify_noc; false: log_recovery. */
+export const FAILED_GRAPH: GraphDoc = {
+  graph_format: 1,
+  nodes: [
+    step("get_device", "acme.get_device@1", 140), step("is_down", "flow.if@1", 280), step("open_case", "acme.send_request@1", 420),
+    step("notify_noc", "acme.post_message@1", 560), step("log_recovery", "flow.transform@1", 420, 400),
+  ],
+  edges: [to("get_device", "is_down"), to("is_down", "open_case", "true"), to("open_case", "notify_noc"), to("is_down", "log_recovery", "false")],
+};  // prettier-ignore
+
+/** An attempt of a step in the failed run. */
+export const attempt = (key: string, over: Partial<RunStep> = {}): RunStep => ({
+  step_id: `id-${key}`, key, iteration_key: "", attempt: 1, status: "succeeded", started_at: local(9, 41, 13), ended_at: local(9, 41, 13, 400),
+  input: null, output: null, error: null, outcome: null, cel_mode: null, effect: null, ...over,
+});  // prettier-ignore
+const summary = (key: string, type: string, over: Partial<RunStepSummary> = {}): RunStepSummary => ({
+  step_id: `id-${key}`, key, type, origin: null, instances: 1, statuses: { succeeded: 1 }, ports: {}, final: attempt(key), ...over,
+});  // prettier-ignore
+/** Its steps in run order, as the server sums them up. */
+export const FAILED_STEPS: RunSteps = {
+  given: "input",
+  steps: [
+    summary("get_device", "acme.get_device@1", { origin: "sent" }),
+    summary("is_down", "flow.if@1", { ports: { true: 1 }, final: attempt("is_down", { effect: { port: "true" } }) }),
+    summary("open_case", "acme.send_request@1", { origin: "sent", final: attempt("open_case", { started_at: local(9, 41, 14), ended_at: local(9, 41, 15, 800) }) }),
+    summary("notify_noc", "acme.post_message@1", {
+      statuses: { failed: 1 },
+      final: attempt("notify_noc", {
+        attempt: 3, status: "failed", started_at: local(9, 41, 49), ended_at: local(9, 41, 50),
+        error: { code: "channel_not_found", message: "The channel wasn't found." },
+        input: { channel: "#noc-alert", text: "AP Paris-Opera-12 offline since 09:38", token: "[redacted]", blocks: "[truncated]" },
+      }),
+    }),
+    summary("log_recovery", "flow.transform@1", { origin: "skipped", statuses: { skipped: 1 }, final: attempt("log_recovery", { status: "skipped" }) }),
+  ],
+};  // prettier-ignore
```

- [ ] **Step 2: Run them**

Run: `npx --offline pnpm@12.6.0 exec vitest run src/routes/runs/RunPage.test.tsx src/routes/editor/Editor.test.tsx
src/routes/editor/StepCard.test.tsx`

Expected: FAIL, 12 failed and 172 passed: a run's page shows no bar, banner or canvas (`Unable to find an accessible
element with the role "group" and name "Workflow steps"`, no Copy id) and isn't read again (`expected +0 to be 1`); the
editor's three tests that read the canvas's tags see none (`expected '[]' to be
'[["id-transform",["succeeded","evalua…'`): the stand-in now reads `results`, which the canvas doesn't have yet. The
step card's tests pass.

- [ ] **Step 3: Implement**

Apply:

```diff
diff --git a/frontend/src/routes/editor/Canvas.tsx b/frontend/src/routes/editor/Canvas.tsx
index d413729f..49218dfd 100644
--- a/frontend/src/routes/editor/Canvas.tsx
+++ b/frontend/src/routes/editor/Canvas.tsx
@@ -49,8 +49,10 @@ export interface CanvasProps {
   placing: boolean; // the next click on an empty place puts a step there (WCAG 2.5.7)
   overview: boolean; // the minimap: off while a side panel narrows the canvas (the owner's ruling on milestone 3)
   onPlace: (at: { x: number; y: number }) => void; // the click, in the canvas's own coordinates
-  start: { summary: string; open: boolean; onOpen: () => void; tags?: SimTag[] }; // the start card: what starts a run, and its panel
-  simulated?: Map<string, SimTag[]>; // each step's result in the editor's simulation, by identity (4d-1c)
+  // the start card: what starts a run, and its panel; its name when it opens something else (a run's start)
+  start: { summary: string; open: boolean; onOpen: () => void; tags?: SimTag[]; label?: string };
+  results?: Map<string, SimTag[]>; // each step's result, by identity: the editor's simulation (4d-1c), or a run (4e-1)
+  resultsLabel?: string; // what those results are, in their names: "simulated result" unless said
 }
 
 /** What React Flow draws: the start card, each step, an edge from the start card to each entry step, and each edge
@@ -60,7 +62,9 @@ function build(p: CanvasProps): { nodes: Node[]; edges: Edge[] } {
   const used = new Map<string, string[]>();
   for (const e of drawableEdges(p.doc)) used.set(idKey(e.from.node), [...(used.get(idKey(e.from.node)) ?? []), portOf(e)]);
   const keyOf = new Map(nodesOf(p.doc).map((n) => [idKey(n.id), n.key]));
-  const start: StartData = { empty: nodesOf(p.doc).length === 0, focusId: p.focusId, editable: p.editable, onItem: p.onItem, ...p.start };
+  const start: StartData = {
+    empty: nodesOf(p.doc).length === 0, focusId: p.focusId, editable: p.editable, onItem: p.onItem, resultsLabel: p.resultsLabel, ...p.start,
+  };  // prettier-ignore
   // A result's tags go beside a card, else under it where another card is beside it (the review's 1).
   const corners = nodesOf(p.doc).map(pos);
   const placeOf = (i: number) => (tagsFitBeside(corners[i]!, [startPosition(p.doc), ...corners.filter((_, j) => j !== i)]) ? "beside" : "under");
@@ -73,8 +77,9 @@ function build(p: CanvasProps): { nodes: Node[]; edges: Edge[] } {
         separate: p.separate.get(idKey(n.id)) ?? 0, conditional: p.conditional.has(idKey(n.id)), current: p.current !== null && sameId(p.current, n.id), focusId: p.focusId,
         editable: p.editable,
         onItem: p.onItem,
-        simulated: p.simulated?.get(idKey(n.id)),
-        simulatedPlace: p.simulated?.has(idKey(n.id)) ? placeOf(i) : undefined,
+        results: p.results?.get(idKey(n.id)),
+        resultsPlace: p.results?.has(idKey(n.id)) ? placeOf(i) : undefined,
+        resultsLabel: p.resultsLabel,
       };  // prettier-ignore
       return { id: idKey(n.id), type: "step", position: pos(n), draggable: p.editable, selectable: false, data, ...SIZE };
     }),
diff --git a/frontend/src/routes/editor/Editor.tsx b/frontend/src/routes/editor/Editor.tsx
index cf07a152..f825aeeb 100644
--- a/frontend/src/routes/editor/Editor.tsx
+++ b/frontend/src/routes/editor/Editor.tsx
@@ -1364,7 +1364,7 @@ function Editor({
             onOpen: () => setSide(side?.kind === "triggers" ? null : { kind: "triggers" }),
             tags: resultShown && simulation.steps?.given === "input" ? [{ text: "input", kind: "given" }] : undefined,
           }}
-          simulated={simulated}
+          results={simulated}
           />
         </div>
         {open && (
diff --git a/frontend/src/routes/editor/StartCard.tsx b/frontend/src/routes/editor/StartCard.tsx
index 4bff7bdf..43a75e8c 100644
--- a/frontend/src/routes/editor/StartCard.tsx
+++ b/frontend/src/routes/editor/StartCard.tsx
@@ -18,6 +18,8 @@ export type StartData = {
   summary: string; // what starts a run, in words
   open: boolean; // the Triggers panel is open
   tags?: SimTag[]; // in a simulation of the whole workflow: the input a person gave (§7.4)
+  resultsLabel?: string; // what those tags are, in their name
+  label?: string; // its name, when it opens something other than the Triggers panel (a run's start, 4e-1)
   onOpen: () => void;
 };
 
@@ -29,7 +31,7 @@ export function StartNode({ data }: NodeProps<Node<StartData, "start">>) {
         type="button"
         data-item={item.start}
         tabIndex={data.focusId === item.start ? 0 : -1}
-        aria-label={startLabel(data.summary)}
+        aria-label={data.label ?? startLabel(data.summary)}
         aria-expanded={data.open}
         onClick={data.onOpen}
         className="pointer-events-auto flex h-[64px] w-[260px] flex-col justify-center rounded-lg border border-dashed border-line-strong bg-surface px-3.5 text-left"
@@ -38,7 +40,7 @@ export function StartNode({ data }: NodeProps<Node<StartData, "start">>) {
         <span className="truncate text-small text-muted">{data.summary}</span>
       </button>
       <Handle type="source" id="out" position={Position.Bottom} isConnectable={false} />
-      {data.tags && <SimTags label="Start" tags={data.tags} />}
+      {data.tags && <SimTags label="Start" tags={data.tags} what={data.resultsLabel} />}
       {data.empty && data.editable && (
         <button
           type="button"
diff --git a/frontend/src/routes/editor/StepCard.tsx b/frontend/src/routes/editor/StepCard.tsx
index 7fe6aac3..d449ce74 100644
--- a/frontend/src/routes/editor/StepCard.tsx
+++ b/frontend/src/routes/editor/StepCard.tsx
@@ -86,8 +86,9 @@ export type StepData = {
   focusId: string;
   editable: boolean;
   onItem: (action: ItemAction) => void;
-  simulated?: SimTag[]; // its result in the editor's simulation, beside the card (4d-1c)
-  simulatedPlace?: "beside" | "under"; // where its tags go: under when another card is beside it
+  results?: SimTag[]; // its result, beside the card: in the editor's simulation (4d-1c), or a run (4e-1)
+  resultsPlace?: "beside" | "under"; // where its tags go: under when another card is beside it
+  resultsLabel?: string; // what they are, in their name
 };
 
 // React Flow turns a node's pointer events off when it can be neither selected nor dragged (ledger M11): its
@@ -115,7 +116,7 @@ export function StepNode({ data }: NodeProps<Node<StepData, "step">>) {
         tabIndex={data.focusId === item.node(node.id) ? 0 : -1}
         onOpen={() => data.onItem({ kind: "open", node: node.id })}
       />
-      {data.simulated && <SimTags label={node.key} tags={data.simulated} place={data.simulatedPlace} />}
+      {data.results && <SimTags label={node.key} tags={data.results} place={data.resultsPlace} what={data.resultsLabel} />}
       {ports.map((port, i) => {
         const from: PortRef = { node: node.id, port };
         const id = item.port(node.id, port);
diff --git a/frontend/src/routes/editor/simulation/lifecycle.ts b/frontend/src/routes/editor/simulation/lifecycle.ts
index 009864e9..92072b74 100644
--- a/frontend/src/routes/editor/simulation/lifecycle.ts
+++ b/frontend/src/routes/editor/simulation/lifecycle.ts
@@ -22,11 +22,11 @@ export function stepsEnded(steps: StepSummary[]): { ended: number; of: number }
   return { ended: steps.filter((s) => s.instances > 0 && !s.statuses.running).length, of: steps.length };
 }
 
-const did = (s: StepSummary, ...statuses: string[]) => statuses.some((k) => (s.statuses[k] ?? 0) > 0);
+const did = (s: Pick<StepSummary, "statuses">, ...statuses: string[]) => statuses.some((k) => (s.statuses[k] ?? 0) > 0);
 
 /** How a simulation ended, naming the step that decided it (the Lifecycle board): the first that failed, the last that
  * ran before a cancel, the one the deadline stopped. */
-export function endedWhat(phase: Phase, steps: StepSummary[]): string {
+export function endedWhat(phase: Phase, steps: Pick<StepSummary, "key" | "statuses">[]): string {
   if (phase === "failed") {
     const at = steps.find((s) => did(s, "failed"));
     return at ? `failed at ${at.key}` : "failed";
diff --git a/frontend/src/routes/runs/RunBar.tsx b/frontend/src/routes/runs/RunBar.tsx
new file mode 100644
index 00000000..61601a19
--- /dev/null
+++ b/frontend/src/routes/runs/RunBar.tsx
@@ -0,0 +1,74 @@
+// SPDX-License-Identifier: Apache-2.0
+// A run's bar and banner (editor 4e-1; the runs design §5.3; the RunFailed, RunRunning and RunOther boards). The bar:
+// the way back to Runs, the workflow, the run's short id and Copy id, its status and what it was (live in orange,
+// D3; a simulation hatched, D2), its version or a draft's revision, its trigger, start and duration, and Open the
+// workflow ("Open in the editor" for a draft simulation). The banner says what a live run did, or what a simulation
+// proves, in the present while it runs.
+import { Link } from "@tanstack/react-router";
+import type { ReactNode } from "react";
+import { Button, LINK_BUTTON } from "../../components/Button";
+import { ModeChip, RunStatusChip } from "../../components/RunChips";
+import { When } from "../../components/When";
+import { announce } from "../../lib/announce";
+import { isEnded, type Run } from "../../lib/runs";
+import { duration, runId } from "../../lib/runStatus";
+import { SimBanner } from "../editor/simulation/SimBanner";
+import { triggerWords } from "./trigger";
+
+/** The run's facts in a line: "version 2 · webhook, Mist events · started today 09:41:12 · 38 s". */
+function Facts({ run, version }: { run: Run; version: number | null }) {
+  const ended = isEnded(run.status);
+  const lead = run.draft_snapshot_id !== null ? `draft revision ${run.draft_revision}` : version !== null ? `version ${version}` : null;
+  const start = run.started_at ?? run.queued_at;
+  const lasted = duration(run.started_at, ended ? run.ended_at : new Date(Date.now()).toISOString());
+  return (
+    <span className="grow text-small text-muted">
+      {lead && `${lead} · `}
+      {triggerWords(run)}
+      {start && <> · {run.started_at ? "started" : "queued"} <When iso={start} /></>}
+      {lasted && ` · ${lasted}${ended ? "" : " so far"}`}
+    </span>
+  );
+}
+
+export function RunBar({ tenantId, run, version, children }: { tenantId: string; run: Run; version: number | null; children?: ReactNode }) {
+  const copy = () => navigator.clipboard.writeText(run.id).then(() => announce("Copied the run's id"), () => announce("The run's id couldn't be copied"));
+  return (
+    <div className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-line bg-surface px-5 py-2.5">
+      <Link to="/t/$tenantId/runs" params={{ tenantId }} className="text-small text-muted hover:text-ink">← Runs</Link>
+      <h1 className="min-w-0 truncate text-body-lg font-semibold">{run.workflow_name ?? "—"}</h1>
+      <span className="font-mono text-small">{`run ${runId(run.id)}`}</span>
+      <Button size="sm" onClick={() => void copy()}>Copy id</Button>
+      <RunStatusChip status={run.status} />
+      <ModeChip mode={run.mode} draft={run.draft_snapshot_id !== null} />
+      <Facts run={run} version={version} />
+      {children}
+      <Link to="/t/$tenantId/workflows/$workflowId" params={{ tenantId, workflowId: run.workflow_id }} className={LINK_BUTTON}>
+        {run.draft_snapshot_id !== null ? "Open in the editor" : "Open the workflow"}
+      </Link>
+    </div>
+  );
+}
+
+export function RunBanner({ run }: { run: Run }) {
+  const ended = isEnded(run.status);
+  if (run.mode === "live") {
+    return (
+      <p role="note" className="rounded-lg border border-live bg-live-bg px-3 py-2 text-small text-ink">
+        <strong className="text-live">Live run.</strong>
+        {` It ${ended ? "acted" : "acts"} for real: steps marked `}
+        <span className="rounded-sm border border-live bg-surface px-1.5 text-live">sent</span>
+        {" called their connections."}
+      </p>
+    );
+  }
+  return (
+    <SimBanner>
+      <p>
+        <strong>Simulated.</strong>
+        {` Nothing ${ended ? "was" : "is"} sent. `}
+        {run.draft_snapshot_id !== null ? `The draft's revision ${run.draft_revision} ran, not a published version.` : "Results don't prove the live call will succeed."}
+      </p>
+    </SimBanner>
+  );
+}
diff --git a/frontend/src/routes/runs/RunPage.tsx b/frontend/src/routes/runs/RunPage.tsx
index 0f8fcf8c..8561a3a7 100644
--- a/frontend/src/routes/runs/RunPage.tsx
+++ b/frontend/src/routes/runs/RunPage.tsx
@@ -1,15 +1,31 @@
 // SPDX-License-Identifier: Apache-2.0
-// A run's page (editor 4e-1; the runs design §5.3, §5.4; the RunFailed and RunOther boards), laid out like the editor
-// (the owner's answer 6): the compact rail, and a bar naming the run, its workflow and its short id, with the way back
-// to Runs. A run past its tenant's retention, or an id that never was, is said to be neither, with Back to Runs; a run
-// read while its tenant is erased says why it can't be (§5.5).
+// A run's page (editor 4e-1; the runs design §5.3, §5.4; the RunFailed, RunRunning and RunOther boards), laid out like
+// the editor (the owner's answer 6): the compact rail, the run's bar, its banner, and the graph it ran on the read-only
+// canvas, each step's result beside its card, walked with the editor's keys (D16). It's read while it runs
+// (useRunReads). A run past its tenant's retention, or an id that never was, is said to be neither, with Back to Runs;
+// a run read while its tenant is erased says why it can't be (§5.5).
 import { useQuery } from "@tanstack/react-query";
 import { Link } from "@tanstack/react-router";
+import { useCallback, useMemo, type KeyboardEvent } from "react";
 import { Button, LINK_BUTTON } from "../../components/Button";
+import { When } from "../../components/When";
 import { ApiError } from "../../lib/client";
-import { runQuery } from "../../lib/runs";
+import { findNode, idKey, portsOf } from "../../lib/graph";
+import { isEnded } from "../../lib/runs";
 import { runId } from "../../lib/runStatus";
+import { draftSnapshotQuery } from "../../lib/simulations";
 import { useDocumentTitle } from "../../lib/title";
+import { versionQuery } from "../../lib/triggers";
+import { timeOf } from "../../lib/when";
+import { nodeTypesQuery, type GraphDoc } from "../../lib/workflows";
+import { Canvas } from "../editor/Canvas";
+import { NAV_KEYS, type NavKey } from "../editor/canvasNav";
+import { endedWhat } from "../editor/simulation/lifecycle";
+import { tagsOf, type SimTag } from "../editor/simulation/results";
+import { useCanvasNav } from "../editor/useCanvasNav";
+import { RunBanner, RunBar } from "./RunBar";
+import { triggerOf, triggerWords } from "./trigger";
+import { useRunReads } from "./useRunReads";
 
 /** Why a run couldn't be read: gone, the tenant's key gone during an erasure, or the read failed. */
 function Unread({ tenantId, id, error, retry }: { tenantId: string; id: string; error: Error; retry: () => void }) {
@@ -35,18 +51,106 @@ function Unread({ tenantId, id, error, retry }: { tenantId: string; id: string;
   );
 }
 
+const NONE: GraphDoc = { graph_format: 1, nodes: [], edges: [] };
+const NO_STEPS: ReadonlySet<string> = new Set();
+const NO_PROBLEMS = new Map();
+const nothing = () => undefined;
+
 export function RunPage({ tenantId, runId: id }: { tenantId: string; runId: string }) {
   useDocumentTitle(`Run ${runId(id)}`);
-  const run = useQuery(runQuery(tenantId, id));
+  const { run, steps } = useRunReads(tenantId, id);
   const r = run.data;
-  // Only a run never read says why it isn't shown: a read that fails later keeps what was read.
+  const types = useQuery(nodeTypesQuery);
+  // The graph it ran: its version's, or the draft a draft simulation froze for it. Neither ever changes.
+  const version = useQuery({ ...versionQuery(tenantId, r?.workflow_id ?? "", r?.version_id ?? ""), enabled: !!r?.version_id });
+  const snapshot = useQuery({ ...draftSnapshotQuery(tenantId, r?.workflow_id ?? "", r?.draft_snapshot_id ?? ""), enabled: !!r?.draft_snapshot_id });
+  const graph = (r?.draft_snapshot_id ? snapshot.data?.graph : version.data?.graph) ?? null;
+  const typeMap = useMemo(() => new Map((types.data ?? []).map((t) => [t.ref, t])), [types.data]);
+  const portsByStep = useCallback((nodeId: string) => {
+    const n = graph && findNode(graph, nodeId);
+    return n ? portsOf(n, typeMap.get(n.type)) : [];
+  }, [graph, typeMap]);  // prettier-ignore
+  const keys = useCanvasNav(graph ?? NONE, portsByStep, false);
+  const ended = r !== undefined && isEnded(r.status);
+  // Each step's tags, 4d-1c's grammar with a run's (§5.3): an attempt is said "of" the step's own limit, else its
+  // type's; an action's time, a failure's code.
+  const results = useMemo(() => {
+    const tags = new Map<string, SimTag[]>();
+    for (const s of steps.data?.steps ?? []) {
+      const type = typeMap.get(s.type);
+      const max = (graph && findNode(graph, s.step_id)?.options?.max_attempts) ?? type?.retry.max_attempts ?? null;
+      tags.set(idKey(s.step_id), tagsOf(s, { maxAttempts: max, ended, run: { action: type?.kind === "action" } }));
+    }
+    return tags;
+  }, [steps.data, typeMap, graph, ended]);
+  // Only a run never read says why it isn't shown: a read that fails later keeps what was read, and says so.
   if (!r) return run.isError ? <Unread tenantId={tenantId} id={id} error={run.error} retry={() => void run.refetch()} /> : <p role="status" className="p-6 text-body text-muted">Reading the run…</p>;
+  const trigger = triggerOf(r);
+  const given = steps.data?.given === "input" ? [{ text: "input", kind: "given" as const }] : undefined;
+  function onCanvasKey(e: KeyboardEvent<HTMLDivElement>) {
+    if (!(e.target as HTMLElement).dataset.item || e.altKey || e.ctrlKey || e.metaKey || !NAV_KEYS.includes(e.key)) return;
+    e.preventDefault();
+    keys.walk(e.key as NavKey);
+  }
+  const endedAt = ended && r.ended_at && r.status !== "refused" && r.status !== "dead" ? r.ended_at : null;
   return (
-    <div className="flex min-h-0 flex-1 flex-col">
-      <div className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-line bg-surface px-5 py-2.5">
-        <Link to="/t/$tenantId/runs" params={{ tenantId }} className="text-small text-muted hover:text-ink">← Runs</Link>
-        <h1 className="min-w-0 truncate text-body-lg font-semibold">{r.workflow_name ?? "—"}</h1>
-        <span className="font-mono text-small">{`run ${runId(r.id)}`}</span>
+    <div className="@container flex min-h-0 flex-1 flex-col">
+      <RunBar tenantId={tenantId} run={r} version={version.data?.number ?? null} />
+      <div className="flex flex-col gap-2 border-b border-line bg-surface px-5 py-2.5">
+        {run.isRefetchError && (
+          <p className="flex flex-wrap items-center gap-2 text-small text-muted">
+            {`Couldn't be refreshed · as of ${timeOf(run.dataUpdatedAt)}`}
+            <Button size="sm" onClick={() => void run.refetch()}>Try again</Button>
+          </p>
+        )}
+        <RunBanner run={r} />
+        {endedAt && steps.data && (
+          <p className="text-small text-muted">
+            {`Ended: ${endedWhat(r.status, steps.data.steps)} · `}
+            <When iso={endedAt} />
+          </p>
+        )}
+      </div>
+      <div className="flex min-h-0 flex-1 @max-3xl:flex-col">
+        <div className="relative flex min-h-0 min-w-0 flex-1">
+          {graph === null ? (
+            version.isError || snapshot.isError ? (
+              <p role="alert" className="p-6 text-body text-danger">The workflow it ran couldn&apos;t be read.</p>
+            ) : (
+              <p role="status" className="p-6 text-body text-muted">Reading the workflow it ran…</p>
+            )
+          ) : (
+            <Canvas
+              doc={graph}
+              types={typeMap}
+              problems={NO_PROBLEMS}
+              separate={NO_PROBLEMS}
+              conditional={NO_STEPS}
+              editable={false}
+              current={null}
+              focusId={keys.shown}
+              focusRequest={keys.focusRequest}
+              onFocusItem={keys.onFocusItem}
+              onItem={nothing}
+              onMove={nothing}
+              onConnect={nothing}
+              onLayout={nothing}
+              onKeyDown={onCanvasKey}
+              placing={false}
+              onPlace={nothing}
+              overview
+              start={{
+                summary: trigger.words ? `${trigger.kind} · ${trigger.words}` : trigger.kind,
+                label: `Start: ${triggerWords(r)}. Open the run's start`,
+                open: false,
+                onOpen: nothing,
+                tags: given,
+              }}
+              results={results}
+              resultsLabel="result"
+            />
+          )}
+        </div>
       </div>
     </div>
   );
diff --git a/frontend/src/routes/runs/trigger.tsx b/frontend/src/routes/runs/trigger.tsx
index 25c9616c..909474d0 100644
--- a/frontend/src/routes/runs/trigger.tsx
+++ b/frontend/src/routes/runs/trigger.tsx
@@ -15,15 +15,25 @@ const KIND: Record<NonNullable<RunItem["trigger"]>["source"], string> = {
   dev: "Development",
 };
 
-/** Its kind ("By hand"), and what says more about it, when known. */
-export function triggerOf(run: RunItem): { kind: string; detail: ReactNode } {
+/** Its kind ("By hand"), and what says more about it, when known: drawn (`detail`, a re-run's id in mono) and in
+ * plain words (`words`, for a name). */
+export function triggerOf(run: RunItem): { kind: string; detail: ReactNode; words: string | null } {
   const t = run.trigger;
-  if (t === null) return { kind: "—", detail: null };
-  const detail =
+  if (t === null) return { kind: "—", detail: null, words: null };
+  if (t.source === "rerun" && t.rerun_of) {
+    return { kind: KIND.rerun, detail: <>of <span className="font-mono">{runId(t.rerun_of)}</span></>, words: `of ${runId(t.rerun_of)}` };
+  }
+  const words =
     t.source === "manual" ? run.started_by
-    : t.source === "rerun" ? t.rerun_of && <>of <span className="font-mono">{runId(t.rerun_of)}</span></>
     : t.source === "schedule" ? t.schedule && timingTitle(t.schedule)
     : t.source === "webhook" ? t.endpoint
     : null;  // prettier-ignore
-  return { kind: KIND[t.source], detail: detail ?? null };
+  return { kind: KIND[t.source], detail: words ?? null, words: words ?? null };
+}
+
+/** The same in a sentence: "webhook, Mist events", "schedule, weekdays at 06:00". */
+export function triggerWords(run: RunItem): string {
+  const { kind, words } = triggerOf(run);
+  const said = words && run.trigger?.source === "schedule" ? words.charAt(0).toLowerCase() + words.slice(1) : words;
+  return `${kind.toLowerCase()}${said ? `, ${said}` : ""}`;
 }
diff --git a/frontend/src/routes/runs/useRunReads.ts b/frontend/src/routes/runs/useRunReads.ts
new file mode 100644
index 00000000..b56b1a0b
--- /dev/null
+++ b/frontend/src/routes/runs/useRunReads.ts
@@ -0,0 +1,41 @@
+// SPDX-License-Identifier: Apache-2.0
+// Reading a run while it runs (editor 4e-1; the runs design §5.3): its state every second, backing off to every 5 s
+// (as a simulation's, `pollEvery`), paused while the tab is hidden; its steps' summary with it, at most every 5 s. Once
+// it ends, its steps are read then, and both once more 5 s later: step rows and sub-runs can still settle. After that,
+// only on focus or a reload. Its end is said once, through the shell's live region (§5.6).
+import { useQuery } from "@tanstack/react-query";
+import { useEffect, useRef } from "react";
+import { announce } from "../../lib/announce";
+import { isEnded, runQuery, runStepsQuery } from "../../lib/runs";
+import { RUN_STATUS } from "../../lib/runStatus";
+import { pollEvery } from "../../lib/simulations";
+
+const SUMMARY_EVERY = 5000;
+const SETTLE = 5000; // the once-more read after the end
+
+export function useRunReads(tenantId: string, runId: string) {
+  const run = useQuery({
+    ...runQuery(tenantId, runId),
+    refetchInterval: (q) => (q.state.data === undefined || isEnded(q.state.data.status) ? false : pollEvery(q.state.dataUpdateCount + q.state.errorUpdateCount)),
+  });
+  const ended = run.data !== undefined && isEnded(run.data.status);
+  const steps = useQuery({ ...runStepsQuery(tenantId, runId), enabled: run.data !== undefined, refetchInterval: ended ? false : SUMMARY_EVERY });
+  const status = run.data?.status;
+  const was = useRef(status);
+  const { refetch: readRun } = run;
+  const { refetch: readSteps } = steps;
+  useEffect(() => {
+    const before = was.current;
+    was.current = status;
+    // Only an end seen here: a run already ended when the page opened is read as it is.
+    if (status === undefined || before === undefined || isEnded(before) || !isEnded(status)) return;
+    announce(`Run ended: ${RUN_STATUS[status].word.toLowerCase()}`);
+    void readSteps();
+    const later = setTimeout(() => {
+      void readRun();
+      void readSteps();
+    }, SETTLE);
+    return () => clearTimeout(later);
+  }, [status, readRun, readSteps]);
+  return { run, steps };
+}
```

- [ ] **Step 4: Run them again**

Run: the same command.

Expected: PASS, 184 passed.

- [ ] **Step 5: Static checks, and the chunks**

Run: the two of "How to run things". Expected: no output. Then `npx --offline pnpm@12.6.0 build` and list
`dist/assets`: an `Editor-*.js` of about 247 kB, a shared chunk of about 258 kB with the editor's stylesheet, and
`RunsPage-*.js` and `RunPage-*.js` of their own (ruling 21). `dist` is ignored by git.

- [ ] **Step 6: Commit**

```bash
git add frontend/src frontend/e2e/workflows.spec.ts
git commit -m "feat(editor): a run's page: its bar and banner, the graph it ran with each step's result, read while it runs (4e-1b)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: A step's result in the drawer

**Spec:** §5.3 (the drawer: Result and Setup, the attempts, the marks, a sub-run), §3's answer 6 (a failed run opens on
its failed step), §5.6 (focus); the RunFailed and RunLoop boards.

**Files:**
- Create: `frontend/src/routes/runs/RunResult.tsx`
- Modify: `frontend/src/routes/runs/RunPage.tsx`, `frontend/src/routes/runs/RunPage.test.tsx`
- Modify: `frontend/src/routes/editor/drawer/StepDrawer.tsx`, `frontend/src/routes/editor/drawer/context.ts`,
  `frontend/src/routes/editor/drawer/PillDetails.tsx`, `frontend/src/routes/editor/Editor.tsx`
- Modify: `frontend/src/lib/runStatus.ts`

**Interfaces:**
- Consumes: `runAttemptsQuery`, `runQuery` (Task 3); `took`, `STEP_STATUS`'s tones (`ToneChip`, Task 2); `PreviewValue`
  (`PillDetails.tsx`); `ORIGIN` (Task 8).
- Produces:
  - `STEP_STATUS` (`lib/runStatus.ts`): a step's status, word and tone.
  - `StepDrawer`'s `result?: ReactNode`: Result first, then Setup with every setting.
  - `CANT`, `READ_ONLY_ACTIONS` (`drawer/context.ts`, moved from `Editor.tsx`); `Chip` exported from `PillDetails.tsx`.
  - `RunResult.tsx`: `Section({ title, children })`, `InstanceResult({ tenantId, runId, step, max, ended })`,
    `StepResult({ tenantId, runId, summary, max, ended, several })`.

A step's result opens in the editor's drawer, read only, its Result tab first: its status, "attempt N of M" and its
times; its error's code and message; its attempts, one row each; the last attempt's input and output, redacted and cut
as the server stored them; the run it started. Setup lists its settings, or says the server doesn't know its type. A
failed run opens on its failed step; the drawer's heading takes focus, and Close gives it back to the card. An open
drawer's attempts are read with the summary while the run runs.

- [ ] **Step 1: Write the failing tests**

Apply:

```diff
diff --git a/frontend/src/routes/runs/RunPage.test.tsx b/frontend/src/routes/runs/RunPage.test.tsx
index 0df1036e..7bc49ddf 100644
--- a/frontend/src/routes/runs/RunPage.test.tsx
+++ b/frontend/src/routes/runs/RunPage.test.tsx
@@ -6,7 +6,7 @@ import userEvent from "@testing-library/user-event";
 import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
 import { onAnnounce } from "../../lib/announce";
 import type { Run, RunSteps } from "../../lib/runs";
-import { FAILED_GRAPH, FAILED_RUN, FAILED_STEPS, RUN_TYPES, local } from "../../test/runs";
+import { FAILED_GRAPH, FAILED_RUN, FAILED_STEPS, RUN_TYPES, attempt, local } from "../../test/runs";
 import type { CanvasProps } from "../editor/Canvas";
 import { RunPage } from "./RunPage";
 
@@ -265,4 +265,99 @@ describe("reading a run while it runs (§5.3)", () => {
     expect(said).toEqual(["Run ended: failed"]);
     stop();
   });
+
+  it("reads an open drawer's attempts with the summary while the run runs", async () => {
+    const ATTEMPTS = `${RUN_PATH}/steps/id-get_device/attempts`;
+    answers.set(RUN_PATH, json(running));
+    answers.set(STEPS_PATH, json(runningSteps));
+    answers.set(ATTEMPTS, json({ items: [runningSteps.steps[0]!.final] }));
+    show();
+    await vi.waitFor(() => expect(count(STEPS_PATH)).toBe(1));
+    await userEvent.click(within(canvas()).getByRole("button", { name: "get_device" }));
+    await vi.waitFor(() => expect(count(ATTEMPTS)).toBe(1));
+    await act(() => vi.advanceTimersByTimeAsync(5000));
+    expect(count(ATTEMPTS)).toBe(2);
+  });
+});
+
+describe("a step's result in the drawer (§5.3; the RunFailed and RunLoop boards)", () => {
+  const RUN_PATH = `/api/v1/t/t1/runs/${RUN.id}`;
+  const attemptsOf = (key: string) => `${RUN_PATH}/steps/id-${key}/attempts`;
+  const drawer = (key: string) => screen.getByRole("complementary", { name: key });
+  const failedAttempt = (n: number, at: number) =>
+    attempt("notify_noc", { attempt: n, status: "failed", started_at: local(9, 41, at), ended_at: local(9, 41, at + 1, 200 - n * 100),
+      error: { code: "channel_not_found", message: "The channel wasn't found." } });  // prettier-ignore
+
+  beforeEach(() => {
+    answers.set(RUN_PATH, json(RUN));
+    answers.set(attemptsOf("notify_noc"), json({ items: [failedAttempt(1, 20), failedAttempt(2, 31), { ...FAILED_STEPS.steps[3]!.final, started_at: local(9, 41, 49) }] }));
+    answers.set(attemptsOf("get_device"), json({ items: [attempt("get_device", { output: { name: "Paris-Opera-12", status: "disconnected" } })] }));
+  });
+
+  it("opens a failed run on its failed step: its status and times, its error, its attempts, its input with its marks", async () => {
+    show();
+    const side = await screen.findByRole("complementary", { name: "notify_noc" });
+    await vi.waitFor(() => expect(document.activeElement).toBe(within(side).getByRole("heading", { name: "notify_noc" })));
+    expect(canvas().dataset.current).toBe("id-notify_noc");
+    expect(within(side).getByRole("tab", { name: "Result", selected: true })).toBeTruthy();
+    expect(within(side).getByText("Failed").className).toContain("border-danger");
+    expect(await within(side).findByText("attempt 3 of 3 · 09:41:20 to 09:41:50 · 30 s")).toBeTruthy();
+    expect(within(side).getAllByText("channel_not_found")[0]!.closest("p")!.textContent).toBe("channel_not_found · The channel wasn't found.");
+    const attempts = within(within(side).getByRole("region", { name: "Attempts" })).getAllByRole("listitem");
+    expect(attempts.map((a) => a.textContent)).toEqual([
+      "1failedchannel_not_found09:41:201.1 s", "2failedchannel_not_found09:41:311.0 s", "3failedchannel_not_found09:41:491.0 s",
+    ]);  // prettier-ignore
+    const input = within(side).getByRole("region", { name: "Input" });
+    expect(within(input).getByText("As the last attempt received it. Sensitive values are redacted and long ones cut.")).toBeTruthy();
+    expect(within(input).getAllByRole("term").map((k) => k.textContent)).toEqual(["channel", "text", "token", "blocks"]);
+    expect(within(input).getAllByRole("definition").map((v) => v.textContent)).toEqual([
+      '"#noc-alert"', '"AP Paris-Opera-12 offline since 09:38"', "redacted", "truncated",
+    ]);  // prettier-ignore
+    expect(within(within(side).getByRole("region", { name: "Output" })).getByText("None: the step failed.")).toBeTruthy();
+  });
+
+  it("opens a step from the canvas, its setup read only on Setup, and gives focus back to its card on Close", async () => {
+    show();
+    await screen.findByRole("complementary", { name: "notify_noc" });
+    await userEvent.click(within(canvas()).getByRole("button", { name: "get_device" }));
+    const side = drawer("get_device");
+    expect(await within(side).findByText("attempt 1 of 3 · 09:41:13 · 0.4 s")).toBeTruthy();
+    expect(within(within(side).getByRole("region", { name: "Output" })).getAllByRole("definition").map((v) => v.textContent)).toEqual(['"Paris-Opera-12"', '"disconnected"']);
+    await userEvent.click(within(side).getByRole("tab", { name: "Setup" }));
+    expect(within(side).getByText("This step has nothing to set up.")).toBeTruthy();
+    await userEvent.click(within(side).getByRole("button", { name: "Close" }));
+    expect(screen.queryByRole("complementary")).toBeNull();
+    await vi.waitFor(() => expect(document.activeElement?.textContent).toBe("get_device"));
+  });
+
+  it("links the run a step started, with its workflow and status (the RunLoop board)", async () => {
+    const child = { ...RUN, id: "7d2e0c11-0000-4000-8000-000000000000", workflow_name: "Escalate an outage", status: "succeeded", error: null };
+    const steps = structuredClone(FAILED_STEPS);
+    steps.steps[2]!.final!.child_run_id = child.id;
+    answers.set(`${RUN_PATH}/steps`, json(steps));
+    answers.set(`/api/v1/t/t1/runs/${child.id}`, json(child));
+    answers.set(attemptsOf("open_case"), json({ items: [steps.steps[2]!.final] }));
+    const router = show();
+    await screen.findByRole("complementary", { name: "notify_noc" });
+    await userEvent.click(within(canvas()).getByRole("button", { name: "open_case" }));
+    const link = await within(drawer("open_case")).findByRole("link", { name: "7d2e0c11" });
+    expect(link.closest("p")!.textContent).toBe("Its run: 7d2e0c11 · Escalate an outage · Succeeded");
+    await userEvent.click(link);
+    expect(router.state.location.pathname).toBe(`/t/t1/runs/${child.id}`);
+  });
+
+  it("shows the result of a step whose type the server no longer knows, and says why its settings can't be shown", async () => {
+    const gone = "acme.gone@1";
+    const graph = { ...FAILED_GRAPH, nodes: FAILED_GRAPH.nodes!.map((n) => (n.key === "get_device" ? { ...n, type: gone } : n)) };
+    const steps = { ...FAILED_STEPS, steps: FAILED_STEPS.steps.map((s) => (s.key === "get_device" ? { ...s, type: gone } : s)) };
+    answers.set("/api/v1/t/t1/workflows/w1/versions/v2", json({ ...VERSION, graph }));
+    answers.set(`${RUN_PATH}/steps`, json(steps));
+    show();
+    await screen.findByRole("complementary", { name: "notify_noc" });
+    await userEvent.click(within(canvas()).getByRole("button", { name: "get_device" }));
+    const side = drawer("get_device");
+    expect(await within(side).findByText("attempt 1 · 09:41:13 · 0.4 s")).toBeTruthy();
+    await userEvent.click(within(side).getByRole("tab", { name: "Setup" }));
+    expect(within(side).getByText("This server doesn't know this step's type, so its settings can't be shown. They're kept as they are.")).toBeTruthy();
+  });
 });
```

- [ ] **Step 2: Run them**

Run: `npx --offline pnpm@12.6.0 exec vitest run src/routes/runs/RunPage.test.tsx src/routes/editor/Editor.test.tsx`

Expected: FAIL, 5 failed and 177 passed: no drawer opens (`Unable to find role="complementary" and name "notify_noc"`),
and no attempts are read (`expected +0 to be 1`). The editor's tests pass.

- [ ] **Step 3: Implement**

Apply:

```diff
diff --git a/frontend/src/lib/runStatus.ts b/frontend/src/lib/runStatus.ts
index 63419e76..a11613a3 100644
--- a/frontend/src/lib/runStatus.ts
+++ b/frontend/src/lib/runStatus.ts
@@ -21,6 +21,16 @@ export const RUN_STATUS: Record<RunStatus, { word: string; tone: Tone }> = {
   refused: { word: "Refused", tone: "danger" },
 };
 
+/** A step's status, in the same words and looks: a step that was skipped or never started, neutral. */
+export const STEP_STATUS: Record<"running" | "succeeded" | "failed" | "cancelled" | "skipped" | "not_started", { word: string; tone: Tone }> = {
+  running: { word: "Running", tone: "running" },
+  succeeded: { word: "Succeeded", tone: "ok" },
+  failed: { word: "Failed", tone: "danger" },
+  cancelled: { word: "Cancelled", tone: "neutral" },
+  skipped: { word: "Skipped", tone: "neutral" },
+  not_started: { word: "Not started", tone: "neutral" },
+};
+
 /** How long a run ran, as a person reads it: "14 s", "3 min 20 s", "1 h 2 min"; null when either end is unknown. */
 export function duration(from: string | null, to: string | null): string | null {
   if (from === null || to === null) return null;
diff --git a/frontend/src/routes/editor/Editor.tsx b/frontend/src/routes/editor/Editor.tsx
index f825aeeb..e10bbfce 100644
--- a/frontend/src/routes/editor/Editor.tsx
+++ b/frontend/src/routes/editor/Editor.tsx
@@ -37,7 +37,7 @@ import { Canvas } from "./Canvas";
 import { NAV_KEYS, navModel, pathTo, type NavKey } from "./canvasNav";
 import { checkLabel, checkState, lastOf, type Check } from "./check";
 import { ConnectDialog } from "./ConnectDialog";
-import type { DrawerActions } from "./drawer/context";
+import { CANT, READ_ONLY_ACTIONS, type DrawerActions } from "./drawer/context";
 import { StepDrawer } from "./drawer/StepDrawer";
 import { addsOf, item, type ItemAction } from "./items";
 import { DeclassifyPanel } from "./DeclassifyPanel";
@@ -96,22 +96,6 @@ function portsQuestion(dropped: GraphEdge[], keyOf: (id: string) => string): str
     dropped.length === 1 ? "its edge" : "their edges"} to ${targets.join(", ")} ${dropped.length === 1 ? "is" : "are"} deleted.`;
 }
 
-const CANT = "Not written: the draft can't be changed now."; // a conflict, an exit agreed to, a version view
-
-/** A version's drawer: read only, and blind to the draft's edits not applied, which are never a version's (the review
- * of milestone 2). */
-const VERSION_ACTIONS: DrawerActions = {
-  set: () => CANT,
-  options: () => CANT,
-  held: () => undefined,
-  hold: () => undefined,
-  release: () => undefined,
-  discard: () => undefined,
-  apply: () => CANT,
-  stale: () => false,
-  rebase: () => undefined,
-  restructure: () => CANT,
-};
 
 export function EditorPage({ tenantId, workflowId, openTriggers = false }: { tenantId: string; workflowId: string; openTriggers?: boolean }) {
   const qc = useQueryClient();
@@ -1384,7 +1368,7 @@ function Editor({
             expressions={(viewing ? viewing.expressions : (trusted?.expressions ?? [])).filter((x) => x.node !== null && sameId(x.node, open.id))}
             editable={editable}
             adds={editable ? addsOf(doc, open, portMap.get(idKey(open.id)) ?? []) : []}
-            actions={viewing ? VERSION_ACTIONS : actionsFor(open.id)}
+            actions={viewing ? READ_ONLY_ACTIONS : actionsFor(open.id)}
             note={noteFor(open.id)}
             focusField={side?.kind === "step" ? (side.field ?? null) : null}
             testAt={side?.kind === "step" ? (side.test?.n ?? null) : null}
diff --git a/frontend/src/routes/editor/drawer/PillDetails.tsx b/frontend/src/routes/editor/drawer/PillDetails.tsx
index 6e542756..395d7ff1 100644
--- a/frontend/src/routes/editor/drawer/PillDetails.tsx
+++ b/frontend/src/routes/editor/drawer/PillDetails.tsx
@@ -13,7 +13,7 @@ import { useDrawer } from "./context";
 import { usePillEntry } from "./Pill";
 
 /** A preview's marker, as a chip: never the value it stands for (D20). */
-const Chip = ({ children }: { children: ReactNode }) => (
+export const Chip = ({ children }: { children: ReactNode }) => (
   <span className="rounded-sm border border-line-strong px-1.5 font-mono text-meta text-muted">{children}</span>
 );
 
diff --git a/frontend/src/routes/editor/drawer/StepDrawer.tsx b/frontend/src/routes/editor/drawer/StepDrawer.tsx
index 1799b383..58053c10 100644
--- a/frontend/src/routes/editor/drawer/StepDrawer.tsx
+++ b/frontend/src/routes/editor/drawer/StepDrawer.tsx
@@ -33,7 +33,13 @@ const NUDGES: { key: Nudge; glyph: string; word: string }[] = [
   { key: "ArrowRight", glyph: "→", word: "right" },
 ];
 
-type Tab = "setup" | "options" | "test";
+const UNKNOWN = (
+  <p className="text-small">
+    This server doesn&apos;t know this step&apos;s type, so its settings can&apos;t be shown. They&apos;re kept as they are.
+  </p>
+);
+
+type Tab = "result" | "setup" | "options" | "test";
 
 /** The drawer's disabled controls, its own and 4a's alike, look disabled: the disabled fill and line, their values in
  * muted ink, which stays legible where the disabled ink wouldn't (the owner's ruling O2). 4a's forms elsewhere keep
@@ -80,13 +86,16 @@ function locate(root: HTMLElement, { pointer, kind }: FocusRequest): HTMLElement
 
 export function StepDrawer({
   node, type, tenantId, workflowId, revision, steps, openDeclassify, ports, problems, expressions, editable, adds, actions, note, focusField,
-  test, testAt, onAdd, onDelete, onConnectPort, onPlace, onNudge, onClose,
+  test, testAt, result, onAdd, onDelete, onConnectPort, onPlace, onNudge, onClose,
 }: {
   node: GraphNode; type: NodeType | undefined; tenantId: string; workflowId: string; revision: number | null;
   steps: { id: string; key: string; title: string | null }[]; openDeclassify?: () => void; ports: string[];
   problems: Diagnostic[] | null; expressions: Expression[]; editable: boolean; adds: { label: string; action: ItemAction }[];
   actions: DrawerActions; note: string | null; focusField: { pointer: string; kind?: UnappliedKind; n: number } | null;
   test?: ReactNode; // the Test tab, for editors (4d-1c, §7.6), even on a step with nothing to set up
+  // On a run's page (4e-1, the runs design §5.3): its result, the first tab and the one shown; Setup then holds every
+  // setting, read only
+  result?: ReactNode;
   testAt?: number | null; // asked to show the Test tab (the Simulation panel's "Open"), counted
   onAdd: (action: ItemAction) => void; onDelete: () => void; onConnectPort: (port: string) => void;
   onPlace: () => void; onNudge: (key: Nudge) => void; onClose: () => void;
@@ -100,7 +109,7 @@ export function StepDrawer({
   }, [node.id]);
   const fields = useMemo(() => (type ? fieldsOf(type) : []), [type]);
   const { setup, options } = tabsOf(fields);
-  const [tab, setTab] = useState<Tab>(test && testAt ? "test" : setup.length > 0 ? "setup" : "options");
+  const [tab, setTab] = useState<Tab>(result ? "result" : test && testAt ? "test" : setup.length > 0 ? "setup" : "options");
   useEffect(() => {
     if (test && testAt) setTab("test");
   }, [testAt]);
@@ -231,10 +240,28 @@ export function StepDrawer({
             </section>
           )
         )}
-        {!type ? (
-          <p className="text-small">
-            This server doesn&apos;t know this step&apos;s type, so its settings can&apos;t be shown. They&apos;re kept as they are.
-          </p>
+        {result ? (
+          <Tabs
+            label="Result and setup"
+            value={tab}
+            onChange={setTab}
+            tabs={[
+              { value: "result", label: "Result", content: result },
+              {
+                value: "setup",
+                label: "Setup",
+                content: !type ? (
+                  UNKNOWN
+                ) : fields.length > 0 ? (
+                  [...setup, ...options].map((f) => <FieldView key={f.pointer} spec={f} />)
+                ) : (
+                  <p className="text-small text-muted">This step has nothing to set up.</p>
+                ),
+              },
+            ]}
+          />
+        ) : !type ? (
+          UNKNOWN
         ) : fields.length === 0 && !test ? (
           <p className="text-small text-muted">This step has nothing to set up.</p>
         ) : (
diff --git a/frontend/src/routes/editor/drawer/context.ts b/frontend/src/routes/editor/drawer/context.ts
index d85d5968..f9a58e5c 100644
--- a/frontend/src/routes/editor/drawer/context.ts
+++ b/frontend/src/routes/editor/drawer/context.ts
@@ -51,6 +51,24 @@ export interface Drawer extends DrawerActions {
   explains?: (pointer: string) => () => void;
 }
 
+/** Why a read-only drawer writes nothing: a conflict, an exit agreed to, a version's or a run's view. */
+export const CANT = "Not written: the draft can't be changed now.";
+
+/** A drawer that changes nothing: a version's, or a run's (4e-1), blind to the draft's edits not applied, which are
+ * never theirs (the review of milestone 2). */
+export const READ_ONLY_ACTIONS: DrawerActions = {
+  set: () => CANT,
+  options: () => CANT,
+  held: () => undefined,
+  hold: () => undefined,
+  release: () => undefined,
+  discard: () => undefined,
+  apply: () => CANT,
+  stale: () => false,
+  rebase: () => undefined,
+  restructure: () => CANT,
+};
+
 export const DrawerContext = createContext<Drawer | null>(null);
 
 export function useDrawer(): Drawer {
diff --git a/frontend/src/routes/runs/RunPage.tsx b/frontend/src/routes/runs/RunPage.tsx
index 8561a3a7..6435d6ee 100644
--- a/frontend/src/routes/runs/RunPage.tsx
+++ b/frontend/src/routes/runs/RunPage.tsx
@@ -2,16 +2,18 @@
 // A run's page (editor 4e-1; the runs design §5.3, §5.4; the RunFailed, RunRunning and RunOther boards), laid out like
 // the editor (the owner's answer 6): the compact rail, the run's bar, its banner, and the graph it ran on the read-only
 // canvas, each step's result beside its card, walked with the editor's keys (D16). It's read while it runs
-// (useRunReads). A run past its tenant's retention, or an id that never was, is said to be neither, with Back to Runs;
-// a run read while its tenant is erased says why it can't be (§5.5).
+// (useRunReads). A step's result opens in the editor's drawer, read only, its Result tab first; a failed run opens on
+// its failed step (the owner's answer 6), and Close gives focus back to its card. A run past its tenant's retention, or
+// an id that never was, is said to be neither, with Back to Runs; a run read while its tenant is erased says why it
+// can't be (§5.5).
 import { useQuery } from "@tanstack/react-query";
 import { Link } from "@tanstack/react-router";
-import { useCallback, useMemo, type KeyboardEvent } from "react";
+import { useCallback, useMemo, useState, type KeyboardEvent } from "react";
 import { Button, LINK_BUTTON } from "../../components/Button";
 import { When } from "../../components/When";
 import { ApiError } from "../../lib/client";
-import { findNode, idKey, portsOf } from "../../lib/graph";
-import { isEnded } from "../../lib/runs";
+import { findNode, idKey, nodesOf, portsOf } from "../../lib/graph";
+import { isEnded, type RunStepSummary } from "../../lib/runs";
 import { runId } from "../../lib/runStatus";
 import { draftSnapshotQuery } from "../../lib/simulations";
 import { useDocumentTitle } from "../../lib/title";
@@ -20,10 +22,14 @@ import { timeOf } from "../../lib/when";
 import { nodeTypesQuery, type GraphDoc } from "../../lib/workflows";
 import { Canvas } from "../editor/Canvas";
 import { NAV_KEYS, type NavKey } from "../editor/canvasNav";
+import { READ_ONLY_ACTIONS } from "../editor/drawer/context";
+import { StepDrawer } from "../editor/drawer/StepDrawer";
+import { item, type ItemAction } from "../editor/items";
 import { endedWhat } from "../editor/simulation/lifecycle";
 import { tagsOf, type SimTag } from "../editor/simulation/results";
 import { useCanvasNav } from "../editor/useCanvasNav";
 import { RunBanner, RunBar } from "./RunBar";
+import { StepResult } from "./RunResult";
 import { triggerOf, triggerWords } from "./trigger";
 import { useRunReads } from "./useRunReads";
 
@@ -72,17 +78,22 @@ export function RunPage({ tenantId, runId: id }: { tenantId: string; runId: stri
   }, [graph, typeMap]);  // prettier-ignore
   const keys = useCanvasNav(graph ?? NONE, portsByStep, false);
   const ended = r !== undefined && isEnded(r.status);
-  // Each step's tags, 4d-1c's grammar with a run's (§5.3): an attempt is said "of" the step's own limit, else its
-  // type's; an action's time, a failure's code.
-  const results = useMemo(() => {
-    const tags = new Map<string, SimTag[]>();
-    for (const s of steps.data?.steps ?? []) {
-      const type = typeMap.get(s.type);
-      const max = (graph && findNode(graph, s.step_id)?.options?.max_attempts) ?? type?.retry.max_attempts ?? null;
-      tags.set(idKey(s.step_id), tagsOf(s, { maxAttempts: max, ended, run: { action: type?.kind === "action" } }));
-    }
-    return tags;
-  }, [steps.data, typeMap, graph, ended]);
+  // An attempt is said "of" the step's own limit, else its type's.
+  const attemptsOf = useCallback(
+    (s: RunStepSummary) => (graph && findNode(graph, s.step_id)?.options?.max_attempts) ?? typeMap.get(s.type)?.retry.max_attempts ?? null,
+    [graph, typeMap],
+  );
+  const tagsFor = useCallback(
+    (s: RunStepSummary) => tagsOf(s, { maxAttempts: attemptsOf(s), ended, run: { action: typeMap.get(s.type)?.kind === "action" } }),
+    [attemptsOf, ended, typeMap],
+  );
+  // Each step's tags, 4d-1c's grammar with a run's (§5.3): an action's time, a failure's code.
+  const results = useMemo(() => new Map((steps.data?.steps ?? []).map((s): [string, SimTag[]] => [idKey(s.step_id), tagsFor(s)])), [steps.data, tagsFor]);
+  // The step whose result is open. Undecided until its steps and graph are read: a failed run opens on its failed step.
+  const [open, setOpen] = useState<string | null | undefined>(undefined);
+  if (open === undefined && r && steps.data && graph) {
+    setOpen(r.status === "failed" ? (steps.data.steps.find((s) => (s.statuses.failed ?? 0) > 0)?.step_id ?? null) : null);
+  }
   // Only a run never read says why it isn't shown: a read that fails later keeps what was read, and says so.
   if (!r) return run.isError ? <Unread tenantId={tenantId} id={id} error={run.error} retry={() => void run.refetch()} /> : <p role="status" className="p-6 text-body text-muted">Reading the run…</p>;
   const trigger = triggerOf(r);
@@ -93,6 +104,11 @@ export function RunPage({ tenantId, runId: id }: { tenantId: string; runId: stri
     keys.walk(e.key as NavKey);
   }
   const endedAt = ended && r.ended_at && r.status !== "refused" && r.status !== "dead" ? r.ended_at : null;
+  const node = open && graph ? findNode(graph, open) : undefined;
+  const summary = node && steps.data?.steps.find((s) => idKey(s.step_id) === idKey(node.id));
+  const onItem = (action: ItemAction) => {
+    if (action.kind === "open") setOpen(action.node);
+  };
   return (
     <div className="@container flex min-h-0 flex-1 flex-col">
       <RunBar tenantId={tenantId} run={r} version={version.data?.number ?? null} />
@@ -127,18 +143,18 @@ export function RunPage({ tenantId, runId: id }: { tenantId: string; runId: stri
               separate={NO_PROBLEMS}
               conditional={NO_STEPS}
               editable={false}
-              current={null}
+              current={node ? node.id : null}
               focusId={keys.shown}
               focusRequest={keys.focusRequest}
               onFocusItem={keys.onFocusItem}
-              onItem={nothing}
+              onItem={onItem}
               onMove={nothing}
               onConnect={nothing}
               onLayout={nothing}
               onKeyDown={onCanvasKey}
               placing={false}
               onPlace={nothing}
-              overview
+              overview={!node}
               start={{
                 summary: trigger.words ? `${trigger.kind} · ${trigger.words}` : trigger.kind,
                 label: `Start: ${triggerWords(r)}. Open the run's start`,
@@ -151,6 +167,44 @@ export function RunPage({ tenantId, runId: id }: { tenantId: string; runId: stri
             />
           )}
         </div>
+        {node && graph && (
+          <StepDrawer
+            key={idKey(node.id)}
+            node={node}
+            type={typeMap.get(node.type)}
+            tenantId={tenantId}
+            workflowId={r.workflow_id}
+            revision={null}
+            steps={nodesOf(graph).map((n) => ({ id: n.id, key: n.key, title: typeMap.get(n.type)?.title ?? null }))}
+            ports={portsOf(node, typeMap.get(node.type))}
+            problems={[]}
+            expressions={[]}
+            editable={false}
+            adds={[]}
+            actions={READ_ONLY_ACTIONS}
+            note={null}
+            focusField={null}
+            result={
+              <StepResult
+                tenantId={tenantId}
+                runId={id}
+                summary={summary}
+                max={summary ? attemptsOf(summary) : null}
+                ended={ended}
+                several={summary && <p className="text-small">{tagsFor(summary).map((t) => t.text).join(" · ")}</p>}
+              />
+            }
+            onAdd={nothing}
+            onDelete={nothing}
+            onConnectPort={nothing}
+            onPlace={nothing}
+            onNudge={nothing}
+            onClose={() => {
+              setOpen(null);
+              keys.focus(item.node(node.id));
+            }}
+          />
+        )}
       </div>
     </div>
   );
diff --git a/frontend/src/routes/runs/RunResult.tsx b/frontend/src/routes/runs/RunResult.tsx
new file mode 100644
index 00000000..c21ecb32
--- /dev/null
+++ b/frontend/src/routes/runs/RunResult.tsx
@@ -0,0 +1,129 @@
+// SPDX-License-Identifier: Apache-2.0
+// A step's result in a run, its drawer's Result tab (editor 4e-1; the runs design §5.3; the RunFailed and RunLoop
+// boards). An instance: its status, "attempt N of M" and its times; its error's code and message; its attempts, one row
+// each (at most 20, §4.4); the last attempt's input and its output, sensitive values redacted and long ones cut as the
+// server stored them, said in words (D20: never dots); and the run it started. Its attempts are read again while the
+// run runs. A step with no instance says why, in the canvas's words.
+import { useQuery } from "@tanstack/react-query";
+import { Link } from "@tanstack/react-router";
+import { Fragment, useId, type ReactNode } from "react";
+import { ToneChip } from "../../components/RunChips";
+import { runAttemptsQuery, runQuery, type RunStep, type RunStepSummary } from "../../lib/runs";
+import { RUN_STATUS, STEP_STATUS, runId, took } from "../../lib/runStatus";
+import { timeOf } from "../../lib/when";
+import { Chip, PreviewValue } from "../editor/drawer/PillDetails";
+import { ORIGIN } from "../editor/simulation/results";
+
+const READ_EVERY = 5000; // an open drawer's reads, while the run runs: with the summary
+const at = (iso: string) => timeOf(Date.parse(iso));
+const MARKS: Record<string, string> = { "[redacted]": "redacted", "[truncated]": "truncated" };
+
+export function Section({ title, children }: { title: string; children: ReactNode }) {
+  const id = useId();
+  return (
+    <section aria-labelledby={id} className="flex flex-col gap-1.5">
+      <h3 id={id} className="text-small font-semibold">{title}</h3>
+      {children}
+    </section>
+  );
+}
+
+/** A preview as the server stored it: an object as its keys and values, a value wholly redacted or cut as its mark. */
+function Values({ value, none }: { value: unknown; none: string }) {
+  const one = (v: unknown) => (typeof v === "string" && MARKS[v] ? <Chip>{MARKS[v]}</Chip> : <PreviewValue value={v} />);
+  if (value === null || value === undefined) return <p className="text-small text-muted">{none}</p>;
+  if (typeof value !== "object" || Array.isArray(value)) return <p className="text-small break-words">{one(value)}</p>;
+  const entries = Object.entries(value as Record<string, unknown>);
+  if (entries.length === 0) return <p className="text-small text-muted">{none}</p>;
+  return (
+    <dl className="grid grid-cols-[minmax(0,8rem)_minmax(0,1fr)] gap-x-3 gap-y-1 text-small">
+      {entries.map(([k, v]) => (
+        <Fragment key={k}>
+          <dt className="font-mono break-all">{k}</dt>
+          <dd className="min-w-0 break-words">{one(v)}</dd>
+        </Fragment>
+      ))}
+    </dl>
+  );
+}
+
+/** The run a step started: its name, a link to its page, its workflow and its status. */
+function SubRun({ tenantId, id }: { tenantId: string; id: string }) {
+  const child = useQuery(runQuery(tenantId, id));
+  return (
+    <p className="text-small">
+      {"Its run: "}
+      <Link to="/t/$tenantId/runs/$runId" params={{ tenantId, runId: id }} className="font-mono text-accent-ink underline underline-offset-2">
+        {runId(id)}
+      </Link>
+      {child.data && ` · ${child.data.workflow_name ?? "—"} · ${RUN_STATUS[child.data.status].word}`}
+    </p>
+  );
+}
+
+/** One instance of a step, from its final attempt: as its attempts' read gives it once read, fresher while the run
+ * runs; `max`: its attempts, its own or its type's. */
+export function InstanceResult({ tenantId, runId: id, step: final, max, ended }: {
+  tenantId: string; runId: string; step: RunStep; max: number | null; ended: boolean;
+}) {  // prettier-ignore
+  const attempts = useQuery({ ...runAttemptsQuery(tenantId, id, final.step_id, final.iteration_key), refetchInterval: ended ? false : READ_EVERY });
+  const all = attempts.data?.items.length ? attempts.data.items : [final];
+  const step = all.at(-1)!;
+  const from = all[0]?.started_at ?? step.started_at;
+  const to = step.ended_at;
+  const times = from && to ? (at(from) === at(to) ? at(from) : `${at(from)} to ${at(to)}`) : from ? `since ${at(from)}` : null;
+  const facts = [max ? `attempt ${step.attempt} of ${max}` : `attempt ${step.attempt}`, times, took(from, to)].filter(Boolean).join(" · ");
+  const status = STEP_STATUS[step.status];
+  return (
+    <>
+      <p className="flex flex-wrap items-center gap-2">
+        <ToneChip tone={status.tone}>{status.word}</ToneChip>
+        <span className="text-small text-muted">{facts}</span>
+      </p>
+      {step.error && (
+        <p className="rounded-lg border border-danger bg-danger-bg px-3 py-2 text-small">
+          <span className="font-mono text-danger">{step.error.code}</span>
+          {step.error.message && ` · ${step.error.message}`}
+        </p>
+      )}
+      <Section title="Attempts">
+        {attempts.isError ? (
+          <p className="text-small text-muted">Its attempts couldn&apos;t be read.</p>
+        ) : (
+          <ol className="flex flex-col text-small">
+            {all.map((a) => (
+              <li key={a.attempt} className="grid grid-cols-[1.5rem_auto_minmax(0,1fr)_auto_auto] items-center gap-2 border-t border-line py-1.5 first:border-t-0">
+                <span>{a.attempt}</span>
+                <ToneChip tone={STEP_STATUS[a.status].tone}>{STEP_STATUS[a.status].word.toLowerCase()}</ToneChip>
+                <span className="truncate font-mono text-meta">{a.error?.code ?? ""}</span>
+                <span className="text-muted">{a.started_at ? at(a.started_at) : ""}</span>
+                <span className="text-muted">{took(a.started_at, a.ended_at) ?? ""}</span>
+              </li>
+            ))}
+          </ol>
+        )}
+      </Section>
+      <Section title="Input">
+        <p className="text-small text-muted">As the last attempt received it. Sensitive values are redacted and long ones cut.</p>
+        <Values value={step.input} none="None." />
+      </Section>
+      <Section title="Output">
+        {step.status === "failed" ? <p className="text-small text-muted">None: the step failed.</p> : <Values value={step.output} none="None." />}
+      </Section>
+      {step.child_run_id && <SubRun tenantId={tenantId} id={step.child_run_id} />}
+    </>
+  );
+}
+
+/** A step's result: its one instance, or why it has none; `summary` undefined when the run's steps don't name it. */
+export function StepResult({ tenantId, runId: id, summary, max, ended, several }: {
+  tenantId: string; runId: string; summary: RunStepSummary | undefined; max: number | null; ended: boolean; several: ReactNode;
+}) {  // prettier-ignore
+  if (!summary) return <p className="text-small text-muted">This run has no result for this step.</p>;
+  if (summary.instances === 0) {
+    const why = summary.origin === null ? "No result." : `${ORIGIN[summary.origin].charAt(0).toUpperCase()}${ORIGIN[summary.origin].slice(1)}.`;
+    return <p className="text-small">{why}</p>;
+  }
+  if (summary.instances === 1 && summary.final) return <InstanceResult tenantId={tenantId} runId={id} step={summary.final} max={max} ended={ended} />;
+  return several;
+}
```

- [ ] **Step 4: Run them again**

Run: the same command.

Expected: PASS, 182 passed.

- [ ] **Step 5: Static checks**

Run: the two of "How to run things". Expected: no output.

- [ ] **Step 6: Commit**

```bash
git add frontend/src
git commit -m "feat(editor): a run's step in the editor's drawer: its result first, its attempts, input and output (4e-1b)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 11: A loop

**Spec:** §5.3 (a loop's drawer pages its iterations four at a time, with Open; a step in a loop has 4d-1c's
iteration picker); the RunLoop board; 4d-1c's ruling 4 (ledger 194).

**Files:**
- Create: `frontend/src/routes/editor/simulation/IterationPicker.tsx`
- Modify: `frontend/src/routes/editor/simulation/Iterations.tsx`,
  `frontend/src/routes/editor/simulation/Iterations.test.tsx`,
  `frontend/src/routes/editor/simulation/loopBody.ts`, `frontend/src/routes/editor/simulation/SimulationResult.tsx`,
  `frontend/src/routes/editor/simulation/LatestResult.tsx`
- Modify: `frontend/src/routes/runs/RunResult.tsx`, `frontend/src/routes/runs/RunPage.tsx`,
  `frontend/src/routes/runs/RunPage.test.tsx`, `frontend/src/test/runs.ts`

**Interfaces:**
- Consumes: `runInstancesQuery` (Task 3); `InstanceResult` (Task 10); `bodyOf` (`loopBody.ts`).
- Produces:
  - `InstancePages { key, read(stepId, page) }` (`loopBody.ts`); `Iterations({ pages, loop, body, onOpen? })` (was
    `tenantId`, `workflowId`, `requestId`); `IterationPicker({ pages, stepId, iteration, beyond?, show })`, `counted`.
  - `RunResult.tsx`: `LoopResult({ summary, pages, body, onOpen })`, `SeveralResult({ tenantId, runId, summary, total,
    pages, loopKey, iteration, max, ended })`; `InstanceResult`'s `iteration?`; `StepResult` loses `several`.
  - `test/runs.ts`: `LOOP_GRAPH`, `LOOP_STEPS`, `LOOP_TOTAL`, `loopInstance(key, n)`.

A loop that ran once says how many iterations, then lists them four at a time once it has ended, each row what its own
steps did, a failed one with Open. A step in a loop gives its instances' totals and, once the run has ended, one
iteration at a time, picked from its first 50, or the one a loop's Open asked for. 4d-1c's panel and Test tab read
through the same `InstancePages`.

- [ ] **Step 1: Write the failing tests**

Apply:

```diff
diff --git a/frontend/src/routes/editor/simulation/Iterations.test.tsx b/frontend/src/routes/editor/simulation/Iterations.test.tsx
index 46bdf11c..8f73ded1 100644
--- a/frontend/src/routes/editor/simulation/Iterations.test.tsx
+++ b/frontend/src/routes/editor/simulation/Iterations.test.tsx
@@ -3,6 +3,7 @@ import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
 import { render, screen, within } from "@testing-library/react";
 import userEvent from "@testing-library/user-event";
 import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
+import { stepInstancesQuery } from "../../../lib/simulations";
 import { Iterations } from "./Iterations";
 
 const PATH = "/api/v1/t/t1/workflows/w1/draft/simulations/r1/steps";
@@ -42,7 +43,7 @@ function show() {
   render(
     <QueryClientProvider client={qc}>
       <Iterations
-        tenantId="t1" workflowId="w1" requestId="r1" loop={{ key: "each_ap", prefix: "" }}
+        pages={{ key: ["simulation", "r1"], read: (step, page) => qc.query(stepInstancesQuery("t1", "w1", "r1", step, page)) }} loop={{ key: "each_ap", prefix: "" }}
         body={[{ id: "id-is_offline", key: "is_offline", type: "flow.if@1" }, { id: "id-notify", key: "notify", type: "slack.post@1" }]}
         onOpen={onOpen}
       />
diff --git a/frontend/src/routes/runs/RunPage.test.tsx b/frontend/src/routes/runs/RunPage.test.tsx
index 7bc49ddf..fc3b4b52 100644
--- a/frontend/src/routes/runs/RunPage.test.tsx
+++ b/frontend/src/routes/runs/RunPage.test.tsx
@@ -6,7 +6,7 @@ import userEvent from "@testing-library/user-event";
 import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
 import { onAnnounce } from "../../lib/announce";
 import type { Run, RunSteps } from "../../lib/runs";
-import { FAILED_GRAPH, FAILED_RUN, FAILED_STEPS, RUN_TYPES, attempt, local } from "../../test/runs";
+import { FAILED_GRAPH, FAILED_RUN, FAILED_STEPS, LOOP_GRAPH, LOOP_STEPS, LOOP_TOTAL, RUN_TYPES, attempt, local, loopInstance } from "../../test/runs";
 import type { CanvasProps } from "../editor/Canvas";
 import { RunPage } from "./RunPage";
 
@@ -52,7 +52,7 @@ const NOW = Date.parse(local(10, 2, 19));
 const VERSION = { id: "v2", number: 2, graph: FAILED_GRAPH, active: true, blocked_by: [], cel_profile: "p", engine_abi: 9, executable: true,
   expressions: [], graph_hash: "h", node_refs: [], published_at: local(8, 0, 0), published_by: null, version_hash: "vh" };  // prettier-ignore
 
-let answers: Map<string, () => Response>;
+let answers: Map<string, (url: URL) => Response>;
 let reads: string[];
 
 beforeEach(() => {
@@ -64,10 +64,10 @@ beforeEach(() => {
   reads = [];
   vi.spyOn(Date, "now").mockReturnValue(NOW);
   vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
-    const path = new URL((input as Request).url).pathname;
-    reads.push(path);
-    const answer = answers.get(path);
-    return Promise.resolve(answer ? answer() : new Response(JSON.stringify({ error: "not_found" }), { status: 404 }));
+    const url = new URL((input as Request).url);
+    reads.push(url.pathname);
+    const answer = answers.get(url.pathname);
+    return Promise.resolve(answer ? answer(url) : new Response(JSON.stringify({ error: "not_found" }), { status: 404 }));
   });
 });
 afterEach(() => vi.restoreAllMocks());
@@ -361,3 +361,78 @@ describe("a step's result in the drawer (§5.3; the RunFailed and RunLoop boards
     expect(within(side).getByText("This server doesn't know this step's type, so its settings can't be shown. They're kept as they are.")).toBeTruthy();
   });
 });
+
+describe("a loop (§5.3; the RunLoop board)", () => {
+  const RUN_PATH = `/api/v1/t/t1/runs/${RUN.id}`;
+  const loopRun: Run = { ...RUN, status: "succeeded", error: null, ended_at: local(14, 4, 31) };
+  const instances = (key: "is_offline" | "notify") => (url: URL) => {
+    const [offset, limit, within] = [Number(url.searchParams.get("offset")), Number(url.searchParams.get("limit")), url.searchParams.get("within")];
+    const all = Array.from({ length: LOOP_TOTAL }, (_, n) => loopInstance(key, n)).filter((i) => !within || i.iteration_key === within);
+    return new Response(JSON.stringify({ total: all.length, items: all.slice(offset, offset + limit) }));
+  };
+  const drawer = (key: string) => screen.getByRole("complementary", { name: key });
+
+  beforeEach(() => {
+    answers.set(RUN_PATH, json(loopRun));
+    answers.set(`${RUN_PATH}/steps`, json(LOOP_STEPS));
+    answers.set("/api/v1/t/t1/workflows/w1/versions/v2", json({ ...VERSION, graph: LOOP_GRAPH }));
+    answers.set(`${RUN_PATH}/steps/id-is_offline/instances`, instances("is_offline"));
+    answers.set(`${RUN_PATH}/steps/id-notify/instances`, instances("notify"));
+    answers.set(`${RUN_PATH}/steps/id-notify/attempts`, (url) => json({ items: [loopInstance("notify", Number(url.searchParams.get("iteration")!.split(":")[1]))] })());
+    answers.set(`${RUN_PATH}/steps/id-each_ap/attempts`, json({ items: [LOOP_STEPS.steps[1]!.final] }));
+  });
+
+  it("totals each step on the canvas, from the server's summary", async () => {
+    show();
+    await vi.waitFor(() => expect(canvas().dataset.results).not.toBe("[]"));
+    expect((JSON.parse(canvas().dataset.results!) as unknown[]).slice(1)).toEqual([
+      ["id-each_ap", ["succeeded", "120 iterations"]],
+      ["id-is_offline", ["120 instances: 120 succeeded", "→ true ×17", "→ false ×103"]],
+      ["id-notify", ["120 instances: 14 succeeded · 3 failed · 103 skipped", "sent"]],
+    ]);  // prettier-ignore
+  });
+
+  it("pages the loop's iterations four at a time, and opens a failed one's step at that iteration", async () => {
+    show();
+    await vi.waitFor(() => expect(canvas().dataset.results).not.toBe("[]"));
+    await userEvent.click(within(canvas()).getByRole("button", { name: "each_ap" }));
+    const side = drawer("each_ap");
+    expect(await within(side).findByText("120 iterations · 14:02:10 to 14:04:30 · 2 min 20 s")).toBeTruthy();
+    const list = await within(side).findByRole("list", { name: "each_ap's iterations, 1 to 4 of 120" });
+    expect(within(list).getAllByRole("listitem").map((li) => li.textContent)).toEqual([
+      "1 · is_offline → false · notify skipped", "2 · is_offline → true · notify succeeded", "3 · is_offline → false · notify skipped",
+      "4 · is_offline → true · notify failed · invalid_blocks Open",
+    ]);  // prettier-ignore
+    await userEvent.click(within(side).getByRole("button", { name: "Next 4" }));
+    expect(await within(side).findByRole("list", { name: "each_ap's iterations, 5 to 8 of 120" })).toBeTruthy();
+    await userEvent.click(within(side).getByRole("button", { name: "Previous 4" }));
+    await userEvent.click(await within(side).findByRole("button", { name: "Open notify, iteration 4" }));
+    const step = drawer("notify");
+    expect(await within(step).findByText("iteration 4 · attempt 1 of 3 · 14:02:13 · 0.9 s")).toBeTruthy();
+    expect(within(step).getAllByText("invalid_blocks")[0]!.closest("p")!.textContent).toBe("invalid_blocks · Slack refused the message's blocks.");
+    expect(within(step).getByRole<HTMLSelectElement>("combobox", { name: "Iteration" }).value).toBe("each_ap:3");
+  });
+
+  it("shows one of a loop step's first 50 iterations at a time, picked (§5.3; 4d-1c's picker)", async () => {
+    show();
+    await vi.waitFor(() => expect(canvas().dataset.results).not.toBe("[]"));
+    await userEvent.click(within(canvas()).getByRole("button", { name: "notify" }));
+    const side = drawer("notify");
+    expect(within(side).getByText("120 instances: 14 succeeded · 3 failed · 103 skipped")).toBeTruthy();
+    const pick = await within(side).findByRole("combobox", { name: "Iteration" });
+    expect(within(pick).getAllByRole("option")).toHaveLength(50);
+    expect(within(side).getByText("The first 50 of 120 iterations. Open any other from each_ap's list.")).toBeTruthy();
+    await userEvent.selectOptions(pick, "each_ap:1");
+    await userEvent.click(within(side).getByRole("button", { name: "Show" }));
+    expect(await within(side).findByText("iteration 2 · attempt 1 of 3 · 14:02:11 · 0.9 s")).toBeTruthy();
+    expect(within(side).getByText("Succeeded").className).toContain("border-ok");
+  });
+
+  it("opens a failed run on its failed step in a loop, one of its iterations at a time", async () => {
+    answers.set(RUN_PATH, json({ ...loopRun, status: "failed", error: { code: "invalid_blocks", message: "Slack refused the message's blocks." } }));
+    show();
+    const side = await screen.findByRole("complementary", { name: "notify" });
+    expect(within(side).getByText("120 instances: 14 succeeded · 3 failed · 103 skipped")).toBeTruthy();
+    expect(await within(side).findByRole("combobox", { name: "Iteration" })).toBeTruthy();
+  });
+});
diff --git a/frontend/src/test/runs.ts b/frontend/src/test/runs.ts
index 69515754..00a84893 100644
--- a/frontend/src/test/runs.ts
+++ b/frontend/src/test/runs.ts
@@ -3,7 +3,7 @@
 // steps. Made up, never a real tenant's (D24).
 import type { Run, RunItem, RunStep, RunStepSummary, RunSteps } from "../lib/runs";
 import type { GraphDoc, NodeType } from "../lib/workflows";
-import { IF, TRANSFORM, typeWith } from "./nodeTypes";
+import { IF, LOOP, TRANSFORM, typeWith } from "./nodeTypes";
 
 /** An instant on the person's own clock, today (16 October 2026) unless `day` says: what a page says of it doesn't
  * depend on the zone the tests run in. */
@@ -30,6 +30,7 @@ export const RUN_TYPES: NodeType[] = [
   typeWith({}, { ref: "acme.send_request@1", type: "acme.send_request", title: "Send a request" }),
   typeWith({}, { ref: "acme.post_message@1", type: "acme.post_message", title: "Post a message" }),
   IF,
+  LOOP,
   TRANSFORM,
 ];
 
@@ -71,3 +72,36 @@ export const FAILED_STEPS: RunSteps = {
     summary("log_recovery", "flow.transform@1", { origin: "skipped", statuses: { skipped: 1 }, final: attempt("log_recovery", { status: "skipped" }) }),
   ],
 };  // prettier-ignore
+
+/** The RunLoop board: list_aps, then each_ap over its output; in its body, is_offline, and notify where it's true. */
+export const LOOP_GRAPH: GraphDoc = {
+  graph_format: 1,
+  nodes: [
+    step("list_aps", "acme.get_device@1", 140), { ...step("each_ap", "flow.loop@1", 280), config: { items: { $value: { kind: "cel", expr: "steps.list_aps.output" } } } },
+    step("is_offline", "flow.if@1", 420), step("notify", "acme.post_message@1", 560),
+  ],
+  edges: [to("list_aps", "each_ap"), to("each_ap", "is_offline", "body"), to("is_offline", "notify", "true")],
+};  // prettier-ignore
+export const LOOP_TOTAL = 120;
+/** Iteration n (from 0): is_offline took "true" on every seventh; notify ran there (the 4th iteration's failed), and
+ * was skipped elsewhere. */
+export function loopInstance(key: "is_offline" | "notify", n: number): RunStep {
+  const on = n % 7 === 3 || n === 1;
+  const at = local(14, 2, 10 + (n % 50), 0);
+  if (key === "is_offline") return attempt(key, { iteration_key: `each_ap:${n}`, started_at: at, ended_at: at, effect: { port: on ? "true" : "false" } });
+  if (!on) return attempt(key, { iteration_key: `each_ap:${n}`, status: "skipped", started_at: null, ended_at: null });
+  return attempt(key, {
+    iteration_key: `each_ap:${n}`, status: n === 3 ? "failed" : "succeeded", started_at: at, ended_at: local(14, 2, 10 + (n % 50), 900),
+    error: n === 3 ? { code: "invalid_blocks", message: "Slack refused the message's blocks." } : null,
+    input: { channel: "#noc-alert", text: `AP-Lobby-0${n} offline` },
+  });  // prettier-ignore
+}
+export const LOOP_STEPS: RunSteps = {
+  given: "input",
+  steps: [
+    summary("list_aps", "acme.get_device@1", { origin: "sent" }),
+    summary("each_ap", "flow.loop@1", { final: attempt("each_ap", { started_at: local(14, 2, 10), ended_at: local(14, 4, 30), output: { count: LOOP_TOTAL } }) }),
+    summary("is_offline", "flow.if@1", { instances: LOOP_TOTAL, statuses: { succeeded: LOOP_TOTAL }, ports: { true: 17, false: 103 }, final: null }),
+    summary("notify", "acme.post_message@1", { origin: "sent", instances: LOOP_TOTAL, statuses: { succeeded: 14, failed: 3, skipped: 103 }, final: null }),
+  ],
+};  // prettier-ignore
```

- [ ] **Step 2: Run them**

Run: `npx --offline pnpm@12.6.0 exec vitest run src/routes/runs/RunPage.test.tsx src/routes/editor/simulation`

Expected: FAIL, 5 failed and 137 passed: a loop's drawer says nothing of its iterations and a step in a loop has no
picker (`Unable to find an element with the text: 120 instances: 14 succeeded · 3 failed · 103 skipped`); 4d-1c's
`Iterations` ignores the `pages` it's now given (`expected [ …(2) ] to include
'/api/v1/t/t1/workflows/w1/draft/simul…'`). "totals each step on the canvas" passes at once: Tasks 8 and 9 already sum a
loop's steps; it pins them on the loop fixture.

- [ ] **Step 3: Implement**

Apply:

```diff
diff --git a/frontend/src/routes/editor/simulation/IterationPicker.tsx b/frontend/src/routes/editor/simulation/IterationPicker.tsx
new file mode 100644
index 00000000..7a5bb792
--- /dev/null
+++ b/frontend/src/routes/editor/simulation/IterationPicker.tsx
@@ -0,0 +1,69 @@
+// SPDX-License-Identifier: Apache-2.0
+// One iteration of a step that ran in a loop, picked (4d-1c; the simulation design §7.6's iteration picker; and a run's
+// drawer, 4e-1, the RunLoop board): from the first page of its instances, in iteration order, or the one a loop's
+// "Open" asked for, read on its own when it's past that page. Show shows it.
+import { useQuery } from "@tanstack/react-query";
+import { useEffect, useState, type ReactNode } from "react";
+import { Button } from "../../../components/Button";
+import { Select } from "../../../components/Field";
+import type { InstancePages } from "./loopBody";
+import { field } from "./results";
+
+const PAGE = 50;
+
+/** An iteration as a person counts it: from 1, nested ones joined ("2/3"). */
+export const counted = (key: string) => key.split("/").map((part) => Number(part.split(":").at(-1)) + 1).join("/");
+const keyOf = (item: unknown) => {
+  const key = field(item, "iteration_key");
+  return typeof key === "string" ? key : "";
+};
+function optionOf(item: unknown): string {
+  const status = field(item, "status");
+  const code = field(field(item, "error"), "code");
+  return `${counted(keyOf(item))} · ${typeof status === "string" ? status.replace("_", " ") : "not recorded"}${typeof code === "string" ? ` · ${code}` : ""}`;
+}
+
+/** `iteration`: one asked for (counted, so the same one asked again shows again); `beyond`: what the caption adds when
+ * there are more than the first page; `show`: an instance, by its counted iteration. */
+export function IterationPicker({ pages, stepId, iteration, beyond, show }: {
+  pages: InstancePages; stepId: string; iteration: { key: string; n: number } | null; beyond?: string;
+  show: (item: unknown, iteration: string) => ReactNode;
+}) {  // prettier-ignore
+  const page = useQuery({ queryKey: ["iteration-picker", ...pages.key, stepId], queryFn: () => pages.read(stepId, { offset: 0, limit: PAGE }) });
+  const [picked, setPicked] = useState<string | null>(iteration?.key ?? null);
+  const [shown, setShown] = useState<string | null>(iteration?.key ?? null);
+  useEffect(() => {
+    if (iteration) {
+      setPicked(iteration.key);
+      setShown(iteration.key);
+    }
+  }, [iteration?.n]);
+  const first = page.data?.items ?? [];
+  const askedPast = iteration !== null && page.data !== undefined && !first.some((i) => keyOf(i) === iteration.key);
+  const asked = useQuery({
+    queryKey: ["iteration-picker", ...pages.key, stepId, iteration?.key ?? null],
+    queryFn: () => pages.read(stepId, { offset: 0, limit: 1, within: iteration?.key }),
+    enabled: askedPast,
+  });
+  if (page.isError) return <p className="text-small text-muted">Its iterations couldn&apos;t be read.</p>;
+  if (!page.data) return <p className="text-small text-muted">Reading its iterations…</p>;
+  const items = askedPast && asked.data ? [...first, ...asked.data.items.filter((i) => keyOf(i) === iteration?.key)] : first;
+  const choice = picked ?? (items[0] ? keyOf(items[0]) : "");
+  const item = shown === null ? undefined : items.find((i) => keyOf(i) === shown);
+  return (
+    <>
+      <div className="flex flex-wrap items-end gap-2">
+        <div className="min-w-0 grow">
+          <Select label="Iteration" value={choice} onChange={(e) => setPicked(e.target.value)}>
+            {items.map((i) => <option key={keyOf(i)} value={keyOf(i)}>{optionOf(i)}</option>)}
+          </Select>
+        </div>
+        <Button size="md" onClick={() => setShown(choice || null)}>Show</Button>
+      </div>
+      {page.data.total > first.length && (
+        <p className="text-small text-muted">{`The first ${first.length} of ${page.data.total} iterations.${beyond ? ` ${beyond}` : ""}`}</p>
+      )}
+      {item !== undefined && show(item, counted(keyOf(item)))}
+    </>
+  );
+}
diff --git a/frontend/src/routes/editor/simulation/Iterations.tsx b/frontend/src/routes/editor/simulation/Iterations.tsx
index bec0efa1..0848e27e 100644
--- a/frontend/src/routes/editor/simulation/Iterations.tsx
+++ b/frontend/src/routes/editor/simulation/Iterations.tsx
@@ -1,14 +1,13 @@
 // SPDX-License-Identifier: Apache-2.0
-// A loop's iterations in the Simulation panel, four at a time (4d-1c; the simulation design §7.5; the ResultPanel
-// board): each row, what the loop's own steps did in that iteration, read a page at a time from the server's
-// instances (decision 5), never the whole run at once. A failed step opens its instance in that iteration. While the
+// A loop's iterations, four at a time (4d-1c; the simulation design §7.5; the ResultPanel board; and a run's drawer,
+// 4e-1, the RunLoop board): each row, what the loop's own steps did in that iteration, read a page at a time from the
+// server's instances (decision 5), never the whole run at once. A failed step opens its instance in that iteration. While the
 // next page is read, the one shown stays, with the focus where it was; when a page has no button the person was on
 // (the last has no Next, the first no Previous), the focus goes to the other one.
-import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";
+import { keepPreviousData, useQuery } from "@tanstack/react-query";
 import { Fragment, useEffect, useRef, useState } from "react";
 import { Button } from "../../../components/Button";
-import { stepInstancesQuery } from "../../../lib/simulations";
-import { PAGE, cellOf, iterationOf } from "./loopBody";
+import { PAGE, cellOf, iterationOf, type InstancePages } from "./loopBody";
 
 export interface BodyStep {
   id: string;
@@ -18,25 +17,22 @@ export interface BodyStep {
 
 const keyed = (item: unknown): unknown => (typeof item === "object" && item !== null ? (item as Record<string, unknown>).iteration_key : undefined);
 
-export function Iterations({ tenantId, workflowId, requestId, loop, body, onOpen }: {
-  tenantId: string; workflowId: string; requestId: string; loop: { key: string; prefix: string }; body: BodyStep[];
-  onOpen?: (stepId: string, iterationKey: string) => void;
+export function Iterations({ pages, loop, body, onOpen }: {
+  pages: InstancePages; loop: { key: string; prefix: string }; body: BodyStep[]; onOpen?: (stepId: string, iterationKey: string) => void;
 }) {  // prettier-ignore
   const [offset, setOffset] = useState(0); // the page asked for
   const [view, setView] = useState(0); // the page shown while the one asked for is read
   const [paged, setPaged] = useState<"next" | "previous" | null>(null); // the button the person paged with
   const next = useRef<HTMLButtonElement>(null);
   const previous = useRef<HTMLButtonElement>(null);
-  // One query per page, each step's instances read through the client (and kept under their own keys): one observer, so
+  // One query per page, each step's instances read through `pages` (and kept under their own keys): one observer, so
   // the page shown stays while the next is read (useQueries makes a new observer per key, with nothing to keep).
-  const qc = useQueryClient();
-  const pages = useQuery({
-    queryKey: ["simulation-iterations", tenantId, workflowId, requestId, loop.prefix, loop.key, body.map((b) => b.id), offset],
-    queryFn: () =>
-      Promise.all(body.map((b) => qc.fetchQuery(stepInstancesQuery(tenantId, workflowId, requestId, b.id, { offset, limit: PAGE, within: loop.prefix || undefined })))),
+  const read = useQuery({
+    queryKey: ["iterations", ...pages.key, loop.prefix, loop.key, body.map((b) => b.id), offset],
+    queryFn: () => Promise.all(body.map((b) => pages.read(b.id, { offset, limit: PAGE, within: loop.prefix || undefined }))),
     placeholderData: keepPreviousData,
   });
-  const reading = pages.isPlaceholderData;
+  const reading = read.isPlaceholderData;
   useEffect(() => {
     if (!reading) setView(offset);
   }, [reading, offset]);
@@ -46,17 +42,17 @@ export function Iterations({ tenantId, workflowId, requestId, loop, body, onOpen
     if (lost) (paged === "next" ? previous : next).current?.focus();
     setPaged(null);
   }, [paged, reading, offset]);
-  if (pages.isError) {
+  if (read.isError) {
     return (
       <p className="flex flex-wrap items-center gap-2 text-small">
         The iterations couldn&apos;t be read.
-        <Button size="sm" onClick={() => void pages.refetch()}>Read them again</Button>
+        <Button size="sm" onClick={() => void read.refetch()}>Read them again</Button>
       </p>
     );
   }
-  const read = pages.data;
-  if (read === undefined) return <p className="text-small text-muted">Reading the iterations…</p>;
-  const total = Math.max(0, ...read.map((d) => d.total));
+  const answers = read.data;
+  if (answers === undefined) return <p className="text-small text-muted">Reading the iterations…</p>;
+  const total = Math.max(0, ...answers.map((d) => d.total));
   if (total === 0) return <p className="text-small text-muted">No iteration was opened.</p>;
   const at0 = reading ? view : offset; // the first iteration shown
   const shown = Math.max(0, Math.min(PAGE, total - at0));
@@ -76,7 +72,7 @@ export function Iterations({ tenantId, workflowId, requestId, loop, body, onOpen
             <li key={n} className="border-t border-line py-1.5 first:border-t-0">
               {n + 1}
               {body.map((b, j) => {
-                const c = cellOf(read[j]?.items.find((item) => keyed(item) === at), b.type);
+                const c = cellOf(answers[j]?.items.find((item) => keyed(item) === at), b.type);
                 return (
                   <Fragment key={b.id}>
                     {" · "}
diff --git a/frontend/src/routes/editor/simulation/LatestResult.tsx b/frontend/src/routes/editor/simulation/LatestResult.tsx
index b21bcdca..a13f8078 100644
--- a/frontend/src/routes/editor/simulation/LatestResult.tsx
+++ b/frontend/src/routes/editor/simulation/LatestResult.tsx
@@ -3,88 +3,40 @@
 // "After a workflow simulation, the step's result in it, with an iteration picker"; the TestTab and TestOther boards):
 // its tags, as on the canvas; one instance shown as it is; a step that ran in a loop, one iteration at a time, picked
 // from the first page of its instances, or the one the Simulation panel's "Open" asked for.
-import { useQuery } from "@tanstack/react-query";
-import { useEffect, useState } from "react";
-import { Button } from "../../../components/Button";
-import { Select } from "../../../components/Field";
+import { useQueryClient } from "@tanstack/react-query";
 import { sameId } from "../../../lib/graph";
 import { ENDED, stepInstancesQuery, type StepSummary } from "../../../lib/simulations";
 import type { GraphNode } from "../../../lib/workflows";
 import { clock } from "./lifecycle";
-import { field, tagsOf } from "./results";
+import { IterationPicker } from "./IterationPicker";
+import type { InstancePages } from "./loopBody";
+import { tagsOf } from "./results";
 import { InstanceDetail } from "./StepResult";
 import { Section } from "./UsedValues";
 import type { SimulationSession } from "./useSimulation";
 
-const PAGE = 50;
-
-/** An iteration as a person counts it: from 1, nested ones joined ("2/3"). */
-const counted = (key: string) => key.split("/").map((part) => Number(part.split(":").at(-1)) + 1).join("/");
-const keyOf = (item: unknown) => {
-  const key = field(item, "iteration_key");
-  return typeof key === "string" ? key : "";
-};
-function optionOf(item: unknown): string {
-  const status = field(item, "status");
-  const code = field(field(item, "error"), "code");
-  return `${counted(keyOf(item))} · ${typeof status === "string" ? status.replace("_", " ") : "not recorded"}${typeof code === "string" ? ` · ${code}` : ""}`;
-}
-
 export function LatestResult({ tenantId, workflowId, session, node, attemptsOf, iteration }: {
   tenantId: string; workflowId: string; session: SimulationSession; node: GraphNode;
   attemptsOf: (s: StepSummary) => number | null; iteration: { key: string; n: number } | null;
 }) {  // prettier-ignore
   const { state, phase } = session;
+  const qc = useQueryClient();
   const s = state && state.request.target_step_id === null ? session.steps?.steps.find((x) => sameId(x.step_id, node.id)) : undefined;
   const ended = phase !== null && ENDED.has(phase);
-  const several = s !== undefined && s.instances > 1;
-  const page = useQuery({
-    ...stepInstancesQuery(tenantId, workflowId, state?.request.id ?? "", node.id, { offset: 0, limit: PAGE }),
-    enabled: several && ended,
-  });
-  const [picked, setPicked] = useState<string | null>(iteration?.key ?? null);
-  const [shown, setShown] = useState<string | null>(iteration?.key ?? null);
-  useEffect(() => {
-    if (iteration) {
-      setPicked(iteration.key);
-      setShown(iteration.key);
-    }
-  }, [iteration?.n]);
-  // The iteration "Open" asked for, read on its own when it's past the picker's first page (§7.5: a loop's iterations).
-  const first = page.data?.items ?? [];
-  const askedPast = iteration !== null && page.data !== undefined && !first.some((i) => keyOf(i) === iteration.key);
-  const asked = useQuery({
-    ...stepInstancesQuery(tenantId, workflowId, state?.request.id ?? "", node.id, { offset: 0, limit: 1, within: iteration?.key }),
-    enabled: several && ended && askedPast,
-  });
   if (!s || !state) return null;
-  const items = askedPast && asked.data ? [...first, ...asked.data.items.filter((i) => keyOf(i) === iteration?.key)] : first;
-  const choice = picked ?? (items[0] ? keyOf(items[0]) : "");
-  const item = shown === null ? undefined : items.find((i) => keyOf(i) === shown);
+  const several = s.instances > 1;
+  const requestId = state.request.id;
+  const pages: InstancePages = {
+    key: ["simulation", tenantId, workflowId, requestId],
+    read: (stepId, page) => qc.query(stepInstancesQuery(tenantId, workflowId, requestId, stepId, page)),
+  };
   const words = tagsOf(s, { maxAttempts: attemptsOf(s), ended }).map((t) => t.text).join(" · ");
   return (
     <Section title="In your latest simulation">
       <p className="text-small">{`Revision ${state.request.draft_revision}, ${state.request.queued_at ? clock(state.request.queued_at) : "earlier"}: ${words}.`}</p>
       {s.instances === 1 && <InstanceDetail final={s.final} max={attemptsOf(s)} />}
       {several && ended && (
-        page.isError ? (
-          <p className="text-small text-muted">Its iterations couldn&apos;t be read.</p>
-        ) : !page.data ? (
-          <p className="text-small text-muted">Reading its iterations…</p>
-        ) : (
-          <>
-            <div className="flex flex-wrap items-end gap-2">
-              <div className="min-w-0 grow">
-                <Select label="Iteration" value={choice} onChange={(e) => setPicked(e.target.value)}>
-                  {items.map((i) => <option key={keyOf(i)} value={keyOf(i)}>{optionOf(i)}</option>)}
-                </Select>
-              </div>
-              <Button size="md" onClick={() => setShown(choice || null)}>Show</Button>
-            </div>
-            {page.data.total > first.length && <p className="text-small text-muted">{`The first ${first.length} of ${page.data.total} iterations.`}</p>}
-            {item !== undefined && <InstanceDetail final={item} max={attemptsOf(s)} />}
-          </>
-        )
+        <IterationPicker pages={pages} stepId={node.id} iteration={iteration} show={(item) => <InstanceDetail final={item} max={attemptsOf(s)} />} />
       )}
     </Section>
   );
diff --git a/frontend/src/routes/editor/simulation/SimulationResult.tsx b/frontend/src/routes/editor/simulation/SimulationResult.tsx
index ac29d30a..c7c3880d 100644
--- a/frontend/src/routes/editor/simulation/SimulationResult.tsx
+++ b/frontend/src/routes/editor/simulation/SimulationResult.tsx
@@ -5,13 +5,14 @@
 // request stored it (§6.6's read-back: never recomputed from today's draft). A result from before the person's edits
 // says so, and marks each step changed since or no longer in the draft; a failed step says its code and message, and
 // that nothing was sent; a refusal is shown in the server's words (§7.7; the Stale and Refusals boards).
+import { useQueryClient } from "@tanstack/react-query";
 import { useState } from "react";
 import { Button } from "../../../components/Button";
 import { findNode, idKey } from "../../../lib/graph";
-import { ENDED, type StepSummary } from "../../../lib/simulations";
+import { ENDED, stepInstancesQuery, type StepSummary } from "../../../lib/simulations";
 import type { GraphDoc } from "../../../lib/workflows";
 import { Failure } from "./Failure";
-import { bodyOf } from "./loopBody";
+import { bodyOf, type InstancePages } from "./loopBody";
 import { Iterations } from "./Iterations";
 import { tagsOf } from "./results";
 import { SimBanner } from "./SimBanner";
@@ -33,6 +34,7 @@ export function SimulationResult({ tenantId, workflowId, session, doc, ran, stal
   onGoTo: (stepId: string) => void; onShowProblems: () => void; onOpen?: (stepId: string, iterationKey: string) => void;
 }) {  // prettier-ignore
   const [open, setOpen] = useState<string | null>(null); // the loop whose iterations are shown
+  const qc = useQueryClient();
   const { local, state, phase } = session;
   if (local.kind === "refused") {
     return <Refusal error={local.error} doc={doc} onGoTo={onGoTo} onShowProblems={onShowProblems} onTryAgain={() => void session.checkAgain()} />;
@@ -41,6 +43,10 @@ export function SimulationResult({ tenantId, workflowId, session, doc, ran, stal
   const ended = ENDED.has(phase);
   const began = phase !== "refused" && phase !== "dead"; // it ran, if only in part
   const request = state.request;
+  const pages: InstancePages = {
+    key: ["simulation", tenantId, workflowId, request.id],
+    read: (stepId, page) => qc.query(stepInstancesQuery(tenantId, workflowId, request.id, stepId, page)),
+  };
   const all = session.steps?.steps ?? [];
   const steps = ended ? all : all.filter((s) => s.instances > 0);
   const goTo = (id: string, key: string) =>
@@ -109,7 +115,7 @@ export function SimulationResult({ tenantId, workflowId, session, doc, ran, stal
                   {expanded && (
                     <div className="basis-full ps-3">
                       <Iterations
-                        tenantId={tenantId} workflowId={workflowId} requestId={request.id} loop={{ key: s.key, prefix: iterationKey(s.final) }}
+                        pages={pages} loop={{ key: s.key, prefix: iterationKey(s.final) }}
                         body={body.map((n) => ({ id: n.id, key: n.key, type: n.type }))} onOpen={onOpen}
                       />
                     </div>
diff --git a/frontend/src/routes/editor/simulation/loopBody.ts b/frontend/src/routes/editor/simulation/loopBody.ts
index 8553e990..6305b8a1 100644
--- a/frontend/src/routes/editor/simulation/loopBody.ts
+++ b/frontend/src/routes/editor/simulation/loopBody.ts
@@ -9,6 +9,13 @@ import type { GraphDoc, GraphNode } from "../../../lib/workflows";
 const LOOP = "flow.loop@";
 export const PAGE = 4;
 
+/** Where a loop's instances are read (4e-1): under the simulation or the run they're of (`key`), a page of one step's
+ * at a time, under an iteration when `within` names one. */
+export interface InstancePages {
+  key: readonly unknown[];
+  read: (stepId: string, page: { offset: number; limit: number; within?: string }) => Promise<{ total: number; items: unknown[] }>;
+}
+
 /** Every step reachable from a loop's `body` port, as the engine reads a loop's region (engine/graph/structure.py). */
 export function regionOf(doc: GraphDoc, loopId: string): Set<string> {
   const edges = edgesOf(doc);
diff --git a/frontend/src/routes/runs/RunPage.tsx b/frontend/src/routes/runs/RunPage.tsx
index 6435d6ee..ac50ebff 100644
--- a/frontend/src/routes/runs/RunPage.tsx
+++ b/frontend/src/routes/runs/RunPage.tsx
@@ -6,14 +6,14 @@
 // its failed step (the owner's answer 6), and Close gives focus back to its card. A run past its tenant's retention, or
 // an id that never was, is said to be neither, with Back to Runs; a run read while its tenant is erased says why it
 // can't be (§5.5).
-import { useQuery } from "@tanstack/react-query";
+import { useQuery, useQueryClient } from "@tanstack/react-query";
 import { Link } from "@tanstack/react-router";
 import { useCallback, useMemo, useState, type KeyboardEvent } from "react";
 import { Button, LINK_BUTTON } from "../../components/Button";
 import { When } from "../../components/When";
 import { ApiError } from "../../lib/client";
-import { findNode, idKey, nodesOf, portsOf } from "../../lib/graph";
-import { isEnded, type RunStepSummary } from "../../lib/runs";
+import { findNode, idKey, nodesOf, portsOf, sameId } from "../../lib/graph";
+import { isEnded, runInstancesQuery, type RunStepSummary } from "../../lib/runs";
 import { runId } from "../../lib/runStatus";
 import { draftSnapshotQuery } from "../../lib/simulations";
 import { useDocumentTitle } from "../../lib/title";
@@ -26,10 +26,11 @@ import { READ_ONLY_ACTIONS } from "../editor/drawer/context";
 import { StepDrawer } from "../editor/drawer/StepDrawer";
 import { item, type ItemAction } from "../editor/items";
 import { endedWhat } from "../editor/simulation/lifecycle";
+import { bodyOf, type InstancePages } from "../editor/simulation/loopBody";
 import { tagsOf, type SimTag } from "../editor/simulation/results";
 import { useCanvasNav } from "../editor/useCanvasNav";
 import { RunBanner, RunBar } from "./RunBar";
-import { StepResult } from "./RunResult";
+import { LoopResult, SeveralResult, StepResult } from "./RunResult";
 import { triggerOf, triggerWords } from "./trigger";
 import { useRunReads } from "./useRunReads";
 
@@ -90,7 +91,14 @@ export function RunPage({ tenantId, runId: id }: { tenantId: string; runId: stri
   // Each step's tags, 4d-1c's grammar with a run's (§5.3): an action's time, a failure's code.
   const results = useMemo(() => new Map((steps.data?.steps ?? []).map((s): [string, SimTag[]] => [idKey(s.step_id), tagsFor(s)])), [steps.data, tagsFor]);
   // The step whose result is open. Undecided until its steps and graph are read: a failed run opens on its failed step.
+  // A loop's "Open" asks for one iteration of a step in it (counted: the same one asked again shows again).
   const [open, setOpen] = useState<string | null | undefined>(undefined);
+  const [iteration, setIteration] = useState<{ key: string; n: number } | null>(null);
+  const qc = useQueryClient();
+  const pages = useMemo<InstancePages>(
+    () => ({ key: ["run", tenantId, id], read: (stepId, page) => qc.query(runInstancesQuery(tenantId, id, stepId, page)) }),
+    [qc, tenantId, id],
+  );
   if (open === undefined && r && steps.data && graph) {
     setOpen(r.status === "failed" ? (steps.data.steps.find((s) => (s.statuses.failed ?? 0) > 0)?.step_id ?? null) : null);
   }
@@ -107,8 +115,33 @@ export function RunPage({ tenantId, runId: id }: { tenantId: string; runId: stri
   const node = open && graph ? findNode(graph, open) : undefined;
   const summary = node && steps.data?.steps.find((s) => idKey(s.step_id) === idKey(node.id));
   const onItem = (action: ItemAction) => {
-    if (action.kind === "open") setOpen(action.node);
+    if (action.kind !== "open") return;
+    setOpen(action.node);
+    setIteration(null);
+  };
+  const openIteration = (stepId: string, key: string) => {
+    setOpen(stepId);
+    setIteration((i) => ({ key, n: (i?.n ?? 0) + 1 }));
   };
+  // A step's result: a loop that ran once, its iterations; a step in a loop, its instances one at a time; else its one
+  // instance, or why it has none.
+  function resultOf(summary: RunStepSummary | undefined) {
+    const max = summary ? attemptsOf(summary) : null;
+    if (summary && graph && summary.type.startsWith("flow.loop@") && summary.instances === 1 && summary.final) {
+      const body = bodyOf(graph, summary.step_id).map((n) => ({ id: n.id, key: n.key, type: n.type }));
+      return <LoopResult summary={summary} pages={pages} body={body} onOpen={openIteration} />;
+    }
+    if (summary && graph && summary.instances > 1) {
+      const loop = nodesOf(graph).find((n) => n.type.startsWith("flow.loop@") && bodyOf(graph, n.id).some((b) => sameId(b.id, summary.step_id)));
+      return (
+        <SeveralResult
+          tenantId={tenantId} runId={id} summary={summary} total={tagsFor(summary)[0]?.text ?? ""} pages={pages}
+          loopKey={loop?.key ?? null} iteration={iteration} max={max} ended={ended}
+        />
+      );  // prettier-ignore
+    }
+    return <StepResult tenantId={tenantId} runId={id} summary={summary} max={max} ended={ended} />;
+  }
   return (
     <div className="@container flex min-h-0 flex-1 flex-col">
       <RunBar tenantId={tenantId} run={r} version={version.data?.number ?? null} />
@@ -184,16 +217,7 @@ export function RunPage({ tenantId, runId: id }: { tenantId: string; runId: stri
             actions={READ_ONLY_ACTIONS}
             note={null}
             focusField={null}
-            result={
-              <StepResult
-                tenantId={tenantId}
-                runId={id}
-                summary={summary}
-                max={summary ? attemptsOf(summary) : null}
-                ended={ended}
-                several={summary && <p className="text-small">{tagsFor(summary).map((t) => t.text).join(" · ")}</p>}
-              />
-            }
+            result={resultOf(summary)}
             onAdd={nothing}
             onDelete={nothing}
             onConnectPort={nothing}
diff --git a/frontend/src/routes/runs/RunResult.tsx b/frontend/src/routes/runs/RunResult.tsx
index c21ecb32..21a25190 100644
--- a/frontend/src/routes/runs/RunResult.tsx
+++ b/frontend/src/routes/runs/RunResult.tsx
@@ -3,7 +3,8 @@
 // boards). An instance: its status, "attempt N of M" and its times; its error's code and message; its attempts, one row
 // each (at most 20, §4.4); the last attempt's input and its output, sensitive values redacted and long ones cut as the
 // server stored them, said in words (D20: never dots); and the run it started. Its attempts are read again while the
-// run runs. A step with no instance says why, in the canvas's words.
+// run runs. A step with no instance says why, in the canvas's words. A loop gives its iterations four at a time, with
+// Open; a step in a loop, one iteration at a time, picked from its first 50 or opened from the loop's list (4d-1c's).
 import { useQuery } from "@tanstack/react-query";
 import { Link } from "@tanstack/react-router";
 import { Fragment, useId, type ReactNode } from "react";
@@ -12,10 +13,16 @@ import { runAttemptsQuery, runQuery, type RunStep, type RunStepSummary } from ".
 import { RUN_STATUS, STEP_STATUS, runId, took } from "../../lib/runStatus";
 import { timeOf } from "../../lib/when";
 import { Chip, PreviewValue } from "../editor/drawer/PillDetails";
-import { ORIGIN } from "../editor/simulation/results";
+import { IterationPicker } from "../editor/simulation/IterationPicker";
+import { Iterations, type BodyStep } from "../editor/simulation/Iterations";
+import type { InstancePages } from "../editor/simulation/loopBody";
+import { ORIGIN, field } from "../editor/simulation/results";
 
 const READ_EVERY = 5000; // an open drawer's reads, while the run runs: with the summary
 const at = (iso: string) => timeOf(Date.parse(iso));
+/** When it ran: "09:41:20 to 09:41:50", one time when both are the same second, "since 09:41:20" while it runs. */
+const timesOf = (from: string | null, to: string | null) =>
+  from && to ? (at(from) === at(to) ? at(from) : `${at(from)} to ${at(to)}`) : from ? `since ${at(from)}` : null;
 const MARKS: Record<string, string> = { "[redacted]": "redacted", "[truncated]": "truncated" };
 
 export function Section({ title, children }: { title: string; children: ReactNode }) {
@@ -63,16 +70,17 @@ function SubRun({ tenantId, id }: { tenantId: string; id: string }) {
 
 /** One instance of a step, from its final attempt: as its attempts' read gives it once read, fresher while the run
  * runs; `max`: its attempts, its own or its type's. */
-export function InstanceResult({ tenantId, runId: id, step: final, max, ended }: {
-  tenantId: string; runId: string; step: RunStep; max: number | null; ended: boolean;
+export function InstanceResult({ tenantId, runId: id, step: final, max, ended, iteration }: {
+  tenantId: string; runId: string; step: RunStep; max: number | null; ended: boolean; iteration?: string;
 }) {  // prettier-ignore
   const attempts = useQuery({ ...runAttemptsQuery(tenantId, id, final.step_id, final.iteration_key), refetchInterval: ended ? false : READ_EVERY });
   const all = attempts.data?.items.length ? attempts.data.items : [final];
   const step = all.at(-1)!;
   const from = all[0]?.started_at ?? step.started_at;
   const to = step.ended_at;
-  const times = from && to ? (at(from) === at(to) ? at(from) : `${at(from)} to ${at(to)}`) : from ? `since ${at(from)}` : null;
-  const facts = [max ? `attempt ${step.attempt} of ${max}` : `attempt ${step.attempt}`, times, took(from, to)].filter(Boolean).join(" · ");
+  const facts = [
+    iteration && `iteration ${iteration}`, max ? `attempt ${step.attempt} of ${max}` : `attempt ${step.attempt}`, timesOf(from, to), took(from, to),
+  ].filter(Boolean).join(" · ");  // prettier-ignore
   const status = STEP_STATUS[step.status];
   return (
     <>
@@ -115,15 +123,72 @@ export function InstanceResult({ tenantId, runId: id, step: final, max, ended }:
   );
 }
 
-/** A step's result: its one instance, or why it has none; `summary` undefined when the run's steps don't name it. */
-export function StepResult({ tenantId, runId: id, summary, max, ended, several }: {
-  tenantId: string; runId: string; summary: RunStepSummary | undefined; max: number | null; ended: boolean; several: ReactNode;
+/** A loop that ran once: how many iterations and when, then its iterations, four at a time, once it has ended (a
+ * running loop's pages would move under the reader, 4d-1c ruling 4). */
+export function LoopResult({ summary, pages, body, onOpen }: {
+  summary: RunStepSummary; pages: InstancePages; body: BodyStep[]; onOpen: (stepId: string, iterationKey: string) => void;
 }) {  // prettier-ignore
-  if (!summary) return <p className="text-small text-muted">This run has no result for this step.</p>;
-  if (summary.instances === 0) {
+  const final = summary.final!;
+  const count = field(final.output, "count");
+  const status = STEP_STATUS[final.status];
+  const facts = [
+    typeof count === "number" && `${count} ${count === 1 ? "iteration" : "iterations"}`, timesOf(final.started_at, final.ended_at), took(final.started_at, final.ended_at),
+  ].filter(Boolean).join(" · ");  // prettier-ignore
+  return (
+    <>
+      <p className="flex flex-wrap items-center gap-2">
+        <ToneChip tone={status.tone}>{status.word}</ToneChip>
+        <span className="text-small text-muted">{facts}</span>
+      </p>
+      {final.error && (
+        <p className="rounded-lg border border-danger bg-danger-bg px-3 py-2 text-small">
+          <span className="font-mono text-danger">{final.error.code}</span>
+          {final.error.message && ` · ${final.error.message}`}
+        </p>
+      )}
+      <Section title="Iterations">
+        {final.status === "running" ? (
+          <p className="text-small text-muted">Its iterations are listed once it ends.</p>
+        ) : (
+          <Iterations pages={pages} loop={{ key: summary.key, prefix: final.iteration_key }} body={body} onOpen={onOpen} />
+        )}
+      </Section>
+    </>
+  );
+}
+
+/** A step that ran in a loop: its instances' totals, then one iteration at a time, picked once the run has ended;
+ * `loopKey`: the loop whose list opens any other. */
+export function SeveralResult({ tenantId, runId: id, summary, total, pages, loopKey, iteration, max, ended }: {
+  tenantId: string; runId: string; summary: RunStepSummary; total: string; pages: InstancePages; loopKey: string | null;
+  iteration: { key: string; n: number } | null; max: number | null; ended: boolean;
+}) {  // prettier-ignore
+  return (
+    <>
+      <p className="text-small">{total}</p>
+      {ended ? (
+        <IterationPicker
+          pages={pages}
+          stepId={summary.step_id}
+          iteration={iteration}
+          beyond={loopKey ? `Open any other from ${loopKey}'s list.` : undefined}
+          show={(item, n) => <InstanceResult tenantId={tenantId} runId={id} step={item as RunStep} max={max} ended={ended} iteration={n} />}
+        />
+      ) : (
+        <p className="text-small text-muted">Its iterations can be picked once the run ends.</p>
+      )}
+    </>
+  );
+}
+
+/** A step's result when it ran once, or why it has none; `summary` undefined when the run's steps don't name it. */
+export function StepResult({ tenantId, runId: id, summary, max, ended }: {
+  tenantId: string; runId: string; summary: RunStepSummary | undefined; max: number | null; ended: boolean;
+}) {  // prettier-ignore
+  if (!summary || (summary.instances > 0 && !summary.final)) return <p className="text-small text-muted">This run has no result for this step.</p>;
+  if (summary.instances === 0 || !summary.final) {
     const why = summary.origin === null ? "No result." : `${ORIGIN[summary.origin].charAt(0).toUpperCase()}${ORIGIN[summary.origin].slice(1)}.`;
     return <p className="text-small">{why}</p>;
   }
-  if (summary.instances === 1 && summary.final) return <InstanceResult tenantId={tenantId} runId={id} step={summary.final} max={max} ended={ended} />;
-  return several;
+  return <InstanceResult tenantId={tenantId} runId={id} step={summary.final} max={max} ended={ended} />;
 }
```

- [ ] **Step 4: Run them again**

Run: the same command.

Expected: PASS, 142 passed.

- [ ] **Step 5: Static checks**

Run: the two of "How to run things". Expected: no output.

- [ ] **Step 6: Commit, and the milestone**

```bash
git add frontend/src
git commit -m "feat(editor): a run's loop, its iterations four at a time, and a step in it picked one at a time (4e-1b)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

Append `### 4e-1b, milestone 2 (date)` to the ledger: the tasks' commits, each task's test counts as run, every
mid-slice ruling. Commit it (`docs(editor-4): 4e-1b milestone 2`). **Pause** for the owner's review.

---

# Milestone 3 — Cancel, other runs, the ways in

### Task 12: Cancel

**Spec:** §5.3 (cancel), §3's answer 7 (a live run asks first); the RunRunning board.

**Files:**
- Create: `frontend/src/routes/runs/useCancel.ts`
- Modify: `frontend/src/routes/runs/RunPage.tsx`, `frontend/src/routes/runs/RunPage.test.tsx`,
  `frontend/src/routes/runs/RunBar.tsx`
- Modify: `frontend/src/components/ConfirmDialog.tsx`, `frontend/src/components/ConfirmDialog.test.tsx`

**Interfaces:**
- Consumes: `cancelRun`, `canCancel`, `runQuery` (Task 3); `tenantQuery` (`lib/workflows.ts`); `RunBar`'s `children`
  (Task 9).
- Produces: `useCancel(tenantId, runId, live): { state, ask, send, keep }`; `RUN_TITLE`; `ConfirmDialog`'s `alert`.

"Cancel the run", for the roles that hold `run.cancel`, while it waits or runs. A live run asks first, in an alert
dialog: "Cancel this run? It stops at its next step. What it already did against Mist and its other connections isn't
undone." (Keep it running, Cancel the run). A simulation cancels at once. Then "Cancel requested" stands for the status,
with "It's shown as cancelled once the server confirms it.", until it does; a cancel that didn't go through says
"Couldn't cancel it. Try again."

- [ ] **Step 1: Write the failing tests**

Apply:

```diff
diff --git a/frontend/src/components/ConfirmDialog.test.tsx b/frontend/src/components/ConfirmDialog.test.tsx
index 4006f7b0..035a676c 100644
--- a/frontend/src/components/ConfirmDialog.test.tsx
+++ b/frontend/src/components/ConfirmDialog.test.tsx
@@ -95,3 +95,14 @@ it("asks afresh when its question changes while open: focus goes back to Cancel"
   rerender(ask("Publish version 2"));
   expect(document.activeElement).toBe(screen.getByRole("button", { name: "Cancel" }));
 });
+
+it("asks as an alert dialog when told, its words its description (a live run's cancel, the runs design §5.3)", () => {
+  render(
+    <ConfirmDialog open alert title="Cancel this run?" confirmLabel="Cancel the run" cancelLabel="Keep it running" onConfirm={vi.fn()} onCancel={vi.fn()}>
+      It stops at its next step.
+    </ConfirmDialog>,
+  );
+  const dialog = screen.getByRole("alertdialog", { name: "Cancel this run?" });
+  expect(document.getElementById(dialog.getAttribute("aria-describedby")!)!.textContent).toBe("It stops at its next step.");
+  expect(document.activeElement).toBe(screen.getByRole("button", { name: "Keep it running" }));
+});
diff --git a/frontend/src/routes/runs/RunPage.test.tsx b/frontend/src/routes/runs/RunPage.test.tsx
index fc3b4b52..b1cac82d 100644
--- a/frontend/src/routes/runs/RunPage.test.tsx
+++ b/frontend/src/routes/runs/RunPage.test.tsx
@@ -1,7 +1,7 @@
 // SPDX-License-Identifier: Apache-2.0
 import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
 import { RouterProvider, createMemoryHistory, createRootRoute, createRoute, createRouter } from "@tanstack/react-router";
-import { act, render, screen, within } from "@testing-library/react";
+import { act, cleanup, render, screen, within } from "@testing-library/react";
 import userEvent from "@testing-library/user-event";
 import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
 import { onAnnounce } from "../../lib/announce";
@@ -54,9 +54,12 @@ const VERSION = { id: "v2", number: 2, graph: FAILED_GRAPH, active: true, blocke
 
 let answers: Map<string, (url: URL) => Response>;
 let reads: string[];
+let role: string;
 
 beforeEach(() => {
+  role = "operator";
   answers = new Map([
+    ["/api/v1/t/t1", () => json({ id: "t1", name: "Acme Retail", slug: "acme-retail", require_passkey: false, role })()],
     ["/api/v1/node-types", json(RUN_TYPES)],
     ["/api/v1/t/t1/workflows/w1/versions/v2", json(VERSION)],
     [`/api/v1/t/t1/runs/${RUN.id}/steps`, json(FAILED_STEPS)],
@@ -436,3 +439,88 @@ describe("a loop (§5.3; the RunLoop board)", () => {
     expect(await within(side).findByRole("combobox", { name: "Iteration" })).toBeTruthy();
   });
 });
+
+describe("cancel (§5.3; the RunRunning board)", () => {
+  const RUN_PATH = `/api/v1/t/t1/runs/${RUN.id}`;
+  const CANCEL = `${RUN_PATH}/cancel`;
+  const running: Run = { ...RUN, status: "running", ended_at: null, error: null };
+  const requested = { cancel: "requested", request: { id: RUN.id, workflow_id: "w1", version_id: "v2", draft_snapshot_id: null, target_step_id: null,
+    mode: "live", source: "webhook", status: "started", reason: null, queued_at: RUN.queued_at, ended_at: null } };  // prettier-ignore
+  const posts = () => reads.filter((r) => r === CANCEL).length;
+
+  beforeEach(() => answers.set(RUN_PATH, json(running)));
+
+  it("asks before cancelling a live run, then says it's requested until the server confirms it", async () => {
+    const said: string[] = [];
+    const stop = onAnnounce((m) => said.push(m));
+    show();
+    await userEvent.click(await screen.findByRole("button", { name: "Cancel the run" }));
+    const ask = screen.getByRole("alertdialog", { name: "Cancel this run?" });
+    expect(within(ask).getByText("It stops at its next step. What it already did against Mist and its other connections isn't undone.")).toBeTruthy();
+    await userEvent.click(within(ask).getByRole("button", { name: "Keep it running" }));
+    expect(screen.queryByRole("alertdialog")).toBeNull();
+    expect(posts()).toBe(0);
+    answers.set(CANCEL, json(requested));
+    await userEvent.click(screen.getByRole("button", { name: "Cancel the run" }));
+    answers.set(RUN_PATH, json({ ...running, cancel_requested_at: local(10, 2, 20) }));
+    await userEvent.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "Cancel the run" }));
+    expect(await within(bar()).findByText("Cancel requested")).toBeTruthy();
+    expect(within(bar()).queryByText("Running")).toBeNull();
+    expect(screen.getByText("It's shown as cancelled once the server confirms it.")).toBeTruthy();
+    expect(screen.queryByRole("button", { name: "Cancel the run" })).toBeNull();
+    expect(posts()).toBe(1);
+    expect(said).toContain("Cancel requested. It's shown as cancelled once the server confirms it.");
+    stop();
+  });
+
+  it("cancels a simulated run at once, without asking", async () => {
+    answers.set(RUN_PATH, json({ ...running, mode: "simulate" }));
+    answers.set(CANCEL, json({ ...requested, request: { ...requested.request, mode: "simulate" } }));
+    show();
+    await userEvent.click(await screen.findByRole("button", { name: "Cancel the run" }));
+    expect(screen.queryByRole("alertdialog")).toBeNull();
+    await vi.waitFor(() => expect(posts()).toBe(1));
+  });
+
+  it("says when the cancel didn't go through, and offers it again", async () => {
+    answers.set(RUN_PATH, json({ ...running, mode: "simulate" }));
+    answers.set(CANCEL, json({ error: "internal_error" }, 500));
+    show();
+    await userEvent.click(await screen.findByRole("button", { name: "Cancel the run" }));
+    expect((await screen.findByRole("alert")).textContent).toBe("Couldn't cancel it. Try again.");
+    expect(screen.getByRole("button", { name: "Cancel the run" })).toBeTruthy();
+    expect(within(bar()).getByText("Running")).toBeTruthy();
+  });
+
+  it("offers no Cancel to a role without run.cancel, nor on a run that ended", async () => {
+    role = "viewer";
+    show();
+    await screen.findByRole("heading", { level: 1, name: "AP offline triage" });
+    await vi.waitFor(() => expect(reads).toContain("/api/v1/t/t1"));
+    expect(screen.queryByRole("button", { name: "Cancel the run" })).toBeNull();
+    cleanup();
+    role = "operator";
+    answers.set(RUN_PATH, json(RUN));
+    show();
+    await screen.findByRole("heading", { level: 1, name: "AP offline triage" });
+    await vi.waitFor(() => expect(reads.filter((r) => r === "/api/v1/t/t1")).toHaveLength(2));
+    expect(screen.queryByRole("button", { name: "Cancel the run" })).toBeNull();
+  });
+
+  it("reads a run cancelled while it waited as cancelled, never as a cancel requested", async () => {
+    const said: string[] = [];
+    const stop = onAnnounce((m) => said.push(m));
+    const queued: Run = { ...running, status: "queued", started_at: null, request: { status: "queued", source: "webhook", reason: null } };
+    answers.set(RUN_PATH, json(queued));
+    answers.set(CANCEL, json({ ...requested, cancel: "cancelled", request: { ...requested.request, status: "cancelled" } }));
+    show();
+    await userEvent.click(await screen.findByRole("button", { name: "Cancel the run" }));
+    answers.set(RUN_PATH, json({ ...queued, status: "cancelled", ended_at: local(10, 2, 20), request: { ...queued.request!, status: "cancelled" } }));
+    await userEvent.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "Cancel the run" }));
+    expect(await within(bar()).findByText("Cancelled")).toBeTruthy();
+    expect(screen.queryByText("Cancel requested")).toBeNull();
+    await vi.waitFor(() => expect(said).toContain("Run ended: cancelled"));
+    expect(said).not.toContain("Cancel requested. It's shown as cancelled once the server confirms it.");
+    stop();
+  });
+});
```

- [ ] **Step 2: Run them**

Run: `npx --offline pnpm@12.6.0 exec vitest run src/routes/runs/RunPage.test.tsx src/components/ConfirmDialog.test.tsx`

Expected: FAIL, 6 failed and 29 passed: there's no Cancel (`Unable to find role="button" and name "Cancel the run"`),
the tenant's role isn't read (`expected [ …(4) ] to include '/api/v1/t/t1'`), and the dialog isn't an alert dialog.

- [ ] **Step 3: Implement**

Apply:

```diff
diff --git a/frontend/src/components/ConfirmDialog.tsx b/frontend/src/components/ConfirmDialog.tsx
index d5a9c9b6..46656577 100644
--- a/frontend/src/components/ConfirmDialog.tsx
+++ b/frontend/src/components/ConfirmDialog.tsx
@@ -3,14 +3,16 @@
 // the page behind is inert, no injected styles: D23). Focus starts on Cancel, the safe choice. A constructive action
 // (publish, make active) confirms in the primary colour; focus still starts on Cancel, and goes back there when the
 // question changes. While its action runs (`busy`) it holds: Escape is refused and Cancel is off, so a cancel never
-// races the action it can't stop.
-import { useEffect, useRef, type ReactNode } from "react";
+// races the action it can't stop. One that warns of what can't be taken back (a live run's cancel) asks as an alert
+// dialog, its words its description.
+import { useEffect, useId, useRef, type ReactNode } from "react";
 import { Button } from "./Button";
 
 export function ConfirmDialog({
-  open, title, confirmLabel, cancelLabel = "Cancel", tone = "danger", busy = false, onConfirm, onCancel, children,
+  open, title, confirmLabel, cancelLabel = "Cancel", tone = "danger", busy = false, alert = false, onConfirm, onCancel, children,
 }: {
   open: boolean;
+  alert?: boolean;
   tone?: "danger" | "primary";
   title: string;
   confirmLabel: string;
@@ -23,6 +25,7 @@ export function ConfirmDialog({
   const dialog = useRef<HTMLDialogElement>(null);
   const cancel = useRef<HTMLButtonElement>(null);
   const closing = useRef(false); // set while the dialog closes because `open` turned false
+  const words = useId();
   useEffect(() => {
     const d = dialog.current;
     if (!d) return;
@@ -42,6 +45,8 @@ export function ConfirmDialog({
     <dialog
       ref={dialog}
       aria-label={title}
+      role={alert ? "alertdialog" : undefined}
+      aria-describedby={alert ? words : undefined}
       onCancel={(e) => {
         if (busy) e.preventDefault();
       }}
@@ -53,7 +58,7 @@ export function ConfirmDialog({
       className="mx-auto mt-24 w-[480px] max-w-[calc(100vw-32px)] rounded-dialog border border-line bg-surface p-6 text-ink shadow-dialog backdrop:bg-overlay"
     >
       <h2 className="text-h3 font-semibold">{title}</h2>
-      <div className="mt-2 text-body text-muted">{children}</div>
+      <div id={words} className="mt-2 text-body text-muted">{children}</div>
       <div className="mt-6 flex justify-end gap-2">
         <Button ref={cancel} onClick={onCancel} disabled={busy}>{cancelLabel}</Button>
         <Button variant={tone} onClick={onConfirm} disabled={busy}>{confirmLabel}</Button>
diff --git a/frontend/src/routes/runs/RunBar.tsx b/frontend/src/routes/runs/RunBar.tsx
index 61601a19..d649d111 100644
--- a/frontend/src/routes/runs/RunBar.tsx
+++ b/frontend/src/routes/runs/RunBar.tsx
@@ -2,18 +2,19 @@
 // A run's bar and banner (editor 4e-1; the runs design §5.3; the RunFailed, RunRunning and RunOther boards). The bar:
 // the way back to Runs, the workflow, the run's short id and Copy id, its status and what it was (live in orange,
 // D3; a simulation hatched, D2), its version or a draft's revision, its trigger, start and duration, and Open the
-// workflow ("Open in the editor" for a draft simulation). The banner says what a live run did, or what a simulation
-// proves, in the present while it runs.
+// workflow ("Open in the editor" for a draft simulation); a cancel asked for says so in place of its status. The
+// banner says what a live run did, or what a simulation proves, in the present while it runs.
 import { Link } from "@tanstack/react-router";
 import type { ReactNode } from "react";
 import { Button, LINK_BUTTON } from "../../components/Button";
-import { ModeChip, RunStatusChip } from "../../components/RunChips";
+import { ModeChip, RunStatusChip, ToneChip } from "../../components/RunChips";
 import { When } from "../../components/When";
 import { announce } from "../../lib/announce";
 import { isEnded, type Run } from "../../lib/runs";
 import { duration, runId } from "../../lib/runStatus";
 import { SimBanner } from "../editor/simulation/SimBanner";
 import { triggerWords } from "./trigger";
+import { RUN_TITLE } from "./useCancel";
 
 /** The run's facts in a line: "version 2 · webhook, Mist events · started today 09:41:12 · 38 s". */
 function Facts({ run, version }: { run: Run; version: number | null }) {
@@ -36,10 +37,10 @@ export function RunBar({ tenantId, run, version, children }: { tenantId: string;
   return (
     <div className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-line bg-surface px-5 py-2.5">
       <Link to="/t/$tenantId/runs" params={{ tenantId }} className="text-small text-muted hover:text-ink">← Runs</Link>
-      <h1 className="min-w-0 truncate text-body-lg font-semibold">{run.workflow_name ?? "—"}</h1>
+      <h1 id={RUN_TITLE} tabIndex={-1} className="min-w-0 truncate text-body-lg font-semibold">{run.workflow_name ?? "—"}</h1>
       <span className="font-mono text-small">{`run ${runId(run.id)}`}</span>
       <Button size="sm" onClick={() => void copy()}>Copy id</Button>
-      <RunStatusChip status={run.status} />
+      {run.cancel_requested_at && !isEnded(run.status) ? <ToneChip tone="running">Cancel requested</ToneChip> : <RunStatusChip status={run.status} />}
       <ModeChip mode={run.mode} draft={run.draft_snapshot_id !== null} />
       <Facts run={run} version={version} />
       {children}
diff --git a/frontend/src/routes/runs/RunPage.tsx b/frontend/src/routes/runs/RunPage.tsx
index ac50ebff..cac64aac 100644
--- a/frontend/src/routes/runs/RunPage.tsx
+++ b/frontend/src/routes/runs/RunPage.tsx
@@ -5,21 +5,22 @@
 // (useRunReads). A step's result opens in the editor's drawer, read only, its Result tab first; a failed run opens on
 // its failed step (the owner's answer 6), and Close gives focus back to its card. A run past its tenant's retention, or
 // an id that never was, is said to be neither, with Back to Runs; a run read while its tenant is erased says why it
-// can't be (§5.5).
+// can't be (§5.5). Cancel, for the roles that hold run.cancel, while it waits or runs (useCancel).
 import { useQuery, useQueryClient } from "@tanstack/react-query";
 import { Link } from "@tanstack/react-router";
 import { useCallback, useMemo, useState, type KeyboardEvent } from "react";
 import { Button, LINK_BUTTON } from "../../components/Button";
+import { ConfirmDialog } from "../../components/ConfirmDialog";
 import { When } from "../../components/When";
 import { ApiError } from "../../lib/client";
 import { findNode, idKey, nodesOf, portsOf, sameId } from "../../lib/graph";
-import { isEnded, runInstancesQuery, type RunStepSummary } from "../../lib/runs";
+import { canCancel, isEnded, runInstancesQuery, type RunStepSummary } from "../../lib/runs";
 import { runId } from "../../lib/runStatus";
 import { draftSnapshotQuery } from "../../lib/simulations";
 import { useDocumentTitle } from "../../lib/title";
 import { versionQuery } from "../../lib/triggers";
 import { timeOf } from "../../lib/when";
-import { nodeTypesQuery, type GraphDoc } from "../../lib/workflows";
+import { nodeTypesQuery, tenantQuery, type GraphDoc } from "../../lib/workflows";
 import { Canvas } from "../editor/Canvas";
 import { NAV_KEYS, type NavKey } from "../editor/canvasNav";
 import { READ_ONLY_ACTIONS } from "../editor/drawer/context";
@@ -32,6 +33,7 @@ import { useCanvasNav } from "../editor/useCanvasNav";
 import { RunBanner, RunBar } from "./RunBar";
 import { LoopResult, SeveralResult, StepResult } from "./RunResult";
 import { triggerOf, triggerWords } from "./trigger";
+import { useCancel } from "./useCancel";
 import { useRunReads } from "./useRunReads";
 
 /** Why a run couldn't be read: gone, the tenant's key gone during an erasure, or the read failed. */
@@ -68,6 +70,8 @@ export function RunPage({ tenantId, runId: id }: { tenantId: string; runId: stri
   const { run, steps } = useRunReads(tenantId, id);
   const r = run.data;
   const types = useQuery(nodeTypesQuery);
+  const tenant = useQuery(tenantQuery(tenantId));
+  const cancel = useCancel(tenantId, id, r?.mode === "live");
   // The graph it ran: its version's, or the draft a draft simulation froze for it. Neither ever changes.
   const version = useQuery({ ...versionQuery(tenantId, r?.workflow_id ?? "", r?.version_id ?? ""), enabled: !!r?.version_id });
   const snapshot = useQuery({ ...draftSnapshotQuery(tenantId, r?.workflow_id ?? "", r?.draft_snapshot_id ?? ""), enabled: !!r?.draft_snapshot_id });
@@ -144,7 +148,11 @@ export function RunPage({ tenantId, runId: id }: { tenantId: string; runId: stri
   }
   return (
     <div className="@container flex min-h-0 flex-1 flex-col">
-      <RunBar tenantId={tenantId} run={r} version={version.data?.number ?? null} />
+      <RunBar tenantId={tenantId} run={r} version={version.data?.number ?? null}>
+        {canCancel(tenant.data?.role) && !ended && !r.cancel_requested_at && (
+          <Button size="sm" variant="danger-outline" disabled={cancel.state === "sending"} onClick={cancel.ask}>Cancel the run</Button>
+        )}
+      </RunBar>
       <div className="flex flex-col gap-2 border-b border-line bg-surface px-5 py-2.5">
         {run.isRefetchError && (
           <p className="flex flex-wrap items-center gap-2 text-small text-muted">
@@ -153,6 +161,8 @@ export function RunPage({ tenantId, runId: id }: { tenantId: string; runId: stri
           </p>
         )}
         <RunBanner run={r} />
+        {r.cancel_requested_at && !ended && <p className="text-small">It&apos;s shown as cancelled once the server confirms it.</p>}
+        {cancel.state === "failed" && <p role="alert" className="text-small text-danger">Couldn&apos;t cancel it. Try again.</p>}
         {endedAt && steps.data && (
           <p className="text-small text-muted">
             {`Ended: ${endedWhat(r.status, steps.data.steps)} · `}
@@ -230,6 +240,18 @@ export function RunPage({ tenantId, runId: id }: { tenantId: string; runId: stri
           />
         )}
       </div>
+      <ConfirmDialog
+        open={cancel.state === "asking" || (cancel.state === "sending" && r.mode === "live")}
+        alert
+        title="Cancel this run?"
+        confirmLabel="Cancel the run"
+        cancelLabel="Keep it running"
+        busy={cancel.state === "sending"}
+        onConfirm={cancel.send}
+        onCancel={cancel.keep}
+      >
+        It stops at its next step. What it already did against Mist and its other connections isn&apos;t undone.
+      </ConfirmDialog>
     </div>
   );
 }
diff --git a/frontend/src/routes/runs/useCancel.ts b/frontend/src/routes/runs/useCancel.ts
new file mode 100644
index 00000000..01d0697e
--- /dev/null
+++ b/frontend/src/routes/runs/useCancel.ts
@@ -0,0 +1,35 @@
+// SPDX-License-Identifier: Apache-2.0
+// Cancelling a run (editor 4e-1; the runs design §5.3; the RunRunning board). A live run asks first: what it already
+// did isn't undone. A simulation cancels at once. Once sent, the run is read again: it says the cancel is requested
+// until the server confirms it, and focus goes to its name, the Cancel it was on gone. A cancel that didn't go through
+// says so, and is offered again.
+import { useQueryClient } from "@tanstack/react-query";
+import { useState } from "react";
+import { announce } from "../../lib/announce";
+import { cancelRun, runQuery } from "../../lib/runs";
+
+export const RUN_TITLE = "run-title"; // the bar's heading, where focus goes once a cancel is sent
+
+export function useCancel(tenantId: string, runId: string, live: boolean) {
+  const qc = useQueryClient();
+  const [state, setState] = useState<"idle" | "asking" | "sending" | "failed">("idle");
+  async function send() {
+    setState("sending");
+    try {
+      const answer = await cancelRun(tenantId, runId);
+      await qc.invalidateQueries({ queryKey: runQuery(tenantId, runId).queryKey });
+      setState("idle");
+      if (answer.cancel === "requested") announce("Cancel requested. It's shown as cancelled once the server confirms it.");
+      document.getElementById(RUN_TITLE)?.focus();
+    } catch {
+      setState("failed");
+    }
+  }
+  return {
+    state,
+    /** Asks first for a live run; a simulation's is sent at once. */
+    ask: () => (live ? setState("asking") : void send()),
+    send: () => void send(),
+    keep: () => setState("idle"),
+  };
+}
```

- [ ] **Step 4: Run them again**

Run: the same command.

Expected: PASS, 35 passed.

- [ ] **Step 5: Static checks**

Run: the two of "How to run things". Expected: no output.

- [ ] **Step 6: Commit**

```bash
git add frontend/src
git commit -m "feat(editor): cancel a run: a live one asks first, then cancel requested until the server confirms it (4e-1b)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 13: Runs that didn't run, an older run, and the Start drawer

**Spec:** §5.4; the RunOther board.

**Files:**
- Create: `frontend/src/routes/runs/StartDrawer.tsx`
- Modify: `frontend/src/routes/runs/RunPage.tsx`, `frontend/src/routes/runs/RunPage.test.tsx`,
  `frontend/src/routes/runs/RunResult.tsx`

**Interfaces:**
- Consumes: `runInputQuery` (Task 3); `reasonWords` (Task 2); `Section`, `Values` (Task 10, `Values` now exported);
  `triggerOf` (Task 9); `SIDE` (`routes/editor/side.ts`).
- Produces: `StartDrawer({ tenantId, run, onClose })`.

A request that never started shows its graph without tags, and its state in place of the banner: "Waiting to start ·
queued …. Nothing has run yet." (with Cancel), cancelled before it started, or why it couldn't start or was refused,
by its code and words. An older run says a step it didn't record shows "not recorded". The start card opens the Start
drawer: the trigger, who and when; the input as its request stored it, redacted, or why it isn't kept or can't be read
back; a CSV run's file.

- [ ] **Step 1: Write the failing tests**

Apply:

```diff
diff --git a/frontend/src/routes/runs/RunPage.test.tsx b/frontend/src/routes/runs/RunPage.test.tsx
index b1cac82d..c8a57b9c 100644
--- a/frontend/src/routes/runs/RunPage.test.tsx
+++ b/frontend/src/routes/runs/RunPage.test.tsx
@@ -524,3 +524,95 @@ describe("cancel (§5.3; the RunRunning board)", () => {
     stop();
   });
 });
+
+describe("runs that didn't run, and others (§5.4; the RunOther board)", () => {
+  const RUN_PATH = `/api/v1/t/t1/runs/${RUN.id}`;
+  const unstarted = (status: Run["status"], reason: string | null = null): Run => ({
+    ...RUN, status, started_at: null, ended_at: status === "queued" ? null : RUN.queued_at, error: null,
+    request: { status: status === "running" ? "started" : (status as "queued"), source: "webhook", reason },
+  });  // prettier-ignore
+  const notReached: RunSteps = { given: "input", steps: FAILED_STEPS.steps.map((s) => ({ ...s, origin: "not_reached_yet", instances: 0, statuses: {}, final: null })) };
+
+  it("says a run is waiting to start, its steps without tags, with Cancel", async () => {
+    answers.set(RUN_PATH, json(unstarted("queued")));
+    answers.set(`${RUN_PATH}/steps`, json(notReached));
+    show();
+    expect((await screen.findByText(/^Waiting to start/)).textContent).toBe("Waiting to start · queued today 09:41:12. Nothing has run yet.");
+    await vi.waitFor(() => expect(reads).toContain(`${RUN_PATH}/steps`));
+    await vi.waitFor(() => expect(canvas().dataset.results).toBe("[]"));
+    expect(screen.queryByRole("note")).toBeNull(); // nothing has acted yet
+    expect(await screen.findByRole("button", { name: "Cancel the run" })).toBeTruthy();
+  });
+
+  it("says why a run couldn't start, or was refused, by its code, and that nothing ran", async () => {
+    answers.set(RUN_PATH, json(unstarted("dead", "start_throttled")));
+    show();
+    expect((await screen.findByText(/^start_throttled/)).closest("p")!.textContent).toBe("start_throttled · Too many runs were starting at once. Nothing ran.");
+    expect(within(bar()).getByText("Couldn't start")).toBeTruthy();
+    cleanup();
+    answers.set(RUN_PATH, json(unstarted("refused", "input_invalid")));
+    show();
+    expect((await screen.findByText(/^input_invalid/)).closest("p")!.textContent).toBe("input_invalid · Its input didn't fit the workflow's input. Nothing ran.");
+    expect(screen.queryByRole("button", { name: "Cancel the run" })).toBeNull();
+  });
+
+  it("says an older run doesn't say how each step ended", async () => {
+    answers.set(RUN_PATH, json({ ...RUN, outcomes_recorded: false }));
+    show();
+    expect(await screen.findByText("This run is older than step-by-step results: a step it didn't record shows “not recorded”.")).toBeTruthy();
+  });
+
+  describe("its start (the Start drawer)", () => {
+    const byHand: Run = { ...RUN, started_by: "nadia@example.com", trigger: { source: "manual", schedule: null, endpoint: null, rerun_of: null } };
+    const start = () => within(canvas()).getByRole("button", { name: "Start: by hand, nadia@example.com. Open the run's start" });
+    beforeEach(() => answers.set(RUN_PATH, json(byHand)));
+
+    it("says who started it and when, and its input as its request stored it, redacted", async () => {
+      answers.set(`${RUN_PATH}/input`, json({ read_back: "kept", input: { org: "Acme Retail", api_token: "[redacted]" }, seeds: null }));
+      show();
+      await screen.findByRole("complementary", { name: "notify_noc" });
+      await userEvent.click(start());
+      const side = screen.getByRole("complementary", { name: "Start" });
+      await vi.waitFor(() => expect(document.activeElement).toBe(within(side).getByRole("heading", { name: "Start" })));
+      expect(within(side).getByText(/^By hand/).textContent).toBe("By hand · nadia@example.com · today 09:41:12");
+      const input = within(side).getByRole("region", { name: "Input" });
+      expect(await within(input).findByText("As the run's request stored it. Sensitive values are redacted.")).toBeTruthy();
+      expect(within(input).getAllByRole("definition").map((d) => d.textContent)).toEqual(['"Acme Retail"', "redacted"]);
+      expect(canvas().dataset.current).toBe("");
+      await userEvent.click(within(side).getByRole("button", { name: "Close" }));
+      expect(screen.queryByRole("complementary", { name: "Start" })).toBeNull();
+      await vi.waitFor(() => expect(document.activeElement).toBe(start()));
+    });
+
+    it("says when its input isn't kept any more, or can't be read back", async () => {
+      answers.set(`${RUN_PATH}/input`, json({ read_back: "absent", input: null, seeds: null }));
+      show();
+      await screen.findByRole("complementary", { name: "notify_noc" });
+      await userEvent.click(start());
+      expect(await screen.findByText("Its input isn't kept any more. The run's steps and results still are.")).toBeTruthy();
+      cleanup();
+      answers.set(`${RUN_PATH}/input`, json({ read_back: "unreadable", input: null, seeds: null }));
+      show();
+      await screen.findByRole("complementary", { name: "notify_noc" });
+      await userEvent.click(start());
+      expect(await screen.findByText("Its input can't be read back: it doesn't open, or the tenant's key is gone during an erasure.")).toBeTruthy();
+    });
+
+    it("shows a CSV run's file: the rows read, run and skipped, why each was skipped, and its columns", async () => {
+      answers.set(RUN_PATH, json({
+        ...byHand,
+        csv: { row_count: 50, headers: ["site_name", "country"], mapping: { name: "site_name", country_code: "country" },
+          skipped: [{ row: 7, code: "missing_value" }, { row: 19, code: "not_a_number" }], errors: [], error_count: 0 },
+      }));  // prettier-ignore
+      answers.set(`${RUN_PATH}/input`, json({ read_back: "kept", input: {}, seeds: null }));
+      show();
+      await screen.findByRole("complementary", { name: "notify_noc" });
+      await userEvent.click(start());
+      const file = await screen.findByRole("region", { name: "CSV file" });
+      expect(within(file).getAllByRole("term").map((d) => d.textContent)).toEqual(["Rows", "Skipped", "Columns"]);
+      expect(within(file).getAllByRole("definition").map((d) => d.textContent)).toEqual([
+        "50 read · 48 run · 2 skipped", "row 7 missing_value · row 19 not_a_number", "site_name → name, country → country_code",
+      ]);  // prettier-ignore
+    });
+  });
+});
```

- [ ] **Step 2: Run them**

Run: `npx --offline pnpm@12.6.0 exec vitest run src/routes/runs/RunPage.test.tsx`

Expected: FAIL, 6 failed and 27 passed: a request that never started has no words of its own (`/^Waiting to start/`,
`/^start_throttled/`), an older run says nothing of it, and the start card opens nothing (no "Start" drawer, no "CSV
file").

- [ ] **Step 3: Implement**

Apply:

```diff
diff --git a/frontend/src/routes/runs/RunPage.tsx b/frontend/src/routes/runs/RunPage.tsx
index cac64aac..e8c19f9c 100644
--- a/frontend/src/routes/runs/RunPage.tsx
+++ b/frontend/src/routes/runs/RunPage.tsx
@@ -13,9 +13,9 @@ import { Button, LINK_BUTTON } from "../../components/Button";
 import { ConfirmDialog } from "../../components/ConfirmDialog";
 import { When } from "../../components/When";
 import { ApiError } from "../../lib/client";
-import { findNode, idKey, nodesOf, portsOf, sameId } from "../../lib/graph";
-import { canCancel, isEnded, runInstancesQuery, type RunStepSummary } from "../../lib/runs";
-import { runId } from "../../lib/runStatus";
+import { START, findNode, idKey, nodesOf, portsOf, sameId } from "../../lib/graph";
+import { canCancel, isEnded, runInstancesQuery, type Run, type RunStepSummary } from "../../lib/runs";
+import { reasonWords, runId } from "../../lib/runStatus";
 import { draftSnapshotQuery } from "../../lib/simulations";
 import { useDocumentTitle } from "../../lib/title";
 import { versionQuery } from "../../lib/triggers";
@@ -32,6 +32,7 @@ import { tagsOf, type SimTag } from "../editor/simulation/results";
 import { useCanvasNav } from "../editor/useCanvasNav";
 import { RunBanner, RunBar } from "./RunBar";
 import { LoopResult, SeveralResult, StepResult } from "./RunResult";
+import { StartDrawer } from "./StartDrawer";
 import { triggerOf, triggerWords } from "./trigger";
 import { useCancel } from "./useCancel";
 import { useRunReads } from "./useRunReads";
@@ -60,6 +61,29 @@ function Unread({ tenantId, id, error, retry }: { tenantId: string; id: string;
   );
 }
 
+/** What a request that never started says in place of a run's banner (§5.4): waiting, cancelled before it started, or
+ * why it couldn't start or was refused, by its code and words. Nothing ran. */
+function Unstarted({ run }: { run: Run }) {
+  if (run.status === "refused" || run.status === "dead") {
+    const code = run.request?.reason ?? null;
+    const words = reasonWords(code);
+    return (
+      <p className="rounded-lg border border-danger bg-danger-bg px-3 py-2 text-small">
+        {code && <span className="font-mono text-danger">{code}</span>}
+        {`${code ? " · " : ""}${words ? `${words} ` : ""}Nothing ran.`}
+      </p>
+    );
+  }
+  const waiting = run.status === "queued" || run.status === "starting";
+  return (
+    <p className="text-small">
+      {waiting ? "Waiting to start" : "Cancelled before it started"}
+      {run.queued_at && <> · queued <When iso={run.queued_at} /></>}
+      {waiting ? ". Nothing has run yet." : ". Nothing ran."}
+    </p>
+  );
+}
+
 const NONE: GraphDoc = { graph_format: 1, nodes: [], edges: [] };
 const NO_STEPS: ReadonlySet<string> = new Set();
 const NO_PROBLEMS = new Map();
@@ -127,6 +151,8 @@ export function RunPage({ tenantId, runId: id }: { tenantId: string; runId: stri
     setOpen(stepId);
     setIteration((i) => ({ key, n: (i?.n ?? 0) + 1 }));
   };
+  // A request that never started shows its graph without tags: nothing ran (§5.4).
+  const unstarted = r.request !== null && r.request.status !== "started";
   // A step's result: a loop that ran once, its iterations; a step in a loop, its instances one at a time; else its one
   // instance, or why it has none.
   function resultOf(summary: RunStepSummary | undefined) {
@@ -160,7 +186,10 @@ export function RunPage({ tenantId, runId: id }: { tenantId: string; runId: stri
             <Button size="sm" onClick={() => void run.refetch()}>Try again</Button>
           </p>
         )}
-        <RunBanner run={r} />
+        {unstarted ? <Unstarted run={r} /> : <RunBanner run={r} />}
+        {!unstarted && !r.outcomes_recorded && (
+          <p className="text-small">This run is older than step-by-step results: a step it didn&apos;t record shows “not recorded”.</p>
+        )}
         {r.cancel_requested_at && !ended && <p className="text-small">It&apos;s shown as cancelled once the server confirms it.</p>}
         {cancel.state === "failed" && <p role="alert" className="text-small text-danger">Couldn&apos;t cancel it. Try again.</p>}
         {endedAt && steps.data && (
@@ -197,19 +226,29 @@ export function RunPage({ tenantId, runId: id }: { tenantId: string; runId: stri
               onKeyDown={onCanvasKey}
               placing={false}
               onPlace={nothing}
-              overview={!node}
+              overview={!node && open !== START}
               start={{
                 summary: trigger.words ? `${trigger.kind} · ${trigger.words}` : trigger.kind,
                 label: `Start: ${triggerWords(r)}. Open the run's start`,
-                open: false,
-                onOpen: nothing,
-                tags: given,
+                open: open === START,
+                onOpen: () => setOpen(open === START ? null : START),
+                tags: unstarted ? undefined : given,
               }}
-              results={results}
+              results={unstarted ? undefined : results}
               resultsLabel="result"
             />
           )}
         </div>
+        {open === START && (
+          <StartDrawer
+            tenantId={tenantId}
+            run={r}
+            onClose={() => {
+              setOpen(null);
+              keys.focus(item.start);
+            }}
+          />
+        )}
         {node && graph && (
           <StepDrawer
             key={idKey(node.id)}
diff --git a/frontend/src/routes/runs/RunResult.tsx b/frontend/src/routes/runs/RunResult.tsx
index 21a25190..074dc4fb 100644
--- a/frontend/src/routes/runs/RunResult.tsx
+++ b/frontend/src/routes/runs/RunResult.tsx
@@ -36,7 +36,7 @@ export function Section({ title, children }: { title: string; children: ReactNod
 }
 
 /** A preview as the server stored it: an object as its keys and values, a value wholly redacted or cut as its mark. */
-function Values({ value, none }: { value: unknown; none: string }) {
+export function Values({ value, none }: { value: unknown; none: string }) {
   const one = (v: unknown) => (typeof v === "string" && MARKS[v] ? <Chip>{MARKS[v]}</Chip> : <PreviewValue value={v} />);
   if (value === null || value === undefined) return <p className="text-small text-muted">{none}</p>;
   if (typeof value !== "object" || Array.isArray(value)) return <p className="text-small break-words">{one(value)}</p>;
diff --git a/frontend/src/routes/runs/StartDrawer.tsx b/frontend/src/routes/runs/StartDrawer.tsx
new file mode 100644
index 00000000..4787a0f3
--- /dev/null
+++ b/frontend/src/routes/runs/StartDrawer.tsx
@@ -0,0 +1,87 @@
+// SPDX-License-Identifier: Apache-2.0
+// A run's start, opened from its start card (editor 4e-1; the runs design §5.4; the RunOther board), in the editor's
+// side drawer: what started it, who and when; its input as its request stored it, read back, sensitive values redacted
+// (`absent` once its tenant's retention dropped it, `unreadable` when it doesn't open); a step test's values; and a CSV
+// run's file: the rows read, run and skipped, why each skipped row was (the first 100), and the columns it mapped. Its
+// heading takes focus as it opens; Escape closes it as Close does.
+import { useQuery } from "@tanstack/react-query";
+import { useEffect, useId, useRef } from "react";
+import { Button } from "../../components/Button";
+import { When } from "../../components/When";
+import { runInputQuery, type Run } from "../../lib/runs";
+import { SIDE } from "../editor/side";
+import { Section, Values } from "./RunResult";
+import { triggerOf } from "./trigger";
+
+const SKIPPED = 100; // the skipped rows listed
+
+function Input({ tenantId, run }: { tenantId: string; run: Run }) {
+  const read = useQuery(runInputQuery(tenantId, run.id));
+  if (read.isPending) return <p className="text-small text-muted">Reading its input…</p>;
+  if (read.isError) return <p className="text-small text-muted">Its input couldn&apos;t be read.</p>;
+  const { read_back: kept, input, seeds } = read.data;
+  if (kept === "absent") return <p className="text-small">Its input isn&apos;t kept any more. The run&apos;s steps and results still are.</p>;
+  if (kept === "unreadable") return <p className="text-small">Its input can&apos;t be read back: it doesn&apos;t open, or the tenant&apos;s key is gone during an erasure.</p>;
+  return (
+    <>
+      <p className="text-small text-muted">As the run&apos;s request stored it. Sensitive values are redacted.</p>
+      {seeds ? <Values value={seeds} none="None." /> : <Values value={input} none="None." />}
+    </>
+  );
+}
+
+function CsvFile({ csv }: { csv: NonNullable<Run["csv"]> }) {
+  const listed = csv.skipped.slice(0, SKIPPED).map((s) => `row ${s.row} ${s.code}`);
+  const more = csv.skipped.length - listed.length;
+  return (
+    <Section title="CSV file">
+      <dl className="grid grid-cols-[minmax(0,6rem)_minmax(0,1fr)] gap-x-3 gap-y-1 text-small">
+        <dt>Rows</dt>
+        <dd>{`${csv.row_count} read · ${csv.row_count - csv.skipped.length} run · ${csv.skipped.length} skipped`}</dd>
+        {listed.length > 0 && (
+          <>
+            <dt>Skipped</dt>
+            <dd className="font-mono">{`${listed.join(" · ")}${more > 0 ? ` · ${more} more` : ""}`}</dd>
+          </>
+        )}
+        <dt>Columns</dt>
+        <dd>{Object.entries(csv.mapping).map(([column, header]) => `${header} → ${column}`).join(", ")}</dd>
+      </dl>
+    </Section>
+  );
+}
+
+export function StartDrawer({ tenantId, run, onClose }: { tenantId: string; run: Run; onClose: () => void }) {
+  const title = useId();
+  const heading = useRef<HTMLHeadingElement>(null);
+  useEffect(() => heading.current?.focus(), []);
+  const trigger = triggerOf(run);
+  return (
+    <aside
+      aria-labelledby={title}
+      onKeyDown={(e) => {
+        if (e.key === "Escape") {
+          e.stopPropagation();
+          onClose();
+        }
+      }}
+      className={`${SIDE} gap-5`}
+    >
+      <div className="flex items-start justify-between gap-3">
+        <div className="flex min-w-0 flex-col gap-1">
+          <h2 id={title} ref={heading} tabIndex={-1} className="text-body-lg font-semibold">Start</h2>
+          <p className="text-small text-muted">
+            {trigger.kind}
+            {trigger.detail && <> · {trigger.detail}</>}
+            {run.queued_at && <> · <When iso={run.queued_at} /></>}
+          </p>
+        </div>
+        <Button size="sm" onClick={onClose}>Close</Button>
+      </div>
+      <Section title="Input">
+        <Input tenantId={tenantId} run={run} />
+      </Section>
+      {run.csv && <CsvFile csv={run.csv} />}
+    </aside>
+  );
+}
```

- [ ] **Step 4: Run them again**

Run: the same command.

Expected: PASS, 33 passed.

- [ ] **Step 5: Static checks**

Run: the two of "How to run things". Expected: no output.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/routes/runs
git commit -m "feat(editor): runs that didn't run, an older run, and a run's start: its input read back, a CSV's file (4e-1b)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 14: The ways in

**Spec:** §5.1 (the entry points: the toolbar's Runs, the Workflows list's last run, the Simulation panel's run id).

**Files:**
- Modify: `frontend/src/routes/editor/Editor.tsx`, `frontend/src/routes/editor/Editor.test.tsx`
- Modify: `frontend/src/routes/editor/simulation/SimulationPanel.tsx`,
  `frontend/src/routes/editor/simulation/SimulationPanel.test.tsx`
- Modify: `frontend/src/routes/Workflows.tsx`, `frontend/src/routes/Workflows.test.tsx`,
  `frontend/src/components/Button.tsx`

**Interfaces:**
- Consumes: the routes (Task 4); `runId` (Task 2); `LastRunOut.id` (4e-1a).
- Produces: `LINK_BUTTON_MD`; `SimulationPanel`'s `runOf?: (id) => ReactNode` (ruling 29).

The editor's toolbar links to the workflow's runs, filtered to it; the Workflows list's last run and last simulation
link to their pages; the Simulation panel's run id links to its run's page.

- [ ] **Step 1: Write the failing tests**

Apply:

```diff
diff --git a/frontend/src/routes/Workflows.test.tsx b/frontend/src/routes/Workflows.test.tsx
index 7536a091..a2c8c16c 100644
--- a/frontend/src/routes/Workflows.test.tsx
+++ b/frontend/src/routes/Workflows.test.tsx
@@ -10,13 +10,13 @@ const NOW = Date.parse("2026-10-06T12:00:00Z");
 const row = (over: Record<string, unknown>) => ({
   id: "w1", name: "Nightly", enabled: true, draft_revision: 3, active_version_id: "v2", active_version_number: 2,
   executable: true, blocked_by: [], created_at: "2026-10-01T00:00:00Z", updated_at: "2026-10-06T10:00:00Z",
-  unpublished_changes: false, last_run: { status: "succeeded", at: "2026-10-06T11:48:00Z" }, last_simulation: null,
+  unpublished_changes: false, last_run: { id: "run-nightly", status: "succeeded", at: "2026-10-06T11:48:00Z" }, last_simulation: null,
   runs_24h: { live: 4, simulate: 0 }, needs_attention: [], triggers: { schedules: 0, schedules_enabled: 0, webhook_bindings: 0, csv: false }, ...over,
 });  // prettier-ignore
 const ROWS = [
   row({}),
   row({ id: "w2", name: "Triage", enabled: false, unpublished_changes: true, runs_24h: { live: 1, simulate: 2 },
-        last_run: { status: "failed", at: "2026-10-06T11:00:00Z" }, last_simulation: { status: "succeeded", at: "2026-10-06T11:30:00Z" },
+        last_run: { id: "run-triage", status: "failed", at: "2026-10-06T11:00:00Z" }, last_simulation: { id: "sim-triage", status: "succeeded", at: "2026-10-06T11:30:00Z" },
         needs_attention: ["last_run_failed"] }),
   row({ id: "w3", name: "Sketch", active_version_id: null, active_version_number: null, executable: null,
         unpublished_changes: true, last_run: null, runs_24h: { live: 0, simulate: 0 } }),
@@ -50,7 +50,8 @@ beforeEach(() => {
 async function show({ startNew = false } = {}) {
   const root = createRootRoute({ component: () => <WorkflowsPage tenantId="t1" startNew={startNew} /> });
   const editor = createRoute({ getParentRoute: () => root, path: "/t/$tenantId/workflows/$workflowId", component: () => <p>editor</p> });
-  const router = createRouter({ routeTree: root.addChildren([editor]), history: createMemoryHistory({ initialEntries: ["/"] }) });
+  const run = createRoute({ getParentRoute: () => root, path: "/t/$tenantId/runs/$runId", component: () => <p>a run</p> });
+  const router = createRouter({ routeTree: root.addChildren([editor, run]), history: createMemoryHistory({ initialEntries: ["/"] }) });
   render(
     <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
       <RouterProvider router={router} />
@@ -61,6 +62,8 @@ async function show({ startNew = false } = {}) {
 }
 
 const rowOf = (name: string) => screen.getByRole("link", { name }).closest("tr")!;
+/** The workflows listed, by the name link in each row's first cell. */
+const names = () => screen.getAllByRole("row").slice(1).map((r) => r.querySelector("td a")?.textContent);
 
 it("shows each workflow's version, last run and last 24 hours in words", async () => {
   await show();
@@ -81,13 +84,13 @@ it("filters by state, with counts, and by name", async () => {
     "All 3", "Published 2", "Unpublished changes 2", "Needs attention 1",
   ]);  // prettier-ignore
   await userEvent.click(within(filters).getByRole("button", { name: "Unpublished changes 2" }));
-  expect(screen.getAllByRole("link").map((l) => l.textContent)).toEqual(["Triage", "Sketch"]); // never published counts
+  expect(names()).toEqual(["Triage", "Sketch"]); // never published counts
   await userEvent.click(within(filters).getByRole("button", { name: "Needs attention 1" }));
   expect(screen.queryByRole("link", { name: "Nightly" })).toBeNull();
   expect(screen.getByRole("link", { name: "Triage" })).toBeTruthy();
   await userEvent.click(within(filters).getByRole("button", { name: "All 3" }));
   await userEvent.type(screen.getByLabelText("Filter by name"), "sk");
-  expect(screen.getAllByRole("link").map((l) => l.textContent)).toEqual(["Sketch"]);
+  expect(names()).toEqual(["Sketch"]);
 });
 
 it("lets a publisher switch a workflow off, and says why one can't be switched on", async () => {
@@ -180,3 +183,9 @@ it("names what starts each workflow besides a person, and says why one needs att
   expect(rowOf("Audit").cells[0]!.textContent).toContain("Needs attention: a schedule couldn't be synced.");
   expect(rowOf("Rename").cells[1]!.textContent).toBe("CSV file");
 });
+
+it("links each workflow's last run, and its last simulation, to their pages (the runs design §5.1)", async () => {
+  await show();
+  expect(within(rowOf("Triage")).getByRole("link", { name: "Failed · 1 h ago" }).getAttribute("href")).toBe("/t/t1/runs/run-triage");
+  expect(within(rowOf("Triage")).getByRole("link", { name: "Simulated: Succeeded · 30 min ago" }).getAttribute("href")).toBe("/t/t1/runs/sim-triage");
+});
diff --git a/frontend/src/routes/editor/Editor.test.tsx b/frontend/src/routes/editor/Editor.test.tsx
index ef4a5783..f94d9f81 100644
--- a/frontend/src/routes/editor/Editor.test.tsx
+++ b/frontend/src/routes/editor/Editor.test.tsx
@@ -130,8 +130,10 @@ async function show({ seed, at = "/t/t1/workflows/w1" }: { seed?: (qc: QueryClie
       throw redirect({ to: "/t/$tenantId/workflows/$workflowId", params: { tenantId: "t1", workflowId: "w1" } });
     },
   });
+  const runs = createRoute({ getParentRoute: () => root, path: "/t/$tenantId/runs", component: () => <p>runs</p> });
+  const run = createRoute({ getParentRoute: () => root, path: "/t/$tenantId/runs/$runId", component: () => <p>a run</p> });
   const router = createRouter({
-    routeTree: root.addChildren([list, editor, away]),
+    routeTree: root.addChildren([list, editor, away, runs, run]),
     history: createMemoryHistory({ initialEntries: [at] }),
   });
   const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
@@ -2444,3 +2446,26 @@ describe("Simulate workflow", () => {
     expect(await screen.findByRole("button", { name: "◌ Simulate workflow" })).toBeTruthy();
   });
 });
+
+describe("the runs, from the editor (the runs design §5.1)", () => {
+  it("links to the workflow's runs from the toolbar, its filter set", async () => {
+    await show();
+    expect(screen.getByRole("link", { name: "Runs" }).getAttribute("href")).toBe("/t/t1/runs?workflow=w1");
+  });
+
+  it("links the latest simulation's run to its page, from the Simulation panel", async () => {
+    const SIM = `${BASE}/draft/simulations`;
+    const request = { id: "7c1e9a40-0000-4000-8000-000000000000", workflow_id: "w1", version_id: null, draft_snapshot_id: "s1", draft_revision: 1, target_step_id: null, mode: "simulate", source: "manual", status: "started", reason: null, queued_at: "2026-10-15T10:42:05Z", ended_at: null, admission_checks: [] };
+    const run = { status: "succeeded", queued_at: null, started_at: "2026-10-15T10:42:05Z", ended_at: "2026-10-15T10:42:06Z", error: null, iterations: 0 };
+    answers.set(`GET ${BASE}`, () => json({ ...WORKFLOW, draft: draftWith("transform") }));
+    answers.set(`GET ${SIM}`, () => json([request]));
+    answers.set(`GET ${SIM}/${request.id}`, () => json({ request, run, cancel_requested: false, read_back: "kept", input: {}, seeds: null }));
+    answers.set(`GET ${SIM}/${request.id}/steps`, () => json({ given: "input", steps: [] }));
+    const { router } = await show();
+    await screen.findByRole("button", { name: "Hide the result" });
+    await userEvent.click(screen.getByRole("button", { name: "Simulation" }));
+    const panel = await screen.findByRole("complementary", { name: "Simulation" });
+    await userEvent.click(within(panel).getByRole("link", { name: "run 7c1e9a40" }));
+    await vi.waitFor(() => expect(router.state.location.pathname).toBe(`/t/t1/runs/${request.id}`));
+  });
+});
diff --git a/frontend/src/routes/editor/simulation/SimulationPanel.test.tsx b/frontend/src/routes/editor/simulation/SimulationPanel.test.tsx
index 766fb84e..6f66fc5c 100644
--- a/frontend/src/routes/editor/simulation/SimulationPanel.test.tsx
+++ b/frontend/src/routes/editor/simulation/SimulationPanel.test.tsx
@@ -122,3 +122,15 @@ describe("the Simulation panel's lifecycle (§7.2; the Lifecycle and Running boa
     expect(onClose).toHaveBeenCalledTimes(2);
   });
 });
+
+it("links its run to the run's page when it's given one (the runs design §5.1)", () => {
+  render(
+    <SimulationPanel
+      session={admitted("started", run("succeeded", "2026-10-15T10:42:19Z"), { phase: "succeeded" })}
+      onClose={vi.fn()}
+      runOf={(id) => <a href={`/runs/${id}`}>{`run ${id.slice(0, 8)}`}</a>}
+    />,
+  );
+  expect(screen.getByRole("link", { name: "run 7c1e9a40" }).getAttribute("href")).toBe(`/runs/${ID}`);
+  expect(screen.getByText(/^Ended: /).textContent).toMatch(/ · draft revision 14 · run 7c1e9a40$/);
+});
```

- [ ] **Step 2: Run them**

Run: `npx --offline pnpm@12.6.0 exec vitest run src/routes/Workflows.test.tsx
src/routes/editor/simulation/SimulationPanel.test.tsx src/routes/editor/Editor.test.tsx`

Expected: FAIL, 4 failed and 184 passed: the toolbar has no "Runs" link, "Failed · 1 h ago" isn't a link, and the
panel's run isn't one ("run 7c1e9a40").

- [ ] **Step 3: Implement**

Apply:

```diff
diff --git a/frontend/src/components/Button.tsx b/frontend/src/components/Button.tsx
index 64df182f..c5d8d18b 100644
--- a/frontend/src/components/Button.tsx
+++ b/frontend/src/components/Button.tsx
@@ -41,10 +41,11 @@ const SIZES = {
 
 const DISABLED = "disabled:bg-disabled-bg disabled:border-disabled-line disabled:text-disabled-ink";
 
+const LINK = "inline-flex items-center justify-center gap-2 rounded-lg border border-line-strong bg-surface font-medium text-ink hover:bg-surface-hover active:bg-surface-pressed";
 /** A link that looks like a small secondary button: an action that goes to another page ("Back to Runs"). */
-export const LINK_BUTTON =
-  "inline-flex min-h-8 items-center justify-center gap-2 rounded-lg border border-line-strong bg-surface px-3 text-small " +
-  "font-medium text-ink hover:bg-surface-hover active:bg-surface-pressed";
+export const LINK_BUTTON = `${LINK} ${SIZES.sm}`;
+/** The same at a toolbar's size (the editor's Runs). */
+export const LINK_BUTTON_MD = `${LINK} ${SIZES.md}`;
 
 export function Button({
   variant = "secondary",
diff --git a/frontend/src/routes/Workflows.tsx b/frontend/src/routes/Workflows.tsx
index 3c1ca80d..e53a4bf7 100644
--- a/frontend/src/routes/Workflows.tsx
+++ b/frontend/src/routes/Workflows.tsx
@@ -44,8 +44,9 @@ function Version({ w }: { w: WorkflowRow }) {
   );
 }
 
-/** The last live run, what attention follows; the last simulation apart, in the simulation colour (4b ruling 7). */
-function LastRun({ w }: { w: WorkflowRow }) {
+/** The last live run, what attention follows; the last simulation apart, in the simulation colour (4b ruling 7). Each
+ * links to its run's page (the runs design §5.1). */
+function LastRun({ tenantId, w }: { tenantId: string; w: WorkflowRow }) {
   const live = w.last_run;
   const simulated = w.last_simulation;
   if (!live && !simulated) return <span className="text-muted">No runs yet</span>;
@@ -54,12 +55,18 @@ function LastRun({ w }: { w: WorkflowRow }) {
       {live ? (
         <span className="inline-flex items-center gap-2">
           <span aria-hidden="true" className={`size-2 rounded-sm ${DOT[RUN_STATUS[live.status].tone]}`} />
-          {RUN_STATUS[live.status].word} · {since(live.at)}
+          <Link to="/t/$tenantId/runs/$runId" params={{ tenantId, runId: live.id }} className="underline underline-offset-2">
+            {RUN_STATUS[live.status].word} · {since(live.at)}
+          </Link>
         </span>
       ) : (
         <span className="text-muted">No live runs yet</span>
       )}
-      {simulated && <span className="text-sim">Simulated: {RUN_STATUS[simulated.status].word} · {since(simulated.at)}</span>}
+      {simulated && (
+        <Link to="/t/$tenantId/runs/$runId" params={{ tenantId, runId: simulated.id }} className="text-sim underline underline-offset-2">
+          Simulated: {RUN_STATUS[simulated.status].word} · {since(simulated.at)}
+        </Link>
+      )}
     </span>
   );
 }
@@ -175,7 +182,7 @@ export function WorkflowsPage({ tenantId, startNew = false }: { tenantId: string
                 </Td>
                 <Td className="text-small">{triggerColumn(w.triggers)}</Td>
                 <Td><Version w={w} /></Td>
-                <Td><LastRun w={w} /></Td>
+                <Td><LastRun tenantId={tenantId} w={w} /></Td>
                 <Td className="font-mono text-small">
                   {w.runs_24h.live}
                   {w.runs_24h.simulate > 0 && <span className="font-sans text-sim"> +{w.runs_24h.simulate} simulated</span>}
diff --git a/frontend/src/routes/editor/Editor.tsx b/frontend/src/routes/editor/Editor.tsx
index e10bbfce..91cbd78a 100644
--- a/frontend/src/routes/editor/Editor.tsx
+++ b/frontend/src/routes/editor/Editor.tsx
@@ -2,9 +2,9 @@
 // The editor (screen 1c): the draft, on a canvas, by pointer or keyboard alone (D16), saved as it changes (D17). Task 14
 // adds problems, Task 15 publishing and versions.
 import { useQuery, useQueryClient } from "@tanstack/react-query";
-import { useBlocker, useMatch, useRouter } from "@tanstack/react-router";
+import { Link, useBlocker, useMatch, useRouter } from "@tanstack/react-router";
 import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
-import { Button } from "../../components/Button";
+import { Button, LINK_BUTTON_MD } from "../../components/Button";
 import { ConfirmDialog } from "../../components/ConfirmDialog";
 import { LoadError } from "../../components/LoadError";
 import { announce } from "../../lib/announce";
@@ -20,6 +20,7 @@ import {
 import { begin, record, redo, undo, type History } from "../../lib/history";
 import { CARD, layout } from "../../lib/layout";
 import { guardLeaving } from "../../lib/leaving";
+import { runId } from "../../lib/runStatus";
 import type { Path } from "../../lib/schemaForm";
 import { ENDED, draftSnapshotQuery, freeze, type StepSummary } from "../../lib/simulations";
 import { useDocumentTitle } from "../../lib/title";
@@ -1210,6 +1211,7 @@ function Editor({
         <Button ref={versionsButton} size="md" aria-expanded={side?.kind === "versions"} onClick={() => setSide(side?.kind === "versions" ? null : { kind: "versions" })}>
           Versions
         </Button>
+        <Link to="/t/$tenantId/runs" params={{ tenantId }} search={{ workflow: workflow.id }} className={LINK_BUTTON_MD}>Runs</Link>
         <Button size="md" onClick={() => void exportFile()}>Export</Button>
         {simulator && (
           <Button
@@ -1480,6 +1482,11 @@ function Editor({
         {side?.kind === "simulation" && (
           <SimulationPanel
             session={simulation}
+            runOf={(id) => (
+              <Link to="/t/$tenantId/runs/$runId" params={{ tenantId, runId: id }} className="underline underline-offset-2">
+                {`run ${runId(id)}`}
+              </Link>
+            )}
             onSimulateAgain={simulator && sync.status !== "conflict" && !simulation.busy ? () => whenSettled("simulate", () => void simulate()) : undefined}
             onClose={() => {
               setSide(null);
diff --git a/frontend/src/routes/editor/simulation/SimulationPanel.tsx b/frontend/src/routes/editor/simulation/SimulationPanel.tsx
index 0dcfe20f..165b00d8 100644
--- a/frontend/src/routes/editor/simulation/SimulationPanel.tsx
+++ b/frontend/src/routes/editor/simulation/SimulationPanel.tsx
@@ -3,7 +3,7 @@
 // the editor's simulation is, from being sent to its end, in words. It opens when a simulation is sent, and from the
 // toolbar's strip and the canvas's bar; one side panel at a time, as the others (side.ts). The result's sections (the
 // banner, the checks on the server, the steps, the input used) come in below the lifecycle as `children`.
-import { useEffect, useRef, type ReactNode } from "react";
+import { Fragment, useEffect, useRef, type ReactNode } from "react";
 import { Button } from "../../../components/Button";
 import { duration, runId } from "../../../lib/runStatus";
 import { ENDED } from "../../../lib/simulations";
@@ -12,8 +12,9 @@ import { SimulatedChip, StatusChip } from "./chips";
 import { clock, endedWhat, lineOf } from "./lifecycle";
 import type { SimulationSession } from "./useSimulation";
 
-export function SimulationPanel({ session, onSimulateAgain, onClose, children }: {
-  session: SimulationSession; onSimulateAgain?: () => void; onClose: () => void; children?: ReactNode;
+/** `runOf`: its run's name as a link to the run's page (the runs design §5.1), where there's a router to follow it. */
+export function SimulationPanel({ session, onSimulateAgain, onClose, runOf, children }: {
+  session: SimulationSession; onSimulateAgain?: () => void; onClose: () => void; runOf?: (id: string) => ReactNode; children?: ReactNode;
 }) {  // prettier-ignore
   const heading = useRef<HTMLHeadingElement>(null);
   useEffect(() => heading.current?.focus(), []);
@@ -27,11 +28,12 @@ export function SimulationPanel({ session, onSimulateAgain, onClose, children }:
   const line = lineOf(session); // where it is, in a sentence
 
   // Which run it is, and when it started or how it ended (§7.5).
-  const facts =
+  const named = request && (runOf ? runOf(request.id) : `run ${runId(request.id)}`);
+  const facts: ReactNode[] | null =
     request && state && phase && phase !== "dead" && phase !== "refused"
       ? ended
-        ? [`Ended: ${endedWhat(phase, steps)}`, duration(run?.started_at ?? null, run?.ended_at ?? null), `draft revision ${request.draft_revision}`, `run ${runId(request.id)}`]
-        : [`Started ${said(run?.started_at ?? request.queued_at)}`, `draft revision ${request.draft_revision}`, `run ${runId(request.id)}`]
+        ? [`Ended: ${endedWhat(phase, steps)}`, duration(run?.started_at ?? null, run?.ended_at ?? null), `draft revision ${request.draft_revision}`, named]
+        : [`Started ${said(run?.started_at ?? request.queued_at)}`, `draft revision ${request.draft_revision}`, named]
       : null;  // prettier-ignore
 
   return (
@@ -55,7 +57,16 @@ export function SimulationPanel({ session, onSimulateAgain, onClose, children }:
           <SimulatedChip />
         </p>
       )}
-      {facts && <p className="text-small text-muted">{facts.filter(Boolean).join(" · ")}</p>}
+      {facts && (
+        <p className="text-small text-muted">
+          {facts.filter(Boolean).map((f, i) => (
+            <Fragment key={i}>
+              {i > 0 && " · "}
+              {f}
+            </Fragment>
+          ))}
+        </p>
+      )}
       {line && <p className="text-small">{line}</p>}
       {local.kind === "admitted" && local.latest && request && (
         <p className="text-small text-muted">
```

- [ ] **Step 4: Run them again**

Run: the same command.

Expected: PASS, 188 passed.

- [ ] **Step 5: Static checks**

Run: the two of "How to run things". Expected: no output.

- [ ] **Step 6: Commit, and the milestone**

```bash
git add frontend/src
git commit -m "feat(editor): the ways to a run: the toolbar's Runs, the last run, the Simulation panel's run (4e-1b)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

Append `### 4e-1b, milestone 3 (date)` to the ledger: the tasks' commits, each task's test counts as run, every
mid-slice ruling. Commit it (`docs(editor-4): 4e-1b milestone 3`). **Pause** for the owner's review.

---

# Milestone 4 — Close

### Task 15: In the browser

**Spec:** §6 (4e-1b: the Playwright gate over each board's state, light and dark, at 1280 and 320 px; the runs seeded
through the API; nothing leaves the stack).

**Files:**
- Create: `frontend/e2e/runs.spec.ts`, `frontend/e2e/fixtures/runs-check.dewpoint.json`,
  `frontend/e2e/fixtures/runs-loop.dewpoint.json`, `frontend/e2e/fixtures/runs-wait.dewpoint.json`
- Modify: `frontend/playwright.config.ts` (the workflows project runs `runs.spec.ts`)

**Interfaces:**
- Consumes: `test`, `expect`, `expectAccessible` (`e2e/gate.ts`); the admin's saved state (the foundations project).
- Produces: nothing other tasks use.

Three fixtures of control steps only: "Runs check" (greet, then check: `size(trigger.site) > 2`, done on true, a `fail`
step on false), "Runs loop" (each site, is_long, mark) and "Runs wait" (a 10-minute delay). Each spec imports and
publishes its own through the API, with the session's CSRF token, and starts runs by hand:
- the list, light and dark: its rows, the status menu, the workflow chooser, nothing matching and Clear the filters;
- a failed live run, opened on its failed step: the banner, the tags, the Result tab, the Setup tab;
- a loop: its totals, its iterations four at a time, a step's iteration shown;
- a running live run: its question in an alert dialog, then cancelled;
- at 320 px: the list as a list, a simulation's page, its start, and a run not kept.

The gate fails any CSP violation, console error or request to another origin.

- [ ] **Step 1: Write the specs**

Apply:

```diff
diff --git a/frontend/e2e/fixtures/runs-check.dewpoint.json b/frontend/e2e/fixtures/runs-check.dewpoint.json
new file mode 100644
index 00000000..7058117c
--- /dev/null
+++ b/frontend/e2e/fixtures/runs-check.dewpoint.json
@@ -0,0 +1,23 @@
+{
+  "format": "dewpoint.workflow",
+  "format_version": 1,
+  "name": "Runs check",
+  "graph": {
+    "graph_format": 1,
+    "nodes": [
+      { "id": "9c3e4f5a-6b7c-4d8e-9f0a-1b2c3d4e5f01", "key": "greet", "type": "flow.transform@1", "config": { "fields": { "greeting": { "$value": { "kind": "cel", "expr": "'hello ' + trigger.site" } } } }, "position": { "x": 0, "y": 140 } },
+      { "id": "9c3e4f5a-6b7c-4d8e-9f0a-1b2c3d4e5f02", "key": "check", "type": "flow.if@1", "config": { "condition": { "$value": { "kind": "cel", "expr": "size(trigger.site) > 2" } } }, "position": { "x": 0, "y": 280 } },
+      { "id": "9c3e4f5a-6b7c-4d8e-9f0a-1b2c3d4e5f03", "key": "done", "type": "flow.transform@1", "config": { "fields": { "n": 1 } }, "position": { "x": -200, "y": 420 } },
+      { "id": "9c3e4f5a-6b7c-4d8e-9f0a-1b2c3d4e5f04", "key": "halt", "type": "flow.fail@1", "config": { "message": "The site's name is too short." }, "position": { "x": 200, "y": 420 } }
+    ],
+    "edges": [
+      { "from": { "node": "9c3e4f5a-6b7c-4d8e-9f0a-1b2c3d4e5f01" }, "to": { "node": "9c3e4f5a-6b7c-4d8e-9f0a-1b2c3d4e5f02" } },
+      { "from": { "node": "9c3e4f5a-6b7c-4d8e-9f0a-1b2c3d4e5f02", "port": "true" }, "to": { "node": "9c3e4f5a-6b7c-4d8e-9f0a-1b2c3d4e5f03" } },
+      { "from": { "node": "9c3e4f5a-6b7c-4d8e-9f0a-1b2c3d4e5f02", "port": "false" }, "to": { "node": "9c3e4f5a-6b7c-4d8e-9f0a-1b2c3d4e5f04" } }
+    ],
+    "settings": {
+      "input_schema": { "type": "object", "properties": { "site": { "type": "string", "title": "Site" } }, "required": ["site"] }
+    }
+  },
+  "bindings": []
+}
diff --git a/frontend/e2e/fixtures/runs-loop.dewpoint.json b/frontend/e2e/fixtures/runs-loop.dewpoint.json
new file mode 100644
index 00000000..73b06e6e
--- /dev/null
+++ b/frontend/e2e/fixtures/runs-loop.dewpoint.json
@@ -0,0 +1,23 @@
+{
+  "format": "dewpoint.workflow",
+  "format_version": 1,
+  "name": "Runs loop",
+  "graph": {
+    "graph_format": 1,
+    "nodes": [
+      { "id": "9d3e4f5a-6b7c-4d8e-9f0a-1b2c3d4e5f01", "key": "each_site", "type": "flow.loop@1", "config": { "items": { "$value": { "kind": "cel", "expr": "trigger.sites" } } }, "position": { "x": 0, "y": 140 } },
+      { "id": "9d3e4f5a-6b7c-4d8e-9f0a-1b2c3d4e5f02", "key": "is_long", "type": "flow.if@1", "config": { "condition": { "$value": { "kind": "cel", "expr": "size(item) > 4" } } }, "position": { "x": 0, "y": 280 } },
+      { "id": "9d3e4f5a-6b7c-4d8e-9f0a-1b2c3d4e5f03", "key": "mark", "type": "flow.transform@1", "config": { "fields": { "site": { "$value": { "kind": "cel", "expr": "item" } } } }, "position": { "x": 0, "y": 420 } }
+    ],
+    "edges": [
+      { "from": { "node": "9d3e4f5a-6b7c-4d8e-9f0a-1b2c3d4e5f01", "port": "body" }, "to": { "node": "9d3e4f5a-6b7c-4d8e-9f0a-1b2c3d4e5f02" } },
+      { "from": { "node": "9d3e4f5a-6b7c-4d8e-9f0a-1b2c3d4e5f02", "port": "true" }, "to": { "node": "9d3e4f5a-6b7c-4d8e-9f0a-1b2c3d4e5f03" } }
+    ],
+    "settings": {
+      "input_schema": {
+        "type": "object", "properties": { "sites": { "type": "array", "items": { "type": "string" }, "title": "Sites" } }, "required": ["sites"]
+      }
+    }
+  },
+  "bindings": []
+}
diff --git a/frontend/e2e/fixtures/runs-wait.dewpoint.json b/frontend/e2e/fixtures/runs-wait.dewpoint.json
new file mode 100644
index 00000000..5cf3acfd
--- /dev/null
+++ b/frontend/e2e/fixtures/runs-wait.dewpoint.json
@@ -0,0 +1,14 @@
+{
+  "format": "dewpoint.workflow",
+  "format_version": 1,
+  "name": "Runs wait",
+  "graph": {
+    "graph_format": 1,
+    "nodes": [
+      { "id": "9e3e4f5a-6b7c-4d8e-9f0a-1b2c3d4e5f01", "key": "wait", "type": "flow.delay@1", "config": { "duration_s": 600 }, "position": { "x": 0, "y": 140 } },
+      { "id": "9e3e4f5a-6b7c-4d8e-9f0a-1b2c3d4e5f02", "key": "after", "type": "flow.transform@1", "config": { "fields": { "n": 1 } }, "position": { "x": 0, "y": 280 } }
+    ],
+    "edges": [{ "from": { "node": "9e3e4f5a-6b7c-4d8e-9f0a-1b2c3d4e5f01" }, "to": { "node": "9e3e4f5a-6b7c-4d8e-9f0a-1b2c3d4e5f02" } }]
+  },
+  "bindings": []
+}
diff --git a/frontend/e2e/runs.spec.ts b/frontend/e2e/runs.spec.ts
new file mode 100644
index 00000000..5f7b3b55
--- /dev/null
+++ b/frontend/e2e/runs.spec.ts
@@ -0,0 +1,189 @@
+// SPDX-License-Identifier: Apache-2.0
+// Slice 4e-1b in the browser (the runs design §5, §6): the Runs page and a run's page against the real stack, its
+// dispatcher and worker, behind nginx, under the served CSP, with axe, light and dark, at 1280 and 320 px. The runs are
+// seeded through the API: workflows of control steps only, run live (nothing leaves the stack, D24) and simulated, one
+// failing at a `fail` step, a loop, and a run held by a delay to be cancelled. The gate fails any request to another
+// origin.
+import { readFileSync } from "node:fs";
+import type { Page } from "@playwright/test";
+import { expect, expectAccessible, test } from "./gate";
+
+test.describe.configure({ mode: "serial" });
+
+const ENDED = new Set(["succeeded", "failed", "cancelled", "deadline_exceeded", "refused", "dead"]);
+
+async function tenantId(page: Page): Promise<string> {
+  const tenants = (await (await page.request.get("/api/v1/tenants")).json()) as { id: string }[];
+  return tenants[0]!.id;
+}
+
+/** The API as the web client calls it: an unsafe request names the client and carries the session's CSRF token. */
+async function api(page: Page) {
+  const tenant = await tenantId(page);
+  const { csrf_token } = (await (await page.request.get("/api/v1/auth/session")).json()) as { csrf_token: string };
+  const headers = { "X-Dewpoint-Client": "web", "X-CSRF-Token": csrf_token };
+  const post = async (path: string, data: unknown) => {
+    const answer = await page.request.post(`/api/v1/t/${tenant}${path}`, { data, headers });
+    expect(answer.ok(), `POST ${path}: ${answer.status()}`).toBe(true);
+    return (await answer.json()) as Record<string, unknown>;
+  };
+  return {
+    tenant,
+    /** A fixture imported under `name` and published: its workflow's id. */
+    async publish(fixture: string, name: string): Promise<string> {
+      const document = JSON.parse(readFileSync(`e2e/fixtures/${fixture}`, "utf8")) as unknown;
+      const workflow = await post("/workflows/import", { name, document });
+      await post(`/workflows/${String(workflow.id)}/publish`, { expected_latest_version: null });
+      return String(workflow.id);
+    },
+    /** A run started by hand: its id. */
+    async start(workflowId: string, input: Record<string, unknown>, mode: "live" | "simulate" = "live"): Promise<string> {
+      return String((await post(`/workflows/${workflowId}/runs`, { input, mode })).id);
+    },
+    /** Waits for a run to end, as the dispatcher and the worker run it. */
+    async ended(runId: string): Promise<void> {
+      await expect
+        .poll(async () => ENDED.has(((await (await page.request.get(`/api/v1/t/${tenant}/runs/${runId}`)).json()) as { status: string }).status), { timeout: 60_000 })
+        .toBe(true);
+    },
+    /** Waits for a run to be running. */
+    async running(runId: string): Promise<void> {
+      await expect
+        .poll(async () => ((await (await page.request.get(`/api/v1/t/${tenant}/runs/${runId}`)).json()) as { status: string }).status, { timeout: 60_000 })
+        .toBe("running");
+    },
+  };
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
+const tags = (page: Page, key: string) => page.getByRole("list", { name: `${key}: result` });
+
+test("the Runs page lists runs, filters them in its address, and says when none match (the Main and ListStates boards)", async ({ page }) => {
+  const seed = await api(page);
+  const check = await seed.publish("runs-check.dewpoint.json", "Runs A");
+  const ok = await seed.start(check, { site: "HQ Paris" });
+  const failed = await seed.start(check, { site: "X" });
+  const simulated = await seed.start(check, { site: "Lab" }, "simulate");
+  for (const id of [ok, failed, simulated]) await seed.ended(id);
+  await page.goto(`/t/${seed.tenant}/runs?workflow=${check}`);
+  await expect(page.getByRole("heading", { level: 1, name: "Runs" })).toBeVisible();
+  await expect(page.getByText("Updates every 5 s")).toBeVisible();
+  const table = page.getByRole("region", { name: "Runs" });
+  await expect(table.getByRole("link", { name: failed.slice(0, 8) })).toBeVisible();
+  await expect(table.getByRole("link", { name: ok.slice(0, 8) })).toBeVisible();
+  await expect(table.getByRole("row").filter({ has: page.getByRole("link", { name: simulated.slice(0, 8) }) })).toContainText("Simulated");
+  await expect(table.getByRole("row").filter({ has: page.getByRole("link", { name: failed.slice(0, 8) }) })).toContainText("workflow_failed");
+  await accessibleBothWays(page, "runs: the list");
+  // One status, from its menu: the address keeps it.
+  await page.getByRole("button", { name: "Status · Any" }).click();
+  await accessibleBothWays(page, "runs: the status menu");
+  await page.getByRole("menuitemradio", { name: "Failed" }).click();
+  await expect(page).toHaveURL(/status=failed/);
+  await expect(table.getByRole("link", { name: ok.slice(0, 8) })).toHaveCount(0);
+  await expect(table.getByRole("link", { name: failed.slice(0, 8) })).toBeVisible();
+  // The workflow, from a list that can be searched.
+  await page.getByRole("button", { name: "Workflow · Runs A" }).click();
+  await page.getByRole("dialog", { name: "Choose a workflow" }).getByRole("combobox").fill("Runs A");
+  await accessibleBothWays(page, "runs: choosing a workflow");
+  await page.keyboard.press("Escape");
+  // Nothing matches: said, with Clear the filters.
+  await page.getByRole("button", { name: "Trigger · Any" }).click();
+  await page.getByRole("menuitemradio", { name: "Schedule" }).click();
+  await expect(page.getByText("No runs match these filters in the last 24 hours.")).toBeVisible();
+  await accessibleBothWays(page, "runs: nothing matches");
+  await page.getByRole("button", { name: "Clear the filters" }).click();
+  await expect(page).toHaveURL(/\/runs$/);
+});
+
+test("a failed live run opens on its failed step, its result in the drawer (the RunFailed board)", async ({ page }) => {
+  const seed = await api(page);
+  const check = await seed.publish("runs-check.dewpoint.json", "Runs B");
+  const failed = await seed.start(check, { site: "X" });
+  await seed.ended(failed);
+  await page.goto(`/t/${seed.tenant}/runs?workflow=${check}`);
+  await page.getByRole("link", { name: failed.slice(0, 8) }).click();
+  await expect(page.getByRole("heading", { level: 1, name: "Runs B" })).toBeVisible();
+  await expect(page.getByRole("note")).toHaveText("Live run. It acted for real: steps marked sent called their connections.");
+  await expect(tags(page, "greet")).toContainText("succeeded");
+  await expect(tags(page, "check")).toContainText("→ false");
+  await expect(tags(page, "done")).toContainText("skipped");
+  const drawer = page.getByRole("complementary", { name: "halt" });
+  await expect(drawer.getByRole("tab", { name: "Result", selected: true })).toBeVisible();
+  await expect(drawer.getByText("workflow_failed").first()).toBeVisible();
+  await expect(drawer.getByRole("heading", { name: "halt" })).toBeFocused();
+  await accessibleBothWays(page, "a run: failed, its failed step's result");
+  await drawer.getByRole("tab", { name: "Setup" }).click();
+  await expect(drawer.getByText("Message", { exact: true }).first()).toBeVisible();
+  await accessibleBothWays(page, "a run: its failed step's setup");
+});
+
+test("a loop's iterations, four at a time, and one step's, picked (the RunLoop board)", async ({ page }) => {
+  const seed = await api(page);
+  const loop = await seed.publish("runs-loop.dewpoint.json", "Runs C");
+  const run = await seed.start(loop, { sites: ["Paris-Opera", "Lyon", "Nice", "Bordeaux-Centre", "Lille-Flandres"] });
+  await seed.ended(run);
+  await page.goto(`/t/${seed.tenant}/runs/${run}`);
+  await expect(tags(page, "each_site")).toContainText("5 iterations");
+  await expect(tags(page, "is_long")).toContainText("5 instances: 5 succeeded");
+  await page.getByRole("button", { name: /^each_site, Loop/ }).click();
+  const drawer = page.getByRole("complementary", { name: "each_site" });
+  await expect(drawer.getByRole("list", { name: "each_site's iterations, 1 to 4 of 5" })).toBeVisible();
+  await accessibleBothWays(page, "a run: a loop's iterations");
+  await drawer.getByRole("button", { name: "Next 1" }).click();
+  await expect(drawer.getByRole("list", { name: "each_site's iterations, 5 to 5 of 5" })).toBeVisible();
+  await page.getByRole("button", { name: /^mark, Transform/ }).click();
+  const mark = page.getByRole("complementary", { name: "mark" });
+  await mark.getByRole("button", { name: "Show" }).click();
+  await expect(mark.getByRole("region", { name: "Output" })).toContainText("Paris-Opera");
+  await accessibleBothWays(page, "a run: a step's iteration");
+});
+
+test("a running live run is cancelled after its question (the RunRunning board)", async ({ page }) => {
+  const seed = await api(page);
+  const wait = await seed.publish("runs-wait.dewpoint.json", "Runs D");
+  const run = await seed.start(wait, {});
+  await seed.running(run);
+  await page.goto(`/t/${seed.tenant}/runs/${run}`);
+  await expect(page.getByRole("note")).toHaveText("Live run. It acts for real: steps marked sent called their connections.");
+  await expect(tags(page, "wait")).toContainText("running");
+  await accessibleBothWays(page, "a run: running");
+  await page.getByRole("button", { name: "Cancel the run" }).click();
+  const ask = page.getByRole("alertdialog", { name: "Cancel this run?" });
+  await expect(ask).toBeVisible();
+  await accessibleBothWays(page, "a run: cancel's question");
+  await ask.getByRole("button", { name: "Cancel the run" }).click();
+  await expect(page.getByRole("heading", { level: 1 }).locator("..").getByText(/^(Cancel requested|Cancelled)$/)).toBeVisible();
+  await expect(page.getByRole("heading", { level: 1 }).locator("..").getByText("Cancelled", { exact: true })).toBeVisible({ timeout: 60_000 });
+  await accessibleBothWays(page, "a run: cancelled");
+});
+
+test("at 320 px: the list as a list, a simulation's page and its start, and a run not kept (the RunOther and Narrow boards)", async ({ page }) => {
+  const seed = await api(page);
+  const check = await seed.publish("runs-check.dewpoint.json", "Runs E");
+  const simulated = await seed.start(check, { site: "Lab" }, "simulate");
+  await seed.ended(simulated);
+  await page.setViewportSize({ width: 320, height: 720 });
+  await page.goto(`/t/${seed.tenant}/runs?workflow=${check}`);
+  const list = page.getByRole("list", { name: "Runs" });
+  await expect(list.getByRole("link", { name: simulated.slice(0, 8) })).toBeVisible();
+  await expect(page.getByRole("table")).toHaveCount(0);
+  await accessibleBothWays(page, "runs: the list, 320 px");
+  await list.getByRole("link", { name: simulated.slice(0, 8) }).click();
+  await expect(page.getByText(/^Simulated\./).first()).toBeVisible();
+  await expect(tags(page, "greet")).toContainText("succeeded");
+  await page.getByRole("button", { name: /^Start: by hand/ }).click();
+  const start = page.getByRole("complementary", { name: "Start" });
+  await expect(start.getByRole("region", { name: "Input" })).toContainText("Lab");
+  await accessibleBothWays(page, "a run: its start, 320 px");
+  await page.goto(`/t/${seed.tenant}/runs/0d4f9b2a-0000-4000-8000-000000000000`);
+  await expect(page.getByText("This run isn't kept any more, or it never existed here.")).toBeVisible();
+  await accessibleBothWays(page, "a run: not kept, 320 px");
+  await page.setViewportSize({ width: 1280, height: 720 });
+});
diff --git a/frontend/playwright.config.ts b/frontend/playwright.config.ts
index bc57ab5d..d339c003 100644
--- a/frontend/playwright.config.ts
+++ b/frontend/playwright.config.ts
@@ -7,7 +7,7 @@ export default defineConfig({
     { name: "foundations", testMatch: /(foundations|gate)\.spec\.ts/, use: { ...devices["Desktop Chrome"] } },
     {
       name: "workflows",
-      testMatch: /(workflows|triggers|simulation)\.spec\.ts/,
+      testMatch: /(workflows|triggers|simulation|runs)\.spec\.ts/,
       dependencies: ["foundations"],
       use: { ...devices["Desktop Chrome"], storageState: "test-results/admin-state.json" },
     },
```

- [ ] **Step 2: Type check and lint them**

Run: the two of "How to run things". Expected: no output (the type check covers `e2e/`, and ESLint lints it).

- [ ] **Step 3: Run them in the browser**

They need the Compose stack, with its dispatcher and worker, as CI's e2e job brings it up (`deploy/compose`, the
development override, a generated `.env` that's never printed, `dewpoint admin init`). Locally, building it takes long:
ask the owner first. Then, from `$WT/frontend`: `npx --offline pnpm@12.6.0 exec playwright test` (the foundations
project signs the admin in first).
Expected: every spec passes, the five of `runs.spec.ts` among them, and the editor's asset test as rewritten in Task 9.
A failure is read and fixed test-first. If the owner prefers, the specs run in CI's e2e job on the PR instead, and the
summary says they weren't run locally.

- [ ] **Step 4: Commit**

```bash
git add frontend/e2e frontend/playwright.config.ts
git commit -m "test(e2e): the Runs page and a run's page in the browser, light and dark, at 1280 and 320 px (4e-1b)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 16: Every check, the ledger, the final checkpoint

**Files:**
- Modify: `docs/superpowers/plans/2026-10-05-editor-ui-4-ledger.md`

- [ ] **Step 1: Every check, and CodeQL**

From `$WT/frontend`:
- `npx --offline pnpm@12.6.0 exec vitest run`: the whole suite (about 2 minutes);
- `npx --offline pnpm@12.6.0 exec eslint .`; `npx --offline pnpm@12.6.0 build` (the type check, then Vite);
- `npx --offline pnpm@12.6.0 check:api`: the API's schema, unchanged since 4e-1a;
- local CodeQL on the head (`scratchpad/codeql/scan-js.sh 4e1b <dir>` on a `git archive` of it): no alert.

Expected, as on the plan's own check (at the top): the suite, 1277 passed in 98 files; ESLint and the type check silent;
the build done, the editor's script about 150 kB beside the shared chunk about 357 kB and its stylesheet, a run's page
19 kB and the Runs page 11 kB of their own, the entry 641 kB (ruling 21); `check:api` passes; CodeQL, no finding.

A failure is read and fixed test-first, or reported as it is: never a claim that every check passes when one didn't.

- [ ] **Step 2: The ledger**

Append `### 4e-1b, milestone 4 and the final checkpoint (date)`: the tasks' commits, each check's result as run (the
suite's counts), whether the e2e specs ran locally or wait for CI, every mid-slice ruling, anything deferred. Commit it
(`docs(editor-4): 4e-1b final checkpoint`).

- [ ] **Step 3: The final review and the pause**

A fresh reviewer, on the most capable model, reviews the whole branch:
- against this plan (its Review Focus first) and the spec's §5 and §6, with the boards;
- with the ledger's rulings in view.

Critical and important findings are fixed test-first, once; minor ones are listed. Then **stop**. The summary to the
owner names what's built, the checks as run, and the rulings proposed and made. It asks for the owner's word on push
and a PR; nothing is pushed before it. CI on the PR runs the backend (about 12 minutes), the frontend, CodeQL and the
Compose e2e: say so before pushing.
