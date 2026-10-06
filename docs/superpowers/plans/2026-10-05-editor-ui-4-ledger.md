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
