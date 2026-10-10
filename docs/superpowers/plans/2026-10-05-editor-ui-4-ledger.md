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
| 0043 | Used on main (2b-4, `0043_fence_fails_closed`); it had been reserved for B4b, now 0048 |
| 0044 | Used on main (`0044_orphan_backoff`); it had been reserved for B8, now 0049 |
| 0045 | B7: per-attempt connection provenance, with sub-project 3 |
| 0046 | B9: preview consumption and durable live-test execution |
| 0047 | 4b: `runs_workflow_last` (ruling 72; merged in #60, chained after 0044: M36) |
| 0048 | B4b: `skipped` and `not_started` projection statuses (the owner, 2026-10-08) |
| 0049 | B8: draft and single-step simulation (the owner, 2026-10-08) |

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
50. Fixed: the 320 px check measured before the lists loaded, so it passed while connections scrolled 166 px sideways
    and members 41 px. A table header's screen-reader-only label (absolutely positioned) had no positioned ancestor,
    so the page held it, not the table's scrolling frame. The frame is positioned now; the check waits for the network
    to settle before measuring and failed red on connections first.
51. Fixed: a list that fails to load says so in its place ("… couldn't be loaded. Reload the page to try again.",
    `LoadError`, an alert) - Connections, Members, Tenants and Security's passkeys showed an empty list, which reads
    as "none"; Security no longer draws an empty bordered list while its passkeys load (the checkpoint screenshot
    showed it as a stray line) - none.
52. Ruling: the development banner appears when the platform status answers, so a development deployment's first
    full page load moves the page down once; production shows no banner, so it never moves - a one-time shift on
    development stacks.

### 4a, a second fresh-context review (2026-10-06)

A second reviewer read the fixes (e8e9bf4, ae52c6c) against rulings 44-50: nothing critical, six minor findings and
three gaps in what the fixes claimed. What became of each:

53. Fixed (finding 3, WCAG 1.4.11): below `lg` the rail shows icons only, so no bold label marks the current item; its
    fill there is a new `--rail-current` (40 % white: 3.72:1 off the rail, dark 3.81:1; the white icon on it 4.38:1,
    dark 4.81:1), held in PAIRS. From `lg` up, ruling 18's 18 % fill and weight stay - a heavier tile on the icon
    rail; a different cue (a ring) would be one token.
54. Fixed (finding 2, WCAG 2.1.1): a table's scrolling frame is a named region that takes focus, so the keyboard can
    scroll a table that holds nothing focusable (an empty list, Members as a viewer sees it) - one more Tab stop per
    table.
55. Fixed (finding 1): Security gives focus back to the button that asked for re-authentication, when the prompt is
    cancelled or done; the authenticator setup's start button takes focus when the button that opened it gives way,
    and its code field when the setup appears (in enrolment too) - focus never falls to the page's body there.
56. Fixed (finding 4): ConfirmDialog holds while its action runs - Escape is refused, Cancel is off - and Members moves
    focus to the list's heading once a removal is done, however the dialog closed (Chrome closes it on a second
    Escape regardless); the flag that outlived it is gone.
57. Fixed (finding 5): the AI-tells guard also catches bare `shadow` and `blur`, durations over 150 ms or arbitrary,
    stripes on the right or on facing sides, Tailwind's mask fades, outlines over 2 px or in a soft colour, and in a
    stylesheet any box-shadow but a token's, side borders over 1 px, long transitions and animations, and keyframes of
    our own. `shadow-none` now passes. Each has a test case; the sources pass unchanged.
58. Fixed (finding 6): each axe check in the e2e waits for its screen's own content (the login form, the QR code, the
    tenant and connection lists, Security past its session check); the 320 px check waits for each screen's data
    and banner rather than for the network to settle; the saved token is looked for in field values too.
59. Fixed (gaps in 44 and 46): the remembered theme is applied by `public/theme.js`, a classic script in `<head>`
    served from 'self' (the CSP is unchanged), so it is set before the first paint rather than after the deferred
    bundle; a gate self-test proves a 4xx console line from anything but the API is a problem (it fails against the
    old exemption); the base-layer test checks its rules sit inside the layer and nowhere else.

### Owner, 4a checkpoint (2026-10-06, pasted)

- 4a's look approved, the palette, the confirmation dialog and Members included (no separate design pass); 124
  contrast pairs pass. The push held for one finding: a connection draft survived a tenant switch and saved to the
  other tenant (ruling 60).
- Licences: exceptions approved for exactly `isbot@5.2.2` (Unlicense, production and the whole tree),
  `minimatch@10.2.6` (BlueOak-1.0.0), `caniuse-lite@1.0.30001810` (CC-BY-4.0), `@csstools/color-helpers@5.1.0`
  (MIT-0) and `argparse@2.0.1` (Python-2.0), the last four dev-only - not the licences in general. Licence texts,
  copyright and attribution notices are kept, with change notices if licensed material is modified; a scope
  promotion or a version change goes back to review.
- SPDX: `OR` passes when an allowed alternative is selected, and the check reports it (`type-fest → MIT`); `AND`
  needs every licence; unsupported expressions fail closed.
- The 406 serial backend tests: time about 20 representative ones, expensive fixtures included, and report the
  timing and an estimated range before running all 406.
- Push and PR after the tenant-switch fix and passing local checks: `[skip ci]` on the next genuine checkpoint
  commit, no amended commits; record that Actions did not run. No merge ruling on #41 from this review.

### 4a, after the checkpoint (2026-10-06)

60. Fixed: a tenant's screens (Connections, Settings and Members) are keyed by the tenant in the router, so switching
    tenants mounts them afresh - the router alone reuses a screen whose route stays and only its parameter changes.
    Nothing typed for one tenant (a token, an email) can be saved to another, and a save still on its way for the old
    tenant lands on a screen that is gone, never on the new tenant's form. Tests on the app's own routes cover an
    unsaved draft, an in-flight save and a member being added; with the key removed, the two connection tests fail.
61. The licence exceptions are in `scripts/licence-check.mjs` as the owner listed them: name, version, licence and
    scope must all match (a dev-only package in the production list fails), and each applied exception and each OR
    choice is reported. Notices: none of the six ships - `isbot` is imported only by TanStack Router's server-side
    stream renderer, which this app doesn't use, and a build holds none of its code; the dev-only five are build
    tools and data - and none is modified, so no notice or change notice is due today; if one starts to ship, it
    goes back to review. Open, for the owner: the bundle keeps React's `@license` comments, but most MIT packages
    carry none, so the shipped bundle doesn't reproduce their notices; a generated third-party notices file would.
62. The serial group's sample: 23 of the 406 (each gate file's expensive test - cost, determinism, replay, hostile
    bombs, task cost, estimator - each evaluator file, one test from each other file but four small ones): 22 passed
    and 1 skipped (`test_limits.py` is Linux only: its 7 tests skip on macOS) in 47 s, of which about 32 s is
    collection and imports. The slowest: the replay in five processes 5.0 s, the task cost 3.5 s setup and 2.4 s.
    Estimate for all 406 here: 2 to 5 minutes. Not run until the owner says.
63. `main` moved on to 15084df (plugins-3a-1, #40), so the branch merges it - a merge commit; no commit rewritten.
    One textual conflict, the CLI: both command groups kept (`platform egress`, `api openapi`). One semantic break:
    3a-1's GET of one connection adds `cooldowns`, which 4a's strict `ConnectionOut` refused - main's own two tests
    failed with a 500 on the merged tree - so that route declares `ConnectionDetailOut` (`cooldowns`: a list of
    `{scope, until}`, or null); the schema copy and the client's types are regenerated. On that merged tree the
    backend's parallel suite (without the serial CEL group) had 2,269 passes and 2 failures, not a clean run: two
    dispatcher tests failed (`test_reconcile.py::test_a_queued_request_whose_run_already_ended_is_never_started_again`,
    `assert None == Held(reason='run_ended')` with `start_absent` logged; and
    `test_triggers_end_to_end.py::test_a_short_outage_fires_each_missed_time_and_admits_each_once`). Reruns then
    passed: the first test failed 3 of 5 alone, then passed 5 of 5 at 6482c53, at `origin/main`, at f6bf190 and on
    the merged tree; the second passed 5 of 5 alone; the dispatcher's 202 tests passed. Ruff, mypy, import contracts,
    pip-licenses and schema drift were clean; the frontend's 292 tests, lint, types, build, `check:api` and licences
    passed; the browser gate passed 7 of 7. Corrected (owner, 2026-10-06): the load was a suspicion, not the cause,
    and unchanged code with later passing runs supports, but doesn't prove, that the failure predates 4a. #43 then
    established the first test's cause with a matched reproduction on main's own code: `settle` stamped "due at once"
    with the dispatcher's clock while `begin` read the database's, which lags it on Docker Desktop's VM; CPU load
    alone didn't reproduce it. #43 is merged (ruling 64). The outage test's failure has no established cause.

### Owner, PR #42 held (2026-10-06, pasted)

- The tenant-switch fix and the scoped licence exceptions with OR reporting accepted; the visual approval stands.
- Hold the merge of #42 for: (1) an update from current `main` (#41 merged), merged without rewriting commits, keeping
  both the logging fixes and 4a's API and schema changes, with the affected checks rerun, the logging regression
  tests included; (2) generated third-party notices - a distribution requirement - with copyright notices and full
  licence texts for the shipped JavaScript, CSS and fonts, in `dist` and the web image, inclusion decided from build
  metadata and package provenance, never from searching the minified output; (3) the full serial test run, in
  `cel-gates`' pinned Linux environment, locally, stopping to report past ten minutes; (4) the replay-history gate,
  locally, against the updated base, and the PR's statement that it needs CI corrected.
- Correct the verification wording: the parallel run had 2,269 passes and two failures, then passing reruns - not
  "every check passes"; the cause stays suspected unless a matched baseline reproduction establishes it.

### 4a, the PR's hold items (2026-10-06)

64. `main` moved on to 717f420: #41 (the logging fix, aa33705) and #43 (the dispatcher's clock, the cause of ruling
    63's first failure). The branch merges it (838ebc8, a merge commit). One conflict, the API's `main.py`: 4a's route
    tuple (`openapi.py`) kept with #41's `logs.configure()` and `LifespanFailures`; the CLI merged clean, and #41's
    callback prints nothing into `dewpoint api openapi`, whose dump is unchanged. On the merged tree: #41's logging
    tests, #43's dispatcher tests and 4a's API tests 124 passed; the backend's parallel suite 2,305 passed, none
    failed (3 min 27 s); ruff, format, mypy, import contracts and pip-licenses clean; the frontend's 292 tests, lint,
    types, build, `check:api` and licence checks pass; the browser gate passes 8 of 8.
65. Third-party notices (`frontend/scripts/third-party-notices.mjs`, a Vite plugin, no new dependency):
    `third-party-notices.txt` is written into `dist`, so the web image's nginx serves it (the browser gate fetches it:
    text/plain, React, Tailwind, the fonts' OFL and the MIT text). What ships is read from the build's metadata: a
    package whose code a chunk renders (tree-shaken modules don't count), whose stylesheet the build reads (an
    imported CSS module, or a CSS file Tailwind inlines, from its watch files), or whose file becomes an asset (each
    font's source file); Vite's preload polyfill and its bundled CommonJS helpers are Vite's (its LICENSE.md carries
    the bundled plugins' licences), and any other virtual module fails the build. Each entry gives the package, its
    version, its declared licence and every licence and notice file it ships, in full; a shipped package with no
    declared licence or no licence text fails the build. 57 packages today, the same 57 an independent probe of the
    build's metadata found. `react-remove-scroll-bar@2.3.8` ships no licence file: its upstream repository's MIT text
    (`LICENSE` at 8ca9ba5, retrieved 2026-10-06; v2.3.7 has none and there's no v2.3.8 tag) is under
    `frontend/licences/`, with its source - the owner may want that reviewed. A self-test runs in CI's licence job.
66. The serial CEL group ran in full in `cel-gates`' image, `python:3.12-slim-bookworm` (digest 34386ef0, arm64: this
    Mac's architecture, where CI's runners are x86_64), with uv 0.12.10 and `uv sync --locked`, CI's pytest command
    and a 10-minute cap: 406 passed, none skipped (the seven Linux-only limit tests included), in 98 s. Three
    differences from CI's job had to be matched first, none a test failure: the repository's `deploy/` beside
    `backend/` (`test_isolation` reads the evaluator's Dockerfile), the Docker socket (`test_gate_task_cost` starts
    Postgres with testcontainers, reached at `host.docker.internal` from the container), and Temporal's Linux test
    server (the container couldn't download it through this Mac's TLS interception; the host fetched the same
    official archive, `temporal-test-server` 1.40.0, sha256 1d712f6f, and it went where the SDK looks first). The
    gates' measurements (cost, memory, task cost) are kept with the run's log in the session's evidence.
67. The replay-history gate ran locally against the updated base (717f420), in CI's pull-request form and with the
    base given: no recorded history changed or removed - the branch changes none. It needs only git; the PR's
    "needs CI's environment" is corrected.

### Owner, 4b plan (2026-10-06, pasted)

The 4b plan (`2026-10-06-editor-ui-4b-workflows-canvas.md`) went through four revisions on the owner's reviews:
325fc14 (seven corrections), 089c004 (five and one smaller), a206ea9 (one Task 13 lifecycle correction and one
smaller), and 5a0076f, which incorporates the last. Rulings on its proposals: 1-4, 6, 8-12, 14, 16, 19-21 accepted
(4 and 6 with the unpublished filter correction); 5 held until the batching and query-plan evidence exist (any index
needs a migration slot); 7, 13, 15, 17, 18 amended; 22-24 and 26 accepted; 25 accepted, its non-null hash proof as
evidence that a version holds the submitted graph, not of which caller published it; 27 and 28 accepted. They join
this ledger as rulings 68-95 when the slice is approved; the plan carries their text.

Execution: "Proceed inline from current `main`, locally through milestone 1, then stop for the API/probe review.
Incorporate the Task 13 correction before requesting approval for the remaining milestones. No push or PR
authorization." The Task 13 correction is revision 4 (5a0076f).

### 4b, milestone 1 (2026-10-06)

M1. **The branch starts from `main` at f65c6f9**, not 66443c3 as the plan says: #44 (plugins 3a-2) and #45 (CodeQL
    in CI) merged after the plan was written. `feat/editor-4b` is f65c6f9 with the plan's commits merged in (c3ba754).
    #44 touches files milestone 1 changes (the node-types and workflow routes, `responses.py`, `workflow_ops.py`, the
    SDK's fields, test helpers); each task is checked against `main` before its code, and what differs is ruled here.
    - #44 is merged on `main`, and the plan's line numbers into those files are 66443c3's. - Wrong line references
    in the plan for those files; the code they describe is found by name.
M2. **`NodeTypeOut` also declares `icon` and `options`** (Task 1): #44's palette answer carries both (a first-party
    icon's name, plugins-3; the config fields `options()` lists, D3), and the named model forbids extra keys, so it
    must declare them. The test pins `flow.loop`'s icon (`repeat`) and `testkit.pick`'s options (`site_id`). - Without
    them the answer fails its own model. - Two fields the 4b plan didn't list; 4c and 4f use them.
M3. **The plan's cross-tenant run named the wrong version** (Task 3; corrected on the owner's milestone 1 review):
    `runs` carries the foreign key `runs_version_fk (workflow_version_id, workflow_id) -> workflow_versions (id,
    workflow_id)` (migration 0008), which the ORM model doesn't show. It guarantees that a run's version belongs to the
    workflow the run names; it has no tenant column, so it doesn't prove that a run and its workflow share a tenant.
    The plan's `test_another_tenants_runs_never_count` paired this tenant's workflow with the other tenant's version,
    which the key refuses. Restored with the workflow's own version under the other tenant's id (the key holds; only
    row-level security and the statements' tenant filter keep the row out), beside a second test proving the
    statements' own tenant filter with row-level security out of the way (the owner's session). The probe seeds real
    workflows and versions (`seed_workflow`, 200 a tenant) and its runs name them. - The schema refuses the row the
    plan's test inserted. - None: the restored test keeps the plan's scenario.
