# Sub-project 4 — Editor UI: outline for rulings

- **Status:** draft for the owner's rulings, 2026-10-05. Nothing is built before them.
- **Branch:** `docs/editor-ui-4-outline`, from `origin/main` 6482c53 (#37).
- **Read:** the design export `Dewpoint UI.dc.html` (screens 1a–1i, today's UI 0a–0b, logo variants A–D), as data;
  architecture spec §3.3, §6.8, §10–§14; engine-core spec §3, §5.5, §5.7, §5.10, §8, §12; engine 2b spec §2.1, §4.1,
  §7.7, §8.1; `frontend/` and the API on `origin/main`.
- **Untouched:** 2b-4a (its branches, migrations 0035–0040), sub-project 3's branches, the local `main`, `spikes/`.

## 1. Design screens → slices

| Screen | What it shows | Slice |
|---|---|---|
| 1a | Workflows list: filters, version, last run, 24 h count, enable toggle | 4b |
| 1b | New workflow: trigger first, then Describe it / From template / Blank | 4b (Describe it hidden until 5; D9) |
| 1c | Editor: canvas, + on edges, Add step `A`, auto layout, zoom, minimap; drawer Setup tab, pills, footer | 4b, 4c, 4d |
| 1d | Editor with the assistant and ghost nodes | 5 |
| 1e | Library: curated, team and agent templates | deferred (D9) |
| 1f | Runs list: filters, polling | 4e |
| 1g | Run detail: replay on the canvas, step panel, re-run | 4e ("Explain this failure" hidden until 5) |
| 1h | Approvals inbox | 5 |
| 1i | Settings → Connections (Mist, LLM, MCP sections), add-connection form | 4a, Mist only (D1) |
| 0a, 0b | Today's Connections and Tenants | restyled in 4a |

**Not designed** (D8): Home; the ⌘K palette; the tenant menu; the drawer's Options and Test tabs; simulate results;
the live-step dialog; the run form with CSV mapping; the upstream data tree and pill details; the condition builder;
the diagnostics panel and CEL class badges; trigger setup (manual form and CSV columns, schedule, webhook); the
declassify list (2b §4.1); empty, loading and error states; login, MFA, enroll and security; the development banner.

## 2. Slices

Each slice is shippable on its own branch (D26) and ends at one checkpoint (review, summary, your rulings).

**4a — foundation.**
- Tokens first (you approve them before a slice uses them), fonts and the mark (D2–D7).
- Shell, as designed: a 224 px rail with labels on list pages, a 60 px icon rail in the editor and run detail.
  Items: Workflows, Runs, Connections, Settings; Home, Agents and Approvals hidden (D1, D10). Header: tenant
  switcher, ⌘K, Security, Sign out. The development banner on every screen (2b §2.1, B2).
- ⌘K palette: jump to a workflow, run or page, and "New workflow"; client-side over the cached lists.
- Generated client (B1) replacing `src/lib/api.ts`, keeping CSRF, `ApiError` and step-up.
- Today's screens (login, MFA, enroll, security, tenants, connections) on the new tokens; Settings → Members (D11).
- Harnesses: Playwright fails a flow on any CSP violation or console error; axe checks every screen (D21); a pnpm
  licence check in CI (D22).

**4b — workflows and canvas.**
- 1a list with its filters and the enable toggle (B3); 1b chooser (Blank, Import from file: D9, B12).
- Canvas: React Flow, dagre auto layout on demand, zoom, minimap, node cards with status badges (problems,
  conditional, disabled); "+" on edges and ports; `A` opens the node-type picker (`node_types`, B5).
- Keyboard: every node, edge and "+" reachable and operable without a pointer (D16).
- Draft autosave with `If-Match` compare-and-swap; a 409 never overwrites (D17).
- Validate and publish: a problems panel, per-node badges, focus jumps to the field; CEL class badges with their
  reason (validate returns them today) and the §5.10 messages; the publish confirmation names the version number.

**4c — step drawer.**
- Our JSON-Schema renderer: `x-widget` → component registry, `x-group` order; Setup holds the required fields,
  Options the rest (§10.3); the error-handling chip (`on_error`, retries, timeout).
- Built-in widgets: text, number, boolean, enum, `pill-text`, `cel`, `connection`, list, object, opt-in JSON. The
  widget contract of §3.3: value, schema, upstream scope, options loader.
- Pills: `/` and + Data open the upstream tree (B6) with types and always/conditional markers; pill details open on
  focus + Enter (a popover, never on hover alone): the redacted sample, its run, connection, time and staleness (B7).
- Condition builder → CEL (D18); formula mode behind a toggle; the class badge with its reason.
- Trigger setup: manual input form and CSV columns (§6.8), schedule, webhook endpoint and topic filter (B13), and
  Settings → Webhook endpoints (D11). The declassify list, with what each site reveals (2b §4.1; publish needs
  `workflow.declassify`).

**4d — test semantics.**
- 4d-1: Simulate workflow and Simulate step (D14, B8). Every result says "Simulated · nothing was sent · results
  don't prove the live call will succeed"; each step carries its data-origin tag; the server's checks are listed
  apart; slate with a hatch (D2).
- 4d-2, after sub-project 3 and B9: the live single-step dialog of §10.4 (connection, cloud, org, target and
  where it came from with an override, operation, retries, current → after diff, exact body; a checkbox and the
  target's name, or the count and the org's name). Results labelled Live.

**4e — runs** (after 2b-4a merges: retention cutoffs, erasure and `410 input_not_retained` change what it shows).
- Run form from `start-form` (B11): typed fields; CSV drop zone → upload → column mapping (save as default) →
  preview with errors → skip invalid → "Start run for N rows"; one `Idempotency-Key` per submit, reused on retry.
- 1f list (B10): workflow, status, trigger and time filters; the paging cursor; polling every 5 s while visible.
- 1g detail: the run's version (B4) replayed from `run_steps` (status per node, loop iterations); a step panel with
  redacted input and output previews, attempts, timing and side-effect outcome; cancel; the re-run dialog (D13).
- Home (D10).

**4f — plugin widgets** (after sub-project 3's manifests; against x-widget fixtures until then): the Mist picker
(Resource → Action, live options that accept pills, Find a setting), nested update, the message composer with Slack,
Teams and Google Chat previews, and the run form's connection-scoped pickers (`picker`).

**Helm:** out of sub-project 4 (D25).

## 3. Decisions

Each gives my recommendation (**Rec**). D1–D7 are where the design and §10 differ.

- **D1 Connections.** 1i makes it a Settings tab (with LLM and MCP sections); §10.2 and your slicing make it a rail
  item. Rec: a rail item showing 1i's sectioned page, Mist only until 3 and 5.
- **D2 Simulated.** §10.1: neutral hatched slate. The design: slate (`--sim`) outlines and a "◌" marker, no hatch, no
  simulated-result screen. Rec: slate for simulate controls; simulated results (node badges, test and run banners,
  origin tags) add a hatch (a bundled SVG) and their text label, so colour is never the only signal.
- **D3 Orange.** §10.1: live. The design also uses it for "Awaiting approval" (1a, 1f), the Approvals count and expiry
  text. Rec: orange only where a real call was or will be made (live button, live runs, "real input", re-run).
- **D4 Amber.** §10.1: conditional. The design also uses it for warnings (approval tag, drift, private egress, an
  unbound connection). Rec: amber means "not guaranteed, check this" for both; conditional pills are also dashed, end
  in "?" and say "conditional" to assistive technology.
- **D5 Green.** Not in §10.1's list. The design: `--ok` for succeeded, verified and saved; brand `#84b135` in the mark,
  the "Engine healthy" dot and Library's sub-nav. Rec: `--ok` for success only; brand green only in the mark.
- **D6 Accent and theme.** The design's light theme declares the accent trio twice; the later wins: #0b7c8c / #075e6b
  / #e0f2f4 (repo: #0e6874 / #0a4f58 / #e3f0f1); white on #0b7c8c is about 4.9:1 (6.3:1 today). Rec: the design's
  effective values; a unit test holds every text/background pair to 4.5:1 (borders 3:1) in both themes. Theme
  follows the OS, with a header toggle kept in localStorage.
- **D7 Type and mark.** The design: Schibsted Grotesk (headings), Instrument Sans (UI), JetBrains Mono (keys, IDs,
  CEL), loaded from Google Fonts in the mock, which the CSP forbids; logo variant B ("Condensation"). Repo: IBM Plex
  and a drop outline. Rec: the design's fonts bundled through @fontsource (OFL-1.1, like IBM Plex, which goes), Latin
  subsets; mark B as an SVG component.
- **D8 Undesigned screens** (§1). DesignSync can't reach the project from here. Rec: before 4c, 4d and 4e you extend
  the design for their high-risk gaps (Test tab and simulate results, live dialog, run form with CSV, data tree and
  pill details, condition builder) and export it; the low-risk ones (Home, ⌘K, empty states, auth screens) I build in
  the design's grammar for your ruling at the checkpoint.
- **D9 Library and templates.** 1e has no backend; the spec has only export and import of templates (§4.1); "Used by
  212 tenants" is a cross-tenant figure v1 has no level for. Rec: defer 1e and "Browse library"; 4b ships Blank and
  "Import from file" (B12); "From template" waits for curated templates shipped as plugin data; no usage counts.
- **D10 Home and the rail footer.** No Home design, no summary API; "Engine healthy · worker ok" would show platform
  health to every tenant user, and no route reads it. Rec: Home hidden until 4e, landing on Workflows; no health
  footer in v1; the development banner (B2) stays.
- **D11 Settings tabs** (1i). Rec: Members & roles (4a) and Webhook endpoints (4c), whose APIs exist; Notification
  channels with sub-project 3; Service grants with 5; Security stays the per-user page behind the header link.
- **D12 Live button.** 1c shows a filled orange "Run step against Mist…" first in the footer, on an AI agent step.
  Rec: Simulate step first; live as an orange outline, rendered only for node types that support a live test once
  B9 exists; no disabled teaser before that.
- **D13 Re-run.** The API re-runs on the workflow's **active** version, which may not be the run's (2b §7.7); 1g's
  "Re-run with same input…" hides that. Rec: a dialog naming the version, mode and input source; on
  `410 input_not_retained` it offers new input.
- **D14 Simulating a draft.** `mode: simulate` runs only the active published version (`apps/admission.py`); nothing
  simulates a draft or one step, and publishing to test would activate its triggers. Rec: a short engine design
  before 4d (draft snapshots that can never activate, single-step runs, skipped steps projected), with a migration
  slot from you (B8).
- **D15 Generated client.** Rec: openapi-typescript + openapi-fetch (typed by path, so operation ids don't matter);
  the schema dumped by a CLI, committed, and CI fails on drift (B1).
- **D16 Keyboard canvas.** Rec: roving focus over nodes in graph order; arrows follow edges; Enter opens the drawer;
  `A` adds after the focused node; Delete asks; Esc returns focus; a live region announces changes; React Flow's own
  keys kept only where they don't trap focus.
- **D17 Draft saves.** Rec: autosave 1 s after the last change with `If-Match`; a 409 turns the editor read-only
  ("changed elsewhere": reload, or download my version); undo and redo local. Validate runs on the saved revision,
  the only one the API checks.
- **D18 Condition builder.** Rec: its state is a small AST serialized to CEL in the browser; only CEL it produced
  reopens in it, anything else opens formula mode; the server alone checks and classifies.
- **D19 Editors.** Rec: our own pill editor over the `template` value (`parts: text | ref`), pills as atomic buttons;
  formula mode is a monospace textarea with the server's diagnostics. No CodeMirror or Monaco (both inject `<style>`
  at run time, which the CSP refuses) and no ajv: only required and type hints run in the browser.
- **D20 Redacted values.** 1g shows `"token": "••••••••"`; the API sends `"[redacted]"` and `"[truncated]"`
  (engine-core §8). Rec: those markers render as chips; the client never masks, never receives the value, and keeps
  no sample in browser storage.
- **D21 Accessibility.** Rec: @axe-core/playwright (MPL-2.0, dev only, not shipped) on each e2e screen; keyboard flows.
- **D22 Licence check.** CI checks only Python today (a denylist). Rec: a CI step over `pnpm licenses list --json`:
  production deps allowlisted (MIT, ISC, BSD-2/3-Clause, Apache-2.0, 0BSD, OFL-1.1 for fonts), dev deps may add
  MPL-2.0; no new tool.
- **D23 CSP.** It stays `style-src 'self'`, no `'unsafe-inline'`. Known risk: Radix Dialog's scroll lock
  (react-remove-scroll, also inside cmdk) injects a `<style>`. Rec: 4a's harness checks every library in the browser;
  if one violates, I stop and bring options (a per-request nonce from nginx, or no scroll lock).
- **D24 Tests without plugins.** Rec: unit tests render widgets from x-widget fixture manifests; e2e drives only the
  flow plugin's nodes against Compose's development environment; no Mist or SaaS call, ever.
- **D25 Helm.** Rec: out of sub-project 4 until 2b-4b's readiness checks, D12's production-Temporal ruling (on `main`,
  2b spec §10.4 still lists Temporal Cloud) and an approved evaluator network transport (engine-core §5.7, §12.4).
- **D26 Branches and order.** Rec: a worktree and branch per slice (`feat/editor-4a`…), stacked on the previous one
  until it merges, then rebased on `origin/main`; rulings in `2026-10-05-editor-ui-4-ledger.md`. Order: 4a, 4b, 4c,
  4d-1 (after D14's design), 4e (after 2b-4a), then 4d-2 and 4f (after sub-project 3).

## 4. New npm dependencies (registry versions today; transitive licences checked again at install)

| Package | Version | Licence | Use | Slice |
|---|---|---|---|---|
| @fontsource/instrument-sans | 5.3.0 | OFL-1.1 | UI text (replaces @fontsource/ibm-plex-sans) | 4a |
| @fontsource/schibsted-grotesk | 5.3.0 | OFL-1.1 | headings, wordmark | 4a |
| @fontsource/jetbrains-mono | 5.3.0 | OFL-1.1 | keys, IDs, CEL (replaces @fontsource/ibm-plex-mono) | 4a |
| openapi-typescript (dev) | 7.13.0 | MIT | generates `schema.d.ts` from the API's OpenAPI | 4a |
| openapi-fetch | 0.17.0 | MIT | typed fetch over that schema (+ openapi-typescript-helpers, MIT) | 4a |
| cmdk | 1.1.1 | MIT | ⌘K palette (its deps are Radix, already used) | 4a |
| @axe-core/playwright (dev) | 4.13.0 | MPL-2.0 | WCAG checks in e2e (D21) | 4a |
| @xyflow/react | 12.12.0 | MIT | canvas (+ @xyflow/system, zustand, classcat MIT; d3-drag/zoom/selection ISC) | 4b |
| @dagrejs/dagre | 3.1.1 | MIT | auto layout (+ @dagrejs/graphlib, MIT) | 4b |
| @radix-ui/react-tabs, -popover, -switch, -checkbox | 1.1.21, 1.1.23, 1.3.7, 1.3.11 | MIT | drawer tabs, pill details, enable toggle, confirmations | 4b, 4c |

Not proposed: elkjs (EPL-2.0 or GPL-3.0), CodeMirror, Monaco, ajv (D19), react-jsonschema-form (§10.1: our own
renderer), MSW, papaparse (the API parses CSV). pnpm 12.6.0 runs as the cached `npx pnpm@12.6.0`: nothing to install.

## 5. Backend work the UI needs

Each is its own test-first change with its role × endpoint matrix rows and RLS tests; only B7–B9 may need a
migration (a slot from you). Today no route sets `response_model`.

| # | Slice | Change | Migration |
|---|---|---|---|
| B1 | 4a | OpenAPI for the client: a CLI dumps it without a server; unique component names (two `CreateIn`, two `PatchIn`); the `Graph` model on the draft PUT; `response_model` on each route as its slice adopts it; CI regenerates `frontend/src/api/schema.d.ts` and fails on drift | no |
| B2 | 4a | `GET /api/v1/platform/status`: environment and whether production runs are on, for the banner and for explaining a refusal before a start | no |
| B3 | 4b | Workflow list summary: last run (status, time), runs in 24 h, unpublished changes (draft hash ≠ active `graph_hash`), needs attention. Rec: "Unpublished changes" without 1c's edit count, which would need a column | no |
| B4 | 4b, 4e | `GET …/workflows/{wid}/versions/{vid}` with the graph and its expression classes: run detail replays the run's version, which no route returns | no |
| B5 | 4b, 4c | `/node-types` adds side effect, credentials, capabilities, retry and timeout defaults (Options defaults, connection picker, D12) | no |
| B6 | 4c | Draft scope: every ref available at a node, with type, always or conditional, and sensitive, from the validator's liveness analysis (today it only shows in diagnostics) | no |
| B7 | 4c | Samples: a step's latest redacted output preview (by node id) with its run, mode, version and time, from `run_steps` | maybe an index |
| B8 | 4d-1 | Draft and single-step simulation (D14), after its design | likely |
| B9 | 4d-2 | Live single-step test, after sub-project 3: a preview call (target and source, diff, exact body) and an execute call that checks the typed target name, or count and org name, plus capability and scope **on the server** | with 3's design |
| B10 | 4e | Runs list: status, mode, source and time filters, the workflow's name per item, a next cursor | no |
| B11 | 4e | CSV: read the saved default mapping; re-preview a staged upload under a new mapping | no |
| B12 | 4b | Workflow export and import as JSON, connections replaced by typed placeholders and re-bound on import (D9) | no |
| B13 | 4c | Webhook bindings per workflow, for the trigger drawer | no |

Seen, not proposed here: `connection.use`, `approval.decide` and `agent.grant` are defined but no route checks them;
`/api/v1/openapi.json` is served without a session (B1 could serve it only in development).
