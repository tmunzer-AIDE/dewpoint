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