M4. **The import's audit entry is read as the database's owner** (Task 5): the plan's test read `/audit` as the
    importing editor, but `audit.view` is an admin's and an owner's, so the editor is refused. The test reads the
    tenant's newest audit entry through the owner's session instead and asserts its action, its target (the new
    workflow) and its details (`{"name", "source": "import"}`). - An editor can't read the audit log. - None: the
    route and the entry are as planned.

### Owner, 4b milestone 1 reviewed (2026-10-06, pasted)

Reviewed f550076 against f65c6f9. Revision 4's exit handling, the null-hash reconciliation, the save's authoritative
comparison and the publish precondition match the agreed contracts. Ruling 5 (ledger 72) decided: **the index and a
batched LATERAL read**, migration slot 0047 reserved for `runs (workflow_id, mode, queued_at DESC, id DESC) WHERE kind
= 'run'`; one LATERAL statement for every workflow, keeping the tenant, root-run and mode filters and the `queued_at
DESC, id DESC` order, never one query per workflow. 0043-0046 stay reserved and untouched; slot numbers are ownership,
not order: 0047 chains from the actual head, one head, no deployed migration rewritten. The probe's 1.19 ms needs a
workload qualification (its shared modulo made 180 workflows live-only and 20 simulate-only, so half the 400 lookups
missed): decouple mode and status from workflow selection, rerun with both modes per workflow, and assert the two
queries' complete results equal; quiet workflows and equal-timestamp ordering join the regression tests. Corrections:
(1) `portable` detects duplicate steps by UUID identity, not spelling (lowercase/uppercase, hyphenated/unhyphenated
aliases, on export and import; a refused import still creates nothing); (2) M3 overstated `runs_version_fk` (no tenant
column): its claim is corrected and the plan's scenario restored with the target workflow's own version; (3) Task 15's
lost-answer wording is limited to graph equivalence: "Version N holds the submitted graph. Your publish request's
outcome wasn't received." M1, M2 and M4 accepted. Execution: incorporate these and the index addendum, then proceed
inline through milestones 2-4; the pauses after milestone 3 and at the final checkpoint stay, and Task 11's immediate
stop on any CSP failure. No push or PR.

### 4b, after the milestone 1 review (2026-10-06)

