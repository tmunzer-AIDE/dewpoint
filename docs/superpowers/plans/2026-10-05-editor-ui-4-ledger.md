# Sub-project 4 — Editor UI: rulings ledger

Rulings on the outline (`2026-10-05-editor-ui-4-outline.md`, revision 4, cc8b01c), and every ruling taken mid-slice.
Mid-slice entries use the form "Ruling: <what> - <why> - <cost if wrong>" and wait for the owner at the checkpoint.

## Owner rulings, 2026-10-05

They came as pasted text, plus the owner's own chat message approving D27. Per the standing rule, pasted rulings
cover local work only: anything outward-facing (push, PR, issues) is confirmed in chat first.

| Item | Ruling |
|---|---|
| D1–D7 | Adopted: navigation, semantic colours, bundled fonts, mark B. Final token values wait for the specimen's approval, including focus, hover, disabled, error and selected states. |
| D8 | I draft the undesigned screens in the design's grammar. The high-risk flows are approved before their slices: simulation, live confirmation, CSV mapping, data tree and pill details, condition builder. |
| D9–D13 | Accepted: the deferrals, the Settings structure, simulate first, version-bound run confirmation. |
| D14 | A separate engine design, not an implementation shortcut. Draft snapshots never activate triggers. Execution, provenance and retention semantics are settled before B8. |
| D15–D22 | Accepted. |
| D23 | The CSP stays. Prefer a CSP-compatible library configuration or implementation. A nonce-based policy is a separate decision; nothing is relaxed automatically. |
| D24 | No real Mist or SaaS calls. Plugin-dependent flows also get integration tests against local fakes; widget fixtures alone don't cover them. |
| D25–D26 | Helm deferred; slice order and checkpoints kept. |
| D27 | Owner, in chat: commit the export under `docs/design/`, without support scripts, unrelated exports or sensitive data, never served. Done: `docs/design/2026-10-05-dewpoint-ui.dc.html` (unchanged bytes) and its README. |
| Token gaps | I fill them; light and dark specimen pages for approval. No separate Claude Design pass. |
| npm | The 13 packages of the outline's §4, at their recorded versions, each installed when its slice needs it. Approval holds only if the resolved transitive licences pass D22's policy; an unexpected licence goes to review, never to an allowlist exception. |

## Migration slots

2b-4a holds 0035–0040; the plugin outline reserves 0041–0042. These numbers reserve ownership, not order.

| Slot | Work |
|---|---|
| 0043 | B4b: `skipped` and `not_started` projection statuses |
| 0044 | B8: draft and single-step simulation |
| 0045 | B7: per-attempt connection provenance, with sub-project 3 |
| 0046 | B9: preview consumption and durable live-test execution |

- One Alembic chain: before merging, the first unmerged migration's `down_revision` is reconciled with the actual head.
- Deployed migrations are never rewritten; 0035–0042 are never altered.
- A design that needs more migrations gets more slots, never an overloaded one.

## Mid-slice rulings

### 4a, token pass (2026-10-06)

