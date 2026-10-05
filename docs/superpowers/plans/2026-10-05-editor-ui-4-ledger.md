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

None yet.