M5. **The last-runs read bounds the mode from below inside each lookup and checks it outside** (ruling 5's index and
    batched LATERAL read): `workflow_id = w.id and mode >= m.mode order by mode, queued_at desc, id desc limit 1`,
    then `where r.mode = m.mode` outside the lookup, keeping the tenant and root-run filters. The ruling's literal
    form (the mode an equality, `order by queued_at desc, id desc`) answers the same rows, but its plan depends on the
    statistics: an equality makes the mode redundant in the order, so `runs_tenant_queued (tenant_id, queued_at DESC,
    id DESC)` serves the order as well as `runs_workflow_last`. On a tenant whose one workflow has only live runs,
    analyzed, the planner chose `runs_tenant_queued` and read the tenant's whole history for each workflow and mode
    with no run: 60,000 rows and 1,419 pages at 20k runs in the test database; 34 ms at 100k and 372 ms at 1M in the
    probe, slower than the DISTINCT ON read it replaced (24 and 262 ms). Bounding the mode on both sides kept the
    order but let the planner's default range estimate (0.5%) choose a bitmap scan and a sort of each workflow's runs
    of the mode (11.4 ms at 10k, against 2.5 ms). From below, the estimate is a third, only `runs_workflow_last` gives
    the order, and the first row is the mode's newest, or another mode's when it has none (dropped outside). The probe
    observed one ordered index scan, stopping at the first row, at every size of both workloads it tried (the
    planner's choice there, not a guarantee for every future PostgreSQL plan), and the reads' whole
    results equal; `test_the_last_runs_read_examines_one_run_per_workflow_and_mode` pins the ordered scan on the
    skewed history (it fails on the literal form). - A plan that turns on statistics reads a tenant's whole history
    for a quiet workflow. - None in results (the reads agree whole, and the regression tests compare them); the
    statement is less obvious, and its comment says why.

### 4b, milestone 2 (2026-10-06)

M6. **The tenants page opens a tenant on its workflows too** (Task 6; ruling 19, "Workflows lands a tenant"): the
    plan changed the switcher and the palette; the tenants page's name link still opened Connections. It now opens
    Workflows (`router.test.tsx`: from `/tenants`, choosing Acme Lab lands on `/t/t2/workflows`). The palette's
    existing "goes where the chosen item points" test now chooses Security, since a tenant lands on Workflows (its
    own new test). - Three ways to choose a tenant should land in one place. - None: the link's target only.
M7. **Two test adaptations** (Tasks 6, 8): the plan's Announcer test advanced timers in `act(() =>
    vi.advanceTimersByTime(50))`, whose callback returns the timer utilities, so `act` answers a promise and
    typescript-eslint refuses it floating; a block body returns nothing. jsdom 25's `Blob` has no `text()`, which
    every browser gives and `NewWorkflow` reads a picked file with; the test setup gains a stand-in through jsdom's
    `FileReader`, beside its dialog and `ResizeObserver` stand-ins. - Lint and the test runtime, not the product.
    - None: the product code is the plan's.

### 4b, milestone 3 (2026-10-06)

M8. **The graph tests' node type carries `icon` and `options`** (Task 9; follows M2): the plan's `type()` helper
    built a `NodeType` without them, which the generated type requires since `NodeTypeOut` declares them; it adds
    `icon: null, options: []`. Five non-null assertions on `edges` and `nodes`, which the generated `Graph` declares
    present, are dropped (typescript-eslint's `no-unnecessary-type-assertion`). - The schema the plan was written
    against had neither field. - None: test fixtures only.
M9. **dagre's graph is typed with its own `NodeLabel`** (Task 10): checked in the installed 3.1.1 (default export
    `{graphlib, layout, …}`; graphlib 4.0.5's `Graph<GraphLabel, NodeLabel, EdgeLabel>` with `setGraph`,
    `setDefaultEdgeLabel`, `setNode`, `setEdge`, `hasNode`, `node`). Untyped, its labels are `any`, which
    typescript-eslint refuses; `new dagre.graphlib.Graph<object, NodeLabel, object>()` types them, and `x`/`y`
    (optional in `NodeLabel`) are read with a default. Positions are the offset of each card's centre from the start
    card's, which equals the plan's top-left arithmetic for cards of one size. - Lint. - None: the layout tests hold.
M10. **The foundations e2e follows ruling 19** (Task 11): choosing a tenant in the switcher now opens its workflows,
    so the flow asserts `/workflows` there and follows the rail's Connections link to the connections it goes on to
    test. It also saves the signed-in state (`e2e/state.ts`) for the `workflows` project, as the plan says. - The
    plan changed the switcher (Task 6) but not this test. - None.
M11. **React Flow's nodes take the pointer and keep their size** (Task 11; the browser gate caught three faults, none
    of them CSP: the traces hold no console message, and the gate saw no violation). In the installed 12.12.0: a
    node's wrapper gets `pointer-events: none` unless it can be selected or dragged or has a mouse handler
    (`hasPointerEvents`), so the start card's "+" (and a viewer's step card) passed the press to the pane; the cards
    and their "+" carry `pointer-events-auto`, as the edges' "+" already did in React Flow's label layer. A node object
    without `measured` has no dimensions (`nodeHasDimensions`) and is hidden until measured again: the canvas rebuilt
    its nodes on each editor render, so a press that moved focus (and re-rendered) released over the pane (a
    MutationObserver showed the start node's style flip and `pointerup` on `react-flow__pane`); a rebuilt node now
    keeps its measured size. A new node is hidden until its first measure, after the frame that focuses it, so the
    step just added never took focus; every node carries `initialWidth`/`initialHeight` (the card's 260 by 64). A unit
    test pins `pointer-events-auto`; the gate's pointer flow pins the rest. - Clicks and focus lost on the canvas. -
    None: the canvas behaves as the plan describes.
M12. **The isolated stack builds the 4b worktree** (Task 11, scratchpad only): `compose-ui4a/dc.sh` and `e2e.sh` point
    at `ui4/4b` (4a is merged), and `reset.sh` syncs the installed plugins as the admin login after `admin init`, as
    CI's e2e job does. Project, ports, images' tags, secrets file and CSP are ruling 24's, unchanged. Base images:
    the ones 4a's gate built from. A gate run (rebuild, fresh database, admin, sync, e2e) takes about 1.8 minutes. -
    None.
M13. **The canvas moves the view for the keyboard only, and placing never moves the canvas** (Task 12; the browser
    gate's placing flow caught both). `reveal` recentred any item not wholly inside the canvas on every focus, a
    pointer's included: a step placed with a click near the edge (the step's panel open, the canvas narrower) was
    recentred off the click (273 px), and a press on a half-visible card would slide it from under the press before
    the release. It now runs only for `:focus-visible` focus (Tab, the arrows, a change made from the keyboard). The
    "Click an empty place…" bar sat above the canvas and pushed it down; when placing ended the canvas rose by the
    bar's height (51 px) and the card with it. The bar now lies over the canvas's top edge. The plan's keyboard flow
    also waits for focus to settle on the step a deleted one came after (a frame after the confirm) before Control+z,
    asserting where focus goes. - The step a person places stays under the click. - Keyboard focus to a half-visible
    item still brings it into view; a pointer's doesn't (the person can see it).
M14. **Two things the screenshots showed** (milestone 3's review evidence): the start card's second line ("By hand, on a
    schedule or from a webhook") wrapped onto a third and overflowed its 64 px card; it now reads "By hand, a schedule
    or a webhook", truncated if a font draws it wider. The list's row menu was three middle dots, which at 13 px merge
    into what reads as a dash; it's now a drawn icon of three square dots (`MoreIcon`), the trigger keeping its name
    ("Actions for …"). - Text outside its card; a menu that didn't look like one. - None.

### Owner, milestone 3 reviewed (2026-10-07, pasted)

M5 accepted: the lower-bound lookup is the exact-mode lookup's answer (the requested mode sorts first when it exists,
else the outer equality drops the other), tenant and root-run filters inside; its explanation is kept, the ordered
scan described as observed on the tested workloads, not guaranteed. Milestone 4 approved locally, these carried into
it; milestone 3 isn't final UI acceptance; no push or PR. Corrections found in 6471c0e: (1) the frontend matches step
ids by spelling: a graph with lowercase node ids and uppercase edge references drops its edge on the canvas, and a
deletion leaves an incident edge; identity is matched by UUID across rendering, navigation, connection and cycle
checks, deletion and declassification, the authored document kept, uppercase and unhyphenated aliases covered, and
the server's canonical diagnostic ids mapped back to their cards. (2) Undo can strand keyboard focus on a removed item;
focus stays when its item survives, else goes to a surviving predecessor or the start card; a browser sequence undoes
and redoes without repairing focus by hand. (3) A creation answer arriving after the dialog was dismissed (and the
tenant switched) navigated into the abandoned tenant; the cache stays scoped to the original tenant, the abandoned
dialog neither navigates nor announces, and nothing claims dismissal cancelled the write. (4) File reads can land out
of order and a failed read escapes; a token keeps only the latest selection, reading and failure are shown, and a late
read never overwrites a name typed since. Rulings: lazy-load the editor without new dependencies (React Flow and dagre
out of the cold list and login load, an accessible loading and error state, the CSP gate repeated for lazy JS and CSS,
the initial load measured); overlapping edge controls on a cycle fixed before final acceptance (independently
targetable controls or an edge chooser, reciprocal edges and a valid multi-port join covered); the minimap hidden while
a side panel is open (an accessible overview toggle if needed; the narrow canvas checked; focus never left behind an
overlay). Proceed inline through Tasks 13-16 with these, then stop at the final checkpoint.

### 4b, after the milestone 3 review (2026-10-07)

M15. **The editor matches step ids by UUID identity** (owner's correction 1): `idKey` (`lib/graph.ts`) reads an id as
    the API's `uuid.UUID` does (case, hyphens, braces, a urn), and `sameId`, `findNode` and `edgeId` go through it:
    entries, drawable edges, reachability, connect, insert, delete (edges and declassify entries), moves, the dagre
    layout, the canvas's React Flow ids and item ids, and the keyboard model. New edges are written with each step's
    authored spelling; nothing already in the document is rewritten. Unit tests cover uppercase, unhyphenated, braced
    and urn spellings (they fail without the change: 13 of 50), and the gate imports a file whose edge spells its
    steps' ids in capitals and without hyphens: drawn, walked, and gone with its step. Task 14 maps the server's
    canonical diagnostic ids to cards through `idKey`. - A draft from elsewhere lost edges on the canvas and kept
    dangling ones on delete. - None: the document keeps its spelling.
M16. **Undo and redo keep focus in the editor; a key acts from the item focus is meant to be on** (owner's correction
    2): undo or redo that removes the focused item (or the step whose panel holds focus, closing it) moves focus to
    the nearest surviving item back along its path, else the start card; an item that survives keeps its focus,
    untouched (asking again would steal it a frame later from wherever the person had moved it, as the gate showed).
    Focus moves a frame after a key (the canvas draws first); a key pressed before then (auto-repeat, two quick
    presses, the gate's own) used to act from the old item, so the canvas's keys act from the editor's tab stop.
    The unit tests' stand-in canvas reports focus to the editor as the canvas does. Unit tests undo, redo and keep the
    panel without repairing focus by hand; the gate adds a keyboard undo and redo sequence. Three gate runs: 14
    passed each. - Focus on the page body after an undo, and keys heard nowhere. - None.
M17. **New workflow speaks only while it's open, and reads only the latest file** (owner's corrections 3 and 4): once
    the dialog is dismissed, or gone with its tenant's screen, a creation that answers late still refreshes that
    tenant's list (`["workflows", tenantId]`, the tenant it was asked in) but neither opens the workflow nor announces
    it; nothing claims dismissing cancelled the request (the server may create it, and the list then shows it). Each
    file chosen takes a number: an earlier read that answers later changes nothing; "Reading the file…" shows while
    one runs; a read that fails says so ("That file couldn't be read. Choose it again, or another.") instead of an
    unhandled rejection; and the file's name fills the Name field only if the person hasn't typed one meanwhile.
    Tests: a held creation then Cancel (no navigation, no announcement, the list invalidated); a held creation then a
    tenant switch in the whole app (the new tenant's screen stays); reads answering in reverse order; a failed read
    then a good one; a name typed during a read. - A late answer opened another tenant's workflow; a late read
    replaced the file shown. - None.
M18. **The owner's three rulings on milestone 3, built** (2026-10-07). Lazy editor: the route loads `routes/editor`
    with React's `lazy` (no new dependency); "Loading the editor…" (a status) while it loads, and a load failure says
    so with Try again (a new load; an error inside the editor still goes to the router's boundary). Vite's
    `\0vite/preload-helper.js` now ships, so the notices plugin names its owner (Vite, MIT, as its other two helpers;
    the self-test covers it). First load: JavaScript 816 kB -> 556 kB (265 -> 180 kB gzipped); the editor's chunk is
    263 kB (86 kB) and 12 kB of CSS. In the browser the list and the sign-in page fetch 589,599 bytes of script and
    style and never the editor's chunk; opening a workflow adds 276,065 bytes; the gate's CSP checks pass with it.
    Edge controls: an edge that climbs (a cycle's way back, a self edge, a step beside its source) runs its middle,
    and its "+", past the right of both cards (`route`, React Flow's `centerX`); a "+" names its port when it isn't
    `out`, so two edges from one step to one target read apart. The gate clicks every "+" of reciprocal edges and of a
    join from `if`'s two ports by pointer, none overlapping. Minimap: off while a side panel is open, and off on a
    canvas under 640 px (a CSS container query); the keys' reveal treats the minimap, the zoom controls and the placing
    bar as covering, so a step reached behind one is brought clear. The gate checks all three. No overview toggle:
    closing the panel brings it back. - The rulings. - None.

### 4b, milestone 4 (2026-10-07)

M19. **Problems, as the plan has them, with three adaptations** (Task 14): the problem and expression counts are keyed
    by the step's identity (`idKey`) and a step's panel filters by `sameId`, so the server's canonical ids find a step
    the draft spells otherwise (a test: an uppercase id, its problem on its card, in its panel, and "Go to" by its
    key); the editor's check state starts at "Checking…" for an editor (it checks on opening: its first frame never
    says "Not checked" for an instant); and the right column's one panel (`side`) keeps Task 12's step panel as a
    derived `panel`, so undo's focus rules (M16) read as before, and any side panel hides the minimap (M18). The plan's
    test block declared `steps()` again (Task 13's tests needed it first). - The plan predates M15, M16 and M18. -
    None.
M20. **Publishing and versions, as the plan has them, on M15 and M19** (Task 15): a viewed version's step panel finds
    its step and its expressions by identity (`findNode`, `sameId`), the editor's `editable` folds in the version view
    and a running publication or activation ahead of the keyboard model (which reads what's on the screen), and the
    side column (M19) carries the versions panel. The lost-publish wording is revision 5's (graph equivalence only).
    - The plan predates M15 and M19. - None.
M21. **The Report fixture's output guards its read** (Task 16; the browser gate caught it): the plan's fixture is CI's
    seed graph, which publishes as it stands, but the flow's second publish (a stop step added after `t`) is refused,
    `cel.conditional_ref`. A graph with a stop step may end a run while a step is still pending, so at the exit every
    step's output may be missing (`engine/graph/validate.py`, by design). Of the flow types only `flow.stop` has a
    valid default configuration (every other requires a field), so the flow keeps it, and the fixture's output reads
    `has(steps.t.output) ? steps.t.output.answer : 0`, the fix the server's message gives. The editor did as designed
    throughout: it showed "Problems · 1" before the publish, and the refused publish opened the panel with the problem
    "Found at publish". - The flow tests the editor; the rule is the engine's. - None for the product; the fixture
    differs from CI's seed graph by its guard.
M22. **The notices name what dagre's build inlines** (Task 16): Step 3 expects `@dagrejs/graphlib` in the notices, but
    dagre 3.1.1's `dist/dagre.esm.js` imports nothing and carries graphlib's code, so the build's metadata names only
    dagre. The notices plugin gains `INLINED` (`@dagrejs/dagre` to `@dagrejs/graphlib`, read from beside the package in
    its `node_modules`; one missing fails the build), and its self-test covers it. The gate's notices check also asks
    for the four canvas packages. - graphlib's code ships, so its notice must (ruling 65). - A future dependency that
    inlines another package's code goes unnoticed until someone reads its build: the map is per package, reviewed by
    hand.
M23. **Task 16's checks, as they came out** (2026-10-07, the working tree before its commit):
    - Browser gate, on a freshly reset stack: 24 passed in 49.4 s, with no CSP violation, console error or remote
      request. `foundations` 8; `workflows` 16 (the plan's 11, plus M15's aliases, M16's undo and redo, and M18's lazy
      load, pointer reachability and minimap). The list and sign-in load 591,007 bytes; opening a workflow adds
      300,443.
    - Frontend: 497 tests in 41 files; lint, types and `check:api` clean.
    - Build: index 557.57 kB of JS (180.60 kB gzipped), the editor's chunk 288.36 kB (93.54 kB), CSS 32.85 and 12.09 kB.
    - Licences: both self-tests pass; production and all dependencies are within D22 (isbot's Unlicense, the approved
      exception).
    - Notices: the canvas's packages, each with its licence text. @xyflow/react 12.12.0, @xyflow/system 0.0.83,
      @dagrejs/dagre 3.1.1, @dagrejs/graphlib 4.0.5, @radix-ui/react-switch 1.3.7, classcat 5.0.5, zustand 4.5.7, and
      d3's color, dispatch, drag, ease, interpolate, selection, timer, transition and zoom.
    - Backend: ruff clean; format clean (599 files); mypy clean (231 source files); import contracts 11 kept;
      pip-licenses clean. The OpenAPI dump matches the frontend's copy. The replay gate, against the merge base
      f65c6f9, finds no recorded history changed or removed.
    - The parallel suite, without the serial CEL group as the plan says: 2,639 passed, 1 failed, 223 s. The failure
      is `test_triggers_end_to_end::test_a_short_outage_fires_each_missed_time_and_admits_each_once`, with gaps
      {2.0, 4.0}: one missed time not fired.
      - 4b changes nothing in the dispatcher or its tests. Alone, the test passed 3 of 3 (18 s each).
      - It was listed as open before this slice, and it isn't the database-clock fault #43 fixed.
      - Its cause isn't established: load on a real-time Temporal schedule is suspected, not shown.
    - The serial CEL group didn't run: this slice doesn't touch it (ruling 66's procedure, if the owner asks).

### 4b, the final checkpoint (2026-10-07)

A fresh-context reviewer (a subagent, read-only) reviewed f65c6f9..f0d5ac8 against the six hunts, with the screenshots
beside frames 1a, 1b and 1c. Nothing Critical; four Important findings and six Minor. One process slip, its own
report says: its first grep wrote `scratchpad/files4b.txt`, outside the directory it was given; it deleted that file
by name, and the worktree stayed clean.

M24. **Eight findings fixed, each test-first** (a failing test first, watched failing, then the fix):
    - Edges and the minimap's steps were drawn in `--line-strong`: 1.43:1 on the ground in light, 1.77:1 in dark.
      They now use `--edge` (3.65:1 and 4.65:1), as 4a's ruling 1 has it. Axe doesn't measure SVG strokes, so
      `canvasStyles.test.ts` holds both to tokens `PAIRS` pins at 3:1.
    - Focus the editor sends after a pointer's press (Go to, a step added, a version viewed) never moved the view, so
      a step off the canvas took focus unseen (WCAG 2.4.11). M13 is revised: `reveal.ts` decides.
      - Focus moved by the keyboard: the view moves unless the item is wholly in the clear (as before).
      - Any other focus: the view moves only when the item is entirely hidden. A press or a placing click is always
        on something that shows, so M13's protection holds.
      - A browser flow drags a step off the canvas, then uses Go to with the pointer. It failed on the old canvas
        (focused, viewport ratio 0) and passes now.
    - Focus fell to the page in three places (WCAG 2.4.3). The editor now places it:
      - a closed panel returns focus to its toolbar button;
      - a version made active lands focus on the versions panel's heading (its Make active is gone);
      - a publish refused for its problems lands on the problems panel's heading;
      - a publish done returns to Publish, which names the next version. The dialog holds, busy, until the versions
        are read again, so the button is enabled when focus comes back.
    - Status messages (WCAG 4.1.3):
      - a failed save is announced ("Your latest edits aren't saved. Retry is in the toolbar.");
      - a notice's live region is there before its text, and a refusal is an alert;
      - the step types' trouble line keeps its region too;
      - New workflow's file errors are alerts;
      - the lost-publish notice no longer also announces the same words.
    - A viewer could open New workflow from the palette or `?new=true`, only for the server to refuse it. The palette
      offers it only to a role that can create one, and the list opens it only once the role is known to.
    - The open step wore the focus ring's 2 px outline, so it looked focused when it wasn't. It now wears a 2 px accent
      border all round, as 1c draws it, with its padding a pixel less.
    - The toolbar follows 1c: the save state (and Retry) beside the name; Add step first among the actions; Publish,
      the one primary, last.
    - The list's filter wrapped at 320 px into ragged rows with stray borders. Its options are now separated by 1 px
      gaps and fill each row.
    - The connect dialog found its source step by spelling, so a draft spelling the id otherwise titled it "Connect a
      step to" (M15). It now finds the step by identity.
    - The plan predates the review. - Small; each fix has its test.
M25. **Ruled for the owner: a schema message can quote a value** (Minor, hunt 1; the code predates 4b).
    - The engine's `config.invalid` passes jsonschema's own message through (`engine/graph/validate.py`,
      `_schema_errors`), and that message may quote the value (`'…' is too short`). 4b shows the server's messages
      as they come (§5.10).
    - So a literal typed into a field marked sensitive that also fails its schema shows in the problems panel. The
      draft holds it already, for the same readers.
    - Separately, export refuses only ids. A draft the validator flags for `sensitive.literal` exports with that
      literal in the file (ruling 18's scope).
    - Neither is 4b's code to change. Recommended: the engine builds `config.invalid` from the failing keyword and the
      path, never the value (at least where the schema marks the field sensitive), and export refuses a draft with a
      `sensitive.literal` problem. - Until then a sensitive literal shows to its draft's readers and travels in an
      exported file.
M26. **Ruled for the owner: the "+" controls' size when zoomed out** (Minor, hunt 5, WCAG 2.5.8).
    - The "+" controls are 24 px at 100% and scale with the canvas.
    - Below 100% they rely on the spacing exception: a 24 px circle on each must touch no other target.
    - From the layout (cards 64 px tall, ranks 76 apart, a port's "+" centred 36 px below its card, ports spread
      evenly over the card's 260 px), that holds from a zoom of 0.35 for one port. With n ports it needs
      24(n+1)/260: 0.37 for three, 0.55 for five.
    - The canvas zooms out to 0.25, and a fit stops there.
    - Options:
      - fit no lower than the zoom that holds, and let a person zoom out further by hand;
      - keep the "+" at 24 px on screen whatever the zoom;
      - accept it.
    - Recommended: the first. - Today a large graph's fit, or a person zooming out, can leave "+" controls too small
      to meet 2.5.8.
M27. **The checks after the fixes** (2026-10-07):
    - Frontend: 515 tests in 44 files; lint, types and `check:api` clean.
    - Build: index 557.69 kB of JS (180.66 kB gzipped), the editor's chunk 289.75 kB (93.91 kB).
    - Licence and notices self-tests pass.
    - Browser gate, on a freshly reset stack: 25 passed in 53.1 s (M23's 24 and the off-canvas flow), with no CSP
      violation, console error or remote request. The list and sign-in load 591,346 bytes; opening a workflow adds
      301,824.
    - No backend file changed since M23, whose backend results stand.

### Owner, 6d7766e reviewed (2026-10-07, pasted)

"Final acceptance is still held at `6d7766e`: I reproduced four remaining defects." The owner asked for the branch to
stay local: no push, no PR, no final approval recorded. The earlier UUID, import-race, undo-focus and lazy-loading
corrections stand. The corrections:
1. An open dialog could edit after a conflict: enforce edit permission where the change lands, and close what's open.
2. A navigation within the same editor held its document for good: tell leaving from staying, and give an abandoned
   exit back, without weakening the sign-out hold.
3. A join climbing up and to the right put both its "+" on one rectangle: make the targets collision-aware (or give
   an equivalent chooser), and add that join to the pointer regression.
4. At 320 px a panel left the canvas zero wide: keep it usable, and test Go to and placing there by what shows.

Rulings:
- M25: a separate engine and portability follow-up (both schema-error sites, `_schema_errors` and `_check_instance`,
  and refusing to export a sensitive literal). No browser-side masking. Resolve it before 4c accepts sensitive
  configuration editing.
- M26: "Do not accept a Fit-only restriction." Prefer screen-sized, collision-aware controls, or an equivalent unscaled
  chooser. A minimum zoom is acceptable only if it covers the targets as rendered and every zoom path.
- The outage test: investigate it separately, keeping its record as it stands (2,639 passed, 1 failed; three isolated
  reruns passed; cause unknown).
- The serial CEL group: run it on the corrected head.
- Visual approval is still pending: the artifact's screenshots didn't reach the owner, so they come with this
  checkpoint.

### 4b, after the review of 6d7766e (2026-10-07)

A fresh reviewer (read-only; it wrote no file this time) reviewed the correction round, 6d7766e..cd864ea. It found two
Important findings and seven Minor ones, all fixed in 4e3061e and 37c764b and folded into M28–M32. Each fix has a test
first, which was watched failing.

M28. **Editing stops where a change lands, and what only editing offers stops with it** (correction 1; second-review
    findings 1, 4 and 9).
    - `change()` and undo ask `mayEdit()`: `editable` as last drawn, an exit agreed to, and the saver's own state,
      which knows of a conflict before the screen does.
    - When editing stops, an open picker, connect or delete dialog closes, and placing ends and says so.
    - Focus held by what's gone moves:
      - from a dialog, to the canvas item it was on;
      - from a "+" (on a read-only canvas there are none), to its step, never the start card;
      - from a panel's buttons, to the panel's heading;
      - from Auto layout or Add step, to the canvas item.
    - Tests: a conflict arriving under each of the three dialogs, under a panel button, while placing, and under a
      port's "+".
    - The owner's review. - None found.
M29. **Only leaving the editor is an exit** (correction 2; finding 3).
    - "This editor" is its route and its params, so a hash, a query or another spelling of the path (`/w1/` and
      `/w1`) asks nothing and holds nothing.
    - A router exit agreed to is released if a later navigation resolves back on this editor (`onResolved`).
    - A sign-out's consent stays the guard's, released only by its own `stayed`: no second prompt.
    - Tests: a hash, a query, a respelled path, and an exit whose destination redirects back.
    - An exit a second blocker refuses fires no `onResolved`: there is no second blocker today.
M30. **No two "+" share a rectangle, however the steps are placed** (correction 3; findings 5 and 6).
    - Each edge reports the line it draws, and the canvas places every "+" (`pluses.ts`):
      - React Flow's label point when it's clear;
      - else the clear point along the edge's own line nearest its middle, off the cards where there's room;
      - never on another edge's "+" or on a card's own "+";
      - sideways only when the whole line is taken.
    - Each port climbs in its own lane, measured from the cards' right edges, so a lane never runs through the card.
    - The pointer regression now has the join climbing up and to the right.
    - Edges that share a segment still draw one line there, though their "+" sit apart.
M31. **A narrow editor keeps its canvas** (correction 4; findings 7 and 8).
    - Below a 48rem editor (a container query), side panels stack under the canvas, at most half its height.
    - The open step is brought back into the clear as its panel takes that half.
    - The canvas's controls keep one row: no label wraps, and the zoom percentage hides below a 340 px canvas.
      Measured, the row didn't overflow; it was 44 px tall with Auto layout broken onto two lines.
    - The 320 px flow checks what shows:
      - the canvas is over 200 px wide with Problems open;
      - Go to shows the step at least half;
      - a step opened in the lower half stays 90 % visible;
      - Place lands the step centred on the click;
      - the controls row is one row inside the canvas.
    - At 320 × 720 with a panel open, the canvas is about 150 px tall: the shell's header, the development banner and
      the toolbar take the rest.
M32. **M26 as built: targets covered as rendered and on every zoom path** (finding 2).
    - The UI's rem is 14 px, so the canvas's `h-16` cards were 56 px and its `size-6` "+" 21 px. The canvas now draws
      in px, as React Flow lays it out: cards are CARD in size (64 tall), each "+" 24 square and 24 below its card.
    - `MIN_ZOOM` 0.4 (a card 25.6 px tall) is React Flow's `minZoom`, the first fit's and the Fit button's. It bounds
      the wheel, a pinch, the buttons and the minimap.
    - Each "+" scales below 24 px. A step's panel offers every one of them at full size: insert before an entry,
      insert on every edge the canvas draws from it (ports its type no longer lists included), add after each free
      port. That is WCAG 2.5.8's equivalent.
    - Handles have Connect to…; the start card is itself the full-size form of its "+".
    - A browser flow zooms out every way and measures the card; another inserts through the panel.
    - For the owner to confirm: that the panel's equivalents, with the minimum zoom, meet the ruling.
M33. **M25 and the outage test, as ruled**: separate follow-ups, not in 4b. The outage test's record is unchanged:
    2,639 passed, 1 failed; three isolated reruns passed; cause unknown.
M34. **The checks on the corrected head** (37c764b, frontend only since 6d7766e):
    - Frontend: 538 tests in 46 files; lint, types, `check:api`, licences and both self-tests clean.
    - Build: index 557.70 kB of JS (180.66 kB gzipped), the editor's chunk 295.31 kB (96.09 kB).
    - Browser gate, on a freshly reset stack: 27 passed. The list and sign-in load 591,680 bytes; opening a workflow
      adds 307,451.
    - Serial CEL group, by ruling 66's procedure: 406 passed, none skipped, at cd864ea (85.78 s) and at 4e3061e
      (84.99 s).
      - Same image digest 34386ef0, uv 0.12.10, `uv sync --locked`.
      - The Temporal test server was fetched again from the URL recorded, its sha256 matching 1d712f6f.
      - The second run overlapped a stack rebuild.
      - No backend or deploy file changed between those heads and 37c764b.
    - The backend's parallel suite didn't rerun: no backend file changed since M23.

### Owner, 315e19f reviewed (2026-10-08, pasted)

"M26 is accepted as built, but final acceptance remains held at `315e19f` for one reproduced exit race. No push or PR
approval yet."
- The mutation-boundary, edge-placement and narrow-panel corrections hold. In Chromium, both climbing-join controls
  take pointer clicks, and cards and the panel's equivalents stay at least 24 px at the minimum zoom.
- At 320 × 720, Problems leaves a 260 × 150 px canvas, and Go to visibly focuses its step.
- The remaining correction: a router exit waiting on a save, joined by a sign-out through `mayLeave()`, then sent
  back here, released both holds. `agreedBy` recorded only the first caller.
  - "Record every participating exit before sharing the decision."
  - A router return releases only the router's hold. Sign-out keeps its own until it fails or is cancelled, or the
    editor unmounts.
  - Cover both arrival orders, with one shared question and no second prompt after logout.
- The serial CEL evidence covers the final head (no backend or deployment file changed). The outage test and M25
  stand as ruled.
- Visual approval is still pending: the six comparison images didn't reach the owner's conversation.

### 4b, after the review of 315e19f (2026-10-08)

M35. **Every exit that joins a decision holds the document in its own right** (the owner's correction).
    - `decide(by)` records its caller in `joined` before it shares the decision in flight. A consent adds every
      joined exit to `holders`.
    - `withdraw(exit)` removes only that exit, and the document is editable again only when none holds it:
      - the router's return (`onResolved` here) withdraws "router";
      - a failed sign-out (`stayed`) withdraws "guard";
      - the editor unmounting ends them all.
    - Tests, in both orders (router first, sign-out first), with the save held so the exits overlap:
      - the router sent back leaves sign-out's hold, and the navigation after logout asks nothing;
      - a failed sign-out gives the document back.
    - Another test: a failed save asks its one question once for both exits; leaving still holds after the router's
      return.
    - The router-first cases failed before the fix; sign-out first already held, its caller having been the one
      recorded.
    - Checks:
      - Frontend: 543 tests in 46 files; lint, types, `check:api`, licences and self-tests clean.
      - Build: the editor's chunk 295.47 kB (96.18 kB gzipped), index 557.70 kB.
      - Browser gate, on a freshly reset stack: 27 passed. The list and sign-in load 591,680 bytes; opening a workflow
        adds 307,602.
      - No backend or deploy file changed.
    - The owner's review. - An exit kind beyond these two would need its own name in `holders`.

### Owner, 4b accepted (2026-10-08, in chat)

The owner approved the visual checkpoint and, when asked, gave final acceptance of slice 4b at fd988dd, the exit-race
fix (M35) included. Push and a PR followed, by the same answer. As the owner's plan section says, the plan's rulings
join this ledger now, as 68–95. They are copied as ruled. Inside them, a reference to a plan ruling from 1 to 28 means
the ledger ruling numbered 67 higher (ruling 5 is 72); a higher number (47, 65) is already this ledger's.

68. **Accepted. Triggers wait for 4c.** Triggers are rows (schedules, webhook bindings, CSV uploads), not graph nodes,
   and their setup is 4c's. So 4b's chooser (1b) asks only how to start (Blank, Import from file); its first step,
   "What starts it?", arrives with 4c's trigger setup. The list (1a) has no Trigger column until then. - Showing a
   trigger the editor can't set up would promise what 4b can't do. - 1b's first step and 1a's column wait one slice.
69. **Accepted. A start card heads the canvas, and no end marker closes it.** The card is not a graph node: it stands
   for whatever starts a run, and its edges reach every entry step (a step with no incoming edge). Its "+" adds a
   first step. 1c's "End · run succeeds" marker is left out: a run ends when no step remains, and a drawn end would
   look like a step. - The graph has no trigger node to draw. - One cue fewer than 1c.
70. **Accepted. Step badges are problems and "runs as a separate step".** 1c's "conditional" badge needs the
   validator's liveness per step, which B6 brings in 4c; "disabled" has no meaning in the graph model (`GraphNode`
   has no such field). - Neither can be shown truthfully in 4b. - Two of the outline's three badges wait or drop.
71. **Accepted, with the filter correction. The list's filters and columns.** Name, Version, Last run (live; the last
   simulation beneath it, apart), Last 24 h, Enabled, and a row menu (Open, Export). Filters: All, Published,
   Unpublished changes (a workflow never published included: ruling 6), Needs attention, as a segmented control with
   counts (no pills, §6); the text filter matches names (no tags exist). No delete: no route deletes a workflow, and
   the API's database role has no DELETE grant on `workflows`. - What the API supports today. - No delete from the UI.
72. **Decided (owner, milestone 1 review, 2026-10-06): the index and a batched LATERAL read.** Slot 0047 holds
   `runs_workflow_last` on `runs (workflow_id, mode, queued_at DESC, id DESC) WHERE kind = 'run'`, chained from the
   head (0042); 0043-0046 stay reserved. The list reads every workflow's last root run of each mode in one LATERAL
   statement, one ordered index lookup per workflow and mode, keeping the tenant, root-run and mode filters and the
   newest-first order (the mode's form: ledger M5). See Task 5a. - The probe's history-wide scan and on-disk sort
   (1.5 s at 1M root runs). - An index on a hot table: one more entry per root run written.
73. **Accepted, with the filter correction. "Unpublished changes" compares graph hashes.** The draft's `graph_hash`
   (parsed and hashed on read, once per draft revision and off the event loop) against the active version's. Never
   published counts as unpublished, in the summary and in the list's filter. No edit count (outline B3). Positions
   count: moving a step is an unpublished change, as the hash says. - The hash is what publish records. - A list's
   first read after a restart parses each draft once (bounded by the 1 MiB body cap; the probe measures it).
74. **Amended (owner): live failures drive attention; simulations stay separately identified.** Needs attention is the
   last *live* root run failed or exceeded its deadline, or the active version can't run (`blocked_by`). The last
   simulated run is its own field (`last_simulation`) and shows apart in the simulation colour; a later successful
   simulation never clears a live failure, and a failed one never raises attention. Schedules' sync errors join with
   4c. **Last 24 h** counts root runs queued in the last 24 hours, live and simulated apart; the list shows the live
   count and "+N simulated". - Live and simulated are never blended (D2). - None.
75. **Accepted. The draft PUT's schema documents `Graph` while the route parses a plain object** (ruling 47). FastAPI
   ignores `WithJsonSchema` on a body and merges `openapi_extra` into the generated object schema (both verified
   against FastAPI 0.141.1), so `openapi.py` refines the one schema both the API and `dewpoint api openapi` emit: the
   draft PUT's body becomes exactly `{"$ref": "#/components/schemas/Graph"}`. The route keeps its own parsing, so its
   `graph.format` diagnostics and admission checks (non-finite numbers, depth, value count) stay as they are. -
   Typing the body as `Graph` would route bad drafts through `{"error":"invalid","fields":[...]}` and skip those
   checks. - The documented body and the parsed one are two declarations, held together by a test.
76. **Accepted. Answers keep a draft verbatim** (`draft: object` in the schema); the client types it as `Graph` at one
   boundary (`asGraph` in `src/lib/graph.ts`). - A response model typed `Graph` would re-serialize the stored draft
   with defaults the author never wrote. - One cast, at one place.
77. **Accepted. Inserting on an edge offers only steps that continue the flow:** a type with an `out` port, or
    `flow.loop`'s `done`. "+" after a port offers every type; a type with no ports (`flow.stop`, `flow.fail`) ends its
    branch. - Inserting a branching step mid-edge would have to guess which port carries the rest of the flow. -
    Inserting an `if` mid-flow takes two actions (add after, reconnect).
78. **Accepted. A new step** gets a random UUID, a key from its type's last segment (`transform`, then `transform_2`),
    a config with its schema's top-level defaults (a connection field gets none), no options (the server's defaults),
    and a place below its source; inserting on an edge moves every step at or below that place down one row. - Keys
    must be unique and match `^[a-z][a-z0-9_]{0,62}$`. - None.
79. **Accepted. Deleting a step asks first**, and when the step has exactly one incoming and one outgoing edge, its
    predecessor is reconnected to its successor; the dialog says so. References to the step in other steps' values
    stay, and the validator reports them (`ref.unknown_step`). Its `settings.declassify` entries go with it. - Healing
    a chain is what a person deleting a middle step expects; rewriting references isn't. - None.
80. **Amended (owner): single-pointer movement equivalent to a drag. Moving steps.** A pointer drags; a step's panel
    also has "Place on the canvas…" (the next click on an empty place puts the step there, centred on it; Escape or
    Cancel stops it) and four buttons that move it 20 px a click; Shift+arrow keys nudge the focused step by 20 px;
    Auto layout arranges the whole graph. Positions are saved in the draft. - WCAG 2.5.7: auto layout doesn't put a
    step where a person wants it, and keyboard nudging alone isn't a pointer's alternative. - A placing mode the
    design doesn't show (a bar above the canvas says what the next click does).
81. **Accepted. Connecting existing steps.** A port's "Connect to…" lists the steps that may follow it (not itself,
    not one that would close a cycle, not one already connected from that port); dragging from a handle does the
    same with a pointer. An edge is removed from its "+" item with Delete, after a confirmation. - Every pointer
    action has a keyboard one (2.1.1). - None.
82. **Amended (owner): demonstrably complete keyboard navigation. The keyboard model (D16), exactly.** The canvas is one
    tab stop. Its items are the start card, each step, each edge (its "+"), and each free port (its "+"); each lists its
    children from the start card down, and a step no entry reaches (a cycle no entry leads into, a step whose only edges
    in come from steps that aren't there) joins the start card's children, topmost first, so every item drawn is
    reached. A step joined from two places is a child of both, so the keys carry the path they came by (revision 3, the
    owner's correction 3): Down goes to the first child, Up back the way the keys came, Left and Right among the
    children of the item they came from (at a join, the branch taken), each passing over items already on the path (a
    cycle's way back, a self edge), so a path never repeats an item; a click, Tab or a change starts the path afresh
    from the walk's own. Home goes to the start card. Enter on a step opens its panel (read-only in 4b; 4c's drawer
    replaces it), on an edge or a free port the picker; `A` opens the picker after the focused step's first port; `C`
    connects from it; Delete asks; Escape closes the picker or panel and returns focus; Ctrl or Cmd+Z undoes, Shift+Ctrl
    or Cmd+Z redoes. A polite live region announces what changed. React Flow's own keyboard handling is off. Tests press
    every key from every path reached, over chains, branches, joins (one a second branch also reaches), cycles, separate
    components and an imported draft's dangling, repeated and self edges, editable and read only (a viewer, a conflict,
    a viewed version); the editor's own wiring is tested at that join for all three read-only cases, and the browser
    walks an imported cycle. - D16. - None.
83. **Accepted. A problem focuses its step** on the canvas (brought into view); the field itself waits for 4c's
    drawer. - 4b has no field to focus. - None.
84. **Amended (owner): server-bound publish confirmation.** Publish needs `workflow.publish`; an editor without it
    doesn't see Publish, the enable switch, or Make active. The confirmation names the next number from the versions
    list ("Publish version 3"), and publish sends that list's newest number as `expected_latest_version`, which the
    API checks under the lock that numbers the new version (Task 4); a mismatch is `409 version_changed`, and the
    editor refreshes the list and asks again with the new number. Publish names no number while the list loads,
    refreshes or can't be read. Callers that send no expectation (the CLI, the tests) publish as before. A publish
    refused for a check only publish runs (`connection.*`, `subflow.*`, `declassify.forbidden`, `lifecycle.*`,
    `version.unbounded`) shows those in the problems panel, marked "found at publish". - A dialog that names a
    number the server may not use isn't a confirmation. - One more 409 the editor handles.
85. **Amended (owner): validated, fail-closed portable files. Export and import (B12).** Export is the saved draft
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
86. **Accepted. Workflows lands a tenant.** Workflows joins the rail first; choosing a tenant (the switcher, the
    palette) opens its workflows (D10); the palette lists the current tenant's workflows and "New workflow". The editor
    uses the 60 px icon rail at every width, and keeps the shell's header (tenant, ⌘K, Security, Sign out); its own
    toolbar sits below it with the breadcrumb, save state and actions. - One header everywhere. - 1c's single header
    row becomes two.
87. **Accepted. React Flow's attribution link is hidden** (`proOptions.hideAttribution`), which its MIT licence allows;
    the third-party notices carry its licence. Only its structural `base.css` is imported: colours, borders and shadows
    come from our tokens. - An external link in the canvas, and a second visual language. - None.
88. **Accepted, extended by correction 4. Undo and redo stay local** (D17): a history of up to 100 documents in
    memory, cleared when the editor closes. Undo is off after a conflict (the editor is read-only), and while a
    publication or an activation runs. - D17. - None.
89. **Accepted (owner, with revision 2); extended in revisions 3 and 4. Leaving the editor saves first, as one
    transaction.** One decision, the editor's: save what's pending; when that can't be done (a failed save, a
    conflict), ask: stay, download my version, or leave without saving. It answers every way out: router navigations
    (the breadcrumb, the rail, the palette, the tenant switcher) through the router's blocker; sign-out, which asks it
    before revoking the session or clearing the query cache; and an ended session, which keeps the shell and the
    unsaved work on screen with a notice instead of swapping it for the sign-in page. Exits that overlap share the
    decision in flight, so one answer (a Stay included) settles every one of them, and Sign out runs once at a time.
    Once an exit is agreed to, the document is held (no edit, no undo) until the exit completes or is withdrawn (a
    sign-out that failed withdraws it): no edit lands after the consent and is discarded under it, and the navigation
    that follows sign-out doesn't ask again. Closing the tab gets the browser's prompt. Reload after a conflict asks
    before discarding the local version. The saver is disposed when the editor closes: a save still in flight that
    answers afterwards sends nothing more. - The debounce and a conflict both leave work only on the screen, and a
    revoked session or a cleared cache must not take it first; neither may an exit's consent stand for work made
    after it (the owner's review of revision 3). - Leaving waits as long as a save takes; an ended session waits for
    the person's choice; the editor is read only while a sign-out waits on the server.
90. **Accepted (owner, with revision 2); extended in revision 3. The editor opens on a fresh snapshot, and stays
    open.** It waits for the workflow read made after it mounted (never a cached copy, which would conflict on the
    first edit), and keeps what it opened with (the workflow, the step types, the role): a later read or a failed
    refresh of an auxiliary query neither replaces nor closes it, and a failure shows beside it; the query cache is
    cleared only at sign-out, after the editor's decision. -
    A stale draft turns the first edit into a conflict; a background failure must not discard local work. - One read,
    and a moment of "Loading…", on every entry; step types refreshed elsewhere may lag in an open editor.
91. **Accepted (owner, with revision 2); extended in revision 3. A check is current only for what's on the screen.**
    The editor says "Checking…" or "Not checked" before the first answer, "Check failed" when a request fails, "…
    before your edits" when the answer is for an older revision or edits came since; badges sit on the steps, and a
    step's panel lists its problems, only while the check is current. What only publish found carries its own
    snapshot (revision and generation) and is current on the same terms: afterwards it stays in the panel's "Found
    at publish", marked as before the latest edits, never in a step's problems or an unqualified count. Viewing a
    version shows none of the draft's. - A failed or stale check must not keep reassuring, nor a stale finding
    alarm. - Badges disappear between an edit and the next check (about a second, plus the check).
92. **Accepted (owner, with revision 3): the non-null hash proof shows a version holds the submitted graph, not which
    caller published it. An outcome is said only when known.** A publish or an activation without an answer from the API
    (the network, or a 5xx) is read back and reported as found, or as not known; never as failed, and never as published
    without evidence. A version holds this draft only if its recorded `graph_hash` is the hash the server gave for the
    revision submitted (the save's answer, or the load's `draft_graph_hash`); a version of that number with another hash
    is another publication, and this one was refused; with no hash for the draft submitted, nothing is proven either
    way, and it's "not known". The active version and the draft's comparison always come from the read (or the answer)
    itself, never from the number hoped for. A version made active stays made active when the read after it fails, and
    the draft's comparison with it is "not known" until read (`Saved · v1 is active`); nothing read back leaves the
    active version "not known". Only the newest "View version" answer is shown. - A version's existence and the draft's
    current revision don't say which revision the version holds (the owner reproduced both wrong inferences). - Two
    reads after a lost answer; the draft's hash travels in the save's answer and the summary.
93. **Accepted (owner, with revision 2). A draft that can't be exported portably is offered as it is, labelled.** In
    the editor, a refused export offers "Download this draft as it is (not portable)", a `.draft.json` file the
    importer refuses (it isn't a `dewpoint.workflow` file); the list says to open the workflow for it. - The owner's
    option of a separately labelled recovery download: the person keeps their work, and the label says the file
    holds this tenant's ids. - One more download path carrying the tenant's ids, as the conflict's download already
    does.
94. **Accepted (owner, with revision 3). A save's answer names the version it compared with.** `put_draft` reads the
    active version after its compare-and-swap, under the row lock the swap took, and answers it (`active_version_id`,
    `active_version_number`) beside `unpublished_changes` and the saved draft's `graph_hash`; the editor labels the
    active version from that same answer. - The route reads the workflow without a lock, so an activation can land
    between that read and the swap (the owner's correction 5). - Two fields more on each save's answer, and one read.
95. **Accepted (owner, with revision 3). Bindings are chosen, from what was read.** Each binding starts at "Choose…",
    and the import waits for a choice for every one: one of this tenant's, or "Leave unbound" (left out of what's sent).
    While this tenant's connections and workflows are loading, or when they couldn't be read, no choice is offered; a
    binding with nothing to offer says to choose "Leave unbound". - Unbound must be a deliberate choice, never a default
    nor a failed lookup. - One choice more per binding before an import.

### Owner, #60 reviewed (2026-10-08, pasted)

The owner reviewed head d960959 against main 6e092b5: "#60 is not merge-ready." The exit-race hold closes; the
owner reran the original reproduction, and the editor stays locked until sign-out gives up its own hold.
- **High.** Combining the migrations made two Alembic heads: 0047 still chained from 0042, while main had gone on to
  0044. "Chain it from main's current head, 0044, without rewriting main's migrations." Update its reservation
  comment (main holds 0043 and 0044), keep the historical ruling, and append the corrected chain, with replacement
  slots coordinated for future work.
- **`/node-types`** needs no choice between contracts: keep main's gzip negotiation and catalog transport with 4b's
  `NodeTypeOut` and run-time metadata. A raw `Response` bypasses the response model, so validate and serialize with
  `TypeAdapter(list[NodeTypeOut])` before `catalog_answer`, as main's `/trigger-types` does. Keep `/trigger-types`,
  regenerate both frontend API files from the combined backend, and exercise metadata, compression and OpenAPI
  together.
- Main requires both CodeQL contexts, `analyze (python)` and `analyze (javascript-typescript)`. "Acceptance needs the
  resolved, combined tree checked—not just the previously accepted branch."
- M25 and the outage test remain the agreed separate follow-ups.

### 4b, merged with main for #60 (2026-10-08)

M36. **The branch merges main at 6e092b5 (be8bfc7, a merge commit), as the owner's review of #60 rules.**
    - **The migration chain.** 0047 (`runs_workflow_last`) now chains from main's head, 0044. The chain has one head
      again, and main's migrations are untouched. A test holds it: one head, 0047 after 0044, read from Alembic's own
      scripts. The historical ruling stands as written (ruling 72; M5): 0047 was written on 0042.
    - **Slots.** Main used 0043 and 0044, which this ledger had reserved for B4b and B8. Those two need replacement
      slots, which the owner assigns. The next free numbers are 0048 and 0049. 0045 and 0046 stay reserved, for B7 and
      B9.
    - **`/node-types`.** It keeps main's gzip negotiation and catalog transport, and answers 4b's `NodeTypeOut`. Each
      row is validated and serialized through `TypeAdapter(list[NodeTypeOut])`, as `/trigger-types` does, before
      `catalog_answer`, off the event loop: the catalog runs to megabytes. `/trigger-types` is unchanged, and both
      frontend API files were regenerated from the combined backend.
    - Tests for the route:
      - the gzipped palette carries B5's metadata, the same as plain;
      - a row the model refuses is never sent. Without the validation this test failed; with it, it passes.
    - The cost if wrong is the owner's call: a row that doesn't fit the model now fails the palette (500) rather than
      reaching the editor.
M37. **Two summary tests follow main's 0035.**
    - Since 2b-4a, `runs_version_fk` names the tenant: `(workflow_version_id, workflow_id, tenant_id)`. A run can no
      longer name another tenant's workflow.
    - `test_another_tenants_runs_never_count` now asserts the database refuses such a row, a stronger guarantee than
      the M3 scenario the owner had restored.
    - The statements' own tenant filter is still held by `test_the_statements_filter_by_tenant_themselves`.
    - The reference comparison seeds another tenant's newer run of its own workflow, not of this one.
    - What the owner had required (milestone 1 review, correction 2) is now impossible to seed; the owner may want the
      new form confirmed.
M38. **The combined tree's checks** (be8bfc7, main 6e092b5 merged):
    - Backend:
      - ruff, format (743 files) and mypy (275 source files) clean; import contracts 11 kept; pip-licenses clean.
      - The OpenAPI dump matches the regenerated `openapi.json`. The replay gate, against main, finds no history
        changed.
      - The parallel suite, without the serial CEL group: 3,955 passed, 0 failed, in 18 min 29 s. That ran past the
        owner's ~10 minutes without asking first: main's added tests weren't estimated.
      - The serial CEL group, by ruling 66's procedure: 406 passed, none skipped, 99 s.
    - Frontend: 543 tests in 46 files; lint, types, `check:api` (the regenerated schema), licences, self-tests and the
      build clean.
    - Browser gate, on a freshly reset stack (main's new retention service included; the scratch stack's `.env` gained
      a generated `DEWPOINT_RETENTION_DB_PASSWORD`):
      - The first run had **1 failed and 20 not run**. Foundations' palette step typed "secur" and pressed Enter, and
        landed on Settings → Members, not Security. The load average was then about 37 on 14 cores (other sessions).
        A race between typing and the palette's filtering is suspected, not established.
      - The rerun passed 27 of 27.
    - CodeQL, run locally as codeql.yml does, with CI's versions (CLI 2.27.1, python-queries 1.8.11,
      javascript-queries 2.4.6, read from main's run 37746611558): 0 findings in each language.
    - gitleaks 8.30.1 over f65c6f9..HEAD: no leaks.

### Owner, 5c6d802 reviewed (2026-10-08, pasted)

"The integration blockers are resolved at `5c6d802`." The owner accepted the revised cross-tenant summary tests and
found no new blocking defect.
- The owner ran 47 focused backend tests, matched the regenerated OpenAPI against the combined backend, and exercised
  `/node-types` over all 310 node types from six shipped plugins, Mist included: identity and gzip answer identical
  validated catalogs. Alembic has one head, 0047 → 0044, and main's migrations are untouched.
- A minor correction: `test_migration_chain.py` wasn't database-independent. It inherited
  `clean_db → owner_sessionmaker → pg_url`, which runs `alembic upgrade head` first, so a second head would fail setup,
  not the assertion.
- The qualifications to keep explicit:
  - The browser failure's cause is unknown. Keep both runs, and synchronize the palette step on its focused input and
    selected option rather than attribute the failure to load.
  - Different query and SARIF-rule counts don't establish missing coverage, but matching pack versions alone doesn't
    prove CI parity. Local CodeQL results don't satisfy GitHub's required checks.
- 0048 for B4b and 0049 for B8 are "sensible replacement reservations, subject to the owner's explicit assignment";
  0045 and 0046 are unchanged.

### 4b, after the review of 5c6d802 (2026-10-08)

M39. **The two corrections, and M38's wording withdrawn where it went too far.**
    - `test_migration_chain.py` overrides `clean_db` with a no-op, so its setup plan touches no database. With 0047's
      old parent briefly restored (0042), both assertions failed on their own terms (`['0044', '0047'] == ['0047']`,
      `'0042' == '0044'`). With 0044 restored, both pass, and the file is unchanged.
    - The foundations palette step now waits for its search to be visible and focused, for "secur" to be in it, and
      for Security to be the selected option before Enter. The browser gate then passed 27 of 27, at a load average
      of about 30.
    - M38's first gate run: its cause is **unknown**. The run is kept as recorded (1 failed, 20 not run; the palette
      went to Settings → Members), and so is the rerun (27 passed). M38's "A race between typing and the palette's
      filtering is suspected" is withdrawn.
    - CodeQL: the local runs (0 findings in each language) used CI's CLI and pack versions. That doesn't prove parity
      with CI, and different query and rule counts don't establish missing coverage. They don't satisfy GitHub's
      required checks, `analyze (python)` and `analyze (javascript-typescript)`, which must run on #60's head.
    - Slots: 0048 (B4b) and 0049 (B8) are proposed replacements, not yet assigned; they wait for the owner's explicit
      assignment. 0045 (B7) and 0046 (B9) are unchanged.

### Owner, after #60 merged (2026-10-08, in chat)

"assign 0048 to B4b and 0049 to B8", and "M25 approved". #60 had merged green (441b854), with every check passing,
both CodeQL analyses included. The slot table above now shows the assignment; 0045 and 0046 are unchanged.

### M25, built (2026-10-08, branch fix/m25-sensitive-values from main 441b854)

M40. **A value's schema problem is said without the value, and export refuses a sensitive literal** (M25, as the owner
    ruled and approved).
    - Both schema-error sites, `_schema_errors` (a step's literal config) and `_check_instance` (a literal value, and a
      reference's default, against the field it fills), say `config.invalid` through `schema_messages.explain`. It
      builds the message from the failing keyword and the schema's constraint, never from the value.
      - For example: "Must be at most 3 characters long.", "Must be one of …", "Needs `token`.", and "Has a property
        its schema doesn't allow: `extra`.". A property is named by its name, which is structure.
      - A keyword without words of its own is named; the `false` schema says "Isn't allowed here."
      - jsonschema reports a property-name failure under the inner keyword; its schema path says so, and so does the
        message.
    - Every `config.invalid` changes, sensitive field or not: no field shows a literal back. No test asserted
      jsonschema's wording, and no recorded replay history holds a `config.invalid`.
    - Two other messages were checked and quote no value: the workflow's own declared schemas (`settings.invalid_schema`
      quotes the schema), and envelope syntax (fixed sentences, or a reference's own root name).
    - Export applies the validator's own rule (`sensitive.literal`, from the same `check_draft` as `/validate`). The
      draft is refused with `not_portable`, reason `sensitive_literal`, by step and field, beside any id problem: every
      reason at once. The same field filled from the run's input exports.
    - The frontend's export refusal says "it has a sensitive value written into a step (send)". There is no masking in
      the browser: the server never sends the value.
    - Tests, each watched failing first:
      - the builder over 28 keyword cases with a sentinel string and number that never appear, a property named like a
        keyword, the fallback, and jsonschema's own words quoting the value (the regression);
      - each validator site's message, never the sentinel;
      - the export refusal and its run-time-input counterpart;
      - the frontend's words.
    - The owner's ruling. - Messages say less than jsonschema did ("'ab' is too short" becomes "Must be at least 3
      characters long."): the field, named beside each, shows where.

### Owner, 4c-1 plan (2026-10-09, in chat)

The owner chose to have the 4c-1 plan (revision 6, deaa466) built: "go ahead", inline in one session, with a pause after
milestone 2 (screenshots beside 1c) and at the final checkpoint. Two policies in ruling 7 were confirmed in the review
of revision 4: rejecting `1e300` is a conservative editor input policy, not an engine requirement nor a promise to
keep decimals exactly; and opening the drawer never rewrites existing values. Rulings 96 to 113 stay the plan's until
the owner accepts the slice.

### 4c-1, milestone 1 (2026-10-09)

M41. **The branch starts from `main` at ab7fcfe, not 0838e4f** as the plan was written against: two backend-only fixes
    had merged since (#67, #68). `feat/editor-4c1` is ab7fcfe with the plan merged in (0be88e1). - The plan says to
    cut from `main` when execution starts. - None: neither touches the frontend.

### 4c-1, milestone 2 (2026-10-09)

M42. **The plan's `// prettier-ignore` markers stay** (Tasks 5 to 7). They were first dropped as noise, then restored
    (bd0b614, comments only): 22 files already mark hand-formatted lines with them. - The codebase's convention. -
    None: comments.