1. Ruling: input, checkbox and switch boundaries and canvas edges use a new `--line-control` (#7a817b, dark #788088),
   not the design's `--line-strong` (1.57:1) - WCAG 1.4.11 wants 3:1 for a control's boundary and for graphics that
   carry meaning - inputs and edges look a little heavier than the mock.
2. Ruling: text on filled live and danger buttons is dark in the dark theme (`--on-live`, `--on-danger`), not the
   design's white (2.1:1 and 2.7:1) - AA text contrast - dark filled buttons read differently from light ones.
3. Ruling: the accent is a fill and ring colour; accent text uses `--accent-ink` - `--accent` on the light ground is
   4.49:1 - none visible.
4. Ruling: the current rail item's white text is a token (`--rail-ink-strong`), not a raw colour - the guard bans
   colours outside `tokens.css` - none.
5. Ruling: the simulated hatch is a bundled SVG mask, never a CSS gradient, and simulated text is held to 4.5:1 over
   it - the guard bans `gradient` outright - a mask needs an evergreen browser.
6. Ruling: JetBrains Mono's ligatures are off for code (`code`, `kbd`, `pre`, `samp`, `.font-mono`) - the specimen
   drew CEL's `!=` as one `≠` glyph, which misleads anyone reading or typing an expression - none.
7. Ruling: the dialog shadow is `0 8px 24px` at 14 % (dark 50 %), not the design's `0 20px 60px` at 25 % - outline §6
   - dialogs float a little less.
8. Ruling: hover on the rail is `--rail-line`, the current item `--rail-active` with strong ink and weight 500 - the
   design shows only the current item - hover and current are close; the weight and `aria-current` tell them apart.
9. Ruling: Tailwind no longer scans test files for class names - the guard's fixtures (`bg-indigo-500`,
   `shadow-xl`…) were shipping 6 KB of banned utilities - none.
10. Ruling: tests read stylesheets as text through vitest's `css.include` - no `@types/node` dependency for `fs` -
    none.
11. Ruling: the specimen runs from a background Vite on 127.0.0.1:5181, not `.claude/launch.json` - the main
    checkout stays untouched - it isn't in the app's preview list.
12. Ruling: screenshots used the cached Chromium build 1234 through `executablePath`; the locked Playwright wants
    build 1243, which isn't installed - installing it is a tool install, left for the owner - 4a's e2e harness (CSP
    and axe checks) can't run until it's installed or pinned to a cached build.
