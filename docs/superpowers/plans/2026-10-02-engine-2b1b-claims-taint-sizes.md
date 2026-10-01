# Engine 2b-1b: Claims, Taint and Sizes — Implementation Plan (DRAFT OUTLINE, for the owner's check)

> **Status:** an outline of milestones and tasks, written before any task is prototyped, so the order and scope can
> be checked early. Each task gets its full steps, tests and code (a prototype's tested diffs, as in 2b-1a) once the
> outline is agreed.

**Goal:** Keep sensitive and large values out of Temporal history: they become encrypted claims in Postgres, and
history holds only bounded handles to them. Publish knows which paths are tainted, and only listed sites may turn
tainted input into plain decisions. Every continued input fits its bound by construction (§5.3, the gate passed
2026-10-01). `ENGINE_ABI` becomes 6.

**Spec:** `docs/superpowers/specs/2026-09-29-engine-2b-design.md`, revision 5 (this branch is cut from
`docs/engine-2b1b-gonogo`, ad4be07). Sections: §1 (scope), §2.7 (`claim_check`), §3 (claims), §4 (taint), §5
(sizes and snapshots; §5.3 approved for implementation), §6.1 (the exact id grammar), §6.6 (ABI 6), §9 (codes),
§11.2–11.3 (the prototype's evidence), §12 (testing), §13 (older specs), §14 (tables and roles), §15 (values).

**Shape:** one plan, one branch (`feat/engine-2b1b`, cut from `main` once this plan lands), one merge, `ENGINE_ABI`
6 (the owner's choice, 2026-10-01). Four milestones, each ending at the owner's checkpoint.

---

## Milestones and order

The order is chosen so that **handles never enter a run before everything that reads them exists**. Claims are
built and tested in isolation first; publish learns taint next; only then does run-time protection put handles into
runs, with routing, declassification and grants in the same milestone; sizes come last, reusing all of it.

1. **Claims infrastructure** (§3.1–3.5, §3.7's storage): tables, encryption, handles, the store, the splitter, the
   secret index's matcher. Nothing in a run uses them yet.
2. **Taint at publish** (§3.8, §4.1, §4.3, §4.5): the analysis, `declassify`, its permission and audit, the
   refusals. Versions record the result; runs don't use it yet.
3. **Run-time protection** (§3.2–3.7, §4.2–4.4, §6.1, ABI 6): admission claims the trigger; every read of a handle
   goes to an activity; tainted expressions route by handle; declassified sites return plain decisions; the tainted
   filter; grants for sub-flows and handlers; the boundary wrapper and the secret index; learned secrets leave
   history. `ENGINE_ABI` 6 and the abi6 goldens.
4. **Sizes and snapshots** (§5): size claims at 64 KiB, spilling before failing, and §5.3: the live budget and its
   containers, segments, the cap computed at publish, the open-iteration cap with its reservation, captures, the
   shared budget request, the at-continue term, `snapshot_format` 2, and a workflow task's CPU.
5. **Proofs and docs:** canary secrets end to end, the RLS matrix, operations guides, the older specs (§13).

Checkpoints for the owner: after milestone 2 (the static half), after 3, after 4; a whole-branch review after 5.

---

## Tasks

### Milestone 1 — Claims infrastructure

1. **Claim tables.** Migration 0014: `run_inputs`, `step_outputs`, `claim_grants`, `run_secret_index`, each with
   ENABLE + FORCE RLS, a `_scope` policy, and least-privilege grants (worker: claims and grants; dispatch: inserts
   into `run_inputs` and the index at admission). Columns per §3.1: tenant, owner run, root run id, producer (step,
   iteration, attempt), sensitive-pointer map, content hash, ciphertext. ORM models. RLS tests for the new tables (no
   context, another tenant, cross-tenant writes, missing grants).
2. **Claim encryption.** A cipher over a `KeySource` (the codec's cached, read-only active key), with the keyring's
   blob layout and AAD `dewpoint|<tenant>|claim|<claim id>`, so admission (dispatch role) and workers encrypt without
   `Keyring.encrypt`'s per-tenant lock. Tests: a blob moved to another id or tenant fails; rotation decrypts old
   versions.
3. **Handles.** `ClaimRef(id, pointer)` under a reserved marker key; JSON-pointer grammar; `POINTER_MAX` 256,
   `HANDLE_MAX` (computed by a test as the marker, a claim id and the longest pointer); `extend(ref, path)` that
   reports when a pointer would pass `POINTER_MAX`; `contains_marker(value)` for forged handles. Property tests.
4. **The claim store.** `core/claims/service.py`: write (idempotent; a row that exists must match the content hash, or
   the write fails), read with §3.3's checks (tenant from the workflow id, owner or grant, the pointer exists, the
   result's taint from the sensitive-pointer map, nested claims included), grant (only what the granter owns or
   holds). `claim_unavailable` for a claim gone or refused. Store methods on `RunStore`, `DbRunStore`, `MemoryStore`.
5. **The splitter (§3.5).** A pure function `split(value, schema) -> Split(envelope, claims)`: sensitive first (every
   `x-sensitive` position, and every position the schema doesn't declare, unions with any sensitive branch), then size
   (> 64 KiB, after its sensitive descendants), then reappearing text (a ≥ 4-character string from the value's own
   sensitive fields), then the envelope (largest subtrees until within `TRIGGER_INLINE`, ties by pointer, root last).
   The schema walker moves from `engine/runtime/projection.py` into a shared engine module, so publish can use it.
   Property tests: nothing plain at a sensitive or undeclared position; nesting follows the claiming order.
6. **The secret index's matcher and storage (§3.7).** One encrypted row per root run, with a version; a matcher built
   once per version and cached with it; the bounds (100,000 strings or 8 MiB) → `secret_index_limit`; an unreadable
   index → retried, then `secret_index_unavailable`. **Needs a dependency** (open question 2).

### Milestone 2 — Taint at publish

7. **Sensitive literals refused (§3.8).** Publish refuses a literal at a sensitive config position, a sensitive
   `default` in `input_schema` or `vars_schema`; republishing such a version fails the same way. The one existing test
   that uses a literal sensitive token moves to a trigger input.
8. **The taint analysis (§4.1).** At `_Validator._resolve`, every path read is marked tainted or not: sources
   (sensitive positions of `input_schema`, manifests' output schemas, `vars_schema`; undeclared positions; dynamic
   addressing and bare-root reads); propagation per path (refs, templates, CEL, transforms; variables by fixpoint;
   `item`/`loops.<k>.item` field by field; `index` and `run.*` never; collected `items` from `collect`; `count`
   plain; whole-list reads; a sub-flow's outputs from its pinned version's output-taint map). The version stores the
   per-site taint (`ExpressionRecord.tainted`, a site map for refs and templates) and a per-output taint map.
9. **Declassify (§4.3).** `graph.settings.declassify` (node, field); publish refuses an unlisted tainted decision and a
   stale entry; the `trigger.rows` exception; `workflow.declassify` (admins and owners) required when the list is
   non-empty; the publish audit entry lists every site and what it reveals (no `code`-like keys).
10. **Refused at publish (§4.5), and the editor's explanations.** Timers from tainted data, a tainted `flow.fail`
    message, a tainted value into a child's non-sensitive input field. `validate_draft` returns each expression's
    taint reason and each declassified site.

### Milestone 3 — Run-time protection (`ENGINE_ABI` 6)

11. **ABI 6 and the exact id grammar (§6.1).** The batch suffix parsed part by part; `ENGINE_ABI` 6; the abi6
    goldens (recorded here, re-recorded as later tasks change commands, all within the branch).
12. **Admission claims the trigger (§3.5).** `start_run` validates the trigger against `input_schema` (absent on
    `main`), splits it, writes `run_inputs` owned by the run, and seeds the secret index; a trigger holding the marker
    is refused.
13. **Reading a handle (§3.2–3.3, §4.2's runtime rule).** `resolve.read` stops at a handle and extends its pointer; a
    pointer past `POINTER_MAX` derives a claim through an activity (deterministic id); a binding that is a handle is
    never evaluated in the workflow: CEL and templates over handles go to `cel.evaluate` by handle, and the worker
    resolves them with §3.3's checks; a result that resolved a tainted claim comes back claimed.
14. **The activity boundary (§3.6).** A plugin step's input handles are resolved in its activity; its output is split
    by its output schema; anything plain at a sensitive or undeclared position is a sanitized, non-retryable error;
    a forged marker in output is refused; the workflow's tripwire fails the run `internal_error`.
15. **Routing by taint and declassified decisions (§4.2–4.3).** A tainted expression or template always goes to
    `cel.evaluate` by handle and returns a claimed result; at a listed site (`flow.if`, `flow.switch`, a loop's
    `items`, a filter) it returns the plain decision only.
16. **Loops over handles.** A loop's items may be a handle: its count comes from an activity (declassified, or plain
    for a size-only list); each item is `ClaimRef(X, "/n")`, or a row with handles in its sensitive cells; batches
    carry item handles.
17. **The tainted filter (§4.4).** One activity resolves the list, evaluates each item in the evaluator, and stores the
    kept items as a claim (tainted when the items or predicate are); the workflow gets the handle and the two counts;
    the budget is charged the input count.
18. **Sub-flows and failure handlers (§3.4).** A child's input is split like a trigger; the parent grants the handles
    it passes, in an activity before the start; a child grants its outputs to its parent before its result returns;
    the parent reads them through the grant.
19. **The secret index at every boundary; learned secrets leave history (§3.7).** Each tainted claim extends the
    index; an untainted part of an output that contains an indexed string is claimed with taint; every error message
    leaving an activity is masked; projection masking moves into the `project` activity; `secrets` leave `Parent`,
    `RunResult`, `BatchResult` and the snapshot, and `SECRETS_BYTES` retires.
20. **`claim_check` (§2.7).** The capability, proven by the self-check (the claim store answers), with its tri-state.

### Milestone 4 — Sizes and snapshots (§5)

21. **Size claims at 64 KiB (§5.1, §5.4).** A plugin output or an evaluator result larger than 64 KiB is claimed where
    it's produced (instead of `payload_too_large`); activity inputs carry the inline threshold (above the live
    budget, outputs over 1 KiB are claimed).
22. **Spilling before failing (§5.2).** A `spill` activity writes the largest values of an outgoing command into size
    claims, in chunks under the limit, idempotent and hash-checked; step inputs, sub-flow and handler starts and batch
    inputs spill before they fail.
23. **`snapshot_format` 2.** One code per node and edge in region order, indexes for ids, no stored queue; restoring
    rebuilds the queues.
24. **The live-state counter.** Every value counted at its encoded size as it enters and leaves; recounted on restore;
    a test asserts the two agree at every snapshot.
25. **Containers and their claims.** Past `LIVE_BUDGET`, the largest spillable container is claimed (ties by scheduling
    order; values on their way still count); collections compact into segments (`SEGMENT_BYTES`) with a segment list
    claimed as an index; a loop's inline items become segments and a cursor; scopes' result sets and items; the
    variables and their versions; a batch's frozen results. Merges are authoritative.
26. **The cap and the maxima at publish.** `OPEN_SCOPES_CAP_v` and `D_v` computed and pinned in the version; tests
    build each maximum (`ID_MAX`, `HANDLE_MAX`, `ENVELOPE_MAX`, `TRIGGER_MAX`, `LOOP_MAX`, `UNIT_MAX`,
    `ITER_SCOPE_MAX_v`, `ROOT_SCOPE_MAX_v`); `LIVE_BUDGET` is above the all-claimed minimum for every cap.
27. **The open-iteration cap and its reservation.** At most `OPEN_SCOPES_CAP_v` iteration scopes, plus one reserved per
    nesting level on the progress path; a loop step in an iteration starts only when its loop can open one.
28. **Captures.** A loop step queued in an iteration reads the variables as they were when it became ready; versions
    numbered from 0; older versions kept as differences while a queued step names them.
29. **The shared budget request and the at-continue term.** Queued loop steps share one request; a refusal starts them
    to fail at their first iteration; an execution continues only with no waiting need, no child's grant and its live
    state within budget (a drain still starts its claims); the snapshot refuses otherwise.
30. **Each value travels once.** A continued `LoopBatch` drops `items`, `outer` and `variables`.
31. **A workflow task's CPU.** Snapshot and restore in steps charged in structural units; step and take charges; a
    per-worker program cache. Regressions count units, not time.

### Milestone 5 — Proofs and docs

32. **Canary secrets end to end (§12).** Runs seeded with known secrets, through triggers, plugin outputs, sub-flows,
    batches, filters and spills: their decoded histories, projections and logs hold none.
33. **Docs.** The operations guides (ABI 6 rollout, `claim_check`, the new codes); engine-core and the architecture spec
    (§13); measured values back into spec §15.

---

## The owner's decisions (2026-10-02)

1. **The order:** claims infrastructure → taint at publish → run-time protection → sizes, as above.
2. **The secret index's matcher:** `ahocorasick-rs` (Rust, MIT/Apache-2.0), a new runtime dependency (Task 6).
3. **How the plan gives code:** prototype first, as 2b-1a: every task is built and tested on a branch from `main`, the
   plan holds the tested diffs, and execution cherry-picks them.