M43. **The notices name Radix Tabs from Task 7, not Task 5**: the notices plugin lists only packages whose code lands
    in a chunk, and nothing imports `Tabs` before the drawer. Task 7's build lists `@radix-ui/react-tabs 1.1.21`, and
    the browser gate's notices test checks it. - The plugin's rule. - None.
M44. **`e.relatedTarget` without a cast** (Tasks 6 and 9): lint refuses `as Node | null`, which React's types make
    unnecessary. - The lint rule. - None: types.
M45. **Two conflict tests look for the banner by its own words** (Task 8): the leave question is a native dialog
    rendered while closed, so "This draft was changed elsewhere" matched it too. - The plan's query matched two
    elements. - None: the same element.
M46. **An async `act` in the codebase's form** (Task 8): `act(() => Promise.resolve(answer()))`, as lint refuses an
    async arrow with no `await`. - None.

### Owner, milestone 2 reviewed (2026-10-09, pasted)

Four defects at 8bfc9e0, reproduced in tests and in Chromium with fake APIs: (1, high) a version's drawer showed the
draft's pending text; (2) export skipped text typed while its save was awaited; (3) Clear discarded a stale edit but
left the value; (4) the list of edits not applied left focus on the page body. Milestone 3 held. Five points the
checkpoint raised got the review's recommendations, recorded as recommendations.