13. Ruling: the three font packages are saved at exact versions (pnpm 12's default) - "at their recorded versions" -
    none.
14. Ruling: the theme and base styles live in `styles/theme.css`; the app's entry (`app.css`) and the specimen's
    (`specimen/specimen.css`) each import it, and the app's scan skips the specimen - the specimen's utilities had
    grown the shipped stylesheet from 17.7 to 25.7 KB - none.

### Owner, 4a token checkpoint (2026-10-06, pasted)

- Token approval held for one failure: the light outline live button pressed (`live` on `surface-pressed`) was
  4.43:1 and missing from `PAIRS`. Fix it, and cover every rendered default, hover and pressed combination.
- The figures were stale: 50 pairs a theme then (not 49), smallest margin 2.8 % (sim on the hatch), not 8 %.
- Migrate the MFA recovery toggle's `text-accent` to `text-accent-ink`.
- Direction of rulings 1–7, 9–11, 13–14 accepted. Ruling 8: confirm the current rail item stays visibly apart from
  hover (`aria-current` isn't visible). Ruling 12: install Chromium 1243 for the locked Playwright; no repinning;
  build 1234 only for provisional screenshots.
- Final visual approval and the CSP/axe browser gate remain open.

### 4a, after the token checkpoint (2026-10-06)

15. Ruling: button states are data (`BUTTON_STATES` in `styles/tokenNames.ts`), drawn by the specimen and, next, the
    Button component; every default, hover and pressed text-on-background pair joins `PAIRS` from it - the 4.43:1
    pair escaped a hand-kept list - none.
16. Ruling: the outline live button's pressed text is `--live-hover` (5.67:1, dark 6.99:1) - `live` on
    `surface-pressed` was 4.43:1 - its pressed text is a shade darker than its resting text.
17. Ruling: a new `--danger-pressed` (#861a12, dark #f59a92) - the filled danger button pressed like hover - none.
18. Ruling (revises 8): hover on the rail is 5 % white, the current item 18 % with white ink and weight 600, a 1.5:1
    step between the two backgrounds that tokens.test.ts holds - the design's 8 % and 10 % differed by 1.06:1 -
    the current item is brighter than the mock's.
19. Ruling: the hatch sits only behind slate text (`text-sim`), and a guard rule (`hatch-text`) fails a class list
    that draws it without; a simulated node is a slate-tinted card with a hatched "fixture" tag - grey text on the
    hatch was 4.21:1 (dark 4.20:1), a failure the review hadn't listed - less hatch on the canvas than a fully
    hatched card.
20. Ruling: a guard rule (`accent-text`) fails `text-accent`; the MFA recovery toggle and the old shell's logo moved
    to `text-accent-ink` - the accent is 4.49:1 on the light ground - the logo's drop is a shade darker until the
    shell is rebuilt.
21. Ruling: `@axe-core/playwright` 4.13.0 installed (dev; it and `axe-core` 4.13.0 are MPL-2.0, as D22 allows for
    dev) to cross-check the specimen: colour contrast in Chromium 1243 passes 236 rendered elements a theme with no
    violation; the 7 hatched elements a theme are "incomplete" (axe can't read a pseudo-element background) and are
    covered by `sim` on `sim-hatch` - none.
22. Figures now: 59 pairs a theme (118), none under its floor; the smallest margin is `sim` on `sim-hatch`, light,
    4.627:1 (+2.8 %).

### Owner, tokens approved (2026-10-06, pasted)

- Tokens and visual direction approved at 4de186f, with rulings 15–22. Next: wire them into 4a, and the real-app
  CSP/axe gate behind nginx: estimate before Compose, an isolated Compose project, the CSP unchanged. Token approval
  doesn't close the 4a checkpoint or authorize a push or PR.

### 4a, the browser gate (2026-10-06)

23. Ruling: the gate is a Playwright fixture every e2e test runs under (`e2e/gate.ts`): a test fails on a CSP violation,
    a console error, a page error or a request to another origin; `expectAccessible` runs axe (WCAG 2.2 AA tags) on
    each screen; three self-tests prove each catch under the served CSP. The browser's console line for an API's 4xx
    answer is ignored (it's the API's contract: a wrong password, no session); 5xx stays a problem - a 4xx the UI
    mishandles would surface elsewhere - a 4xx the UI should never trigger isn't flagged by the gate.
24. Ruling: the isolated stack is the 4a worktree's Compose files plus a scratchpad-only override: project
    `dewpoint-ui4a`, web on 127.0.0.1:18080, Temporal's port unpublished, images tagged `:ui4a`, the hooks subnet
    172.31.254.248/29, no ingress profile (nginx resolves it lazily; /hooks answers 502), fresh secrets in a 0600
    scratchpad file, the CSP unchanged. A gate run (rebuild, fresh database, admin, e2e) takes about 1.5 minutes -
    nothing is shared with other stacks - none.
25. Ruling: the tenant menu is non-modal (`modal={false}`). The gate's first run caught both faults of the modal
    one: its scroll lock injects a `<style>` the CSP refuses, and axe's `aria-hidden-focus` (it hides the page while
    it stays focusable). This is D23's library configuration, no CSP change - the menu no longer locks page scroll.
26. Ruling: input patterns escape a class's `-` (the tenant slug and the org ID): browsers compile `pattern` with the
    `v` flag, where the old patterns were invalid, so the fields validated nothing; a unit guard compiles every
    pattern that way - none.

### 4a, the shell and today's screens (2026-10-06)

27. Ruling: the rail shows only destinations that exist: Connections now; Settings arrives with its Members tab,
    Workflows with 4b, Runs with 4e - no empty placeholder pages - the rail looks sparse until then.
28. Ruling: the Tenants page leaves the rail (the design has none) and is reached from the tenant menu's new "All
    tenants" item, and as the landing page without a tenant - the design's header owns tenant choice - one more
    step for a platform admin creating tenants.
29. Ruling: the add-connection form is a side panel, as in 1i, with a form landmark ("Add Mist connection") rather
    than `role="dialog"`: it is not modal and doesn't trap focus; its first field takes focus when it opens - none.
30. Ruling: Connections has no "Used by" column (1i shows "5 workflows"): no API counts it yet - one column short of
    the design until workflows exist.
31. Ruling: the org ID shows in full, not truncated in the middle as in 1i - it's copied and compared whole - a wider
    table.
32. Ruling: off a tenant's routes (Security, Tenants), the switcher reads "Choose tenant": the current tenant lives
    only in the URL - no stored state - one more click back to a tenant after Security.
33. Ruling: buttons centre their label; full-width buttons stay only on the centred sign-in screens; form actions
    elsewhere align to the start, as in 0b - none.
34. Ruling: the add-connection form's button says "Save", not 1i's "Save and verify": saving doesn't verify, and
    verifying calls Mist with the token, which no test may do - one more click to verify a new connection.
35. Ruling: the frontend licence gate (D22) is `frontend/scripts/licence-check.mjs` (with a self-test), run in CI's
    frontend job. It holds production dependencies to MIT, ISC, BSD-2/3-Clause, Apache-2.0, 0BSD and OFL-1.1, and
    the whole tree to that plus MPL-2.0, as ruled. It fails today on six licences, all from dependencies older than
    4a, which the owner reviews; no exception was added: production `Unlicense` (`isbot` 5.2.2, from TanStack
    Router); dev `BlueOak-1.0.0` (`minimatch` 10.2.6), `CC-BY-4.0` (`caniuse-lite`), `MIT-0`
    (`@csstools/color-helpers` 5.1.0), `Python-2.0` (`argparse` 2.0.1), `Unlicense` (`isbot`) - the frontend CI job is
    red until the owner rules.
36. Ruling: the ⌘K palette (cmdk 1.1.1, approved; MIT, no new licence) is cmdk's `Command` inside a native modal
    `<dialog>`, never cmdk's `Command.Dialog`, which is Radix Dialog with its style-injecting scroll lock (D23). The
    native dialog moves focus in and back, makes the page inert and closes on Escape. It lists "Go to" (Connections,
    Security, All tenants) and every tenant; later slices add theirs. The trigger is 1a's header search box - the
    palette itself is a D8 gap built in the design's grammar - its look is the owner's to rule at the checkpoint.
37. Ruling: the palette focuses its search field itself, right after `showModal()`: React's `autoFocus` ran while the
    dialog was closed, so keys went to the dialog (the browser gate's first palette run caught it; jsdom can't). Test
    setup stands in for what jsdom lacks (a modal dialog's open and close, ResizeObserver, scrollIntoView,
    scrollTo); the browser gate checks the real ones - none.
38. Ruling (B2): `GET /api/v1/platform/status` answers signed-in sessions only, with the environment (null until
    recorded) and whether production runs are on, never the Temporal namespace. The shell shows an amber note,
    "Development deployment", on every signed-in screen of a development deployment; the browser gate checks it on
    the dev stack. The sign-in screens (login, MFA, enrolment) don't show it: that would take an unauthenticated
    endpoint - the label is missing there until the owner wants one.
39. Ruling (B1): the routes live in one tuple (`apps/api/openapi.py`) that the app and `dewpoint api openapi` share;
    a test holds the printed schema to the served one. The two `CreateIn` and `PatchIn` pairs are renamed per module
    (`Connection…`, `Workflow…`). Slice 4a's routes (auth, MFA, passkeys, tenants, members, connections, platform
    status) declare response models (`apps/api/responses.py`) that forbid extra keys; where an answer omits a key
    (a tenant's `role`, a type's `clouds`) `response_model_exclude_unset` keeps the JSON as it was - the existing
    API and core suites (434 tests) pass unchanged - routes of later slices get theirs as those slices adopt them.
40. Ruling (D15): the client is openapi-fetch 0.17.0 over types from openapi-typescript 7.13.0 (both approved),
    generated with `--default-non-nullable false` so request fields the server defaults stay optional. `src/api/
    openapi.json` and `schema.d.ts` are committed; CI fails when either drifts (backend: the dump against the copy;
    frontend: `pnpm check:api`). `ok()` keeps ApiError and the CSRF handling; `src/lib/api.ts` is gone. A
    connection's `config` is free-form per type in the API, so Connections reads a Mist one through a local
    `MistConfig` - none.
41. Ruling: the licence check reads SPDX expressions: `A OR B` passes when either is allowed, `A AND B` when both are.
    `type-fest` (via openapi-typescript, dev) is `(MIT OR CC0-1.0)` and passes under MIT - the owner may want such
    choices listed for review instead.
42. Ruling (D11): Settings is a rail item; its tabs are links, as in 1i, with one tab in 4a (Members & roles), and
    `/t/$tenantId/settings` goes to it. Every member reads the list; only admins and owners see the add form, the
    role selectors and Remove, and the API decides every write. Its refusals read plainly (no such account, the last
    owner, owner-only). An admin's role selector offers "owner", which the API refuses (`owner_only`) - one refused
    click before the message explains it.
43. Ruling: removing a member asks first, in a native modal dialog (D23) whose focus starts on Cancel, naming who
    loses access to which tenant; the browser gate opens it, runs axe and closes it with Escape. `Button` takes a ref
    (React 19's `ComponentProps<"button">`) - none.

### 4a, the pre-checkpoint review (2026-10-06)

A fresh-context reviewer read 3cc32fa..cfe2c14 against the owner's checklist: nothing critical; six important and
thirteen minor findings. What became of each:

44. Fixed: I1, the licence step stopped the frontend job and so the e2e browser gate; it is now its own job
    (`frontend-licences`), still red until the owner's review. I2, the palette's selected option showed only a 1.2:1
    fill; it now carries the 3:1 focus outline. I3, the gate exempted a 4xx on any resource; only the API's answers
    are exempt now, and a failed font, script or image is a problem (a self-test proves it). I4, the guard missed
    Tailwind v4's gradients (`bg-linear-*`, `bg-radial-*`, `bg-conic-*`), side stripes (`border-s-*`, `border-e-*`),
    non-token shadows, text shadows and motion over 150 ms; it catches them now. I5, D6's theme choice was missing:
    a header select (system, light, dark) remembered in this browser, applied before the first paint.
45. Ruling: I6 isn't 4a's: the API (and every process) logs unhandled errors with structlog's defaults, a traceback
    with local variables, so a password or a CSRF token can reach the logs. It is on `main` today; a separate task
    configures logging without locals, with a regression test - the leak stays until that task merges.
46. Fixed (minors): base rules moved into `@layer base`, so a utility can override them, and the palette's field draws
    an inset ring (M1); placeholders in muted ink (M2); focus returns to the opener when the add-connection form
    closes, and to the members heading after a removal (M3); Cancel forgets a typed token (M4); the licence check
    fails closed on mixed AND/OR (M5); each screen sets its title (M6); the shell reflows to 320 px (M7: below `lg`
    the rail is the design's 60 px icon rail, the header wraps, tables scroll in their frame, side panels stack; the
    gate checks four screens at 320 px); an unreadable environment shows a note instead of nothing (M8); the members
    list is headed "Members" (M9); Security's re-authentication is a named form that focuses its field (M10);
    ConfirmDialog reports a cancel only when the user cancels (M13).
47. Ruling (M11): the `Graph` model on the draft PUT waits for 4b, the slice that edits drafts, as ruling 39 has each
    slice adopt its routes' models - the draft PUT's body stays a free-form object in the schema until then.
48. Ruling (M12): axe now also checks the open add-connection form, a refused member addition and the authenticator
    setup; the step-up banner isn't reached (it needs a tenant that requires passkeys, and a session without one) -
    its contrast rests on the warn pair in PAIRS until a later slice's e2e reaches it.
49. Not mechanised, left to the checkpoint reviewer's eye: the pill shape off data pills (`rounded-full`,
    `rounded-pill`) and "!" in UI copy - the guard can't tell a data pill or a code sample from decoration.
