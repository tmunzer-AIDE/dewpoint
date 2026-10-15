# Editor UI 4d-1c: Simulate Workflow and Simulate Step (the UI) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Revision 1, 2026-10-15.** Nothing is built before the owner approves this plan. Nothing is pushed and no PR is
opened without the owner's OK in chat.

The plan's code was checked before review on a scratch tree of main at 44bc2f52, never on a branch. Each task's
diffs were applied as written, in order:
- the test diff alone, then the task's tests: they failed as its "Run them" step says;
- then the implementation diff and the same tests: they passed;
- after every task, the type check (`tsc -b --noEmit`) and ESLint: silent;
- after the last, the tree matched the prototype the diffs were cut from, file for file;
- the 23 diff blocks, taken from this file's own text, are the diffs applied, byte for byte, in order;
- on the final tree: the whole frontend suite (1175 passed, 90 files), ESLint, the build, `check:api`, and CodeQL
  (javascript-typescript, CLI 2.27.2, javascript-queries 2.4.7: no finding).

Three things changed after the prototype. Task 2 gained the hidden tab's test (it fails when the interval keeps reading
in the background: "expected 3 to be 2"), and Task 8's try again now first checks that the 503 is a refusal (red before
Task 8's code: "expected 'unknown' to be 'refused'"); both before this check. Task 13 gained its third spec (after an
edit, and refused) after it: the type check, ESLint and CodeQL ran again on the final tree with it, and its diff
reverses cleanly from that tree.

The e2e specs (Task 13) were type-checked and linted, not run: they need the Compose stack, which Task 13 asks the owner
about. The executor still runs every step: the check is evidence, not a substitute.

**Goal:** The editor simulates its saved draft, whole or one step alone, and shows where the simulation is and what it
did: on the canvas, in a Simulation panel and in each step's Test tab (the spec's §7, against the signed-off D8 boards).

**Architecture:**
- **The API layer.** A frozen request (its key, revision and body) is sent once, with `Idempotency-Key` and `If-Match`,
  and sent again as it is when its answer is lost. `useSimulation` reads the editor's own simulation, or after a
  reload the person's latest, until it ends: at 1 s, backing off to 5 s, paused while the tab is hidden.
- **Starting.** "◌ Simulate workflow" runs Publish's preflight and asks for the input at the revision the save made.
  A step's Test tab reads its seed contract at the saved revision and sends the values it reads.
- **The result.** Canvas tags come from the server's per-step summary, never from a partial page. The Simulation panel
  gives the lifecycle, the checks, the steps in run order, a loop's iterations four at a time, and the input used. A
  result after edits is marked against the draft it ran (its snapshot). Refusals are shown in the server's words.

**Tech Stack:** React 19, TanStack Query 5 (query-core 5.103.2), TanStack Router, openapi-fetch over the generated
`schema.d.ts`, Radix Tabs, Tailwind v4 tokens; Vitest and Testing Library (no jest-dom); Playwright against the Compose
stack, with axe.

**Spec:** `docs/superpowers/specs/2026-10-13-editor-4d1-simulation-design.md`: §7 (the UI), with §6.6 (the reads it
uses) and §8 (4d-1c's tests). The boards: "4d-1 Simulation Mockups" v20 (Main, Preflight, InputFields, InputJson,
Running, Lifecycle, ResultCanvas, ResultPanel, TestTab, TestResult, TestOther, Refusals, Stale, ReadOnly, Narrow 320).

## Global Constraints

- **The frontend only.** No backend change, no migration, no ABI change. The API's schema is 4d-1b's, unchanged:
  `check:api` passes as it is.
- **No new dependency.** No npm package is added, and there's no third-party JavaScript or CDN asset: everything is
  bundled, under the strict CSP, with no inline script or style.
- **Words first.** Every state is said in words; colour and the hatch only repeat them (§7.4). The server's codes are
  worded in the UI (`results.ts`'s `ORIGIN`); refusals are shown in the server's own words, with no client catalogue.
  The boards' copy is used where it exists; the rulings below say where it isn't.
- **No AI tells.** No left-border accents, halos, tinted icon tiles or eyebrows (`src/test/aiTells.test.ts` enforces
  them).
- **WCAG 2.2 AA**, light and dark, at 1280 and 320 px: axe in the e2e specs (Task 13); every control named, every
  state in text.
- **No real Mist or SaaS call.** Unit tests stub `fetch`. The e2e specs simulate flow steps only, on the Compose stack;
  nothing leaves the stack (D24: the gate fails a request to another origin).
- **Verify, don't remember.** Each library behaviour relied on was checked in the installed package:
  - query-core 5.103.2: `refetchInterval` as a function, and the interval skipped while `focusManager` says the tab
    isn't focused (`refetchIntervalInBackground` false); `keepPreviousData`.
  - Radix Tabs: an inactive panel isn't mounted, so the Test tab reads its contract only when it's open.
  - openapi-fetch's types drop a key the schema allows only as `null`: `SimulationRequest` is
    `Omit<SimulationOut, "version_id">`.
- **CI.**
  - Every check runs locally first. Commits and PRs carry no skip marker.
  - Nothing is pushed and no PR is opened without the owner's OK in chat.
  - Ask before any local run expected over 10 minutes (the e2e specs on a local Compose stack).

## Review Focus

These are the inputs and conditions most likely to bite a person using this. Each is pinned by the test named, in the
task that owns the code.

- **A simulation's answer lost** (a dropped connection, a proxy's 502). It's "outcome unknown", and "Check again" sends
  the same request under the same key: never a second simulation. A coded 503 (the production gate, no current build)
  is a refusal, never a lost answer. Task 2: `whose answer is lost is unknown, and Check again sends the same request,
  its key unchanged`. Task 8: `refused by the deployment says so too: a 503 in the server's words isn't a lost answer`.
- **The tab hidden while a simulation runs.** Nothing is read while it's hidden; it's read at once when shown (§7.2).
  Task 2: `is read again after a second, and not while the tab is hidden (§7.2)`.
- **A save that moves the draft between reading a step's values and sending them.** The contract is read again at the
  new revision and shown, saying what changed; nothing is sent with an older contract. Task 10: `reads the values again
  when saving moved the draft, and sends nothing until they're checked`.
- **A result read after edits.** "Before your edits", with each step changed since, new since or gone, from the draft
  it ran. Task 8: `marks a result from before the person's edits, on the canvas and in the panel (§7.7; the Stale
  board)`.
- **A sensitive value.** Typed and masked, never prefilled; read back as "redacted". Task 10: `types a sensitive value,
  never prefilled`. Task 11: `shows the values used, each seeded, sensitive ones redacted, and the output`.
- **A loop of more than four iterations.** Paged four at a time, back and forth, stopping at the last; "Open" on a
  failed one lands on its step's Test tab at that iteration. Task 7: `pages on, and back, and stops at the last`.
  Task 12: `opens a failed iteration's step on its Test tab, at that iteration (§7.5, §7.6)`.

## Rulings this plan proposes

They join the ledger as 191 onward only when the owner accepts the plan; mid-slice rulings start at M102. Each follows
the spec where the boards or the spec are silent, or says where it departs from a board.

1. **A loop's progress is its items, never "N of M iterations ended"** (the Running board). While a loop runs, its tag
   gives the items it was given ("12 items"); a step in its body says "So far, 4 instances: …" with no "of M"; once it
   ended, the loop says "12 iterations", in place of an origin. Why: D-a4, the server keeps no per-iteration status, so
   "ended" per iteration can't be known without reading every instance. Cost if wrong: a read per loop while it runs.
2. **"attempt N of M" shows on the canvas only when N > 1**; the Test tab's result always says it (the TestResult
   board). M is the step's own `max_attempts`, else its type's. Why: a first attempt says nothing the status doesn't.
   Cost if wrong: a tag.
3. **The panel's step rows carry the canvas's tags.** The ResultPanel board drops a control step's status and adds a
   delay's "10 min"; here one function words both places. Why: one wording, no second one to drift. Cost if wrong: the
   rows read a little longer than the board.
4. **A loop's iterations are paged once it ended, for a loop with one instance.** A nested loop's own iterations wait
   for 4e's run detail; its row shows its totals. Why: a running loop's pages move under the reader, and a nested loop
   needs a second level of paging. Cost if wrong: a nested loop's iterations aren't browsable here.
5. **The draft a simulation ran is read when its result is stale** (`GET …/draft/snapshots/{id}`, once: it never
   changes): it gives "changed since", and the iterations' columns. A current result uses the draft, which is the same.
   Why: the snapshot is the only record of what ran. Cost if wrong: one read per stale result.
6. **"Changed since" compares a step's own definition**: its key, type, config and options, with the options' defaults
   filled in. Never its position, nor its edges: a rewired edge is covered by "Before your edits". Why: a moved card
   isn't a change. Cost if wrong: a step whose wiring changed isn't marked on its own.
7. **"Before your edits" shows once the result has ended**: the server's draft moved on, or an edit here isn't saved
   (the editor's generation, as publish's findings are dated). Why: §7.7; while it runs, the bar says it's running.
   Cost if wrong: none.
8. **The input used lists what the request stored**, never the ResultPanel board's "left out" fields: the form at an
   older revision can't be read once the draft moved (`start-form` answers 409 at another revision). Cost if wrong:
   an omitted field isn't named.
9. **A coded 503 is a refusal, never a lost answer.** The production gate, an environment not recorded and no current
   build answer 503 with their code; only a 5xx without the API's code (a proxy's) is "outcome unknown". "Try again"
   (no current build) sends the same frozen request: admission rolls a refusal back, so its key is free. Why: §7.2's
   unknown state is for a lost answer. Cost if wrong: none.
10. **A draft changed elsewhere refuses a simulation as it refuses a save:** a 409 `draft_conflict` turns the editor
    read only, as a save's 409 does (`saver.conflict()`), and the panel says why. Why: one fact, one banner. Cost if
    wrong: none.
11. **A step that can't run alone says so in the server's words** (the contract's `refused`), not the TestOther
    board's sentence for a loop. Why: §7.7, refusals in the server's words. Cost if wrong: copy.
12. **Simulate step keeps the drawer open; its result is in the Test tab**, and on the canvas, not in the Simulation
    panel, which would replace the drawer (one side panel at a time). Why: the person is in the drawer; the bar's
    "Simulation" opens the panel. Cost if wrong: a click.
13. **A seed is typed as text when its types are text, else as JSON; an empty value is a value not given.** An empty
    string can't be sent as text. Why: one control per value, the contract's types deciding. Cost if wrong: a step that
    reads `""` can't be tested with it.
14. **A seed's title** is its schema's: the workflow's input schema, or the output schema of the step that writes it;
    a loop's item is named by its loop; else the pointer's last name. Its tags are part of its accessible name, as the
    input dialog's are. The prefill names its step, not its sample's date ("From get_site's sample."): the contract
    carries no date. Cost if wrong: a field in the API, later.
15. **Values are shown as the request stored them**: text as it is, anything else as JSON (not the TestResult board's
    "{3 fields}"), "[redacted]" as "redacted". Why: one rule in the panel and the Test tab. Cost if wrong: a long value
    wraps.
16. **A branch's result says its port** ("Takes → true."), not its condition's text: the run records the port, and
    the condition's text would be today's draft's, not the run's. Cost if wrong: a line.
17. **The step's line in the latest simulation has one format** ("Revision 14, 10:42:05: <its tags>."), a loop's
    included; its iteration picker lists the first 50 instances, in iteration order. Cost if wrong: a later page.
18. **The editor's chunk passes Vite's 500 kB warning** (453 to 502 kB, 15 kB more gzipped), with no code split. Why:
    the entry chunk already raises it on main, and the editor loads apart from the list and sign-in. Cost if wrong: a
    lazy chunk later.
19. **The browser checks the boards' settled states** (§8: "over each board's state"): the input, the result, after an
    edit, refused, and a step test at 320 px, each light and dark. The transient ones (Running, the Lifecycle's) and
    those needing another role or the deployment's gate (ReadOnly, the gate's refusal) are covered by the unit tests.
    Why: a state that lasts a second can't be held for axe without a hook in the product. Cost if wrong: those states'
    names and contrast are checked in jsdom only.

## File Structure

New, under `frontend/src/`:
- `lib/simulations.ts`: the API's types, the frozen request, its send and cancel, the phase, polling, the reads.
- `lib/skeleton.ts`: an input's skeleton from its schema (a Mist event's).
- `components/Tag.tsx`: a word beside a label.
- `routes/editor/startInput.tsx`: the start form's fields, moved from `ScheduleForm` to serve the dialog too.
- `routes/editor/simulation/`:
  - `useSimulation.ts`: the editor's simulation.
  - `SimulateDialog.tsx`, `SimBanner.tsx`: the input.
  - `lifecycle.ts`, `chips.tsx`, `SimulationPanel.tsx`: where it is.
  - `results.ts`, `SimTags.tsx`, `ResultBar.tsx`: its result on the canvas.
  - `loopBody.ts`, `Iterations.tsx`, `SimulationResult.tsx`, `UsedValues.tsx`, `Failure.tsx`: its result in the panel.
  - `stale.ts`, `Refusal.tsx`: after edits, and refused.
  - `TestTab.tsx`, `seeds.ts`, `SeedField.tsx`, `StepResult.tsx`, `LatestResult.tsx`: the Test tab.
- Each with its test beside it.
- `e2e/simulation.spec.ts`, `e2e/fixtures/simulate.dewpoint.json`.

Changed:
- `components/Field.tsx` (a label is a `ReactNode`), `routes/editor/triggers/ScheduleForm.tsx` (imports
  `startInput`).
- `routes/editor/Editor.tsx`: the toolbar's button, the busy strip, the dialog, the panel, the bar, the canvas's tags,
  the Test tab, staleness, the conflict.
- `routes/editor/Canvas.tsx`, `StepCard.tsx`, `StartCard.tsx`: a step's and the start card's tags.
- `routes/editor/drawer/StepDrawer.tsx`: the Test tab.
- `routes/editor/Editor.test.tsx`; `playwright.config.ts`.
- Docs: the ledger.

## Milestones

1. **Starting** (Tasks 1–5): the ledger, the API layer, the input dialog, Simulate workflow in the toolbar, the
   Simulation panel's lifecycle. **Pause:** the owner's review.
2. **The result** (Tasks 6–8): on the canvas, in the panel, after edits and refused. **Pause:** the owner's review.
3. **Simulate step** (Tasks 9–12): the Test tab, the values and the send, a step test's result, the step in the latest
   simulation. **Pause:** the owner's review.
4. **Close** (Tasks 13–14): the e2e specs, every check, the final checkpoint. **Pause:** a fresh reviewer, the summary;
   then stop.

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
- **The branch** is settled with the owner at the start. The default proposed: `feat/editor-4d1c` from `origin/main`
  (44bc2f52, or later), in its own worktree (`~/4_dev/mist_dewpoint-4d1c`), with the docs branch
  `docs/editor-ui-4d1c-plan` (this plan) merged into it first. A later main is merged in, never rebased.
- **Where the code base differs from a step**, the executor stops at the diff that doesn't apply, adapts it test-first
  and records the difference as a mid-slice ruling in the ledger (M102 onward).
- **The rulings above** join the ledger only when the owner accepts the plan; until then the ledger says they're
  proposed.

---

# Milestone 1 — Starting

### Task 1: The ledger: 4d-1b merged, this plan proposed

**Files:**
- Modify: `docs/superpowers/plans/2026-10-05-editor-ui-4-ledger.md` (append at the end)

**Interfaces:**
- Consumes: nothing.
- Produces: the ledger sections later tasks append to (`### 4d-1c, milestone N`).

- [ ] **Step 1: Append the plan's status**

Append exactly:

```markdown
### 4d-1b merged; the 4d-1c plan proposed (2026-10-15)

The owner merged 4d-1b as #107 (squash 44bc2f52), CI green ("green and merged").
`docs/superpowers/plans/2026-10-15-editor-ui-4d1c-simulation.md`, revision 1: one plan for the whole of the spec's §7,
with milestone pauses (the owner, 2026-10-15: "One plan"). Its rulings (1–19) are proposed, and join this ledger as
191 onward only when the owner accepts the plan. Mid-slice rulings start at M102. The frontend only: no backend
change, no migration, no ABI change; the API's schema is 4d-1b's.
```

- [ ] **Step 2: Commit**

```bash
git add docs/superpowers/plans/2026-10-05-editor-ui-4-ledger.md
git commit -m "docs(editor-4): 4d-1b merged, the 4d-1c plan proposed

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: The editor's simulation, from the API

**Spec:** §7.1 (the frozen request), §7.2 (the lifecycle, polling), §6.6 (the reads).

**Files:**
- Create: `frontend/src/lib/simulations.ts`, `frontend/src/lib/simulations.test.ts`
- Create: `frontend/src/routes/editor/simulation/useSimulation.ts`,
  `frontend/src/routes/editor/simulation/useSimulation.test.tsx`

**Interfaces:**
- Consumes: `client`, `ok`, `ApiError`, `Schemas` (`lib/client.ts`); TanStack Query's `queryOptions`, `useQuery`,
  `useQueryClient`.
- Produces, in `lib/simulations.ts`:
  - types `SimulationRequest` (`Omit<SimulationOut, "version_id">`), `SimulationState`, `SimulationRun`,
    `SimulationSteps`, `StepSummary`, `StepInstances`, `SeedContract`, `SeedEntry`, `DraftStartForm`, `SimulateBody`,
    `Origin`;
  - `interface Frozen { key: string; revision: number; body: SimulateBody }`;
    `freeze(revision, body, key = crypto.randomUUID()): Frozen`;
  - `sendSimulation(tenantId, workflowId, frozen): Promise<SimulationRequest>` (`Idempotency-Key`, `If-Match`);
    `cancelSimulation(tenantId, requestId): Promise<"cancelled" | "requested">`;
  - `type Phase`, `ENDED: ReadonlySet<Phase>`, `phaseOf(state): Phase`, `pollEvery(reads): number` (1000, 1000,
    2000, 3000, then 5000 ms);
  - query factories: `draftStartFormQuery(t, w, revision)`, `latestSimulationQuery(t, w)`,
    `simulationStateQuery(t, w, requestId)`, `simulationStepsQuery(t, w, requestId)`,
    `stepInstancesQuery(t, w, requestId, stepId, { offset, limit, within? })`, `seedContractQuery(t, w, stepId,
    revision)`.
- Produces, in `useSimulation.ts`: `type Local` (`idle`, `submitting`, `unknown`, `refused`, `admitted`);
  `interface SimulationSession { local; state; steps; phase; busy; readFailed; asOf; start(frozen); checkAgain();
  cancel(); readAgain() }`; `useSimulation(tenantId, workflowId): SimulationSession`.

The frozen request is kept in memory: an answer lost (no answer, or a 5xx in the API's place) is `unknown`, and "Check
again" sends that same request under its key. A request admitted is read until it ends, with its steps; the steps are
read once more after the end. While idle, the person's latest simulation of the workflow is found, labelled `latest`.
A failed read keeps the last state, as of when it was read.

- [ ] **Step 1: Write the failing tests**

Apply:

```diff
diff --git a/frontend/src/lib/simulations.test.ts b/frontend/src/lib/simulations.test.ts
new file mode 100644
index 00000000..a79b4eb7
--- /dev/null
+++ b/frontend/src/lib/simulations.test.ts
@@ -0,0 +1,101 @@
+// SPDX-License-Identifier: Apache-2.0
+import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
+import { ApiError } from "./client";
+import {
+  ENDED, cancelSimulation, freeze, phaseOf, pollEvery, sendSimulation, type SimulationRequest, type SimulationState,
+} from "./simulations";  // prettier-ignore
+
+const request = (status: SimulationRequest["status"]): SimulationRequest => ({
+  id: "r1", workflow_id: "w1", draft_snapshot_id: "s1", draft_revision: 14, target_step_id: null,
+  mode: "simulate", source: "manual", status, reason: null, queued_at: "2026-10-15T10:42:05Z", ended_at: null,
+  admission_checks: [],
+});  // prettier-ignore
+
+const state = (
+  status: SimulationRequest["status"],
+  run: SimulationState["run"] = null,
+  cancel_requested = false,
+): SimulationState => ({ request: request(status), run, cancel_requested, read_back: "kept", input: {}, seeds: null });
+
+const run = (status: NonNullable<SimulationState["run"]>["status"]): SimulationState["run"] => ({
+  status, queued_at: null, started_at: "2026-10-15T10:42:06Z", ended_at: null, error: null, iterations: 0,
+});
+
+describe("where a simulation is (§7.2)", () => {
+  it("follows its request until its run is written, then its run", () => {
+    expect(phaseOf(state("queued"))).toBe("queued");
+    expect(phaseOf(state("starting"))).toBe("starting");
+    expect(phaseOf(state("started"))).toBe("starting"); // the run row isn't read yet
+    expect(phaseOf(state("started", run("running")))).toBe("running");
+    expect(phaseOf(state("started", run("succeeded")))).toBe("succeeded");
+    expect(phaseOf(state("started", run("deadline_exceeded")))).toBe("deadline_exceeded");
+    expect(phaseOf(state("refused"))).toBe("refused");
+    expect(phaseOf(state("dead"))).toBe("dead");
+    expect(phaseOf(state("cancelled"))).toBe("cancelled"); // cancelled while queued
+  });
+
+  it("says a cancel was requested until the server confirms it, never that it's cancelled", () => {
+    expect(phaseOf(state("starting", null, true))).toBe("cancel_requested");
+    expect(phaseOf(state("started", run("running"), true))).toBe("cancel_requested");
+    expect(phaseOf(state("started", run("cancelled"), true))).toBe("cancelled");
+    expect(phaseOf(state("started", run("succeeded"), true))).toBe("succeeded"); // it ended before the cancel landed
+  });
+
+  it("knows which phases have ended", () => {
+    expect([...ENDED].sort()).toEqual(["cancelled", "dead", "deadline_exceeded", "failed", "refused", "succeeded"]);
+  });
+});
+
+describe("how often it's read again (§7.2)", () => {
+  it("starts at 1 s and backs off to 5 s", () => {
+    expect([0, 1, 2, 3, 4, 5, 20].map(pollEvery)).toEqual([1000, 1000, 2000, 3000, 5000, 5000, 5000]);
+  });
+});
+
+describe("one request per submit (§7.1)", () => {
+  it("is frozen with a key of its own, sent again as it is", () => {
+    const a = freeze(14, { input: { site: "HQ" } });
+    const b = freeze(14, { input: { site: "HQ" } });
+    expect(a.key).not.toBe(b.key);
+    expect(a).toMatchObject({ revision: 14, body: { input: { site: "HQ" } } });
+  });
+});
+
+describe("the requests it makes", () => {
+  let sent: { method: string; path: string; headers: Headers; body: unknown }[];
+  let answer: () => Response;
+  beforeEach(() => {
+    sent = [];
+    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
+      const r = input as Request;
+      const text = await r.text();
+      sent.push({ method: r.method, path: new URL(r.url).pathname, headers: r.headers, body: text ? JSON.parse(text) : null });
+      return answer();
+    });
+  });
+  afterEach(() => vi.restoreAllMocks());
+  const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
+
+  it("sends a simulation with its key and the revision it was frozen at", async () => {
+    answer = () => json(request("queued"), 202);
+    const frozen = freeze(14, { target: { step_id: "n1", values: { "/vars/x": 1 }, absent: [] } }, "k1");
+    expect((await sendSimulation("t1", "w1", frozen)).id).toBe("r1");
+    expect(sent[0]).toMatchObject({ method: "POST", path: "/api/v1/t/t1/workflows/w1/draft/simulations" });
+    expect(sent[0]!.headers.get("Idempotency-Key")).toBe("k1");
+    expect(sent[0]!.headers.get("If-Match")).toBe("14");
+    expect(sent[0]!.body).toEqual({ target: { step_id: "n1", values: { "/vars/x": 1 }, absent: [] } });
+  });
+
+  it("says a refusal in the server's code", async () => {
+    answer = () => json({ error: "draft_conflict", draft_revision: 15 }, 409);
+    await expect(sendSimulation("t1", "w1", freeze(14, { input: {} }))).rejects.toMatchObject(
+      new ApiError(409, "draft_conflict", { error: "draft_conflict", draft_revision: 15 }),
+    );
+  });
+
+  it("cancels through the run's own route, saying whether it's done or requested", async () => {
+    answer = () => json({ cancel: "requested", request: request("starting") }, 202);
+    expect(await cancelSimulation("t1", "r1")).toBe("requested");
+    expect(sent[0]).toMatchObject({ method: "POST", path: "/api/v1/t/t1/runs/r1/cancel" });
+  });
+});
diff --git a/frontend/src/routes/editor/simulation/useSimulation.test.tsx b/frontend/src/routes/editor/simulation/useSimulation.test.tsx
new file mode 100644
index 00000000..1a08d310
--- /dev/null
+++ b/frontend/src/routes/editor/simulation/useSimulation.test.tsx
@@ -0,0 +1,130 @@
+// SPDX-License-Identifier: Apache-2.0
+import { QueryClient, QueryClientProvider, focusManager } from "@tanstack/react-query";
+import { act, renderHook, waitFor } from "@testing-library/react";
+import type { ReactNode } from "react";
+import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
+import { freeze, type SimulationRequest, type SimulationState } from "../../../lib/simulations";
+import { useSimulation } from "./useSimulation";
+
+const BASE = "/api/v1/t/t1/workflows/w1/draft/simulations";
+type Answer = () => Response | Promise<Response>;
+let answers: Map<string, Answer>;
+let sent: { method: string; path: string; key: string | null }[];
+const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
+
+const request = (status: SimulationRequest["status"], id = "r1"): SimulationRequest => ({
+  id, workflow_id: "w1", draft_snapshot_id: "s1", draft_revision: 14, target_step_id: null, mode: "simulate",
+  source: "manual", status, reason: null, queued_at: "2026-10-15T10:42:05Z", ended_at: null, admission_checks: [],
+});  // prettier-ignore
+const state = (status: SimulationRequest["status"], run: SimulationState["run"] = null, cancel_requested = false): SimulationState =>
+  ({ request: request(status), run, cancel_requested, read_back: "kept", input: {}, seeds: null });
+
+beforeEach(() => {
+  sent = [];
+  answers = new Map<string, Answer>([[`GET ${BASE}`, () => json([])]]);
+  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
+    const r = input as Request;
+    const path = new URL(r.url).pathname;
+    sent.push({ method: r.method, path, key: r.headers.get("Idempotency-Key") });
+    const answer = answers.get(`${r.method} ${path}`);
+    return answer ? answer() : json({ error: "not_found" }, 404);
+  });
+});
+afterEach(() => vi.restoreAllMocks());
+
+function session() {
+  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
+  const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
+  return renderHook(() => useSimulation("t1", "w1"), { wrapper });
+}
+
+describe("a simulation the editor sends (§7.1, §7.2)", () => {
+  it("is sent once, then read where it is, and holds Simulate while it hasn't ended", async () => {
+    answers.set(`POST ${BASE}`, () => json(request("queued"), 202));
+    answers.set(`GET ${BASE}/r1`, () => json(state("queued")));
+    const { result } = session();
+    await act(() => result.current.start(freeze(14, { input: {} }, "k1")));
+    await waitFor(() => expect(result.current.phase).toBe("queued"));
+    expect(result.current.busy).toBe(true);
+    expect(sent.filter((s) => s.method === "POST")).toEqual([{ method: "POST", path: BASE, key: "k1" }]);
+  });
+
+  it("whose answer is lost is unknown, and Check again sends the same request, its key unchanged", async () => {
+    answers.set(`POST ${BASE}`, () => Promise.reject(new TypeError("network")));
+    const { result } = session();
+    await act(() => result.current.start(freeze(14, { input: {} }, "k1")));
+    expect(result.current.local.kind).toBe("unknown");
+    expect(result.current.busy).toBe(true); // it may have started: never a second one meanwhile
+    answers.set(`POST ${BASE}`, () => json(request("starting"), 202));
+    answers.set(`GET ${BASE}/r1`, () => json(state("starting")));
+    await act(() => result.current.checkAgain());
+    await waitFor(() => expect(result.current.phase).toBe("starting"));
+    expect(sent.filter((s) => s.method === "POST").map((s) => s.key)).toEqual(["k1", "k1"]);
+  });
+
+  it("refused says so in the server's words, and leaves Simulate free", async () => {
+    answers.set(`POST ${BASE}`, () => json({ error: "csv_not_simulated", messages: ["This draft's input takes a CSV file…"] }, 422));
+    const { result } = session();
+    await act(() => result.current.start(freeze(14, { input: {} })));
+    expect(result.current.local).toMatchObject({ kind: "refused", error: { status: 422, code: "csv_not_simulated" } });
+    expect(result.current.busy).toBe(false);
+  });
+
+  it("can be cancelled, and is read again at once", async () => {
+    let cancelled = false;
+    answers.set(`POST ${BASE}`, () => json(request("started"), 202));
+    answers.set(`GET ${BASE}/r1`, () => json(state("started", { status: "running", queued_at: null, started_at: null, ended_at: null, error: null, iterations: 0 }, cancelled)));
+    answers.set("POST /api/v1/t/t1/runs/r1/cancel", () => {
+      cancelled = true;
+      return json({ cancel: "requested", request: request("started") }, 202);
+    });
+    const { result } = session();
+    await act(() => result.current.start(freeze(14, { input: {} })));
+    await waitFor(() => expect(result.current.phase).toBe("running"));
+    await act(async () => void (await result.current.cancel()));
+    await waitFor(() => expect(result.current.phase).toBe("cancel_requested"));
+  });
+
+  it("whose read fails keeps the last state it knew, and says so", async () => {
+    answers.set(`POST ${BASE}`, () => json(request("queued"), 202));
+    answers.set(`GET ${BASE}/r1`, () => json(state("queued")));
+    const { result } = session();
+    await act(() => result.current.start(freeze(14, { input: {} })));
+    await waitFor(() => expect(result.current.phase).toBe("queued"));
+    answers.set(`GET ${BASE}/r1`, () => json({ error: "unavailable" }, 503));
+    act(() => result.current.readAgain());
+    await waitFor(() => expect(result.current.readFailed).toBe(true));
+    expect(result.current.phase).toBe("queued");
+    expect(result.current.asOf).not.toBeNull();
+  });
+
+  it("is read again after a second, and not while the tab is hidden (§7.2)", async () => {
+    answers.set(`POST ${BASE}`, () => json(request("queued"), 202));
+    answers.set(`GET ${BASE}/r1`, () => json(state("queued")));
+    const reads = () => sent.filter((s) => s.method === "GET" && s.path === `${BASE}/r1`).length;
+    const { result } = session();
+    await act(() => result.current.start(freeze(14, { input: {} })));
+    await waitFor(() => expect(reads()).toBeGreaterThan(1), { timeout: 3000 }); // read again a second later
+    try {
+      act(() => focusManager.setFocused(false)); // the tab hidden
+      const hidden = reads();
+      await new Promise((r) => setTimeout(r, 2500)); // past the next read's time
+      expect(reads()).toBe(hidden);
+      act(() => focusManager.setFocused(true)); // shown again: read at once
+      await waitFor(() => expect(reads()).toBeGreaterThan(hidden));
+    } finally {
+      focusManager.setFocused(undefined);
+    }
+  });
+});
+
+describe("after a reload (§7.1)", () => {
+  it("finds the person's latest simulation of the workflow, labelled as exactly that", async () => {
+    answers.set(`GET ${BASE}`, () => json([request("started", "r9")]));
+    answers.set(`GET ${BASE}/r9`, () => json({ ...state("started", { status: "succeeded", queued_at: null, started_at: null, ended_at: "2026-10-15T10:42:19Z", error: null, iterations: 1 }), request: request("started", "r9") }));
+    const { result } = session();
+    await waitFor(() => expect(result.current.phase).toBe("succeeded"));
+    expect(result.current.local).toMatchObject({ kind: "admitted", latest: true, frozen: null });
+    expect(result.current.busy).toBe(false);
+  });
+});
```

- [ ] **Step 2: Run them**

Run: `npx --offline pnpm@12.6.0 exec vitest run src/lib/simulations.test.ts
src/routes/editor/simulation/useSimulation.test.tsx`

Expected: FAIL at collection, no test run: neither file can import its module ("Failed to resolve import" for
`./simulations` and `../../../lib/simulations`).

- [ ] **Step 3: Implement**

Apply:

```diff
diff --git a/frontend/src/lib/simulations.ts b/frontend/src/lib/simulations.ts
new file mode 100644
index 00000000..12816a63
--- /dev/null
+++ b/frontend/src/lib/simulations.ts
@@ -0,0 +1,127 @@
+// SPDX-License-Identifier: Apache-2.0
+// Simulating the draft (4d-1c; the simulation design §6.6, §7): the API's simulation routes, as the generated schema
+// types them (B1). One request per submit, frozen with its key and revision, sent again as it is when its answer is
+// lost (§7.1); where a simulation is, from its state (§7.2); how often it's read again.
+import { queryOptions } from "@tanstack/react-query";
+import { client, ok, type Schemas } from "./client";
+
+// `version_id` is always null for a simulation, and openapi-fetch drops a key typed only as null from an answer.
+export type SimulationRequest = Omit<Schemas["SimulationOut"], "version_id">;
+export type SimulationState = Omit<Schemas["SimulationStateOut"], "request"> & { request: SimulationRequest };
+export type SimulationRun = Schemas["SimulationRunOut"];
+export type SimulationSteps = Schemas["SimulationStepsOut"];
+export type StepSummary = Schemas["StepSummaryOut"];
+export type StepInstances = Schemas["StepInstancesOut"];
+export type SeedContract = Schemas["SeedContractOut"];
+export type SeedEntry = Schemas["SeedEntryOut"];
+export type DraftStartForm = Schemas["DraftStartFormOut"];
+export type SimulateBody = Schemas["SimulateIn"];
+export type Origin = StepSummary["origin"];
+
+/** A simulation as the editor sent it: its key, the revision it was frozen at and its body. An answer lost sends this
+ * same request again; while the first is kept, the server answers it rather than start a second (§7.1). */
+export interface Frozen {
+  key: string;
+  revision: number;
+  body: SimulateBody;
+}
+
+export const freeze = (revision: number, body: SimulateBody, key: string = crypto.randomUUID()): Frozen => ({ key, revision, body });
+
+const path = (tenantId: string, workflowId: string) => ({ tenant_id: tenantId, workflow_id: workflowId });
+
+/** Sends a frozen simulation: its request, admitted (202), or an ApiError in the server's words. */
+export function sendSimulation(tenantId: string, workflowId: string, frozen: Frozen): Promise<SimulationRequest> {
+  return ok(
+    client.POST("/api/v1/t/{tenant_id}/workflows/{workflow_id}/draft/simulations", {
+      params: {
+        path: path(tenantId, workflowId),
+        header: { "Idempotency-Key": frozen.key, "If-Match": String(frozen.revision) },
+      },
+      body: frozen.body,
+    }),
+  );
+}
+
+/** Cancels a simulation through its run's own route: `cancelled` when it was only queued, else `requested` (§6.6). */
+export async function cancelSimulation(tenantId: string, requestId: string): Promise<"cancelled" | "requested"> {
+  const answer = await ok(
+    client.POST("/api/v1/t/{tenant_id}/runs/{request_id}/cancel", { params: { path: { tenant_id: tenantId, request_id: requestId } } }),
+  );
+  return (answer as { cancel?: unknown }).cancel === "cancelled" ? "cancelled" : "requested";
+}
+
+/** Where a simulation is (§7.2). `cancel_requested`: still going, never said cancelled before the server does. */
+export type Phase =
+  | "queued" | "starting" | "running" | "cancel_requested"
+  | "succeeded" | "failed" | "cancelled" | "deadline_exceeded" | "refused" | "dead";  // prettier-ignore
+
+export const ENDED: ReadonlySet<Phase> = new Set(["succeeded", "failed", "cancelled", "deadline_exceeded", "refused", "dead"]);
+
+export function phaseOf(state: SimulationState): Phase {
+  const { request, run, cancel_requested } = state;
+  if (request.status === "queued" || request.status === "cancelled" || request.status === "refused" || request.status === "dead") {
+    return request.status;
+  }
+  if (run === null || run.status === "running") return cancel_requested ? "cancel_requested" : run === null ? "starting" : "running";
+  return run.status;
+}
+
+const STEPS = [1000, 1000, 2000, 3000];
+/** How long until a simulation is read again, after `reads` reads: 1 s at first, backing off to 5 s (§7.2). */
+export const pollEvery = (reads: number) => STEPS[reads] ?? 5000;
+
+/** The draft's input as a form, at the revision a simulation will send (§7.1). */
+export const draftStartFormQuery = (tenantId: string, workflowId: string, revision: number) =>
+  queryOptions({
+    queryKey: ["draft-start-form", tenantId, workflowId, revision],
+    queryFn: () =>
+      ok(client.GET("/api/v1/t/{tenant_id}/workflows/{workflow_id}/draft/start-form", { params: { path: path(tenantId, workflowId), query: { revision } } })),
+    staleTime: Infinity, // a revision's form never changes
+  });
+
+/** The person's latest simulation of the workflow, or null: what a reload finds (§7.1, "your latest simulation"). */
+export const latestSimulationQuery = (tenantId: string, workflowId: string) =>
+  queryOptions({
+    queryKey: ["simulations", tenantId, workflowId, "latest"],
+    queryFn: async () =>
+      (await ok(client.GET("/api/v1/t/{tenant_id}/workflows/{workflow_id}/draft/simulations", { params: { path: path(tenantId, workflowId), query: { limit: 1 } } })))[0] ?? null,
+  });
+
+/** A simulation where it is, its request and run, and what it ran with, redacted (§6.6). */
+export const simulationStateQuery = (tenantId: string, workflowId: string, requestId: string) =>
+  queryOptions({
+    queryKey: ["simulation", tenantId, workflowId, requestId],
+    queryFn: () =>
+      ok(client.GET("/api/v1/t/{tenant_id}/workflows/{workflow_id}/draft/simulations/{request_id}", { params: { path: { ...path(tenantId, workflowId), request_id: requestId } } })),
+  });
+
+/** A simulation's steps in run order, each with its counts and its data origin (§6.6, §7.4). */
+export const simulationStepsQuery = (tenantId: string, workflowId: string, requestId: string) =>
+  queryOptions({
+    queryKey: ["simulation-steps", tenantId, workflowId, requestId],
+    queryFn: () =>
+      ok(client.GET("/api/v1/t/{tenant_id}/workflows/{workflow_id}/draft/simulations/{request_id}/steps", { params: { path: { ...path(tenantId, workflowId), request_id: requestId } } })),
+  });
+
+/** A page of a step's instances, one per iteration, in iteration order (§6.6). */
+export const stepInstancesQuery = (
+  tenantId: string, workflowId: string, requestId: string, stepId: string, page: { offset: number; limit: number; within?: string },
+) =>
+  queryOptions({
+    queryKey: ["simulation-instances", tenantId, workflowId, requestId, stepId, page.offset, page.limit, page.within ?? null],
+    queryFn: () =>
+      ok(client.GET("/api/v1/t/{tenant_id}/workflows/{workflow_id}/draft/simulations/{request_id}/steps/{step_id}/instances", {
+        params: { path: { ...path(tenantId, workflowId), request_id: requestId, step_id: stepId }, query: { offset: page.offset, limit: page.limit, within: page.within } },
+      })),
+  });  // prettier-ignore
+
+/** A step's seed contract at a revision, each value prefilled where its step's own sample allows (§6.6, D-s2). */
+export const seedContractQuery = (tenantId: string, workflowId: string, stepId: string, revision: number) =>
+  queryOptions({
+    queryKey: ["seed-contract", tenantId, workflowId, stepId, revision],
+    queryFn: () =>
+      ok(client.GET("/api/v1/t/{tenant_id}/workflows/{workflow_id}/draft/steps/{step_id}/seeds", {
+        params: { path: { ...path(tenantId, workflowId), step_id: stepId }, query: { revision } },
+      })),
+  });  // prettier-ignore
diff --git a/frontend/src/routes/editor/simulation/useSimulation.ts b/frontend/src/routes/editor/simulation/useSimulation.ts
new file mode 100644
index 00000000..775078cf
--- /dev/null
+++ b/frontend/src/routes/editor/simulation/useSimulation.ts
@@ -0,0 +1,101 @@
+// SPDX-License-Identifier: Apache-2.0
+// The editor's simulation (4d-1c; the simulation design §7.1, §7.2; the Lifecycle board): one at a time, from this
+// editor. A submit is frozen with its key; its answer lost, "Check again" sends that same request, which can't start a
+// second time while the first is kept. Once admitted it's read where it is, at 1 s, backing off to 5 s, paused while
+// the tab is hidden; a failed read keeps the last state known, as of when it was read. After a reload there is no
+// frozen request: the person's latest simulation of the workflow is read, labelled as exactly that.
+import { useQuery, useQueryClient } from "@tanstack/react-query";
+import { useCallback, useEffect, useMemo, useState } from "react";
+import { ApiError } from "../../../lib/client";
+import {
+  ENDED, cancelSimulation, latestSimulationQuery, phaseOf, pollEvery, sendSimulation, simulationStateQuery,
+  simulationStepsQuery, type Frozen, type Phase, type SimulationRequest, type SimulationState, type SimulationSteps,
+} from "../../../lib/simulations";  // prettier-ignore
+
+/** Where the editor's own part of a simulation is: before an answer, or after one. */
+export type Local =
+  | { kind: "idle" }
+  | { kind: "submitting"; frozen: Frozen }
+  | { kind: "unknown"; frozen: Frozen } // its answer was lost: it may have started
+  | { kind: "refused"; frozen: Frozen; error: ApiError } // admission said no, in the server's words
+  | { kind: "admitted"; frozen: Frozen | null; request: SimulationRequest; latest: boolean };
+
+export interface SimulationSession {
+  local: Local;
+  state: SimulationState | null; // the newest read
+  steps: SimulationSteps | null; // its steps, read with it
+  phase: Phase | null;
+  /** Simulate waits: a submit, an answer lost, or a simulation not ended (§7.1). */
+  busy: boolean;
+  /** The last read failed: what's shown is as of `asOf` (§7.2). */
+  readFailed: boolean;
+  asOf: number | null;
+  start: (frozen: Frozen) => Promise<void>;
+  checkAgain: () => Promise<void>;
+  cancel: () => Promise<"cancelled" | "requested" | null>;
+  readAgain: () => void;
+}
+
+/** Whether a request's outcome is unknown: no answer reached the editor, or a 5xx came in the API's place. */
+const uncertain = (e: unknown) => !(e instanceof ApiError) || e.status >= 500;
+
+export function useSimulation(tenantId: string, workflowId: string): SimulationSession {
+  const qc = useQueryClient();
+  const [local, setLocal] = useState<Local>({ kind: "idle" });
+  const latest = useQuery({ ...latestSimulationQuery(tenantId, workflowId), enabled: local.kind === "idle" });
+  useEffect(() => {
+    const found = latest.data;
+    if (found) setLocal((l) => (l.kind === "idle" ? { kind: "admitted", frozen: null, request: found, latest: true } : l));
+  }, [latest.data]);
+
+  const requestId = local.kind === "admitted" ? local.request.id : null;
+  const read = useQuery({
+    ...simulationStateQuery(tenantId, workflowId, requestId ?? ""),
+    enabled: requestId !== null,
+    refetchInterval: (q) => (q.state.data && ENDED.has(phaseOf(q.state.data)) ? false : pollEvery(q.state.dataUpdateCount + q.state.errorUpdateCount)),
+  });
+  const state = requestId !== null ? (read.data ?? null) : null;
+  const phase = state ? phaseOf(state) : null;
+  const ended = phase !== null && ENDED.has(phase);
+  const stepsRead = useQuery({
+    ...simulationStepsQuery(tenantId, workflowId, requestId ?? ""),
+    enabled: requestId !== null && phase !== null && phase !== "refused" && phase !== "dead",
+    refetchInterval: (q) => (ended ? false : pollEvery(q.state.dataUpdateCount + q.state.errorUpdateCount)),
+  });
+  // Its steps as they were when it ended: read once more after the end is known.
+  useEffect(() => {
+    if (ended && requestId !== null) void qc.invalidateQueries({ queryKey: ["simulation-steps", tenantId, workflowId, requestId] });
+  }, [ended, requestId, qc, tenantId, workflowId]);
+
+  const send = useCallback(
+    async (frozen: Frozen) => {
+      setLocal({ kind: "submitting", frozen });
+      try {
+        const request = await sendSimulation(tenantId, workflowId, frozen);
+        setLocal({ kind: "admitted", frozen, request, latest: false });
+      } catch (e) {
+        setLocal(uncertain(e) ? { kind: "unknown", frozen } : { kind: "refused", frozen, error: e as ApiError });
+      }
+    },
+    [tenantId, workflowId],
+  );
+  const checkAgain = useCallback(async () => {
+    if (local.kind === "unknown") await send(local.frozen);
+  }, [local, send]);
+  const cancel = useCallback(async () => {
+    if (requestId === null) return null;
+    const done = await cancelSimulation(tenantId, requestId);
+    await qc.invalidateQueries({ queryKey: ["simulation", tenantId, workflowId, requestId] });
+    return done;
+  }, [qc, requestId, tenantId, workflowId]);
+  const readAgain = useCallback(() => void read.refetch(), [read]);
+
+  const busy = local.kind === "submitting" || local.kind === "unknown" || (local.kind === "admitted" && !ended);
+  return useMemo(
+    () => ({
+      local, state, steps: requestId !== null ? (stepsRead.data ?? null) : null, phase, busy,
+      readFailed: read.isRefetchError, asOf: read.dataUpdatedAt || null, start: send, checkAgain, cancel, readAgain,
+    }),
+    [local, state, requestId, stepsRead.data, phase, busy, read.isRefetchError, read.dataUpdatedAt, send, checkAgain, cancel, readAgain],
+  );  // prettier-ignore
+}
```

- [ ] **Step 4: Run them again**

Run: the same command.

Expected: PASS, 15 passed (the hidden tab's test waits out 2.5 s).

- [ ] **Step 5: Static checks**

Run: the two of "How to run things". Expected: no output.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/simulations.ts frontend/src/lib/simulations.test.ts frontend/src/routes/editor/simulation
git commit -m "feat(editor): a simulation of the draft, sent once with its key and read until it ends (4d-1c)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: The input dialog

**Spec:** §7.1 (the input dialog); the InputFields and InputJson boards.

**Files:**
- Create: `frontend/src/lib/skeleton.ts`, `frontend/src/lib/skeleton.test.ts`
- Create: `frontend/src/routes/editor/startInput.tsx` (moved from `ScheduleForm.tsx`)
- Create: `frontend/src/components/Tag.tsx`, `frontend/src/routes/editor/simulation/SimBanner.tsx`
- Create: `frontend/src/routes/editor/simulation/SimulateDialog.tsx`,
  `frontend/src/routes/editor/simulation/SimulateDialog.test.tsx`
- Modify: `frontend/src/components/Field.tsx` (a label is a `ReactNode`),
  `frontend/src/routes/editor/triggers/ScheduleForm.tsx` (imports `startInput.tsx`)

**Interfaces:**
- Consumes: `draftStartFormQuery` (Task 2); `triggerTypesQuery`; the start form's field helpers, now in
  `startInput.tsx`.
- Produces:
  - `skeletonOf(schema, root, depth?)`: every declared field, a list with one item, an enum's or const's first value,
    an `anyOf`/`oneOf`/`allOf`'s first branch, null where unknown; 8 levels at most.
  - `startInput.tsx`: `Entry`, `entryOf`, `JSON_HINT`, `nameOf`, `valueOf`, `shownOf`, `textOf`, `fieldKey`,
    `fromFields(form, values, required, requiredWords?)`, `listed`, `InputControl({ f, value, error, onChange, label?,
    hint? })`, `startValues(form)`, `SHOWN`, `fieldsShow`, `wholeOf`.
  - `Tag({ children })`; `SimBanner({ children, role? })` (hatched slate).
  - `SimulateDialog({ tenantId, workflowId, name, revision, doc, onSimulate(input), onClose })`.

The dialog reads the draft's start form at the revision the save made. Fields show as the published form's do, with
"required" and "sensitive" tags and their hints; "Edit as JSON" switches to the whole input. A Mist-event input starts
from a skeleton of the draft's own schema, labelled as such; an input `fieldsShow` can't show is entered as JSON from
its skeleton. A draft whose input takes a CSV file says it can't be simulated whole, and Simulate stays disabled.

- [ ] **Step 1: Write the failing tests**

Apply:

```diff
diff --git a/frontend/src/lib/skeleton.test.ts b/frontend/src/lib/skeleton.test.ts
new file mode 100644
index 00000000..b1eee75e
--- /dev/null
+++ b/frontend/src/lib/skeleton.test.ts
@@ -0,0 +1,40 @@
+// SPDX-License-Identifier: Apache-2.0
+import { describe, expect, it } from "vitest";
+import { skeletonOf } from "./skeleton";
+
+describe("a skeleton of an input (§7.1; the InputJson board)", () => {
+  it("fills every field the input declares with an empty value of its type, optional ones too", () => {
+    expect(
+      skeletonOf({
+        type: "object",
+        properties: { topic: { type: "string" }, n: { type: "integer" }, x: { type: "number" }, on: { type: "boolean" }, gone: { type: "null" } },
+        required: ["topic"],
+      }),
+    ).toEqual({ topic: "", n: 0, x: 0, on: false, gone: null });
+  });
+
+  it("gives a list one item, so its shape shows, and follows references", () => {
+    const schema = {
+      type: "object",
+      properties: { events: { type: "array", items: { $ref: "#/$defs/event" } } },
+      $defs: { event: { type: "object", properties: { mac: { type: "string" }, timestamp: { type: "integer" } } } },
+    };
+    expect(skeletonOf(schema)).toEqual({ events: [{ mac: "", timestamp: 0 }] });
+  });
+
+  it("takes a choice's first branch, a nullable type's other type, and an enum's first value", () => {
+    expect(skeletonOf({ anyOf: [{ type: "string" }, { type: "integer" }] })).toBe("");
+    expect(skeletonOf({ type: ["null", "integer"] })).toBe(0);
+    expect(skeletonOf({ type: "string", enum: ["up", "down"] })).toBe("up");
+  });
+
+  it("stops where it would go on forever: a schema that refers to itself", () => {
+    const schema = { $defs: { node: { type: "object", properties: { next: { $ref: "#/$defs/node" } } } }, $ref: "#/$defs/node" };
+    expect(JSON.stringify(skeletonOf(schema)).length).toBeLessThan(400);
+  });
+
+  it("leaves what it can't tell as null", () => {
+    expect(skeletonOf({})).toBeNull();
+    expect(skeletonOf({ $ref: "#/$defs/missing" })).toBeNull();
+  });
+});
diff --git a/frontend/src/routes/editor/simulation/SimulateDialog.test.tsx b/frontend/src/routes/editor/simulation/SimulateDialog.test.tsx
new file mode 100644
index 00000000..3a917c53
--- /dev/null
+++ b/frontend/src/routes/editor/simulation/SimulateDialog.test.tsx
@@ -0,0 +1,128 @@
+// SPDX-License-Identifier: Apache-2.0
+import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
+import { render, screen } from "@testing-library/react";
+import userEvent from "@testing-library/user-event";
+import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
+import type { DraftStartForm } from "../../../lib/simulations";
+import type { GraphDoc } from "../../../lib/workflows";
+import { SimulateDialog } from "./SimulateDialog";
+
+const SCHEMA = {
+  type: "object",
+  properties: { site: { type: "string" }, floor: { type: "integer" }, api_token: { type: "string", "x-sensitive": true } },
+  required: ["site", "api_token"],
+};
+const FORM: DraftStartForm = {
+  workflow_id: "w1",
+  draft_revision: 14,
+  csv: null,
+  fields: [
+    { name: "site", title: "Site", type: "string", required: true, sensitive: false, description: "The site's name, as in Mist." },
+    { name: "floor", title: "Floor", type: "integer", required: false, sensitive: false },
+    { name: "api_token", title: "API token", type: "string", required: true, sensitive: true },
+  ],
+};
+const EVENT = {
+  type: "object",
+  properties: { topic: { type: "string" }, events: { type: "array", items: { type: "object", properties: { mac: { type: "string" }, timestamp: { type: "integer" } } } } },
+};  // prettier-ignore
+const doc = (input_schema: unknown): GraphDoc => ({ graph_format: 1, nodes: [], edges: [], settings: { input_schema } }) as unknown as GraphDoc;
+
+let form: DraftStartForm;
+let types: unknown[];
+let asked: string[];
+const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
+beforeEach(() => {
+  form = FORM;
+  types = [];
+  asked = [];
+  vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
+    const url = new URL((input as Request).url);
+    asked.push(url.pathname + url.search);
+    if (url.pathname === "/api/v1/t/t1/workflows/w1/draft/start-form") return Promise.resolve(json(form));
+    if (url.pathname === "/api/v1/trigger-types") return Promise.resolve(json(types));
+    return Promise.resolve(json({ error: "not_found" }, 404));
+  });
+});
+afterEach(() => vi.restoreAllMocks());
+
+/** What a control's description says: its hint and its error, as a screen reader reads them. */
+const description = (el: HTMLElement) =>
+  (el.getAttribute("aria-describedby") ?? "").split(" ").filter(Boolean).map((id) => document.getElementById(id)?.textContent ?? "").join(" ");
+
+function show(input: unknown = SCHEMA) {
+  const onSimulate = vi.fn();
+  const onClose = vi.fn();
+  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
+  render(
+    <QueryClientProvider client={qc}>
+      <SimulateDialog tenantId="t1" workflowId="w1" name="AP offline alert" revision={14} doc={doc(input)} onSimulate={onSimulate} onClose={onClose} />
+    </QueryClientProvider>,
+  );
+  return { onSimulate, onClose };
+}
+
+describe("Simulate workflow's input (§7.1; the InputFields, InputJson boards)", () => {
+  it("is the draft's own form at the revision being simulated, sensitive values typed, never shown", async () => {
+    const { onSimulate } = show();
+    expect(await screen.findByRole("heading", { name: "Simulate workflow" })).toBeTruthy();
+    expect(screen.getByText("AP offline alert · draft revision 14")).toBeTruthy();
+    expect(asked).toContain("/api/v1/t/t1/workflows/w1/draft/start-form?revision=14");
+    expect(description(await screen.findByLabelText("Site required"))).toBe("The site's name, as in Mist.");
+    expect(description(screen.getByLabelText("Floor"))).toBe("Optional: left out when empty.");
+    const token = screen.getByLabelText("API token required sensitive");
+    expect(token.getAttribute("type")).toBe("password");
+    expect(description(token)).toBe("Stored as a protected value: results show it as redacted.");
+    await userEvent.type(screen.getByLabelText("Site required"), "HQ Paris");
+    await userEvent.type(token, "t0ken");
+    await userEvent.click(screen.getByRole("button", { name: "◌ Simulate" }));
+    expect(onSimulate).toHaveBeenCalledWith({ site: "HQ Paris", api_token: "t0ken" }); // an empty optional field is left out
+  });
+
+  it("asks for a required value before anything is sent", async () => {
+    const { onSimulate } = show();
+    await userEvent.click(await screen.findByRole("button", { name: "◌ Simulate" }));
+    expect(description(await screen.findByLabelText("Site required"))).toContain("Give a value: the input requires it.");
+    expect(onSimulate).not.toHaveBeenCalled();
+  });
+
+  it("can be edited as JSON, what's typed going with it", async () => {
+    const { onSimulate } = show();
+    await userEvent.type(await screen.findByLabelText("Site required"), "HQ");
+    await userEvent.click(screen.getByRole("button", { name: "Edit as JSON" }));
+    const area = screen.getByLabelText("The input, as JSON");
+    expect(JSON.parse((area as HTMLTextAreaElement).value)).toEqual({ site: "HQ" });
+    await userEvent.clear(area);
+    await userEvent.type(area, '{{"site": "HQ", "floor": 2, "api_token": "x"}');
+    await userEvent.click(screen.getByRole("button", { name: "◌ Simulate" }));
+    expect(onSimulate).toHaveBeenCalledWith({ site: "HQ", floor: 2, api_token: "x" });
+  });
+
+  it("starts a Mist event's input from a skeleton of its shape, labelled as such", async () => {
+    types = [{ key: "mist", label: "Mist", plugin: "mist", topic_pointer: "/topic", endpoint: {}, topics: { "device-events": EVENT } }];
+    form = { ...FORM, fields: [] };
+    const { onSimulate } = show(EVENT);
+    const area = await screen.findByLabelText("Input, as a device-events event");
+    expect(JSON.parse((area as HTMLTextAreaElement).value)).toEqual({ topic: "", events: [{ mac: "", timestamp: 0 }] });
+    expect(description(area)).toBe("A generated skeleton: every field the input declares, filled with empty values of its type. Fill it with the event you want to try.");
+    await userEvent.click(screen.getByRole("button", { name: "◌ Simulate" }));
+    expect(onSimulate).toHaveBeenCalledWith({ topic: "", events: [{ mac: "", timestamp: 0 }] });
+  });
+
+  it("says a CSV input can't be simulated whole yet, and that Simulate step still works", async () => {
+    form = { ...FORM, csv: { max_rows: 10, max_bytes: 1000, columns: [] } };
+    const { onClose } = show();
+    expect(await screen.findByText(/This draft's input takes a CSV file, and a simulation can't take one yet\./)).toBeTruthy();
+    expect(screen.getByText(/Simulate step still works: a step's values, rows included, are typed in its Test tab\./)).toBeTruthy();
+    expect(screen.getByRole("button", { name: "◌ Simulate" })).toHaveProperty("disabled", true);
+    await userEvent.click(screen.getByRole("button", { name: "Close" }));
+    expect(onClose).toHaveBeenCalled();
+  });
+
+  it("is cancelled without sending anything", async () => {
+    const { onSimulate, onClose } = show();
+    await userEvent.click(await screen.findByRole("button", { name: "Cancel" }));
+    expect(onClose).toHaveBeenCalled();
+    expect(onSimulate).not.toHaveBeenCalled();
+  });
+});
```

- [ ] **Step 2: Run them**

Run: `npx --offline pnpm@12.6.0 exec vitest run src/lib/skeleton.test.ts
src/routes/editor/simulation/SimulateDialog.test.tsx src/components/Field.test.tsx src/routes/editor/triggers`

Expected: FAIL at collection for `skeleton.test.ts` and `SimulateDialog.test.tsx` ("Failed to resolve import" for
`./skeleton` and `./SimulateDialog`); the field's and the triggers' tests, 72, pass.

- [ ] **Step 3: Implement**

Apply:

```diff
diff --git a/frontend/src/components/Field.tsx b/frontend/src/components/Field.tsx
index 4022bf45..bd4ab6fe 100644
--- a/frontend/src/components/Field.tsx
+++ b/frontend/src/components/Field.tsx
@@ -9,7 +9,7 @@ const CONTROL = "min-h-11 w-full min-w-0 rounded-lg border bg-surface px-3 text-
 export const controlClass = (invalid: boolean): string => `${CONTROL} ${invalid ? "border-danger" : "border-line-control"}`;
 
 interface Labelled {
-  label: string;
+  label: ReactNode; // its text, with what a form adds beside it (a "required" tag)
   hint?: ReactNode;
   error?: string;
 }
diff --git a/frontend/src/components/Tag.tsx b/frontend/src/components/Tag.tsx
new file mode 100644
index 00000000..f091a6c3
--- /dev/null
+++ b/frontend/src/components/Tag.tsx
@@ -0,0 +1,8 @@
+// SPDX-License-Identifier: Apache-2.0
+// A word beside a label (4d-1c; the InputFields and TestTab boards): what a field is, said in words, never colour
+// alone (§7.4). Small, muted and outlined: data about the field, not a button.
+import type { ReactNode } from "react";
+
+export function Tag({ children }: { children: ReactNode }) {
+  return <span className="ms-1.5 rounded-sm border border-line-strong px-1.5 text-meta font-normal text-muted">{children}</span>;
+}
diff --git a/frontend/src/lib/skeleton.ts b/frontend/src/lib/skeleton.ts
new file mode 100644
index 00000000..2a524749
--- /dev/null
+++ b/frontend/src/lib/skeleton.ts
@@ -0,0 +1,29 @@
+// SPDX-License-Identifier: Apache-2.0
+// A skeleton of an input (4d-1c; the simulation design §7.1, the InputJson board): every field its schema declares,
+// optional ones too, filled with an empty value of its type, a list with one item so its shape shows. The Mist
+// catalogue keeps no examples (plugins/mist/schemas.py), so a Mist event's input starts from this, labelled as such.
+import { deref, isObject, type Schema } from "./schemaForm";
+
+const DEPTH = 8; // deep enough for an event's shape; a schema that refers to itself stops here
+
+const EMPTY: Record<string, unknown> = { string: "", integer: 0, number: 0, boolean: false, null: null };
+
+export function skeletonOf(schema: unknown, root: Schema = isObject(schema) ? schema : {}, depth = 0): unknown {
+  if (depth > DEPTH) return null;
+  const s = deref(schema, root);
+  for (const key of ["anyOf", "oneOf", "allOf"]) {
+    const branches = s[key];
+    if (Array.isArray(branches) && branches.length > 0 && s.type === undefined && s.properties === undefined) {
+      return skeletonOf(branches[0], root, depth + 1);
+    }
+  }
+  if (Array.isArray(s.enum) && s.enum.length > 0) return s.enum[0] as unknown;
+  if ("const" in s) return s.const;
+  const type = Array.isArray(s.type) ? ((s.type as unknown[]).find((t) => t !== "null") ?? "null") : s.type;
+  if (type === "object" || isObject(s.properties)) {
+    const properties = isObject(s.properties) ? s.properties : {};
+    return Object.fromEntries(Object.entries(properties).map(([name, p]) => [name, skeletonOf(p, root, depth + 1)]));
+  }
+  if (type === "array") return s.items === undefined ? [] : [skeletonOf(s.items, root, depth + 1)];
+  return typeof type === "string" && type in EMPTY ? EMPTY[type] : null;
+}
diff --git a/frontend/src/routes/editor/simulation/SimBanner.tsx b/frontend/src/routes/editor/simulation/SimBanner.tsx
new file mode 100644
index 00000000..52a5dcd5
--- /dev/null
+++ b/frontend/src/routes/editor/simulation/SimBanner.tsx
@@ -0,0 +1,12 @@
+// SPDX-License-Identifier: Apache-2.0
+// What a simulation is, said wherever one is started or shown (D2, D3; §7.1, §7.3): slate with the hatch, never live
+// orange. The hatch sits only behind slate text (`text-sim`), which holds 4.5:1 over it.
+import type { ReactNode } from "react";
+
+export function SimBanner({ children, role }: { children: ReactNode; role?: "status" }) {
+  return (
+    <div role={role} className="hatch-sim flex flex-col gap-1.5 rounded-lg border border-sim bg-sim-bg px-3 py-2 text-small text-sim">
+      {children}
+    </div>
+  );
+}
diff --git a/frontend/src/routes/editor/simulation/SimulateDialog.tsx b/frontend/src/routes/editor/simulation/SimulateDialog.tsx
new file mode 100644
index 00000000..a20965b8
--- /dev/null
+++ b/frontend/src/routes/editor/simulation/SimulateDialog.tsx
@@ -0,0 +1,159 @@
+// SPDX-License-Identifier: Apache-2.0
+// Simulate workflow's input (4d-1c; the simulation design §7.1; the InputFields, InputJson and Narrow boards): the
+// draft's own form at the revision it will send, its fields as a schedule's form enters them, or as JSON. An input in
+// a Mist event's shape, or with rules no field shows, is entered as JSON from a skeleton of its schema, labelled as
+// such (the catalogue keeps no examples). A draft whose input takes a CSV can't be simulated whole yet: the dialog says
+// so, and that Simulate step still works. Submitting hands the input to the editor, which freezes and sends it.
+import { useQuery } from "@tanstack/react-query";
+import { useEffect, useId, useRef, useState, type FormEvent } from "react";
+import { Button } from "../../../components/Button";
+import { TextArea } from "../../../components/Field";
+import { Tag } from "../../../components/Tag";
+import { inputOf, topicShaped } from "../../../lib/input";
+import { draftStartFormQuery } from "../../../lib/simulations";
+import { skeletonOf } from "../../../lib/skeleton";
+import { triggerTypesQuery, type StartField } from "../../../lib/triggers";
+import type { GraphDoc } from "../../../lib/workflows";
+import { InputControl, fieldKey, fieldsShow, fromFields, nameOf, startValues, wholeOf } from "../startInput";
+import { SimBanner } from "./SimBanner";
+
+const REQUIRED = "Give a value: the input requires it.";
+const SKELETON = "A generated skeleton: every field the input declares, filled with empty values of its type. Fill it with the event you want to try.";
+
+/** A field's label, with what it is beside it, and what its hint adds: optional ones are left out when empty, sensitive
+ * ones stored as protected values (the InputFields board). */
+const labelOf = (f: StartField) => (
+  <>
+    {nameOf(f)}
+    {f.required && <> <Tag>required</Tag></>}
+    {f.sensitive && <> <Tag>sensitive</Tag></>}
+  </>
+);
+const hintOf = (f: StartField) =>
+  [
+    f.description,
+    f.required ? null : "Optional: left out when empty.",
+    f.sensitive ? "Stored as a protected value: results show it as redacted." : null,
+  ].filter(Boolean).join(" ") || undefined;  // prettier-ignore
+
+export function SimulateDialog({ tenantId, workflowId, name, revision, doc, onSimulate, onClose }: {
+  tenantId: string; workflowId: string; name: string; revision: number; doc: GraphDoc;
+  onSimulate: (input: Record<string, unknown>) => void; onClose: () => void;
+}) {  // prettier-ignore
+  const id = useId();
+  const dialog = useRef<HTMLDialogElement>(null);
+  useEffect(() => {
+    const d = dialog.current;
+    if (d && !d.open) d.showModal();
+  }, []);
+  const form = useQuery(draftStartFormQuery(tenantId, workflowId, revision));
+  const types = useQuery(triggerTypesQuery);
+  const schema = inputOf(doc);
+  const webhook = (types.data ?? []).find((t) => Object.keys(t.topics).length > 0);
+  const topic = webhook ? topicShaped(schema, webhook.topics) : null;
+  const whole = topic !== null || !fieldsShow(schema); // the fields can't show it: entered as JSON
+  const resolving = form.isPending || types.isPending; // how it's entered isn't known before both are read
+  const [asJson, setAsJson] = useState(false);
+  const json = whole || asJson;
+  const [values, setValues] = useState<ReadonlyMap<string, string> | null>(null);
+  const shownValues = values ?? (form.data ? startValues(form.data) : new Map<string, string>());
+  const [jsonText, setJsonText] = useState<string | null>(null);
+  const [errors, setErrors] = useState<Record<string, string>>({});
+  const seeded = () => {
+    if (whole) return JSON.stringify(skeletonOf(schema), null, 2);
+    const made = form.data ? fromFields(form.data, shownValues, false) : { input: {} };
+    return "input" in made && Object.keys(made.input).length > 0 ? JSON.stringify(made.input, null, 2) : "";
+  };
+  const shownJson = jsonText ?? seeded();
+  const csv = form.data?.csv != null;
+
+  /** What's in the fields, as JSON; a field whose value doesn't read keeps the form where it is, saying why. */
+  const toJson = () => {
+    if (!form.data) return;
+    const made = fromFields(form.data, shownValues, false);
+    if ("problems" in made) return setErrors(made.problems);
+    setErrors({});
+    setJsonText(Object.keys(made.input).length > 0 ? JSON.stringify(made.input, null, 2) : "");
+    setAsJson(true);
+  };
+
+  function submit(e: FormEvent) {
+    e.preventDefault();
+    if (csv || resolving || !form.data) return;
+    if (json) {
+      const read = wholeOf(shownJson);
+      if ("problem" in read) return setErrors({ input: read.problem });
+      return onSimulate(read.value);
+    }
+    const made = fromFields(form.data, shownValues, true, () => REQUIRED);
+    if ("problems" in made) return setErrors(made.problems);
+    onSimulate(made.input);
+  }
+
+  return (
+    <dialog
+      ref={dialog}
+      aria-labelledby={`${id}-title`}
+      onClose={onClose}
+      className="mx-auto mt-16 w-[560px] max-w-[calc(100vw-32px)] rounded-dialog border border-line bg-surface p-6 text-ink shadow-dialog backdrop:bg-overlay"
+    >
+      <form onSubmit={submit} className="flex flex-col gap-4">
+        <header>
+          <h2 id={`${id}-title`} className="text-h3 font-semibold">Simulate workflow</h2>
+          <p className="text-small text-muted">{`${name} · draft revision ${revision}`}</p>
+        </header>
+        <SimBanner>
+          <p>
+            <strong>Simulated.</strong> Nothing is sent: actions return fixtures instead of calling out, and the other steps
+            evaluate as they would live. Results don&apos;t prove the live call will succeed.
+          </p>
+        </SimBanner>
+        {resolving ? (
+          <p className="text-small text-muted">Loading the draft&apos;s input…</p>
+        ) : form.isError ? (
+          <p role="alert" className="text-small text-danger">The draft&apos;s input couldn&apos;t be read. Close this and simulate again.</p>
+        ) : csv ? (
+          <p className="text-small">
+            This draft&apos;s input takes a CSV file, and a simulation can&apos;t take one yet. Its rows come only from an uploaded
+            file, so the whole workflow can&apos;t be simulated until then. Simulate step still works: a step&apos;s values, rows
+            included, are typed in its Test tab.
+          </p>
+        ) : json ? (
+          <>
+            <TextArea
+              label={topic ? `Input, as a ${topic} event` : "The input, as JSON"}
+              hint={whole ? SKELETON : 'An object, like {"site": "HQ"}. Shown as typed, a sensitive value too.'}
+              error={errors.input}
+              value={shownJson}
+              rows={12}
+              spellCheck={false}
+              className="font-mono"
+              onChange={(e) => setJsonText(e.target.value)}
+            />
+          </>
+        ) : (
+          <>
+            {form.data.fields.length === 0 && <p className="text-small text-muted">This draft takes no input.</p>}
+            {form.data.fields.map((f) => (
+              <InputControl
+                key={f.name} f={f} value={shownValues.get(f.name)} error={errors[fieldKey(f.name)]} label={labelOf(f)} hint={hintOf(f)}
+                onChange={(v) => setValues(new Map(shownValues).set(f.name, v))}
+              />
+            ))}
+          </>
+        )}
+        {!resolving && !csv && !whole && form.data && (
+          <div>
+            <Button size="sm" aria-pressed={asJson} onClick={() => (asJson ? (setAsJson(false), setJsonText(null)) : toJson())}>
+              Edit as JSON
+            </Button>
+          </div>
+        )}
+        <div className="flex flex-wrap justify-end gap-2">
+          <Button onClick={onClose}>{csv ? "Close" : "Cancel"}</Button>
+          <Button type="submit" variant="simulate" disabled={csv || resolving || form.isError}>◌ Simulate</Button>
+        </div>
+      </form>
+    </dialog>
+  );
+}
diff --git a/frontend/src/routes/editor/startInput.tsx b/frontend/src/routes/editor/startInput.tsx
new file mode 100644
index 00000000..d02c32db
--- /dev/null
+++ b/frontend/src/routes/editor/startInput.tsx
@@ -0,0 +1,147 @@
+// SPDX-License-Identifier: Apache-2.0
+// A start form's input (4c-3b; shared since 4d-1c): each field of a form as its control, what's typed read back as the
+// input's values, and the input entered whole as JSON where the fields can't show its rules. A schedule's form and the
+// Simulate workflow dialog both enter an input this way; a sensitive field is never prefilled with what it hides.
+import type { ReactNode } from "react";
+import { Field, Select, TextArea } from "../../components/Field";
+import { parseJson } from "../../lib/config";
+import { isObject } from "../../lib/schemaForm";
+import type { StartField } from "../../lib/triggers";
+import { parseNumber } from "../../lib/unapplied";
+
+/** How a field of the input is entered: one of its values, as its type says, or JSON for what the simple controls can't
+ * hold (a list, an object, several types or none), each value's type kept (the review of revision 1). */
+export type Entry = "choice" | "yesno" | "whole" | "number" | "text" | "json";
+
+export function entryOf(f: StartField): Entry {
+  if (Array.isArray(f.enum) && !f.enum_masked) return "choice";
+  const type: unknown = f.type;
+  return type === "boolean" ? "yesno" : type === "integer" ? "whole" : type === "number" ? "number" : type === "string" ? "text" : "json";
+}
+
+export const JSON_HINT = 'As JSON, like ["ap-1"] or {"site": "HQ"}; text in quotes.';
+
+export const nameOf = (f: StartField) => f.title ?? f.name;
+
+/** What's typed for one field of the input, as the input holds it: nothing given is left out. A choice's option is its
+ * value as JSON, so a number stays a number; JSON a parse would change (a number too large, a whole one past 2^53) is
+ * refused, as the draft's is. */
+export function valueOf(f: StartField, typed: string | undefined): { value: unknown } | { problem: string } {
+  if (typed === undefined || typed === "") return { value: undefined };
+  const entry = entryOf(f);
+  if (entry === "choice") return { value: JSON.parse(typed) as unknown };
+  if (entry === "yesno") return { value: typed === "true" };
+  if (entry === "whole" || entry === "number") {
+    const parsed = parseNumber(typed, entry === "whole");
+    return "problem" in parsed ? parsed : { value: parsed.value };
+  }
+  if (entry === "text") return { value: typed };
+  return parseJson(typed);
+}
+
+/** A value as its field's control shows it, or null where that control can't show it as it is: a line break, which a
+ * one-line control drops, or text that doesn't read back as the value (an empty text is "not given"). The reviews of
+ * revisions 4 and 5. */
+export function shownOf(f: StartField, v: unknown): string | null {
+  const shown = textOf(f, v);
+  if (shown === null || /[\r\n]/.test(shown)) return null;
+  const read = valueOf(f, shown);
+  return "value" in read && JSON.stringify(read.value) === JSON.stringify(v) ? shown : null;
+}
+
+/** A value as its field's control would hold it, before it's read back. */
+export function textOf(f: StartField, v: unknown): string | null {
+  switch (entryOf(f)) {
+    case "choice":
+      return (f.enum ?? []).some((x) => JSON.stringify(x) === JSON.stringify(v)) ? JSON.stringify(v) : null;
+    case "yesno":
+      return typeof v === "boolean" ? String(v) : null;
+    case "whole":
+      return typeof v === "number" && Number.isInteger(v) ? String(v) : null;
+    case "number":
+      return typeof v === "number" ? String(v) : null;
+    case "text":
+      return typeof v === "string" ? v : null;
+    case "json":
+      return JSON.stringify(v);
+  }
+}
+
+/** Where a field's problem is kept among the form's: apart from its own (`when`, `input`…), whatever the field's name. */
+export const fieldKey = (name: string) => `field:${name}`;
+
+/** The fields' values as one input, each by its name as a key of its own (a field may be named `__proto__`), or each
+ * field's problem; `required` holds a required field to being given. */
+export function fromFields(
+  form: { fields: StartField[] }, values: ReadonlyMap<string, string>, required: boolean,
+  requiredWords: (f: StartField) => string = (f) => `${nameOf(f)} is required.`,
+): { input: Record<string, unknown> } | { problems: Record<string, string> } {
+  const entries: [string, unknown][] = [];
+  const problems: [string, string][] = [];
+  for (const f of form.fields) {
+    const read = valueOf(f, values.get(f.name));
+    if ("problem" in read) problems.push([fieldKey(f.name), read.problem]);
+    else if (read.value !== undefined) entries.push([f.name, read.value]);
+    else if (required && f.required) problems.push([fieldKey(f.name), requiredWords(f)]);
+  }
+  return problems.length > 0 ? { problems: Object.fromEntries(problems) } : { input: Object.fromEntries(entries) };
+}
+
+export const listed = (items: string[]) => (items.length < 2 ? (items[0] ?? "") : `${items.slice(0, -1).join(", ")} and ${items.at(-1)!}`);
+
+/** One field of the published version's form: never prefilled with what a sensitive field hides. */
+export function InputControl({ f, value, error, onChange, label: shownLabel, hint: shownHint }: {
+  f: StartField; value: string | undefined; error?: string; onChange: (v: string) => void; label?: ReactNode; hint?: ReactNode;
+}) {  // prettier-ignore
+  const label = shownLabel ?? `${nameOf(f)}${f.required ? " (required)" : ""}`;
+  const entry = entryOf(f);
+  const hint = shownHint ?? (entry === "json" ? [f.description, JSON_HINT].filter(Boolean).join(" ") : (f.description ?? undefined));
+  if (entry === "yesno") {
+    return (
+      <Select label={label} hint={hint} error={error} value={value === undefined ? "" : String(value)} onChange={(e) => onChange(e.target.value)}>
+        <option value="">Not given</option>
+        <option value="true">Yes</option>
+        <option value="false">No</option>
+      </Select>
+    );
+  }
+  if (entry === "choice") {
+    return (
+      <Select label={label} hint={hint} error={error} value={value ?? ""} onChange={(e) => onChange(e.target.value)}>
+        <option value="">Not given</option>
+        {(f.enum ?? []).map((v) => <option key={JSON.stringify(v)} value={JSON.stringify(v)}>{typeof v === "string" ? v : JSON.stringify(v)}</option>)}
+      </Select>
+    );  // prettier-ignore
+  }
+  if (entry === "json" && !f.sensitive) {
+    return <TextArea label={label} hint={hint} error={error} value={value ?? ""} rows={3} spellCheck={false} onChange={(e) => onChange(e.target.value)} />;
+  }
+  return (
+    <Field
+      label={label} hint={hint} error={error} type={f.sensitive ? "password" : "text"} autoComplete="off" spellCheck={entry === "json" ? false : undefined}
+      inputMode={entry === "whole" || entry === "number" ? "decimal" : undefined} value={value ?? ""}
+      onChange={(e) => onChange(e.target.value)}
+    />
+  );  // prettier-ignore
+}
+
+/** The published version's form, with the values it starts from: a default its control shows, where one isn't hidden. */
+export const startValues = (form: { fields: StartField[] }): ReadonlyMap<string, string> =>
+  new Map(form.fields.flatMap((f) => {
+    const shown = f.sensitive || f.default === undefined || f.default === null ? null : shownOf(f, f.default);
+    return shown === null ? [] : [[f.name, shown] as const];
+  }));  // prettier-ignore
+
+/** What a start form's fields show of an input (apps/forms.py reads its root's properties and required): any other
+ * keyword at its root (allOf, $ref, if, …) holds rules no field shows, and the input is then entered whole, as JSON. */
+export const SHOWN = new Set(["type", "properties", "required", "title", "description", "additionalProperties", "$schema", "$defs", "$comment", "examples"]);
+export const fieldsShow = (schema: Record<string, unknown>) => Object.keys(schema).every((k) => SHOWN.has(k) || k.startsWith("x-"));
+
+/** The whole input typed as JSON: an object, its keys as parsed, or why it isn't one (JSON a parse would change, as a
+ * field's); nothing typed is an empty input. */
+export function wholeOf(text: string): { value: Record<string, unknown> } | { problem: string } {
+  const read = parseJson(text);
+  if ("problem" in read) return read;
+  if (read.value === undefined) return { value: {} };
+  return isObject(read.value) ? { value: read.value } : { problem: 'An object, like {"site": "HQ"}.' };
+}
diff --git a/frontend/src/routes/editor/triggers/ScheduleForm.tsx b/frontend/src/routes/editor/triggers/ScheduleForm.tsx
index a1bb8798..5b0d7252 100644
--- a/frontend/src/routes/editor/triggers/ScheduleForm.tsx
+++ b/frontend/src/routes/editor/triggers/ScheduleForm.tsx
@@ -11,15 +11,13 @@ import { useMutation, useQuery } from "@tanstack/react-query";
 import { useId, useState, type FormEvent, type ReactNode } from "react";
 import { Button } from "../../../components/Button";
 import { Field, Select, TextArea } from "../../../components/Field";
+import { InputControl, fieldKey, fieldsShow, fromFields, listed, shownOf, startValues, wholeOf } from "../startInput";
 import { announce } from "../../../lib/announce";
 import { ApiError } from "../../../lib/client";
 import { CATCHUP, TIMING_WORDS, blankWhen, intervalWords, timingOf, whenOf, zones, type Preset, type When } from "../../../lib/timing";
-import { parseJson } from "../../../lib/config";
 import { asGraph } from "../../../lib/graph";
 import { inputOf } from "../../../lib/input";
-import { createSchedule, scheduleTitle, updateSchedule, versionQuery, type Schedule, type StartField, type StartForm } from "../../../lib/triggers";
-import { isObject } from "../../../lib/schemaForm";
-import { parseNumber } from "../../../lib/unapplied";
+import { createSchedule, scheduleTitle, updateSchedule, versionQuery, type Schedule, type StartForm } from "../../../lib/triggers";
 import { useTriggers } from "./context";
 
 const PRESETS: { value: Preset; label: string }[] = [
@@ -40,138 +38,6 @@ function fieldOfProblem(field: string, preset: Preset): keyof When | "zone" | "c
   return preset === "custom" ? "cron" : preset === "daily" || preset === "weekdays" ? "time" : "when";
 }
 
-/** How a field of the input is entered: one of its values, as its type says, or JSON for what the simple controls can't
- * hold (a list, an object, several types or none), each value's type kept (the review of revision 1). */
-type Entry = "choice" | "yesno" | "whole" | "number" | "text" | "json";
-
-function entryOf(f: StartField): Entry {
-  if (Array.isArray(f.enum) && !f.enum_masked) return "choice";
-  const type: unknown = f.type;
-  return type === "boolean" ? "yesno" : type === "integer" ? "whole" : type === "number" ? "number" : type === "string" ? "text" : "json";
-}
-
-const JSON_HINT = 'As JSON, like ["ap-1"] or {"site": "HQ"}; text in quotes.';
-
-const nameOf = (f: StartField) => f.title ?? f.name;
-
-/** What's typed for one field of the input, as the input holds it: nothing given is left out. A choice's option is its
- * value as JSON, so a number stays a number; JSON a parse would change (a number too large, a whole one past 2^53) is
- * refused, as the draft's is. */
-function valueOf(f: StartField, typed: string | undefined): { value: unknown } | { problem: string } {
-  if (typed === undefined || typed === "") return { value: undefined };
-  const entry = entryOf(f);
-  if (entry === "choice") return { value: JSON.parse(typed) as unknown };
-  if (entry === "yesno") return { value: typed === "true" };
-  if (entry === "whole" || entry === "number") {
-    const parsed = parseNumber(typed, entry === "whole");
-    return "problem" in parsed ? parsed : { value: parsed.value };
-  }
-  if (entry === "text") return { value: typed };
-  return parseJson(typed);
-}
-
-/** A value as its field's control shows it, or null where that control can't show it as it is: a line break, which a
- * one-line control drops, or text that doesn't read back as the value (an empty text is "not given"). The reviews of
- * revisions 4 and 5. */
-function shownOf(f: StartField, v: unknown): string | null {
-  const shown = textOf(f, v);
-  if (shown === null || /[\r\n]/.test(shown)) return null;
-  const read = valueOf(f, shown);
-  return "value" in read && JSON.stringify(read.value) === JSON.stringify(v) ? shown : null;
-}
-
-/** A value as its field's control would hold it, before it's read back. */
-function textOf(f: StartField, v: unknown): string | null {
-  switch (entryOf(f)) {
-    case "choice":
-      return (f.enum ?? []).some((x) => JSON.stringify(x) === JSON.stringify(v)) ? JSON.stringify(v) : null;
-    case "yesno":
-      return typeof v === "boolean" ? String(v) : null;
-    case "whole":
-      return typeof v === "number" && Number.isInteger(v) ? String(v) : null;
-    case "number":
-      return typeof v === "number" ? String(v) : null;
-    case "text":
-      return typeof v === "string" ? v : null;
-    case "json":
-      return JSON.stringify(v);
-  }
-}
-
-/** Where a field's problem is kept among the form's: apart from its own (`when`, `input`…), whatever the field's name. */
-const fieldKey = (name: string) => `field:${name}`;
-
-/** The fields' values as one input, each by its name as a key of its own (a field may be named `__proto__`), or each
- * field's problem; `required` holds a required field to being given. */
-function fromFields(form: StartForm, values: ReadonlyMap<string, string>, required: boolean): { input: Record<string, unknown> } | { problems: Record<string, string> } {
-  const entries: [string, unknown][] = [];
-  const problems: [string, string][] = [];
-  for (const f of form.fields) {
-    const read = valueOf(f, values.get(f.name));
-    if ("problem" in read) problems.push([fieldKey(f.name), read.problem]);
-    else if (read.value !== undefined) entries.push([f.name, read.value]);
-    else if (required && f.required) problems.push([fieldKey(f.name), `${nameOf(f)} is required.`]);
-  }
-  return problems.length > 0 ? { problems: Object.fromEntries(problems) } : { input: Object.fromEntries(entries) };
-}
-
-const listed = (items: string[]) => (items.length < 2 ? (items[0] ?? "") : `${items.slice(0, -1).join(", ")} and ${items.at(-1)!}`);
-
-/** One field of the published version's form: never prefilled with what a sensitive field hides. */
-function InputControl({ f, value, error, onChange }: { f: StartField; value: string | undefined; error?: string; onChange: (v: string) => void }) {
-  const label = `${nameOf(f)}${f.required ? " (required)" : ""}`;
-  const entry = entryOf(f);
-  const hint = entry === "json" ? [f.description, JSON_HINT].filter(Boolean).join(" ") : (f.description ?? undefined);
-  if (entry === "yesno") {
-    return (
-      <Select label={label} hint={hint} error={error} value={value === undefined ? "" : String(value)} onChange={(e) => onChange(e.target.value)}>
-        <option value="">Not given</option>
-        <option value="true">Yes</option>
-        <option value="false">No</option>
-      </Select>
-    );
-  }
-  if (entry === "choice") {
-    return (
-      <Select label={label} hint={hint} error={error} value={value ?? ""} onChange={(e) => onChange(e.target.value)}>
-        <option value="">Not given</option>
-        {(f.enum ?? []).map((v) => <option key={JSON.stringify(v)} value={JSON.stringify(v)}>{typeof v === "string" ? v : JSON.stringify(v)}</option>)}
-      </Select>
-    );  // prettier-ignore
-  }
-  if (entry === "json" && !f.sensitive) {
-    return <TextArea label={label} hint={hint} error={error} value={value ?? ""} rows={3} spellCheck={false} onChange={(e) => onChange(e.target.value)} />;
-  }
-  return (
-    <Field
-      label={label} hint={hint} error={error} type={f.sensitive ? "password" : "text"} autoComplete="off" spellCheck={entry === "json" ? false : undefined}
-      inputMode={entry === "whole" || entry === "number" ? "decimal" : undefined} value={value ?? ""}
-      onChange={(e) => onChange(e.target.value)}
-    />
-  );  // prettier-ignore
-}
-
-/** The published version's form, with the values it starts from: a default its control shows, where one isn't hidden. */
-const startValues = (form: StartForm): ReadonlyMap<string, string> =>
-  new Map(form.fields.flatMap((f) => {
-    const shown = f.sensitive || f.default === undefined || f.default === null ? null : shownOf(f, f.default);
-    return shown === null ? [] : [[f.name, shown] as const];
-  }));  // prettier-ignore
-
-/** What a start form's fields show of an input (apps/forms.py reads its root's properties and required): any other
- * keyword at its root (allOf, $ref, if, …) holds rules no field shows, and the input is then entered whole, as JSON. */
-const SHOWN = new Set(["type", "properties", "required", "title", "description", "additionalProperties", "$schema", "$defs", "$comment", "examples"]);
-const fieldsShow = (schema: Record<string, unknown>) => Object.keys(schema).every((k) => SHOWN.has(k) || k.startsWith("x-"));
-
-/** The whole input typed as JSON: an object, its keys as parsed, or why it isn't one (JSON a parse would change, as a
- * field's); nothing typed is an empty input. */
-function wholeOf(text: string): { value: Record<string, unknown> } | { problem: string } {
-  const read = parseJson(text);
-  if ("problem" in read) return read;
-  if (read.value === undefined) return { value: {} };
-  return isObject(read.value) ? { value: read.value } : { problem: 'An object, like {"site": "HQ"}.' };
-}
-
 /** Whether two "When"s say the same, field for field. */
 const sameWhen = (a: When, b: When) => (Object.keys(a) as (keyof When)[]).every((k) => a[k] === b[k]);
 
```

- [ ] **Step 4: Run them again**

Run: the same command.

Expected: PASS, 83 passed: the schedule form's tests among them, on the fields moved to `startInput.tsx`.

- [ ] **Step 5: Static checks**

Run: the two of "How to run things". Expected: no output.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/skeleton.ts frontend/src/lib/skeleton.test.ts frontend/src/components \
  frontend/src/routes/editor/startInput.tsx frontend/src/routes/editor/triggers/ScheduleForm.tsx \
  frontend/src/routes/editor/simulation
git commit -m "feat(editor): the simulation's input, from the draft's start form or as JSON (4d-1c)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Simulate workflow in the toolbar

**Spec:** §7.1 (starting); the Main, Preflight and ReadOnly boards.

**Files:**
- Modify: `frontend/src/routes/editor/Editor.tsx`
- Modify: `frontend/src/routes/editor/Editor.test.tsx`

**Interfaces:**
- Consumes: `freeze` (Task 2), `useSimulation` (Task 2), `SimulateDialog` (Task 3); the editor's `whenSettled`,
  `saver.current.flush()`, `ConflictError`, `land()`.
- Produces: in `Editor`, `simulation` (the session) and `simulator` (`canEdit(role) && viewing === null`); `simulate()`
  (the preflight); the landing targets `"simulate"`.

"◌ Simulate workflow" sits just before Publish, for editors and up, never on a version's view. It's disabled during a
conflict, while a save it waits for runs, while another action is busy, and while the person's own simulation hasn't
ended; a strip says why ("Your simulation hasn't ended. Simulate again once it has."). Held edits get Publish's
question, worded "Discard and simulate". The save is flushed ("Saving before the simulation…"); a failed save sends
nothing and says so, with Retry. The dialog asks at the revision the save made, and its input is sent frozen at it.

- [ ] **Step 1: Write the failing tests**

Apply:

```diff
diff --git a/frontend/src/routes/editor/Editor.test.tsx b/frontend/src/routes/editor/Editor.test.tsx
index 8e41b8ca..a05dc822 100644
--- a/frontend/src/routes/editor/Editor.test.tsx
+++ b/frontend/src/routes/editor/Editor.test.tsx
@@ -2151,3 +2151,88 @@ describe("the Triggers panel (4c-3b)", () => {
     expect(within(panel).getByRole("button", { name: "Show as JSON" })).toBeTruthy();
   });
 });
+
+// Simulate workflow (4d-1c; the simulation design §7.1; the Main, Preflight and ReadOnly boards).
+describe("Simulate workflow", () => {
+  const SIM = `${BASE}/draft/simulations`;
+  const simRequest = (status: string) => ({
+    id: "r1", workflow_id: "w1", version_id: null, draft_snapshot_id: "s1", draft_revision: 2, target_step_id: null,
+    mode: "simulate", source: "manual", status, reason: null, queued_at: "2026-10-15T10:42:05Z", ended_at: null,
+    admission_checks: [],
+  });  // prettier-ignore
+  const simState = (status: string) => ({ request: simRequest(status), run: null, cancel_requested: false, read_back: "kept", input: {}, seeds: null });
+  beforeEach(() => {
+    answers.set(`GET ${SIM}`, () => json([]));
+    answers.set(`GET ${BASE}/draft/start-form`, () =>
+      json({ workflow_id: "w1", draft_revision: 2, csv: null, fields: [{ name: "site", title: "Site", type: "string", required: false, sensitive: false }] }));
+    answers.set("GET /api/v1/trigger-types", () => json([]));
+  });
+
+  it("sits just before Publish, and sends the draft as saved, once, with its own key and revision", async () => {
+    answers.set(`POST ${SIM}`, () => json(simRequest("queued"), 202));
+    answers.set(`GET ${SIM}/r1`, () => json(simState("queued")));
+    await show();
+    await addTransform();
+    const simulate = await screen.findByRole("button", { name: "◌ Simulate workflow" });
+    expect(simulate.nextElementSibling?.textContent).toBe("Publish v1");
+    await userEvent.click(simulate);
+    const dialog = await screen.findByRole("dialog", { name: "Simulate workflow" });
+    expect(within(dialog).getByText("Nightly · draft revision 2")).toBeTruthy(); // the save came first
+    await userEvent.type(await within(dialog).findByLabelText("Site"), "HQ");
+    await userEvent.click(within(dialog).getByRole("button", { name: "◌ Simulate" }));
+    await vi.waitFor(() => expect(sent.some((r) => r.method === "POST" && r.path === SIM)).toBe(true));
+    const post = sent.findIndex((r) => r.method === "POST" && r.path === SIM);
+    expect(sent.findIndex((r) => r.method === "PUT")).toBeLessThan(post);
+    expect(sent[post]!.headers.get("If-Match")).toBe("2");
+    expect(sent[post]!.headers.get("Idempotency-Key")).toMatch(/^[0-9a-f-]{36}$/);
+    expect(sent[post]!.body).toEqual({ input: { site: "HQ" } });
+    // One at a time, from this editor (the Main board): until it ends, Simulate waits, saying why.
+    expect(await screen.findByText("Your simulation hasn't ended. Simulate again once it has.")).toBeTruthy();
+    expect(screen.getByRole("button", { name: "◌ Simulate workflow" }).hasAttribute("disabled")).toBe(true);
+  });
+
+  it("asks Publish's own question about edits not applied, worded for simulating", async () => {
+    await unappliedDuration();
+    await userEvent.click(screen.getByRole("button", { name: "◌ Simulate workflow" }));
+    const ask = screen.getByRole("dialog", { name: "Edits not applied" });
+    await userEvent.click(within(ask).getByRole("button", { name: "Discard and simulate" }));
+    expect(await screen.findByRole("dialog", { name: "Simulate workflow" })).toBeTruthy();
+  });
+
+  it("sends nothing when the save fails, and says so", async () => {
+    answers.set(`PUT ${BASE}/draft`, () => json({ error: "http_error" }, 500));
+    await show();
+    await addTransform();
+    await screen.findByText("Not saved", {}, { timeout: 3000 });
+    await userEvent.click(screen.getByRole("button", { name: "◌ Simulate workflow" }));
+    expect(await screen.findByText("Not simulated: your latest edits aren't saved. Retry the save, then simulate.")).toBeTruthy();
+    expect(screen.queryByRole("dialog", { name: "Simulate workflow" })).toBeNull();
+    expect(sent.some((r) => r.method === "POST" && r.path === SIM)).toBe(false);
+  });
+
+  it("waits while the draft was changed elsewhere", async () => {
+    answers.set(`PUT ${BASE}/draft`, () => json({ error: "draft_conflict", draft_revision: 5 }, 409));
+    await show();
+    await addTransform();
+    expect((await screen.findByRole("alert", {}, { timeout: 3000 })).textContent).toContain("changed elsewhere");
+    expect(screen.getByRole("button", { name: "◌ Simulate workflow" }).hasAttribute("disabled")).toBe(true);
+  });
+
+  it("isn't offered to a viewer, nor on a version's view (the ReadOnly board)", async () => {
+    role = "viewer";
+    await show();
+    expect(screen.queryByRole("button", { name: "◌ Simulate workflow" })).toBeNull();
+  });
+
+  it("goes while a version is viewed, and comes back with the draft", async () => {
+    answers.set(`GET ${BASE}/versions`, () => json([version(1, true)]));
+    answers.set(`GET ${BASE}/versions/v1`, () => json(detail(1, "one")));
+    await show();
+    await userEvent.click(screen.getByRole("button", { name: "Versions" }));
+    await userEvent.click(await screen.findByRole("button", { name: "View version 1" }));
+    await screen.findByText("Viewing version 1, read only. The draft is unchanged.");
+    expect(screen.queryByRole("button", { name: "◌ Simulate workflow" })).toBeNull();
+    await userEvent.click(screen.getByRole("button", { name: "Back to the draft" }));
+    expect(await screen.findByRole("button", { name: "◌ Simulate workflow" })).toBeTruthy();
+  });
+});
```

- [ ] **Step 2: Run them**

Run: `npx --offline pnpm@12.6.0 exec vitest run src/routes/editor/Editor.test.tsx`

Expected: FAIL, 5 failed and 148 passed (about 35 s): there's no "◌ Simulate workflow" button to find. "isn't offered to
a viewer, nor on a version's view" passes at once: it pins an absence.

- [ ] **Step 3: Implement**

Apply:

```diff
diff --git a/frontend/src/routes/editor/Editor.tsx b/frontend/src/routes/editor/Editor.tsx
index e691f854..258fa054 100644
--- a/frontend/src/routes/editor/Editor.tsx
+++ b/frontend/src/routes/editor/Editor.tsx
@@ -21,6 +21,7 @@ import { begin, record, redo, undo, type History } from "../../lib/history";
 import { CARD, layout } from "../../lib/layout";
 import { guardLeaving } from "../../lib/leaving";
 import type { Path } from "../../lib/schemaForm";
+import { freeze } from "../../lib/simulations";
 import { useDocumentTitle } from "../../lib/title";
 import { schedulesQuery, startSummary, workflowBindingsQuery } from "../../lib/triggers";
 import {
@@ -42,6 +43,8 @@ import { addsOf, item, type ItemAction } from "./items";
 import { DeclassifyPanel } from "./DeclassifyPanel";
 import { ProblemsPanel, type PublishProblems } from "./ProblemsPanel";
 import { SaveState } from "./SaveState";
+import { SimulateDialog } from "./simulation/SimulateDialog";
+import { useSimulation } from "./simulation/useSimulation";
 import { type Problems } from "./StepCard";
 import { StepPicker, type PickMode } from "./StepPicker";
 import { READ_ONLY, type PanelActions } from "./triggers/context";
@@ -365,9 +368,10 @@ function Editor({
   const publishButton = useRef<HTMLButtonElement>(null);
   const unappliedButton = useRef<HTMLButtonElement>(null);
   const declassifyButton = useRef<HTMLButtonElement>(null);
+  const simulateButton = useRef<HTMLButtonElement>(null);
   const jumps = useRef(0); // each "Go to" a field, so the same one twice still focuses it
   const [landing, setLanding] = useState<{
-    on: "problems" | "versions" | "publish" | "problems-panel" | "versions-panel" | "unapplied" | "unapplied-panel" | "declassify" | "declassify-panel" | "triggers-panel";
+    on: "problems" | "versions" | "publish" | "problems-panel" | "versions-panel" | "unapplied" | "unapplied-panel" | "declassify" | "declassify-panel" | "triggers-panel" | "simulate";
     n: number;
   } | null>(null);
   const land = (on: NonNullable<typeof landing>["on"]) => setLanding((l) => ({ on, n: (l?.n ?? 0) + 1 }));
@@ -387,6 +391,7 @@ function Editor({
         declassify: () => usable(declassifyButton.current) ?? usable(versionsButton.current),
         "declassify-panel": () => document.getElementById("declassify-title") ?? usable(declassifyButton.current),
         "triggers-panel": () => document.getElementById("triggers-title"),
+        simulate: () => usable(simulateButton.current) ?? usable(versionsButton.current),
       }[landing.on]();
       target?.focus();
     });
@@ -465,6 +470,11 @@ function Editor({
   const [notice, setNotice] = useState<Notice | null>(null);
   const viewAsked = useRef(0); // the newest version view asked for
   const publisher = canPublish(role) && sync.status !== "conflict";
+  // Simulating the draft (4d-1c, §7.1): editors and up, who hold workflow.edit and run.start; never on a version's view.
+  const simulation = useSimulation(tenantId, workflow.id);
+  const simulator = canEdit(role) && viewing === null;
+  const [simulateAt, setSimulateAt] = useState<{ revision: number; doc: GraphDoc } | null>(null); // the input, asked
+  const [saving, setSaving] = useState(false); // the save Simulate waits for
   // When editing stops (a conflict, an exit, a publication), what only editing offers stops with it: an open dialog
   // closes, placing ends (a click on a read-only canvas places nothing) and says so. Focus held by what's gone (the
   // dialog, a "+", Auto layout, Add step, a panel's buttons) goes to what's drawn: a panel's heading when it was in
@@ -884,6 +894,26 @@ function Editor({
     return left;
   }
 
+  /** Simulate workflow's preflight, Publish's own (§7.1): with the edits not applied settled, the save is flushed, and
+   * the input is asked for at the revision that save made, never an older one. A failed save sends nothing. */
+  async function simulate() {
+    setSaving(true);
+    setNotice({ tone: "info", text: "Saving before the simulation…" });
+    try {
+      const revision = await saver.current!.flush();
+      setNotice(null);
+      setSimulateAt({ revision, doc: draftNow() });
+    } catch (e) {
+      // A conflict has its own banner.
+      setNotice(e instanceof ConflictError ? null : {
+        tone: "danger", text: "Not simulated: your latest edits aren't saved. Retry the save, then simulate.",
+        action: { label: "Retry", run: () => saver.current?.retry() },
+      });  // prettier-ignore
+    } finally {
+      setSaving(false);
+    }
+  }
+
   /** `then`, once every unapplied edit is in the draft; when one can't be, the person decides first (ruling 18). */
   function whenSettled(action: string, then: () => void) {
     const left = settleAll();
@@ -1162,6 +1192,19 @@ function Editor({
           Versions
         </Button>
         <Button size="md" onClick={() => void exportFile()}>Export</Button>
+        {simulator && (
+          <Button
+            ref={simulateButton}
+            variant="simulate"
+            size="md"
+            aria-haspopup="dialog"
+            aria-describedby={simulation.busy ? "simulate-busy" : undefined}
+            disabled={sync.status === "conflict" || simulation.busy || saving || busy !== null}
+            onClick={() => whenSettled("simulate", () => void simulate())}
+          >
+            ◌ Simulate workflow
+          </Button>
+        )}
         {publisher && viewing === null && (
           <Button
             ref={publishButton}
@@ -1176,6 +1219,11 @@ function Editor({
           </Button>
         )}
       </Toolbar>
+      {simulator && simulation.busy && (
+        <p id="simulate-busy" className="flex flex-wrap items-center gap-3 border-b border-line bg-surface-2 px-5 py-2.5 text-small">
+          <span className="grow">Your simulation hasn&apos;t ended. Simulate again once it has.</span>
+        </p>
+      )}
       {viewing && (
         <div className="flex flex-wrap items-center gap-3 border-b border-line bg-surface-2 px-5 py-2.5 text-small">
           <span className="grow">Viewing version {viewing.number}, read only. The draft is unchanged.</span>
@@ -1407,6 +1455,24 @@ function Editor({
           onClose={() => setPicker(null)}
         />
       )}
+      {simulateAt && (
+        <SimulateDialog
+          tenantId={tenantId}
+          workflowId={workflow.id}
+          name={workflow.name}
+          revision={simulateAt.revision}
+          doc={simulateAt.doc}
+          onSimulate={(input) => {
+            setSimulateAt(null);
+            void simulation.start(freeze(simulateAt.revision, { input }));
+            land("simulate");
+          }}
+          onClose={() => {
+            setSimulateAt(null);
+            land("simulate");
+          }}
+        />
+      )}
       {connecting && (
         <ConnectDialog
           doc={doc}
```

- [ ] **Step 4: Run them again**

Run: the same command.

Expected: PASS, 153 passed.

- [ ] **Step 5: Static checks**

Run: the two of "How to run things". Expected: no output.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/routes/editor/Editor.tsx frontend/src/routes/editor/Editor.test.tsx
git commit -m "feat(editor): Simulate workflow beside Publish, with Publish's preflight (4d-1c)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: The Simulation panel's lifecycle

**Spec:** §7.2 (the lifecycle), §7.5 (the panel's status line); the Lifecycle and Running boards.

**Files:**
- Create: `frontend/src/routes/editor/simulation/lifecycle.ts`,
  `frontend/src/routes/editor/simulation/lifecycle.test.ts`
- Create: `frontend/src/routes/editor/simulation/chips.tsx`
- Create: `frontend/src/routes/editor/simulation/SimulationPanel.tsx`,
  `frontend/src/routes/editor/simulation/SimulationPanel.test.tsx`
- Modify: `frontend/src/routes/editor/Editor.tsx`, `frontend/src/routes/editor/Editor.test.tsx`

**Interfaces:**
- Consumes: `SimulationSession` (Task 2); `SIDE` (`side.ts`).
- Produces:
  - `lifecycle.ts`: `STATUS: Record<Phase, string>`, `duration(from, to)` ("14 s", "3 min 20 s", "1 h 2 min",
    "under 1 s"), `runId(id)` (8 characters), `clock(iso)` (en-GB, to the second), `stepsEnded(steps)`,
    `endedWhat(phase, steps)` ("failed at notify", "cancelled after get_site", "the run passed its deadline, during
    …").
  - `chips.tsx`: `StatusChip({ phase })`, `SimulatedChip()`.
  - `SimulationPanel({ session, onSimulateAgain?, onClose, children? })`; in `Editor`, the side panel
    `{ kind: "simulation" }` and the landing `"simulation-panel"`.

The panel opens when a simulation is sent (its heading takes focus), and from the strip's "Simulation". It says where
the simulation is, in a sentence: being sent, its answer lost (with "Check again"), being read, waiting for a run slot,
starting, how many steps ended, cancel requested, couldn't start. Then its status and "Simulated" chips; which run it
is and when it started, or how it ended and how long it took; after a reload, that it's the person's latest. A failed
read says "Couldn't be refreshed · as of …" with "Read it again". "Cancel the simulation" while it runs; "◌ Simulate
again" once it ended. Close and Escape close it.

- [ ] **Step 1: Write the failing tests**

Apply:

```diff
diff --git a/frontend/src/routes/editor/Editor.test.tsx b/frontend/src/routes/editor/Editor.test.tsx
index a05dc822..a3cd678c 100644
--- a/frontend/src/routes/editor/Editor.test.tsx
+++ b/frontend/src/routes/editor/Editor.test.tsx
@@ -2191,6 +2191,23 @@ describe("Simulate workflow", () => {
     expect(screen.getByRole("button", { name: "◌ Simulate workflow" }).hasAttribute("disabled")).toBe(true);
   });
 
+  it("opens the Simulation panel once sent, and the strip opens it again while it runs", async () => {
+    answers.set(`POST ${SIM}`, () => json(simRequest("queued"), 202));
+    answers.set(`GET ${SIM}/r1`, () => json(simState("queued")));
+    await show();
+    await userEvent.click(await screen.findByRole("button", { name: "◌ Simulate workflow" }));
+    const dialog = await screen.findByRole("dialog", { name: "Simulate workflow" });
+    await userEvent.click(await within(dialog).findByRole("button", { name: "◌ Simulate" }));
+    const panel = await screen.findByRole("complementary", { name: "Simulation" });
+    expect(await within(panel).findByText("Waiting for a free run slot.")).toBeTruthy();
+    await userEvent.click(within(panel).getByRole("button", { name: "Close" }));
+    expect(screen.queryByRole("complementary", { name: "Simulation" })).toBeNull();
+    const strip = screen.getByRole("button", { name: "Simulation" });
+    expect(strip.getAttribute("aria-expanded")).toBe("false");
+    await userEvent.click(strip);
+    expect(await screen.findByRole("complementary", { name: "Simulation" })).toBeTruthy();
+  });
+
   it("asks Publish's own question about edits not applied, worded for simulating", async () => {
     await unappliedDuration();
     await userEvent.click(screen.getByRole("button", { name: "◌ Simulate workflow" }));
diff --git a/frontend/src/routes/editor/simulation/SimulationPanel.test.tsx b/frontend/src/routes/editor/simulation/SimulationPanel.test.tsx
new file mode 100644
index 00000000..4e19b523
--- /dev/null
+++ b/frontend/src/routes/editor/simulation/SimulationPanel.test.tsx
@@ -0,0 +1,118 @@
+// SPDX-License-Identifier: Apache-2.0
+import { render, screen } from "@testing-library/react";
+import userEvent from "@testing-library/user-event";
+import { describe, expect, it, vi } from "vitest";
+import type { SimulationRequest, SimulationState, StepSummary } from "../../../lib/simulations";
+import { SimulationPanel } from "./SimulationPanel";
+import type { SimulationSession } from "./useSimulation";
+
+const ID = "7c1e9a40-3b2d-4e5f-9a1b-2c3d4e5f6a7b";
+const QUEUED_AT = "2026-10-15T10:42:05Z";
+const request = (status: SimulationRequest["status"]): SimulationRequest => ({
+  id: ID, workflow_id: "w1", draft_snapshot_id: "s1", draft_revision: 14, target_step_id: null, mode: "simulate",
+  source: "manual", status, reason: null, queued_at: QUEUED_AT, ended_at: null, admission_checks: [],
+});  // prettier-ignore
+const run = (status: NonNullable<SimulationState["run"]>["status"], ended_at: string | null = null): SimulationState["run"] => ({
+  status, queued_at: QUEUED_AT, started_at: "2026-10-15T10:42:05Z", ended_at, error: null, iterations: 0,
+});
+const step = (key: string, statuses: Record<string, number>): StepSummary => ({
+  step_id: `id-${key}`, key, type: "flow.transform@1", origin: "evaluated", instances: Object.values(statuses).reduce((a, b) => a + b, 0),
+  statuses, ports: {}, final: null,
+});  // prettier-ignore
+const at = (iso: string) => new Date(iso).toLocaleTimeString("en-GB");
+
+function session(over: Partial<SimulationSession> = {}): SimulationSession {
+  return {
+    local: { kind: "admitted", frozen: null, request: request("queued"), latest: false },
+    state: null, steps: null, phase: null, busy: true, readFailed: false, asOf: null,
+    start: vi.fn(), checkAgain: vi.fn(), cancel: vi.fn(() => Promise.resolve("requested" as const)), readAgain: vi.fn(),
+    ...over,
+  };  // prettier-ignore
+}
+const admitted = (status: SimulationRequest["status"], r: SimulationState["run"] = null, over: Partial<SimulationSession> = {}, cancel_requested = false) => {
+  const state: SimulationState = { request: request(status), run: r, cancel_requested, read_back: "kept", input: {}, seeds: null };
+  return session({ state, ...over });
+};
+
+function show(s: SimulationSession) {
+  const onSimulateAgain = vi.fn();
+  const onClose = vi.fn();
+  render(<SimulationPanel session={s} onSimulateAgain={onSimulateAgain} onClose={onClose} />);
+  return { onSimulateAgain, onClose };
+}
+
+describe("the Simulation panel's lifecycle (§7.2; the Lifecycle and Running boards)", () => {
+  it("says it's being sent, and when its answer is lost, sends the same request again on Check again", async () => {
+    const frozen = { key: "k1", revision: 14, body: { input: {} } };
+    show(session({ local: { kind: "submitting", frozen } }));
+    expect(screen.getByText("Sending the simulation…")).toBeTruthy();
+    const lost = session({ local: { kind: "unknown", frozen } });
+    show(lost);
+    expect(screen.getByText(/It isn't known whether the simulation started: its answer was lost\. Checking sends the same request again: while the first request is still kept, it can't start a second time\./)).toBeTruthy();
+    await userEvent.click(screen.getByRole("button", { name: "Check again" }));
+    expect(lost.checkAgain).toHaveBeenCalled();
+  });
+
+  it("waits for a run slot, and can be cancelled", async () => {
+    const s = admitted("queued", null, { phase: "queued" });
+    show(s);
+    expect(screen.getByRole("heading", { name: "Simulation" })).toBe(document.activeElement);
+    expect(screen.getByText("Queued")).toBeTruthy();
+    expect(screen.getByText("Simulated")).toBeTruthy();
+    expect(screen.getByText("Waiting for a free run slot.")).toBeTruthy();
+    await userEvent.click(screen.getByRole("button", { name: "Cancel the simulation" }));
+    expect(s.cancel).toHaveBeenCalled();
+  });
+
+  it("says how far it got while it runs, and that it's read again while the tab is open", () => {
+    const steps = { given: "input" as const, steps: [step("get_site", { succeeded: 1 }), step("list_aps", { succeeded: 1 }), step("has_aps", { running: 1 }), step("report", {})] };
+    show(admitted("started", run("running"), { phase: "running", steps }));
+    expect(screen.getByText("2 of 4 steps ended.")).toBeTruthy();
+    expect(screen.getByText(`Started ${at("2026-10-15T10:42:05Z")} · draft revision 14 · run 7c1e9a40`)).toBeTruthy();
+    expect(screen.getByText("Read again every few seconds while this tab is open.")).toBeTruthy();
+  });
+
+  it("says a cancel is requested until the server confirms it", () => {
+    show(admitted("started", run("running"), { phase: "cancel_requested" }, true));
+    expect(screen.getByText("Cancel requested. It's shown as cancelled once the server confirms it.")).toBeTruthy();
+    expect(screen.getByRole("button", { name: "Cancel requested" })).toHaveProperty("disabled", true);
+  });
+
+  it("says how it ended, and offers to simulate again", async () => {
+    const steps = { given: "input" as const, steps: [step("get_site", { succeeded: 1 }), step("notify", { failed: 1 })] };
+    const { onSimulateAgain } = show(admitted("started", run("failed", "2026-10-15T10:42:19Z"), { phase: "failed", steps, busy: false }));
+    expect(screen.getByText("Failed")).toBeTruthy();
+    expect(screen.getByText("Ended: failed at notify · 14 s · draft revision 14 · run 7c1e9a40")).toBeTruthy();
+    await userEvent.click(screen.getByRole("button", { name: "◌ Simulate again" }));
+    expect(onSimulateAgain).toHaveBeenCalled();
+  });
+
+  it("says when it couldn't start", () => {
+    show(admitted("dead", null, { phase: "dead", busy: false }));
+    expect(screen.getByText("Couldn't start")).toBeTruthy();
+    expect(screen.getByText("The simulation couldn't be started. Nothing ran.")).toBeTruthy();
+  });
+
+  it("keeps the last state it knew when a read fails, as of when it was read", async () => {
+    const s = admitted("started", run("running"), { phase: "running", readFailed: true, asOf: Date.parse("2026-10-15T10:42:31Z") });
+    show(s);
+    expect(screen.getByText("Running")).toBeTruthy();
+    expect(screen.getByText(`Couldn't be refreshed · as of ${at("2026-10-15T10:42:31Z")}.`)).toBeTruthy();
+    await userEvent.click(screen.getByRole("button", { name: "Read it again" }));
+    expect(s.readAgain).toHaveBeenCalled();
+  });
+
+  it("after a reload, is the person's latest simulation, labelled as exactly that", () => {
+    const s = admitted("started", run("succeeded", "2026-10-15T10:42:19Z"), { phase: "succeeded", busy: false });
+    s.local = { kind: "admitted", frozen: null, request: request("started"), latest: true };
+    show(s);
+    expect(screen.getByText(`Your latest simulation of this workflow, started ${at(QUEUED_AT)} on revision 14.`)).toBeTruthy();
+  });
+
+  it("closes on Close and on Escape", async () => {
+    const { onClose } = show(admitted("queued", null, { phase: "queued" }));
+    await userEvent.keyboard("{Escape}");
+    await userEvent.click(screen.getByRole("button", { name: "Close" }));
+    expect(onClose).toHaveBeenCalledTimes(2);
+  });
+});
diff --git a/frontend/src/routes/editor/simulation/lifecycle.test.ts b/frontend/src/routes/editor/simulation/lifecycle.test.ts
new file mode 100644
index 00000000..756e8236
--- /dev/null
+++ b/frontend/src/routes/editor/simulation/lifecycle.test.ts
@@ -0,0 +1,39 @@
+// SPDX-License-Identifier: Apache-2.0
+import { describe, expect, it } from "vitest";
+import type { StepSummary } from "../../../lib/simulations";
+import { duration, endedWhat, runId, stepsEnded } from "./lifecycle";
+
+const step = (key: string, statuses: Record<string, number>, origin: StepSummary["origin"] = "evaluated"): StepSummary => ({
+  step_id: `id-${key}`, key, type: "flow.transform@1", origin, instances: Object.values(statuses).reduce((a, b) => a + b, 0),
+  statuses, ports: {}, final: null,
+});  // prettier-ignore
+
+describe("a simulation's lifecycle, in words (§7.2, §7.5; the Lifecycle board)", () => {
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
+  it("counts the steps that have ended while it runs", () => {
+    const steps = [step("a", { succeeded: 1 }), step("b", { running: 1 }), step("c", {}, "not_reached_yet"), step("d", { failed: 2, skipped: 1 })];
+    expect(stepsEnded(steps)).toEqual({ ended: 2, of: 4 });
+  });
+
+  it("says how it ended, naming the step that decided it", () => {
+    const steps = [step("get_site", { succeeded: 1 }), step("list_aps", { succeeded: 1 }), step("notify", { failed: 1 }), step("report", { cancelled: 1 })];
+    expect(endedWhat("succeeded", steps)).toBe("succeeded");
+    expect(endedWhat("failed", steps)).toBe("failed at notify");
+    expect(endedWhat("failed", [])).toBe("failed");
+    expect(endedWhat("cancelled", steps)).toBe("cancelled after notify");
+    expect(endedWhat("cancelled", [])).toBe("cancelled before any step ran");
+    expect(endedWhat("deadline_exceeded", steps)).toBe("the run passed its deadline, during report");
+    expect(endedWhat("deadline_exceeded", [])).toBe("the run passed its deadline");
+  });
+});
```

- [ ] **Step 2: Run them**

Run: `npx --offline pnpm@12.6.0 exec vitest run src/routes/editor/simulation/lifecycle.test.ts
src/routes/editor/simulation/SimulationPanel.test.tsx src/routes/editor/Editor.test.tsx`

Expected: FAIL: `lifecycle.test.ts` and `SimulationPanel.test.tsx` can't import their modules; in the editor's file, 1
failed and 153 passed: once sent, there's no Simulation panel (`role="complementary"`, name "Simulation").

- [ ] **Step 3: Implement**

Apply:

```diff
diff --git a/frontend/src/routes/editor/Editor.tsx b/frontend/src/routes/editor/Editor.tsx
index 258fa054..41c49827 100644
--- a/frontend/src/routes/editor/Editor.tsx
+++ b/frontend/src/routes/editor/Editor.tsx
@@ -44,6 +44,7 @@ import { DeclassifyPanel } from "./DeclassifyPanel";
 import { ProblemsPanel, type PublishProblems } from "./ProblemsPanel";
 import { SaveState } from "./SaveState";
 import { SimulateDialog } from "./simulation/SimulateDialog";
+import { SimulationPanel } from "./simulation/SimulationPanel";
 import { useSimulation } from "./simulation/useSimulation";
 import { type Problems } from "./StepCard";
 import { StepPicker, type PickMode } from "./StepPicker";
@@ -59,7 +60,7 @@ type Opened = { workflow: WorkflowDetail; types: NodeType[]; role: string | null
  * Triggers panel (4c-3b), at a place in it when "Go to it" sent it there. */
 type Side =
   | { kind: "step"; node: string; field?: { pointer: string; kind?: UnappliedKind; n: number } } | { kind: "problems" } | { kind: "versions" }
-  | { kind: "unapplied" } | { kind: "declassify" } | { kind: "triggers"; at?: { pointer: string; n: number } } | null;  // prettier-ignore
+  | { kind: "unapplied" } | { kind: "declassify" } | { kind: "triggers"; at?: { pointer: string; n: number } } | { kind: "simulation" } | null;  // prettier-ignore
 const NO_DIAGNOSTICS: Diagnostic[] = []; // one empty list, so a memo over it holds
 const NO_STEPS: ReadonlySet<string> = new Set();
 
@@ -371,7 +372,7 @@ function Editor({
   const simulateButton = useRef<HTMLButtonElement>(null);
   const jumps = useRef(0); // each "Go to" a field, so the same one twice still focuses it
   const [landing, setLanding] = useState<{
-    on: "problems" | "versions" | "publish" | "problems-panel" | "versions-panel" | "unapplied" | "unapplied-panel" | "declassify" | "declassify-panel" | "triggers-panel" | "simulate";
+    on: "problems" | "versions" | "publish" | "problems-panel" | "versions-panel" | "unapplied" | "unapplied-panel" | "declassify" | "declassify-panel" | "triggers-panel" | "simulate" | "simulation-panel";
     n: number;
   } | null>(null);
   const land = (on: NonNullable<typeof landing>["on"]) => setLanding((l) => ({ on, n: (l?.n ?? 0) + 1 }));
@@ -392,6 +393,7 @@ function Editor({
         "declassify-panel": () => document.getElementById("declassify-title") ?? usable(declassifyButton.current),
         "triggers-panel": () => document.getElementById("triggers-title"),
         simulate: () => usable(simulateButton.current) ?? usable(versionsButton.current),
+        "simulation-panel": () => document.getElementById("simulation-title") ?? usable(simulateButton.current),
       }[landing.on]();
       target?.focus();
     });
@@ -1222,6 +1224,9 @@ function Editor({
       {simulator && simulation.busy && (
         <p id="simulate-busy" className="flex flex-wrap items-center gap-3 border-b border-line bg-surface-2 px-5 py-2.5 text-small">
           <span className="grow">Your simulation hasn&apos;t ended. Simulate again once it has.</span>
+          <Button size="sm" aria-expanded={side?.kind === "simulation"} onClick={() => setSide(side?.kind === "simulation" ? null : { kind: "simulation" })}>
+            Simulation
+          </Button>
         </p>
       )}
       {viewing && (
@@ -1426,6 +1431,16 @@ function Editor({
             }}
           />
         )}
+        {side?.kind === "simulation" && (
+          <SimulationPanel
+            session={simulation}
+            onSimulateAgain={simulator && sync.status !== "conflict" && !simulation.busy ? () => whenSettled("simulate", () => void simulate()) : undefined}
+            onClose={() => {
+              setSide(null);
+              land("simulate");
+            }}
+          />
+        )}
         {side?.kind === "problems" && (
           <ProblemsPanel
             state={checked}
@@ -1465,7 +1480,7 @@ function Editor({
           onSimulate={(input) => {
             setSimulateAt(null);
             void simulation.start(freeze(simulateAt.revision, { input }));
-            land("simulate");
+            setSide({ kind: "simulation" }); // its heading takes focus
           }}
           onClose={() => {
             setSimulateAt(null);
diff --git a/frontend/src/routes/editor/simulation/SimulationPanel.tsx b/frontend/src/routes/editor/simulation/SimulationPanel.tsx
new file mode 100644
index 00000000..cb105d9a
--- /dev/null
+++ b/frontend/src/routes/editor/simulation/SimulationPanel.tsx
@@ -0,0 +1,101 @@
+// SPDX-License-Identifier: Apache-2.0
+// The Simulation panel (4d-1c; the simulation design §7.2, §7.5; the Lifecycle, Running and ResultPanel boards): where
+// the editor's simulation is, from being sent to its end, in words. It opens when a simulation is sent, and from the
+// toolbar's strip and the canvas's bar; one side panel at a time, as the others (side.ts). The result's sections (the
+// banner, the checks on the server, the steps, the input used) come in below the lifecycle as `children`.
+import { useEffect, useRef, type ReactNode } from "react";
+import { Button } from "../../../components/Button";
+import { ENDED } from "../../../lib/simulations";
+import { SIDE } from "../side";
+import { SimulatedChip, StatusChip } from "./chips";
+import { clock, duration, endedWhat, runId, stepsEnded } from "./lifecycle";
+import type { SimulationSession } from "./useSimulation";
+
+const LOST =
+  "It isn't known whether the simulation started: its answer was lost. Checking sends the same request again: while the " +
+  "first request is still kept, it can't start a second time.";
+
+export function SimulationPanel({ session, onSimulateAgain, onClose, children }: {
+  session: SimulationSession; onSimulateAgain?: () => void; onClose: () => void; children?: ReactNode;
+}) {  // prettier-ignore
+  const heading = useRef<HTMLHeadingElement>(null);
+  useEffect(() => heading.current?.focus(), []);
+  const { local, state, phase } = session;
+  const steps = session.steps?.steps ?? [];
+  const ended = phase !== null && ENDED.has(phase);
+  const request = state?.request ?? (local.kind === "admitted" ? local.request : null);
+  const run = state?.run ?? null;
+  const said = (iso: string | null) => (iso ? clock(iso) : "a moment ago");
+
+  let line: string | null = null; // where it is, in a sentence
+  if (local.kind === "submitting") line = "Sending the simulation…";
+  else if (local.kind === "unknown") line = LOST;
+  else if (local.kind === "admitted" && state === null) line = "Reading the simulation…";
+  else if (phase === "queued") line = "Waiting for a free run slot.";
+  else if (phase === "starting") line = "Its run is being started.";
+  else if (phase === "running") {
+    const { ended: done, of } = stepsEnded(steps);
+    line = session.steps ? `${done} of ${of} steps ended.` : "Running.";
+  } else if (phase === "cancel_requested") line = "Cancel requested. It's shown as cancelled once the server confirms it.";
+  else if (phase === "dead") line = "The simulation couldn't be started. Nothing ran.";
+  else if (phase === "refused") line = request?.reason ?? "The simulation was refused.";
+
+  // Which run it is, and when it started or how it ended (§7.5).
+  const facts =
+    request && state && phase && phase !== "dead" && phase !== "refused"
+      ? ended
+        ? [`Ended: ${endedWhat(phase, steps)}`, duration(run?.started_at ?? null, run?.ended_at ?? null), `draft revision ${request.draft_revision}`, `run ${runId(request.id)}`]
+        : [`Started ${said(run?.started_at ?? request.queued_at)}`, `draft revision ${request.draft_revision}`, `run ${runId(request.id)}`]
+      : null;  // prettier-ignore
+
+  return (
+    <aside
+      aria-labelledby="simulation-title"
+      onKeyDown={(e) => {
+        if (e.key === "Escape") {
+          e.stopPropagation();
+          onClose();
+        }
+      }}
+      className={`${SIDE} gap-4`}
+    >
+      <div className="flex items-center justify-between gap-3">
+        <h2 id="simulation-title" ref={heading} tabIndex={-1} className="text-body-lg font-semibold">Simulation</h2>
+        <Button size="sm" onClick={onClose}>Close</Button>
+      </div>
+      {phase && (
+        <p className="flex flex-wrap items-center gap-2">
+          <StatusChip phase={phase} />
+          <SimulatedChip />
+        </p>
+      )}
+      {facts && <p className="text-small text-muted">{facts.filter(Boolean).join(" · ")}</p>}
+      {line && <p className="text-small">{line}</p>}
+      {local.kind === "admitted" && local.latest && request && (
+        <p className="text-small text-muted">
+          {`Your latest simulation of this workflow, started ${said(request.queued_at)} on revision ${request.draft_revision}.`}
+        </p>
+      )}
+      {session.readFailed && (
+        <p className="flex flex-wrap items-center gap-2 text-small">
+          {`Couldn't be refreshed · as of ${session.asOf ? clock(new Date(session.asOf).toISOString()) : "earlier"}.`}
+          <Button size="sm" onClick={session.readAgain}>Read it again</Button>
+        </p>
+      )}
+      <div className="flex flex-wrap gap-2">
+        {local.kind === "unknown" && <Button size="sm" onClick={() => void session.checkAgain()}>Check again</Button>}
+        {(phase === "queued" || phase === "starting" || phase === "running") && (
+          <Button size="sm" onClick={() => void session.cancel()}>Cancel the simulation</Button>
+        )}
+        {phase === "cancel_requested" && <Button size="sm" disabled>Cancel requested</Button>}
+      </div>
+      {children}
+      {phase !== null && !ended && <p className="text-small text-muted">Read again every few seconds while this tab is open.</p>}
+      {ended && onSimulateAgain && (
+        <div>
+          <Button variant="simulate" size="md" onClick={onSimulateAgain}>◌ Simulate again</Button>
+        </div>
+      )}
+    </aside>
+  );
+}
diff --git a/frontend/src/routes/editor/simulation/chips.tsx b/frontend/src/routes/editor/simulation/chips.tsx
new file mode 100644
index 00000000..6db8fb32
--- /dev/null
+++ b/frontend/src/routes/editor/simulation/chips.tsx
@@ -0,0 +1,21 @@
+// SPDX-License-Identifier: Apache-2.0
+// A simulation's status and what it is, as chips (4d-1c; the Lifecycle and ResultPanel boards): words first, the
+// colour only repeating them (§7.4). Simulated results are slate (D2), never live orange (D3).
+import type { Phase } from "../../../lib/simulations";
+import { STATUS } from "./lifecycle";
+
+const TONE: Partial<Record<Phase, string>> = {
+  succeeded: "border-ok text-ok",
+  failed: "border-danger text-danger",
+  deadline_exceeded: "border-danger text-danger",
+  dead: "border-danger text-danger",
+  refused: "border-danger text-danger",
+};
+
+export function StatusChip({ phase }: { phase: Phase }) {
+  return <span className={`rounded-md border px-1.5 text-meta ${TONE[phase] ?? "border-line-strong text-muted"}`}>{STATUS[phase]}</span>;
+}
+
+export function SimulatedChip() {
+  return <span className="rounded-md border border-sim px-1.5 text-meta text-sim">Simulated</span>;
+}
diff --git a/frontend/src/routes/editor/simulation/lifecycle.ts b/frontend/src/routes/editor/simulation/lifecycle.ts
new file mode 100644
index 00000000..23d3e562
--- /dev/null
+++ b/frontend/src/routes/editor/simulation/lifecycle.ts
@@ -0,0 +1,59 @@
+// SPDX-License-Identifier: Apache-2.0
+// A simulation's lifecycle in words (4d-1c; the simulation design §7.2, §7.5; the Lifecycle, Running and ResultPanel
+// boards): its status, how long it ran, which run it is, how far it got, and how it ended, naming the step that
+// decided it, from the server's per-step summary in run order.
+import type { Phase, StepSummary } from "../../../lib/simulations";
+
+export const STATUS: Record<Phase, string> = {
+  queued: "Queued",
+  starting: "Starting",
+  running: "Running",
+  cancel_requested: "Running", // still going: it's cancelled once the server says so
+  succeeded: "Succeeded",
+  failed: "Failed",
+  cancelled: "Cancelled",
+  deadline_exceeded: "Deadline exceeded",
+  refused: "Not simulated",
+  dead: "Couldn't start",
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
+/** The time of day an instant was, to the second, as the person's clock says it. */
+export const clock = (iso: string) => new Date(iso).toLocaleTimeString("en-GB");
+
+/** How many of the steps have ended while it runs: those with an instance, none of them still running. */
+export function stepsEnded(steps: StepSummary[]): { ended: number; of: number } {
+  return { ended: steps.filter((s) => s.instances > 0 && !s.statuses.running).length, of: steps.length };
+}
+
+const did = (s: StepSummary, ...statuses: string[]) => statuses.some((k) => (s.statuses[k] ?? 0) > 0);
+
+/** How a simulation ended, naming the step that decided it (the Lifecycle board): the first that failed, the last that
+ * ran before a cancel, the one the deadline stopped. */
+export function endedWhat(phase: Phase, steps: StepSummary[]): string {
+  if (phase === "failed") {
+    const at = steps.find((s) => did(s, "failed"));
+    return at ? `failed at ${at.key}` : "failed";
+  }
+  if (phase === "cancelled") {
+    const after = steps.findLast((s) => did(s, "succeeded", "failed"));
+    return after ? `cancelled after ${after.key}` : "cancelled before any step ran";
+  }
+  if (phase === "deadline_exceeded") {
+    const during = steps.findLast((s) => did(s, "cancelled", "running"));
+    return during ? `the run passed its deadline, during ${during.key}` : "the run passed its deadline";
+  }
+  return STATUS[phase].toLowerCase();
+}
```

- [ ] **Step 4: Run them again**

Run: the same command.

Expected: PASS, 167 passed.

- [ ] **Step 5: Static checks**

Run: the two of "How to run things". Expected: no output.

- [ ] **Step 6: Commit, and the milestone**

```bash
git add frontend/src/routes/editor
git commit -m "feat(editor): the Simulation panel: where a simulation is, from sent to its end (4d-1c)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

Append `### 4d-1c, milestone 1 (date)` to the ledger: the tasks' commits, each task's test counts as run, every
mid-slice ruling. Commit it (`docs(editor-4): 4d-1c milestone 1`). **Pause** for the owner's review.

---

# Milestone 2 — The result

### Task 6: The result on the canvas

**Spec:** §7.3 (the result), §7.4 (the data-origin tags); the ResultCanvas and Running boards.

**Files:**
- Create: `frontend/src/routes/editor/simulation/results.ts`, `frontend/src/routes/editor/simulation/results.test.ts`
- Create: `frontend/src/routes/editor/simulation/SimTags.tsx`, `frontend/src/routes/editor/simulation/SimTags.test.tsx`
- Create: `frontend/src/routes/editor/simulation/ResultBar.tsx`,
  `frontend/src/routes/editor/simulation/ResultBar.test.tsx`
- Modify: `frontend/src/routes/editor/StepCard.tsx`, `frontend/src/routes/editor/StartCard.tsx`,
  `frontend/src/routes/editor/Canvas.tsx`
- Modify: `frontend/src/routes/editor/Editor.tsx`, `frontend/src/routes/editor/Editor.test.tsx`

**Interfaces:**
- Consumes: `StepSummary`, `Origin`, `ENDED`, `Phase` (Task 2); `STATUS`, `clock`, `StatusChip` (Task 5);
  `SimBanner` (Task 3).
- Produces:
  - `results.ts`: `type SimTagKind` (`ok`, `fail`, `status`, `given`, `fixture`, `evaluated`, `absent`, `note`),
    `interface SimTag { text; kind }`, `ORIGIN` (each code's words), `words(tags)`, `tagsOf(summary, { maxAttempts,
    ended }): SimTag[]`.
  - `SimTags({ label, tags })`: a list named "<key>: simulated result", beside a card, under it at narrow widths.
  - `ResultBar({ phase, revision, endedAt, notWaited, hidden, onHide, onShow, onPanel, onCancel })`.
  - `StepData.simulated?: SimTag[]`, `StartData.tags?: SimTag[]`; `CanvasProps.simulated?: Map<string, SimTag[]>` (by
    `idKey`) and `start.tags?`.
  - In `Editor`: `simulated` (each step's tags by `idKey`, an attempt said of the step's own `max_attempts`, else its
    type's) and `hiddenFor` (the request whose result is hidden).

Each step's tags sit beside its card and never change it (rulings 1 and 2): a step that ran once, its final attempt's
status, "attempt N of M" past the first, and its origin (an evaluation says the port it took); a loop, its iterations
(its items while it runs); a step in a loop, its instances' total, and its ports apart; one with none, why ("didn't
run", "not reached yet"). The start card says "input". Above the canvas, while it runs: "◌ Simulating · running ·
nothing is sent", with Cancel; once ended, the hatched banner ("Simulated. Nothing was sent. Results don't prove the
live call will succeed.", and the flow-timer line when one wasn't waited), its status and end, "Simulation" and "Hide
the result". Hidden, one bar brings it back; the next simulation shows again.

- [ ] **Step 1: Write the failing tests**

Apply:

```diff
diff --git a/frontend/src/routes/editor/Editor.test.tsx b/frontend/src/routes/editor/Editor.test.tsx
index a3cd678c..f0910071 100644
--- a/frontend/src/routes/editor/Editor.test.tsx
+++ b/frontend/src/routes/editor/Editor.test.tsx
@@ -40,6 +40,8 @@ vi.mock("./Canvas", async () => {
           data-problems={String(props.problems.size)}
           data-problem-steps={[...props.problems.keys()].join(",")}
           data-conditional={[...props.conditional].join(",")}
+          data-simulated={JSON.stringify((props.simulated ? [...props.simulated.entries()] : []).map(([k, tags]) => [k, tags.map((t) => t.text)]))}
+          data-start-tags={(props.start.tags ?? []).map((t) => t.text).join(",")}
         >
           <button data-item="start" data-summary={props.start.summary} aria-expanded={props.start.open} onClick={props.start.onOpen}>Start</button>
           <button onClick={() => props.onItem({ kind: "after", from: null })}>Add the first step</button>
@@ -2208,6 +2210,27 @@ describe("Simulate workflow", () => {
     expect(await screen.findByRole("complementary", { name: "Simulation" })).toBeTruthy();
   });
 
+  it("shows the result beside each step, under the banner, until it's hidden (§7.3)", async () => {
+    const summary = {
+      given: "input",
+      steps: [{ step_id: "id-transform", key: "transform", type: "flow.transform@1", origin: "evaluated", instances: 1, statuses: { succeeded: 1 }, ports: {}, final: { attempt: 1, status: "succeeded" } }],
+    };  // prettier-ignore
+    const ended = { ...simState("started"), run: { status: "succeeded", queued_at: null, started_at: "2026-10-15T10:42:05Z", ended_at: "2026-10-15T10:42:19Z", error: null, iterations: 0 } };
+    answers.set(`GET ${BASE}`, () => json({ ...WORKFLOW, draft: draftWith("transform") }));
+    answers.set(`GET ${SIM}`, () => json([simRequest("started")])); // a reload finds the latest
+    answers.set(`GET ${SIM}/r1`, () => json(ended));
+    answers.set(`GET ${SIM}/r1/steps`, () => json(summary));
+    await show();
+    await vi.waitFor(() => expect(steps().dataset.simulated).toBe(JSON.stringify([["id-transform", ["succeeded", "evaluated"]]])));
+    expect(steps().dataset.startTags).toBe("input");
+    expect(screen.getByText("Hide the result")).toBeTruthy();
+    await userEvent.click(screen.getByRole("button", { name: "Hide the result" }));
+    expect(steps().dataset.simulated).toBe("[]");
+    expect(screen.getByText("Simulation result hidden · Succeeded · revision 2")).toBeTruthy();
+    await userEvent.click(screen.getByRole("button", { name: "Show the result" }));
+    expect(steps().dataset.simulated).toBe(JSON.stringify([["id-transform", ["succeeded", "evaluated"]]]));
+  });
+
   it("asks Publish's own question about edits not applied, worded for simulating", async () => {
     await unappliedDuration();
     await userEvent.click(screen.getByRole("button", { name: "◌ Simulate workflow" }));
diff --git a/frontend/src/routes/editor/simulation/ResultBar.test.tsx b/frontend/src/routes/editor/simulation/ResultBar.test.tsx
new file mode 100644
index 00000000..543c5923
--- /dev/null
+++ b/frontend/src/routes/editor/simulation/ResultBar.test.tsx
@@ -0,0 +1,41 @@
+// SPDX-License-Identifier: Apache-2.0
+import { render, screen } from "@testing-library/react";
+import userEvent from "@testing-library/user-event";
+import { describe, expect, it, vi } from "vitest";
+import { ResultBar } from "./ResultBar";
+
+const props = (over: Partial<Parameters<typeof ResultBar>[0]> = {}) => ({
+  phase: "succeeded" as const, revision: 14, endedAt: "2026-10-15T10:42:19Z", notWaited: false, hidden: false,
+  onHide: vi.fn(), onShow: vi.fn(), onPanel: vi.fn(), onCancel: vi.fn(), ...over,
+});  // prettier-ignore
+
+describe("the canvas's bar for a simulation (§7.3; the ResultCanvas and Running boards)", () => {
+  it("says while it runs that nothing is sent, and offers Cancel", async () => {
+    const p = props({ phase: "running", endedAt: null });
+    render(<ResultBar {...p} />);
+    expect(screen.getByText("◌ Simulating · running · nothing is sent")).toBeTruthy();
+    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
+    expect(p.onCancel).toHaveBeenCalled();
+  });
+
+  it("says once it ended that nothing was sent and what that doesn't prove, and when a timer wasn't waited", async () => {
+    const p = props({ notWaited: true });
+    render(<ResultBar {...p} />);
+    expect(screen.getByRole("status").textContent).toContain("Simulated. Nothing was sent. Results don't prove the live call will succeed.");
+    expect(screen.getByText("Flow delays and wait-until weren't waited; the simulation clock wasn't advanced.")).toBeTruthy();
+    expect(screen.getByText(`revision 14 · ${new Date("2026-10-15T10:42:19Z").toLocaleTimeString("en-GB")}`)).toBeTruthy();
+    await userEvent.click(screen.getByRole("button", { name: "Simulation" }));
+    expect(p.onPanel).toHaveBeenCalled();
+    await userEvent.click(screen.getByRole("button", { name: "Hide the result" }));
+    expect(p.onHide).toHaveBeenCalled();
+  });
+
+  it("once hidden, is one bar that brings the result back", async () => {
+    const p = props({ hidden: true });
+    render(<ResultBar {...p} />);
+    expect(screen.getByText("Simulation result hidden · Succeeded · revision 14")).toBeTruthy();
+    expect(screen.queryByText(/Nothing was sent/)).toBeNull();
+    await userEvent.click(screen.getByRole("button", { name: "Show the result" }));
+    expect(p.onShow).toHaveBeenCalled();
+  });
+});
diff --git a/frontend/src/routes/editor/simulation/SimTags.test.tsx b/frontend/src/routes/editor/simulation/SimTags.test.tsx
new file mode 100644
index 00000000..17d88687
--- /dev/null
+++ b/frontend/src/routes/editor/simulation/SimTags.test.tsx
@@ -0,0 +1,38 @@
+// SPDX-License-Identifier: Apache-2.0
+import { render, screen, within } from "@testing-library/react";
+import { expect, it } from "vitest";
+import { SimTags } from "./SimTags";
+
+it("lists a step's result beside its card, in words, each tag drawn as what it is (§7.3, §7.4)", () => {
+  render(
+    <SimTags
+      label="notify"
+      tags={[
+        { text: "succeeded", kind: "ok" },
+        { text: "attempt 2 of 3", kind: "note" },
+        { text: "fixture · not sent", kind: "fixture" },
+        { text: "input", kind: "given" },
+        { text: "evaluated", kind: "evaluated" },
+        { text: "didn't run", kind: "absent" },
+        { text: "failed", kind: "fail" },
+      ]}
+    />,
+  );
+  const list = screen.getByRole("list", { name: "notify: simulated result" });
+  const tag = (text: string) => within(list).getByText(text).className;
+  expect(list.className).toMatch(/\bleft-full\b/); // beside the card…
+  expect(list.className).toMatch(/@max-3xl:top-full/); // …under it at narrow widths
+  expect(tag("succeeded")).toMatch(/border-ok/);
+  expect(tag("failed")).toMatch(/border-danger/);
+  expect(tag("fixture · not sent")).toMatch(/hatch-sim/);
+  expect(tag("fixture · not sent")).toMatch(/text-sim/); // the hatch only behind slate text
+  expect(tag("input")).toMatch(/border-sim/);
+  expect(tag("evaluated")).toMatch(/border-line-strong/);
+  expect(tag("didn't run")).toMatch(/border-dashed/);
+  expect(tag("attempt 2 of 3")).not.toMatch(/\bborder\b/);
+});
+
+it("draws nothing without a result", () => {
+  const { container } = render(<SimTags label="notify" tags={[]} />);
+  expect(container.textContent).toBe("");
+});
diff --git a/frontend/src/routes/editor/simulation/results.test.ts b/frontend/src/routes/editor/simulation/results.test.ts
new file mode 100644
index 00000000..e85adeb4
--- /dev/null
+++ b/frontend/src/routes/editor/simulation/results.test.ts
@@ -0,0 +1,55 @@
+// SPDX-License-Identifier: Apache-2.0
+import { describe, expect, it } from "vitest";
+import type { StepSummary } from "../../../lib/simulations";
+import { tagsOf, words } from "./results";
+
+type Final = NonNullable<StepSummary["final"]>;
+const summary = (over: Partial<StepSummary>): StepSummary => ({
+  step_id: "id-a", key: "a", type: "testkit.echo@1", origin: "fixture_not_sent", instances: 1, statuses: { succeeded: 1 },
+  ports: {}, final: null, ...over,
+});  // prettier-ignore
+const final = (over: Partial<Final> = {}): Final => ({ attempt: 1, status: "succeeded", output: null, input: null, effect: null, ...over });
+
+describe("a step's result on the canvas (§7.3, §7.4; the ResultCanvas and Running boards)", () => {
+  it("shows a step that ran once by its final attempt, and where its data came from", () => {
+    expect(words(tagsOf(summary({ final: final() }), { maxAttempts: 3, ended: true }))).toEqual(["succeeded", "fixture · not sent"]);
+    expect(words(tagsOf(summary({ final: final({ attempt: 2 }) }), { maxAttempts: 3, ended: true }))).toEqual(["succeeded", "attempt 2 of 3", "fixture · not sent"]);
+  });
+
+  it("says the port a branch took beside its evaluation, and that a timer wasn't waited", () => {
+    const ifStep = summary({ type: "flow.if@1", origin: "evaluated", final: final({ effect: { port: "true" } }), ports: { true: 1 } });
+    expect(words(tagsOf(ifStep, { maxAttempts: 1, ended: true }))).toEqual(["succeeded", "evaluated · → true"]);
+    const delay = summary({ type: "flow.delay@1", origin: "evaluated_not_waited", final: final() });
+    expect(words(tagsOf(delay, { maxAttempts: 1, ended: true }))).toEqual(["succeeded", "evaluated · not waited"]);
+  });
+
+  it("gives a loop its iterations once it ended, and its items while it runs", () => {
+    const loop = summary({ type: "flow.loop@1", origin: "evaluated", final: final({ output: { items: [], failures: [], count: 12 } }) });
+    expect(words(tagsOf(loop, { maxAttempts: 1, ended: true }))).toEqual(["succeeded", "12 iterations"]);
+    const running = summary({ type: "flow.loop@1", origin: "evaluated", statuses: { running: 1 }, final: final({ status: "running", input: { items: [1, 2, 3] } }) });
+    expect(words(tagsOf(running, { maxAttempts: 1, ended: false }))).toEqual(["running", "3 items"]);
+    const cut = summary({ type: "flow.loop@1", origin: "evaluated", final: final({ output: "[truncated]" }) });
+    expect(words(tagsOf(cut, { maxAttempts: 1, ended: true }))).toEqual(["succeeded"]);
+  });
+
+  it("totals a step's instances over every opened iteration, skipped ones included, its ports apart", () => {
+    const notify = summary({ instances: 12, statuses: { succeeded: 1, failed: 2, skipped: 9 } });
+    expect(words(tagsOf(notify, { maxAttempts: 3, ended: true }))).toEqual(["12 instances: 1 succeeded · 2 failed · 9 skipped", "fixture · not sent"]);
+    const branch = summary({ type: "flow.if@1", origin: "evaluated", instances: 12, statuses: { succeeded: 12 }, ports: { true: 3, false: 9 } });
+    expect(words(tagsOf(branch, { maxAttempts: 1, ended: true }))).toEqual(["12 instances: 12 succeeded", "evaluated", "→ true ×3", "→ false ×9"]);
+    const sofar = summary({ instances: 4, statuses: { succeeded: 1, failed: 1, skipped: 2 } });
+    expect(words(tagsOf(sofar, { maxAttempts: 3, ended: false }))).toEqual(["So far, 4 instances: 1 succeeded · 1 failed · 2 skipped", "fixture · not sent"]);
+  });
+
+  it("says why a step has no result, in words", () => {
+    expect(words(tagsOf(summary({ instances: 0, statuses: {}, origin: "didnt_run" }), { maxAttempts: 1, ended: true }))).toEqual(["didn't run"]);
+    expect(words(tagsOf(summary({ instances: 0, statuses: {}, origin: "not_reached_yet" }), { maxAttempts: 1, ended: false }))).toEqual(["not reached yet"]);
+    expect(words(tagsOf(summary({ instances: 1, statuses: { skipped: 1 }, origin: "skipped", final: final({ status: "skipped" }) }), { maxAttempts: 1, ended: true }))).toEqual(["skipped"]);
+  });
+
+  it("marks each tag by what it is: a status, a person's values, a fixture, an evaluation, an absence", () => {
+    const tags = tagsOf(summary({ final: final() }), { maxAttempts: 3, ended: true });
+    expect(tags.map((t) => t.kind)).toEqual(["ok", "fixture"]);
+    expect(tagsOf(summary({ instances: 0, statuses: {}, origin: "not_recorded" }), { maxAttempts: 1, ended: true })[0]!.kind).toBe("absent");
+  });
+});
```

- [ ] **Step 2: Run them**

Run: `npx --offline pnpm@12.6.0 exec vitest run src/routes/editor/simulation/results.test.ts
src/routes/editor/simulation/SimTags.test.tsx src/routes/editor/simulation/ResultBar.test.tsx
src/routes/editor/StepCard.test.tsx src/routes/editor/Editor.test.tsx`

Expected: FAIL: `results.test.ts`, `SimTags.test.tsx` and `ResultBar.test.tsx` can't import their modules; 1 failed and
161 passed: the canvas gets no tags (`expected '[]' to be '[["id-transform",["succeeded","evalua…'`). The step card's
tests pass.

- [ ] **Step 3: Implement**

Apply:

```diff
diff --git a/frontend/src/routes/editor/Canvas.tsx b/frontend/src/routes/editor/Canvas.tsx
index c3760e72..92016972 100644
--- a/frontend/src/routes/editor/Canvas.tsx
+++ b/frontend/src/routes/editor/Canvas.tsx
@@ -21,6 +21,7 @@ import { StartNode, type StartData } from "./StartCard";
 import { StepNode, type Problems, type StepData } from "./StepCard";
 import { PLUS, Pluses, placePluses, type Box, type Point } from "./pluses";
 import { mustReveal } from "./reveal";
+import type { SimTag } from "./simulation/results";
 
 const nodeTypes = { step: StepNode, start: StartNode } satisfies NodeTypes;
 const edgeTypes = { flow: FlowEdge } satisfies EdgeTypes;
@@ -48,7 +49,8 @@ export interface CanvasProps {
   placing: boolean; // the next click on an empty place puts a step there (WCAG 2.5.7)
   overview: boolean; // the minimap: off while a side panel narrows the canvas (the owner's ruling on milestone 3)
   onPlace: (at: { x: number; y: number }) => void; // the click, in the canvas's own coordinates
-  start: { summary: string; open: boolean; onOpen: () => void }; // the start card: what starts a run, and its panel
+  start: { summary: string; open: boolean; onOpen: () => void; tags?: SimTag[] }; // the start card: what starts a run, and its panel
+  simulated?: Map<string, SimTag[]>; // each step's result in the editor's simulation, by identity (4d-1c)
 }
 
 /** What React Flow draws: the start card, each step, an edge from the start card to each entry step, and each edge
@@ -68,6 +70,7 @@ function build(p: CanvasProps): { nodes: Node[]; edges: Edge[] } {
         separate: p.separate.get(idKey(n.id)) ?? 0, conditional: p.conditional.has(idKey(n.id)), current: p.current !== null && sameId(p.current, n.id), focusId: p.focusId,
         editable: p.editable,
         onItem: p.onItem,
+        simulated: p.simulated?.get(idKey(n.id)),
       };  // prettier-ignore
       return { id: idKey(n.id), type: "step", position: pos(n), draggable: p.editable, selectable: false, data, ...SIZE };
     }),
diff --git a/frontend/src/routes/editor/Editor.tsx b/frontend/src/routes/editor/Editor.tsx
index 41c49827..4e3d6151 100644
--- a/frontend/src/routes/editor/Editor.tsx
+++ b/frontend/src/routes/editor/Editor.tsx
@@ -21,7 +21,7 @@ import { begin, record, redo, undo, type History } from "../../lib/history";
 import { CARD, layout } from "../../lib/layout";
 import { guardLeaving } from "../../lib/leaving";
 import type { Path } from "../../lib/schemaForm";
-import { freeze } from "../../lib/simulations";
+import { ENDED, freeze } from "../../lib/simulations";
 import { useDocumentTitle } from "../../lib/title";
 import { schedulesQuery, startSummary, workflowBindingsQuery } from "../../lib/triggers";
 import {
@@ -44,6 +44,8 @@ import { DeclassifyPanel } from "./DeclassifyPanel";
 import { ProblemsPanel, type PublishProblems } from "./ProblemsPanel";
 import { SaveState } from "./SaveState";
 import { SimulateDialog } from "./simulation/SimulateDialog";
+import { ResultBar } from "./simulation/ResultBar";
+import { tagsOf, type SimTag } from "./simulation/results";
 import { SimulationPanel } from "./simulation/SimulationPanel";
 import { useSimulation } from "./simulation/useSimulation";
 import { type Problems } from "./StepCard";
@@ -477,6 +479,22 @@ function Editor({
   const simulator = canEdit(role) && viewing === null;
   const [simulateAt, setSimulateAt] = useState<{ revision: number; doc: GraphDoc } | null>(null); // the input, asked
   const [saving, setSaving] = useState(false); // the save Simulate waits for
+  // Its result on the canvas (§7.3): tags beside each step, under the banner, until "Hide the result", which hides this
+  // simulation's only (the next one shows again).
+  const simulationId = simulation.state?.request.id ?? null;
+  const [hiddenFor, setHiddenFor] = useState<string | null>(null);
+  const resultShown = simulator && simulationId !== null && simulation.phase !== null && hiddenFor !== simulationId;
+  const simulated = useMemo(() => {
+    const tags = new Map<string, SimTag[]>();
+    if (!resultShown) return tags;
+    const ended = simulation.phase !== null && ENDED.has(simulation.phase);
+    for (const s of simulation.steps?.steps ?? []) {
+      const node = findNode(doc, s.step_id);
+      const maxAttempts = node?.options?.max_attempts ?? typeMap.get(s.type)?.retry.max_attempts ?? null;
+      tags.set(idKey(s.step_id), tagsOf(s, { maxAttempts, ended }));
+    }
+    return tags;
+  }, [resultShown, simulation.phase, simulation.steps, doc, typeMap]);
   // When editing stops (a conflict, an exit, a publication), what only editing offers stops with it: an open dialog
   // closes, placing ends (a click on a read-only canvas places nothing) and says so. Focus held by what's gone (the
   // dialog, a "+", Auto layout, Add step, a panel's buttons) goes to what's drawn: a panel's heading when it was in
@@ -1280,6 +1298,19 @@ function Editor({
           <Button size="sm" variant="primary" onClick={() => setReloading(true)}>Reload</Button>
         </div>
       )}
+      {simulator && simulationId !== null && simulation.phase !== null && simulation.state && (
+        <ResultBar
+          phase={simulation.phase}
+          revision={simulation.state.request.draft_revision}
+          endedAt={simulation.state.run?.ended_at ?? simulation.state.request.ended_at}
+          notWaited={(simulation.steps?.steps ?? []).some((s) => s.origin === "evaluated_not_waited")}
+          hidden={!resultShown}
+          onHide={() => setHiddenFor(simulationId)}
+          onShow={() => setHiddenFor(null)}
+          onPanel={() => setSide({ kind: "simulation" })}
+          onCancel={() => void simulation.cancel()}
+        />
+      )}
       <div className="flex min-h-0 flex-1 @max-3xl:flex-col">
         <div className="relative flex min-h-0 min-w-0 flex-1">
           {placing && editable && (
@@ -1316,7 +1347,9 @@ function Editor({
             summary,
             open: side?.kind === "triggers",
             onOpen: () => setSide(side?.kind === "triggers" ? null : { kind: "triggers" }),
+            tags: resultShown && simulation.steps?.given === "input" ? [{ text: "input", kind: "given" }] : undefined,
           }}
+          simulated={simulated}
           />
         </div>
         {open && (
diff --git a/frontend/src/routes/editor/StartCard.tsx b/frontend/src/routes/editor/StartCard.tsx
index c48a4cb0..4bff7bdf 100644
--- a/frontend/src/routes/editor/StartCard.tsx
+++ b/frontend/src/routes/editor/StartCard.tsx
@@ -7,6 +7,8 @@ import { Handle, Position, type Node, type NodeProps } from "@xyflow/react";
 import { START } from "../../lib/graph";
 import { startLabel } from "../../lib/triggers";
 import { item, type ItemAction } from "./items";
+import type { SimTag } from "./simulation/results";
+import { SimTags } from "./simulation/SimTags";
 
 export type StartData = {
   empty: boolean;
@@ -15,6 +17,7 @@ export type StartData = {
   onItem: (action: ItemAction) => void;
   summary: string; // what starts a run, in words
   open: boolean; // the Triggers panel is open
+  tags?: SimTag[]; // in a simulation of the whole workflow: the input a person gave (§7.4)
   onOpen: () => void;
 };
 
@@ -35,6 +38,7 @@ export function StartNode({ data }: NodeProps<Node<StartData, "start">>) {
         <span className="truncate text-small text-muted">{data.summary}</span>
       </button>
       <Handle type="source" id="out" position={Position.Bottom} isConnectable={false} />
+      {data.tags && <SimTags label="Start" tags={data.tags} />}
       {data.empty && data.editable && (
         <button
           type="button"
diff --git a/frontend/src/routes/editor/StepCard.tsx b/frontend/src/routes/editor/StepCard.tsx
index b2180d2e..2bb1f1ff 100644
--- a/frontend/src/routes/editor/StepCard.tsx
+++ b/frontend/src/routes/editor/StepCard.tsx
@@ -6,6 +6,8 @@ import { Fragment } from "react";
 import type { PortRef } from "../../lib/graph";
 import type { GraphNode, NodeType } from "../../lib/workflows";
 import { item, say, type ItemAction } from "./items";
+import type { SimTag } from "./simulation/results";
+import { SimTags } from "./simulation/SimTags";
 
 const CODES: Record<string, string> = {
   "flow.if": "IF", "flow.switch": "SWITCH", "flow.loop": "LOOP", "flow.filter": "FILTER", "flow.set_variables": "SET",
@@ -84,6 +86,7 @@ export type StepData = {
   focusId: string;
   editable: boolean;
   onItem: (action: ItemAction) => void;
+  simulated?: SimTag[]; // its result in the editor's simulation, beside the card (4d-1c)
 };
 
 // React Flow turns a node's pointer events off when it can be neither selected nor dragged (ledger M11): its
@@ -111,6 +114,7 @@ export function StepNode({ data }: NodeProps<Node<StepData, "step">>) {
         tabIndex={data.focusId === item.node(node.id) ? 0 : -1}
         onOpen={() => data.onItem({ kind: "open", node: node.id })}
       />
+      {data.simulated && <SimTags label={node.key} tags={data.simulated} />}
       {ports.map((port, i) => {
         const from: PortRef = { node: node.id, port };
         const id = item.port(node.id, port);
diff --git a/frontend/src/routes/editor/simulation/ResultBar.tsx b/frontend/src/routes/editor/simulation/ResultBar.tsx
new file mode 100644
index 00000000..8223d91d
--- /dev/null
+++ b/frontend/src/routes/editor/simulation/ResultBar.tsx
@@ -0,0 +1,49 @@
+// SPDX-License-Identifier: Apache-2.0
+// The canvas's bar for the editor's simulation (4d-1c; the simulation design §7.3; the Running and ResultCanvas
+// boards). While it runs: that nothing is sent, and Cancel. Once ended: the hatched banner (nothing was sent, and what
+// that doesn't prove; that flow timers weren't waited, when one wasn't), its status, revision and end, the panel, and
+// "Hide the result". Hidden: one bar that brings it back; the simulation, its history, and one running are untouched.
+import { Button } from "../../../components/Button";
+import { ENDED, type Phase } from "../../../lib/simulations";
+import { StatusChip } from "./chips";
+import { STATUS, clock } from "./lifecycle";
+import { SimBanner } from "./SimBanner";
+
+const BAR = "flex flex-wrap items-center gap-3 border-b border-line bg-surface-2 px-5 py-2.5 text-small";
+
+export function ResultBar({ phase, revision, endedAt, notWaited, hidden, onHide, onShow, onPanel, onCancel }: {
+  phase: Phase; revision: number; endedAt: string | null; notWaited: boolean; hidden: boolean;
+  onHide: () => void; onShow: () => void; onPanel: () => void; onCancel: () => void;
+}) {  // prettier-ignore
+  if (!ENDED.has(phase)) {
+    const going = phase === "cancel_requested" ? "cancel requested" : phase;
+    return (
+      <div className={BAR}>
+        <span className="grow text-sim">{`◌ Simulating · ${going} · nothing is sent`}</span>
+        {phase !== "cancel_requested" && <Button size="sm" onClick={onCancel}>Cancel</Button>}
+      </div>
+    );
+  }
+  if (hidden) {
+    return (
+      <div className={BAR}>
+        <span className="grow">{`Simulation result hidden · ${STATUS[phase]} · revision ${revision}`}</span>
+        <Button size="sm" onClick={onShow}>Show the result</Button>
+      </div>
+    );
+  }
+  return (
+    <div className="border-b border-line bg-surface px-5 py-2.5">
+      <SimBanner role="status">
+        <p><strong>Simulated.</strong> Nothing was sent. Results don&apos;t prove the live call will succeed.</p>
+        {notWaited && <p>Flow delays and wait-until weren&apos;t waited; the simulation clock wasn&apos;t advanced.</p>}
+        <p className="flex flex-wrap items-center gap-2 text-ink">
+          <StatusChip phase={phase} />
+          <span className="grow text-muted">{`revision ${revision}${endedAt ? ` · ${clock(endedAt)}` : ""}`}</span>
+          <Button size="sm" onClick={onPanel}>Simulation</Button>
+          <Button size="sm" onClick={onHide}>Hide the result</Button>
+        </p>
+      </SimBanner>
+    </div>
+  );
+}
diff --git a/frontend/src/routes/editor/simulation/SimTags.tsx b/frontend/src/routes/editor/simulation/SimTags.tsx
new file mode 100644
index 00000000..f5b653d0
--- /dev/null
+++ b/frontend/src/routes/editor/simulation/SimTags.tsx
@@ -0,0 +1,31 @@
+// SPDX-License-Identifier: Apache-2.0
+// A simulated step's tags beside its card (4d-1c; the simulation design §7.3; the ResultCanvas and Narrow boards):
+// beside it, under it at narrow widths, never on it, so the card and its problem and "may not run" badges stay as they
+// are. Each tag is drawn as what it is: a status, values a person gave (slate outline), a fixture (hatched slate), an
+// evaluation, an absence (dashed), a note; the words carry it, the look only repeats them (§7.4).
+import type { SimTag, SimTagKind } from "./results";
+
+const LOOK: Record<SimTagKind, string> = {
+  ok: "rounded-md border border-ok bg-surface px-1.5 text-ok",
+  fail: "rounded-md border border-danger bg-surface px-1.5 text-danger",
+  status: "rounded-md border border-line-strong bg-surface px-1.5 text-muted",
+  given: "rounded-sm border border-sim bg-surface px-1.5 text-sim",
+  fixture: "hatch-sim rounded-sm border border-sim bg-sim-bg px-1.5 text-sim",
+  evaluated: "rounded-sm border border-line-strong bg-surface px-1.5 text-muted",
+  absent: "rounded-sm border border-dashed border-line-strong bg-surface px-1.5 text-muted",
+  note: "bg-surface text-muted",
+};
+
+export function SimTags({ label, tags }: { label: string; tags: SimTag[] }) {
+  if (tags.length === 0) return null;
+  return (
+    <ul
+      aria-label={`${label}: simulated result`}
+      className="pointer-events-none absolute top-0 left-full ml-2 flex w-[240px] flex-wrap content-start gap-1 text-meta @max-3xl:top-full @max-3xl:left-0 @max-3xl:mt-[56px] @max-3xl:ml-0"
+    >
+      {tags.map((t, i) => (
+        <li key={i} className={`leading-[18px] whitespace-nowrap ${LOOK[t.kind]}`}>{t.text}</li>
+      ))}
+    </ul>
+  );
+}
diff --git a/frontend/src/routes/editor/simulation/results.ts b/frontend/src/routes/editor/simulation/results.ts
new file mode 100644
index 00000000..8087182b
--- /dev/null
+++ b/frontend/src/routes/editor/simulation/results.ts
@@ -0,0 +1,78 @@
+// SPDX-License-Identifier: Apache-2.0
+// A simulated step's result, as tags beside its card (4d-1c; the simulation design §7.3, §7.4; the ResultCanvas and
+// Running boards), from the server's per-step summary, never a partial page. A step that ran once shows its final
+// attempt; a loop's step totals its instances, one per opened iteration, skipped ones included, its ports apart; a
+// step with none says why, in the server's tag. Always words: the colour and the hatch only repeat them.
+import type { Origin, StepSummary } from "../../../lib/simulations";
+
+/** What a tag is: a status (ok, failed or other), values a person gave, a plugin's fixture, an evaluation, an absence,
+ * or a note (an attempt, a loop's iterations). */
+export type SimTagKind = "ok" | "fail" | "status" | "given" | "fixture" | "evaluated" | "absent" | "note";
+export interface SimTag {
+  text: string;
+  kind: SimTagKind;
+}
+
+/** §7.4's tags, in the server's code and the words the editor shows. */
+export const ORIGIN: Record<Origin | "input" | "seeded", string> = {
+  input: "input",
+  seeded: "seeded",
+  evaluated: "evaluated",
+  evaluated_not_waited: "evaluated · not waited",
+  fixture_not_sent: "fixture · not sent",
+  skipped: "skipped",
+  not_started: "not started",
+  cancelled: "cancelled",
+  didnt_run: "didn't run",
+  not_recorded: "not recorded",
+  not_reached_yet: "not reached yet",
+};
+const ORIGIN_KIND: Record<Origin, SimTagKind> = {
+  evaluated: "evaluated",
+  evaluated_not_waited: "evaluated",
+  fixture_not_sent: "fixture",
+  skipped: "absent",
+  not_started: "absent",
+  cancelled: "status",
+  didnt_run: "absent",
+  not_recorded: "absent",
+  not_reached_yet: "absent",
+};
+
+const ORDER = ["succeeded", "failed", "cancelled", "skipped", "not_started", "running"];
+const said = (status: string) => status.replace("_", " ");
+const statusKind = (status: string): SimTagKind => (status === "succeeded" ? "ok" : status === "failed" ? "fail" : "status");
+const field = (v: unknown, key: string): unknown => (typeof v === "object" && v !== null && !Array.isArray(v) ? (v as Record<string, unknown>)[key] : undefined);
+
+export const words = (tags: SimTag[]) => tags.map((t) => t.text);
+
+/** A step's tags. `maxAttempts`: its own, or its type's (an attempt is said "of" it); `ended`: whether the
+ * simulation has (while it runs, a loop's step says what it has so far). */
+export function tagsOf(s: StepSummary, { maxAttempts, ended }: { maxAttempts: number | null; ended: boolean }): SimTag[] {
+  if (s.instances === 0) return [{ text: ORIGIN[s.origin], kind: ORIGIN_KIND[s.origin] }];
+  const loop = s.type.startsWith("flow.loop@");
+  if (s.instances === 1) {
+    const status = typeof field(s.final, "status") === "string" ? (field(s.final, "status") as string) : (Object.keys(s.statuses)[0] ?? "running");
+    if (status === "skipped" || status === "not_started" || status === "cancelled") return [{ text: said(status), kind: ORIGIN_KIND[status] }];
+    const tags: SimTag[] = [{ text: said(status), kind: statusKind(status) }];
+    const attempt = field(s.final, "attempt");
+    if (typeof attempt === "number" && attempt > 1 && maxAttempts) tags.push({ text: `attempt ${attempt} of ${maxAttempts}`, kind: "note" });
+    if (loop) {
+      const count = field(field(s.final, "output"), "count");
+      const items = field(field(s.final, "input"), "items");
+      if (typeof count === "number") tags.push({ text: `${count} ${count === 1 ? "iteration" : "iterations"}`, kind: "note" });
+      else if (!ended && Array.isArray(items)) tags.push({ text: `${items.length} ${items.length === 1 ? "item" : "items"}`, kind: "note" });
+      return tags;
+    }
+    const port = field(field(s.final, "effect"), "port");
+    const origin = ORIGIN[s.origin] + (typeof port === "string" && s.origin === "evaluated" ? ` · → ${port}` : "");
+    return [...tags, { text: origin, kind: ORIGIN_KIND[s.origin] }];
+  }
+  const counts = ORDER.filter((k) => (s.statuses[k] ?? 0) > 0).map((k) => `${s.statuses[k]} ${said(k)}`).join(" · ");
+  const total = `${s.instances} instances: ${counts}`;
+  return [
+    { text: ended ? total : `So far, ${total}`, kind: "status" },
+    ...(loop ? [] : [{ text: ORIGIN[s.origin], kind: ORIGIN_KIND[s.origin] }]),
+    ...Object.entries(s.ports).map(([port, n]): SimTag => ({ text: `→ ${port} ×${n}`, kind: "evaluated" })),
+  ];
+}
```

- [ ] **Step 4: Run them again**

Run: the same command.

Expected: PASS, 173 passed.

- [ ] **Step 5: Static checks**

Run: the two of "How to run things". Expected: no output.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/routes/editor
git commit -m "feat(editor): a simulation's result beside each step, under its banner, until it's hidden (4d-1c)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: The result in the panel

**Spec:** §7.5 (the Simulation panel); the ResultPanel board.

**Files:**
- Create: `frontend/src/routes/editor/simulation/loopBody.ts`, `frontend/src/routes/editor/simulation/loopBody.test.ts`
- Create: `frontend/src/routes/editor/simulation/Iterations.tsx`,
  `frontend/src/routes/editor/simulation/Iterations.test.tsx`
- Create: `frontend/src/routes/editor/simulation/SimulationResult.tsx`,
  `frontend/src/routes/editor/simulation/SimulationResult.test.tsx`
- Modify: `frontend/src/routes/editor/simulation/SimTags.tsx` (`InlineTags`)
- Modify: `frontend/src/routes/editor/Editor.tsx`, `frontend/src/routes/editor/Editor.test.tsx`

**Interfaces:**
- Consumes: `stepInstancesQuery` (Task 2); `tagsOf` (Task 6); `SimBanner` (Task 3); `SimulationPanel`'s `children`
  (Task 5).
- Produces:
  - `loopBody.ts`: `PAGE = 4`; `bodyOf(doc, loopId): GraphNode[]` (what's reachable from the loop's `body` port, as
    the engine reads a loop's region, minus the regions of loops nested in it); `iterationOf(prefix, loopKey, index)`
    (`loop:index`, joined by `/` when nested); `cellOf(item, type)`.
    The name isn't `iterations.ts`: on macOS's case-insensitive disk, `./Iterations` would resolve to it.
  - `Iterations({ tenantId, workflowId, requestId, loop: { key, prefix }, body, onOpen? })`.
  - `SimulationResult({ tenantId, workflowId, session, doc, attemptsOf, onGoTo, onOpen? })`.
  - `InlineTags({ tags })`.
  - In `Editor`: `attemptsOf(summary)` (the step's own `max_attempts`, else its type's).

Below the lifecycle: the banner once it ended; "Checks on the server" (the request's `admission_checks`, each with Go
to when its step is in the draft); the steps in run order, with the canvas's tags (ruling 3) and Go to, only those
reached while it runs ("Steps so far"); a loop's iterations under it (ruling 4), four at a time: each row what the
loop's own steps did in that iteration, "Iterations 1–4 of 12", "Previous 4" and "Next 4", a failed step's code, and
"Open" where a later task gives it somewhere to go; the input used, as the request stored it (ruling 8).

- [ ] **Step 1: Write the failing tests**

Apply:

```diff
diff --git a/frontend/src/routes/editor/Editor.test.tsx b/frontend/src/routes/editor/Editor.test.tsx
index f0910071..c722c081 100644
--- a/frontend/src/routes/editor/Editor.test.tsx
+++ b/frontend/src/routes/editor/Editor.test.tsx
@@ -2231,6 +2231,26 @@ describe("Simulate workflow", () => {
     expect(steps().dataset.simulated).toBe(JSON.stringify([["id-transform", ["succeeded", "evaluated"]]]));
   });
 
+  it("lists the result in the Simulation panel, and goes to a step from it (§7.5)", async () => {
+    const summary = {
+      given: "input",
+      steps: [{ step_id: "id-transform", key: "transform", type: "flow.transform@1", origin: "evaluated", instances: 1, statuses: { succeeded: 1 }, ports: {}, final: { attempt: 1, status: "succeeded" } }],
+    };  // prettier-ignore
+    const ended = { ...simState("started"), run: { status: "succeeded", queued_at: null, started_at: "2026-10-15T10:42:05Z", ended_at: "2026-10-15T10:42:19Z", error: null, iterations: 0 } };
+    answers.set(`GET ${BASE}`, () => json({ ...WORKFLOW, draft: draftWith("transform") }));
+    answers.set(`GET ${SIM}`, () => json([simRequest("started")]));
+    answers.set(`GET ${SIM}/r1`, () => json(ended));
+    answers.set(`GET ${SIM}/r1/steps`, () => json(summary));
+    await show();
+    await screen.findByRole("button", { name: "Hide the result" }); // the simulation's read, ended
+    await userEvent.click(screen.getByRole("button", { name: "Simulation" }));
+    const panel = await screen.findByRole("complementary", { name: "Simulation" });
+    const listed = within(panel).getByRole("region", { name: "Steps, in run order" });
+    expect(within(listed).getByText("evaluated")).toBeTruthy();
+    await userEvent.click(within(listed).getByRole("button", { name: "Go to transform" }));
+    await vi.waitFor(() => expect(document.activeElement?.getAttribute("data-item")).toBe("node:id-transform"));
+  });
+
   it("asks Publish's own question about edits not applied, worded for simulating", async () => {
     await unappliedDuration();
     await userEvent.click(screen.getByRole("button", { name: "◌ Simulate workflow" }));
diff --git a/frontend/src/routes/editor/simulation/Iterations.test.tsx b/frontend/src/routes/editor/simulation/Iterations.test.tsx
new file mode 100644
index 00000000..8f012a86
--- /dev/null
+++ b/frontend/src/routes/editor/simulation/Iterations.test.tsx
@@ -0,0 +1,88 @@
+// SPDX-License-Identifier: Apache-2.0
+import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
+import { render, screen, within } from "@testing-library/react";
+import userEvent from "@testing-library/user-event";
+import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
+import { Iterations } from "./Iterations";
+
+const PATH = "/api/v1/t/t1/workflows/w1/draft/simulations/r1/steps";
+const TOTAL = 12;
+// Iteration n: is_offline took "true" on every other one; notify ran there (the 4th failed), and was skipped elsewhere.
+const instance = (step: string, n: number) =>
+  step === "id-is_offline"
+    ? { step_id: step, key: "is_offline", iteration_key: `each_ap:${n}`, attempt: 1, status: "succeeded", effect: { port: n % 2 ? "true" : "false" } }
+    : { step_id: step, key: "notify", iteration_key: `each_ap:${n}`, attempt: 1, status: n % 2 ? (n === 3 ? "failed" : "succeeded") : "skipped",
+        error: n === 3 ? { code: "invalid_blocks", message: "Block 2 has no text." } : null };  // prettier-ignore
+
+let asked: string[];
+let failing: boolean;
+const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
+beforeEach(() => {
+  asked = [];
+  failing = false;
+  vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
+    const url = new URL((input as Request).url);
+    asked.push(url.pathname + url.search);
+    const m = url.pathname.match(/\/steps\/([^/]+)\/instances$/);
+    if (failing || !m) return Promise.resolve(json({ error: "http_error" }, 500));
+    const offset = Number(url.searchParams.get("offset"));
+    const limit = Number(url.searchParams.get("limit"));
+    const items = Array.from({ length: Math.max(0, Math.min(limit, TOTAL - offset)) }, (_, i) => instance(m[1]!, offset + i));
+    return Promise.resolve(json({ total: TOTAL, items }));
+  });
+});
+afterEach(() => vi.restoreAllMocks());
+
+function show() {
+  const onOpen = vi.fn();
+  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
+  render(
+    <QueryClientProvider client={qc}>
+      <Iterations
+        tenantId="t1" workflowId="w1" requestId="r1" loop={{ key: "each_ap", prefix: "" }}
+        body={[{ id: "id-is_offline", key: "is_offline", type: "flow.if@1" }, { id: "id-notify", key: "notify", type: "slack.post@1" }]}
+        onOpen={onOpen}
+      />
+    </QueryClientProvider>,
+  );  // prettier-ignore
+  return { onOpen };
+}
+const rows = (list: HTMLElement) => within(list).getAllByRole("listitem").map((li) => li.textContent);
+
+describe("a loop's iterations, paged (§7.5; the ResultPanel board)", () => {
+  it("shows four iterations at a time, each as what its steps did, from the server's pages", async () => {
+    show();
+    const list = await screen.findByRole("list", { name: "each_ap's iterations, 1 to 4 of 12" });
+    expect(rows(list).slice(0, 3)).toEqual(["1 · is_offline → false · notify skipped", "2 · is_offline → true · notify succeeded", "3 · is_offline → false · notify skipped"]);
+    expect(rows(list)[3]).toContain("4 · is_offline → true · notify failed · invalid_blocks");
+    expect(screen.getByText("Iterations 1–4 of 12")).toBeTruthy();
+    expect(asked).toContain(`${PATH}/id-notify/instances?offset=0&limit=4`);
+  });
+
+  it("opens a failed step's instance in its iteration", async () => {
+    const { onOpen } = show();
+    await userEvent.click(await screen.findByRole("button", { name: "Open notify, iteration 4" }));
+    expect(onOpen).toHaveBeenCalledWith("id-notify", "each_ap:3");
+  });
+
+  it("pages on, and back, and stops at the last", async () => {
+    show();
+    await userEvent.click(await screen.findByRole("button", { name: "Next 4" }));
+    expect(await screen.findByRole("list", { name: "each_ap's iterations, 5 to 8 of 12" })).toBeTruthy();
+    expect(asked).toContain(`${PATH}/id-is_offline/instances?offset=4&limit=4`);
+    await userEvent.click(screen.getByRole("button", { name: "Next 4" }));
+    expect(await screen.findByText("Iterations 9–12 of 12")).toBeTruthy();
+    expect(screen.queryByRole("button", { name: /^Next/ })).toBeNull();
+    await userEvent.click(screen.getByRole("button", { name: "Previous 4" }));
+    expect(await screen.findByText("Iterations 5–8 of 12")).toBeTruthy();
+  });
+
+  it("says when they couldn't be read, and reads them again", async () => {
+    failing = true;
+    show();
+    expect(await screen.findByText("The iterations couldn't be read.")).toBeTruthy();
+    failing = false;
+    await userEvent.click(screen.getByRole("button", { name: "Read them again" }));
+    expect(await screen.findByRole("list", { name: "each_ap's iterations, 1 to 4 of 12" })).toBeTruthy();
+  });
+});
diff --git a/frontend/src/routes/editor/simulation/SimulationResult.test.tsx b/frontend/src/routes/editor/simulation/SimulationResult.test.tsx
new file mode 100644
index 00000000..2add9063
--- /dev/null
+++ b/frontend/src/routes/editor/simulation/SimulationResult.test.tsx
@@ -0,0 +1,133 @@
+// SPDX-License-Identifier: Apache-2.0
+import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
+import { render, screen, within } from "@testing-library/react";
+import userEvent from "@testing-library/user-event";
+import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
+import type { SimulationRequest, SimulationState, StepSummary } from "../../../lib/simulations";
+import type { GraphDoc } from "../../../lib/workflows";
+import { SimulationResult } from "./SimulationResult";
+import type { SimulationSession } from "./useSimulation";
+
+const request = (over: Partial<SimulationRequest> = {}): SimulationRequest => ({
+  id: "r1", workflow_id: "w1", draft_snapshot_id: "s1", draft_revision: 14, target_step_id: null, mode: "simulate",
+  source: "manual", status: "started", reason: null, queued_at: "2026-10-15T10:42:05Z", ended_at: null, admission_checks: [], ...over,
+});  // prettier-ignore
+const step = (key: string, over: Partial<StepSummary> = {}): StepSummary => ({
+  step_id: `id-${key}`, key, type: "testkit.echo@1", origin: "fixture_not_sent", instances: 1, statuses: { succeeded: 1 }, ports: {},
+  final: { attempt: 1, status: "succeeded" }, ...over,
+});  // prettier-ignore
+const node = (key: string, type: string) => ({ id: `id-${key}`, key, type, config: {} });
+const DOC = {
+  graph_format: 1,
+  nodes: [node("get_site", "testkit.echo@1"), node("each_ap", "flow.loop@1"), node("notify", "slack.post@1"), node("wait_10m", "flow.delay@1")],
+  edges: [{ from: { node: "id-each_ap", port: "body" }, to: { node: "id-notify" } }, { from: { node: "id-each_ap", port: "done" }, to: { node: "id-wait_10m" } }],
+} as unknown as GraphDoc;  // prettier-ignore
+const STEPS = [
+  step("get_site"),
+  step("each_ap", { type: "flow.loop@1", origin: "evaluated", final: { attempt: 1, status: "succeeded", output: { items: [], failures: [], count: 2 } } }),
+  step("notify", { instances: 2, statuses: { succeeded: 1, skipped: 1 }, final: null }),
+  step("wait_10m", { type: "flow.delay@1", origin: "evaluated_not_waited" }),
+  step("gone", { origin: "didnt_run", instances: 0, statuses: {}, final: null }),
+];
+
+function session(over: { phase?: SimulationSession["phase"]; state?: Partial<SimulationState>; request?: Partial<SimulationRequest>; steps?: StepSummary[] } = {}): SimulationSession {
+  const state: SimulationState = { request: request(over.request), run: null, cancel_requested: false, read_back: "kept", input: { site: "HQ Paris", floor: 3, api_token: "[redacted]" }, seeds: null, ...over.state };
+  return {
+    local: { kind: "admitted", frozen: null, request: state.request, latest: false }, state, steps: { given: "input", steps: over.steps ?? STEPS },
+    phase: over.phase ?? "succeeded", busy: false, readFailed: false, asOf: null, start: vi.fn(), checkAgain: vi.fn(), cancel: vi.fn(), readAgain: vi.fn(),
+  };  // prettier-ignore
+}
+
+const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
+beforeEach(() => {
+  vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
+    const url = new URL((input as Request).url);
+    if (url.pathname.endsWith("/steps/id-notify/instances")) {
+      return Promise.resolve(json({ total: 2, items: [
+        { step_id: "id-notify", key: "notify", iteration_key: "each_ap:0", attempt: 1, status: "succeeded" },
+        { step_id: "id-notify", key: "notify", iteration_key: "each_ap:1", attempt: 1, status: "skipped" },
+      ] }));  // prettier-ignore
+    }
+    return Promise.resolve(json({ error: "not_found" }, 404));
+  });
+});
+afterEach(() => vi.restoreAllMocks());
+
+function show(s: SimulationSession) {
+  const onGoTo = vi.fn();
+  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
+  render(
+    <QueryClientProvider client={qc}>
+      <SimulationResult tenantId="t1" workflowId="w1" session={s} doc={DOC} attemptsOf={() => 3} onGoTo={onGoTo} />
+    </QueryClientProvider>,
+  );
+  return { onGoTo };
+}
+const section = (name: string) => screen.getByRole("region", { name });
+
+describe("the Simulation panel's result (§7.5; the ResultPanel board)", () => {
+  it("says what a simulation proves, and that a flow timer wasn't waited", () => {
+    show(session());
+    expect(screen.getByText("Simulated.").parentElement?.textContent).toBe("Simulated. Nothing was sent. Results don't prove the live call will succeed.");
+    expect(screen.getByText("Flow delays and wait-until weren't waited; the simulation clock wasn't advanced.")).toBeTruthy();
+  });
+
+  it("lists the checks the server found at admission, each with Go to", async () => {
+    const check = { code: "connection.missing", message: "The connection “Slack ops” no longer exists.", node: "id-notify", field: null, fix: null, severity: "warning" as const };
+    const { onGoTo } = show(session({ request: { admission_checks: [check] } }));
+    const checks = section("Checks on the server");
+    expect(within(checks).getByText("Found when the simulation was admitted. They didn't stop it; a live run would meet them.")).toBeTruthy();
+    expect(within(checks).getByText("The connection “Slack ops” no longer exists.")).toBeTruthy();
+    await userEvent.click(within(checks).getByRole("button", { name: "Go to notify" }));
+    expect(onGoTo).toHaveBeenCalledWith("id-notify");
+  });
+
+  it("lists the steps in run order, with their tags and Go to", async () => {
+    const { onGoTo } = show(session());
+    const steps = section("Steps, in run order");
+    const rows = within(steps).getAllByRole("listitem");
+    expect(rows.map((r) => r.querySelector("[data-key]")?.textContent)).toEqual(["get_site", "each_ap", "notify", "wait_10m", "gone"]);
+    expect(within(rows[0]!).getByText("fixture · not sent")).toBeTruthy();
+    expect(within(rows[2]!).getByText("2 instances: 1 succeeded · 1 skipped")).toBeTruthy();
+    expect(within(rows[3]!).getByText("evaluated · not waited")).toBeTruthy();
+    expect(within(rows[4]!).getByText("didn't run")).toBeTruthy();
+    expect(within(rows[4]!).queryByRole("button", { name: /^Go to/ })).toBeNull(); // not in the draft any more
+    await userEvent.click(within(rows[0]!).getByRole("button", { name: "Go to get_site" }));
+    expect(onGoTo).toHaveBeenCalledWith("id-get_site");
+  });
+
+  it("opens a loop's iterations under it", async () => {
+    show(session());
+    const toggle = screen.getByRole("button", { name: "Iterations of each_ap" });
+    expect(toggle.getAttribute("aria-expanded")).toBe("false");
+    await userEvent.click(toggle);
+    expect(toggle.getAttribute("aria-expanded")).toBe("true");
+    expect(await screen.findByRole("list", { name: "each_ap's iterations, 1 to 2 of 2" })).toBeTruthy();
+  });
+
+  it("while it runs, lists only the steps reached so far, and no banner", () => {
+    show(session({ phase: "running", steps: [step("get_site"), step("each_ap", { type: "flow.loop@1", origin: "evaluated", statuses: { running: 1 }, final: { attempt: 1, status: "running" } }), step("notify", { origin: "not_reached_yet", instances: 0, statuses: {}, final: null })] }));
+    const rows = within(section("Steps so far")).getAllByRole("listitem");
+    expect(rows.map((r) => r.querySelector("[data-key]")?.textContent)).toEqual(["get_site", "each_ap"]);
+    expect(screen.queryByText("Simulated.")).toBeNull();
+    expect(screen.queryByRole("button", { name: /^Iterations of/ })).toBeNull();
+  });
+
+  it("shows the input used as the request stored it, sensitive values redacted", () => {
+    show(session());
+    const used = section("Input used");
+    expect(within(used).getByText("As this simulation's request stored it, sensitive values redacted.")).toBeTruthy();
+    const pairs = within(used).getAllByRole("term").map((t) => `${t.textContent}=${t.nextElementSibling?.textContent}`);
+    expect(pairs).toEqual(["site=HQ Paris", "floor=3", "api_token=redacted"]);
+  });
+
+  it("says when the input used isn't kept any more", () => {
+    show(session({ state: { read_back: "absent", input: null } }));
+    expect(within(section("Input used")).getByText("The input used isn't kept any more.")).toBeTruthy();
+  });
+
+  it("says when the input used can't be read back", () => {
+    show(session({ state: { read_back: "unreadable", input: null } }));
+    expect(within(section("Input used")).getByText("The input used couldn't be read back.")).toBeTruthy();
+  });
+});
diff --git a/frontend/src/routes/editor/simulation/loopBody.test.ts b/frontend/src/routes/editor/simulation/loopBody.test.ts
new file mode 100644
index 00000000..9bb03524
--- /dev/null
+++ b/frontend/src/routes/editor/simulation/loopBody.test.ts
@@ -0,0 +1,35 @@
+// SPDX-License-Identifier: Apache-2.0
+import { describe, expect, it } from "vitest";
+import type { GraphDoc } from "../../../lib/workflows";
+import { bodyOf, cellOf, iterationOf } from "./loopBody";
+
+const node = (key: string, type: string) => ({ id: `id-${key}`, key, type, config: {} });
+const edge = (from: string, to: string, port?: string) => ({ from: { node: `id-${from}`, ...(port ? { port } : {}) }, to: { node: `id-${to}` } });
+// each_ap loops over is_offline -> notify, and an inner loop over ping; report follows on done.
+const DOC = {
+  graph_format: 1,
+  nodes: [node("each_ap", "flow.loop@1"), node("is_offline", "flow.if@1"), node("notify", "slack.post@1"), node("inner", "flow.loop@1"), node("ping", "testkit.echo@1"), node("report", "flow.transform@1")],
+  edges: [edge("each_ap", "is_offline", "body"), edge("is_offline", "notify", "true"), edge("is_offline", "inner", "false"), edge("inner", "ping", "body"), edge("each_ap", "report", "done")],
+} as unknown as GraphDoc;  // prettier-ignore
+
+describe("a loop's iterations in the panel (§7.5; the ResultPanel board)", () => {
+  it("lists the steps each iteration runs, in the draft's order: not a nested loop's own, nor what follows the loop", () => {
+    expect(bodyOf(DOC, "id-each_ap").map((n) => n.key)).toEqual(["is_offline", "notify", "inner"]);
+    expect(bodyOf(DOC, "id-inner").map((n) => n.key)).toEqual(["ping"]);
+    expect(bodyOf(DOC, "id-report")).toEqual([]);
+  });
+
+  it("names an iteration as the engine keys it, under the loop's own", () => {
+    expect(iterationOf("", "each_ap", 0)).toBe("each_ap:0");
+    expect(iterationOf("outer:2", "each_ap", 3)).toBe("outer:2/each_ap:3");
+  });
+
+  it("words a step's instance in one iteration: the port it took, its status, a failure's code, a loop's count", () => {
+    expect(cellOf({ status: "succeeded", effect: { port: "false" } }, "flow.if@1")).toEqual({ text: "→ false", failed: false, code: null });
+    expect(cellOf({ status: "skipped", effect: null }, "slack.post@1")).toEqual({ text: "skipped", failed: false, code: null });
+    expect(cellOf({ status: "failed", error: { code: "invalid_blocks", message: "Block 2 has no text." } }, "slack.post@1")).toEqual({ text: "failed", failed: true, code: "invalid_blocks" });
+    expect(cellOf({ status: "succeeded", output: { items: [], failures: [], count: 3 } }, "flow.loop@1")).toEqual({ text: "3 iterations", failed: false, code: null });
+    expect(cellOf({ status: "not_started" }, "slack.post@1")).toEqual({ text: "not started", failed: false, code: null });
+    expect(cellOf(undefined, "slack.post@1")).toEqual({ text: "not recorded", failed: false, code: null });
+  });
+});
```

- [ ] **Step 2: Run them**

Run: `npx --offline pnpm@12.6.0 exec vitest run src/routes/editor/simulation/loopBody.test.ts
src/routes/editor/simulation/Iterations.test.tsx src/routes/editor/simulation/SimulationResult.test.tsx
src/routes/editor/Editor.test.tsx`

Expected: FAIL: `loopBody.test.ts`, `Iterations.test.tsx` and `SimulationResult.test.tsx` can't import their modules; 1
failed and 155 passed: the panel has no "Steps, in run order" region.

- [ ] **Step 3: Implement**

Apply:

```diff
diff --git a/frontend/src/routes/editor/Editor.tsx b/frontend/src/routes/editor/Editor.tsx
index 4e3d6151..d64f4367 100644
--- a/frontend/src/routes/editor/Editor.tsx
+++ b/frontend/src/routes/editor/Editor.tsx
@@ -3,7 +3,7 @@
 // adds problems, Task 15 publishing and versions.
 import { useQuery, useQueryClient } from "@tanstack/react-query";
 import { useBlocker, useMatch, useRouter } from "@tanstack/react-router";
-import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
+import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
 import { Button } from "../../components/Button";
 import { ConfirmDialog } from "../../components/ConfirmDialog";
 import { LoadError } from "../../components/LoadError";
@@ -21,7 +21,7 @@ import { begin, record, redo, undo, type History } from "../../lib/history";
 import { CARD, layout } from "../../lib/layout";
 import { guardLeaving } from "../../lib/leaving";
 import type { Path } from "../../lib/schemaForm";
-import { ENDED, freeze } from "../../lib/simulations";
+import { ENDED, freeze, type StepSummary } from "../../lib/simulations";
 import { useDocumentTitle } from "../../lib/title";
 import { schedulesQuery, startSummary, workflowBindingsQuery } from "../../lib/triggers";
 import {
@@ -47,6 +47,7 @@ import { SimulateDialog } from "./simulation/SimulateDialog";
 import { ResultBar } from "./simulation/ResultBar";
 import { tagsOf, type SimTag } from "./simulation/results";
 import { SimulationPanel } from "./simulation/SimulationPanel";
+import { SimulationResult } from "./simulation/SimulationResult";
 import { useSimulation } from "./simulation/useSimulation";
 import { type Problems } from "./StepCard";
 import { StepPicker, type PickMode } from "./StepPicker";
@@ -484,17 +485,18 @@ function Editor({
   const simulationId = simulation.state?.request.id ?? null;
   const [hiddenFor, setHiddenFor] = useState<string | null>(null);
   const resultShown = simulator && simulationId !== null && simulation.phase !== null && hiddenFor !== simulationId;
+  // An attempt is said "of" the step's own limit, else its type's.
+  const attemptsOf = useCallback(
+    (s: StepSummary) => findNode(doc, s.step_id)?.options?.max_attempts ?? typeMap.get(s.type)?.retry.max_attempts ?? null,
+    [doc, typeMap],
+  );
   const simulated = useMemo(() => {
     const tags = new Map<string, SimTag[]>();
     if (!resultShown) return tags;
     const ended = simulation.phase !== null && ENDED.has(simulation.phase);
-    for (const s of simulation.steps?.steps ?? []) {
-      const node = findNode(doc, s.step_id);
-      const maxAttempts = node?.options?.max_attempts ?? typeMap.get(s.type)?.retry.max_attempts ?? null;
-      tags.set(idKey(s.step_id), tagsOf(s, { maxAttempts, ended }));
-    }
+    for (const s of simulation.steps?.steps ?? []) tags.set(idKey(s.step_id), tagsOf(s, { maxAttempts: attemptsOf(s), ended }));
     return tags;
-  }, [resultShown, simulation.phase, simulation.steps, doc, typeMap]);
+  }, [resultShown, simulation.phase, simulation.steps, attemptsOf]);
   // When editing stops (a conflict, an exit, a publication), what only editing offers stops with it: an open dialog
   // closes, placing ends (a click on a read-only canvas places nothing) and says so. Focus held by what's gone (the
   // dialog, a "+", Auto layout, Add step, a panel's buttons) goes to what's drawn: a panel's heading when it was in
@@ -1472,7 +1474,12 @@ function Editor({
               setSide(null);
               land("simulate");
             }}
-          />
+          >
+            <SimulationResult
+              tenantId={tenantId} workflowId={workflow.id} session={simulation} doc={doc} attemptsOf={attemptsOf}
+              onGoTo={(id) => focus(item.node(id))}
+            />
+          </SimulationPanel>
         )}
         {side?.kind === "problems" && (
           <ProblemsPanel
diff --git a/frontend/src/routes/editor/simulation/Iterations.tsx b/frontend/src/routes/editor/simulation/Iterations.tsx
new file mode 100644
index 00000000..77ef6cc8
--- /dev/null
+++ b/frontend/src/routes/editor/simulation/Iterations.tsx
@@ -0,0 +1,83 @@
+// SPDX-License-Identifier: Apache-2.0
+// A loop's iterations in the Simulation panel, four at a time (4d-1c; the simulation design §7.5; the ResultPanel
+// board): each row, what the loop's own steps did in that iteration, read a page at a time from the server's
+// instances (decision 5), never the whole run at once. A failed step opens its instance in that iteration.
+import { useQueries } from "@tanstack/react-query";
+import { Fragment, useState } from "react";
+import { Button } from "../../../components/Button";
+import { stepInstancesQuery } from "../../../lib/simulations";
+import { PAGE, cellOf, iterationOf } from "./loopBody";
+
+export interface BodyStep {
+  id: string;
+  key: string;
+  type: string;
+}
+
+const keyed = (item: unknown): unknown => (typeof item === "object" && item !== null ? (item as Record<string, unknown>).iteration_key : undefined);
+
+export function Iterations({ tenantId, workflowId, requestId, loop, body, onOpen }: {
+  tenantId: string; workflowId: string; requestId: string; loop: { key: string; prefix: string }; body: BodyStep[];
+  onOpen?: (stepId: string, iterationKey: string) => void;
+}) {  // prettier-ignore
+  const [offset, setOffset] = useState(0);
+  const pages = useQueries({
+    queries: body.map((b) => stepInstancesQuery(tenantId, workflowId, requestId, b.id, { offset, limit: PAGE, within: loop.prefix || undefined })),
+  });
+  if (pages.some((p) => p.isError)) {
+    return (
+      <p className="flex flex-wrap items-center gap-2 text-small">
+        The iterations couldn&apos;t be read.
+        <Button size="sm" onClick={() => pages.forEach((p) => p.isError && void p.refetch())}>Read them again</Button>
+      </p>
+    );
+  }
+  const read = pages.map((p) => p.data);
+  if (read.some((d) => d === undefined)) return <p className="text-small text-muted">Reading the iterations…</p>;
+  const total = Math.max(0, ...read.map((d) => d!.total));
+  if (total === 0) return <p className="text-small text-muted">No iteration was opened.</p>;
+  const shown = Math.max(0, Math.min(PAGE, total - offset));
+  const rest = total - offset - shown;
+  const span = `${offset + 1} to ${offset + shown} of ${total}`;
+  return (
+    <div className="flex flex-col gap-1.5">
+      <ol aria-label={`${loop.key}'s iterations, ${span}`} className="flex flex-col text-small">
+        {Array.from({ length: shown }, (_, i) => offset + i).map((n) => {
+          const at = iterationOf(loop.prefix, loop.key, n);
+          return (
+            <li key={n} className="border-t border-line py-1.5 first:border-t-0">
+              {n + 1}
+              {body.map((b, j) => {
+                const c = cellOf(read[j]!.items.find((item) => keyed(item) === at), b.type);
+                return (
+                  <Fragment key={b.id}>
+                    {" · "}
+                    <span className="font-mono">{b.key}</span>{" "}
+                    <span className={c.failed ? "text-danger" : "text-muted"}>{c.text}</span>
+                    {c.code && (
+                      <>
+                        {" · "}
+                        <span className="font-mono text-meta">{c.code}</span>
+                      </>
+                    )}
+                    {c.failed && onOpen && (
+                      <>
+                        {" "}
+                        <Button size="sm" aria-label={`Open ${b.key}, iteration ${n + 1}`} onClick={() => onOpen(b.id, at)}>Open</Button>
+                      </>
+                    )}
+                  </Fragment>
+                );
+              })}
+            </li>
+          );
+        })}
+      </ol>
+      <p className="flex flex-wrap items-center gap-2 text-small text-muted">
+        <span className="grow">{`Iterations ${offset + 1}–${offset + shown} of ${total}`}</span>
+        {offset > 0 && <Button size="sm" onClick={() => setOffset(Math.max(0, offset - PAGE))}>{`Previous ${PAGE}`}</Button>}
+        {rest > 0 && <Button size="sm" onClick={() => setOffset(offset + PAGE)}>{`Next ${Math.min(PAGE, rest)}`}</Button>}
+      </p>
+    </div>
+  );
+}
diff --git a/frontend/src/routes/editor/simulation/SimTags.tsx b/frontend/src/routes/editor/simulation/SimTags.tsx
index f5b653d0..a47b05c1 100644
--- a/frontend/src/routes/editor/simulation/SimTags.tsx
+++ b/frontend/src/routes/editor/simulation/SimTags.tsx
@@ -29,3 +29,10 @@ export function SimTags({ label, tags }: { label: string; tags: SimTag[] }) {
     </ul>
   );
 }
+
+/** The same tags in a line of text: the Simulation panel's steps (§7.5). */
+export function InlineTags({ tags }: { tags: SimTag[] }) {
+  return tags.map((t, i) => (
+    <span key={i} className={`text-meta leading-[18px] whitespace-nowrap ${LOOK[t.kind]}`}>{t.text}</span>
+  ));
+}
diff --git a/frontend/src/routes/editor/simulation/SimulationResult.tsx b/frontend/src/routes/editor/simulation/SimulationResult.tsx
new file mode 100644
index 00000000..9c1507aa
--- /dev/null
+++ b/frontend/src/routes/editor/simulation/SimulationResult.tsx
@@ -0,0 +1,134 @@
+// SPDX-License-Identifier: Apache-2.0
+// A simulation's result in the Simulation panel (4d-1c; the simulation design §7.5; the ResultPanel and Running
+// boards), below its lifecycle: what a simulation proves (the banner), the checks the server found when it admitted
+// it, the steps in run order with the canvas's tags and Go to, a loop's iterations paged, and the input used, as the
+// request stored it (§6.6's read-back: never recomputed from today's draft).
+import { useId, useState, type ReactNode } from "react";
+import { Button } from "../../../components/Button";
+import { findNode } from "../../../lib/graph";
+import { ENDED, type StepSummary } from "../../../lib/simulations";
+import type { GraphDoc } from "../../../lib/workflows";
+import { bodyOf } from "./loopBody";
+import { Iterations } from "./Iterations";
+import { tagsOf } from "./results";
+import { SimBanner } from "./SimBanner";
+import { InlineTags } from "./SimTags";
+import type { SimulationSession } from "./useSimulation";
+
+const REDACTED = "[redacted]"; // the server's marker for a sensitive value (engine/runtime/projection.py)
+
+function Section({ title, children }: { title: string; children: ReactNode }) {
+  const id = useId();
+  return (
+    <section aria-labelledby={id} className="flex flex-col gap-1.5">
+      <h3 id={id} className="text-small font-semibold">{title}</h3>
+      {children}
+    </section>
+  );
+}
+
+const shown = (v: unknown): string => (v === REDACTED ? "redacted" : typeof v === "string" ? v : JSON.stringify(v));
+const iterationKey = (final: StepSummary["final"]): string => {
+  const key = final?.iteration_key;
+  return typeof key === "string" ? key : "";
+};
+
+export function SimulationResult({ tenantId, workflowId, session, doc, attemptsOf, onGoTo, onOpen }: {
+  tenantId: string; workflowId: string; session: SimulationSession; doc: GraphDoc;
+  attemptsOf: (s: StepSummary) => number | null; onGoTo: (stepId: string) => void;
+  onOpen?: (stepId: string, iterationKey: string) => void;
+}) {  // prettier-ignore
+  const [open, setOpen] = useState<string | null>(null); // the loop whose iterations are shown
+  const { state, phase } = session;
+  if (!state || !phase) return null;
+  const ended = ENDED.has(phase);
+  const ran = phase !== "refused" && phase !== "dead";
+  const request = state.request;
+  const all = session.steps?.steps ?? [];
+  const steps = ended ? all : all.filter((s) => s.instances > 0);
+  const goTo = (id: string, key: string) =>
+    findNode(doc, id) ? <Button size="sm" aria-label={`Go to ${key}`} onClick={() => onGoTo(id)}>Go to</Button> : null;
+
+  return (
+    <>
+      {ended && ran && (
+        <SimBanner>
+          <p><strong>Simulated.</strong> Nothing was sent. Results don&apos;t prove the live call will succeed.</p>
+          {all.some((s) => s.origin === "evaluated_not_waited") && (
+            <p>Flow delays and wait-until weren&apos;t waited; the simulation clock wasn&apos;t advanced.</p>
+          )}
+        </SimBanner>
+      )}
+      {request.admission_checks.length > 0 && (
+        <Section title="Checks on the server">
+          <p className="text-small text-muted">Found when the simulation was admitted. They didn&apos;t stop it; a live run would meet them.</p>
+          <ul className="flex flex-col text-small">
+            {request.admission_checks.map((d, i) => {
+              const key = d.node ? findNode(doc, d.node)?.key : undefined;
+              return (
+                <li key={i} className="flex flex-wrap items-center gap-2 border-t border-line py-1.5 first:border-t-0">
+                  <span className="grow">{d.message}</span>
+                  {d.fix && <span className="basis-full text-muted">{d.fix}</span>}
+                  {d.node && key !== undefined && goTo(d.node, key)}
+                </li>
+              );
+            })}
+          </ul>
+        </Section>
+      )}
+      {ran && steps.length > 0 && (
+        <Section title={ended ? "Steps, in run order" : "Steps so far"}>
+          <ul className="flex flex-col text-small">
+            {steps.map((s) => {
+              const loop = s.type.startsWith("flow.loop@") && s.instances === 1 && findNode(doc, s.step_id) !== undefined;
+              const body = loop && ended ? bodyOf(doc, s.step_id) : [];
+              const expanded = open === s.step_id && body.length > 0;
+              return (
+                <li key={s.step_id} className="flex flex-wrap items-center gap-1.5 border-t border-line py-1.5 first:border-t-0">
+                  <span data-key className="font-mono">{s.key}</span>
+                  <InlineTags tags={tagsOf(s, { maxAttempts: attemptsOf(s), ended })} />
+                  <span className="grow" />
+                  {body.length > 0 && (
+                    <Button size="sm" aria-label={`Iterations of ${s.key}`} aria-expanded={expanded} onClick={() => setOpen(expanded ? null : s.step_id)}>
+                      Iterations
+                    </Button>
+                  )}
+                  {goTo(s.step_id, s.key)}
+                  {expanded && (
+                    <div className="basis-full ps-3">
+                      <Iterations
+                        tenantId={tenantId} workflowId={workflowId} requestId={request.id} loop={{ key: s.key, prefix: iterationKey(s.final) }}
+                        body={body.map((n) => ({ id: n.id, key: n.key, type: n.type }))} onOpen={onOpen}
+                      />
+                    </div>
+                  )}
+                </li>
+              );
+            })}
+          </ul>
+        </Section>
+      )}
+      {request.target_step_id === null && (
+        <Section title="Input used">
+          {state.read_back === "absent" ? (
+            <p className="text-small text-muted">The input used isn&apos;t kept any more.</p>
+          ) : state.read_back === "unreadable" ? (
+            <p className="text-small text-muted">The input used couldn&apos;t be read back.</p>
+          ) : (
+            <>
+              <p className="text-small text-muted">As this simulation&apos;s request stored it, sensitive values redacted.</p>
+              <dl className="grid grid-cols-[max-content_1fr] gap-x-3 gap-y-1 text-small">
+                {Object.entries(state.input ?? {}).map(([k, v]) => (
+                  <div key={k} className="contents">
+                    <dt className="font-mono text-muted">{k}</dt>
+                    <dd className="break-words">{shown(v)}</dd>
+                  </div>
+                ))}
+              </dl>
+            </>
+          )}
+        </Section>
+      )}
+    </>
+  );
+}
diff --git a/frontend/src/routes/editor/simulation/loopBody.ts b/frontend/src/routes/editor/simulation/loopBody.ts
new file mode 100644
index 00000000..59f0e8f5
--- /dev/null
+++ b/frontend/src/routes/editor/simulation/loopBody.ts
@@ -0,0 +1,53 @@
+// SPDX-License-Identifier: Apache-2.0
+// A loop's iterations in the Simulation panel (4d-1c; the simulation design §7.5; the ResultPanel board): which steps
+// an iteration runs, how the engine keys an iteration, and what a step did in one, in words. Every opened iteration
+// holds exactly one instance of each step directly in its body, skipped ones included (B4b), so a page of each step's
+// instances is a page of iterations.
+import { edgesOf, idKey, nodesOf, portOf, sameId } from "../../../lib/graph";
+import type { GraphDoc, GraphNode } from "../../../lib/workflows";
+
+const LOOP = "flow.loop@";
+export const PAGE = 4;
+
+/** Every step reachable from a loop's `body` port, as the engine reads a loop's region (engine/graph/structure.py). */
+function regionOf(doc: GraphDoc, loopId: string): Set<string> {
+  const edges = edgesOf(doc);
+  const region = new Set<string>();
+  const queue = edges.filter((e) => sameId(e.from.node, loopId) && portOf(e) === "body").map((e) => idKey(e.to.node));
+  for (let next = queue.shift(); next !== undefined; next = queue.shift()) {
+    if (region.has(next)) continue;
+    region.add(next);
+    queue.push(...edges.filter((e) => idKey(e.from.node) === next).map((e) => idKey(e.to.node)));
+  }
+  return region;
+}
+
+/** The steps a loop's iteration runs itself, in the draft's order: not those of a loop nested in it, which run in
+ * that loop's own iterations. */
+export function bodyOf(doc: GraphDoc, loopId: string): GraphNode[] {
+  const region = regionOf(doc, loopId);
+  const nested = new Set<string>();
+  for (const n of nodesOf(doc)) {
+    if (n.type.startsWith(LOOP) && region.has(idKey(n.id))) for (const id of regionOf(doc, n.id)) nested.add(id);
+  }
+  return nodesOf(doc).filter((n) => region.has(idKey(n.id)) && !nested.has(idKey(n.id)));
+}
+
+/** An iteration's key as the engine writes it: `loop:index`, under the iterations it's nested in. */
+export const iterationOf = (prefix: string, loopKey: string, index: number): string => `${prefix ? `${prefix}/` : ""}${loopKey}:${index}`;
+
+const field = (v: unknown, key: string): unknown => (typeof v === "object" && v !== null && !Array.isArray(v) ? (v as Record<string, unknown>)[key] : undefined);
+
+/** What a step did in one iteration: the port it took, else a nested loop's count, else its status; a failure's code. */
+export function cellOf(item: unknown, type: string): { text: string; failed: boolean; code: string | null } {
+  if (item === undefined) return { text: "not recorded", failed: false, code: null };
+  const status = typeof field(item, "status") === "string" ? (field(item, "status") as string) : "not recorded";
+  const port = field(field(item, "effect"), "port");
+  const count = field(field(item, "output"), "count");
+  const code = field(field(item, "error"), "code");
+  const text =
+    status === "succeeded" && typeof port === "string" ? `→ ${port}`
+    : status === "succeeded" && type.startsWith(LOOP) && typeof count === "number" ? `${count} ${count === 1 ? "iteration" : "iterations"}`
+    : status.replace("_", " ");  // prettier-ignore
+  return { text, failed: status === "failed", code: typeof code === "string" ? code : null };
+}
```

- [ ] **Step 4: Run them again**

Run: the same command.

Expected: PASS, 171 passed.

- [ ] **Step 5: Static checks**

Run: the two of "How to run things". Expected: no output.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/routes/editor
git commit -m "feat(editor): the panel's result: the server's checks, the steps in run order, a loop's iterations, the input used (4d-1c)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Before your edits, and refusals

**Spec:** §7.7 (stale and refusals), §7.2 (outcome unknown); the Stale and Refusals boards.

**Files:**
- Create: `frontend/src/routes/editor/simulation/stale.ts`, `frontend/src/routes/editor/simulation/stale.test.ts`
- Create: `frontend/src/routes/editor/simulation/Refusal.tsx`, `frontend/src/routes/editor/simulation/Refusal.test.tsx`
- Modify: `frontend/src/lib/simulations.ts` (`DraftSnapshot`, `draftSnapshotQuery`)
- Modify: `frontend/src/routes/editor/simulation/useSimulation.ts`, `ResultBar.tsx`, `SimulationResult.tsx` and their
  tests
- Modify: `frontend/src/routes/editor/Editor.tsx`, `frontend/src/routes/editor/Editor.test.tsx`

**Interfaces:**
- Consumes: `ApiError` (`lib/client.ts`); `DraftSync.conflict()`; `SimulationResult` and `ResultBar` (Tasks 6, 7).
- Produces:
  - `draftSnapshotQuery(t, w, snapshotId)` (`staleTime: Infinity`), `type DraftSnapshot`.
  - `stale.ts`: `type Stale` (`{ kind: "revision"; from; to }` or `{ kind: "local" }`), `interface Changes { changed;
    added; gone }` (sets of `idKey`s), `STALE` (the warning's classes), `staleOf(revision, sync)`, `staleWords(stale,
    panel)`, `changesOf(ran, doc)`.
  - `Refusal({ error, doc, onGoTo, onShowProblems, onTryAgain })`.
  - `ResultBar` gains `stale`; `SimulationResult` gains `ran`, `stale`, `changes`, `onShowProblems`.
  - `useSimulation`: a coded 503 is `refused`; `checkAgain()` sends the frozen request again after `unknown` or
    `refused`.

A result is "Before your edits" once it ended, when the server's draft moved on or an edit here isn't saved (rulings 5
to 7): the bar and the panel say so; the draft it ran is read once, and each step changed since says so on the canvas
and in the panel, a step new since reads "new since revision N: no result", a step gone reads "no longer in the
draft", with no Go to. A failed step says its code and message, its attempts, and that nothing was sent. A refused
simulation is shown in the panel in the server's words: a draft's problems ("Fix N problems first", each with Go to,
and "Show the problems"), a declassifying draft without the permission, the deployment's gate, a retired type (Go to
each step of it), no current build ("Try again"), a step test's values by their pointer, the draft changed elsewhere,
which also turns the editor read only (ruling 10). A coded 503 is a refusal, never a lost answer (ruling 9).

- [ ] **Step 1: Write the failing tests**

Apply:

```diff
diff --git a/frontend/src/routes/editor/Editor.test.tsx b/frontend/src/routes/editor/Editor.test.tsx
index c722c081..76b2b344 100644
--- a/frontend/src/routes/editor/Editor.test.tsx
+++ b/frontend/src/routes/editor/Editor.test.tsx
@@ -2216,7 +2216,7 @@ describe("Simulate workflow", () => {
       steps: [{ step_id: "id-transform", key: "transform", type: "flow.transform@1", origin: "evaluated", instances: 1, statuses: { succeeded: 1 }, ports: {}, final: { attempt: 1, status: "succeeded" } }],
     };  // prettier-ignore
     const ended = { ...simState("started"), run: { status: "succeeded", queued_at: null, started_at: "2026-10-15T10:42:05Z", ended_at: "2026-10-15T10:42:19Z", error: null, iterations: 0 } };
-    answers.set(`GET ${BASE}`, () => json({ ...WORKFLOW, draft: draftWith("transform") }));
+    answers.set(`GET ${BASE}`, () => json({ ...WORKFLOW, draft_revision: 2, draft: draftWith("transform") }));
     answers.set(`GET ${SIM}`, () => json([simRequest("started")])); // a reload finds the latest
     answers.set(`GET ${SIM}/r1`, () => json(ended));
     answers.set(`GET ${SIM}/r1/steps`, () => json(summary));
@@ -2237,7 +2237,7 @@ describe("Simulate workflow", () => {
       steps: [{ step_id: "id-transform", key: "transform", type: "flow.transform@1", origin: "evaluated", instances: 1, statuses: { succeeded: 1 }, ports: {}, final: { attempt: 1, status: "succeeded" } }],
     };  // prettier-ignore
     const ended = { ...simState("started"), run: { status: "succeeded", queued_at: null, started_at: "2026-10-15T10:42:05Z", ended_at: "2026-10-15T10:42:19Z", error: null, iterations: 0 } };
-    answers.set(`GET ${BASE}`, () => json({ ...WORKFLOW, draft: draftWith("transform") }));
+    answers.set(`GET ${BASE}`, () => json({ ...WORKFLOW, draft_revision: 2, draft: draftWith("transform") }));
     answers.set(`GET ${SIM}`, () => json([simRequest("started")]));
     answers.set(`GET ${SIM}/r1`, () => json(ended));
     answers.set(`GET ${SIM}/r1/steps`, () => json(summary));
@@ -2251,6 +2251,62 @@ describe("Simulate workflow", () => {
     await vi.waitFor(() => expect(document.activeElement?.getAttribute("data-item")).toBe("node:id-transform"));
   });
 
+  it("marks a result from before the person's edits, on the canvas and in the panel (§7.7; the Stale board)", async () => {
+    const step = (key: string) => ({ step_id: `id-${key}`, key, type: "flow.transform@1", origin: "evaluated", instances: 1, statuses: { succeeded: 1 }, ports: {}, final: { attempt: 1, status: "succeeded" } });
+    const options = { timeout_s: null, max_attempts: null, on_error: "fail" };
+    const snapshot = {
+      id: "s1", workflow_id: "w1", draft_revision: 2, created_at: "", graph_hash: "g", version_hash: "v", cel_profile: "p", engine_abi: 9, node_refs: [], expressions: [],
+      graph: { graph_format: 1, edges: [], nodes: [
+        { id: "id-transform", key: "transform", type: "flow.transform@1", config: { note: { kind: "literal", value: "old" } }, position: { x: 0, y: 140 }, options },
+        { id: "id-kept", key: "kept", type: "flow.transform@1", config: {}, position: { x: 0, y: 280 }, options },
+        { id: "id-old", key: "old", type: "flow.transform@1", config: {}, position: { x: 0, y: 420 }, options },
+      ] },
+    };  // prettier-ignore
+    const ended = { ...simState("started"), run: { status: "succeeded", queued_at: null, started_at: "2026-10-15T10:42:05Z", ended_at: "2026-10-15T10:42:19Z", error: null, iterations: 0 } };
+    answers.set(`GET ${BASE}`, () => json({ ...WORKFLOW, draft_revision: 3, draft: draftWith("transform", "kept", "added") }));
+    answers.set(`GET ${SIM}`, () => json([simRequest("started")]));
+    answers.set(`GET ${SIM}/r1`, () => json(ended));
+    answers.set(`GET ${SIM}/r1/steps`, () => json({ given: "input", steps: [step("transform"), step("kept"), step("old")] }));
+    answers.set(`GET ${BASE}/draft/snapshots/s1`, () => json(snapshot));
+    await show();
+    await vi.waitFor(() =>
+      expect(steps().dataset.simulated).toBe(JSON.stringify([
+        ["id-transform", ["succeeded", "evaluated", "changed since"]], ["id-kept", ["succeeded", "evaluated"]], ["id-added", ["new since revision 2: no result"]],
+      ])),
+    );  // prettier-ignore
+    expect(screen.getByText("Before your edits:").parentElement?.textContent).toBe("Before your edits: this result is for revision 2; the draft is at revision 3.");
+    await userEvent.click(screen.getByRole("button", { name: "Simulation" }));
+    const panel = await screen.findByRole("complementary", { name: "Simulation" });
+    expect(within(panel).getByText("no longer in the draft")).toBeTruthy();
+    expect(panel.textContent).toContain("Simulate again to see the draft as it is.");
+  });
+
+  it("stops when the draft was changed elsewhere, and says so (§7.7)", async () => {
+    answers.set(`POST ${SIM}`, () => json({ error: "draft_conflict", draft_revision: 7 }, 409));
+    await show();
+    await userEvent.click(await screen.findByRole("button", { name: "◌ Simulate workflow" }));
+    const dialog = await screen.findByRole("dialog", { name: "Simulate workflow" });
+    await userEvent.click(await within(dialog).findByRole("button", { name: "◌ Simulate" }));
+    const panel = await screen.findByRole("complementary", { name: "Simulation" });
+    expect(await within(panel).findByText("The draft was changed elsewhere, so it wasn't simulated.")).toBeTruthy();
+    expect((await screen.findByRole("alert")).textContent).toContain("changed elsewhere");
+  });
+
+  it("shows a refusal's problems, and the Problems panel from it (§7.7; the Refusals board)", async () => {
+    const problem = { code: "ref.unknown", message: "A reference to get_sit, which isn't a step.", node: "id-transform", field: null, fix: null, severity: "error" };
+    answers.set(`GET ${BASE}`, () => json({ ...WORKFLOW, draft: draftWith("transform") }));
+    answers.set(`POST ${SIM}`, () => json({ error: "invalid", diagnostics: [problem] }, 422));
+    await show();
+    await userEvent.click(await screen.findByRole("button", { name: "◌ Simulate workflow" }));
+    const dialog = await screen.findByRole("dialog", { name: "Simulate workflow" });
+    await userEvent.click(await within(dialog).findByRole("button", { name: "◌ Simulate" }));
+    const panel = await screen.findByRole("complementary", { name: "Simulation" });
+    expect(await within(panel).findByText("Fix 1 problem first: a draft with problems isn't simulated.")).toBeTruthy();
+    expect(screen.getByRole("button", { name: "◌ Simulate workflow" }).hasAttribute("disabled")).toBe(false); // nothing runs
+    await userEvent.click(within(panel).getByRole("button", { name: "Show the problems" }));
+    expect(await screen.findByRole("complementary", { name: "Problems" })).toBeTruthy();
+  });
+
   it("asks Publish's own question about edits not applied, worded for simulating", async () => {
     await unappliedDuration();
     await userEvent.click(screen.getByRole("button", { name: "◌ Simulate workflow" }));
diff --git a/frontend/src/routes/editor/simulation/Refusal.test.tsx b/frontend/src/routes/editor/simulation/Refusal.test.tsx
new file mode 100644
index 00000000..1f9cfc4d
--- /dev/null
+++ b/frontend/src/routes/editor/simulation/Refusal.test.tsx
@@ -0,0 +1,84 @@
+// SPDX-License-Identifier: Apache-2.0
+import { render, screen, within } from "@testing-library/react";
+import userEvent from "@testing-library/user-event";
+import { describe, expect, it, vi } from "vitest";
+import { ApiError } from "../../../lib/client";
+import type { GraphDoc } from "../../../lib/workflows";
+import { Refusal } from "./Refusal";
+
+const node = (key: string, type: string) => ({ id: `id-${key}`, key, type, config: {} });
+const DOC = { graph_format: 1, nodes: [node("get_site", "mist.legacy.sites@1"), node("notify", "slack.post@1"), node("has_aps", "flow.if@1")], edges: [] } as unknown as GraphDoc;
+const diagnostic = (node: string | null, message: string, code = "ref.unknown", severity: "error" | "warning" = "error") => ({ code, message, node, field: null, fix: null, severity });
+
+function show(status: number, body: Record<string, unknown>) {
+  const handlers = { onGoTo: vi.fn(), onShowProblems: vi.fn(), onTryAgain: vi.fn() };
+  render(<Refusal error={new ApiError(status, body.error as string, body)} doc={DOC} {...handlers} />);
+  return handlers;
+}
+
+describe("a refused simulation, in the server's words (§7.7; the Refusals board)", () => {
+  it("asks for a draft's problems to be fixed first, each with Go to, and shows them", async () => {
+    const h = show(422, { error: "invalid", diagnostics: [
+      diagnostic("id-notify", "A reference to get_sit, which isn't a step."),
+      diagnostic("id-has_aps", "The condition reads sensitive data that isn't declassified.", "taint.undeclassified"),
+      diagnostic(null, "Nothing follows the loop.", "graph.unused", "warning"),
+    ] });  // prettier-ignore
+    expect(screen.getByText("Not simulated")).toBeTruthy();
+    expect(screen.getByText("Fix 2 problems first: a draft with problems isn't simulated.")).toBeTruthy();
+    const items = within(screen.getByRole("list", { name: "Problems" })).getAllByRole("listitem");
+    expect(items).toHaveLength(2); // its errors; a warning never refuses
+    expect(within(items[0]!).getByText("A reference to get_sit, which isn't a step.")).toBeTruthy();
+    await userEvent.click(within(items[0]!).getByRole("button", { name: "Go to notify" }));
+    expect(h.onGoTo).toHaveBeenCalledWith("id-notify");
+    await userEvent.click(screen.getByRole("button", { name: "Show the problems" }));
+    expect(h.onShowProblems).toHaveBeenCalled();
+  });
+
+  it("says one problem in the singular", () => {
+    show(422, { error: "invalid", diagnostics: [diagnostic("id-notify", "A reference to get_sit, which isn't a step.")] });
+    expect(screen.getByText("Fix 1 problem first: a draft with problems isn't simulated.")).toBeTruthy();
+  });
+
+  it("says a declassifying draft needs the permission, in the server's words alone", () => {
+    const words = "Simulating a draft that declassifies sensitive data needs the workflow.declassify permission (tenant admins and owners).";
+    show(422, { error: "invalid", diagnostics: [diagnostic(null, words, "declassify.forbidden")] });
+    expect(screen.getByText(words)).toBeTruthy();
+    expect(screen.queryByText(/^Fix /)).toBeNull();
+    expect(screen.queryByRole("button", { name: "Show the problems" })).toBeNull();
+  });
+
+  it("says why the deployment refused it", () => {
+    const words = "Production runs are off in this deployment: no run starts in a production deployment until its gate lifts (engine 2b spec §2).";
+    show(503, { error: "production_runs_disabled", messages: [words] });
+    expect(screen.getByText(words)).toBeTruthy();
+    expect(screen.queryByRole("button", { name: "Try again" })).toBeNull();
+  });
+
+  it("goes to each step of a retired type", async () => {
+    const h = show(409, { error: "node_type_retired", messages: ["mist.legacy.sites@1 has been retired."] });
+    expect(screen.getByText("mist.legacy.sites@1 has been retired.")).toBeTruthy();
+    await userEvent.click(screen.getByRole("button", { name: "Go to get_site" }));
+    expect(h.onGoTo).toHaveBeenCalledWith("id-get_site");
+  });
+
+  it("tries again when no current build was recorded", async () => {
+    const h = show(503, { error: "no_current_build", messages: ["No current build has been recorded lately, so this run's engine ABI can't be checked: the dispatcher records it while it runs."] });
+    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
+    expect(h.onTryAgain).toHaveBeenCalled();
+  });
+
+  it("lists a step test's refused values by their pointer", () => {
+    show(422, { error: "seed_missing", problems: [{ code: "seed_missing", pointer: "/steps/get_site/output/name", message: "A value is required here." }] });
+    expect(screen.getByText("/steps/get_site/output/name: A value is required here.")).toBeTruthy();
+  });
+
+  it("says when the draft was changed elsewhere", () => {
+    show(409, { error: "draft_conflict", draft_revision: 17 });
+    expect(screen.getByText("The draft was changed elsewhere, so it wasn't simulated.")).toBeTruthy();
+  });
+
+  it("names a refusal it has no words for by the server's code", () => {
+    show(403, { error: "forbidden" });
+    expect(screen.getByText("The server refused it: forbidden.")).toBeTruthy();
+  });
+});
diff --git a/frontend/src/routes/editor/simulation/ResultBar.test.tsx b/frontend/src/routes/editor/simulation/ResultBar.test.tsx
index 543c5923..cb39389a 100644
--- a/frontend/src/routes/editor/simulation/ResultBar.test.tsx
+++ b/frontend/src/routes/editor/simulation/ResultBar.test.tsx
@@ -5,7 +5,7 @@ import { describe, expect, it, vi } from "vitest";
 import { ResultBar } from "./ResultBar";
 
 const props = (over: Partial<Parameters<typeof ResultBar>[0]> = {}) => ({
-  phase: "succeeded" as const, revision: 14, endedAt: "2026-10-15T10:42:19Z", notWaited: false, hidden: false,
+  phase: "succeeded" as const, revision: 14, endedAt: "2026-10-15T10:42:19Z", notWaited: false, hidden: false, stale: null,
   onHide: vi.fn(), onShow: vi.fn(), onPanel: vi.fn(), onCancel: vi.fn(), ...over,
 });  // prettier-ignore
 
@@ -30,6 +30,13 @@ describe("the canvas's bar for a simulation (§7.3; the ResultCanvas and Running
     expect(p.onHide).toHaveBeenCalled();
   });
 
+  it("says a result is from before the person's edits (§7.7; the Stale board)", () => {
+    render(<ResultBar {...props({ stale: { kind: "revision", from: 14, to: 16 } })} />);
+    const note = screen.getByText("Before your edits:").parentElement!;
+    expect(note.textContent).toBe("Before your edits: this result is for revision 14; the draft is at revision 16.");
+    expect(note.className).toMatch(/border-warn-line/);
+  });
+
   it("once hidden, is one bar that brings the result back", async () => {
     const p = props({ hidden: true });
     render(<ResultBar {...p} />);
diff --git a/frontend/src/routes/editor/simulation/SimulationResult.test.tsx b/frontend/src/routes/editor/simulation/SimulationResult.test.tsx
index 2add9063..8bc14448 100644
--- a/frontend/src/routes/editor/simulation/SimulationResult.test.tsx
+++ b/frontend/src/routes/editor/simulation/SimulationResult.test.tsx
@@ -3,6 +3,7 @@ import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
 import { render, screen, within } from "@testing-library/react";
 import userEvent from "@testing-library/user-event";
 import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
+import { ApiError } from "../../../lib/client";
 import type { SimulationRequest, SimulationState, StepSummary } from "../../../lib/simulations";
 import type { GraphDoc } from "../../../lib/workflows";
 import { SimulationResult } from "./SimulationResult";
@@ -53,14 +54,17 @@ beforeEach(() => {
 });
 afterEach(() => vi.restoreAllMocks());
 
-function show(s: SimulationSession) {
+function show(s: SimulationSession, over: Partial<Parameters<typeof SimulationResult>[0]> = {}) {
   const onGoTo = vi.fn();
   const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
   render(
     <QueryClientProvider client={qc}>
-      <SimulationResult tenantId="t1" workflowId="w1" session={s} doc={DOC} attemptsOf={() => 3} onGoTo={onGoTo} />
+      <SimulationResult
+        tenantId="t1" workflowId="w1" session={s} doc={DOC} ran={null} stale={null} changes={null} attemptsOf={() => 3} onGoTo={onGoTo}
+        onShowProblems={vi.fn()} {...over}
+      />
     </QueryClientProvider>,
-  );
+  );  // prettier-ignore
   return { onGoTo };
 }
 const section = (name: string) => screen.getByRole("region", { name });
@@ -131,3 +135,40 @@ describe("the Simulation panel's result (§7.5; the ResultPanel board)", () => {
     expect(within(section("Input used")).getByText("The input used couldn't be read back.")).toBeTruthy();
   });
 });
+
+describe("a result before the person's edits, and what failed (§7.7; the Stale and Refusals boards)", () => {
+  it("says it's for an older revision, and marks each step changed since, or no longer in the draft", () => {
+    show(session(), { stale: { kind: "revision", from: 14, to: 16 }, changes: { changed: new Set(["id-notify"]), added: new Set(), gone: new Set(["id-gone"]) } });
+    expect(screen.getByText("Before your edits:").parentElement?.textContent).toBe(
+      "Before your edits: this result is for revision 14; the draft is at revision 16. Simulate again to see the draft as it is.",
+    );
+    const rows = within(section("Steps, in run order")).getAllByRole("listitem");
+    expect(within(rows[2]!).getByText("changed since")).toBeTruthy();
+    expect(within(rows[2]!).getByRole("button", { name: "Go to notify" })).toBeTruthy();
+    expect(within(rows[4]!).getByText("no longer in the draft")).toBeTruthy();
+  });
+
+  it("says a failed step's code and message, its attempts, and that nothing was sent", () => {
+    const failed = (key: string, attempt: number, code: string, message: string) =>
+      step(key, { statuses: { failed: 1 }, final: { attempt, status: "failed", error: { code, message } } });
+    show(session({ phase: "failed", steps: [failed("post_ticket", 1, "simulation_unavailable", "http.request@1 can't be simulated."), failed("notify", 3, "invalid_blocks", "Block 2 has no text.")] }));
+    expect(screen.getByText("simulation_unavailable").parentElement?.textContent).toBe("simulation_unavailable http.request@1 can't be simulated. 1 attempt. Nothing was sent.");
+    expect(screen.getByText("invalid_blocks").parentElement?.textContent).toBe("invalid_blocks Block 2 has no text. 3 attempts, the configured retries. Nothing was sent.");
+  });
+
+  it("shows a refusal in the server's words", () => {
+    const s = session();
+    s.local = { kind: "refused", frozen: { key: "k1", revision: 14, body: { input: {} } }, error: new ApiError(503, "production_runs_disabled", { error: "production_runs_disabled", messages: ["Production runs are off in this deployment."] }) };
+    s.state = null;
+    s.phase = null;
+    show(s);
+    expect(screen.getByText("Not simulated")).toBeTruthy();
+    expect(screen.getByText("Production runs are off in this deployment.")).toBeTruthy();
+  });
+
+  it("pages a loop's iterations over the draft it ran, whatever the draft is now", async () => {
+    show(session(), { doc: { ...DOC, edges: [] }, ran: DOC });
+    await userEvent.click(screen.getByRole("button", { name: "Iterations of each_ap" }));
+    expect(await screen.findByRole("list", { name: "each_ap's iterations, 1 to 2 of 2" })).toBeTruthy();
+  });
+});
diff --git a/frontend/src/routes/editor/simulation/stale.test.ts b/frontend/src/routes/editor/simulation/stale.test.ts
new file mode 100644
index 00000000..1a07cd6d
--- /dev/null
+++ b/frontend/src/routes/editor/simulation/stale.test.ts
@@ -0,0 +1,54 @@
+// SPDX-License-Identifier: Apache-2.0
+import { describe, expect, it } from "vitest";
+import type { GraphDoc } from "../../../lib/workflows";
+import { changesOf, staleOf, staleWords } from "./stale";
+
+const literal = (value: unknown) => ({ kind: "literal", value });
+// The snapshot as the server stores it: canonical ids, every option written out (engine/graph/model.py).
+const SNAPSHOT = {
+  graph_format: 1,
+  nodes: [
+    { id: "0b9f3c2e-1a2b-4c3d-8e4f-5a6b7c8d9e01", key: "get_site", type: "mist.sites.get@1", config: { site: literal("HQ") }, position: { x: 0, y: 0 }, options: { timeout_s: null, max_attempts: null, on_error: "fail" } },
+    { id: "0b9f3c2e-1a2b-4c3d-8e4f-5a6b7c8d9e02", key: "old_lookup", type: "flow.transform@1", config: {}, position: { x: 0, y: 80 }, options: { timeout_s: null, max_attempts: null, on_error: "fail" } },
+    { id: "0b9f3c2e-1a2b-4c3d-8e4f-5a6b7c8d9e03", key: "notify", type: "slack.post@1", config: { text: literal("hi") }, position: { x: 0, y: 160 }, options: { timeout_s: null, max_attempts: 3, on_error: "fail" } },
+    { id: "0b9f3c2e-1a2b-4c3d-8e4f-5a6b7c8d9e05", key: "report", type: "flow.transform@1", config: {}, position: { x: 0, y: 240 }, options: { timeout_s: null, max_attempts: null, on_error: "fail" } },
+  ],
+  edges: [],
+} as unknown as GraphDoc;  // prettier-ignore
+// The draft as the editor holds it: another spelling of an id, a step moved, options left out, one step's text changed,
+// one step renamed, one removed, one added.
+const DRAFT = {
+  graph_format: 1,
+  nodes: [
+    { id: "{0B9F3C2E-1A2B-4C3D-8E4F-5A6B7C8D9E01}", key: "get_site", type: "mist.sites.get@1", config: { site: literal("HQ") }, position: { x: 300, y: 0 } },
+    { id: "0b9f3c2e-1a2b-4c3d-8e4f-5a6b7c8d9e03", key: "notify", type: "slack.post@1", config: { text: literal("hello") }, options: { max_attempts: 3 } },
+    { id: "0b9f3c2e-1a2b-4c3d-8e4f-5a6b7c8d9e05", key: "summary", type: "flow.transform@1", config: {} },
+    { id: "0b9f3c2e-1a2b-4c3d-8e4f-5a6b7c8d9e04", key: "get_site_v2", type: "mist.sites.get@1", config: {} },
+  ],
+  edges: [],
+} as unknown as GraphDoc;  // prettier-ignore
+const id = (n: number) => `0b9f3c2e-1a2b-4c3d-8e4f-5a6b7c8d9e0${n}`;
+
+describe("a result before the person's edits (§7.7; the Stale board)", () => {
+  it("is current while the draft is still the revision it ran, nothing unsaved", () => {
+    expect(staleOf(14, { revision: 14, generation: 3, savedGeneration: 3 })).toBeNull();
+  });
+
+  it("is for an older revision once the draft moved on, and before unsaved edits as soon as there's one", () => {
+    expect(staleOf(14, { revision: 16, generation: 5, savedGeneration: 5 })).toEqual({ kind: "revision", from: 14, to: 16 });
+    expect(staleOf(14, { revision: 14, generation: 4, savedGeneration: 3 })).toEqual({ kind: "local" });
+  });
+
+  it("says so in the board's words, the panel adding what to do", () => {
+    expect(staleWords({ kind: "revision", from: 14, to: 16 }, false)).toBe("this result is for revision 14; the draft is at revision 16.");
+    expect(staleWords({ kind: "revision", from: 14, to: 16 }, true)).toBe("this result is for revision 14; the draft is at revision 16. Simulate again to see the draft as it is.");
+    expect(staleWords({ kind: "local" }, false)).toBe("you've changed the draft since this result, and those changes aren't saved yet.");
+  });
+
+  it("finds the steps changed since, new since and gone, by identity, never by a move or an option's default", () => {
+    const c = changesOf(SNAPSHOT, DRAFT);
+    expect([...c.changed]).toEqual([id(3), id(5)]); // notify's text; report renamed summary
+    expect([...c.added]).toEqual([id(4)]);
+    expect([...c.gone]).toEqual([id(2)]);
+  });
+});
diff --git a/frontend/src/routes/editor/simulation/useSimulation.test.tsx b/frontend/src/routes/editor/simulation/useSimulation.test.tsx
index 1a08d310..2ee1c365 100644
--- a/frontend/src/routes/editor/simulation/useSimulation.test.tsx
+++ b/frontend/src/routes/editor/simulation/useSimulation.test.tsx
@@ -70,6 +70,28 @@ describe("a simulation the editor sends (§7.1, §7.2)", () => {
     expect(result.current.busy).toBe(false);
   });
 
+  it("refused by the deployment says so too: a 503 in the server's words isn't a lost answer", async () => {
+    answers.set(`POST ${BASE}`, () => json({ error: "production_runs_disabled", messages: ["Production runs are off in this deployment."] }, 503));
+    const { result } = session();
+    await act(() => result.current.start(freeze(14, { input: {} })));
+    expect(result.current.local).toMatchObject({ kind: "refused", error: { status: 503, code: "production_runs_disabled" } });
+    answers.set(`POST ${BASE}`, () => new Response("Bad gateway", { status: 502 })); // a proxy's, not the API's
+    await act(() => result.current.start(freeze(14, { input: {} })));
+    expect(result.current.local.kind).toBe("unknown");
+  });
+
+  it("tried again after a refusal is the same request: a refusal is never recorded, so its key is free", async () => {
+    answers.set(`POST ${BASE}`, () => json({ error: "no_current_build", messages: ["No current build has been recorded lately."] }, 503));
+    const { result } = session();
+    await act(() => result.current.start(freeze(14, { input: {} }, "k1")));
+    expect(result.current.local.kind).toBe("refused"); // a known answer, not a lost one
+    answers.set(`POST ${BASE}`, () => json(request("queued"), 202));
+    answers.set(`GET ${BASE}/r1`, () => json(state("queued")));
+    await act(() => result.current.checkAgain());
+    await waitFor(() => expect(result.current.phase).toBe("queued"));
+    expect(sent.filter((s) => s.method === "POST").map((s) => s.key)).toEqual(["k1", "k1"]);
+  });
+
   it("can be cancelled, and is read again at once", async () => {
     let cancelled = false;
     answers.set(`POST ${BASE}`, () => json(request("started"), 202));
```

- [ ] **Step 2: Run them**

Run: `npx --offline pnpm@12.6.0 exec vitest run src/routes/editor/simulation src/routes/editor/Editor.test.tsx`

Expected: FAIL: `stale.test.ts` and `Refusal.test.tsx` can't import their modules; 10 failed and 208 passed: no "Before
your edits:" on the bar or in the panel, no "changed since" or "new since" tag; no refusal shown ("Not simulated", "Fix
1 problem first: …", "The draft was changed elsewhere, so it wasn't simulated."); no failed step's code; the iterations
read the draft, not the one it ran; a 503 in the server's words is taken for a lost answer (`expected { kind: 'unknown'
… } to match object { kind: 'refused' … }`), and the try again's first answer is `unknown`, not `refused`.

- [ ] **Step 3: Implement**

Apply:

```diff
diff --git a/frontend/src/lib/simulations.ts b/frontend/src/lib/simulations.ts
index 12816a63..d848ba8c 100644
--- a/frontend/src/lib/simulations.ts
+++ b/frontend/src/lib/simulations.ts
@@ -16,6 +16,7 @@ export type SeedContract = Schemas["SeedContractOut"];
 export type SeedEntry = Schemas["SeedEntryOut"];
 export type DraftStartForm = Schemas["DraftStartFormOut"];
 export type SimulateBody = Schemas["SimulateIn"];
+export type DraftSnapshot = Schemas["DraftSnapshotOut"];
 export type Origin = StepSummary["origin"];
 
 /** A simulation as the editor sent it: its key, the revision it was frozen at and its body. An answer lost sends this
@@ -116,6 +117,15 @@ export const stepInstancesQuery = (
       })),
   });  // prettier-ignore
 
+/** The draft a simulation ran, as frozen for it (§6.5): never changes, so it's read once. */
+export const draftSnapshotQuery = (tenantId: string, workflowId: string, snapshotId: string) =>
+  queryOptions({
+    queryKey: ["draft-snapshot", tenantId, workflowId, snapshotId],
+    queryFn: () =>
+      ok(client.GET("/api/v1/t/{tenant_id}/workflows/{workflow_id}/draft/snapshots/{snapshot_id}", { params: { path: { ...path(tenantId, workflowId), snapshot_id: snapshotId } } })),
+    staleTime: Infinity,
+  });
+
 /** A step's seed contract at a revision, each value prefilled where its step's own sample allows (§6.6, D-s2). */
 export const seedContractQuery = (tenantId: string, workflowId: string, stepId: string, revision: number) =>
   queryOptions({
diff --git a/frontend/src/routes/editor/Editor.tsx b/frontend/src/routes/editor/Editor.tsx
index d64f4367..b28404ba 100644
--- a/frontend/src/routes/editor/Editor.tsx
+++ b/frontend/src/routes/editor/Editor.tsx
@@ -21,7 +21,7 @@ import { begin, record, redo, undo, type History } from "../../lib/history";
 import { CARD, layout } from "../../lib/layout";
 import { guardLeaving } from "../../lib/leaving";
 import type { Path } from "../../lib/schemaForm";
-import { ENDED, freeze, type StepSummary } from "../../lib/simulations";
+import { ENDED, draftSnapshotQuery, freeze, type StepSummary } from "../../lib/simulations";
 import { useDocumentTitle } from "../../lib/title";
 import { schedulesQuery, startSummary, workflowBindingsQuery } from "../../lib/triggers";
 import {
@@ -48,6 +48,7 @@ import { ResultBar } from "./simulation/ResultBar";
 import { tagsOf, type SimTag } from "./simulation/results";
 import { SimulationPanel } from "./simulation/SimulationPanel";
 import { SimulationResult } from "./simulation/SimulationResult";
+import { changesOf, staleOf } from "./simulation/stale";
 import { useSimulation } from "./simulation/useSimulation";
 import { type Problems } from "./StepCard";
 import { StepPicker, type PickMode } from "./StepPicker";
@@ -490,13 +491,31 @@ function Editor({
     (s: StepSummary) => findNode(doc, s.step_id)?.options?.max_attempts ?? typeMap.get(s.type)?.retry.max_attempts ?? null,
     [doc, typeMap],
   );
+  // Before the person's edits (§7.7): once it ended, when the server's draft moved on or an edit here isn't saved; then
+  // the draft it ran (its snapshot, read once) says which steps changed since, are new since, or are gone.
+  const simulationEnded = simulation.phase !== null && ENDED.has(simulation.phase);
+  const stale = simulationEnded && simulation.state ? staleOf(simulation.state.request.draft_revision, sync) : null;
+  const snapshotId = simulation.state?.request.draft_snapshot_id ?? null;
+  const snapshot = useQuery({ ...draftSnapshotQuery(tenantId, workflow.id, snapshotId ?? ""), enabled: snapshotId !== null && stale !== null });
+  const ran = snapshotId !== null && snapshot.data?.id === snapshotId ? snapshot.data.graph : null;
+  const changes = useMemo(() => (stale && ran ? changesOf(ran, doc) : null), [stale, ran, doc]);
   const simulated = useMemo(() => {
     const tags = new Map<string, SimTag[]>();
     if (!resultShown) return tags;
-    const ended = simulation.phase !== null && ENDED.has(simulation.phase);
-    for (const s of simulation.steps?.steps ?? []) tags.set(idKey(s.step_id), tagsOf(s, { maxAttempts: attemptsOf(s), ended }));
+    for (const s of simulation.steps?.steps ?? []) {
+      if (!findNode(doc, s.step_id)) continue; // no longer in the draft: the panel says so
+      const since: SimTag[] = changes?.changed.has(idKey(s.step_id)) ? [{ text: "changed since", kind: "note" }] : [];
+      tags.set(idKey(s.step_id), [...tagsOf(s, { maxAttempts: attemptsOf(s), ended: simulationEnded }), ...since]);
+    }
+    const from = simulation.state?.request.draft_revision;
+    for (const id of changes?.added ?? []) tags.set(id, [{ text: `new since revision ${from}: no result`, kind: "note" }]);
     return tags;
-  }, [resultShown, simulation.phase, simulation.steps, attemptsOf]);
+  }, [resultShown, simulation.steps, simulation.state, simulationEnded, doc, changes, attemptsOf]);
+  // A draft changed elsewhere refuses the simulation as it refuses a save: the editor stops, as on a save's 409.
+  const conflicted = simulation.local.kind === "refused" && simulation.local.error.code === "draft_conflict" ? simulation.local : null;
+  useEffect(() => {
+    if (conflicted) saver.current?.conflict();
+  }, [conflicted]);
   // When editing stops (a conflict, an exit, a publication), what only editing offers stops with it: an open dialog
   // closes, placing ends (a click on a read-only canvas places nothing) and says so. Focus held by what's gone (the
   // dialog, a "+", Auto layout, Add step, a panel's buttons) goes to what's drawn: a panel's heading when it was in
@@ -1306,6 +1325,7 @@ function Editor({
           revision={simulation.state.request.draft_revision}
           endedAt={simulation.state.run?.ended_at ?? simulation.state.request.ended_at}
           notWaited={(simulation.steps?.steps ?? []).some((s) => s.origin === "evaluated_not_waited")}
+          stale={stale}
           hidden={!resultShown}
           onHide={() => setHiddenFor(simulationId)}
           onShow={() => setHiddenFor(null)}
@@ -1476,8 +1496,8 @@ function Editor({
             }}
           >
             <SimulationResult
-              tenantId={tenantId} workflowId={workflow.id} session={simulation} doc={doc} attemptsOf={attemptsOf}
-              onGoTo={(id) => focus(item.node(id))}
+              tenantId={tenantId} workflowId={workflow.id} session={simulation} doc={doc} ran={ran} stale={stale} changes={changes}
+              attemptsOf={attemptsOf} onGoTo={(id) => focus(item.node(id))} onShowProblems={() => setSide({ kind: "problems" })}
             />
           </SimulationPanel>
         )}
diff --git a/frontend/src/routes/editor/simulation/Refusal.tsx b/frontend/src/routes/editor/simulation/Refusal.tsx
new file mode 100644
index 00000000..c66aa5d0
--- /dev/null
+++ b/frontend/src/routes/editor/simulation/Refusal.tsx
@@ -0,0 +1,83 @@
+// SPDX-License-Identifier: Apache-2.0
+// A simulation refused at admission, in the Simulation panel (4d-1c; the simulation design §7.7; the Refusals board):
+// in the server's words, never a catalogue of the client's. A draft's problems ("Fix N problems first", each with Go to,
+// and the Problems panel); a declassifying draft without the permission; the deployment's gate; a retired type (Go to
+// each step of it); no current build (Try again: a refusal is never recorded, so the same request can be sent again);
+// a step test's values by their pointer; the draft changed elsewhere. Nothing ran.
+import { Button } from "../../../components/Button";
+import type { ApiError } from "../../../lib/client";
+import { findNode, nodesOf } from "../../../lib/graph";
+import type { Diagnostic, GraphDoc } from "../../../lib/workflows";
+
+const DECLASSIFY = "declassify.forbidden";
+
+export function Refusal({ error, doc, onGoTo, onShowProblems, onTryAgain }: {
+  error: ApiError; doc: GraphDoc; onGoTo: (stepId: string) => void; onShowProblems: () => void; onTryAgain: () => void;
+}) {  // prettier-ignore
+  const body = (typeof error.body === "object" && error.body !== null ? error.body : {}) as {
+    diagnostics?: Diagnostic[]; messages?: unknown; problems?: { pointer: string; message: string }[];
+  };  // prettier-ignore
+  const messages = Array.isArray(body.messages) ? body.messages.filter((m): m is string => typeof m === "string") : [];
+  const goTo = (id: string, key: string) => (
+    <Button size="sm" aria-label={`Go to ${key}`} onClick={() => onGoTo(id)}>Go to</Button>
+  );
+
+  let said;
+  if (error.code === "invalid") {
+    const errors = (body.diagnostics ?? []).filter((d) => d.severity === "error");
+    said = errors.every((d) => d.code === DECLASSIFY) ? (
+      errors.map((d, i) => <p key={i}>{d.message}</p>)
+    ) : (
+      <>
+        <p>{`Fix ${errors.length} ${errors.length === 1 ? "problem" : "problems"} first: a draft with problems isn't simulated.`}</p>
+        <ul aria-label="Problems" className="flex flex-col">
+          {errors.map((d, i) => {
+            const step = d.node ? findNode(doc, d.node) : undefined;
+            return (
+              <li key={i} className="flex flex-wrap items-center gap-2 border-t border-line py-1.5 first:border-t-0">
+                <span className="grow">
+                  {step && <span className="font-mono">{step.key}</span>}
+                  {step && " · "}
+                  <span>{d.message}</span>
+                </span>
+                {step && goTo(step.id, step.key)}
+              </li>
+            );
+          })}
+        </ul>
+        <div>
+          <Button size="sm" onClick={onShowProblems}>Show the problems</Button>
+        </div>
+      </>
+    );
+  } else if (error.code === "draft_conflict") {
+    said = <p>The draft was changed elsewhere, so it wasn&apos;t simulated.</p>;
+  } else if (Array.isArray(body.problems)) {
+    said = (
+      <ul className="flex flex-col gap-1">
+        {body.problems.map((p, i) => <li key={i}>{`${p.pointer}: ${p.message}`}</li>)}
+      </ul>
+    );
+  } else if (messages.length > 0) {
+    const retired = error.code === "node_type_retired" ? nodesOf(doc).filter((n) => messages.some((m) => m.startsWith(`${n.type} `))) : [];
+    said = (
+      <>
+        {messages.map((m, i) => <p key={i}>{m}</p>)}
+        {retired.length > 0 && <div className="flex flex-wrap gap-2">{retired.map((n) => <Button key={n.id} size="sm" onClick={() => onGoTo(n.id)}>{`Go to ${n.key}`}</Button>)}</div>}
+        {error.code === "no_current_build" && (
+          <div>
+            <Button size="sm" onClick={onTryAgain}>Try again</Button>
+          </div>
+        )}
+      </>
+    );
+  } else {
+    said = <p>{`The server refused it: ${error.code}.`}</p>;
+  }
+  return (
+    <div className="flex flex-col gap-2 text-small">
+      <p className="font-semibold">Not simulated</p>
+      {said}
+    </div>
+  );
+}
diff --git a/frontend/src/routes/editor/simulation/ResultBar.tsx b/frontend/src/routes/editor/simulation/ResultBar.tsx
index 8223d91d..2cf06069 100644
--- a/frontend/src/routes/editor/simulation/ResultBar.tsx
+++ b/frontend/src/routes/editor/simulation/ResultBar.tsx
@@ -2,17 +2,19 @@
 // The canvas's bar for the editor's simulation (4d-1c; the simulation design §7.3; the Running and ResultCanvas
 // boards). While it runs: that nothing is sent, and Cancel. Once ended: the hatched banner (nothing was sent, and what
 // that doesn't prove; that flow timers weren't waited, when one wasn't), its status, revision and end, the panel, and
-// "Hide the result". Hidden: one bar that brings it back; the simulation, its history, and one running are untouched.
+// "Hide the result". Hidden: one bar that brings it back; the simulation, its history, and one running are untouched. A
+// result from before the person's edits says so in it (§7.7; the Stale board).
 import { Button } from "../../../components/Button";
 import { ENDED, type Phase } from "../../../lib/simulations";
 import { StatusChip } from "./chips";
 import { STATUS, clock } from "./lifecycle";
 import { SimBanner } from "./SimBanner";
+import { STALE, staleWords, type Stale } from "./stale";
 
 const BAR = "flex flex-wrap items-center gap-3 border-b border-line bg-surface-2 px-5 py-2.5 text-small";
 
-export function ResultBar({ phase, revision, endedAt, notWaited, hidden, onHide, onShow, onPanel, onCancel }: {
-  phase: Phase; revision: number; endedAt: string | null; notWaited: boolean; hidden: boolean;
+export function ResultBar({ phase, revision, endedAt, notWaited, stale, hidden, onHide, onShow, onPanel, onCancel }: {
+  phase: Phase; revision: number; endedAt: string | null; notWaited: boolean; stale: Stale | null; hidden: boolean;
   onHide: () => void; onShow: () => void; onPanel: () => void; onCancel: () => void;
 }) {  // prettier-ignore
   if (!ENDED.has(phase)) {
@@ -37,6 +39,11 @@ export function ResultBar({ phase, revision, endedAt, notWaited, hidden, onHide,
       <SimBanner role="status">
         <p><strong>Simulated.</strong> Nothing was sent. Results don&apos;t prove the live call will succeed.</p>
         {notWaited && <p>Flow delays and wait-until weren&apos;t waited; the simulation clock wasn&apos;t advanced.</p>}
+        {stale && (
+          <p className={STALE}>
+            <strong>Before your edits:</strong> {staleWords(stale, false)}
+          </p>
+        )}
         <p className="flex flex-wrap items-center gap-2 text-ink">
           <StatusChip phase={phase} />
           <span className="grow text-muted">{`revision ${revision}${endedAt ? ` · ${clock(endedAt)}` : ""}`}</span>
diff --git a/frontend/src/routes/editor/simulation/SimulationResult.tsx b/frontend/src/routes/editor/simulation/SimulationResult.tsx
index 9c1507aa..43ab0dc7 100644
--- a/frontend/src/routes/editor/simulation/SimulationResult.tsx
+++ b/frontend/src/routes/editor/simulation/SimulationResult.tsx
@@ -2,17 +2,21 @@
 // A simulation's result in the Simulation panel (4d-1c; the simulation design §7.5; the ResultPanel and Running
 // boards), below its lifecycle: what a simulation proves (the banner), the checks the server found when it admitted
 // it, the steps in run order with the canvas's tags and Go to, a loop's iterations paged, and the input used, as the
-// request stored it (§6.6's read-back: never recomputed from today's draft).
+// request stored it (§6.6's read-back: never recomputed from today's draft). A result from before the person's edits
+// says so, and marks each step changed since or no longer in the draft; a failed step says its code and message, and
+// that nothing was sent; a refusal is shown in the server's words (§7.7; the Stale and Refusals boards).
 import { useId, useState, type ReactNode } from "react";
 import { Button } from "../../../components/Button";
-import { findNode } from "../../../lib/graph";
+import { findNode, idKey } from "../../../lib/graph";
 import { ENDED, type StepSummary } from "../../../lib/simulations";
 import type { GraphDoc } from "../../../lib/workflows";
 import { bodyOf } from "./loopBody";
 import { Iterations } from "./Iterations";
 import { tagsOf } from "./results";
 import { SimBanner } from "./SimBanner";
+import { Refusal } from "./Refusal";
 import { InlineTags } from "./SimTags";
+import { STALE, staleWords, type Changes, type Stale } from "./stale";
 import type { SimulationSession } from "./useSimulation";
 
 const REDACTED = "[redacted]"; // the server's marker for a sensitive value (engine/runtime/projection.py)
@@ -32,26 +36,39 @@ const iterationKey = (final: StepSummary["final"]): string => {
   const key = final?.iteration_key;
   return typeof key === "string" ? key : "";
 };
+const field = (v: unknown, key: string): unknown => (typeof v === "object" && v !== null && !Array.isArray(v) ? (v as Record<string, unknown>)[key] : undefined);
+/** A step's attempts, said against its retries when it used them all. */
+const attempts = (n: number, max: number | null) => (n === 1 ? "1 attempt." : n === max ? `${n} attempts, the configured retries.` : `${n} attempts.`);
 
-export function SimulationResult({ tenantId, workflowId, session, doc, attemptsOf, onGoTo, onOpen }: {
-  tenantId: string; workflowId: string; session: SimulationSession; doc: GraphDoc;
-  attemptsOf: (s: StepSummary) => number | null; onGoTo: (stepId: string) => void;
-  onOpen?: (stepId: string, iterationKey: string) => void;
+export function SimulationResult({ tenantId, workflowId, session, doc, ran, stale, changes, attemptsOf, onGoTo, onShowProblems, onOpen }: {
+  tenantId: string; workflowId: string; session: SimulationSession;
+  doc: GraphDoc; ran: GraphDoc | null; // the draft as it is; the draft it ran (its snapshot), once read
+  stale: Stale | null; changes: Changes | null; attemptsOf: (s: StepSummary) => number | null;
+  onGoTo: (stepId: string) => void; onShowProblems: () => void; onOpen?: (stepId: string, iterationKey: string) => void;
 }) {  // prettier-ignore
   const [open, setOpen] = useState<string | null>(null); // the loop whose iterations are shown
-  const { state, phase } = session;
+  const { local, state, phase } = session;
+  if (local.kind === "refused") {
+    return <Refusal error={local.error} doc={doc} onGoTo={onGoTo} onShowProblems={onShowProblems} onTryAgain={() => void session.checkAgain()} />;
+  }
   if (!state || !phase) return null;
   const ended = ENDED.has(phase);
-  const ran = phase !== "refused" && phase !== "dead";
+  const began = phase !== "refused" && phase !== "dead"; // it ran, if only in part
   const request = state.request;
   const all = session.steps?.steps ?? [];
   const steps = ended ? all : all.filter((s) => s.instances > 0);
   const goTo = (id: string, key: string) =>
     findNode(doc, id) ? <Button size="sm" aria-label={`Go to ${key}`} onClick={() => onGoTo(id)}>Go to</Button> : null;
 
+  const graph = ran ?? doc;
   return (
     <>
-      {ended && ran && (
+      {ended && stale && (
+        <p className={STALE}>
+          <strong>Before your edits:</strong> {staleWords(stale, true)}
+        </p>
+      )}
+      {ended && began && (
         <SimBanner>
           <p><strong>Simulated.</strong> Nothing was sent. Results don&apos;t prove the live call will succeed.</p>
           {all.some((s) => s.origin === "evaluated_not_waited") && (
@@ -76,17 +93,23 @@ export function SimulationResult({ tenantId, workflowId, session, doc, attemptsO
           </ul>
         </Section>
       )}
-      {ran && steps.length > 0 && (
+      {began && steps.length > 0 && (
         <Section title={ended ? "Steps, in run order" : "Steps so far"}>
           <ul className="flex flex-col text-small">
             {steps.map((s) => {
-              const loop = s.type.startsWith("flow.loop@") && s.instances === 1 && findNode(doc, s.step_id) !== undefined;
-              const body = loop && ended ? bodyOf(doc, s.step_id) : [];
+              const loop = s.type.startsWith("flow.loop@") && s.instances === 1 && findNode(graph, s.step_id) !== undefined;
+              const body = loop && ended ? bodyOf(graph, s.step_id) : [];
               const expanded = open === s.step_id && body.length > 0;
+              const error = s.instances === 1 && field(s.final, "status") === "failed" ? field(s.final, "error") : undefined;
+              const code = field(error, "code");
+              const message = field(error, "message");
+              const attempt = field(s.final, "attempt");
               return (
                 <li key={s.step_id} className="flex flex-wrap items-center gap-1.5 border-t border-line py-1.5 first:border-t-0">
                   <span data-key className="font-mono">{s.key}</span>
                   <InlineTags tags={tagsOf(s, { maxAttempts: attemptsOf(s), ended })} />
+                  {!findNode(doc, s.step_id) && <span className="text-meta text-muted">no longer in the draft</span>}
+                  {changes?.changed.has(idKey(s.step_id)) && <span className="text-meta text-muted">changed since</span>}
                   <span className="grow" />
                   {body.length > 0 && (
                     <Button size="sm" aria-label={`Iterations of ${s.key}`} aria-expanded={expanded} onClick={() => setOpen(expanded ? null : s.step_id)}>
@@ -94,6 +117,12 @@ export function SimulationResult({ tenantId, workflowId, session, doc, attemptsO
                     </Button>
                   )}
                   {goTo(s.step_id, s.key)}
+                  {typeof code === "string" && (
+                    <p className="basis-full text-muted">
+                      <span className="font-mono text-ink">{code}</span>
+                      {` ${typeof message === "string" ? message : ""} ${attempts(typeof attempt === "number" ? attempt : 1, attemptsOf(s))} Nothing was sent.`}
+                    </p>
+                  )}
                   {expanded && (
                     <div className="basis-full ps-3">
                       <Iterations
diff --git a/frontend/src/routes/editor/simulation/stale.ts b/frontend/src/routes/editor/simulation/stale.ts
new file mode 100644
index 00000000..0d5046e9
--- /dev/null
+++ b/frontend/src/routes/editor/simulation/stale.ts
@@ -0,0 +1,64 @@
+// SPDX-License-Identifier: Apache-2.0
+// A simulation's result from before the person's edits (4d-1c; the simulation design §7.7; the Stale board): the
+// server's draft has moved on from the revision it ran, or there are edits here not saved yet (the editor's generation,
+// as publish's findings are dated). Which steps changed since, are new since or are gone comes from the draft it ran
+// (its snapshot) against the draft as it is, by identity: a step moved, or an option left at its default, isn't a
+// change. A step's own definition only: a rewired edge is covered by the banner, not marked on a step.
+import { idKey, nodesOf } from "../../../lib/graph";
+import type { GraphDoc, GraphNode } from "../../../lib/workflows";
+
+export type Stale = { kind: "revision"; from: number; to: number } | { kind: "local" };
+/** Steps by identity (`idKey`). */
+export interface Changes {
+  changed: Set<string>;
+  added: Set<string>;
+  gone: Set<string>;
+}
+
+/** The look of "Before your edits" (the Stale board: a warning, never the simulation's slate). */
+export const STALE = "rounded-md border border-warn-line bg-warn-bg px-2.5 py-2 text-small text-warn-ink";
+
+/** Whether a result for `revision` is before the person's edits. */
+export function staleOf(revision: number, sync: { revision: number; generation: number; savedGeneration: number }): Stale | null {
+  if (sync.revision !== revision) return { kind: "revision", from: revision, to: sync.revision };
+  return sync.generation !== sync.savedGeneration ? { kind: "local" } : null;
+}
+
+/** What follows "Before your edits:"; the panel says what to do. */
+export function staleWords(stale: Stale, panel: boolean): string {
+  const said =
+    stale.kind === "revision"
+      ? `this result is for revision ${stale.from}; the draft is at revision ${stale.to}.`
+      : "you've changed the draft since this result, and those changes aren't saved yet.";
+  return panel ? `${said} Simulate again to see the draft as it is.` : said;
+}
+
+/** JSON with its keys sorted, undefined left out: two spellings of one value are one text. */
+function canonical(v: unknown): string {
+  if (Array.isArray(v)) return `[${v.map(canonical).join(",")}]`;
+  if (v !== null && typeof v === "object") {
+    const entries = Object.entries(v as Record<string, unknown>).filter(([, x]) => x !== undefined);
+    return `{${entries.sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0)).map(([k, x]) => `${JSON.stringify(k)}:${canonical(x)}`).join(",")}}`;
+  }
+  return JSON.stringify(v) ?? "null";
+}
+
+const DEFAULTS = { timeout_s: null, max_attempts: null, on_error: "fail" }; // engine/graph/model.py's Options
+const definition = (n: GraphNode) => {
+  const options = Object.fromEntries(Object.entries(n.options ?? {}).filter(([, x]) => x !== undefined));
+  return canonical({ key: n.key, type: n.type, config: n.config ?? {}, options: { ...DEFAULTS, ...options } });
+};
+
+/** The steps changed since `ran`, new since, and gone, in the draft's order (gone ones in the snapshot's). */
+export function changesOf(ran: GraphDoc, doc: GraphDoc): Changes {
+  const before = new Map(nodesOf(ran).map((n) => [idKey(n.id), definition(n)]));
+  const now = new Set(nodesOf(doc).map((n) => idKey(n.id)));
+  const changes: Changes = { changed: new Set(), added: new Set(), gone: new Set() };
+  for (const n of nodesOf(doc)) {
+    const was = before.get(idKey(n.id));
+    if (was === undefined) changes.added.add(idKey(n.id));
+    else if (was !== definition(n)) changes.changed.add(idKey(n.id));
+  }
+  for (const id of before.keys()) if (!now.has(id)) changes.gone.add(id);
+  return changes;
+}
diff --git a/frontend/src/routes/editor/simulation/useSimulation.ts b/frontend/src/routes/editor/simulation/useSimulation.ts
index 775078cf..e598afaa 100644
--- a/frontend/src/routes/editor/simulation/useSimulation.ts
+++ b/frontend/src/routes/editor/simulation/useSimulation.ts
@@ -36,8 +36,9 @@ export interface SimulationSession {
   readAgain: () => void;
 }
 
-/** Whether a request's outcome is unknown: no answer reached the editor, or a 5xx came in the API's place. */
-const uncertain = (e: unknown) => !(e instanceof ApiError) || e.status >= 500;
+/** Whether a request's outcome is unknown: no answer reached the editor, or a 5xx came in the API's place. The API's
+ * own 503 says why, in its code (the production gate, no current build): a refusal, known. */
+const uncertain = (e: unknown) => !(e instanceof ApiError) || (e.status >= 500 && !(e.status === 503 && e.code !== "http_error"));
 
 export function useSimulation(tenantId: string, workflowId: string): SimulationSession {
   const qc = useQueryClient();
@@ -79,8 +80,9 @@ export function useSimulation(tenantId: string, workflowId: string): SimulationS
     },
     [tenantId, workflowId],
   );
+  // The same request again: its answer lost, or refused (admission rolls a refusal back, so its key is free).
   const checkAgain = useCallback(async () => {
-    if (local.kind === "unknown") await send(local.frozen);
+    if (local.kind === "unknown" || local.kind === "refused") await send(local.frozen);
   }, [local, send]);
   const cancel = useCallback(async () => {
     if (requestId === null) return null;
```

- [ ] **Step 4: Run them again**

Run: the same command.

Expected: PASS, 231 passed.

- [ ] **Step 5: Static checks**

Run: the two of "How to run things". Expected: no output.

- [ ] **Step 6: Commit, and the milestone**

```bash
git add frontend/src/lib/simulations.ts frontend/src/routes/editor
git commit -m "feat(editor): a result from before the person's edits says so; refusals in the server's words (4d-1c)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

Append `### 4d-1c, milestone 2 (date)` to the ledger: the tasks' commits, each task's test counts as run, every
mid-slice ruling. Commit it (`docs(editor-4): 4d-1c milestone 2`). **Pause** for the owner's review.

---

# Milestone 3 — Simulate step

### Task 9: The Test tab

**Spec:** §7.6 (the Test tab), §7.7 (a step that can't run alone); the TestTab and TestOther boards.

**Files:**
- Create: `frontend/src/routes/editor/simulation/TestTab.tsx`, `frontend/src/routes/editor/simulation/TestTab.test.tsx`
- Modify: `frontend/src/routes/editor/drawer/StepDrawer.tsx` (`test`)
- Modify: `frontend/src/routes/editor/simulation/Refusal.tsx` (`heading`)
- Modify: `frontend/src/routes/editor/Editor.tsx`, `frontend/src/routes/editor/Editor.test.tsx`

**Interfaces:**
- Consumes: `seedContractQuery` (Task 2); `Refusal` (Task 8); the editor's `whenSettled`, `simulate()`, `focus()`,
  `item.node()`.
- Produces:
  - `interface TestTabProps { tenantId; workflowId; node; doc; types; revision; session; blocked; onSave():
    Promise<number | null>; onStart(frozen); onSimulateWorkflow(); onGoTo(stepId); onShowProblems() }`;
    `TestTab(props)`.
  - `StepDrawer`'s `test?: ReactNode`: a third tab, "Test", shown even on a step with nothing to set up.
  - `Refusal`'s `heading?: string | null` (default "Not simulated"; null before anything was tried).
  - In `Editor`: `saveFirst(): Promise<number | null>` (the simulation's save and its notices, out of `simulate()`).

The Test tab is offered to editors, on a step of a known type. It reads the step's seed contract at the saved
revision, only while it's open. A step that can't run alone says why in the server's
words, with "◌ Simulate workflow" (ruling 11). A draft with problems asks for them to be fixed first, without "Not
simulated": nothing was tried. A step not saved yet says its values are read once it's saved; a failed read offers
"Read them again". A step that can run alone: "Runs <key> alone, with these values in place of what the steps before
it would give. Nothing is sent.", then "Values it reads" at its revision (Task 10 fills it).

- [ ] **Step 1: Write the failing tests**

Apply:

```diff
diff --git a/frontend/src/routes/editor/Editor.test.tsx b/frontend/src/routes/editor/Editor.test.tsx
index 76b2b344..778537c5 100644
--- a/frontend/src/routes/editor/Editor.test.tsx
+++ b/frontend/src/routes/editor/Editor.test.tsx
@@ -2154,6 +2154,35 @@ describe("the Triggers panel (4c-3b)", () => {
   });
 });
 
+// Simulate step (4d-1c; the simulation design §7.6; the TestTab, TestResult and TestOther boards).
+describe("Simulate step", () => {
+  const SEEDS = `${BASE}/draft/steps/id-transform/seeds`;
+  beforeEach(() => {
+    answers.set(`GET ${BASE}/draft/simulations`, () => json([]));
+    answers.set(`GET ${BASE}`, () => json({ ...WORKFLOW, draft: draftWith("transform") }));
+    answers.set(`GET ${SEEDS}`, () => json({ draft_revision: 1, step_id: "id-transform", refused: null, entries: [] }));
+  });
+
+  it("is a Test tab beside Setup and Options, even on a step with nothing to set up", async () => {
+    await show();
+    await userEvent.click(screen.getByRole("button", { name: "transform" }));
+    const drawer = screen.getByRole("complementary", { name: "transform" });
+    expect(within(drawer).getAllByRole("tab").map((t) => t.textContent)).toEqual(["Setup", "Options", "Test"]);
+    await userEvent.click(within(drawer).getByRole("tab", { name: "Test" }));
+    const intro = "Runs transform alone, with these values in place of what the steps before it would give. Nothing is sent.";
+    expect(await within(drawer).findByText((_, el) => el?.tagName === "P" && el.textContent === intro)).toBeTruthy();
+  });
+
+  it("isn't offered to a viewer", async () => {
+    role = "viewer";
+    await show();
+    await userEvent.click(screen.getByRole("button", { name: "transform" }));
+    const drawer = screen.getByRole("complementary", { name: "transform" });
+    expect(within(drawer).queryByRole("tab", { name: "Test" })).toBeNull();
+    expect(within(drawer).getByText("This step has nothing to set up.")).toBeTruthy();
+  });
+});
+
 // Simulate workflow (4d-1c; the simulation design §7.1; the Main, Preflight and ReadOnly boards).
 describe("Simulate workflow", () => {
   const SIM = `${BASE}/draft/simulations`;
diff --git a/frontend/src/routes/editor/simulation/TestTab.test.tsx b/frontend/src/routes/editor/simulation/TestTab.test.tsx
new file mode 100644
index 00000000..74c92d26
--- /dev/null
+++ b/frontend/src/routes/editor/simulation/TestTab.test.tsx
@@ -0,0 +1,95 @@
+// SPDX-License-Identifier: Apache-2.0
+import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
+import { render, screen } from "@testing-library/react";
+import userEvent from "@testing-library/user-event";
+import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
+import type { SeedContract } from "../../../lib/simulations";
+import type { GraphDoc, GraphNode, NodeType } from "../../../lib/workflows";
+import { TestTab } from "./TestTab";
+import type { SimulationSession } from "./useSimulation";
+
+const SEEDS = "/api/v1/t/t1/workflows/w1/draft/steps/id-notify/seeds";
+const NOTIFY = { id: "id-notify", key: "notify", type: "slack.post@1", config: {} } as unknown as GraphNode;
+const DOC = { graph_format: 1, nodes: [NOTIFY], edges: [] } as unknown as GraphDoc;
+const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
+
+let contract: () => Response;
+let asked: string[];
+beforeEach(() => {
+  asked = [];
+  contract = () => json({ draft_revision: 14, step_id: "id-notify", refused: null, entries: [] } satisfies SeedContract);
+  vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
+    const url = new URL((input as Request).url);
+    asked.push(url.pathname + url.search);
+    return Promise.resolve(url.pathname === SEEDS ? contract() : json({ error: "not_found" }, 404));
+  });
+});
+afterEach(() => vi.restoreAllMocks());
+
+/** A paragraph saying exactly this, whatever its parts (a key in mono). */
+const said = (text: string) => (_: string, el: Element | null) => el?.tagName === "P" && el.textContent === text;
+
+function idle(): SimulationSession {
+  return {
+    local: { kind: "idle" }, state: null, steps: null, phase: null, busy: false, readFailed: false, asOf: null,
+    start: vi.fn(), checkAgain: vi.fn(), cancel: vi.fn(), readAgain: vi.fn(),
+  };  // prettier-ignore
+}
+
+function show(over: Partial<Parameters<typeof TestTab>[0]> = {}) {
+  const props = {
+    tenantId: "t1", workflowId: "w1", node: NOTIFY, doc: DOC, types: new Map<string, NodeType>(), revision: 14, session: idle(),
+    blocked: false, onSave: vi.fn(() => Promise.resolve(14)), onStart: vi.fn(), onSimulateWorkflow: vi.fn(), onGoTo: vi.fn(),
+    onShowProblems: vi.fn(), ...over,
+  };  // prettier-ignore
+  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
+  render(
+    <QueryClientProvider client={qc}>
+      <TestTab {...props} />
+    </QueryClientProvider>,
+  );
+  return props;
+}
+
+describe("the Test tab (§7.6; the TestTab and TestOther boards)", () => {
+  it("reads the values a step reads, at the draft's saved revision", async () => {
+    show();
+    expect(await screen.findByText(said("Runs notify alone, with these values in place of what the steps before it would give. Nothing is sent."))).toBeTruthy();
+    expect(screen.getByRole("heading", { name: "Values it reads" })).toBeTruthy();
+    expect(screen.getByText("revision 14")).toBeTruthy();
+    expect(asked).toEqual([`${SEEDS}?revision=14`]);
+  });
+
+  it("says why a step can't run alone, in the server's words, and offers Simulate workflow", async () => {
+    contract = () => json({ draft_revision: 14, step_id: "id-notify", refused: "This step can't be simulated alone: simulate the workflow to see it run.", entries: [] });
+    const p = show();
+    expect(await screen.findByText("This step can't be simulated alone: simulate the workflow to see it run.")).toBeTruthy();
+    expect(screen.queryByRole("heading", { name: "Values it reads" })).toBeNull();
+    await userEvent.click(screen.getByRole("button", { name: "◌ Simulate workflow" }));
+    expect(p.onSimulateWorkflow).toHaveBeenCalled();
+  });
+
+  it("asks for the draft's problems to be fixed first", async () => {
+    contract = () => json({ error: "invalid", diagnostics: [{ code: "ref.unknown", message: "A reference to get_sit, which isn't a step.", node: "id-notify", field: null, fix: null, severity: "error" }] }, 422);
+    const p = show();
+    expect(await screen.findByText("Fix 1 problem first: a draft with problems isn't simulated.")).toBeTruthy();
+    expect(screen.queryByText("Not simulated")).toBeNull(); // nothing was tried yet
+    await userEvent.click(screen.getByRole("button", { name: "Show the problems" }));
+    expect(p.onShowProblems).toHaveBeenCalled();
+  });
+
+  it("says a new step is read once the draft is saved", async () => {
+    contract = () => json({ error: "not_found" }, 404);
+    show();
+    expect(await screen.findByText("This step isn't in the saved draft yet: its values are read once it's saved.")).toBeTruthy();
+  });
+
+  it("says when the values couldn't be read, and reads them again", async () => {
+    contract = () => json({ error: "http_error" }, 500);
+    show();
+    expect(await screen.findByText("The values it reads couldn't be read.")).toBeTruthy();
+    contract = () => json({ draft_revision: 14, step_id: "id-notify", refused: null, entries: [] });
+    await userEvent.click(screen.getByRole("button", { name: "Read them again" }));
+    expect(await screen.findByRole("heading", { name: "Values it reads" })).toBeTruthy();
+  });
+});
```

- [ ] **Step 2: Run them**

Run: `npx --offline pnpm@12.6.0 exec vitest run src/routes/editor/simulation/TestTab.test.tsx
src/routes/editor/simulation/Refusal.test.tsx src/routes/editor/Editor.test.tsx`

Expected: FAIL: `TestTab.test.tsx` can't import its module; 1 failed and 169 passed: the drawer has no tabs on a step
with nothing to set up. "isn't offered to a viewer" passes at once: it pins what a viewer sees today.

- [ ] **Step 3: Implement**

Apply:

```diff
diff --git a/frontend/src/routes/editor/Editor.tsx b/frontend/src/routes/editor/Editor.tsx
index b28404ba..6c5a9742 100644
--- a/frontend/src/routes/editor/Editor.tsx
+++ b/frontend/src/routes/editor/Editor.tsx
@@ -49,6 +49,7 @@ import { tagsOf, type SimTag } from "./simulation/results";
 import { SimulationPanel } from "./simulation/SimulationPanel";
 import { SimulationResult } from "./simulation/SimulationResult";
 import { changesOf, staleOf } from "./simulation/stale";
+import { TestTab } from "./simulation/TestTab";
 import { useSimulation } from "./simulation/useSimulation";
 import { type Problems } from "./StepCard";
 import { StepPicker, type PickMode } from "./StepPicker";
@@ -935,26 +936,33 @@ function Editor({
     return left;
   }
 
-  /** Simulate workflow's preflight, Publish's own (§7.1): with the edits not applied settled, the save is flushed, and
-   * the input is asked for at the revision that save made, never an older one. A failed save sends nothing. */
-  async function simulate() {
+  /** A simulation's save, Publish's own (§7.1): the draft as it is, saved; the revision saved, else null, said why. A
+   * failed save sends nothing. Called with the edits not applied settled (`whenSettled`). */
+  async function saveFirst(): Promise<number | null> {
     setSaving(true);
     setNotice({ tone: "info", text: "Saving before the simulation…" });
     try {
       const revision = await saver.current!.flush();
       setNotice(null);
-      setSimulateAt({ revision, doc: draftNow() });
+      return revision;
     } catch (e) {
       // A conflict has its own banner.
       setNotice(e instanceof ConflictError ? null : {
         tone: "danger", text: "Not simulated: your latest edits aren't saved. Retry the save, then simulate.",
         action: { label: "Retry", run: () => saver.current?.retry() },
       });  // prettier-ignore
+      return null;
     } finally {
       setSaving(false);
     }
   }
 
+  /** Simulate workflow: the input is asked for at the revision the save made, never an older one. */
+  async function simulate() {
+    const revision = await saveFirst();
+    if (revision !== null) setSimulateAt({ revision, doc: draftNow() });
+  }
+
   /** `then`, once every unapplied edit is in the draft; when one can't be, the person decides first (ruling 18). */
   function whenSettled(action: string, then: () => void) {
     const left = settleAll();
@@ -1394,6 +1402,18 @@ function Editor({
             actions={viewing ? VERSION_ACTIONS : actionsFor(open.id)}
             note={noteFor(open.id)}
             focusField={side?.kind === "step" ? (side.field ?? null) : null}
+            test={
+              simulator ? (
+                <TestTab
+                  tenantId={tenantId} workflowId={workflow.id} node={open} doc={doc} types={typeMap} revision={sync.revision}
+                  session={simulation} blocked={sync.status === "conflict" || simulation.busy || saving || busy !== null}
+                  onSave={() => new Promise((resolve) => whenSettled("simulate", () => void saveFirst().then(resolve)))}
+                  onStart={(frozen) => void simulation.start(frozen)}
+                  onSimulateWorkflow={() => whenSettled("simulate", () => void simulate())}
+                  onGoTo={(id) => focus(item.node(id))} onShowProblems={() => setSide({ kind: "problems" })}
+                />
+              ) : undefined
+            }
             onAdd={onItem}
             onDelete={() => setAsking({ kind: "node", id: open.id })}
             onConnectPort={(port) => setConnecting({ node: open.id, port })}
diff --git a/frontend/src/routes/editor/drawer/StepDrawer.tsx b/frontend/src/routes/editor/drawer/StepDrawer.tsx
index fdd7c82a..c7201d60 100644
--- a/frontend/src/routes/editor/drawer/StepDrawer.tsx
+++ b/frontend/src/routes/editor/drawer/StepDrawer.tsx
@@ -4,7 +4,7 @@
 // schema, the required ones on Setup and the rest on Options (ruling 3). Then how its formulas run, and, for an
 // editor, 4b's actions: its "+" twins (WCAG 2.5.8), where it sits (2.5.7), its edges. Escape closes it as Close does
 // and gives focus back to the step. What its fields do to the draft goes through `actions`, the editor's (ruling 18).
-import { useCallback, useEffect, useMemo, useRef, useState } from "react";
+import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
 import { Button } from "../../../components/Button";
 import { Tabs } from "../../../components/Tabs";
 import { fieldsOf, tabsOf, type FieldSpec } from "../../../lib/schemaForm";
@@ -33,7 +33,7 @@ const NUDGES: { key: Nudge; glyph: string; word: string }[] = [
   { key: "ArrowRight", glyph: "→", word: "right" },
 ];
 
-type Tab = "setup" | "options";
+type Tab = "setup" | "options" | "test";
 
 /** The drawer's disabled controls, its own and 4a's alike, look disabled: the disabled fill and line, their values in
  * muted ink, which stays legible where the disabled ink wouldn't (the owner's ruling O2). 4a's forms elsewhere keep
@@ -80,12 +80,14 @@ function locate(root: HTMLElement, { pointer, kind }: FocusRequest): HTMLElement
 
 export function StepDrawer({
   node, type, tenantId, workflowId, revision, steps, openDeclassify, ports, problems, expressions, editable, adds, actions, note, focusField,
-  onAdd, onDelete, onConnectPort, onPlace, onNudge, onClose,
+  test, onAdd, onDelete, onConnectPort, onPlace, onNudge, onClose,
 }: {
   node: GraphNode; type: NodeType | undefined; tenantId: string; workflowId: string; revision: number | null;
   steps: { id: string; key: string; title: string | null }[]; openDeclassify?: () => void; ports: string[];
   problems: Diagnostic[] | null; expressions: Expression[]; editable: boolean; adds: { label: string; action: ItemAction }[];
-  actions: DrawerActions; note: string | null; focusField: { pointer: string; kind?: UnappliedKind; n: number } | null; onAdd: (action: ItemAction) => void; onDelete: () => void; onConnectPort: (port: string) => void;
+  actions: DrawerActions; note: string | null; focusField: { pointer: string; kind?: UnappliedKind; n: number } | null;
+  test?: ReactNode; // the Test tab, for editors (4d-1c, §7.6), even on a step with nothing to set up
+  onAdd: (action: ItemAction) => void; onDelete: () => void; onConnectPort: (port: string) => void;
   onPlace: () => void; onNudge: (key: Nudge) => void; onClose: () => void;
 }) {  // prettier-ignore
   const heading = useRef<HTMLHeadingElement>(null);
@@ -229,7 +231,7 @@ export function StepDrawer({
           <p className="text-small">
             This server doesn&apos;t know this step&apos;s type, so its settings can&apos;t be shown. They&apos;re kept as they are.
           </p>
-        ) : fields.length === 0 ? (
+        ) : fields.length === 0 && !test ? (
           <p className="text-small text-muted">This step has nothing to set up.</p>
         ) : (
           <Tabs
@@ -256,6 +258,7 @@ export function StepDrawer({
                   ? options.map((f) => <FieldView key={f.pointer} spec={f} />)
                   : <p className="text-small text-muted">Nothing else to set.</p>,
               },
+              ...(test ? [{ value: "test" as const, label: "Test", content: test }] : []),
             ]}
           />
         )}
diff --git a/frontend/src/routes/editor/simulation/Refusal.tsx b/frontend/src/routes/editor/simulation/Refusal.tsx
index c66aa5d0..67d5b632 100644
--- a/frontend/src/routes/editor/simulation/Refusal.tsx
+++ b/frontend/src/routes/editor/simulation/Refusal.tsx
@@ -3,7 +3,8 @@
 // in the server's words, never a catalogue of the client's. A draft's problems ("Fix N problems first", each with Go to,
 // and the Problems panel); a declassifying draft without the permission; the deployment's gate; a retired type (Go to
 // each step of it); no current build (Try again: a refusal is never recorded, so the same request can be sent again);
-// a step test's values by their pointer; the draft changed elsewhere. Nothing ran.
+// a step test's values by their pointer; the draft changed elsewhere. Nothing ran. The Test tab shows a draft's problems
+// before anything is tried, without "Not simulated" (`heading` null).
 import { Button } from "../../../components/Button";
 import type { ApiError } from "../../../lib/client";
 import { findNode, nodesOf } from "../../../lib/graph";
@@ -11,8 +12,9 @@ import type { Diagnostic, GraphDoc } from "../../../lib/workflows";
 
 const DECLASSIFY = "declassify.forbidden";
 
-export function Refusal({ error, doc, onGoTo, onShowProblems, onTryAgain }: {
-  error: ApiError; doc: GraphDoc; onGoTo: (stepId: string) => void; onShowProblems: () => void; onTryAgain: () => void;
+export function Refusal({ error, doc, heading = "Not simulated", onGoTo, onShowProblems, onTryAgain }: {
+  error: ApiError; doc: GraphDoc; heading?: string | null; onGoTo: (stepId: string) => void; onShowProblems: () => void;
+  onTryAgain: () => void;
 }) {  // prettier-ignore
   const body = (typeof error.body === "object" && error.body !== null ? error.body : {}) as {
     diagnostics?: Diagnostic[]; messages?: unknown; problems?: { pointer: string; message: string }[];
@@ -76,7 +78,7 @@ export function Refusal({ error, doc, onGoTo, onShowProblems, onTryAgain }: {
   }
   return (
     <div className="flex flex-col gap-2 text-small">
-      <p className="font-semibold">Not simulated</p>
+      {heading && <p className="font-semibold">{heading}</p>}
       {said}
     </div>
   );
diff --git a/frontend/src/routes/editor/simulation/TestTab.tsx b/frontend/src/routes/editor/simulation/TestTab.tsx
new file mode 100644
index 00000000..7da5ab92
--- /dev/null
+++ b/frontend/src/routes/editor/simulation/TestTab.tsx
@@ -0,0 +1,73 @@
+// SPDX-License-Identifier: Apache-2.0
+// A step's Test tab (4d-1c; the simulation design §7.6; the TestTab, TestResult and TestOther boards), beside Setup and
+// Options, for editors: the values the step reads, its seed contract, read at the draft's saved revision; a step that
+// can't run alone says why, in the server's words, and offers the workflow's simulation instead. A draft with problems
+// is read once they're fixed, as admission reads it.
+import { useQuery } from "@tanstack/react-query";
+import { Button } from "../../../components/Button";
+import { ApiError } from "../../../lib/client";
+import { seedContractQuery, type Frozen } from "../../../lib/simulations";
+import type { GraphDoc, GraphNode, NodeType } from "../../../lib/workflows";
+import { Refusal } from "./Refusal";
+import type { SimulationSession } from "./useSimulation";
+
+export interface TestTabProps {
+  tenantId: string;
+  workflowId: string;
+  node: GraphNode;
+  doc: GraphDoc;
+  types: Map<string, NodeType>;
+  revision: number; // the draft's saved revision: the contract is read at it
+  session: SimulationSession;
+  blocked: boolean; // Simulate waits: a conflict, a save, a simulation not ended
+  onSave: () => Promise<number | null>; // the edits settled and saved: the revision saved, else null (the editor says why)
+  onStart: (frozen: Frozen) => void;
+  onSimulateWorkflow: () => void;
+  onGoTo: (stepId: string) => void;
+  onShowProblems: () => void;
+}
+
+export function TestTab({ tenantId, workflowId, node, doc, revision, onSimulateWorkflow, onGoTo, onShowProblems }: TestTabProps) {
+  const contract = useQuery(seedContractQuery(tenantId, workflowId, node.id, revision));
+  if (contract.isPending) return <p className="text-small text-muted">Reading the values it reads…</p>;
+  if (contract.isError) {
+    const e = contract.error;
+    if (e instanceof ApiError && e.code === "invalid") {
+      return <Refusal error={e} doc={doc} heading={null} onGoTo={onGoTo} onShowProblems={onShowProblems} onTryAgain={() => void contract.refetch()} />;
+    }
+    if (e instanceof ApiError && e.status === 404) {
+      return <p className="text-small text-muted">This step isn&apos;t in the saved draft yet: its values are read once it&apos;s saved.</p>;
+    }
+    return (
+      <p className="flex flex-wrap items-center gap-2 text-small">
+        The values it reads couldn&apos;t be read.
+        <Button size="sm" onClick={() => void contract.refetch()}>Read them again</Button>
+      </p>
+    );
+  }
+  const c = contract.data;
+  if (c.refused !== null) {
+    return (
+      <>
+        <p className="text-small">{c.refused}</p>
+        <div>
+          <Button variant="simulate" size="md" onClick={onSimulateWorkflow}>◌ Simulate workflow</Button>
+        </div>
+      </>
+    );
+  }
+  return (
+    <>
+      <p className="text-small">
+        Runs <span className="font-mono">{node.key}</span> alone, with these values in place of what the steps before it would give.
+        Nothing is sent.
+      </p>
+      <section aria-labelledby="test-values" className="flex flex-col gap-3">
+        <div className="flex items-baseline justify-between gap-3">
+          <h3 id="test-values" className="text-small font-semibold">Values it reads</h3>
+          <span className="text-meta text-muted">{`revision ${c.draft_revision}`}</span>
+        </div>
+      </section>
+    </>
+  );
+}
```

- [ ] **Step 4: Run them again**

Run: the same command.

Expected: PASS, 175 passed.

- [ ] **Step 5: Static checks**

Run: the two of "How to run things". Expected: no output.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/routes/editor
git commit -m "feat(editor): a step's Test tab, its values read at the saved revision (4d-1c)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: A step's values, and Simulate step

**Spec:** §7.6 (the seed contract as fields, the prefill, the revision read again), §7.7 (`seed_missing`,
`seed_alias`, `seed_unknown`); the TestTab and TestOther boards.

**Files:**
- Create: `frontend/src/routes/editor/simulation/seeds.ts`, `frontend/src/routes/editor/simulation/seeds.test.ts`
- Create: `frontend/src/routes/editor/simulation/SeedField.tsx`
- Modify: `frontend/src/routes/editor/simulation/TestTab.tsx`, `TestTab.test.tsx`
- Modify: `frontend/src/routes/editor/simulation/loopBody.ts` (`regionOf` exported)
- Modify: `frontend/src/routes/editor/Editor.test.tsx`

**Interfaces:**
- Consumes: `freeze` (Task 2); `parseJson` (`lib/config.ts`); `controlClass` (`components/Field.tsx`); `Tag` (Task 3);
  `regionOf` (`loopBody.ts`).
- Produces, in `seeds.ts`:
  - `type Choice` (`value`, `null`, `absent`); `interface SeedInput { choice: Choice | null; text: string }`;
    `type Collected` (`{ values; absent }` or `{ missing: string[]; problems: Record<string, string> }`);
  - `choicesOf(entry)`, `typeWords(types)`, `isText(entry)`, `initialOf(entry)`, `prefilled(entry)`,
    `hintOf(entry)`, `titleOf(pointer, doc, types, stepId)`, `collect(contract, inputs, stepKey)`.
- Produces `SeedField({ entry, title, input, error, isNew, onChange })`.

Each value the step reads is a field: its title (ruling 14), "required" or "optional", "nullable", "sensitive", its
type in words, and its pointer. A required value that can be null offers "A value" and "Null"; an optional one, "A
value" and "Absent: as if it was never set" (and "Null" when nullable). A sensitive value is typed and masked, never
prefilled. A value from its step's own sample says so, with Clear; one typed says why (D-s2's reasons). "◌ Simulate
step" saves first. When the save moved the draft, the contract is read again and shown, saying how many more values
the step reads, each marked "new in revision N", and nothing is sent. Missing values are said on each field and
counted above them ("Not simulated: 2 values are missing."), the count following the fields as they're given. The
values are sent at the revision the save made, as `{ target: { step_id, values, absent } }` (ruling 13). Values the
server refused are said on their fields; one with no field, above them.

- [ ] **Step 1: Write the failing tests**

Apply:

```diff
diff --git a/frontend/src/routes/editor/Editor.test.tsx b/frontend/src/routes/editor/Editor.test.tsx
index 778537c5..5f8d1c27 100644
--- a/frontend/src/routes/editor/Editor.test.tsx
+++ b/frontend/src/routes/editor/Editor.test.tsx
@@ -2173,6 +2173,23 @@ describe("Simulate step", () => {
     expect(await within(drawer).findByText((_, el) => el?.tagName === "P" && el.textContent === intro)).toBeTruthy();
   });
 
+  it("sends the step's own simulation, saved first, at the revision the save made", async () => {
+    const sampled = { pointer: "/vars/region", types: ["string"], required: true, nullable: false, sensitive: false, prefill: { state: "typed", reason: "not_step_output", value: null } };
+    answers.set(`GET ${SEEDS}`, () => json({ draft_revision: 1, step_id: "id-transform", refused: null, entries: [sampled] }));
+    answers.set(`POST ${BASE}/draft/simulations`, () => json({ id: "r1", workflow_id: "w1", version_id: null, draft_snapshot_id: "s1", draft_revision: 1, target_step_id: "id-transform", mode: "simulate", source: "manual", status: "queued", reason: null, queued_at: "2026-10-15T10:42:05Z", ended_at: null, admission_checks: [] }, 202));
+    await show();
+    await userEvent.click(screen.getByRole("button", { name: "transform" }));
+    const drawer = screen.getByRole("complementary", { name: "transform" });
+    await userEvent.click(within(drawer).getByRole("tab", { name: "Test" }));
+    await userEvent.type(await within(drawer).findByLabelText("region required text"), "emea");
+    await userEvent.click(within(drawer).getByRole("button", { name: "◌ Simulate step" }));
+    await vi.waitFor(() => expect(sent.some((r) => r.method === "POST" && r.path === `${BASE}/draft/simulations`)).toBe(true));
+    const post = sent.find((r) => r.method === "POST" && r.path === `${BASE}/draft/simulations`)!;
+    expect(post.headers.get("If-Match")).toBe("1");
+    expect(post.body).toEqual({ target: { step_id: "id-transform", values: { "/vars/region": "emea" }, absent: [] } });
+    expect(screen.getByRole("complementary", { name: "transform" })).toBeTruthy(); // the drawer stays: its result comes in the tab
+  });
+
   it("isn't offered to a viewer", async () => {
     role = "viewer";
     await show();
diff --git a/frontend/src/routes/editor/simulation/TestTab.test.tsx b/frontend/src/routes/editor/simulation/TestTab.test.tsx
index 74c92d26..e6e94df7 100644
--- a/frontend/src/routes/editor/simulation/TestTab.test.tsx
+++ b/frontend/src/routes/editor/simulation/TestTab.test.tsx
@@ -1,9 +1,10 @@
 // SPDX-License-Identifier: Apache-2.0
 import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
-import { render, screen } from "@testing-library/react";
+import { render, screen, within } from "@testing-library/react";
 import userEvent from "@testing-library/user-event";
 import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
-import type { SeedContract } from "../../../lib/simulations";
+import { ApiError } from "../../../lib/client";
+import type { SeedContract, SeedEntry } from "../../../lib/simulations";
 import type { GraphDoc, GraphNode, NodeType } from "../../../lib/workflows";
 import { TestTab } from "./TestTab";
 import type { SimulationSession } from "./useSimulation";
@@ -13,7 +14,7 @@ const NOTIFY = { id: "id-notify", key: "notify", type: "slack.post@1", config: {
 const DOC = { graph_format: 1, nodes: [NOTIFY], edges: [] } as unknown as GraphDoc;
 const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
 
-let contract: () => Response;
+let contract: (revision: number) => Response;
 let asked: string[];
 beforeEach(() => {
   asked = [];
@@ -21,7 +22,7 @@ beforeEach(() => {
   vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
     const url = new URL((input as Request).url);
     asked.push(url.pathname + url.search);
-    return Promise.resolve(url.pathname === SEEDS ? contract() : json({ error: "not_found" }, 404));
+    return Promise.resolve(url.pathname === SEEDS ? contract(Number(url.searchParams.get("revision"))) : json({ error: "not_found" }, 404));
   });
 });
 afterEach(() => vi.restoreAllMocks());
@@ -43,12 +44,19 @@ function show(over: Partial<Parameters<typeof TestTab>[0]> = {}) {
     onShowProblems: vi.fn(), ...over,
   };  // prettier-ignore
   const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
-  render(
+  const view = render(
     <QueryClientProvider client={qc}>
       <TestTab {...props} />
     </QueryClientProvider>,
   );
-  return props;
+  /** The editor's next render: a revision saved, a simulation sent. */
+  const again = (more: Partial<Parameters<typeof TestTab>[0]>) =>
+    view.rerender(
+      <QueryClientProvider client={qc}>
+        <TestTab {...props} {...more} />
+      </QueryClientProvider>,
+    );
+  return { ...props, again };
 }
 
 describe("the Test tab (§7.6; the TestTab and TestOther boards)", () => {
@@ -93,3 +101,100 @@ describe("the Test tab (§7.6; the TestTab and TestOther boards)", () => {
     expect(await screen.findByRole("heading", { name: "Values it reads" })).toBeTruthy();
   });
 });
+
+const entry = (pointer: string, over: Partial<SeedEntry> = {}): SeedEntry => ({
+  pointer, types: ["string"], required: true, nullable: false, sensitive: false, prefill: { state: "typed", reason: "not_step_output", value: null }, ...over,
+});  // prettier-ignore
+const ENTRIES = [
+  entry("/steps/get_site/output/name", { prefill: { state: "prefilled", reason: null, value: "HQ Paris" } }),
+  entry("/vars/channel", { required: false, nullable: true }),
+  entry("/trigger/api_token", { sensitive: true, prefill: { state: "typed", reason: "sensitive", value: null } }),
+];
+/** What a control's description says: its hint and its error, as a screen reader reads them. */
+const description = (el: HTMLElement) =>
+  (el.getAttribute("aria-describedby") ?? "").split(" ").filter(Boolean).map((id) => document.getElementById(id)?.textContent ?? "").join(" ");
+
+describe("the values a step test sends (§7.6; the TestTab and TestOther boards)", () => {
+  beforeEach(() => {
+    contract = (revision) => json({ draft_revision: revision, step_id: "id-notify", refused: null, entries: ENTRIES } satisfies SeedContract);
+  });
+
+  it("prefills a value from its step's own sample, and clears it", async () => {
+    show();
+    const name = await screen.findByRole("textbox", { name: "name required text" });
+    expect(name).toHaveProperty("value", "HQ Paris");
+    expect(description(name)).toBe("From get_site's sample.");
+    expect(screen.getByText("/steps/get_site/output/name")).toBeTruthy();
+    await userEvent.click(screen.getByRole("button", { name: "Clear name" }));
+    expect(name).toHaveProperty("value", "");
+    expect(description(name)).toBe("");
+  });
+
+  it("offers Null and Absent where the step's read allows them", async () => {
+    show();
+    const choice = await screen.findByRole("radiogroup", { name: "channel optional nullable text" });
+    expect(within(choice).getAllByRole("radio").map((r) => r.parentElement?.textContent)).toEqual(["A value", "Null", "Absent: as if it was never set"]);
+  });
+
+  it("types a sensitive value, never prefilled", async () => {
+    show();
+    const token = await screen.findByLabelText("api_token required sensitive text");
+    expect(token.getAttribute("type")).toBe("password");
+    expect(description(token)).toBe("Sensitive: typed, never prefilled. Kept as a protected value.");
+  });
+
+  it("says which values are missing, on each, and sends nothing", async () => {
+    const p = show();
+    await userEvent.click(await screen.findByRole("button", { name: "◌ Simulate step" }));
+    expect(await screen.findByText("Not simulated: 2 values are missing.")).toBeTruthy();
+    expect(description(screen.getByLabelText("api_token required sensitive text"))).toContain("Give a value: notify reads it without a default.");
+    expect(screen.getByText("Give a value, or choose Absent.")).toBeTruthy();
+    expect(p.onStart).not.toHaveBeenCalled();
+    await userEvent.type(screen.getByLabelText("api_token required sensitive text"), "s3cret");
+    expect(screen.getByText("Not simulated: 1 value is missing.")).toBeTruthy(); // as each is given
+  });
+
+  it("sends the values at the revision the save made, as the step's own simulation", async () => {
+    const p = show();
+    await userEvent.type(await screen.findByLabelText("api_token required sensitive text"), "s3cret");
+    await userEvent.click(within(screen.getByRole("radiogroup", { name: "channel optional nullable text" })).getByRole("radio", { name: "Absent: as if it was never set" }));
+    await userEvent.click(screen.getByRole("button", { name: "◌ Simulate step" }));
+    await vi.waitFor(() => expect(p.onStart).toHaveBeenCalled());
+    expect(p.onSave).toHaveBeenCalled();
+    expect(vi.mocked(p.onStart).mock.calls[0]![0]).toMatchObject({
+      revision: 14,
+      body: { target: { step_id: "id-notify", values: { "/steps/get_site/output/name": "HQ Paris", "/trigger/api_token": "s3cret" }, absent: ["/vars/channel"] } },
+    });
+    expect(screen.getByText("Each value is checked against what notify reads.")).toBeTruthy();
+  });
+
+  it("reads the values again when saving moved the draft, and sends nothing until they're checked", async () => {
+    contract = (revision) =>
+      json({ draft_revision: revision, step_id: "id-notify", refused: null, entries: revision === 15 ? [...ENTRIES, entry("/vars/severity")] : ENTRIES });
+    const p = show({ onSave: vi.fn(() => Promise.resolve(15)) });
+    await userEvent.click(await screen.findByRole("button", { name: "◌ Simulate step" }));
+    p.again({ revision: 15 });
+    expect(await screen.findByText("Saving moved the draft to revision 15, and notify now reads one more value. Check the values, then simulate.")).toBeTruthy();
+    expect(screen.getByText("new in revision 15")).toBeTruthy();
+    expect(p.onStart).not.toHaveBeenCalled();
+  });
+
+  it("puts a refused value's problem on its field, and one with no field above the form", async () => {
+    const p = show();
+    await screen.findByLabelText("api_token required sensitive text");
+    const frozen = { key: "k1", revision: 14, body: { target: { step_id: "id-notify", values: {}, absent: [] } } };
+    const error = new ApiError(422, "seed_missing", { error: "seed_missing", problems: [
+      { code: "seed_missing", pointer: "/trigger/api_token", message: "A value is required here." },
+      { code: "seed_unknown", pointer: "/vars/gone", message: "Nothing reads this." },
+    ] });  // prettier-ignore
+    p.again({ session: { ...idle(), local: { kind: "refused", frozen, error } } });
+    expect(description(await screen.findByLabelText("api_token required sensitive text"))).toContain("A value is required here.");
+    expect(screen.getByText("Not simulated")).toBeTruthy();
+    expect(screen.getByText("/vars/gone: Nothing reads this.")).toBeTruthy();
+  });
+
+  it("waits while Simulate waits", async () => {
+    show({ blocked: true });
+    expect((await screen.findByRole("button", { name: "◌ Simulate step" })).hasAttribute("disabled")).toBe(true);
+  });
+});
diff --git a/frontend/src/routes/editor/simulation/seeds.test.ts b/frontend/src/routes/editor/simulation/seeds.test.ts
new file mode 100644
index 00000000..b7277cc5
--- /dev/null
+++ b/frontend/src/routes/editor/simulation/seeds.test.ts
@@ -0,0 +1,98 @@
+// SPDX-License-Identifier: Apache-2.0
+import { describe, expect, it } from "vitest";
+import type { SeedContract, SeedEntry } from "../../../lib/simulations";
+import type { GraphDoc, NodeType } from "../../../lib/workflows";
+import { choicesOf, collect, hintOf, initialOf, titleOf, typeWords } from "./seeds";
+
+const entry = (pointer: string, over: Partial<SeedEntry> = {}): SeedEntry => ({
+  pointer, types: ["string"], required: true, nullable: false, sensitive: false, prefill: { state: "typed", reason: "no_sample", value: null }, ...over,
+});  // prettier-ignore
+const contract = (...entries: SeedEntry[]): SeedContract => ({ draft_revision: 14, step_id: "id-notify", refused: null, entries });
+
+describe("a step test's values (§7.6; the TestTab and TestOther boards)", () => {
+  it("offers what the step's read allows: a value, null where it's nullable, absent where it's optional", () => {
+    expect(choicesOf(entry("/a"))).toEqual(["value"]);
+    expect(choicesOf(entry("/a", { nullable: true }))).toEqual(["value", "null"]);
+    expect(choicesOf(entry("/a", { required: false }))).toEqual(["value", "absent"]);
+    expect(choicesOf(entry("/a", { required: false, nullable: true }))).toEqual(["value", "null", "absent"]);
+  });
+
+  it("names a value's types in words", () => {
+    expect(typeWords(["string"])).toBe("text");
+    expect(typeWords(["array"])).toBe("list");
+    expect(typeWords(["object", "null"])).toBe("object");
+    expect(typeWords(["integer", "boolean"])).toBe("whole number or true or false");
+    expect(typeWords([])).toBe("any value");
+  });
+
+  it("starts from a step's own sample where it fits, else from nothing, a single choice made", () => {
+    const sampled = entry("/steps/get_site/output/name", { prefill: { state: "prefilled", reason: null, value: "HQ Paris" } });
+    expect(initialOf(sampled)).toEqual({ choice: "value", text: "HQ Paris" });
+    expect(initialOf(entry("/steps/list_aps/output/results", { types: ["array"], prefill: { state: "prefilled", reason: null, value: [{ mac: "5c" }] } }))).toEqual({ choice: "value", text: '[\n  {\n    "mac": "5c"\n  }\n]' });
+    expect(initialOf(entry("/vars/channel", { required: false }))).toEqual({ choice: null, text: "" });
+    expect(initialOf(entry("/vars/channel"))).toEqual({ choice: "value", text: "" });
+  });
+
+  it("says where a value comes from, or why it's typed", () => {
+    const at = (over: Partial<SeedEntry>, pointer = "/steps/get_site/output/name") => hintOf(entry(pointer, over));
+    expect(at({ prefill: { state: "prefilled", reason: null, value: "HQ" } })).toBe("From get_site's sample.");
+    expect(at({ nullable: true, prefill: { state: "prefilled", reason: null, value: "UTC" } })).toBe("From get_site's sample. It can be null, but it can't be left out.");
+    expect(at({ sensitive: true, prefill: { state: "typed", reason: "sensitive", value: null } })).toBe("Sensitive: typed, never prefilled. Kept as a protected value.");
+    expect(at({ prefill: { state: "typed", reason: "no_sample", value: null } })).toBe("Typed: get_site has no sample yet.");
+    expect(at({ prefill: { state: "typed", reason: "not_faithful", value: null } }, "/steps/list_aps/output/results")).toBe("Typed: list_aps's sample was cut or redacted, so it isn't used.");
+    expect(at({ prefill: { state: "typed", reason: "not_in_sample", value: null } })).toBe("Typed: get_site's sample doesn't hold this value.");
+    expect(at({ prefill: { state: "typed", reason: "doesnt_fit", value: null } })).toBe("Typed: get_site's sample doesn't fit what this step reads.");
+    expect(at({ prefill: { state: "typed", reason: "not_step_output", value: null } }, "/item")).toBe("Typed: a loop's item has no sample.");
+    expect(at({ required: false, nullable: true, prefill: { state: "typed", reason: "not_step_output", value: null } }, "/vars/channel")).toBe(
+      "Typed: variables have no sample. Null and absent differ: a default replaces both, but has() is true for null.",
+    );
+    expect(at({ prefill: { state: "typed", reason: "not_step_output", value: null } }, "/trigger/site")).toBe("Typed: the workflow's input has no sample.");
+  });
+
+  it("sends each value as chosen: typed, null, or absent", () => {
+    const c = contract(
+      entry("/steps/get_site/output/name"),
+      entry("/steps/list_aps/output/results", { types: ["array"] }),
+      entry("/vars/channel", { required: false, nullable: true }),
+      entry("/vars/region", { required: false }),
+    );
+    const sent = collect(c, {
+      "/steps/get_site/output/name": { choice: "value", text: "HQ Paris" },
+      "/steps/list_aps/output/results": { choice: "value", text: "[]" },
+      "/vars/channel": { choice: "null", text: "" },
+      "/vars/region": { choice: "absent", text: "" },
+    }, "notify");  // prettier-ignore
+    expect(sent).toEqual({ values: { "/steps/get_site/output/name": "HQ Paris", "/steps/list_aps/output/results": [], "/vars/channel": null }, absent: ["/vars/region"] });
+  });
+
+  it("says what's missing on each value, and what isn't JSON, sending nothing", () => {
+    const c = contract(entry("/steps/get_site/output/name"), entry("/vars/channel", { required: false }), entry("/vars/tz", { nullable: true }), entry("/steps/list_aps/output/results", { types: ["array"] }));
+    const out = collect(c, { "/steps/list_aps/output/results": { choice: "value", text: "[1," } }, "notify");
+    expect(out).toEqual({
+      missing: ["/steps/get_site/output/name", "/vars/channel", "/vars/tz"],
+      problems: {
+        "/steps/get_site/output/name": "Give a value: notify reads it without a default.",
+        "/vars/channel": "Give a value, or choose Absent.",
+        "/vars/tz": "Give a value, or choose Null.",
+        "/steps/list_aps/output/results": "This isn't valid JSON, so it isn't sent.",
+      },
+    });
+  });
+
+  it("titles a value by its schema where it has one, else by its name", () => {
+    const doc = {
+      graph_format: 1,
+      nodes: [{ id: "id-get_site", key: "get_site", type: "mist.sites.get@1" }, { id: "id-each_ap", key: "each_ap", type: "flow.loop@1" }, { id: "id-notify", key: "notify", type: "slack.post@1" }],
+      edges: [{ from: { node: "id-each_ap", port: "body" }, to: { node: "id-notify" } }],
+      settings: { input_schema: { type: "object", properties: { api_token: { type: "string", title: "API token" } } } },
+    } as unknown as GraphDoc;  // prettier-ignore
+    const types = new Map([["mist.sites.get@1", { output_schema: { type: "object", properties: { name: { type: "string", title: "The site's name" } } } } as unknown as NodeType]]);
+    const title = (p: string) => titleOf(p, doc, types, "id-notify");
+    expect(title("/steps/get_site/output/name")).toBe("The site's name");
+    expect(title("/steps/get_site/output/timezone")).toBe("timezone");
+    expect(title("/trigger/api_token")).toBe("API token");
+    expect(title("/vars/channel")).toBe("channel");
+    expect(title("/item")).toBe("each_ap's item");
+    expect(title("/item/mac")).toBe("mac");
+  });
+});
```

- [ ] **Step 2: Run them**

Run: `npx --offline pnpm@12.6.0 exec vitest run src/routes/editor/simulation/seeds.test.ts
src/routes/editor/simulation/TestTab.test.tsx src/routes/editor/simulation/loopBody.test.ts
src/routes/editor/Editor.test.tsx`

Expected: FAIL: `seeds.test.ts` can't import its module; 9 failed and 169 passed: the Test tab shows no fields (no
textbox named "name required text", no radiogroup, no "◌ Simulate step"), so the editor's step test can't find "region
required text".

- [ ] **Step 3: Implement**

Apply:

```diff
diff --git a/frontend/src/routes/editor/simulation/SeedField.tsx b/frontend/src/routes/editor/simulation/SeedField.tsx
new file mode 100644
index 00000000..312200a5
--- /dev/null
+++ b/frontend/src/routes/editor/simulation/SeedField.tsx
@@ -0,0 +1,67 @@
+// SPDX-License-Identifier: Apache-2.0
+// One value a step test sends (4d-1c; the simulation design §7.6; the TestTab and TestOther boards): its title and what
+// it is beside it, its pointer, the choices its read allows, its value (a sensitive one typed and masked, never
+// prefilled), where it comes from or why it's typed, and what's wrong with it.
+import { useId } from "react";
+import { Button } from "../../../components/Button";
+import { controlClass } from "../../../components/Field";
+import { Tag } from "../../../components/Tag";
+import type { SeedEntry } from "../../../lib/simulations";
+import { choicesOf, hintOf, isText, prefilled, typeWords, type Choice, type SeedInput } from "./seeds";
+
+const SAID: Record<Choice, string> = { value: "A value", null: "Null", absent: "Absent: as if it was never set" };
+
+export function SeedField({ entry: e, title, input, error, isNew, onChange }: {
+  entry: SeedEntry; title: string; input: SeedInput; error: string | null; isNew: number | null; onChange: (input: SeedInput) => void;
+}) {  // prettier-ignore
+  const id = useId();
+  const choices = choicesOf(e);
+  const sample = prefilled(e);
+  const fromSample = sample !== null && input.text === sample;
+  // The sample's line only while the value is still the sample's.
+  const hint = fromSample ? hintOf(e) : hintOf({ ...e, prefill: { state: "typed", reason: e.prefill.state === "prefilled" ? null : e.prefill.reason, value: null } });
+  const described = [hint ? `${id}-hint` : null, error ? `${id}-err` : null].filter(Boolean).join(" ") || undefined;
+  const valued = input.choice === "value" || choices.length === 1;
+  const change = (text: string) => onChange({ choice: "value", text });
+  return (
+    <div data-pointer={e.pointer} className="flex flex-col gap-1.5">
+      <label id={`${id}-label`} htmlFor={id} className="text-small font-semibold">
+        {title} <Tag>{e.required ? "required" : "optional"}</Tag>
+        {e.nullable && <> <Tag>nullable</Tag></>}
+        {e.sensitive && <> <Tag>sensitive</Tag></>}
+        {" "}<Tag>{typeWords(e.types)}</Tag>
+        {isNew !== null && <> <Tag>{`new in revision ${isNew}`}</Tag></>}
+      </label>
+      <code className="font-mono text-meta break-all text-muted">{e.pointer}</code>
+      {choices.length > 1 && (
+        <div role="radiogroup" aria-labelledby={`${id}-label`} aria-describedby={valued ? undefined : described} className="flex flex-wrap gap-x-4 gap-y-1 text-small">
+          {choices.map((c) => (
+            <label key={c} className="flex min-h-11 items-center gap-1.5">
+              <input type="radio" name={id} checked={input.choice === c} onChange={() => onChange({ ...input, choice: c })} />
+              {SAID[c]}
+            </label>
+          ))}
+        </div>
+      )}
+      {valued &&
+        (isText(e) || e.sensitive ? (
+          <input
+            id={id} type={e.sensitive ? "password" : "text"} autoComplete="off" value={input.text} aria-invalid={!!error} aria-describedby={described}
+            className={controlClass(!!error)} onChange={(ev) => change(ev.target.value)}
+          />
+        ) : (
+          <textarea
+            id={id} rows={4} spellCheck={false} value={input.text} aria-invalid={!!error} aria-describedby={described}
+            className={`${controlClass(!!error)} py-2 font-mono text-small`} onChange={(ev) => change(ev.target.value)}
+          />
+        ))}
+      {(hint || fromSample) && (
+        <div className="flex flex-wrap items-center gap-2">
+          {hint && <p id={`${id}-hint`} className="text-small text-muted">{hint}</p>}
+          {fromSample && <Button size="sm" aria-label={`Clear ${title}`} onClick={() => change("")}>Clear</Button>}
+        </div>
+      )}
+      {error && <p id={`${id}-err`} className="text-small text-danger">{error}</p>}
+    </div>
+  );
+}
diff --git a/frontend/src/routes/editor/simulation/TestTab.tsx b/frontend/src/routes/editor/simulation/TestTab.tsx
index 7da5ab92..47b3d28b 100644
--- a/frontend/src/routes/editor/simulation/TestTab.tsx
+++ b/frontend/src/routes/editor/simulation/TestTab.tsx
@@ -2,13 +2,18 @@
 // A step's Test tab (4d-1c; the simulation design §7.6; the TestTab, TestResult and TestOther boards), beside Setup and
 // Options, for editors: the values the step reads, its seed contract, read at the draft's saved revision; a step that
 // can't run alone says why, in the server's words, and offers the workflow's simulation instead. A draft with problems
-// is read once they're fixed, as admission reads it.
-import { useQuery } from "@tanstack/react-query";
+// is read once they're fixed, as admission reads it. "◌ Simulate step" saves first; when the save moved the draft, the
+// contract is read again and shown before anything is sent: a new revision is never paired with an older contract.
+import { keepPreviousData, useQuery } from "@tanstack/react-query";
+import { useState } from "react";
 import { Button } from "../../../components/Button";
 import { ApiError } from "../../../lib/client";
-import { seedContractQuery, type Frozen } from "../../../lib/simulations";
+import { sameId } from "../../../lib/graph";
+import { freeze, seedContractQuery, type Frozen } from "../../../lib/simulations";
 import type { GraphDoc, GraphNode, NodeType } from "../../../lib/workflows";
 import { Refusal } from "./Refusal";
+import { SeedField } from "./SeedField";
+import { collect, initialOf, titleOf, type SeedInput } from "./seeds";
 import type { SimulationSession } from "./useSimulation";
 
 export interface TestTabProps {
@@ -27,8 +32,16 @@ export interface TestTabProps {
   onShowProblems: () => void;
 }
 
-export function TestTab({ tenantId, workflowId, node, doc, revision, onSimulateWorkflow, onGoTo, onShowProblems }: TestTabProps) {
-  const contract = useQuery(seedContractQuery(tenantId, workflowId, node.id, revision));
+const missingWords = (n: number) => `Not simulated: ${n} ${n === 1 ? "value is" : "values are"} missing.`;
+const unreadWords = (n: number) => `Not simulated: ${n} ${n === 1 ? "value isn't" : "values aren't"} valid JSON.`;
+
+export function TestTab(props: TestTabProps) {
+  const { tenantId, workflowId, node, doc, types, revision, session, blocked, onSave, onStart, onSimulateWorkflow, onGoTo, onShowProblems } = props;
+  // The contract at the saved revision; while a newer one is read, the older stays shown (it's never sent with it).
+  const contract = useQuery({ ...seedContractQuery(tenantId, workflowId, node.id, revision), placeholderData: keepPreviousData });
+  const [inputs, setInputs] = useState<Record<string, SeedInput>>({});
+  const [checked, setChecked] = useState<{ missing: string[]; problems: Record<string, string> } | null>(null);
+  const [moved, setMoved] = useState<{ to: number; before: Set<string> } | null>(null); // a save moved the draft
   if (contract.isPending) return <p className="text-small text-muted">Reading the values it reads…</p>;
   if (contract.isError) {
     const e = contract.error;
@@ -56,18 +69,77 @@ export function TestTab({ tenantId, workflowId, node, doc, revision, onSimulateW
       </>
     );
   }
+  // The values the server refused for this step's test, on their fields; one with no field, above them.
+  const local = session.local;
+  const refused = local.kind === "refused" && local.frozen.body.target && sameId(local.frozen.body.target.step_id, node.id) ? local.error : null;
+  const seedProblems = refused && Array.isArray((refused.body as { problems?: unknown } | null)?.problems)
+    ? ((refused.body as { problems: { pointer: string; message: string }[] }).problems)
+    : null;  // prettier-ignore
+  const pointers = new Set(c.entries.map((e) => e.pointer));
+  const added = moved && moved.to === c.draft_revision ? c.entries.filter((e) => !moved.before.has(e.pointer)).length : 0;
+  const errorOf = (pointer: string) =>
+    checked?.problems[pointer] ?? seedProblems?.find((p) => p.pointer === pointer)?.message ?? null;
+  const missing = checked ? checked.missing.filter((p) => p in checked.problems).length : 0;
+  const unread = checked ? Object.keys(checked.problems).length - missing : 0;
+
+  async function simulate() {
+    setChecked(null);
+    const saved = await onSave();
+    if (saved === null) return;
+    if (saved !== c.draft_revision) {
+      setMoved({ to: saved, before: pointers });
+      return;
+    }
+    const out = collect(c, inputs, node.key);
+    if ("problems" in out) return setChecked(out);
+    setMoved(null);
+    onStart(freeze(saved, { target: { step_id: node.id, values: out.values, absent: out.absent } }));
+  }
+
   return (
     <>
       <p className="text-small">
         Runs <span className="font-mono">{node.key}</span> alone, with these values in place of what the steps before it would give.
         Nothing is sent.
       </p>
-      <section aria-labelledby="test-values" className="flex flex-col gap-3">
+      {moved && moved.to === c.draft_revision && (
+        <p role="status" className="text-small">
+          {`Saving moved the draft to revision ${moved.to}${added > 0 ? `, and ${node.key} now reads ${added === 1 ? "one more value" : `${added} more values`}` : ""}. Check the values, then simulate.`}
+        </p>
+      )}
+      {refused && !seedProblems && (
+        <Refusal error={refused} doc={doc} onGoTo={onGoTo} onShowProblems={onShowProblems} onTryAgain={() => void session.checkAgain()} />
+      )}
+      {seedProblems && seedProblems.some((p) => !pointers.has(p.pointer)) && (
+        <div className="flex flex-col gap-1 text-small">
+          <p className="font-semibold">Not simulated</p>
+          {seedProblems.filter((p) => !pointers.has(p.pointer)).map((p) => <p key={p.pointer}>{`${p.pointer}: ${p.message}`}</p>)}
+        </div>
+      )}
+      {(missing > 0 || unread > 0) && (
+        <p role="alert" className="text-small text-danger">{missing > 0 ? missingWords(missing) : unreadWords(unread)}</p>
+      )}
+      <section aria-labelledby="test-values" className="flex flex-col gap-4">
         <div className="flex items-baseline justify-between gap-3">
           <h3 id="test-values" className="text-small font-semibold">Values it reads</h3>
           <span className="text-meta text-muted">{`revision ${c.draft_revision}`}</span>
         </div>
+        {c.entries.length === 0 && <p className="text-small text-muted">It reads no values from before it.</p>}
+        {c.entries.map((e) => (
+          <SeedField
+            key={e.pointer} entry={e} title={titleOf(e.pointer, doc, types, node.id)} input={inputs[e.pointer] ?? initialOf(e)}
+            error={errorOf(e.pointer)} isNew={moved && moved.to === c.draft_revision && !moved.before.has(e.pointer) ? moved.to : null}
+            onChange={(input) => {
+              setInputs({ ...inputs, [e.pointer]: input });
+              if (checked?.problems[e.pointer]) setChecked({ ...checked, problems: Object.fromEntries(Object.entries(checked.problems).filter(([p]) => p !== e.pointer)) });
+            }}
+          />
+        ))}
       </section>
+      <div className="flex flex-col items-start gap-1.5">
+        <Button variant="simulate" size="md" disabled={blocked} onClick={() => void simulate()}>◌ Simulate step</Button>
+        <p className="text-small text-muted">{`Each value is checked against what ${node.key} reads.`}</p>
+      </div>
     </>
   );
 }
diff --git a/frontend/src/routes/editor/simulation/loopBody.ts b/frontend/src/routes/editor/simulation/loopBody.ts
index 59f0e8f5..8553e990 100644
--- a/frontend/src/routes/editor/simulation/loopBody.ts
+++ b/frontend/src/routes/editor/simulation/loopBody.ts
@@ -10,7 +10,7 @@ const LOOP = "flow.loop@";
 export const PAGE = 4;
 
 /** Every step reachable from a loop's `body` port, as the engine reads a loop's region (engine/graph/structure.py). */
-function regionOf(doc: GraphDoc, loopId: string): Set<string> {
+export function regionOf(doc: GraphDoc, loopId: string): Set<string> {
   const edges = edgesOf(doc);
   const region = new Set<string>();
   const queue = edges.filter((e) => sameId(e.from.node, loopId) && portOf(e) === "body").map((e) => idKey(e.to.node));
diff --git a/frontend/src/routes/editor/simulation/seeds.ts b/frontend/src/routes/editor/simulation/seeds.ts
new file mode 100644
index 00000000..df6bd620
--- /dev/null
+++ b/frontend/src/routes/editor/simulation/seeds.ts
@@ -0,0 +1,129 @@
+// SPDX-License-Identifier: Apache-2.0
+// A step test's values (4d-1c; the simulation design §7.6, D-s2; the TestTab and TestOther boards): what the step's
+// seed contract allows for each (a value; null where its read is nullable; absent where it's optional), where a value
+// comes from (its step's own sample, as the server decided) or why it's typed, its title, and the values sent. Text is
+// sent as typed; anything else is read as JSON, as the draft's values are. An empty value is a value not given.
+import { idKey, nodesOf } from "../../../lib/graph";
+import { parseJson } from "../../../lib/config";
+import type { SeedContract, SeedEntry } from "../../../lib/simulations";
+import type { GraphDoc, NodeType } from "../../../lib/workflows";
+import { regionOf } from "./loopBody";
+
+export type Choice = "value" | "null" | "absent";
+/** A value as the form holds it: what's chosen (null: nothing yet) and what's typed. */
+export interface SeedInput {
+  choice: Choice | null;
+  text: string;
+}
+/** The values to send, or each value's problem: those missing apart from those that don't read. */
+export type Collected = { values: Record<string, unknown>; absent: string[] } | { missing: string[]; problems: Record<string, string> };
+
+export function choicesOf(e: SeedEntry): Choice[] {
+  if (e.required) return e.nullable ? ["value", "null"] : ["value"];
+  return e.nullable ? ["value", "null", "absent"] : ["value", "absent"];
+}
+
+const WORDS: Record<string, string> = {
+  string: "text", integer: "whole number", number: "number", boolean: "true or false", object: "object", array: "list",
+};  // prettier-ignore
+export function typeWords(types: string[]): string {
+  const said = types.filter((t) => t !== "null").map((t) => WORDS[t] ?? t);
+  return said.length > 0 ? said.join(" or ") : "any value";
+}
+
+/** Typed as text (sent as typed), or as JSON. */
+export const isText = (e: SeedEntry) => e.types.length > 0 && e.types.every((t) => t === "string" || t === "null");
+const textOf = (e: SeedEntry, v: unknown) => (isText(e) && typeof v === "string" ? v : JSON.stringify(v, null, 2));
+
+export function initialOf(e: SeedEntry): SeedInput {
+  if (e.prefill.state === "prefilled") return { choice: "value", text: textOf(e, e.prefill.value) };
+  return { choice: choicesOf(e).length === 1 ? "value" : null, text: "" };
+}
+
+/** The prefill's text, while the value is still the sample's. */
+export const prefilled = (e: SeedEntry): string | null => (e.prefill.state === "prefilled" ? textOf(e, e.prefill.value) : null);
+
+const segments = (pointer: string) => pointer.split("/").slice(1).map((s) => s.replace(/~1/g, "/").replace(/~0/g, "~"));
+
+/** Where a value comes from, or why it's typed (D-s2's reasons), and what null and absent mean for it. */
+export function hintOf(e: SeedEntry): string {
+  const [root, step] = segments(e.pointer);
+  const owner = root === "steps" ? step : "its step";
+  let from = "";
+  if (e.prefill.state === "prefilled") from = `From ${owner}'s sample.`;
+  else if (e.prefill.reason === "sensitive") from = "Sensitive: typed, never prefilled. Kept as a protected value.";
+  else if (e.prefill.reason === "no_sample") from = `Typed: ${owner} has no sample yet.`;
+  else if (e.prefill.reason === "not_faithful") from = `Typed: ${owner}'s sample was cut or redacted, so it isn't used.`;
+  else if (e.prefill.reason === "not_in_sample") from = `Typed: ${owner}'s sample doesn't hold this value.`;
+  else if (e.prefill.reason === "doesnt_fit") from = `Typed: ${owner}'s sample doesn't fit what this step reads.`;
+  else if (e.prefill.reason === "not_step_output") {
+    from =
+      root === "vars" ? "Typed: variables have no sample."
+      : root === "item" || root === "index" ? "Typed: a loop's item has no sample."
+      : root === "trigger" ? "Typed: the workflow's input has no sample."
+      : "Typed: only a step's output has a sample.";  // prettier-ignore
+  }
+  const nulls =
+    e.required && e.nullable ? "It can be null, but it can't be left out."
+    : !e.required && e.nullable ? "Null and absent differ: a default replaces both, but has() is true for null."
+    : "";  // prettier-ignore
+  return [from, nulls].filter(Boolean).join(" ");
+}
+
+/** A schema's title at a path of property names, else null. */
+function titleIn(schema: unknown, path: string[]): string | null {
+  let at: unknown = schema;
+  for (const p of path) {
+    const props = (at as { properties?: Record<string, unknown> } | undefined)?.properties;
+    at = props?.[p] ?? (/^\d+$/.test(p) ? (at as { items?: unknown } | undefined)?.items : undefined);
+    if (at === undefined) return null;
+  }
+  const title = (at as { title?: unknown } | undefined)?.title;
+  return typeof title === "string" ? title : null;
+}
+
+/** A value's title: its schema's (the workflow's input, a step's output) where it has one, a loop's item by its loop,
+ * else its last name. `stepId`: the step tested, whose loop an item is. */
+export function titleOf(pointer: string, doc: GraphDoc, types: Map<string, NodeType>, stepId: string): string {
+  const [root, ...rest] = segments(pointer);
+  const last = rest.at(-1) ?? root ?? pointer;
+  if (root === "trigger") return titleIn(doc.settings?.input_schema, rest) ?? last;
+  if (root === "steps" && rest[1] === "output") {
+    const step = nodesOf(doc).find((n) => n.key === rest[0]);
+    if (rest.length === 2) return `${rest[0]}'s output`;
+    return titleIn(step ? types.get(step.type)?.output_schema : undefined, rest.slice(2)) ?? last;
+  }
+  if ((root === "item" || root === "index") && rest.length === 0) {
+    const loops = nodesOf(doc).filter((n) => n.type.startsWith("flow.loop@")).map((n) => ({ n, region: regionOf(doc, n.id) }));
+    const mine = loops.filter((l) => l.region.has(idKey(stepId))).sort((a, b) => a.region.size - b.region.size)[0];
+    return mine ? `${mine.n.key}'s ${root}` : root;
+  }
+  return last;
+}
+
+/** The values to send, or what's missing on each and what doesn't read, sending nothing. */
+export function collect(contract: SeedContract, inputs: Record<string, SeedInput>, stepKey: string): Collected {
+  const values: Record<string, unknown> = {};
+  const absent: string[] = [];
+  const problems: Record<string, string> = {};
+  const missing: string[] = [];
+  for (const e of contract.entries) {
+    const input = inputs[e.pointer] ?? initialOf(e);
+    const choice = input.choice ?? (choicesOf(e).length === 1 ? "value" : null);
+    if (choice === "null") values[e.pointer] = null;
+    else if (choice === "absent") absent.push(e.pointer);
+    else if (choice === null || input.text === "") {
+      missing.push(e.pointer);
+      problems[e.pointer] =
+        e.required && !e.nullable ? `Give a value: ${stepKey} reads it without a default.`
+        : e.required ? "Give a value, or choose Null."
+        : "Give a value, or choose Absent.";  // prettier-ignore
+    } else if (isText(e)) values[e.pointer] = input.text;
+    else {
+      const read = parseJson(input.text);
+      if ("problem" in read) problems[e.pointer] = read.problem.replace("isn't saved", "isn't sent");
+      else values[e.pointer] = read.value;
+    }
+  }
+  return Object.keys(problems).length > 0 ? { missing, problems } : { values, absent };
+}
```

- [ ] **Step 4: Run them again**

Run: the same command.

Expected: PASS, 185 passed.

- [ ] **Step 5: Static checks**

Run: the two of "How to run things". Expected: no output.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/routes/editor
git commit -m "feat(editor): a step's values as fields, prefilled where its sample fits, and Simulate step (4d-1c)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 11: A step test's result

**Spec:** §7.3 (a step test's banner), §7.6 (the result); the TestResult board.

**Files:**
- Create: `frontend/src/routes/editor/simulation/StepResult.tsx`,
  `frontend/src/routes/editor/simulation/StepResult.test.tsx`
- Create: `frontend/src/routes/editor/simulation/Failure.tsx`, `frontend/src/routes/editor/simulation/UsedValues.tsx`
- Modify: `frontend/src/routes/editor/simulation/lifecycle.ts` (`lineOf`), `SimulationPanel.tsx` (uses it),
  `results.ts` (`field`, `originTag` exported), `ResultBar.tsx` (`target`), `SimulationResult.tsx`, `TestTab.tsx`, and
  the tests of `ResultBar`, `SimulationResult` and `TestTab`
- Modify: `frontend/src/routes/editor/Editor.tsx`, `frontend/src/routes/editor/Editor.test.tsx`

**Interfaces:**
- Consumes: `tagsOf`, `ORIGIN` (Task 6); `StatusChip` (Task 5); `SimBanner` (Task 3).
- Produces:
  - `lineOf(session): string | null` (moved out of `SimulationPanel`).
  - `field(value, key)`, `originTag(origin): SimTag` (`results.ts`).
  - `Failure({ final, max })`; `UsedValues({ state })`, `Section({ title, children })`, `Pairs({ pairs, tag? })`,
    `shown(value)`.
  - `StepResult({ session, stepKey, attemptsOf })`.
  - `ResultBar`'s `target: string | null` (a step test's key); `TestTab`'s `attemptsOf`.

Once sent, the Test tab shows "Result · <key>": where it is while it runs, then the banner, its status and origin,
"attempt N of M · revision R · run <id>", a failure's code and message with its attempts and "Nothing was sent", the
port a branch took ("Takes → true.", ruling 16) or what a step set, the values used, each "seeded" and sensitive ones
"redacted" (ruling 15), and its output. On the canvas, only the step tested carries a result, and the bar says "Step
test: <key>. Only this step ran. Nothing was sent."; the panel says the same, with "Values used" in place of the input.

- [ ] **Step 1: Write the failing tests**

Apply:

```diff
diff --git a/frontend/src/routes/editor/Editor.test.tsx b/frontend/src/routes/editor/Editor.test.tsx
index 5f8d1c27..8bc02ca5 100644
--- a/frontend/src/routes/editor/Editor.test.tsx
+++ b/frontend/src/routes/editor/Editor.test.tsx
@@ -2190,6 +2190,21 @@ describe("Simulate step", () => {
     expect(screen.getByRole("complementary", { name: "transform" })).toBeTruthy(); // the drawer stays: its result comes in the tab
   });
 
+  it("shows a step test's result on the canvas as the step alone (§7.3; the TestResult board)", async () => {
+    const request = { id: "r1", workflow_id: "w1", version_id: null, draft_snapshot_id: "s1", draft_revision: 1, target_step_id: "id-transform", mode: "simulate", source: "manual", status: "started", reason: null, queued_at: "2026-10-15T10:42:05Z", ended_at: null, admission_checks: [] };
+    const run = { status: "succeeded", queued_at: null, started_at: "2026-10-15T10:42:05Z", ended_at: "2026-10-15T10:42:06Z", error: null, iterations: 0 };
+    answers.set(`GET ${BASE}`, () => json({ ...WORKFLOW, draft: draftWith("transform", "after") }));
+    answers.set(`GET ${BASE}/draft/simulations`, () => json([request]));
+    answers.set(`GET ${BASE}/draft/simulations/r1`, () => json({ request, run, cancel_requested: false, read_back: "kept", input: null, seeds: {} }));
+    answers.set(`GET ${BASE}/draft/simulations/r1/steps`, () => json({ given: "seeded", steps: [
+      { step_id: "id-transform", key: "transform", type: "flow.transform@1", origin: "evaluated", instances: 1, statuses: { succeeded: 1 }, ports: {}, final: { attempt: 1, status: "succeeded" } },
+    ] }));  // prettier-ignore
+    await show();
+    await vi.waitFor(() => expect(steps().dataset.simulated).toBe(JSON.stringify([["id-transform", ["succeeded", "evaluated"]]])));
+    expect(steps().dataset.startTags).toBe(""); // the input wasn't given: the step's values were
+    expect(screen.getByText("Step test: transform.").parentElement?.textContent).toBe("Step test: transform. Only this step ran. Nothing was sent.");
+  });
+
   it("isn't offered to a viewer", async () => {
     role = "viewer";
     await show();
diff --git a/frontend/src/routes/editor/simulation/ResultBar.test.tsx b/frontend/src/routes/editor/simulation/ResultBar.test.tsx
index cb39389a..5576d5f9 100644
--- a/frontend/src/routes/editor/simulation/ResultBar.test.tsx
+++ b/frontend/src/routes/editor/simulation/ResultBar.test.tsx
@@ -5,7 +5,7 @@ import { describe, expect, it, vi } from "vitest";
 import { ResultBar } from "./ResultBar";
 
 const props = (over: Partial<Parameters<typeof ResultBar>[0]> = {}) => ({
-  phase: "succeeded" as const, revision: 14, endedAt: "2026-10-15T10:42:19Z", notWaited: false, hidden: false, stale: null,
+  phase: "succeeded" as const, revision: 14, endedAt: "2026-10-15T10:42:19Z", notWaited: false, hidden: false, stale: null, target: null,
   onHide: vi.fn(), onShow: vi.fn(), onPanel: vi.fn(), onCancel: vi.fn(), ...over,
 });  // prettier-ignore
 
@@ -37,6 +37,12 @@ describe("the canvas's bar for a simulation (§7.3; the ResultCanvas and Running
     expect(note.className).toMatch(/border-warn-line/);
   });
 
+  it("says a step test ran the step alone (§7.3; the TestResult board)", () => {
+    render(<ResultBar {...props({ target: "notify" })} />);
+    expect(screen.getByText("Step test: notify.").parentElement?.textContent).toBe("Step test: notify. Only this step ran. Nothing was sent.");
+    expect(screen.queryByText("Simulated.")).toBeNull();
+  });
+
   it("once hidden, is one bar that brings the result back", async () => {
     const p = props({ hidden: true });
     render(<ResultBar {...p} />);
diff --git a/frontend/src/routes/editor/simulation/SimulationResult.test.tsx b/frontend/src/routes/editor/simulation/SimulationResult.test.tsx
index 8bc14448..f8f7d49e 100644
--- a/frontend/src/routes/editor/simulation/SimulationResult.test.tsx
+++ b/frontend/src/routes/editor/simulation/SimulationResult.test.tsx
@@ -166,6 +166,14 @@ describe("a result before the person's edits, and what failed (§7.7; the Stale
     expect(screen.getByText("Production runs are off in this deployment.")).toBeTruthy();
   });
 
+  it("for a step test, says it ran the step alone, and shows the values used, not an input", () => {
+    const s = session({ request: { target_step_id: "id-get_site" }, state: { input: null, seeds: { "/vars/region": "emea" } }, steps: [step("get_site")] });
+    show(s);
+    expect(screen.getByText("Step test: get_site.").parentElement?.textContent).toBe("Step test: get_site. Only this step ran. Nothing was sent.");
+    expect(screen.queryByRole("region", { name: "Input used" })).toBeNull();
+    expect(within(section("Values used")).getByText("emea")).toBeTruthy();
+  });
+
   it("pages a loop's iterations over the draft it ran, whatever the draft is now", async () => {
     show(session(), { doc: { ...DOC, edges: [] }, ran: DOC });
     await userEvent.click(screen.getByRole("button", { name: "Iterations of each_ap" }));
diff --git a/frontend/src/routes/editor/simulation/StepResult.test.tsx b/frontend/src/routes/editor/simulation/StepResult.test.tsx
new file mode 100644
index 00000000..9b062c17
--- /dev/null
+++ b/frontend/src/routes/editor/simulation/StepResult.test.tsx
@@ -0,0 +1,71 @@
+// SPDX-License-Identifier: Apache-2.0
+import { render, screen, within } from "@testing-library/react";
+import { describe, expect, it, vi } from "vitest";
+import type { SimulationRequest, SimulationState, StepSummary } from "../../../lib/simulations";
+import { StepResult } from "./StepResult";
+import type { SimulationSession } from "./useSimulation";
+
+const ID = "7c1e9a40-3b2d-4e5f-9a1b-2c3d4e5f6a7b";
+const request = (over: Partial<SimulationRequest> = {}): SimulationRequest => ({
+  id: ID, workflow_id: "w1", draft_snapshot_id: "s1", draft_revision: 14, target_step_id: "id-notify", mode: "simulate",
+  source: "manual", status: "started", reason: null, queued_at: "2026-10-15T10:42:05Z", ended_at: null, admission_checks: [], ...over,
+});  // prettier-ignore
+const summary = (over: Partial<StepSummary> = {}): StepSummary => ({
+  step_id: "id-notify", key: "notify", type: "slack.post@1", origin: "fixture_not_sent", instances: 1, statuses: { succeeded: 1 }, ports: {},
+  final: { attempt: 1, status: "succeeded", output: { ok: true, channel: "C0FIXTURE" }, effect: null }, ...over,
+});  // prettier-ignore
+
+function session(phase: SimulationSession["phase"], s: StepSummary | null, state: Partial<SimulationState> = {}): SimulationSession {
+  const full: SimulationState = {
+    request: request(), run: { status: "succeeded", queued_at: null, started_at: "2026-10-15T10:42:05Z", ended_at: "2026-10-15T10:42:06Z", error: null, iterations: 0 },
+    cancel_requested: false, read_back: "kept", input: null, seeds: { "/steps/get_site/output/name": "HQ Paris", "/trigger/api_token": "[redacted]" }, ...state,
+  };  // prettier-ignore
+  return {
+    local: { kind: "admitted", frozen: null, request: full.request, latest: false }, state: full, steps: s ? { given: "seeded", steps: [s] } : null,
+    phase, busy: false, readFailed: false, asOf: null, start: vi.fn(), checkAgain: vi.fn(), cancel: vi.fn(), readAgain: vi.fn(),
+  };  // prettier-ignore
+}
+const show = (s: SimulationSession) => render(<StepResult session={s} stepKey="notify" attemptsOf={() => 3} />);
+
+describe("a step test's result in its Test tab (§7.6; the TestResult board)", () => {
+  it("says what it proves, its status and origin, its attempt, revision and run", () => {
+    show(session("succeeded", summary()));
+    const result = screen.getByRole("region", { name: "Result · notify" });
+    expect(within(result).getByText("Simulated.").parentElement?.textContent).toBe("Simulated. Nothing was sent. Results don't prove the live call will succeed.");
+    expect(within(result).getByText("Succeeded")).toBeTruthy();
+    expect(within(result).getByText("fixture · not sent")).toBeTruthy();
+    expect(within(result).getByText("attempt 1 of 3 · revision 14 · run 7c1e9a40")).toBeTruthy();
+  });
+
+  it("shows the values used, each seeded, sensitive ones redacted, and the output", () => {
+    show(session("succeeded", summary()));
+    const used = screen.getByRole("region", { name: "Values used" });
+    const pairs = within(used).getAllByRole("term").map((t) => `${t.textContent}=${t.nextElementSibling?.textContent}`);
+    expect(pairs).toEqual(["/steps/get_site/output/name=HQ Paris seeded", "/trigger/api_token=redacted seeded"]);
+    expect(screen.getByRole("region", { name: "Output" }).querySelector("pre")?.textContent).toBe('{\n  "ok": true,\n  "channel": "C0FIXTURE"\n}');
+  });
+
+  it("says the port a branch took, and what a step set", () => {
+    show(session("succeeded", summary({ type: "flow.if@1", origin: "evaluated", final: { attempt: 1, status: "succeeded", output: {}, effect: { port: "true" } } })));
+    expect(screen.getByText("Takes → true.")).toBeTruthy();
+    expect(screen.queryByRole("region", { name: "Output" })).toBeNull(); // nothing besides the port
+  });
+
+  it("lists what a step set, sensitive values redacted", () => {
+    const set = { attempt: 1, status: "succeeded", output: {}, effect: { assignments: { channel: "#ops-alerts", webhook_key: "[redacted]" } } };
+    show(session("succeeded", summary({ type: "flow.set_variables@1", origin: "evaluated", final: set })));
+    const sets = screen.getByRole("region", { name: "Sets" });
+    expect(within(sets).getAllByRole("term").map((t) => `${t.textContent}=${t.nextElementSibling?.textContent}`)).toEqual(['channel="#ops-alerts"', "webhook_key=redacted"]);
+  });
+
+  it("says a failure's code and message, its attempts, and that nothing was sent", () => {
+    const failed = { attempt: 3, status: "failed", output: null, error: { code: "invalid_blocks", message: "Block 2 has no text." } };
+    show(session("failed", summary({ statuses: { failed: 1 }, final: failed })));
+    expect(screen.getByText("invalid_blocks").parentElement?.textContent).toBe("invalid_blocks Block 2 has no text. 3 attempts, the configured retries. Nothing was sent.");
+  });
+
+  it("says where it is while it runs", () => {
+    show(session("queued", null, { run: null }));
+    expect(within(screen.getByRole("region", { name: "Result · notify" })).getByText("Waiting for a free run slot.")).toBeTruthy();
+  });
+});
diff --git a/frontend/src/routes/editor/simulation/TestTab.test.tsx b/frontend/src/routes/editor/simulation/TestTab.test.tsx
index e6e94df7..a08a01dd 100644
--- a/frontend/src/routes/editor/simulation/TestTab.test.tsx
+++ b/frontend/src/routes/editor/simulation/TestTab.test.tsx
@@ -41,7 +41,7 @@ function show(over: Partial<Parameters<typeof TestTab>[0]> = {}) {
   const props = {
     tenantId: "t1", workflowId: "w1", node: NOTIFY, doc: DOC, types: new Map<string, NodeType>(), revision: 14, session: idle(),
     blocked: false, onSave: vi.fn(() => Promise.resolve(14)), onStart: vi.fn(), onSimulateWorkflow: vi.fn(), onGoTo: vi.fn(),
-    onShowProblems: vi.fn(), ...over,
+    onShowProblems: vi.fn(), attemptsOf: () => 3, ...over,
   };  // prettier-ignore
   const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
   const view = render(
@@ -193,6 +193,15 @@ describe("the values a step test sends (§7.6; the TestTab and TestOther boards)
     expect(screen.getByText("/vars/gone: Nothing reads this.")).toBeTruthy();
   });
 
+  it("shows its own result once sent, below the values", async () => {
+    const request = { id: "r1", workflow_id: "w1", draft_snapshot_id: "s1", draft_revision: 14, target_step_id: "id-notify", mode: "simulate" as const,
+      source: "manual", status: "queued" as const, reason: null, queued_at: "2026-10-15T10:42:05Z", ended_at: null, admission_checks: [] };  // prettier-ignore
+    const state = { request, run: null, cancel_requested: false, read_back: "kept" as const, input: null, seeds: {} };
+    show({ session: { ...idle(), local: { kind: "admitted", frozen: null, request, latest: false }, state, phase: "queued", busy: true } });
+    const result = await screen.findByRole("region", { name: "Result · notify" });
+    expect(within(result).getByText("Waiting for a free run slot.")).toBeTruthy();
+  });
+
   it("waits while Simulate waits", async () => {
     show({ blocked: true });
     expect((await screen.findByRole("button", { name: "◌ Simulate step" })).hasAttribute("disabled")).toBe(true);
```

- [ ] **Step 2: Run them**

Run: `npx --offline pnpm@12.6.0 exec vitest run src/routes/editor/simulation src/routes/editor/Editor.test.tsx`

Expected: FAIL: `StepResult.test.tsx` can't import its module; 4 failed and 254 passed: no "Step test: <key>." on the
bar, in the panel or on the editor's canvas, and no "Result · notify" in the Test tab.

- [ ] **Step 3: Implement**

Apply:

```diff
diff --git a/frontend/src/routes/editor/Editor.tsx b/frontend/src/routes/editor/Editor.tsx
index 6c5a9742..2688de59 100644
--- a/frontend/src/routes/editor/Editor.tsx
+++ b/frontend/src/routes/editor/Editor.tsx
@@ -1334,6 +1334,7 @@ function Editor({
           endedAt={simulation.state.run?.ended_at ?? simulation.state.request.ended_at}
           notWaited={(simulation.steps?.steps ?? []).some((s) => s.origin === "evaluated_not_waited")}
           stale={stale}
+          target={simulation.state.request.target_step_id ? (findNode(doc, simulation.state.request.target_step_id)?.key ?? simulation.steps?.steps[0]?.key ?? "the step") : null}
           hidden={!resultShown}
           onHide={() => setHiddenFor(simulationId)}
           onShow={() => setHiddenFor(null)}
@@ -1410,7 +1411,7 @@ function Editor({
                   onSave={() => new Promise((resolve) => whenSettled("simulate", () => void saveFirst().then(resolve)))}
                   onStart={(frozen) => void simulation.start(frozen)}
                   onSimulateWorkflow={() => whenSettled("simulate", () => void simulate())}
-                  onGoTo={(id) => focus(item.node(id))} onShowProblems={() => setSide({ kind: "problems" })}
+                  onGoTo={(id) => focus(item.node(id))} onShowProblems={() => setSide({ kind: "problems" })} attemptsOf={attemptsOf}
                 />
               ) : undefined
             }
diff --git a/frontend/src/routes/editor/simulation/Failure.tsx b/frontend/src/routes/editor/simulation/Failure.tsx
new file mode 100644
index 00000000..51e35ae9
--- /dev/null
+++ b/frontend/src/routes/editor/simulation/Failure.tsx
@@ -0,0 +1,21 @@
+// SPDX-License-Identifier: Apache-2.0
+// A simulated step that failed (4d-1c; the simulation design §7.7; the Refusals and TestResult boards): its code and
+// message as the server wrote them, its attempts (its retries said when it used them all), and that nothing was sent.
+import { field } from "./results";
+
+const attempts = (n: number, max: number | null) => (n === 1 ? "1 attempt." : n === max ? `${n} attempts, the configured retries.` : `${n} attempts.`);
+
+/** `final`: a step's final attempt (the run API's step); `max`: its attempts, its own or its type's. */
+export function Failure({ final, max }: { final: unknown; max: number | null }) {
+  const error = field(final, "error");
+  const code = field(error, "code");
+  if (field(final, "status") !== "failed" || typeof code !== "string") return null;
+  const message = field(error, "message");
+  const attempt = field(final, "attempt");
+  return (
+    <p className="basis-full text-small text-muted">
+      <span className="font-mono text-ink">{code}</span>
+      {` ${typeof message === "string" ? message : ""} ${attempts(typeof attempt === "number" ? attempt : 1, max)} Nothing was sent.`}
+    </p>
+  );
+}
diff --git a/frontend/src/routes/editor/simulation/ResultBar.tsx b/frontend/src/routes/editor/simulation/ResultBar.tsx
index 2cf06069..eea27966 100644
--- a/frontend/src/routes/editor/simulation/ResultBar.tsx
+++ b/frontend/src/routes/editor/simulation/ResultBar.tsx
@@ -13,8 +13,10 @@ import { STALE, staleWords, type Stale } from "./stale";
 
 const BAR = "flex flex-wrap items-center gap-3 border-b border-line bg-surface-2 px-5 py-2.5 text-small";
 
-export function ResultBar({ phase, revision, endedAt, notWaited, stale, hidden, onHide, onShow, onPanel, onCancel }: {
-  phase: Phase; revision: number; endedAt: string | null; notWaited: boolean; stale: Stale | null; hidden: boolean;
+export function ResultBar({ phase, revision, endedAt, notWaited, stale, target, hidden, onHide, onShow, onPanel, onCancel }: {
+  phase: Phase; revision: number; endedAt: string | null; notWaited: boolean; stale: Stale | null;
+  target: string | null; // a step test's step, by its key: it ran alone
+  hidden: boolean;
   onHide: () => void; onShow: () => void; onPanel: () => void; onCancel: () => void;
 }) {  // prettier-ignore
   if (!ENDED.has(phase)) {
@@ -37,7 +39,11 @@ export function ResultBar({ phase, revision, endedAt, notWaited, stale, hidden,
   return (
     <div className="border-b border-line bg-surface px-5 py-2.5">
       <SimBanner role="status">
-        <p><strong>Simulated.</strong> Nothing was sent. Results don&apos;t prove the live call will succeed.</p>
+        {target ? (
+          <p><strong>{`Step test: ${target}.`}</strong> Only this step ran. Nothing was sent.</p>
+        ) : (
+          <p><strong>Simulated.</strong> Nothing was sent. Results don&apos;t prove the live call will succeed.</p>
+        )}
         {notWaited && <p>Flow delays and wait-until weren&apos;t waited; the simulation clock wasn&apos;t advanced.</p>}
         {stale && (
           <p className={STALE}>
diff --git a/frontend/src/routes/editor/simulation/SimulationPanel.tsx b/frontend/src/routes/editor/simulation/SimulationPanel.tsx
index cb105d9a..27cea311 100644
--- a/frontend/src/routes/editor/simulation/SimulationPanel.tsx
+++ b/frontend/src/routes/editor/simulation/SimulationPanel.tsx
@@ -8,13 +8,9 @@ import { Button } from "../../../components/Button";
 import { ENDED } from "../../../lib/simulations";
 import { SIDE } from "../side";
 import { SimulatedChip, StatusChip } from "./chips";
-import { clock, duration, endedWhat, runId, stepsEnded } from "./lifecycle";
+import { clock, duration, endedWhat, lineOf, runId } from "./lifecycle";
 import type { SimulationSession } from "./useSimulation";
 
-const LOST =
-  "It isn't known whether the simulation started: its answer was lost. Checking sends the same request again: while the " +
-  "first request is still kept, it can't start a second time.";
-
 export function SimulationPanel({ session, onSimulateAgain, onClose, children }: {
   session: SimulationSession; onSimulateAgain?: () => void; onClose: () => void; children?: ReactNode;
 }) {  // prettier-ignore
@@ -27,18 +23,7 @@ export function SimulationPanel({ session, onSimulateAgain, onClose, children }:
   const run = state?.run ?? null;
   const said = (iso: string | null) => (iso ? clock(iso) : "a moment ago");
 
-  let line: string | null = null; // where it is, in a sentence
-  if (local.kind === "submitting") line = "Sending the simulation…";
-  else if (local.kind === "unknown") line = LOST;
-  else if (local.kind === "admitted" && state === null) line = "Reading the simulation…";
-  else if (phase === "queued") line = "Waiting for a free run slot.";
-  else if (phase === "starting") line = "Its run is being started.";
-  else if (phase === "running") {
-    const { ended: done, of } = stepsEnded(steps);
-    line = session.steps ? `${done} of ${of} steps ended.` : "Running.";
-  } else if (phase === "cancel_requested") line = "Cancel requested. It's shown as cancelled once the server confirms it.";
-  else if (phase === "dead") line = "The simulation couldn't be started. Nothing ran.";
-  else if (phase === "refused") line = request?.reason ?? "The simulation was refused.";
+  const line = lineOf(session); // where it is, in a sentence
 
   // Which run it is, and when it started or how it ended (§7.5).
   const facts =
diff --git a/frontend/src/routes/editor/simulation/SimulationResult.tsx b/frontend/src/routes/editor/simulation/SimulationResult.tsx
index 43ab0dc7..ac29d30a 100644
--- a/frontend/src/routes/editor/simulation/SimulationResult.tsx
+++ b/frontend/src/routes/editor/simulation/SimulationResult.tsx
@@ -5,11 +5,12 @@
 // request stored it (§6.6's read-back: never recomputed from today's draft). A result from before the person's edits
 // says so, and marks each step changed since or no longer in the draft; a failed step says its code and message, and
 // that nothing was sent; a refusal is shown in the server's words (§7.7; the Stale and Refusals boards).
-import { useId, useState, type ReactNode } from "react";
+import { useState } from "react";
 import { Button } from "../../../components/Button";
 import { findNode, idKey } from "../../../lib/graph";
 import { ENDED, type StepSummary } from "../../../lib/simulations";
 import type { GraphDoc } from "../../../lib/workflows";
+import { Failure } from "./Failure";
 import { bodyOf } from "./loopBody";
 import { Iterations } from "./Iterations";
 import { tagsOf } from "./results";
@@ -17,28 +18,13 @@ import { SimBanner } from "./SimBanner";
 import { Refusal } from "./Refusal";
 import { InlineTags } from "./SimTags";
 import { STALE, staleWords, type Changes, type Stale } from "./stale";
+import { Section, UsedValues } from "./UsedValues";
 import type { SimulationSession } from "./useSimulation";
 
-const REDACTED = "[redacted]"; // the server's marker for a sensitive value (engine/runtime/projection.py)
-
-function Section({ title, children }: { title: string; children: ReactNode }) {
-  const id = useId();
-  return (
-    <section aria-labelledby={id} className="flex flex-col gap-1.5">
-      <h3 id={id} className="text-small font-semibold">{title}</h3>
-      {children}
-    </section>
-  );
-}
-
-const shown = (v: unknown): string => (v === REDACTED ? "redacted" : typeof v === "string" ? v : JSON.stringify(v));
 const iterationKey = (final: StepSummary["final"]): string => {
   const key = final?.iteration_key;
   return typeof key === "string" ? key : "";
 };
-const field = (v: unknown, key: string): unknown => (typeof v === "object" && v !== null && !Array.isArray(v) ? (v as Record<string, unknown>)[key] : undefined);
-/** A step's attempts, said against its retries when it used them all. */
-const attempts = (n: number, max: number | null) => (n === 1 ? "1 attempt." : n === max ? `${n} attempts, the configured retries.` : `${n} attempts.`);
 
 export function SimulationResult({ tenantId, workflowId, session, doc, ran, stale, changes, attemptsOf, onGoTo, onShowProblems, onOpen }: {
   tenantId: string; workflowId: string; session: SimulationSession;
@@ -61,6 +47,8 @@ export function SimulationResult({ tenantId, workflowId, session, doc, ran, stal
     findNode(doc, id) ? <Button size="sm" aria-label={`Go to ${key}`} onClick={() => onGoTo(id)}>Go to</Button> : null;
 
   const graph = ran ?? doc;
+  const target = request.target_step_id; // a step test's step
+  const targetKey = target ? (findNode(doc, target)?.key ?? all[0]?.key ?? "the step") : null;
   return (
     <>
       {ended && stale && (
@@ -70,7 +58,11 @@ export function SimulationResult({ tenantId, workflowId, session, doc, ran, stal
       )}
       {ended && began && (
         <SimBanner>
-          <p><strong>Simulated.</strong> Nothing was sent. Results don&apos;t prove the live call will succeed.</p>
+          {targetKey ? (
+            <p><strong>{`Step test: ${targetKey}.`}</strong> Only this step ran. Nothing was sent.</p>
+          ) : (
+            <p><strong>Simulated.</strong> Nothing was sent. Results don&apos;t prove the live call will succeed.</p>
+          )}
           {all.some((s) => s.origin === "evaluated_not_waited") && (
             <p>Flow delays and wait-until weren&apos;t waited; the simulation clock wasn&apos;t advanced.</p>
           )}
@@ -100,10 +92,6 @@ export function SimulationResult({ tenantId, workflowId, session, doc, ran, stal
               const loop = s.type.startsWith("flow.loop@") && s.instances === 1 && findNode(graph, s.step_id) !== undefined;
               const body = loop && ended ? bodyOf(graph, s.step_id) : [];
               const expanded = open === s.step_id && body.length > 0;
-              const error = s.instances === 1 && field(s.final, "status") === "failed" ? field(s.final, "error") : undefined;
-              const code = field(error, "code");
-              const message = field(error, "message");
-              const attempt = field(s.final, "attempt");
               return (
                 <li key={s.step_id} className="flex flex-wrap items-center gap-1.5 border-t border-line py-1.5 first:border-t-0">
                   <span data-key className="font-mono">{s.key}</span>
@@ -117,12 +105,7 @@ export function SimulationResult({ tenantId, workflowId, session, doc, ran, stal
                     </Button>
                   )}
                   {goTo(s.step_id, s.key)}
-                  {typeof code === "string" && (
-                    <p className="basis-full text-muted">
-                      <span className="font-mono text-ink">{code}</span>
-                      {` ${typeof message === "string" ? message : ""} ${attempts(typeof attempt === "number" ? attempt : 1, attemptsOf(s))} Nothing was sent.`}
-                    </p>
-                  )}
+                  {s.instances === 1 && <Failure final={s.final} max={attemptsOf(s)} />}
                   {expanded && (
                     <div className="basis-full ps-3">
                       <Iterations
@@ -137,27 +120,7 @@ export function SimulationResult({ tenantId, workflowId, session, doc, ran, stal
           </ul>
         </Section>
       )}
-      {request.target_step_id === null && (
-        <Section title="Input used">
-          {state.read_back === "absent" ? (
-            <p className="text-small text-muted">The input used isn&apos;t kept any more.</p>
-          ) : state.read_back === "unreadable" ? (
-            <p className="text-small text-muted">The input used couldn&apos;t be read back.</p>
-          ) : (
-            <>
-              <p className="text-small text-muted">As this simulation&apos;s request stored it, sensitive values redacted.</p>
-              <dl className="grid grid-cols-[max-content_1fr] gap-x-3 gap-y-1 text-small">
-                {Object.entries(state.input ?? {}).map(([k, v]) => (
-                  <div key={k} className="contents">
-                    <dt className="font-mono text-muted">{k}</dt>
-                    <dd className="break-words">{shown(v)}</dd>
-                  </div>
-                ))}
-              </dl>
-            </>
-          )}
-        </Section>
-      )}
+      <UsedValues state={state} />
     </>
   );
 }
diff --git a/frontend/src/routes/editor/simulation/StepResult.tsx b/frontend/src/routes/editor/simulation/StepResult.tsx
new file mode 100644
index 00000000..b65adce1
--- /dev/null
+++ b/frontend/src/routes/editor/simulation/StepResult.tsx
@@ -0,0 +1,72 @@
+// SPDX-License-Identifier: Apache-2.0
+// A step test's result in its Test tab (4d-1c; the simulation design §7.6; the TestResult board): where it is while it
+// runs; once ended, what a simulation proves, its status and where its data came from, its attempt, revision and run,
+// a failure's code and message, the port a branch took or what a step set, the values used ("seeded", sensitive ones
+// redacted) and its output.
+import { Button } from "../../../components/Button";
+import { ENDED, type StepSummary } from "../../../lib/simulations";
+import { StatusChip } from "./chips";
+import { Failure } from "./Failure";
+import { lineOf, runId } from "./lifecycle";
+import { field, originTag } from "./results";
+import { SimBanner } from "./SimBanner";
+import { InlineTags } from "./SimTags";
+import { Pairs, Section, UsedValues } from "./UsedValues";
+import type { SimulationSession } from "./useSimulation";
+
+const REDACTED = "[redacted]";
+const something = (v: unknown) =>
+  v !== undefined && v !== null && !(typeof v === "object" && !Array.isArray(v) && Object.keys(v).length === 0);
+
+export function StepResult({ session, stepKey, attemptsOf }: {
+  session: SimulationSession; stepKey: string; attemptsOf: (s: StepSummary) => number | null;
+}) {  // prettier-ignore
+  const { state, phase } = session;
+  const s = session.steps?.steps[0] ?? null; // a step test's summary holds its target alone
+  const ended = phase !== null && ENDED.has(phase);
+  const line = lineOf(session);
+  const final = s?.final;
+  const max = s ? attemptsOf(s) : null;
+  const attempt = field(final, "attempt");
+  const output = field(final, "output");
+  const port = field(field(final, "effect"), "port");
+  const assignments = field(field(final, "effect"), "assignments");
+  const facts = state
+    ? [typeof attempt === "number" && max ? `attempt ${attempt} of ${max}` : null, `revision ${state.request.draft_revision}`, `run ${runId(state.request.id)}`]
+    : [];  // prettier-ignore
+  return (
+    <Section title={`Result · ${stepKey}`}>
+      {line && <p className="text-small">{line}</p>}
+      {session.local.kind === "unknown" && (
+        <div>
+          <Button size="sm" onClick={() => void session.checkAgain()}>Check again</Button>
+        </div>
+      )}
+      {ended && state && phase !== "refused" && phase !== "dead" && (
+        <>
+          <SimBanner>
+            <p><strong>Simulated.</strong> Nothing was sent. Results don&apos;t prove the live call will succeed.</p>
+          </SimBanner>
+          <p className="flex flex-wrap items-center gap-2">
+            <StatusChip phase={phase} />
+            {s && <InlineTags tags={[originTag(s.origin)]} />}
+            <span className="text-small text-muted">{facts.filter(Boolean).join(" · ")}</span>
+          </p>
+          <Failure final={final} max={max} />
+          {typeof port === "string" && <p className="text-small">{`Takes → ${port}.`}</p>}
+          {typeof assignments === "object" && assignments !== null && (
+            <Section title="Sets">
+              <Pairs pairs={Object.entries(assignments).map(([k, v]): [string, unknown] => [k, v === REDACTED ? v : JSON.stringify(v)])} />
+            </Section>
+          )}
+          <UsedValues state={state} />
+          {something(output) && (
+            <Section title="Output">
+              <pre className="overflow-x-auto rounded-md border border-line bg-surface-2 p-2 font-mono text-meta">{JSON.stringify(output, null, 2)}</pre>
+            </Section>
+          )}
+        </>
+      )}
+    </Section>
+  );
+}
diff --git a/frontend/src/routes/editor/simulation/TestTab.tsx b/frontend/src/routes/editor/simulation/TestTab.tsx
index 47b3d28b..54f65bdf 100644
--- a/frontend/src/routes/editor/simulation/TestTab.tsx
+++ b/frontend/src/routes/editor/simulation/TestTab.tsx
@@ -9,11 +9,12 @@ import { useState } from "react";
 import { Button } from "../../../components/Button";
 import { ApiError } from "../../../lib/client";
 import { sameId } from "../../../lib/graph";
-import { freeze, seedContractQuery, type Frozen } from "../../../lib/simulations";
+import { freeze, seedContractQuery, type Frozen, type StepSummary } from "../../../lib/simulations";
 import type { GraphDoc, GraphNode, NodeType } from "../../../lib/workflows";
 import { Refusal } from "./Refusal";
 import { SeedField } from "./SeedField";
 import { collect, initialOf, titleOf, type SeedInput } from "./seeds";
+import { StepResult } from "./StepResult";
 import type { SimulationSession } from "./useSimulation";
 
 export interface TestTabProps {
@@ -30,13 +31,14 @@ export interface TestTabProps {
   onSimulateWorkflow: () => void;
   onGoTo: (stepId: string) => void;
   onShowProblems: () => void;
+  attemptsOf: (s: StepSummary) => number | null;
 }
 
 const missingWords = (n: number) => `Not simulated: ${n} ${n === 1 ? "value is" : "values are"} missing.`;
 const unreadWords = (n: number) => `Not simulated: ${n} ${n === 1 ? "value isn't" : "values aren't"} valid JSON.`;
 
 export function TestTab(props: TestTabProps) {
-  const { tenantId, workflowId, node, doc, types, revision, session, blocked, onSave, onStart, onSimulateWorkflow, onGoTo, onShowProblems } = props;
+  const { tenantId, workflowId, node, doc, types, revision, session, blocked, onSave, onStart, onSimulateWorkflow, onGoTo, onShowProblems, attemptsOf } = props;
   // The contract at the saved revision; while a newer one is read, the older stays shown (it's never sent with it).
   const contract = useQuery({ ...seedContractQuery(tenantId, workflowId, node.id, revision), placeholderData: keepPreviousData });
   const [inputs, setInputs] = useState<Record<string, SeedInput>>({});
@@ -71,6 +73,10 @@ export function TestTab(props: TestTabProps) {
   }
   // The values the server refused for this step's test, on their fields; one with no field, above them.
   const local = session.local;
+  // This step's own test: sent, or read since.
+  const sending = local.kind === "submitting" || local.kind === "unknown" ? local.frozen.body.target?.step_id : undefined;
+  const tested = session.state?.request.target_step_id ?? sending;
+  const mine = typeof tested === "string" && sameId(tested, node.id);
   const refused = local.kind === "refused" && local.frozen.body.target && sameId(local.frozen.body.target.step_id, node.id) ? local.error : null;
   const seedProblems = refused && Array.isArray((refused.body as { problems?: unknown } | null)?.problems)
     ? ((refused.body as { problems: { pointer: string; message: string }[] }).problems)
@@ -140,6 +146,7 @@ export function TestTab(props: TestTabProps) {
         <Button variant="simulate" size="md" disabled={blocked} onClick={() => void simulate()}>◌ Simulate step</Button>
         <p className="text-small text-muted">{`Each value is checked against what ${node.key} reads.`}</p>
       </div>
+      {mine && <StepResult session={session} stepKey={node.key} attemptsOf={attemptsOf} />}
     </>
   );
 }
diff --git a/frontend/src/routes/editor/simulation/UsedValues.tsx b/frontend/src/routes/editor/simulation/UsedValues.tsx
new file mode 100644
index 00000000..666955b3
--- /dev/null
+++ b/frontend/src/routes/editor/simulation/UsedValues.tsx
@@ -0,0 +1,62 @@
+// SPDX-License-Identifier: Apache-2.0
+// What a simulation was given, as its request stored it (4d-1c; the simulation design §6.6's read-back, §7.5, §7.6; the
+// ResultPanel and TestResult boards): a workflow's input, or a step test's values, each "seeded"; sensitive values
+// redacted by the server, never recomputed from today's draft.
+import { useId, type ReactNode } from "react";
+import { Tag } from "../../../components/Tag";
+import type { SimulationState } from "../../../lib/simulations";
+
+const REDACTED = "[redacted]"; // the server's marker for a sensitive value (engine/runtime/projection.py)
+
+/** A stored value as a person reads it: redacted in words, text as it is, the rest as JSON. */
+export const shown = (v: unknown): string => (v === REDACTED ? "redacted" : typeof v === "string" ? v : JSON.stringify(v));
+
+/** A titled section of the result. */
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
+/** Pairs, a name and its value: a dl. */
+export function Pairs({ pairs, tag }: { pairs: [string, unknown][]; tag?: string }) {
+  return (
+    <dl className="grid grid-cols-[max-content_1fr] gap-x-3 gap-y-1 text-small">
+      {pairs.map(([k, v]) => (
+        <div key={k} className="contents">
+          <dt className="font-mono break-all text-muted">{k}</dt>
+          <dd className="break-words">
+            {shown(v)}
+            {tag && <> <Tag>{tag}</Tag></>}
+          </dd>
+        </div>
+      ))}
+    </dl>
+  );
+}
+
+export function UsedValues({ state }: { state: SimulationState }) {
+  const seeds = state.request.target_step_id !== null;
+  const what = seeds ? "values used" : "input used";
+  const values = (seeds ? state.seeds : state.input) ?? {};
+  return (
+    <Section title={seeds ? "Values used" : "Input used"}>
+      {state.read_back === "absent" ? (
+        <p className="text-small text-muted">{seeds ? "The values used aren't kept any more." : "The input used isn't kept any more."}</p>
+      ) : state.read_back === "unreadable" ? (
+        <p className="text-small text-muted">{`The ${what} couldn't be read back.`}</p>
+      ) : (
+        <>
+          <p className="text-small text-muted">
+            {seeds ? "As this step test's request stored them, sensitive values redacted." : "As this simulation's request stored it, sensitive values redacted."}
+          </p>
+          <Pairs pairs={Object.entries(values)} tag={seeds ? "seeded" : undefined} />
+        </>
+      )}
+    </Section>
+  );
+}
diff --git a/frontend/src/routes/editor/simulation/lifecycle.ts b/frontend/src/routes/editor/simulation/lifecycle.ts
index 23d3e562..be71655f 100644
--- a/frontend/src/routes/editor/simulation/lifecycle.ts
+++ b/frontend/src/routes/editor/simulation/lifecycle.ts
@@ -3,6 +3,7 @@
 // boards): its status, how long it ran, which run it is, how far it got, and how it ended, naming the step that
 // decided it, from the server's per-step summary in run order.
 import type { Phase, StepSummary } from "../../../lib/simulations";
+import type { SimulationSession } from "./useSimulation";
 
 export const STATUS: Record<Phase, string> = {
   queued: "Queued",
@@ -57,3 +58,25 @@ export function endedWhat(phase: Phase, steps: StepSummary[]): string {
   }
   return STATUS[phase].toLowerCase();
 }
+
+const LOST =
+  "It isn't known whether the simulation started: its answer was lost. Checking sends the same request again: while the " +
+  "first request is still kept, it can't start a second time.";
+
+/** Where a simulation is, in a sentence (§7.2; the Lifecycle and Running boards); null once its status says it all. */
+export function lineOf(session: SimulationSession): string | null {
+  const { local, state, phase } = session;
+  if (local.kind === "submitting") return "Sending the simulation…";
+  if (local.kind === "unknown") return LOST;
+  if (local.kind === "admitted" && state === null) return "Reading the simulation…";
+  if (phase === "queued") return "Waiting for a free run slot.";
+  if (phase === "starting") return "Its run is being started.";
+  if (phase === "running") {
+    const { ended, of } = stepsEnded(session.steps?.steps ?? []);
+    return session.steps ? `${ended} of ${of} steps ended.` : "Running.";
+  }
+  if (phase === "cancel_requested") return "Cancel requested. It's shown as cancelled once the server confirms it.";
+  if (phase === "dead") return "The simulation couldn't be started. Nothing ran.";
+  if (phase === "refused") return state?.request.reason ?? "The simulation was refused.";
+  return null;
+}
diff --git a/frontend/src/routes/editor/simulation/results.ts b/frontend/src/routes/editor/simulation/results.ts
index 8087182b..9fa67fc9 100644
--- a/frontend/src/routes/editor/simulation/results.ts
+++ b/frontend/src/routes/editor/simulation/results.ts
@@ -39,10 +39,13 @@ const ORIGIN_KIND: Record<Origin, SimTagKind> = {
   not_reached_yet: "absent",
 };
 
+/** Where a step's data came from, as its tag. */
+export const originTag = (origin: Origin): SimTag => ({ text: ORIGIN[origin], kind: ORIGIN_KIND[origin] });
+
 const ORDER = ["succeeded", "failed", "cancelled", "skipped", "not_started", "running"];
 const said = (status: string) => status.replace("_", " ");
 const statusKind = (status: string): SimTagKind => (status === "succeeded" ? "ok" : status === "failed" ? "fail" : "status");
-const field = (v: unknown, key: string): unknown => (typeof v === "object" && v !== null && !Array.isArray(v) ? (v as Record<string, unknown>)[key] : undefined);
+export const field = (v: unknown, key: string): unknown => (typeof v === "object" && v !== null && !Array.isArray(v) ? (v as Record<string, unknown>)[key] : undefined);
 
 export const words = (tags: SimTag[]) => tags.map((t) => t.text);
 
```

- [ ] **Step 4: Run them again**

Run: the same command.

Expected: PASS, 264 passed.

- [ ] **Step 5: Static checks**

Run: the two of "How to run things". Expected: no output.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/routes/editor
git commit -m "feat(editor): a step test's result in its tab, and the step alone on the canvas (4d-1c)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 12: The step in the latest simulation

**Spec:** §7.6 ("After a workflow simulation, the step's result in it, with an iteration picker"), §7.5 (a loop's
iterations); the TestTab and TestOther boards.

**Files:**
- Create: `frontend/src/routes/editor/simulation/LatestResult.tsx`
- Modify: `frontend/src/routes/editor/simulation/StepResult.tsx` (`InstanceDetail`), `TestTab.tsx` (`iteration`),
  `TestTab.test.tsx`
- Modify: `frontend/src/routes/editor/drawer/StepDrawer.tsx` (`testAt`)
- Modify: `frontend/src/routes/editor/Editor.tsx`, `frontend/src/routes/editor/Editor.test.tsx`

**Interfaces:**
- Consumes: `stepInstancesQuery` (Task 2); `tagsOf`, `field` (Tasks 6, 11); `Iterations`' `onOpen` (Task 7);
  `Select` (`components/Field.tsx`).
- Produces:
  - `InstanceDetail({ final, max, used? })`: a failure, a port or what was set, the values used, the output.
  - `LatestResult({ tenantId, workflowId, session, node, attemptsOf, iteration })`.
  - `TestTab`'s `iteration?: { key: string; n: number } | null`; `StepDrawer`'s `testAt?: number | null`.
  - In `Editor`: the step side panel's `test?: { key: string; n: number }`; the panel's `onOpen(stepId,
    iterationKey)`.

After a workflow simulation, the step's Test tab says "In your latest simulation": "Revision 14, 10:42:05: <its tags>."
(ruling 17). A step that ran once shows what it did. A step that ran in a loop offers its iterations in a picker ("4 ·
failed · invalid_blocks"), the first 50, and "Show" shows the one picked. A step that can't run alone shows it too. In
the panel, "Open" on a failed iteration opens its step's drawer on the Test tab, at that iteration.

- [ ] **Step 1: Write the failing tests**

Apply:

```diff
diff --git a/frontend/src/routes/editor/Editor.test.tsx b/frontend/src/routes/editor/Editor.test.tsx
index 8bc02ca5..9ccb5368 100644
--- a/frontend/src/routes/editor/Editor.test.tsx
+++ b/frontend/src/routes/editor/Editor.test.tsx
@@ -2205,6 +2205,37 @@ describe("Simulate step", () => {
     expect(screen.getByText("Step test: transform.").parentElement?.textContent).toBe("Step test: transform. Only this step ran. Nothing was sent.");
   });
 
+  it("opens a failed iteration's step on its Test tab, at that iteration (§7.5, §7.6)", async () => {
+    const SIM = `${BASE}/draft/simulations`;
+    answers.set("GET /api/v1/node-types", () => json([...TYPES, LOOP]));
+    const draft = {
+      graph_format: 1, edges: [{ from: { node: "id-each", port: "body" }, to: { node: "id-notify" } }],
+      nodes: [{ id: "id-each", key: "each", type: "flow.loop@1", config: {}, position: { x: 0, y: 140 } }, { id: "id-notify", key: "notify", type: "flow.transform@1", config: {}, position: { x: 0, y: 280 } }],
+    };  // prettier-ignore
+    const request = { id: "r1", workflow_id: "w1", version_id: null, draft_snapshot_id: "s1", draft_revision: 1, target_step_id: null, mode: "simulate", source: "manual", status: "started", reason: null, queued_at: "2026-10-15T10:42:05Z", ended_at: null, admission_checks: [] };
+    const run = { status: "failed", queued_at: null, started_at: "2026-10-15T10:42:05Z", ended_at: "2026-10-15T10:42:19Z", error: null, iterations: 2 };
+    const failed = { step_id: "id-notify", key: "notify", iteration_key: "each:1", attempt: 1, status: "failed", error: { code: "invalid_blocks", message: "Block 2 has no text." } };
+    answers.set(`GET ${BASE}`, () => json({ ...WORKFLOW, draft }));
+    answers.set(`GET ${SIM}`, () => json([request]));
+    answers.set(`GET ${SIM}/r1`, () => json({ request, run, cancel_requested: false, read_back: "kept", input: {}, seeds: null }));
+    answers.set(`GET ${SIM}/r1/steps`, () => json({ given: "input", steps: [
+      { step_id: "id-each", key: "each", type: "flow.loop@1", origin: "evaluated", instances: 1, statuses: { failed: 1 }, ports: {}, final: { attempt: 1, status: "failed", output: { items: [], failures: [], count: 2 } } },
+      { step_id: "id-notify", key: "notify", type: "flow.transform@1", origin: "evaluated", instances: 2, statuses: { succeeded: 1, failed: 1 }, ports: {}, final: null },
+    ] }));  // prettier-ignore
+    answers.set(`GET ${SIM}/r1/steps/id-notify/instances`, () => json({ total: 2, items: [{ ...failed, iteration_key: "each:0", status: "succeeded", error: null }, failed] }));
+    answers.set(`GET ${BASE}/draft/steps/id-notify/seeds`, () => json({ draft_revision: 1, step_id: "id-notify", refused: null, entries: [] }));
+    await show();
+    await screen.findByRole("button", { name: "Hide the result" });
+    await userEvent.click(screen.getByRole("button", { name: "Simulation" }));
+    const panel = await screen.findByRole("complementary", { name: "Simulation" });
+    await userEvent.click(within(panel).getByRole("button", { name: "Iterations of each" }));
+    await userEvent.click(await within(panel).findByRole("button", { name: "Open notify, iteration 2" }));
+    const drawer = await screen.findByRole("complementary", { name: "notify" });
+    expect(within(drawer).getByRole("tab", { name: "Test" }).getAttribute("aria-selected")).toBe("true");
+    const found = await within(drawer).findByRole("region", { name: "In your latest simulation" });
+    expect(await within(found).findByText("invalid_blocks")).toBeTruthy();
+  });
+
   it("isn't offered to a viewer", async () => {
     role = "viewer";
     await show();
diff --git a/frontend/src/routes/editor/simulation/TestTab.test.tsx b/frontend/src/routes/editor/simulation/TestTab.test.tsx
index a08a01dd..c4e5ad67 100644
--- a/frontend/src/routes/editor/simulation/TestTab.test.tsx
+++ b/frontend/src/routes/editor/simulation/TestTab.test.tsx
@@ -4,7 +4,7 @@ import { render, screen, within } from "@testing-library/react";
 import userEvent from "@testing-library/user-event";
 import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
 import { ApiError } from "../../../lib/client";
-import type { SeedContract, SeedEntry } from "../../../lib/simulations";
+import type { SeedContract, SeedEntry, SimulationRequest, StepSummary } from "../../../lib/simulations";
 import type { GraphDoc, GraphNode, NodeType } from "../../../lib/workflows";
 import { TestTab } from "./TestTab";
 import type { SimulationSession } from "./useSimulation";
@@ -15,6 +15,7 @@ const DOC = { graph_format: 1, nodes: [NOTIFY], edges: [] } as unknown as GraphD
 const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
 
 let contract: (revision: number) => Response;
+let instances: () => Response;
 let asked: string[];
 beforeEach(() => {
   asked = [];
@@ -22,7 +23,9 @@ beforeEach(() => {
   vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
     const url = new URL((input as Request).url);
     asked.push(url.pathname + url.search);
-    return Promise.resolve(url.pathname === SEEDS ? contract(Number(url.searchParams.get("revision"))) : json({ error: "not_found" }, 404));
+    if (url.pathname === SEEDS) return Promise.resolve(contract(Number(url.searchParams.get("revision"))));
+    if (url.pathname.endsWith("/steps/id-notify/instances")) return Promise.resolve(instances());
+    return Promise.resolve(json({ error: "not_found" }, 404));
   });
 });
 afterEach(() => vi.restoreAllMocks());
@@ -207,3 +210,64 @@ describe("the values a step test sends (§7.6; the TestTab and TestOther boards)
     expect((await screen.findByRole("button", { name: "◌ Simulate step" })).hasAttribute("disabled")).toBe(true);
   });
 });
+
+// The person's latest simulation of the whole workflow, ended (§7.6: "After a workflow simulation, the step's result in it").
+function latest(s: StepSummary): SimulationSession {
+  const request: SimulationRequest = {
+    id: "r1", workflow_id: "w1", draft_snapshot_id: "s1", draft_revision: 14, target_step_id: null, mode: "simulate", source: "manual",
+    status: "started", reason: null, queued_at: "2026-10-15T10:42:05Z", ended_at: null, admission_checks: [],
+  };  // prettier-ignore
+  const run = { status: "failed" as const, queued_at: null, started_at: "2026-10-15T10:42:05Z", ended_at: "2026-10-15T10:42:19Z", error: null, iterations: 12 };
+  return {
+    ...idle(), local: { kind: "admitted", frozen: null, request, latest: true }, phase: "failed",
+    state: { request, run, cancel_requested: false, read_back: "kept", input: {}, seeds: null }, steps: { given: "input", steps: [s] },
+  };  // prettier-ignore
+}
+const notify = (over: Partial<StepSummary> = {}): StepSummary => ({
+  step_id: "id-notify", key: "notify", type: "slack.post@1", origin: "fixture_not_sent", instances: 1, statuses: { succeeded: 1 }, ports: {},
+  final: { attempt: 1, status: "succeeded", output: { ok: true } }, ...over,
+});  // prettier-ignore
+const at = (iso: string) => new Date(iso).toLocaleTimeString("en-GB");
+const instance = (n: number, status: string) => ({
+  step_id: "id-notify", key: "notify", iteration_key: `each_ap:${n}`, attempt: status === "failed" ? 3 : 1, status, output: null,
+  error: status === "failed" ? { code: "invalid_blocks", message: "Block 2 has no text." } : null,
+});  // prettier-ignore
+
+describe("the step in your latest simulation (§7.6; the TestTab and TestOther boards)", () => {
+  beforeEach(() => {
+    instances = () => json({ total: 4, items: [instance(0, "skipped"), instance(1, "succeeded"), instance(2, "skipped"), instance(3, "failed")] });
+  });
+
+  it("shows the step's result in the person's latest simulation of the workflow", async () => {
+    show({ session: latest(notify()) });
+    const found = await screen.findByRole("region", { name: "In your latest simulation" });
+    expect(within(found).getByText(`Revision 14, ${at("2026-10-15T10:42:05Z")}: succeeded · fixture · not sent.`)).toBeTruthy();
+    expect(within(found).getByRole("region", { name: "Output" })).toBeTruthy();
+  });
+
+  it("picks one of a looped step's iterations", async () => {
+    show({ session: latest(notify({ instances: 4, statuses: { succeeded: 1, failed: 1, skipped: 2 }, final: null })) });
+    const found = await screen.findByRole("region", { name: "In your latest simulation" });
+    expect(within(found).getByText(`Revision 14, ${at("2026-10-15T10:42:05Z")}: 4 instances: 1 succeeded · 1 failed · 2 skipped · fixture · not sent.`)).toBeTruthy();
+    const picker = await within(found).findByRole("combobox", { name: "Iteration" });
+    expect(within(picker).getAllByRole("option").map((o) => o.textContent)).toEqual(["1 · skipped", "2 · succeeded", "3 · skipped", "4 · failed · invalid_blocks"]);
+    await userEvent.selectOptions(picker, "4 · failed · invalid_blocks");
+    await userEvent.click(within(found).getByRole("button", { name: "Show" }));
+    expect(within(found).getByText("invalid_blocks").parentElement?.textContent).toBe("invalid_blocks Block 2 has no text. 3 attempts, the configured retries. Nothing was sent.");
+    expect(asked).toContain("/api/v1/t/t1/workflows/w1/draft/simulations/r1/steps/id-notify/instances?offset=0&limit=50");
+  });
+
+  it("opens at the iteration asked for", async () => {
+    show({ session: latest(notify({ instances: 4, statuses: { succeeded: 1, failed: 1, skipped: 2 }, final: null })), iteration: { key: "each_ap:3", n: 1 } });
+    const found = await screen.findByRole("region", { name: "In your latest simulation" });
+    expect(await within(found).findByText("invalid_blocks")).toBeTruthy();
+    expect(within(found).getByRole("combobox", { name: "Iteration" })).toHaveProperty("value", "each_ap:3");
+  });
+
+  it("shows it beside a step that can't run alone", async () => {
+    contract = () => json({ draft_revision: 14, step_id: "id-notify", refused: "This step can't be simulated alone: simulate the workflow to see it run.", entries: [] });
+    show({ session: latest(notify({ type: "flow.loop@1", origin: "evaluated", final: { attempt: 1, status: "succeeded", output: { items: [], failures: [], count: 12 } } })) });
+    const found = await screen.findByRole("region", { name: "In your latest simulation" });
+    expect(within(found).getByText(`Revision 14, ${at("2026-10-15T10:42:05Z")}: succeeded · 12 iterations.`)).toBeTruthy();
+  });
+});
```

- [ ] **Step 2: Run them**

Run: `npx --offline pnpm@12.6.0 exec vitest run src/routes/editor/simulation src/routes/editor/Editor.test.tsx`

Expected: FAIL, 5 failed and 264 passed: no "In your latest simulation" region in the Test tab, and in the panel no
"Open notify, iteration 2" (the editor gives `onOpen` nowhere to go yet).

- [ ] **Step 3: Implement**

Apply:

```diff
diff --git a/frontend/src/routes/editor/Editor.tsx b/frontend/src/routes/editor/Editor.tsx
index 2688de59..50d29691 100644
--- a/frontend/src/routes/editor/Editor.tsx
+++ b/frontend/src/routes/editor/Editor.tsx
@@ -64,7 +64,8 @@ type Opened = { workflow: WorkflowDetail; types: NodeType[]; role: string | null
 /** The editor's right column: a step's panel, the problems, the versions, the edits not applied, Declassify, or the
  * Triggers panel (4c-3b), at a place in it when "Go to it" sent it there. */
 type Side =
-  | { kind: "step"; node: string; field?: { pointer: string; kind?: UnappliedKind; n: number } } | { kind: "problems" } | { kind: "versions" }
+  | { kind: "step"; node: string; field?: { pointer: string; kind?: UnappliedKind; n: number }; test?: { key: string; n: number } }
+  | { kind: "problems" } | { kind: "versions" }
   | { kind: "unapplied" } | { kind: "declassify" } | { kind: "triggers"; at?: { pointer: string; n: number } } | { kind: "simulation" } | null;  // prettier-ignore
 const NO_DIAGNOSTICS: Diagnostic[] = []; // one empty list, so a memo over it holds
 const NO_STEPS: ReadonlySet<string> = new Set();
@@ -1403,6 +1404,7 @@ function Editor({
             actions={viewing ? VERSION_ACTIONS : actionsFor(open.id)}
             note={noteFor(open.id)}
             focusField={side?.kind === "step" ? (side.field ?? null) : null}
+            testAt={side?.kind === "step" ? (side.test?.n ?? null) : null}
             test={
               simulator ? (
                 <TestTab
@@ -1412,6 +1414,7 @@ function Editor({
                   onStart={(frozen) => void simulation.start(frozen)}
                   onSimulateWorkflow={() => whenSettled("simulate", () => void simulate())}
                   onGoTo={(id) => focus(item.node(id))} onShowProblems={() => setSide({ kind: "problems" })} attemptsOf={attemptsOf}
+                  iteration={side?.kind === "step" ? (side.test ?? null) : null}
                 />
               ) : undefined
             }
@@ -1519,6 +1522,7 @@ function Editor({
             <SimulationResult
               tenantId={tenantId} workflowId={workflow.id} session={simulation} doc={doc} ran={ran} stale={stale} changes={changes}
               attemptsOf={attemptsOf} onGoTo={(id) => focus(item.node(id))} onShowProblems={() => setSide({ kind: "problems" })}
+              onOpen={(id, iteration) => setSide({ kind: "step", node: id, test: { key: iteration, n: ++jumps.current } })}
             />
           </SimulationPanel>
         )}
diff --git a/frontend/src/routes/editor/drawer/StepDrawer.tsx b/frontend/src/routes/editor/drawer/StepDrawer.tsx
index c7201d60..1799b383 100644
--- a/frontend/src/routes/editor/drawer/StepDrawer.tsx
+++ b/frontend/src/routes/editor/drawer/StepDrawer.tsx
@@ -80,13 +80,14 @@ function locate(root: HTMLElement, { pointer, kind }: FocusRequest): HTMLElement
 
 export function StepDrawer({
   node, type, tenantId, workflowId, revision, steps, openDeclassify, ports, problems, expressions, editable, adds, actions, note, focusField,
-  test, onAdd, onDelete, onConnectPort, onPlace, onNudge, onClose,
+  test, testAt, onAdd, onDelete, onConnectPort, onPlace, onNudge, onClose,
 }: {
   node: GraphNode; type: NodeType | undefined; tenantId: string; workflowId: string; revision: number | null;
   steps: { id: string; key: string; title: string | null }[]; openDeclassify?: () => void; ports: string[];
   problems: Diagnostic[] | null; expressions: Expression[]; editable: boolean; adds: { label: string; action: ItemAction }[];
   actions: DrawerActions; note: string | null; focusField: { pointer: string; kind?: UnappliedKind; n: number } | null;
   test?: ReactNode; // the Test tab, for editors (4d-1c, §7.6), even on a step with nothing to set up
+  testAt?: number | null; // asked to show the Test tab (the Simulation panel's "Open"), counted
   onAdd: (action: ItemAction) => void; onDelete: () => void; onConnectPort: (port: string) => void;
   onPlace: () => void; onNudge: (key: Nudge) => void; onClose: () => void;
 }) {  // prettier-ignore
@@ -99,7 +100,10 @@ export function StepDrawer({
   }, [node.id]);
   const fields = useMemo(() => (type ? fieldsOf(type) : []), [type]);
   const { setup, options } = tabsOf(fields);
-  const [tab, setTab] = useState<Tab>(setup.length > 0 ? "setup" : "options");
+  const [tab, setTab] = useState<Tab>(test && testAt ? "test" : setup.length > 0 ? "setup" : "options");
+  useEffect(() => {
+    if (test && testAt) setTab("test");
+  }, [testAt]);
   const [handling, setHandling] = useState(false);
   // "Go to" (ruling 16; the review of 66fc658): a config field on its tab; a held key at the key field; a held limit in
   // the error handling, opened; a held entry name at its name. Its control takes focus once it has rendered, and one
diff --git a/frontend/src/routes/editor/simulation/LatestResult.tsx b/frontend/src/routes/editor/simulation/LatestResult.tsx
new file mode 100644
index 00000000..160116f0
--- /dev/null
+++ b/frontend/src/routes/editor/simulation/LatestResult.tsx
@@ -0,0 +1,84 @@
+// SPDX-License-Identifier: Apache-2.0
+// A step in the person's latest simulation of the whole workflow, in its Test tab (4d-1c; the simulation design §7.6:
+// "After a workflow simulation, the step's result in it, with an iteration picker"; the TestTab and TestOther boards):
+// its tags, as on the canvas; one instance shown as it is; a step that ran in a loop, one iteration at a time, picked
+// from the first page of its instances, or the one the Simulation panel's "Open" asked for.
+import { useQuery } from "@tanstack/react-query";
+import { useEffect, useState } from "react";
+import { Button } from "../../../components/Button";
+import { Select } from "../../../components/Field";
+import { sameId } from "../../../lib/graph";
+import { ENDED, stepInstancesQuery, type StepSummary } from "../../../lib/simulations";
+import type { GraphNode } from "../../../lib/workflows";
+import { clock } from "./lifecycle";
+import { field, tagsOf } from "./results";
+import { InstanceDetail } from "./StepResult";
+import { Section } from "./UsedValues";
+import type { SimulationSession } from "./useSimulation";
+
+const PAGE = 50;
+
+/** An iteration as a person counts it: from 1, nested ones joined ("2/3"). */
+const counted = (key: string) => key.split("/").map((part) => Number(part.split(":").at(-1)) + 1).join("/");
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
+export function LatestResult({ tenantId, workflowId, session, node, attemptsOf, iteration }: {
+  tenantId: string; workflowId: string; session: SimulationSession; node: GraphNode;
+  attemptsOf: (s: StepSummary) => number | null; iteration: { key: string; n: number } | null;
+}) {  // prettier-ignore
+  const { state, phase } = session;
+  const s = state && state.request.target_step_id === null ? session.steps?.steps.find((x) => sameId(x.step_id, node.id)) : undefined;
+  const ended = phase !== null && ENDED.has(phase);
+  const several = s !== undefined && s.instances > 1;
+  const page = useQuery({
+    ...stepInstancesQuery(tenantId, workflowId, state?.request.id ?? "", node.id, { offset: 0, limit: PAGE }),
+    enabled: several && ended,
+  });
+  const [picked, setPicked] = useState<string | null>(iteration?.key ?? null);
+  const [shown, setShown] = useState<string | null>(iteration?.key ?? null);
+  useEffect(() => {
+    if (iteration) {
+      setPicked(iteration.key);
+      setShown(iteration.key);
+    }
+  }, [iteration?.n]);
+  if (!s || !state) return null;
+  const items = page.data?.items ?? [];
+  const choice = picked ?? (items[0] ? keyOf(items[0]) : "");
+  const item = shown === null ? undefined : items.find((i) => keyOf(i) === shown);
+  const words = tagsOf(s, { maxAttempts: attemptsOf(s), ended }).map((t) => t.text).join(" · ");
+  return (
+    <Section title="In your latest simulation">
+      <p className="text-small">{`Revision ${state.request.draft_revision}, ${state.request.queued_at ? clock(state.request.queued_at) : "earlier"}: ${words}.`}</p>
+      {s.instances === 1 && <InstanceDetail final={s.final} max={attemptsOf(s)} />}
+      {several && ended && (
+        page.isError ? (
+          <p className="text-small text-muted">Its iterations couldn&apos;t be read.</p>
+        ) : !page.data ? (
+          <p className="text-small text-muted">Reading its iterations…</p>
+        ) : (
+          <>
+            <div className="flex flex-wrap items-end gap-2">
+              <div className="min-w-0 grow">
+                <Select label="Iteration" value={choice} onChange={(e) => setPicked(e.target.value)}>
+                  {items.map((i) => <option key={keyOf(i)} value={keyOf(i)}>{optionOf(i)}</option>)}
+                </Select>
+              </div>
+              <Button size="md" onClick={() => setShown(choice || null)}>Show</Button>
+            </div>
+            {page.data.total > items.length && <p className="text-small text-muted">{`The first ${items.length} of ${page.data.total} iterations.`}</p>}
+            {item !== undefined && <InstanceDetail final={item} max={attemptsOf(s)} />}
+          </>
+        )
+      )}
+    </Section>
+  );
+}
diff --git a/frontend/src/routes/editor/simulation/StepResult.tsx b/frontend/src/routes/editor/simulation/StepResult.tsx
index b65adce1..79271e86 100644
--- a/frontend/src/routes/editor/simulation/StepResult.tsx
+++ b/frontend/src/routes/editor/simulation/StepResult.tsx
@@ -3,6 +3,7 @@
 // runs; once ended, what a simulation proves, its status and where its data came from, its attempt, revision and run,
 // a failure's code and message, the port a branch took or what a step set, the values used ("seeded", sensitive ones
 // redacted) and its output.
+import type { ReactNode } from "react";
 import { Button } from "../../../components/Button";
 import { ENDED, type StepSummary } from "../../../lib/simulations";
 import { StatusChip } from "./chips";
@@ -18,6 +19,31 @@ const REDACTED = "[redacted]";
 const something = (v: unknown) =>
   v !== undefined && v !== null && !(typeof v === "object" && !Array.isArray(v) && Object.keys(v).length === 0);
 
+/** What one instance of a step did, from its final attempt: a failure, the port a branch took or what a step set, and its
+ * output (`used`, the values it was given, before it). Its status and origin are said beside it. */
+export function InstanceDetail({ final, max, used }: { final: unknown; max: number | null; used?: ReactNode }) {
+  const output = field(final, "output");
+  const port = field(field(final, "effect"), "port");
+  const assignments = field(field(final, "effect"), "assignments");
+  return (
+    <>
+      <Failure final={final} max={max} />
+      {typeof port === "string" && <p className="text-small">{`Takes → ${port}.`}</p>}
+      {typeof assignments === "object" && assignments !== null && (
+        <Section title="Sets">
+          <Pairs pairs={Object.entries(assignments).map(([k, v]): [string, unknown] => [k, v === REDACTED ? v : JSON.stringify(v)])} />
+        </Section>
+      )}
+      {used}
+      {something(output) && (
+        <Section title="Output">
+          <pre className="overflow-x-auto rounded-md border border-line bg-surface-2 p-2 font-mono text-meta">{JSON.stringify(output, null, 2)}</pre>
+        </Section>
+      )}
+    </>
+  );
+}
+
 export function StepResult({ session, stepKey, attemptsOf }: {
   session: SimulationSession; stepKey: string; attemptsOf: (s: StepSummary) => number | null;
 }) {  // prettier-ignore
@@ -28,9 +54,6 @@ export function StepResult({ session, stepKey, attemptsOf }: {
   const final = s?.final;
   const max = s ? attemptsOf(s) : null;
   const attempt = field(final, "attempt");
-  const output = field(final, "output");
-  const port = field(field(final, "effect"), "port");
-  const assignments = field(field(final, "effect"), "assignments");
   const facts = state
     ? [typeof attempt === "number" && max ? `attempt ${attempt} of ${max}` : null, `revision ${state.request.draft_revision}`, `run ${runId(state.request.id)}`]
     : [];  // prettier-ignore
@@ -52,19 +75,7 @@ export function StepResult({ session, stepKey, attemptsOf }: {
             {s && <InlineTags tags={[originTag(s.origin)]} />}
             <span className="text-small text-muted">{facts.filter(Boolean).join(" · ")}</span>
           </p>
-          <Failure final={final} max={max} />
-          {typeof port === "string" && <p className="text-small">{`Takes → ${port}.`}</p>}
-          {typeof assignments === "object" && assignments !== null && (
-            <Section title="Sets">
-              <Pairs pairs={Object.entries(assignments).map(([k, v]): [string, unknown] => [k, v === REDACTED ? v : JSON.stringify(v)])} />
-            </Section>
-          )}
-          <UsedValues state={state} />
-          {something(output) && (
-            <Section title="Output">
-              <pre className="overflow-x-auto rounded-md border border-line bg-surface-2 p-2 font-mono text-meta">{JSON.stringify(output, null, 2)}</pre>
-            </Section>
-          )}
+          <InstanceDetail final={final} max={max} used={<UsedValues state={state} />} />
         </>
       )}
     </Section>
diff --git a/frontend/src/routes/editor/simulation/TestTab.tsx b/frontend/src/routes/editor/simulation/TestTab.tsx
index 54f65bdf..d8b1ec47 100644
--- a/frontend/src/routes/editor/simulation/TestTab.tsx
+++ b/frontend/src/routes/editor/simulation/TestTab.tsx
@@ -11,6 +11,7 @@ import { ApiError } from "../../../lib/client";
 import { sameId } from "../../../lib/graph";
 import { freeze, seedContractQuery, type Frozen, type StepSummary } from "../../../lib/simulations";
 import type { GraphDoc, GraphNode, NodeType } from "../../../lib/workflows";
+import { LatestResult } from "./LatestResult";
 import { Refusal } from "./Refusal";
 import { SeedField } from "./SeedField";
 import { collect, initialOf, titleOf, type SeedInput } from "./seeds";
@@ -32,6 +33,7 @@ export interface TestTabProps {
   onGoTo: (stepId: string) => void;
   onShowProblems: () => void;
   attemptsOf: (s: StepSummary) => number | null;
+  iteration?: { key: string; n: number } | null; // the iteration the Simulation panel's "Open" asked for
 }
 
 const missingWords = (n: number) => `Not simulated: ${n} ${n === 1 ? "value is" : "values are"} missing.`;
@@ -39,6 +41,7 @@ const unreadWords = (n: number) => `Not simulated: ${n} ${n === 1 ? "value isn't
 
 export function TestTab(props: TestTabProps) {
   const { tenantId, workflowId, node, doc, types, revision, session, blocked, onSave, onStart, onSimulateWorkflow, onGoTo, onShowProblems, attemptsOf } = props;
+  const latest = <LatestResult tenantId={tenantId} workflowId={workflowId} session={session} node={node} attemptsOf={attemptsOf} iteration={props.iteration ?? null} />;
   // The contract at the saved revision; while a newer one is read, the older stays shown (it's never sent with it).
   const contract = useQuery({ ...seedContractQuery(tenantId, workflowId, node.id, revision), placeholderData: keepPreviousData });
   const [inputs, setInputs] = useState<Record<string, SeedInput>>({});
@@ -68,6 +71,7 @@ export function TestTab(props: TestTabProps) {
         <div>
           <Button variant="simulate" size="md" onClick={onSimulateWorkflow}>◌ Simulate workflow</Button>
         </div>
+        {latest}
       </>
     );
   }
@@ -147,6 +151,7 @@ export function TestTab(props: TestTabProps) {
         <p className="text-small text-muted">{`Each value is checked against what ${node.key} reads.`}</p>
       </div>
       {mine && <StepResult session={session} stepKey={node.key} attemptsOf={attemptsOf} />}
+      {latest}
     </>
   );
 }
```

- [ ] **Step 4: Run them again**

Run: the same command.

Expected: PASS, 269 passed.

- [ ] **Step 5: Static checks**

Run: the two of "How to run things". Expected: no output.

- [ ] **Step 6: Commit, and the milestone**

```bash
git add frontend/src/routes/editor
git commit -m "feat(editor): the step in the latest simulation, an iteration at a time, and Open from the panel (4d-1c)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

Append `### 4d-1c, milestone 3 (date)` to the ledger: the tasks' commits, each task's test counts as run, every
mid-slice ruling. Commit it (`docs(editor-4): 4d-1c milestone 3`). **Pause** for the owner's review.

---

# Milestone 4 — Close

### Task 13: In the browser

**Spec:** §8 (4d-1c: the Playwright gate over each board's state, light and dark, at 1280 and 320 px; nothing leaves
the stack).

**Files:**
- Create: `frontend/e2e/simulation.spec.ts`, `frontend/e2e/fixtures/simulate.dewpoint.json`
- Modify: `frontend/playwright.config.ts` (the workflows project runs `simulation.spec.ts`)

**Interfaces:**
- Consumes: `test`, `expect`, `expectAccessible` (`e2e/gate.ts`); the admin's saved state (the foundations project).
- Produces: nothing other tasks use.

The fixture is a by-hand workflow whose input has a required "Site": `greet` reads it, `check` takes "true" when it's
longer than two characters, then `long` or `short`. Three specs, each on its own copy of it:
- simulated from the toolbar: each step's tags (`short` skipped), the panel's steps and input, Hide and Show, and axe
  on the dialog and the result, light and dark;
- a step added after a simulation: "Before your edits", the new step's "new since revision N: no result", axe; then the
  draft, now with a problem, refused ("Fix N problems first"), axe, and "Show the problems";
- at 320 px, `greet` tested alone from its Test tab: its result, its values and output, the bar's step-test line, no
  tags on the other steps, axe light and dark.

The gate fails any CSP violation, console error or request to another origin.

- [ ] **Step 1: Write the specs**

Apply:

```diff
diff --git a/frontend/e2e/fixtures/simulate.dewpoint.json b/frontend/e2e/fixtures/simulate.dewpoint.json
new file mode 100644
index 00000000..38330d33
--- /dev/null
+++ b/frontend/e2e/fixtures/simulate.dewpoint.json
@@ -0,0 +1,23 @@
+{
+  "format": "dewpoint.workflow",
+  "format_version": 1,
+  "name": "Simulate",
+  "graph": {
+    "graph_format": 1,
+    "nodes": [
+      { "id": "8b2d3e4f-5a6b-4c7d-8e9f-0a1b2c3d4e01", "key": "greet", "type": "flow.transform@1", "config": { "fields": { "greeting": { "$value": { "kind": "cel", "expr": "'hello ' + trigger.site" } } } }, "position": { "x": 0, "y": 140 } },
+      { "id": "8b2d3e4f-5a6b-4c7d-8e9f-0a1b2c3d4e02", "key": "check", "type": "flow.if@1", "config": { "condition": { "$value": { "kind": "cel", "expr": "size(trigger.site) > 2" } } }, "position": { "x": 0, "y": 280 } },
+      { "id": "8b2d3e4f-5a6b-4c7d-8e9f-0a1b2c3d4e03", "key": "long", "type": "flow.transform@1", "config": { "fields": { "n": { "$value": { "kind": "cel", "expr": "1" } } } }, "position": { "x": -160, "y": 420 } },
+      { "id": "8b2d3e4f-5a6b-4c7d-8e9f-0a1b2c3d4e04", "key": "short", "type": "flow.transform@1", "config": { "fields": { "n": { "$value": { "kind": "cel", "expr": "2" } } } }, "position": { "x": 160, "y": 420 } }
+    ],
+    "edges": [
+      { "from": { "node": "8b2d3e4f-5a6b-4c7d-8e9f-0a1b2c3d4e01" }, "to": { "node": "8b2d3e4f-5a6b-4c7d-8e9f-0a1b2c3d4e02" } },
+      { "from": { "node": "8b2d3e4f-5a6b-4c7d-8e9f-0a1b2c3d4e02", "port": "true" }, "to": { "node": "8b2d3e4f-5a6b-4c7d-8e9f-0a1b2c3d4e03" } },
+      { "from": { "node": "8b2d3e4f-5a6b-4c7d-8e9f-0a1b2c3d4e02", "port": "false" }, "to": { "node": "8b2d3e4f-5a6b-4c7d-8e9f-0a1b2c3d4e04" } }
+    ],
+    "settings": {
+      "input_schema": { "type": "object", "properties": { "site": { "type": "string", "title": "Site" } }, "required": ["site"] }
+    }
+  },
+  "bindings": []
+}
diff --git a/frontend/e2e/simulation.spec.ts b/frontend/e2e/simulation.spec.ts
new file mode 100644
index 00000000..9f5ce5ad
--- /dev/null
+++ b/frontend/e2e/simulation.spec.ts
@@ -0,0 +1,105 @@
+// SPDX-License-Identifier: Apache-2.0
+// Slice 4d-1c in the browser (the simulation design §7, §8): Simulate workflow and Simulate step against the real stack,
+// its dispatcher and worker, behind nginx, under the served CSP, with axe, light and dark, at 1280 and 320 px. Nothing
+// leaves the stack (D24): the gate fails any request to another origin.
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
+/** The simulation fixture, imported as a new workflow and opened on its canvas alone. */
+async function importSimulate(page: Page, name: string): Promise<void> {
+  await page.goto(`/t/${await tenantId(page)}/workflows`);
+  await page.getByTestId("workflow-new").click();
+  const dialog = page.getByRole("dialog", { name: "New workflow" });
+  await dialog.getByLabel("Name").fill(name);
+  await dialog.getByRole("radio", { name: /Import from file/ }).check();
+  await dialog.getByLabel("Workflow file").setInputFiles("e2e/fixtures/simulate.dewpoint.json");
+  await dialog.getByRole("button", { name: "Import and open" }).click();
+  await expect(page).toHaveURL(/\/workflows\/[0-9a-f-]{36}\?triggers=true$/);
+  await page.goto(new URL(page.url()).pathname);
+  await expect(page.getByRole("button", { name: "No problems" })).toBeVisible({ timeout: 10_000 });
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
+const tags = (page: Page, key: string) => page.getByRole("list", { name: `${key}: simulated result` });
+
+test("a workflow is simulated from its toolbar: the result beside each step, and in the panel", async ({ page }) => {
+  await importSimulate(page, "Simulate A");
+  await page.getByRole("button", { name: "◌ Simulate workflow" }).click();
+  const dialog = page.getByRole("dialog", { name: "Simulate workflow" });
+  await dialog.getByLabel("Site required").fill("HQ Paris");
+  await accessibleBothWays(page, "simulate: the input");
+  await dialog.getByRole("button", { name: "◌ Simulate" }).click();
+  const panel = page.getByRole("complementary", { name: "Simulation" });
+  await expect(panel.getByText("Succeeded", { exact: true })).toBeVisible({ timeout: 60_000 }); // the dispatcher, the worker, the end
+  await expect(page.getByText("Simulated.", { exact: true }).first()).toBeVisible();
+  await expect(tags(page, "greet")).toContainText("succeeded");
+  await expect(tags(page, "check")).toContainText("evaluated · → true");
+  await expect(tags(page, "long")).toContainText("succeeded");
+  await expect(tags(page, "short")).toContainText("skipped");
+  await expect(panel.getByRole("region", { name: "Steps, in run order" })).toBeVisible();
+  await expect(panel.getByRole("region", { name: "Input used" })).toContainText("HQ Paris");
+  await accessibleBothWays(page, "simulate: the result");
+  // Hidden: one bar, the simulation untouched; shown again.
+  await page.getByRole("button", { name: "Hide the result" }).click();
+  await expect(page.getByText(/^Simulation result hidden · Succeeded · revision \d+$/)).toBeVisible();
+  await expect(tags(page, "greet")).toHaveCount(0);
+  await page.getByRole("button", { name: "Show the result" }).click();
+  await expect(tags(page, "greet")).toBeVisible();
+});
+
+test("a result after an edit says so, and a draft with problems isn't simulated (the Stale and Refusals boards)", async ({ page }) => {
+  await importSimulate(page, "Simulate C");
+  await page.getByRole("button", { name: "◌ Simulate workflow" }).click();
+  const dialog = page.getByRole("dialog", { name: "Simulate workflow" });
+  await dialog.getByLabel("Site required").fill("HQ Paris");
+  await dialog.getByRole("button", { name: "◌ Simulate" }).click();
+  await expect(page.getByRole("complementary", { name: "Simulation" }).getByText("Succeeded", { exact: true })).toBeVisible({ timeout: 60_000 });
+  // A step added after it: the result is from before the edit, the new step has none.
+  await page.getByRole("button", { name: "Add a step after long" }).click();
+  await page.getByRole("option", { name: /flow\.transform@1/ }).click();
+  await expect(page.getByText(/^Before your edits: this result is for revision \d+; the draft is at revision \d+\.$/).first()).toBeVisible({ timeout: 10_000 });
+  await expect(tags(page, "transform")).toContainText(/new since revision \d+: no result/);
+  await accessibleBothWays(page, "simulate: a result after an edit");
+  // The new step has problems: simulating the draft is refused, in the server's words.
+  await page.getByRole("button", { name: "◌ Simulate workflow" }).click();
+  await page.getByRole("dialog", { name: "Simulate workflow" }).getByLabel("Site required").fill("HQ Paris");
+  await page.getByRole("dialog", { name: "Simulate workflow" }).getByRole("button", { name: "◌ Simulate" }).click();
+  const panel = page.getByRole("complementary", { name: "Simulation" });
+  await expect(panel.getByText(/^Fix \d+ problems? first: a draft with problems isn't simulated\.$/)).toBeVisible();
+  await accessibleBothWays(page, "simulate: refused");
+  await panel.getByRole("button", { name: "Show the problems" }).click();
+  await expect(page.getByRole("complementary", { name: "Problems" })).toBeVisible();
+});
+
+test("a step is tested alone with its values, at 320 px", async ({ page }) => {
+  await page.setViewportSize({ width: 320, height: 720 });
+  await importSimulate(page, "Simulate B");
+  await page.getByRole("button", { name: /^greet, Transform/ }).click();
+  const drawer = page.getByRole("complementary", { name: "greet" });
+  await drawer.getByRole("tab", { name: "Test" }).click();
+  await drawer.getByLabel("Site required text").fill("HQ Paris");
+  await accessibleBothWays(page, "simulate step: the values, 320 px");
+  await drawer.getByRole("button", { name: "◌ Simulate step" }).click();
+  const result = drawer.getByRole("region", { name: "Result · greet" });
+  await expect(result.getByText("Succeeded", { exact: true })).toBeVisible({ timeout: 60_000 });
+  await expect(result.getByRole("region", { name: "Values used" })).toContainText("HQ Paris");
+  await expect(result.getByRole("region", { name: "Output" })).toContainText("hello HQ Paris");
+  await expect(page.getByText("Step test: greet.", { exact: true })).toBeVisible();
+  await expect(tags(page, "check")).toHaveCount(0); // only the step tested carries a result
+  await accessibleBothWays(page, "simulate step: the result, 320 px");
+  await page.setViewportSize({ width: 1280, height: 720 });
+});
diff --git a/frontend/playwright.config.ts b/frontend/playwright.config.ts
index 5c924f56..bc57ab5d 100644
--- a/frontend/playwright.config.ts
+++ b/frontend/playwright.config.ts
@@ -7,7 +7,7 @@ export default defineConfig({
     { name: "foundations", testMatch: /(foundations|gate)\.spec\.ts/, use: { ...devices["Desktop Chrome"] } },
     {
       name: "workflows",
-      testMatch: /(workflows|triggers)\.spec\.ts/,
+      testMatch: /(workflows|triggers|simulation)\.spec\.ts/,
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
Expected: every spec passes, the three of `simulation.spec.ts` among them. A failure is read and fixed test-first.
If the owner prefers, the specs run in CI's e2e job on the PR instead, and the summary says they weren't run locally.

- [ ] **Step 4: Commit**

```bash
git add frontend/e2e frontend/playwright.config.ts
git commit -m "test(e2e): Simulate workflow and Simulate step in the browser, light and dark, at 1280 and 320 px (4d-1c)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 14: Every check, the ledger, the final checkpoint

**Files:**
- Modify: `docs/superpowers/plans/2026-10-05-editor-ui-4-ledger.md`

- [ ] **Step 1: Every check, and CodeQL**

From `$WT/frontend`:
- `npx --offline pnpm@12.6.0 exec vitest run`: the whole suite (about 2 minutes);
- `npx --offline pnpm@12.6.0 exec eslint .`; `npx --offline pnpm@12.6.0 build` (the type check, then Vite);
- `npx --offline pnpm@12.6.0 check:api`: the API's schema, unchanged since 4d-1b;
- local CodeQL on the head (`scratchpad/codeql/scan-js.sh 4d1c <dir>` on a `git archive` of it): no alert.

Expected, as on the plan's own check (at the top): the suite, 1175 passed in 90 files; ESLint and the type check silent;
the build done, the editor's chunk 502 kB (158 kB gzipped; ruling 18), the entry's 632 kB as on main; `check:api`
passes; CodeQL, no finding.

A failure is read and fixed test-first, or reported as it is: never a claim that every check passes when one didn't.

- [ ] **Step 2: The ledger**

Append `### 4d-1c, milestone 4 and the final checkpoint (date)`: the tasks' commits, each check's result as run (the
suite's counts), whether the e2e specs ran locally or wait for CI, every mid-slice ruling, anything deferred. Commit it
(`docs(editor-4): 4d-1c final checkpoint`).

- [ ] **Step 3: The final review and the pause**

A fresh reviewer, on the most capable model, reviews the whole branch:
- against this plan (its Review Focus first) and the spec's §7 and §8, with the boards;
- with the ledger's rulings in view.

Critical and important findings are fixed test-first, once; minor ones are listed. Then **stop**. The summary to the
owner names what's built, the checks as run, and the rulings proposed and made. It asks for the owner's word on push
and a PR; nothing is pushed before it. CI on the PR runs the backend (about 12 minutes), the frontend, CodeQL and the
Compose e2e: say so before pushing.