### Owner, milestone 2 points ruled (2026-10-09, in chat)

The owner's answers: O1, "Edit as JSON" gets a pressed look, in milestone 3; O2, a disabled look for the drawer's
controls only; O3, the flow plugin's fields get written titles as a follow-up of their own (since #70); O4, "How its
formulas run" drops the repeats, keeping the formulas no field says. The duplicate diagnostic and the Mist title became
follow-ups (#69, #71, #72).

### 4c-1, after the milestone 2 review (2026-10-09)

M47. **The review's four findings, fixed** (f2bd150), each by a test that failed first:
    - a version's read settles what was typed during it, or asks (Discard and view the version, or Go back to them);
      a version's drawer gets read-only actions blind to the draft's edits not applied ("asks about an edit typed
      while a version is read, and never shows it in the version"; "keeps an edit typed while a version is read, when
      the person goes back to it"). No test can drive that guard once the read settles; the next review called it
      enforcement of the version/draft boundary, not a product ruling;
    - export settles and saves in one loop, as leaving does ("asks about an edit typed while an export waits for its
      save"); publishing has no such gap: it disables editing and keeps its dialog open while it saves;
    - Clear writes over a stale edit it discards, the editor's guards still answering ("clears the field on purpose,
      even when what was typed in it is stale"; "clears nothing when the editor refuses the write, and says why");
    - Close returns focus to the toolbar's count, else the canvas; a discarded entry lands on the list's heading
      ("gives focus back to the count…"; "keeps focus in the list when its last entry is discarded").
M48. **The removal/undo test waits for the removal's focus** (1b43b8b, test only): "never moves a held edit to an
    equal item when a removal is undone" typed before the focus move to Add landed, so no edit was held (9 of 12 runs
    failed alone). It now waits, and checks "5x" held and counted before the undo (12 of 12).

### Owner, milestone 2 signed off (2026-10-09, pasted, confirmed in chat)

A pasted review gave the visual sign-off of milestone 2's screens (the single column accepted for this slice; the
mocked viewer shots show appearance, not authorization) and recommended merging `main`. The owner confirmed in chat:
the sign-off stands, milestone 3 may start, and `main` at e9272e0a merges first.

### 4c-1, milestone 3 (2026-10-09)

M49. **The branch merges `main` at e9272e0a** (e35a792): #69 to #72, backend only. The branch's `backend/` and
    `deploy/` equal `main`'s; the frontend suite and the browser gate passed on the merge, and milestone 2's evidence
    was retaken on it (the flow plugin's written titles show).
M50. **Two of Task 8's conflict tests wait 3 s for the banner** (275bc0e, test only): the save that meets the conflict
    is sent 1 s after the edit, and the default 1 s wait lost the race under the full suite's load. 4b's conflict
    tests wait 3 s.
M51. **O1, O2 and O4, built** (66fc658), each by a test that failed first:
    - O1: the toggle takes Segmented's pressed tokens under `aria-pressed` ("shows Edit as JSON pressed while it's
      on…");
    - O2: scoped on the drawer, so 4a's Field and Select inside it (error handling, the key) look disabled too and
      4a's forms elsewhere don't; values in muted ink (about 6:1), as the disabled ink is under 3:1 on its fill ("gives
      a viewer's drawer controls a disabled look, their values legible");
    - O4: a field that says how its formula runs registers while shown; a formula on the other tab stays listed until
      its tab opens ("says how a formula runs once, under its field, and lists only what no field says").

### Owner, milestone 3 reviewed (2026-10-09, pasted)

Three defects at 66fc658: (1) a rename applied with the rest lost its word on formulas; (2) "Go to it" missed held
keys and limits; (3) "Go to" gave up before a picker's list loaded. The owner then chose, in chat, to run Task 15
once they were fixed.

### 4c-1, after the milestone 3 review (2026-10-09)

M52. **The review's three findings, fixed** (b773518), each by a test that failed first:
    - `applyAll`'s note carries its step, and bulk settling keeps it ("keeps a rename's word on formulas when it's
      applied with the rest, as before an export"). Found beside it: the note showed in any open step's drawer, and
      now only in its own ("says a rename's word only in the renamed step's drawer");
    - "Go to it" routes by the edit's kind: a key to the key field, a limit to the error handling, opened, and an entry
      name (the same gap) to its name ("goes to a held key…", "goes to a held limit…", "goes to a held entry name…");
    - a Go to whose control is loading waits for it, watching the drawer, and gives way to the person's click or key,
      another Go to, or the drawer closing ("goes to a field whose control is still loading…"; "drops a pending Go to
      when the person moves on…"). Its test answers after several frames: it had passed by luck when the answer beat
      the first one.

### 4c-1, milestone 4 (2026-10-09)

M53. **The drawer's browser flows read the running app's labels**: the flow plugin's written titles since #70 ("Duration,
    in seconds", a case's "Condition" and "Port name"); text fields by role (`getByLabel` matched the Fixed/Formula
    group too); the drawer's twin of a canvas "+", which shares its name. The gate: 33 passed, the 27 earlier flows
    and 6 new, under the CSP and axe.

### 4c-1, the final checkpoint (2026-10-09)

A fresh reviewer read the whole branch (e9272e0a..55dd746) against the plan, outline §6, the Review Focus and these
rulings: nothing critical, four important findings, nine minor, and no ruling judged wrong. It verified the pure layers
against the engine's constants and grammar, found no AI tells, and checked the O2 contrast (6.0:1 light, 6.7:1 dark).

M54. **The four important findings, fixed** (5b9f45f), each by a test that failed first:
    - focus goes back to the field's control after its Discard, Apply here, Clear and Replace, and to a limit after
      its own (WCAG 2.4.3): "keeps focus at the field after its Discard or its Clear", "…after Apply here", "gives
      focus to the new control after a reference is replaced", "…after a sensitive field's fixed value is replaced",
      "keeps focus at a limit after its Discard";
    - a reference or a template in a sensitive field shows as one, as the engine allows (only a fixed value there is
      hidden and offered a Clear): "shows a reference in a sensitive field as a reference, never as a fixed value to
      clear";
    - an emptied list item or map entry keeps its place, blank, never "Required" nor announced required: "keeps an
      emptied list item blank without calling it missing";
    - a sensitive part under `patternProperties` or `propertyNames` counts, as `engine/sensitive.py`'s positions do:
      "finds a sensitive part under patternProperties or propertyNames, as the engine does".
M55. **Nine minor findings, deferred** for the owner: hexadecimal and binary number notation read as decimal; a
    formula over 16,384 characters truncated on paste; list items keyed by index (view state follows the position);
    every "Show choices" button named alike; a picker's loading and "none yet" states labelled without a control; the
    O2 contrast pair outside the token check; a limit's pointer colliding with a config property named `options` (no
    installed type has one); valid JSON held through Escape (kept and counted, not applied); the heading's focus
    before a pending Go to (a double announcement). What the reviewer set aside is each the plan's, the owner's or
    4b's call, unchanged.

### Owner, the final checkpoint reviewed (2026-10-09, pasted)

Acceptance held at 97235e3 for two blockers: a formula pasted past the limit was cut by the browser and the rest
written (`true` + 16,380 spaces + `&& false` saved as `true`), so M55's paste item isn't cosmetic; and clearing an
optional list or map left focus on the page body. The milestone 3 fixes and the screenshots added no other blocker.

### 4c-1, after the final checkpoint's review (2026-10-09)

M56. **A formula past the engine's limit is held whole, never cut** (the paste item of M55, re-graded by its effect: a
    silent change to the logic). The control has no `maxLength`; `formulaProblem` (16,384 characters, the engine's
    `MAX_CEL`) holds longer text as an edit not applied, with why, in the control and when held edits are applied, and
    the draft keeps what it had: "never applies a formula past the engine's limit, and says why", "holds a formula past
    the engine's limit whole, never cut, and leaves the draft as it was", "keeps a formula past the limit out of the
    draft, held and counted, never cut".
M57. **Clearing an optional list or map lands on its Add**, the one control left: "lands on Add after a map is
    cleared", "lands on Add after a list is cleared".

### Review sign-off at c30d74e (2026-10-09, pasted)

A pasted review signed off 4c-1 at c30d74e on the review side: both blockers corrected (its five failing cases pass,
with two more: the exact 16,384/16,385-character boundary, and export refusing an oversized held formula while keeping
its whole text); 710 tests, typecheck, lint, the API check and the build pass independently; the corrected zip names the
new checkpoint and its 109 screenshots match the reviewed ones byte for byte. The browser gate and CodeQL stay as the
implementer reported them. The eight deferred minors may stay tracked for the catalog as shipped, with one condition:
the `options` collision is latent text loss, to fix before any type with `config.options` is enabled. The earlier
unidentified suite failure stays unexplained. The owner's adoption of rulings 96 to 113 and the push and PR stay the
owner's decisions; the review recommends keeping the isolated stack through CI and the merge.

### Owner, 4c-1 accepted (2026-10-09, in chat)

After the review side signed off at c30d74e, the owner, when asked, accepted slice 4c-1 and adopted its plan's rulings
(a928f78, the review's sign-off recorded). Push and a PR followed, by the same answer; the eight deferred minors go to
one GitHub issue, the `options` collision marked as latent text loss; the isolated stack stays through CI and the merge.
As the plan's own section says, its rulings join this ledger now, as 96–113. They are copied as ruled. Inside them, a
reference to a plan ruling from 1 to 18 means the ledger ruling numbered 95 higher (ruling 18 is 113); a higher number
(83) is already this ledger's.

96. **Accepted. 4c in three plans.** 4c-1 is the drawer; 4c-2 is data; 4c-3 is triggers (the owner, 2026-10-08).
   - **4c-2, data:** B6's scope API; pills with the upstream tree; the condition builder; the "conditional" step
     badge (ruling 70); the declassify list; B7's samples with the per-attempt connection record in slot 0045 (which
     sub-project 3 didn't build). D8's surfaces come as static mockups first.
   - **4c-3, triggers:** B13; the manual input form and CSV columns; schedules; webhook bindings and Settings →
     Webhook endpoints; 1b's "What starts it?" and 1a's Trigger column (ruling 68); schedule sync errors raising
     "needs attention" (ruling 71).
   - Why: each is a 4b-sized piece with its own review. The cost: three plan reviews instead of one.
97. **Accepted. The drawer replaces the step panel in the side column.**
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
98. **Accepted. Setup holds the schema's required top-level fields; Options holds the rest, in the schema's order.**
   - There's no `x-group`: no manifest uses it, and the plugins-3 ledger rules it out for flow steps.
   - A step with nothing required opens on Options. A step with no fields says so, without tabs.
   - A tab's label counts the problems in its fields ("Options · 2 problems").
   - Why: §10.3's "required fields only". The cost: a plugin can't order fields except through its schema.
99. **Accepted. A field's label is its schema `title`, or its name when there's none.**
   - Titles are display annotations: `_schema_contract` keeps them out of a type's contract hash, so a plugin may
     improve one within a version.
   - The drawer shows the titles as the plugins write them ("Duration S").
   - Why: plugins own their wording. The cost: some labels read stiffly until their plugin improves them.
100. **Accepted. The widget comes from `x-widget`, then the engine's markers, then the field's type.**
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
101. **Accepted. A value is fixed, or a formula, where the engine takes it.** These are the engine's own rules (`allowed_kinds`,
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
102. **Accepted. The browser checks only required fields, types, and what a save would refuse.**
   - A required field the person empties says "Required".
   - A number that doesn't parse says so and isn't saved, and so does JSON that doesn't parse. So does a number that
     parsing would change: one too large to be finite, or a whole number past 2^53, in whatever notation it's written.
   - That last rule refuses `1e300` too. It is a conservative editor input policy: not an engine requirement, and no
     promise that decimals are kept exactly. Confirmed in the review of revision 4, pasted in chat on 2026-10-09.
   - Opening the drawer never rewrites a value already in the draft, even one the editor would refuse as typed.
     Confirmed in the same review. Pinned by Task 6's `writes nothing by showing a field`.
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
103. **Accepted. One undo step per field per focus.**
   - A field's typing while it keeps focus coalesces into one history entry. Leaving the field, or any other edit,
     starts a new entry.
   - A discrete choice is one entry each: a select, a checkbox, Fixed or Formula, Add, Remove, Move.
   - Field edits aren't announced: the control says what it holds, and the toolbar says whether it's saved.
   - Saves follow D17 unchanged.
   - Why: undo by keystroke would make undo useless. The cost: none.
104. **Accepted. Ports come and go with settings.**
   - An edit that takes ports away deletes the edges that left them, after asking, as deleting a step does (ruling
     79). The edits that can: removing a switch case, no longer routing errors to a port, a JSON edit of the cases.
     One undo restores the setting and the edges.
   - A canceled question leaves a JSON edit unapplied, its reason at its control (ruling 18).
   - A case's port renamed in place keeps its edges. Its name applies when focus leaves or on Enter.
   - A port name the graph's format refuses, or one another port of the step has, is refused there: edges hang on
     port names.
   - A new case gets the first free port name `case_N`.
   - Why: a port's edges mean nothing without the port. The cost: none.
105. **Accepted. The error-handling chip.**
    - It says, in words, what a failure does ("On error: fail the run"), plus the attempts and timeout when they
      differ from the type's.
    - It opens a section with three settings:
      - what a failure does: Fail the run, Continue with the next step, or Route to an error port;
      - the attempts (1–20);
      - the timeout (above 0, up to 86,400 s).
    - Each setting left empty takes the type's default, named in its hint. "Fail the run" is the default, so it
      isn't written.
    - Why: §10.3's chip, and the graph's `Options` bounds. The cost: none.
106. **Accepted. Key rename.**
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
107. **Accepted. The connection picker.**
    - It lists this tenant's connections of the field's type (every role may read them), named, with their status in
      words.
    - With none of that type, it says so: Mist links to Connections (D1); other types are added by an admin (4g's
      forms come later).
    - A value naming no listed connection shows as "A connection that isn't in this tenant" until it's changed.
    - Why: §3.3. The cost: none.
108. **Accepted. The workflow picker** (`flow.run_workflow`'s `workflow_id`).
    - It lists this tenant's workflows other than this one.
    - A value naming none shows as "A workflow that isn't in this tenant".
    - Why: typing a UUID is no way to choose. The cost: none.
109. **Accepted. Live options load on request, never on render.**
    - A "Show choices" button loads them through `POST …/node-types/{ref}/options`, with the step's connection and the
      text typed.
    - When the type takes a connection and the step has none, the field asks for one first and sends nothing.
    - Each failure is said in words, and a typed value is kept as typed: the list helps, it doesn't gate.
    - **Choices belong to their scope**: the tenant, the step's type, the field, and the connection's id and revision.
      Each change of scope starts a new era, never returned to. The shown choices go, an answer still on its way from
      an older era is ignored even when the scope comes back, and another click is needed.
    - Loading stays off until the connection's revision is known: while the list loads, when it fails, when it
      doesn't name the connection. The last two are said.
    - Why: an options call reaches the plugin's service (for Mist, Mist itself), so it is the person's act, never a
      side effect of opening a drawer (D24). The cost: one click, again after a change of connection.
110. **Accepted. JSON is the value as the engine reads it.**
    - A `{"$value": …}` object in it is computed, as in an imported file, and its hint says so.
    - It applies when focus leaves.
    - "Edit as JSON" is offered on groups, lists and maps without a sensitive part. Untyped fields and unions are JSON
      always.
    - A map's entry can't be named `$value`: the engine would read the whole map as computed.
    - **A `literal` envelope stays a literal.** It's edited as its payload, its hint saying it's kept as data, and
      saved wrapped again. Its kind changes only through Fixed/Formula, Replace or Clear.
    - Why: D19; one reading of `$value` everywhere. The cost: none.
111. **Accepted. A problem focuses its field** (ruling 83, the part that waited for 4c).
    - "Go to" on a problem whose field is inside the step opens the step's drawer on that field's tab and focuses the
      field: the closest one shown, for a pointer inside a list, a map or a JSON value.
    - A pointer no field shows lands on "Problems with this step", which lists it.
    - A problem about the step as a whole (no field, or its whole config) focuses the step, as in 4b.
    - Why: ruling 83. The cost: none.
112. **Accepted. One new dependency, `@radix-ui/react-tabs` 1.1.21**, for the drawer's tabs, on the outline's approved list.
    - Its first browser check is at the end of Task 7, before lists, maps and pickers are built.
    - A CSP violation stops the work for the owner.
    - Why: D23. The cost: none.
113. **Accepted. Unapplied edits are the editor's, never lost in silence.**
    - What counts: text a control holds that isn't in the draft. That is JSON being typed or refused; a map entry's
      name, a port's name or a key being typed or refused; a number or a limit that doesn't parse; a formula the
      graph's format refuses.
    - The editor keeps each, by its step, its field and its kind, never the control. A tab change, a JSON toggle, a
      closed and reopened drawer, or an undo keeps it. It shows at its control, with its reason and a "Discard".
    - **What's held is what shows.** The control displays the held text over its own. The field's view follows what's
      held: JSON as JSON, a formula as a formula.
    - A control writes first and releases its held text only when the write lands. A refused write (an editor turned
      read only, the graph's admission) keeps the text and says why.
    - **What it was typed over.** Each held edit records its base, the value it was typed over, and its lineage, the
      lists and items on its path. Where either has changed since, the edit is applied, or typed through, only when
      the person chooses "Apply here"; otherwise it's discarded, or asked about at an exit. The changes that count: an
      undo moving or removing a list's items, even equal ones; a literal turned to data. The edit keeps the reading it
      began with, a literal's or not.
    - **Their list.** The toolbar's "N edits not applied" opens a list of them all: step, field, text, reason, "Go
      to it", "Discard". It's where an edit whose field is gone is recovered, never by recreating the field.
    - **Discard means discard.** Leaving a field applies what's typed in it; moving to its own Discard or Clear, by
      keyboard or pointer, doesn't.
    - What's held shows first, before what the value under it has become: a reference, a hidden secret, another mode.
    - Every write and settlement reads the editor's latest document, written at once with its history.
    - The toolbar counts them ("1 edit not applied") beside the draft's own state, and the count opens their list.
    - Leaving the editor (the router, sign-out, an ended session), publishing, exporting and viewing a version first
      apply every one that can be applied, as one undo step. Those that can't (refused, or taking ports away) are
      listed in a question: "Discard them and …" or "Go back to them". Leaving folds them into 4b's leave question.
    - **Leaving is one transaction.** It settles, saves, and settles again whatever was typed while the save was
      awaited, until nothing is unapplied or unsaved, or the person is asked.
    - Many edits apply in a fixed order, whatever order they were typed in: values before names, the deepest first.
      An entry's rename waits while an edit inside the entry can't be applied.
    - **Recovery.** "Download my version" is the draft. Wherever it's offered, the drawer says the edits not applied
      aren't in it, and "Download the edits not applied" writes them as a file of their own, never into the graph,
      which is what runs.
    - A change to what holds an unapplied edit first applies the edits beneath it, as one step with the change: a
      list item's move or removal, a map entry's removal, Fixed/Formula, a JSON toggle. When one can't be applied,
      the change waits, and the edit's control says why.
    - Clear and deleting a step discard the unapplied edits beneath them, on purpose. The delete question says so.
    - Why: the review of revision 1; nothing a person typed disappears without their decision. The cost: one more
      state in the editor, and one more question at its exits.

### Owner, 4c-2 mockups and plan shape (2026-10-09, in chat)

Asked with the 4c-2 mockups (the Design canvas "4c-2 Data Mockups", version 10, after a pasted review's six
corrections), the owner:
- signed off D8 for 4c-2: the plan may be written from the mockups;
- adopted the pasted review's ten recommendations as rulings: one text and pill editor as a text field's fixed mode;
  conditional pills stay dashed, with a default; "Add a default" is a visible button; the untyped trigger keeps its
  fallback (type a path), a declared input schema is honoured, and no trigger setup comes before 4c-3; samples show
  only in a pill's details; alternatives are merged conservatively; the builder replaces "Fixed" for conditions; one
  level of groups; per-comparison guards, with "is missing" and "is there" defined; keys a reference can't name are
  shown disabled;
- ruled, when asked again on corrected facts, that the validator merges alternatives (`anyOf`, `oneOf`) only.
  References and templates already treat an index as possibly missing; formulas keep engine-core spec §4.3, an element
  read by index being "data, read freely";
- ruled that 4c-2 is two plans in sequence: 4c-2a, the backend (the merge, B6, liveness, B7 with slot 0045), reviewed,
  built and merged first; then 4c-2b, the UI.

Two findings from the research went to the owner as separate tasks, outside 4c-2: a text-only template or a CEL
string constant at a sensitive position published clean where a literal is refused (#76); and a switch case's declassify
entry followed its index, not its case, when cases were moved or removed (#77). Both are merged.

### 4c-2a plan accepted (2026-10-09, in chat)

`docs/superpowers/plans/2026-10-09-editor-ui-4c2a-data-backend.md`. Reviews pasted in chat held revision 1 (06962fd2)
for eight defects in its code, revision 2 (80de9638) for three, revision 3 (2f2da5d3) for one and revision 4
(ff95fbee) for one; revision 5 (3d5c8b40) answered them, each with a test that fails on the previous revision's code,
and a pasted review signed it off on the review side (no rulings accepted by it). The owner, asked in chat, then
accepted revision 5 and adopted its rulings 1–11, which join this ledger as 114–124, copied as ruled; chose inline
execution with the milestone pauses (the engine reviewed after Milestone 1, a fresh review at the end); approved the
worktree's own locked environment (`uv sync --frozen`); and chose the branch `feat/editor-4c2a` from origin/main
(532ab6c6), the plan's docs branch merged in. Push and a PR stay the owner's decisions.

114. **Accepted. Alternatives are read together, conservatively** (`navigate`, Task 2; engine-core spec §4.3 amended).
     - `anyOf` and `oneOf` are unfolded, nested ones too. Each way a value may match is a conjunction: what surrounds
       a union stays beside each branch, never overwritten by it, and every member of an `allOf` applies (so `allOf`
       is now read, as a conjunction, by `navigate` and `json_types` alike).
     - The bounds: 8 levels of nesting; 64 ways at a position, duplicates merged first; and one budget of 4,096
       unfolded schemas for the whole read, every position counted, `declared_optional` and `declared_nullable`
       included. Past any of them, the value is "any value".
     - Reading a field or an index follows every alternative:
       - the value's type is what any alternative allows there;
       - it may be missing when an alternative may lack it (it doesn't require it, a closed one doesn't declare it, its
         type isn't an object or a list, its list may be shorter, or it's null);
       - an alternative that says nothing about it (open, undeclared) makes it "any value";
       - a field no alternative can hold is `ref.unknown_field`, as for one schema.
     - A union with `null` makes the value nullable whatever its number of alternatives (today only one non-null
       alternative counts). A position that is only `null` stays a plain null value, as today.
     - `declared_optional` and `declared_nullable` read through a union only when every alternative declares the
       field. Otherwise the data is open there, and nothing is reported (spec §4.3: undeclared data needs no guard).
     - Within a way, a field declared by one of its schemas has that schema (all of them, when several declare it); the
       way is closed to an undeclared field when one of them is closed.
     - Types meet as JSON Schema says: an integer is a number, so `number` and `integer` meet in `integer`.
     - Object keywords speak only of objects, `items` only of lists. A way that can't be an object holds no field. A
       field is sure to be there only when its way is sure to be an object and requires it: a value that may be a
       string (`type: ["object", "string"]`, or a string beside `properties`) may lack it. None of the shipped plugins'
       5,719 object schemas is affected: the 30 that declare `properties` without a `type` require nothing.
     - A formula owes the same guards whatever the spelling (a type list, `anyOf`, `oneOf`, `allOf` around either):
       `has()` for a field one way may lack, and `type(x) == map` before reading below a value that may not be an
       object, a `has()` test included (the review of revision 3). This is a new obligation, a `cel.conditional_ref`
       like the null one; a draft whose formula reads below such a value unguarded meets it on its next validation.
     - Why: the owner's ruling, and the data tree must type a device's `name` as text, as validation does. The cost:
       an existing draft may meet new diagnostics when it's next validated: a reference now typed that mismatches its
       field (`ref.type_mismatch`), a formula field declared optional in every alternative (`cel.conditional_ref`), or
       `has()` on a list now typed (`cel.has_on_typed_path`). Reading `allOf` types two Mist schemas
       (`site_setting_switch`, in `mist.site_settings.get` and `.update`) that were "any value". Published versions are
       untouched.
115. **Accepted. "May be missing" and "may be null" are told apart.** `Resolved` gains `missing` and `nullable`, filled by
     `navigate` and by the resolver (a step that may not run); the scope adds a variable not yet set. `conditional`
     stays their union, so every existing check is unchanged. Why: a default replaces both, but the tree and the builder say them
     differently ("may be null" for Mist's `total`). The cost: none.
116. **Accepted. A step is conditional when it may not run**:
     - its liveness in its region isn't "always", or it can't be analysed;
     - or the loop whose body holds it is conditional.
     Validate's answer lists them (`conditional_steps`, node ids, sorted). A version's detail doesn't: the badge is the
     draft's. Why: ruling 70. The cost: none.
117. **Accepted. The scope of a field** (B6): `GET /api/v1/t/{tenant_id}/workflows/{workflow_id}/draft/scope`.
     - It takes `node`, `field` (a JSON pointer in that node's config), and at most one of:
       - nothing: the top of each root (each of `trigger`, `steps.<key>.output|error`, `vars.<name>`, `item`, `index`,
         `loops.<key>.item|index`, `run.id|started_at|now` that the field can read);
       - `under`: the children of one path (at most 500, then `more`); the top answer includes each root's children too;
       - `at`: one path, or the problem that stops the field reading it (the validator's own diagnostic);
       - `find`: fields whose name contains the text, at most 6 levels below each root, 2,000 positions visited and
         50 found.
     - It reads the saved draft, like validate, and answers its `draft_revision`, so an editor drops an old answer
       (D17). It needs `workflow.view`: a viewer's read-only drawer shows a pill's details too.
     - When the saved draft can't be analysed, or doesn't hold the step, it answers `state: "unavailable"` and a
       reason, never an error status.
     - Why: B6; scope is per field, since a filter's predicate and a loop's `collect` see their own `item`. The cost:
       each request runs the validator's analysis once (as validate does).
118. **Accepted. An entry** says:
     - `path`, `parent`, `name` (`timezone`, `[0]`);
     - `root`, and `step` (the producing step's id);
     - `types` (the JSON types it may have; empty: any value) and `format`;
     - `missing` and `nullable`;
     - `sensitive`: what a reference to it holds (engine 2b spec §4.1);
     - `nameable`: false for a key a reference can't name (a dash, a space), shown disabled;
     - `children`;
     - `formula`: null when CEL can't select one of its fields (`in`, `true`, `false`, `null`) or when `problem` is set;
       otherwise its `guards`, whether a formula reading it reads sensitive data, and `null_test`;
     - `problem`: what validation reports for reading it here, as validation says it: a sensitive variable that has no
       default and that no step sure to run sets (`vars.unassigned`). Such an entry is shown, and refused.
     Why: the 4c-2 mockups and their ten rulings. The cost: none.
119. **Accepted. Guards come from the server, as data** (`present`, `not_null`, `is_map`, `is_list`, `min_size`).
     - For each step of the path:
       - a step that may not run: `has(steps.<key>.output)`;
       - a parent that may be null: `parent != null`;
       - a field read from what isn't surely an object: `type(parent) == map`;
       - an index into what isn't surely a list: `type(parent) == list`, then `size(parent) > i`;
       - a field that may be absent: `has(path)`.
     - Never `has()` on a list always there (`cel.has_on_typed_path`).
     - Tests prove a formula made of the guards and the read publishes with no guard diagnostic, and is never an error
       at run time.
     - "is there" is the guards, and `path != null` when the scope's `null_test` says so: the value may be null, is
       untyped, or is only null (a `type: "null"` field is never "there"). "is missing" is its negation. A list always
       there can't be compared with null in CEL (`list != null` doesn't compile), and needs no such test. 4c-2b's
       builder renders them from `guards` and `null_test`, never re-deriving the rules.
     - Why: the owner's ruling for per-comparison guards with defined "is missing" and "is there"; D18 (the server
       alone checks): the same rules make and check them. The cost: the builder can't guard data the scope doesn't
       list.
120. **Accepted. A formula's sensitivity is reported per entry**, for the formula the guards make: the read and every guard.
     - A formula reading `X[0].f` reads the list `X` whole: CEL's chains stop at an index.
     - A guard reads its operand whole: `trigger.owner != null` or `type(trigger.who) == map` reads that object, and
       an object open to undeclared fields counts as sensitive (engine 2b spec §4.1). A `has()` guard reads only the
       field it tests, and `has(steps.k.output)` reads only whether the step ran (the run's shape), never its output.
     - So `formula.sensitive` can differ from `sensitive`. A test holds it equal to what validation finds.
     - Why: a condition on `results[0].name` needs declassifying even though the pill isn't sensitive; the tree says so
       before the person builds it. The cost: none.
121. **Accepted. Each attempt records the connections it opens** (B7, slot 0045).
     - Table `run_step_connections`, keyed `(run_id, step_id, iteration_key, attempt, connection_id, revision)`:
       every revision an attempt opened is kept, so a connection changed between two opens in one attempt shows both.
     - It holds the connection's type, name and revision, and its non-secret config as it was (`context`, at most
       4 KiB as canonical JSON, otherwise `{}`), with the time.
     - The worker writes it when an attempt opens the connection, before the node uses it, inside the activity: no
       ABI change. Opening it twice in one attempt records it once.
     - A write the database doesn't answer fails the attempt as nothing sent (retryable), like the connection's own
       load. Any other failure is a bug, raised. Opening the same revision again records nothing more.
     - A simulated attempt opens no connection, so records nothing. Neither do flow steps.
     - Why: B7: a connection keeps its id while its config changes. The cost: one insert per opened connection per
       attempt.
122. **Accepted. Which sample** (B7):
     - Candidates: the newest 200 runs of this workflow that have ended (an end time recorded, not running), of any
       kind (a run, a sub-flow's run, a failure handler's run), newest ended first. A run that hasn't ended never takes
       a place in the window: the filter comes before the limit.
     - Each candidate must be within retention through its root.
     - Within each candidate, the asked iteration, else the first by number (`l:2` before `l:10`), and its highest
       attempt. Among the candidates, the answer is the one whose row ended last: B7's "newest succeeded row", within
       the window.
     - The answer says how many runs it searched (`searched_runs`, at most `search_limit`, 200). "No sample" then
       means none in those runs, never "this step has never run": 4c-2b's copy says which. The count and the choice come
       from one statement, so one snapshot: a run ending meanwhile can't make them disagree.
     - Migration 0045 adds the index `runs_workflow_ended (workflow_id, ended_at DESC, id DESC) WHERE ended_at IS NOT
       NULL` for it.
     - Why: B7's selection; sub-flows run this workflow's steps too. The cost: a sample older than the newest 200 ended
       runs isn't found, and the answer says so.
123. **Accepted. A sample's answer:**
     - `run_id`, the run's kind and mode, its version id and number, and the search's `searched_runs` and
       `search_limit` (ruling 9);
     - the iteration and attempt, and `captured_at` (the row's end);
     - the node's `type@version` in that version, with `same_type` and `same_config` against the saved draft;
     - `output`: the stored preview, markers as they are;
     - `connections`, with one of four states:
       - `recorded`, with each connection's state: `unchanged`, `changed` (another revision now) or `deleted`;
       - `none`: the step names no connection;
       - `simulated`: none used;
       - `unknown`: the step names one, but no record exists.
       A step "names" a connection only in a top-level field its type marks for one (`x-dewpoint-connection`, read
       from the node type's manifest), naming one of its version's connections: the worker's own rule
       (`DbConnections.named_by`). Text that happens to hold a connection's id names nothing.
     - `stale`: true when the type, the config or a connection differs.
     - A renamed connection is unchanged: a rename doesn't change a revision. The current name shows, or the
       recorded one when the connection is gone.
     - A step the saved draft doesn't hold, or with no sample, answers `sample: null`.
     - It needs `run.view`.
     - Why: B7, D20. The cost: none.
124. **Accepted. The web client's types are regenerated, and its screens untouched.** `schema.d.ts` gains the new routes and
     `conditional_steps`. A test fixture the type checker names gets `conditional_steps: []`. Why: B1's drift check.
     The cost: none.

### 4c-2a, milestone 1 (2026-10-10)

Tasks 1–5 at 69ccd931, on `feat/editor-4c2a` (from origin/main 532ab6c6, the plan merged in b1a67b32): the merge of
alternatives (a7c7c3a6), which steps may not run (7bbabcbb), what a field can read (99e17147), the guards' guarantees
(69ccd931). Checks, as run in the worktree's locked environment:
- the engine's tests: 1,257 passed, 1 skipped (the golden replays among them; ENGINE_ABI 6);
- the whole backend suite, with the owner's OK: 4,692 passed (`-n auto`, CI's ignore list), then CI's CEL gate tests
  415 passed, 8 skipped; no failure anywhere, so no existing test graph met a new diagnostic (about 16 minutes: a first
  attempt ran only the gate files, because zsh doesn't split an unquoted variable; it was rerun under bash);
- ruff, mypy (strict) and the import contracts: clean.

M58. **The branch starts from origin/main 532ab6c6, not the plan's 93a0dd61**: main gained #76 (validate.py's sensitive
    text and constant formulas), #77 and #80 (frontend). Only validate.py overlapped, in another region; every step
    was applied to the current code. Cost if wrong: none seen; the suite is green.
M59. **Task 1 recorded the owner's acceptance and copied rulings 114–124**, where the plan's text said "proposed": the
    owner accepted before Task 1 ran, as with 96–113.

### Owner, milestone 1 reviewed (2026-10-10, pasted)

A pasted review held milestone 1 at dc92b173 for two P2 defects in `scope.py`, both in the accepted plan's own code:
known formats disappeared through nullable type lists, nullable `anyOf` and `allOf`; and a search could say `more:
false` with work omitted at a bound (children past 500, matches past 50, fields below its depth). It found no new
blocker in the validator or guard changes, and authorized no milestone-2 work or push.

### 4c-2a, after the milestone 1 review (2026-10-10)

M60. **A format is kept conservatively**: within a way the one its schemas declare, across ways only one they all
    share (`_format`); two formats, or a way without one, leave none. Test: "keeps a format through null alternatives
    and conjunctions" (failed first on the nullable list, the nullable `anyOf` and the `allOf`).
M61. **A search tracks what it left unsearched at every bound**, without raising any limit: `more` is true when it
    stopped at FIND_FOUND or FIND_VISITS with work left, skipped children past MAX_CHILDREN, or left fields below
    FIND_DEPTH. Tests: "a search says when children past the limit went unsearched", "… when it stopped at its count",
    "… when it stopped at its depth" (each failed first), and "a complete search says so".
    Engine tests 1,262 passed, 1 skipped; ruff, mypy, import contracts clean. The whole backend suite wasn't rerun:
    nothing outside the engine's tests uses `scope.py` yet.

### Review sign-off of milestone 1 at 5a0ce3da (2026-10-10, pasted)

A pasted review signed off milestone 1 on the review side at 5a0ce3da (ledger 21dab57c): both P2 findings closed, no
remaining blockers. Its 55 focused checks passed, the four corrective tests fail on the old scope code while the
complete-search baseline passes; it didn't rerun the whole engine or backend suites. It authorizes neither milestone 2
nor a push: those stay the owner's.

### 4c-2a, milestone 2 (2026-10-10)

The owner started milestone 2 in chat (2026-10-10), with milestone 3 to follow and a pause at the final checkpoint.
Tasks 6–7 are at 5329bd58: validate answers `conditional_steps` (fb987fcb), and `GET …/draft/scope` answers what a
field of the saved draft can read (5329bd58, `workflow.view`, one question at a time). API tests: 95 passed
(test_draft_data, test_openapi, test_workflows, test_workflow_ops). The regenerated client schema passes `check:api`;
typecheck, lint and the frontend's 731 tests pass with no fixture change for the route. Ruff, mypy and the 11 import
contracts are clean. No plan deviation.

### 4c-2a, milestone 3 and the final checkpoint (2026-10-10)

Milestone 3 followed milestone 2 without a pause, as the owner said. Tasks 8–10:
- 46d543f3: migration 0045, `run_step_connections` (forced row-level security, the worker inserts, the API reads, the
  fence trigger, gone with its run) and `runs_workflow_ended`, chained after 0047. The database's guards (chain,
  fence, tenancy, retention, erasure, model/schema): 142 passed.
- 5f2d8899: each step attempt records each connection, and each revision, it opens, before the node can use it; an
  outage while recording is `NotSent`. Worker tests and golden replays: 527 passed. The simulated-attempt test passed
  before the record existed: it guards a negative (a simulation raises before any record).
- c8b6d35f: `core/runs/samples.py` and `GET …/draft/samples` (`run.view`, within retention). API and core tests: 132
  passed.

Every check at c8b6d35f, as run (the owner OK'd the whole suite in chat):
- the backend suite with `-n auto` and CI's ignore list: 4,732 passed (8.5 min); the CEL gate tests serially: 415
  passed, 8 skipped;
- ruff format and check, mypy (284 files), the 11 import contracts: clean; the backend's OpenAPI matches
  `frontend/src/api/openapi.json`;
- the frontend's `check:api`, `lint`, `typecheck`, 731 tests and `build`: pass (no screen changed, so no browser gate);
- local CodeQL: no finding in Python or JavaScript/TypeScript.

The final review (a fresh reviewer, most capable model, 532ab6c6..c8b6d35f, the plan's Review Focus first) found no
critical or important issue and seven minor ones; its verdict: ready to merge.

M62. **A step left without a config has the same config as an empty one.** The review's first minor, re-graded
    important by effect: the draft is stored as written, so a step may leave `config` out, while a version always writes
    it (`{}`, `GraphNode.config`); the sample marked such a step stale for good. Only a missing key defaults to `{}`.
    Test: "a step written without a config has the same config as an empty one" (failed first). Fixed in 782e6401; the
    API, `workflow_ops` and core run tests: 451 passed (the whole suite wasn't rerun: one function, one route).

Deferred (minor, the owner's call):
- a non-outage failure of the connection record on an ambiguous node ends the step "outcome unknown" though nothing
  was sent (only the erasure fence or a bug can cause it);
- the scope's `under` with an unparsable or unresolvable path answers "ok" with no entries, where `at` answers the
  problem (ruling 117 as written);
- a sample says its step names no connection when the node type is no longer installed or the version predates
  `connection_ids`, where "unknown" is truer;
- each `attempt.connection()` call writes a record (the key keeps one row); a per-attempt memory would skip repeats;
- no test of an outage, or of another error, while recording a connection.

What the review set aside, ruled to stand: `runs_workflow_ended` without CONCURRENTLY (project practice for `runs`
indexes); a deleted connection's non-secret config kept with its runs (ruling 121); `same_config` ignores a step's
options (ruling 123); no `conditional_steps` in a version's detail (ruling 116); the existing "unknown outcome" rule for
ambiguous nodes; `analyze()` per scope request (ruling 117); no sample past the newest 200 ended runs, said by
`searched_runs` (ruling 122); the engine's own redaction in previews (engine-core §8).

Paused at the final checkpoint. Nothing is pushed: a push and a PR wait for the owner's word.

### 4c-2a, after the review of 6cc2a4f3 (2026-10-10)

A pasted review held 6cc2a4f3 for two P2 defects in sample matching, both reproduced through the public API; it found
M62 correct and the recording-outage handling as claimed.

M63. **A sample compares a step's config as JSON, as the graph hash does**: `true` and `1`, `false` and `0`, were
    equal in Python, so a value changed between them kept a sample fresh. M62's default stays (a missing config is
    `{}`). Test: "marks a sample stale when a value changes its JSON type" (`true`→`1`, `false`→`0`, nested; each
    failed first).
M64. **Ids are read as UUIDs, as the engine and the worker read them.** A draft's step id written in capitals is the same
    step (its graph hash doesn't change), so its sample stays; a connection field's value written in capitals names the
    connection, as `DbConnections.named_by` already held, so a run from before records says "unknown", not "none".
    Tests: "finds a sample whatever the case of the step's id" (the review's case) and "names a connection whatever
    the case of its id" (the same cause, found while fixing it); both failed first. A version's own graph is written
    by `graph_json`, its ids already in one spelling, so reading the step in it (here and in the worker) stays as is.
    Fixed in 8ec43351; the API, `workflow_ops` and core run tests: 456 passed (the whole suite wasn't rerun: two
    functions of one route and the sample query); the OpenAPI is unchanged.

Paused at the final checkpoint again. Nothing is pushed: a push and a PR wait for the owner's word.

### Review sign-off of the final checkpoint at 96cca1a6 (2026-10-10, pasted)

A pasted review signed off the final checkpoint on the review side at 96cca1a6 (fix 8ec43351): both P2 findings
closed, no new blocker. Its 56 focused checks passed, including the uppercase connection-id case, which agrees with the
worker and answers "unknown" when records are absent; the five new regression cases fail on the held head's source
and M62's baseline still passes. It didn't rerun the whole suite or CodeQL. The five deferred minors stay the owner's
decisions. It authorizes no push, PR or issue: those stay the owner's.
