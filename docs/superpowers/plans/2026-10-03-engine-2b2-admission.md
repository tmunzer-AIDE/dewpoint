# Engine 2b-2: Admission — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Start runs only through admission and the dispatcher. A request is admitted once, idempotently, in its
caller's transaction, with its input claimed and its trigger envelope stored beside its claims; `dewpoint dispatcher`
starts it on Temporal within its tenant's slots, and its reconciler settles what a start leaves uncertain. The run API
starts, cancels, re-runs and lists runs; the dev CLI goes through admission; Compose runs the dispatcher.

**Architecture:**
- **The queue and admission (milestone 1).** `run_requests` is the queue and the intent in one row, with
  `tenant_run_limits`, `run_slots` and the current-build record; the trigger envelope is a `run_inputs` row of the role
  `envelope`, never served as a claim. Claims keep no digest of their value (#28). The idempotency digest is an HMAC
  with a key derived from the tenant's data key. `admit_request` checks the key first, then the mutable conditions,
  and writes claims, envelope and request in one savepoint. Retirement counts requests that haven't started, and a
  forced one cancels the queued ones.
- **The dispatcher (milestone 2).** `dewpoint dispatcher` records the current build and checks the workers; the
  starting transaction takes the gate's and the tenant's shared locks, checks every critical condition and the
  closure, reserves the slot, pre-creates the run's row and seals the start with the tenant's key; the start's answer
  is classified, then applied (a confirmed refusal backs off, then `dead`). The root's end write releases its slot.
  The owner's milestone-2 review separates a key that can't be read, a broken envelope and a bug.
- **The reconciler, cancels and the gate (milestone 3).** One leader settles uncertain starts (by `starting_at`, a
  trustworthy absence only on evidence read under the end write's locks), ended runs and leaked slots, and sends
  recorded cancels; a cancel applies at once, when a start resolves, or through Temporal; `dewpoint platform
  disable-production-runs` turns the gate off under its exclusive lock. The owner's milestone-3 reviews make the end
  write hold its row across its savepoints, and add the recovery transition for an ended run.
- **The run API, the CLI and Compose (milestone 4).** Start (with an `Idempotency-Key`), start form, cancel, re-run
  (the key checked before the old input is rebuilt; new input accepted), the runs list by `(queued_at, id)`, `dewpoint
  dev run` through admission, the dispatcher in Compose with a development override, and the operations docs.
- **Proofs (milestone 5).** Every §7.8 transition with a tenant limit of 1, the races (which found the forced
  retirement's rows and a deadlock, both fixed), the dev server's proofs, a run end to end with the keyring's real
  keys, and the Compose proof in CI.

**Tech Stack:** Python 3.12, Temporal Python SDK 1.33.0 and CLI dev server 1.9.1, PostgreSQL 16 through
testcontainers (`postgres:16-alpine`), SQLAlchemy async with asyncpg, Alembic, `cryptography` (AES-256-GCM, HKDF,
HMAC), FastAPI, typer, pytest with pytest-xdist, ruff, mypy strict, import-linter; `uv`. No new dependency.

**Spec:** `docs/superpowers/specs/2026-09-29-engine-2b-design.md`, revision 6 (approved, 2026-10-03) and the revision
7 draft that lands with this plan, on branch `docs/engine-2b2-plan`. Sections: §2.3–2.5 (the gate, at dispatch and
off), §2.7 (worker capabilities), §3.1 and §7.1 (the envelope, no claim digest), §6.1 (ids), §7 (admission,
dispatch, slots, the reconciler, the run API, the transitions, what stays open), §9 (codes), §10.1 (retention of
requests and their inputs), §12 (testing), §13 (older specs), §14 (roles, tables, functions), §15 (values). Also
engine-core (`2026-09-25-engine-core-design.md`): §4.5 (closure, admission and lifecycle locks, `engine_abi_changed`,
the defensive check) and §9, which this plan's revision 5.10 rewrites.

## Global Constraints

- Nothing starts a run but admission and the dispatcher; 2a's `start_run` stays a test helper no command exposes.
- `admit_request` runs in its caller's READ COMMITTED transaction and never commits it; the dispatcher's starting
  transaction asserts READ COMMITTED; no transaction is open across a call to Temporal.
- Cross-tenant reads are functions returning ids only (`dispatch_candidates`, `reconcile_candidates`,
  `cancel_candidates`); every other read and write is tenant-scoped under forced row-level security, with the
  tenant-scoped policies the operational roles' only (`dewpoint_api`, `dewpoint_dispatch`, `dewpoint_worker`).
- A write past a role's grants is a `SECURITY DEFINER` function with one narrow effect: `end_unstarted_run` (a
  cancelled request's row, in the caller's tenant) and `disable_production_runs` (the gate off, under its lock).
- No unkeyed hash of a value that may hold a secret: the request digest is an HMAC with a tenant-derived key; claims
  keep no digest (#28).
- Codes and messages are fixed and sanitized; logs name exception types, never messages that could quote a value;
  audit detail keys avoid `…code…`, `…secret…`, `…token…`.
- Every new table forces row-level security; migrations upgrade, downgrade and upgrade again over existing rows.
- The 2b-2 values are provisional prototype limits (§15): a start's deadline 10 s, a cycle every 1 s over up to 50
  tenants, a throttle wait 5 s, backoff 5 s doubling to 10 min and `dead` at the 10th refusal, a current-build record
  fresh for 2 min, a worker live for 90 s, the reconciler's grace and recheck 30 s, alert after 10 min, 50 a pass.
- Docker only with the approved images (`postgres:16-alpine`, ryuk, `temporalio/temporal:1.9.1`, the evaluator's
  bases for its image); the Compose proof runs in CI.
- Fix findings test-first; focused checks at each milestone, the whole suite once, at the end.

## Review Focus

The input classes and failure modes most likely to bite a person running this, which no task's tests exercise
(§7.9 keeps them open before production; the reviewer weighs each deliberately):
- **Many slow starts in one cycle.** The cycle starts candidates one after another: 50 starts at their 10-second
  deadline take about 500 seconds, while the operator expects a one-second cycle. Expect it noted, not hidden.
- **A request that fails the same way every cycle.** A bug in its starting transaction is logged and retried each
  second (the reconciler's each recheck), holding its tenant's queue head; there's no bound or alert yet.
- **History Temporal no longer has.** A started run, a held slot, or a `starting` request whose run ended is left as
  it is with an alert; there's no operator command to recover it yet.
- **A cancel Temporal keeps refusing.** It's retried every leader pass with a warning, without a bound or an alert.
- **An operator who disables production runs.** The prototype's audit entry names no actor; production's must.

## File structure

New:
- `backend/migrations/versions/0017_admission.py` … `0024_retirement_ends_rows.py`: the queue, the envelope's shape,
  #28, retirement's policies, dispatcher reports, the reconciler's columns and candidates, cancels, the gate's
  disable, and a retirement ending its rows.
- `backend/src/dewpoint/core/models/requests.py` (`RunRequest`, `TenantRunLimits`, `RunSlot`, `CurrentBuild`),
  `core/requests/digest.py` (the request digest).
- `backend/src/dewpoint/apps/admission.py` (`admit_request`, `admitted_under`, `Rerun`, the reason codes),
  `apps/cancels.py` (a user's cancel), `apps/forms.py` (a start form's fields), `apps/dev_run.py` (the dev CLI's
  admission and wait).
- `backend/src/dewpoint/apps/dispatcher/`: `main.py` (the process), `observe.py` (the current build, reports),
  `dispatch.py` (the starting transaction, the start, its outcome, the cycle), `reconcile.py` (the leader and the
  reconciler), `cancels.py` (sending cancels), `gate.py` (disabling production runs).
- `backend/src/dewpoint/apps/api/routes/run_requests.py` (start, start form, cancel, re-run).
- `deploy/compose/docker-compose.dev.yml`, `deploy/compose/ci/seed-workflow.py`; tests under
  `backend/tests/apps/dispatcher/`, `tests/core/requests/` and the files below.

Changed: `core/claims/service.py` (no digest, the envelope's reader and writer, the request-claim reader),
`core/crypto/keys.py` (the digest key, `key_unreadable`), `core/db.py` (`unavailable`), `core/plugins/lifecycle.py`
(queued references, cancels, `try_lock_shared`), `core/platform/service.py` (workers ready, the current build,
reports), `core/runs/service.py` (the pre-created row, the combined list), `core/authz/permissions.py`
(`run.cancel`), `apps/worker/store.py` (the end write's lock and slot), `apps/api/routes/runs.py`, `apps/api/main.py`,
`apps/cli/main.py`, `apps/inputs.py`, `apps/runs.py`, models, `deploy/compose/docker-compose.yml`, `.github/workflows/
ci.yml`, `docs/operations/runs.md`, `docs/operations/deployment.md`, `README.md`.

## How the steps give code

Each task's code is given as a unified diff against the tree the previous task left, in the task's record. The diffs
are a prototype's commits, and each was replayed onto that tree: its tests alone first, which failed as the record
says (or passed, for a proof of what earlier tasks built), then the rest, after which they passed. New files appear
whole, as `new file mode` diffs.

The prototype is the local branch `proto/2b2-v2`, cut from `main` at `cf93e6e`, one commit per task, built
milestone by milestone with the owner's checkpoint after each (milestones 1–4 approved as prototype checkpoints;
milestone 5 open on two conditions, below). The replay (branch `replay/2b2-v2`) reproduced every commit's tree
exactly.

Each commit was verified this way:
- its tree was reproduced exactly by the replay, its tests failing before its code and passing after;
- ruff (without its cache), mypy and import-linter passed when it was made;
- at each checkpoint, the milestone's focused tests passed (the counts the checkpoints give), and the migrations
  went from 0016 to the head, back, and up again over existing rows.

Per the owner's ruling on the outline, the whole suite runs once, at the end, not at every task.

## Executing this plan

Inline, in one session, from the prototype's commits: the diffs aren't typed again. On `feat/engine-2b2`, cut from
`main` at `cf93e6e`, for each task in order:
1. Read the task.
2. Run `git cherry-pick --no-commit <the task's commit>`, and check that nothing conflicts.
3. Commit with `git commit -C <the task's commit>`, which keeps the prototype's message.

The task's record (its tests, how they failed and passed, its diff) is historical: it isn't run again per task.

**Checkpoints:** after Task 6 (the queue and admission), Task 14 (the dispatcher), Task 21 (the reconciler, cancels
and the gate), Task 27 (the run API, the CLI and Compose) and Task 32 (proofs), run the milestone's focused tests
(group pytest's arguments by directory: pytest 9.1.1 loses a directory's conftest fixtures when the arguments revisit
it after a file of its parent), then stop for the owner's review. After Task 32, run the whole suite and the static
checks once, then a fresh reviewer reviews the whole branch.

**Milestone 5's completion conditions (the owner's):** the Compose proof's CI step (Task 32) passes in this branch's
pull request; the real-keyring proof scans both executions' whole raw histories (Task 31). Production sign-off stays
separate (§7.9).

A conflict, a failing focused test or a failing final check is a finding: stop and report it, and don't patch around
it. The diffs below remain the plan's record of every change.

## The owner's rulings (2026-10-03)

1. **Build check:** a dispatcher-maintained, timestamped current-build record for admission; missing or stale fails
   closed; dispatch checks Temporal and the worker capabilities independently.
2. **API transaction:** admission stays atomic with its caller, with tenant-scoped grants and key reads.
3. **Dispatcher reads:** cross-tenant access only to queue-selection metadata; claim reads and every write stay
   tenant-scoped.
4. **Scope:** retention's health check at dispatch in 2b-4; `tenants.status` and its refusals now, the erasure
   procedure later; CSV in 2b-3; `disable-production-runs` now; health evidence recorded now, without claiming 2b-4's
   retention or readiness gate has passed.
5. **Re-runs:** new admissions on the active version; the complete retained input is reconstructed and validated
   against the new version; old handles are never reused. Refined with the envelope (below): a re-run resolves the
   old *request*, not a run.
6. **Dev CLI:** `--wait` bounded, reporting the database's terminal outcome.
7. **ABI:** no change expected; a change to the workflow payload or the replay contract comes back for approval.
8. **Process:** prototype first; focused checks at milestones and one final suite, not a full suite at every replayed
   task.
9. **Claim hash:** issue #28, fixed before the production gate; removing `content_hash` and comparing decrypted
   plaintext on an id conflict is preferred; M1 may implement it as its own task, accounting for existing rows and
   backups in the migration.
10. **The trigger envelope** (2026-10-03): the storage approach is approved for revision 7 and the prototype, not as
    production sign-off, with two boundaries explicit: ordinary claim lookup and grants exclude envelopes, read only
    through a tenant- and request-scoped reader, with a test of an attempted handle read and of an attempted grant;
    and a re-run resolves the old request by id, authorizes reading that request's input and `run.start` on its
    workflow, then reconstructs and re-admits, with `input_not_retained` for runs from before 2b-2 and for a missing
    envelope or claim. The row shape is enforceable (one envelope per owner, a valid request-to-envelope reference, an
    explicit `pointer` rule); envelope, claims and request share one transaction; retention keeps all three while the
    request is `queued` or `starting` and deletes them together at the applicable terminal cutoff.

## Milestone 1 — The queue and admission

### Task 1: Admission's queue: run requests and their trigger envelopes, slots, limits, the current build

**Commit:** `dce19c6` (prototype `proto/2b2-v2`); the replay's tree was identical: yes.

**Create:** `backend/migrations/versions/0017_admission.py`, `backend/src/dewpoint/core/models/requests.py`, `backend/tests/core/requests/__init__.py`, `backend/tests/core/requests/test_schema.py`

**Modify:** `backend/src/dewpoint/core/models/__init__.py`, `backend/src/dewpoint/core/models/claims.py`, `backend/src/dewpoint/core/models/platform.py`, `backend/src/dewpoint/core/models/runs.py`, `backend/src/dewpoint/core/models/tenancy.py`, `backend/src/dewpoint/core/runs/service.py`, `backend/tests/core/claims/test_rls_claims.py`

**What it does:**

Migration 0017 (engine 2b spec §7, §14; revision 7):
- `run_requests`, the queue and the intent in one row, under forced row-level security: frozen version, source,
  actor, mode, idempotency key unique per tenant, the tenant-keyed digest and its key version, status and reason,
  attempts and next attempt, when it was queued and ended, a recorded cancel.
- The trigger envelope beside its claims in `run_inputs` (role `envelope`): a claim always has a pointer and the
  envelope none, one envelope per owner, and a foreign key on (envelope_id, id, 'envelope') that lets a request reach
  only an envelope it owns, which can't be deleted while the request exists; only a `refused` request has none.
- `tenant_run_limits` (the platform default, 5, in `platform_settings`), `run_slots`, `current_build`;
  `tenants.status` (`active`, `erasing`).
- `runs.queued_at`, backfilled from `started_at`, which becomes nullable with no default; the list index follows it.
- Grants: admission in the API's transaction (requests, claims, the secret index), the dispatcher's transitions,
  slots and build record, the worker's slot release; the dispatcher sees other tenants' queues only through
  `dispatch_candidates()`, which returns the tenant and request ids of each tenant's oldest due request.

Upgrade, downgrade and upgrade again checked on postgres:16-alpine with a pre-2b-2 run row.


- [ ] **Step 1: its tests alone, before its code.** Run: `uv run pytest -n 4 tests/core/claims/test_rls_claims.py tests/core/requests/test_schema.py`. Replay result (exit 1), shortened:

```
FAILED tests/core/requests/test_schema.py::test_a_claim_has_a_pointer_and_an_envelope_none[other-]
FAILED tests/core/requests/test_schema.py::test_runs_are_queued_before_they_start
FAILED tests/core/requests/test_schema.py::test_an_idempotency_key_is_one_request_per_tenant
FAILED tests/core/requests/test_schema.py::test_the_dispatcher_picks_from_every_tenant_seeing_only_what_it_needs
FAILED tests/core/requests/test_schema.py::test_the_current_build_is_written_by_the_dispatcher_and_read_by_admission
FAILED tests/core/requests/test_schema.py::test_a_tenant_is_active_until_it_is_erased
FAILED tests/core/requests/test_schema.py::test_each_role_has_exactly_its_privileges[tenant_run_limits]
FAILED tests/core/requests/test_schema.py::test_each_role_has_exactly_its_privileges[run_requests]
FAILED tests/core/requests/test_schema.py::test_a_slot_is_reserved_by_the_dispatcher_and_released_by_the_end_write
FAILED tests/core/requests/test_schema.py::test_each_role_has_exactly_its_privileges[run_slots]
FAILED tests/core/requests/test_schema.py::test_the_api_updates_only_what_a_cancel_changes
FAILED tests/core/requests/test_schema.py::test_a_request_reaches_no_envelope_of_another_tenant
FAILED tests/core/requests/test_schema.py::test_each_role_has_exactly_its_privileges[current_build]
26 failed, 14 passed in 11.98s
```

- [ ] **Step 2: its code, then the same tests.** Replay result (exit 0), shortened:

```
........................................                                 [100%]
40 passed in 14.61s
```

- [ ] **Step 3: commit.** `git cherry-pick --no-commit dce19c6 && git commit -C dce19c6`

The diff:

```diff
diff --git a/backend/migrations/versions/0017_admission.py b/backend/migrations/versions/0017_admission.py
new file mode 100644
index 0000000..c1f31a4
--- /dev/null
+++ b/backend/migrations/versions/0017_admission.py
@@ -0,0 +1,210 @@
+# SPDX-License-Identifier: Apache-2.0
+"""admission's queue: run requests and their trigger envelopes, slots, limits, the current build (engine 2b spec §7,
+§14; revision 7)"""
+
+import sqlalchemy as sa
+from alembic import op
+from sqlalchemy.dialects import postgresql as pg
+
+revision = "0017"
+down_revision = "0016"
+branch_labels = None
+depends_on = None
+
+TABLES = ("run_requests", "tenant_run_limits", "run_slots")
+# The tenant-scoped policy is the operational roles' only: a policy for every role would combine (OR) with the key
+# admin's narrow ones (0019) and let it do anything within a tenant scope its session sets (the owner's M1 checkpoint).
+OPERATIONAL = "dewpoint_api, dewpoint_dispatch, dewpoint_worker"
+SOURCES = ("manual", "rerun", "schedule", "webhook", "dev")
+STATUSES = ("queued", "starting", "started", "cancelled", "refused", "dead")
+TERMINAL = ("cancelled", "refused", "dead")
+
+
+def _in(values: tuple[str, ...]) -> str:
+    return ", ".join(f"'{v}'" for v in values)
+
+
+STATEMENTS = [
+    *(
+        statement
+        for table in TABLES
+        for statement in (
+            f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY",
+            f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY",
+            f"CREATE POLICY {table}_scope ON {table} TO {OPERATIONAL} "
+            "USING (tenant_id = app_tenant_id()) WITH CHECK (tenant_id = app_tenant_id())",
+        )
+    ),
+    # Admission runs in its caller's transaction (§7.2): the API's, the CLI's (as dispatch), 2b-3's tick and matcher.
+    # It claims the trigger, seeds the secret index, stores the envelope and freezes the request; a user cancels a
+    # queued request (§7.7).
+    "GRANT SELECT, INSERT ON run_inputs TO dewpoint_api",
+    "GRANT SELECT, INSERT, UPDATE ON run_secret_index TO dewpoint_api",
+    "GRANT SELECT, INSERT ON run_requests TO dewpoint_api",
+    "GRANT UPDATE (status, reason, ended_at, cancel_requested_at) ON run_requests TO dewpoint_api",
+    "GRANT SELECT ON tenant_run_limits, run_slots, current_build TO dewpoint_api",
+    # The dispatcher moves requests through their states, reserves slots under the tenant's limits row, pre-creates
+    # the root's run row, and records the current build; it reads every tenant's queue only through
+    # dispatch_candidates().
+    "GRANT SELECT, INSERT, UPDATE ON run_requests TO dewpoint_dispatch",
+    "GRANT SELECT, INSERT, UPDATE ON tenant_run_limits TO dewpoint_dispatch",
+    "GRANT SELECT, INSERT, DELETE ON run_slots TO dewpoint_dispatch",
+    "GRANT SELECT, INSERT, UPDATE ON current_build TO dewpoint_dispatch",
+    # The root's end write releases its slot in the same transaction (§7.5).
+    "GRANT SELECT, DELETE ON run_slots TO dewpoint_worker",
+    # The dispatcher's only view across tenants: queue-selection metadata, never a request's contents (the owner's
+    # ruling on the outline). The oldest due request of each tenant, FIFO among due ones (§7.3); the dispatcher then
+    # locks it tenant-scoped, with SKIP LOCKED. Owned by the migrations' superuser, so it reads past row-level security.
+    """
+CREATE FUNCTION dispatch_candidates(max_tenants integer)
+RETURNS TABLE (tenant_id uuid, request_id uuid)
+LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
+  SELECT tenant_id, request_id FROM (
+    SELECT DISTINCT ON (r.tenant_id) r.tenant_id, r.id AS request_id, r.queued_at
+    FROM run_requests r
+    WHERE r.status = 'queued' AND r.next_attempt_at <= now()
+    ORDER BY r.tenant_id, r.queued_at, r.id
+  ) due
+  ORDER BY due.queued_at, due.request_id
+  LIMIT max_tenants
+$$""",
+    "REVOKE ALL ON FUNCTION dispatch_candidates(integer) FROM PUBLIC",
+    "GRANT EXECUTE ON FUNCTION dispatch_candidates(integer) TO dewpoint_dispatch",
+]
+
+
+def upgrade() -> None:
+    # A tenant being erased is refused by admission and dispatch (§6.5); the erasure itself comes with its own plan.
+    op.add_column(
+        "tenants",
+        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
+    )
+    op.create_check_constraint("tenants_status", "tenants", "status IN ('active', 'erasing')")
+    # The platform's default number of concurrent root runs per tenant (§7.5); a tenant's limits row may override it.
+    op.add_column(
+        "platform_settings", sa.Column("max_concurrent_runs", sa.SmallInteger, nullable=False, server_default="5")
+    )
+    op.create_check_constraint("platform_settings_max_concurrent", "platform_settings", "max_concurrent_runs > 0")
+
+    # A request's trigger envelope sits beside its claims, never one of them (revision 7, §7.1): a claim always has the
+    # pointer it was claimed from, the envelope none; one envelope per owner; a request can reach only its own, in its
+    # own tenant.
+    op.add_column("run_inputs", sa.Column("role", sa.String(16), nullable=False, server_default="claim"))
+    op.alter_column("run_inputs", "pointer", nullable=True)
+    op.create_check_constraint(
+        "run_inputs_role",
+        "run_inputs",
+        "(role = 'claim' AND pointer IS NOT NULL) OR (role = 'envelope' AND pointer IS NULL)",
+    )
+    op.create_unique_constraint("run_inputs_envelope_ref", "run_inputs", ["id", "tenant_id", "owner_run_id", "role"])
+    op.create_index(
+        "run_inputs_one_envelope",
+        "run_inputs",
+        ["owner_run_id"],
+        unique=True,
+        postgresql_where=sa.text("role = 'envelope'"),
+    )
+
+    op.create_table(
+        "run_requests",
+        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),  # the run's id too, once it starts
+        sa.Column("tenant_id", pg.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
+        sa.Column("workflow_id", pg.UUID(as_uuid=True), sa.ForeignKey("workflows.id"), nullable=False),
+        # The frozen version: none only for a request refused before it was frozen.
+        sa.Column("workflow_version_id", pg.UUID(as_uuid=True), sa.ForeignKey("workflow_versions.id")),
+        sa.Column("source", sa.String(16), nullable=False),
+        sa.Column("actor_id", pg.UUID(as_uuid=True)),  # the user, for an interactive source
+        sa.Column("mode", sa.String(16), nullable=False),
+        sa.Column("idempotency_key", sa.String(255), nullable=False),
+        # A tenant-keyed HMAC of source, workflow, mode and input, with its key version (§7.2), never an unkeyed hash.
+        sa.Column("digest", sa.LargeBinary, nullable=False),
+        sa.Column("digest_key_version", sa.Integer, nullable=False),
+        sa.Column("status", sa.String(16), nullable=False),
+        sa.Column("reason", sa.String(64)),
+        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
+        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
+        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
+        sa.Column("ended_at", sa.DateTime(timezone=True)),  # when it became cancelled, refused or dead
+        sa.Column("cancel_requested_at", sa.DateTime(timezone=True)),
+        sa.Column("envelope_id", pg.UUID(as_uuid=True)),
+        sa.Column("envelope_role", sa.String(16), nullable=False, server_default="envelope"),
+        sa.UniqueConstraint("tenant_id", "idempotency_key", name="run_requests_idempotency"),
+        sa.ForeignKeyConstraint(  # an envelope of this tenant, owned by this request (revision 7)
+            ["envelope_id", "tenant_id", "id", "envelope_role"],
+            ["run_inputs.id", "run_inputs.tenant_id", "run_inputs.owner_run_id", "run_inputs.role"],
+            name="run_requests_envelope",
+            ondelete="RESTRICT",
+        ),
+        sa.CheckConstraint(f"source IN ({_in(SOURCES)})", name="run_requests_source"),
+        sa.CheckConstraint("mode IN ('live', 'simulate')", name="run_requests_mode"),
+        sa.CheckConstraint(f"status IN ({_in(STATUSES)})", name="run_requests_status"),
+        sa.CheckConstraint("envelope_role = 'envelope'", name="run_requests_envelope_role"),
+        sa.CheckConstraint("(status = 'refused') = (envelope_id IS NULL)", name="run_requests_envelope_iff_admitted"),
+        sa.CheckConstraint("status = 'refused' OR workflow_version_id IS NOT NULL", name="run_requests_frozen"),
+        sa.CheckConstraint(f"(status IN ({_in(TERMINAL)})) = (ended_at IS NOT NULL)", name="run_requests_ended"),
+        sa.CheckConstraint("octet_length(digest) = 32 AND attempts >= 0", name="run_requests_values"),
+    )
+    op.create_index(
+        "run_requests_due",
+        "run_requests",
+        ["tenant_id", "queued_at", "id"],
+        postgresql_where=sa.text("status = 'queued'"),
+    )
+    op.create_index("run_requests_listed", "run_requests", ["tenant_id", sa.text("queued_at DESC"), sa.text("id DESC")])
+
+    op.create_table(
+        "tenant_run_limits",  # the row whose lock serializes a tenant's slot reservations (§7.5)
+        sa.Column("tenant_id", pg.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), primary_key=True),
+        sa.Column("max_concurrent", sa.SmallInteger),  # none: the platform's default
+        sa.CheckConstraint("max_concurrent IS NULL OR max_concurrent > 0", name="tenant_run_limits_positive"),
+    )
+    op.create_table(
+        "run_slots",  # one row per running root run (§7.5)
+        sa.Column("run_id", pg.UUID(as_uuid=True), primary_key=True),
+        sa.Column("tenant_id", pg.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
+        sa.Column("reserved_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
+    )
+    op.create_index("run_slots_tenant", "run_slots", ["tenant_id"])
+    op.create_table(
+        "current_build",  # what the dispatcher last read from Temporal, for admission's ABI check (ruling 1)
+        sa.Column("id", sa.SmallInteger, primary_key=True),
+        sa.Column("build_id", sa.Text, nullable=False),
+        sa.Column("engine_abi", sa.Integer, nullable=False),
+        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
+        sa.CheckConstraint("id = 1", name="current_build_one_row"),
+    )
+
+    # A root run's row is written at dispatch, before Temporal answers (§7.3): queued at once, started when confirmed.
+    op.add_column("runs", sa.Column("queued_at", sa.DateTime(timezone=True)))
+    op.execute("UPDATE runs SET queued_at = started_at")
+    op.alter_column("runs", "queued_at", nullable=False, server_default=sa.func.now())
+    op.alter_column("runs", "started_at", nullable=True, server_default=None)
+    op.drop_index("runs_tenant_started", table_name="runs")
+    op.create_index("runs_tenant_queued", "runs", ["tenant_id", sa.text("queued_at DESC"), sa.text("id DESC")])
+
+    for statement in STATEMENTS:
+        op.execute(statement)
+
+
+def downgrade() -> None:
+    op.execute("DROP FUNCTION IF EXISTS dispatch_candidates(integer)")
+    op.execute("REVOKE SELECT, INSERT ON run_inputs FROM dewpoint_api")
+    op.execute("REVOKE SELECT, INSERT, UPDATE ON run_secret_index FROM dewpoint_api")
+    op.drop_index("runs_tenant_queued", table_name="runs")
+    op.create_index("runs_tenant_started", "runs", ["tenant_id", sa.text("started_at DESC"), "id"])
+    op.execute("UPDATE runs SET started_at = queued_at WHERE started_at IS NULL")
+    op.alter_column("runs", "started_at", nullable=False, server_default=sa.func.now())
+    op.drop_column("runs", "queued_at")
+    for table in ("current_build", *reversed(TABLES)):
+        op.execute(f"DROP POLICY IF EXISTS {table}_scope ON {table}")
+        op.drop_table(table)
+    op.drop_index("run_inputs_one_envelope", table_name="run_inputs")
+    op.drop_constraint("run_inputs_envelope_ref", "run_inputs")
+    op.drop_constraint("run_inputs_role", "run_inputs")
+    op.execute("DELETE FROM run_inputs WHERE role = 'envelope'")
+    op.alter_column("run_inputs", "pointer", nullable=False)
+    op.drop_column("run_inputs", "role")
+    op.drop_constraint("platform_settings_max_concurrent", "platform_settings")
+    op.drop_column("platform_settings", "max_concurrent_runs")
+    op.drop_constraint("tenants_status", "tenants")
+    op.drop_column("tenants", "status")
diff --git a/backend/src/dewpoint/core/models/__init__.py b/backend/src/dewpoint/core/models/__init__.py
index f37f91b..4c0d33a 100644
--- a/backend/src/dewpoint/core/models/__init__.py
+++ b/backend/src/dewpoint/core/models/__init__.py
@@ -1,5 +1,18 @@
 # SPDX-License-Identifier: Apache-2.0
-from dewpoint.core.models import audit, claims, connections, identity, keys, plugins, runs, tenancy, workflows
+from dewpoint.core.models import (
+    audit,
+    claims,
+    connections,
+    identity,
+    keys,
+    plugins,
+    requests,
+    runs,
+    tenancy,
+    workflows,
+)
 from dewpoint.core.models.base import Base
 
-__all__ = ["Base", "audit", "claims", "connections", "identity", "keys", "plugins", "runs", "tenancy", "workflows"]
+__all__ = [
+    "Base", "audit", "claims", "connections", "identity", "keys", "plugins", "requests", "runs", "tenancy", "workflows",
+]  # fmt: skip
diff --git a/backend/src/dewpoint/core/models/claims.py b/backend/src/dewpoint/core/models/claims.py
index 697056c..7adf020 100644
--- a/backend/src/dewpoint/core/models/claims.py
+++ b/backend/src/dewpoint/core/models/claims.py
@@ -29,10 +29,14 @@ class _Claim:
 
 
 class InputClaim(_Claim, Base):
-    """A claim made before its run starts: a trigger's claimed parts, a sub-flow's input (§3.5)."""
+    """A claim made before its run starts: a trigger's claimed parts, a sub-flow's input (§3.5). Or, with the role
+    `envelope`, a request's trigger envelope (revision 7, §7.1): not a claim, never read or granted as one."""
 
     __tablename__ = "run_inputs"
-    pointer: Mapped[str] = mapped_column(Text)  # where in the run's input it was claimed from
+    role: Mapped[str] = mapped_column(String(16), default="claim")
+    pointer: Mapped[str | None] = mapped_column(
+        Text
+    )  # where in the run's input it was claimed from; none for an envelope
 
 
 class OutputClaim(_Claim, Base):
diff --git a/backend/src/dewpoint/core/models/platform.py b/backend/src/dewpoint/core/models/platform.py
index e33625e..5947900 100644
--- a/backend/src/dewpoint/core/models/platform.py
+++ b/backend/src/dewpoint/core/models/platform.py
@@ -18,6 +18,7 @@ class PlatformSettings(Base):
     environment: Mapped[str] = mapped_column(String(16))
     temporal_namespace: Mapped[str] = mapped_column(Text)
     production_runs: Mapped[bool] = mapped_column(Boolean, default=False)
+    max_concurrent_runs: Mapped[int] = mapped_column(SmallInteger, default=5)  # per tenant, unless its limits row says
     recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
 
 
diff --git a/backend/src/dewpoint/core/models/requests.py b/backend/src/dewpoint/core/models/requests.py
new file mode 100644
index 0000000..e965234
--- /dev/null
+++ b/backend/src/dewpoint/core/models/requests.py
@@ -0,0 +1,71 @@
+# SPDX-License-Identifier: Apache-2.0
+"""Admission's queue (engine 2b spec §7): one row per run request, the intent itself, under row-level security; the
+slots a tenant's running root runs hold; its limits row; and the current build as the dispatcher last read it."""
+
+import uuid
+from datetime import datetime
+
+from sqlalchemy import DateTime, ForeignKey, Integer, LargeBinary, SmallInteger, String, Text, func
+from sqlalchemy.dialects.postgresql import UUID
+from sqlalchemy.orm import Mapped, mapped_column
+
+from dewpoint.core.models.base import Base
+
+SOURCES = ("manual", "rerun", "schedule", "webhook", "dev")
+STATUSES = ("queued", "starting", "started", "cancelled", "refused", "dead")
+TERMINAL = ("cancelled", "refused", "dead")  # a started request's run carries on: its own status says when it ends
+
+
+class RunRequest(Base):
+    """A request to run a workflow, frozen on its version (§7.1). Its id is the run's once it starts. The trigger isn't
+    here: it's an envelope in `run_inputs`, encrypted, beside the claims it holds handles to (revision 7)."""
+
+    __tablename__ = "run_requests"
+    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
+    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"))
+    workflow_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("workflows.id"))
+    workflow_version_id: Mapped[uuid.UUID | None] = mapped_column(
+        UUID(as_uuid=True), ForeignKey("workflow_versions.id")
+    )
+    source: Mapped[str] = mapped_column(String(16))
+    actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
+    mode: Mapped[str] = mapped_column(String(16))
+    idempotency_key: Mapped[str] = mapped_column(String(255))
+    digest: Mapped[bytes] = mapped_column(LargeBinary)
+    digest_key_version: Mapped[int] = mapped_column(Integer)
+    status: Mapped[str] = mapped_column(String(16))
+    reason: Mapped[str | None] = mapped_column(String(64))
+    attempts: Mapped[int] = mapped_column(Integer, default=0)
+    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
+    queued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
+    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
+    cancel_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
+    envelope_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
+
+
+class TenantRunLimits(Base):
+    """A tenant's limits row: its lock serializes the tenant's slot reservations (§7.5)."""
+
+    __tablename__ = "tenant_run_limits"
+    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"), primary_key=True)
+    max_concurrent: Mapped[int | None] = mapped_column(SmallInteger)  # none: the platform's default
+
+
+class RunSlot(Base):
+    """One running root run's slot (§7.5): reserved at dispatch, released by the run's end write."""
+
+    __tablename__ = "run_slots"
+    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
+    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"))
+    reserved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
+
+
+class CurrentBuild(Base):
+    """The deployment's current build as the dispatcher last read it from Temporal, and when (the owner's ruling):
+    admission's ABI check, which fails closed when it's missing or stale."""
+
+    __tablename__ = "current_build"
+    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, default=1)
+    build_id: Mapped[str] = mapped_column(Text)
+    engine_abi: Mapped[int] = mapped_column(Integer)
+    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
diff --git a/backend/src/dewpoint/core/models/runs.py b/backend/src/dewpoint/core/models/runs.py
index ea6734c..e4e1722 100644
--- a/backend/src/dewpoint/core/models/runs.py
+++ b/backend/src/dewpoint/core/models/runs.py
@@ -24,7 +24,10 @@ class Run(Base):
     workflow_version_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
     mode: Mapped[str] = mapped_column(String(16))
     status: Mapped[str] = mapped_column(String(32))
-    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
+    # A root run's row is written at dispatch, before Temporal answers (engine 2b spec §7.3): queued then, started
+    # once the start is confirmed. A run from before 2b-2 was queued when it started.
+    queued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
+    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
     ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
     error_code: Mapped[str | None] = mapped_column(Text)  # a plugin's code: nothing bounds it, sanitize() does
     error_message: Mapped[str | None] = mapped_column(Text)
diff --git a/backend/src/dewpoint/core/models/tenancy.py b/backend/src/dewpoint/core/models/tenancy.py
index 878c0cb..cdb9651 100644
--- a/backend/src/dewpoint/core/models/tenancy.py
+++ b/backend/src/dewpoint/core/models/tenancy.py
@@ -17,6 +17,7 @@ class Tenant(UUIDPk, Timestamps, Base):
     name: Mapped[str] = mapped_column(String(200))
     slug: Mapped[str] = mapped_column(String(63), unique=True)
     require_passkey: Mapped[bool] = mapped_column(Boolean, default=False)
+    status: Mapped[str] = mapped_column(String(16), default="active")  # `erasing`: refused by admission and dispatch
 
 
 class Membership(UUIDPk, Timestamps, Base):
diff --git a/backend/src/dewpoint/core/runs/service.py b/backend/src/dewpoint/core/runs/service.py
index d9d041b..99b4fac 100644
--- a/backend/src/dewpoint/core/runs/service.py
+++ b/backend/src/dewpoint/core/runs/service.py
@@ -10,7 +10,7 @@ from collections.abc import Iterable, Mapping
 from datetime import datetime
 from typing import Any
 
-from sqlalchemy import select, tuple_, update
+from sqlalchemy import func, select, tuple_, update
 from sqlalchemy.dialects.postgresql import insert
 from sqlalchemy.ext.asyncio import AsyncSession
 
@@ -75,6 +75,7 @@ async def insert_run(
         status="running",
         iterations=0,
         started_by=started_by,
+        started_at=func.now(),
     )
     s.add(run)
     await s.flush()
diff --git a/backend/tests/core/claims/test_rls_claims.py b/backend/tests/core/claims/test_rls_claims.py
index 1676913..c24befb 100644
--- a/backend/tests/core/claims/test_rls_claims.py
+++ b/backend/tests/core/claims/test_rls_claims.py
@@ -82,10 +82,12 @@ async def test_a_row_for_another_tenant_is_refused(owner_sessionmaker, worker_se
             await s.execute(insert(table, values), values)
 
 
-# Who may do what. Admission (the dispatch role, until 2b-2's dispatcher) claims a trigger and seeds the secret index;
-# the worker claims during a run, grants, and resolves. Nobody updates or deletes a claim: retention (2b-4) gets its
-# own role.
+# Who may do what. Admission claims a trigger and seeds the secret index in its caller's transaction: the API's (the
+# owner's ruling on 2b-2), the CLI's as dispatch; the worker claims during a run, grants, and resolves. Nobody updates
+# or deletes a claim: retention (2b-4) gets its own role.
 ALLOWED = {
+    ("api", "run_inputs"): {"select", "insert"},
+    ("api", "run_secret_index"): {"select", "insert", "update"},
     ("dispatch", "run_inputs"): {"select", "insert"},
     ("dispatch", "run_secret_index"): {"select", "insert", "update"},
     ("worker", "run_inputs"): {"select", "insert"},
diff --git a/backend/tests/core/requests/__init__.py b/backend/tests/core/requests/__init__.py
new file mode 100644
index 0000000..e69de29
diff --git a/backend/tests/core/requests/test_schema.py b/backend/tests/core/requests/test_schema.py
new file mode 100644
index 0000000..f1b9cc0
--- /dev/null
+++ b/backend/tests/core/requests/test_schema.py
@@ -0,0 +1,301 @@
+# SPDX-License-Identifier: Apache-2.0
+"""Admission's tables (engine 2b spec §7.1, §7.5, §14; revision 7's envelope): the request queue, the slots and the
+limits under forced row-level security; the trigger's envelope stored beside its claims with a shape the database
+enforces; `runs` ordered by when they were queued; and the one way the dispatcher sees every tenant's queue, which
+shows it nothing but what it needs to pick."""
+
+import uuid
+from typing import Any
+
+import pytest
+from sqlalchemy import text
+from sqlalchemy.exc import DBAPIError, IntegrityError
+
+from dewpoint.core.db import tenant_scope
+from tests.support.workflows import seed_workflow
+
+TABLES = ("run_requests", "tenant_run_limits", "run_slots")
+
+
+async def claim(
+    s: Any, tenant: uuid.UUID, owner: uuid.UUID, *, role: str = "claim", pointer: str | None = ""
+) -> uuid.UUID:
+    claim_id = uuid.uuid4()
+    await s.execute(
+        text(
+            "insert into run_inputs (id, tenant_id, owner_run_id, root_run_id, sensitive_pointers, content_hash, "
+            "ciphertext, pointer, role) values (:id, :t, :o, :o, '[]', :h, :c, :p, :r)"
+        ),
+        {"id": claim_id, "t": tenant, "o": owner, "h": b"\x00" * 32, "c": b"\x01", "p": pointer, "r": role},
+    )
+    return claim_id
+
+
+def request(tenant: uuid.UUID, wf: uuid.UUID, version: uuid.UUID | None, **extra: Any) -> dict[str, Any]:
+    return {"id": uuid.uuid4(), "tenant_id": tenant, "workflow_id": wf, "workflow_version_id": version,
+            "source": "manual", "mode": "live", "idempotency_key": str(uuid.uuid4()), "digest": b"\x02" * 32,
+            "digest_key_version": 1, "status": "queued", "envelope_id": None, **extra}  # fmt: skip
+
+
+INSERT_REQUEST = text(
+    "insert into run_requests (id, tenant_id, workflow_id, workflow_version_id, source, mode, idempotency_key, digest, "
+    "digest_key_version, status, envelope_id, ended_at) values (:id, :tenant_id, :workflow_id, :workflow_version_id, "
+    ":source, :mode, :idempotency_key, :digest, :digest_key_version, cast(:status as varchar), :envelope_id, "
+    "case when cast(:status as varchar) in ('cancelled', 'refused', 'dead') then now() end)"
+)
+
+
+@pytest.mark.parametrize("table", TABLES)
+async def test_each_admission_table_forces_row_level_security(owner_sessionmaker, table) -> None:
+    async with owner_sessionmaker() as s:
+        flags = (
+            await s.execute(
+                text("select relrowsecurity, relforcerowsecurity from pg_class where relname = :t"), {"t": table}
+            )
+        ).one()
+    assert tuple(flags) == (True, True)
+
+
+async def test_a_request_with_its_envelope_is_seen_only_within_its_tenant(
+    owner_sessionmaker, api_sessionmaker, dispatch_sessionmaker
+) -> None:
+    tenant, wf, version = await seed_workflow(owner_sessionmaker)
+    other, _, _ = await seed_workflow(owner_sessionmaker, name="Other")
+    values = request(tenant, wf, version)
+    async with api_sessionmaker() as s, s.begin():  # admission runs in the API's transaction (ruling 2)
+        await tenant_scope(s, tenant)
+        values["envelope_id"] = await claim(s, tenant, values["id"], role="envelope", pointer=None)
+        await s.execute(INSERT_REQUEST, values)
+    count = text("select count(*) from run_requests")
+    for maker in (api_sessionmaker, dispatch_sessionmaker):
+        async with maker() as s, s.begin():
+            assert (await s.execute(count)).scalar_one() == 0
+            await tenant_scope(s, other)
+            assert (await s.execute(count)).scalar_one() == 0
+        async with maker() as s, s.begin():
+            await tenant_scope(s, tenant)
+            assert (await s.execute(count)).scalar_one() == 1
+
+
+async def test_the_worker_never_reads_the_queue(owner_sessionmaker, worker_sessionmaker) -> None:
+    tenant, _, _ = await seed_workflow(owner_sessionmaker)
+    with pytest.raises(DBAPIError, match="permission denied"):
+        async with worker_sessionmaker() as s, s.begin():
+            await tenant_scope(s, tenant)
+            await s.execute(text("select count(*) from run_requests"))
+
+
+async def test_only_a_refused_request_has_no_envelope(owner_sessionmaker) -> None:
+    tenant, wf, version = await seed_workflow(owner_sessionmaker)
+    async with owner_sessionmaker() as s, s.begin():
+        await s.execute(INSERT_REQUEST, request(tenant, wf, None, status="refused"))  # refused before it was frozen
+    with pytest.raises(IntegrityError, match="run_requests_envelope_iff_admitted"):
+        async with owner_sessionmaker() as s, s.begin():
+            await s.execute(INSERT_REQUEST, request(tenant, wf, version))
+    async with owner_sessionmaker() as s, s.begin():
+        values = request(tenant, wf, version, status="refused")
+        values["envelope_id"] = await claim(s, tenant, values["id"], role="envelope", pointer=None)
+        with pytest.raises(IntegrityError, match="run_requests_envelope_iff_admitted"):
+            await s.execute(INSERT_REQUEST, values)
+
+
+async def test_a_request_reaches_only_an_envelope_it_owns(owner_sessionmaker) -> None:
+    """The reference can't name a claim, nor another request's envelope (revision 7: an enforced shape)."""
+    tenant, wf, version = await seed_workflow(owner_sessionmaker)
+    for role, owned in (("claim", True), ("envelope", False)):
+        with pytest.raises(IntegrityError, match="run_requests_envelope"):
+            async with owner_sessionmaker() as s, s.begin():
+                values = request(tenant, wf, version)
+                owner = values["id"] if owned else uuid.uuid4()
+                pointer = "" if role == "claim" else None
+                values["envelope_id"] = await claim(s, tenant, owner, role=role, pointer=pointer)
+                await s.execute(INSERT_REQUEST, values)
+
+
+async def test_an_envelope_outlives_no_request_and_stands_alone_per_owner(owner_sessionmaker) -> None:
+    tenant, wf, version = await seed_workflow(owner_sessionmaker)
+    values = request(tenant, wf, version)
+    async with owner_sessionmaker() as s, s.begin():
+        values["envelope_id"] = await claim(s, tenant, values["id"], role="envelope", pointer=None)
+        await s.execute(INSERT_REQUEST, values)
+    with pytest.raises(IntegrityError, match="run_requests_envelope"):  # retention deletes both together, never one
+        async with owner_sessionmaker() as s, s.begin():
+            await s.execute(text("delete from run_inputs where id = :e"), {"e": values["envelope_id"]})
+    with pytest.raises(IntegrityError, match="run_inputs_one_envelope"):
+        async with owner_sessionmaker() as s, s.begin():
+            await claim(s, tenant, values["id"], role="envelope", pointer=None)
+
+
+@pytest.mark.parametrize(("role", "pointer"), [("claim", None), ("envelope", ""), ("envelope", "/a"), ("other", "")])
+async def test_a_claim_has_a_pointer_and_an_envelope_none(owner_sessionmaker, role, pointer) -> None:
+    tenant, _, _ = await seed_workflow(owner_sessionmaker)
+    with pytest.raises(IntegrityError, match="run_inputs_role"):
+        async with owner_sessionmaker() as s, s.begin():
+            await claim(s, tenant, uuid.uuid4(), role=role, pointer=pointer)
+
+
+async def test_an_idempotency_key_is_one_request_per_tenant(owner_sessionmaker) -> None:
+    tenant, wf, version = await seed_workflow(owner_sessionmaker)
+    other, wf2, version2 = await seed_workflow(owner_sessionmaker, name="Other")
+    first = request(tenant, wf, version, status="refused", workflow_version_id=None)
+    async with owner_sessionmaker() as s, s.begin():
+        await s.execute(INSERT_REQUEST, first)
+        await s.execute(
+            INSERT_REQUEST, request(other, wf2, None, status="refused", idempotency_key=first["idempotency_key"])
+        )
+    with pytest.raises(IntegrityError, match="run_requests_idempotency"):
+        async with owner_sessionmaker() as s, s.begin():
+            await s.execute(
+                INSERT_REQUEST, request(tenant, wf, None, status="refused", idempotency_key=first["idempotency_key"])
+            )
+
+
+async def test_runs_are_queued_before_they_start(owner_sessionmaker) -> None:
+    """A root run's row is written at dispatch, before Temporal answers: it's queued at once and started only once the
+    start is confirmed (§7.3)."""
+    tenant, wf, version = await seed_workflow(owner_sessionmaker)
+    async with owner_sessionmaker() as s, s.begin():
+        await s.execute(
+            text(
+                "insert into runs (id, tenant_id, workflow_id, workflow_version_id, mode, status, iterations) "
+                "values (:id, :t, :w, :v, 'live', 'running', 0)"
+            ),  # fmt: skip
+            {"id": uuid.uuid4(), "t": tenant, "w": wf, "v": version},
+        )
+        row = (await s.execute(text("select queued_at is not null, started_at from runs"))).one()
+    assert tuple(row) == (True, None)
+
+
+async def test_the_current_build_is_written_by_the_dispatcher_and_read_by_admission(
+    owner_sessionmaker, api_sessionmaker, dispatch_sessionmaker
+) -> None:
+    async with dispatch_sessionmaker() as s, s.begin():
+        await s.execute(
+            text(
+                "insert into current_build (id, build_id, engine_abi, observed_at) values (1, 'b6', 6, now()) "
+                "on conflict (id) do update set build_id = excluded.build_id, engine_abi = excluded.engine_abi, "
+                "observed_at = excluded.observed_at"
+            )  # fmt: skip
+        )
+    async with api_sessionmaker() as s:
+        assert (await s.execute(text("select build_id, engine_abi from current_build"))).one() == ("b6", 6)
+    with pytest.raises(DBAPIError, match="permission denied"):
+        async with api_sessionmaker() as s, s.begin():
+            await s.execute(text("update current_build set engine_abi = 5"))
+
+
+async def test_the_dispatcher_picks_from_every_tenant_seeing_only_what_it_needs(
+    owner_sessionmaker, api_sessionmaker, dispatch_sessionmaker
+) -> None:
+    """Ruling 3: across tenants, only queue-selection metadata. The oldest due request of each tenant, FIFO among due
+    ones: one waiting for its next attempt doesn't hold back those behind it."""
+    a, wf_a, v_a = await seed_workflow(owner_sessionmaker)
+    b, wf_b, v_b = await seed_workflow(owner_sessionmaker, name="B")
+    rows = []
+    async with owner_sessionmaker() as s, s.begin():
+        for tenant, wf, v, delay in ((a, wf_a, v_a, "1 hour"), (a, wf_a, v_a, None), (a, wf_a, v_a, None),
+                                     (b, wf_b, v_b, None)):  # fmt: skip
+            values = request(tenant, wf, v)
+            values["envelope_id"] = await claim(s, tenant, values["id"], role="envelope", pointer=None)
+            await s.execute(INSERT_REQUEST, values)
+            await s.execute(text("update run_requests set queued_at = now() + make_interval(secs => :n) where id = :i"),
+                            {"n": len(rows), "i": values["id"]})  # queued in this order  # fmt: skip
+            if delay:
+                await s.execute(text(f"update run_requests set next_attempt_at = now() + interval '{delay}' "
+                                     "where id = :i"), {"i": values["id"]})  # fmt: skip
+            rows.append(values["id"])
+    async with dispatch_sessionmaker() as s:
+        picked = (await s.execute(text("select * from dispatch_candidates(10)"))).mappings().all()
+    assert {(r["tenant_id"], r["request_id"]) for r in picked} == {(a, rows[1]), (b, rows[3])}
+    assert set(picked[0].keys()) == {"tenant_id", "request_id"}
+    with pytest.raises(DBAPIError, match="permission denied"):
+        async with api_sessionmaker() as s:
+            await s.execute(text("select * from dispatch_candidates(10)"))
+
+
+async def test_a_slot_is_reserved_by_the_dispatcher_and_released_by_the_end_write(
+    owner_sessionmaker, dispatch_sessionmaker, worker_sessionmaker
+) -> None:
+    tenant, _, _ = await seed_workflow(owner_sessionmaker)
+    run = uuid.uuid4()
+    async with dispatch_sessionmaker() as s, s.begin():
+        await tenant_scope(s, tenant)
+        await s.execute(text("insert into run_slots (tenant_id, run_id) values (:t, :r)"), {"t": tenant, "r": run})
+    async with worker_sessionmaker() as s, s.begin():
+        await tenant_scope(s, tenant)
+        assert (await s.execute(text("delete from run_slots where run_id = :r"), {"r": run})).rowcount == 1
+
+
+async def test_a_tenant_is_active_until_it_is_erased(owner_sessionmaker) -> None:
+    tenant, _, _ = await seed_workflow(owner_sessionmaker)
+    async with owner_sessionmaker() as s, s.begin():
+        assert (
+            await s.execute(text("select status from tenants where id = :t"), {"t": tenant})
+        ).scalar_one() == "active"
+    with pytest.raises(IntegrityError, match="tenants_status"):
+        async with owner_sessionmaker() as s, s.begin():
+            await s.execute(text("update tenants set status = 'paused' where id = :t"), {"t": tenant})
+
+
+# Who may do what (§7, §14): admission freezes requests in the API's transaction and a user cancels a queued one; the
+# dispatcher moves requests, reserves slots under the limits row and records the current build; the worker's end write
+# releases a slot. Column-level grants narrow the API's updates to a cancel's columns.
+ALLOWED = {
+    ("api", "run_requests"): {"select", "insert", "update"},
+    ("api", "tenant_run_limits"): {"select"},
+    ("api", "run_slots"): {"select"},
+    ("api", "current_build"): {"select"},
+    ("dispatch", "run_requests"): {"select", "insert", "update"},
+    ("dispatch", "tenant_run_limits"): {"select", "insert", "update"},
+    ("dispatch", "run_slots"): {"select", "insert", "delete"},
+    ("dispatch", "current_build"): {"select", "insert", "update"},
+    ("worker", "run_slots"): {"select", "delete"},
+}
+ROLES = ("api", "dispatch", "worker", "admin", "auditor")
+OPS = ("select", "insert", "update", "delete")
+
+
+@pytest.mark.parametrize("table", [*TABLES, "current_build"])
+async def test_each_role_has_exactly_its_privileges(owner_sessionmaker, table) -> None:
+    async with owner_sessionmaker() as s:
+        for role in ROLES:
+            for op in OPS:
+                granted = (
+                    await s.execute(
+                        text(  # an update granted on a cancel's columns only counts too; a delete is whole-table
+                            "select has_table_privilege(:r, :t, :p) "
+                            "or (:p <> 'delete' and has_any_column_privilege(:r, :t, :p))"
+                        ),
+                        {"r": f"dewpoint_{role}", "t": table, "p": op},
+                    )
+                ).scalar_one()
+                assert granted == (op in ALLOWED.get((role, table), set())), (role, table, op)
+
+
+async def test_the_api_updates_only_what_a_cancel_changes(owner_sessionmaker, api_sessionmaker) -> None:
+    tenant, wf, version = await seed_workflow(owner_sessionmaker)
+    values = request(tenant, wf, version)
+    async with owner_sessionmaker() as s, s.begin():
+        values["envelope_id"] = await claim(s, tenant, values["id"], role="envelope", pointer=None)
+        await s.execute(INSERT_REQUEST, values)
+    async with api_sessionmaker() as s, s.begin():
+        await tenant_scope(s, tenant)
+        cancel = (
+            "update run_requests set status = 'cancelled', reason = 'user_cancelled', ended_at = now() where id = :i"
+        )
+        await s.execute(text(cancel), {"i": values["id"]})
+    with pytest.raises(DBAPIError, match="permission denied"):
+        async with api_sessionmaker() as s, s.begin():
+            await tenant_scope(s, tenant)
+            await s.execute(text("update run_requests set attempts = 9 where id = :i"), {"i": values["id"]})
+
+
+async def test_a_request_reaches_no_envelope_of_another_tenant(owner_sessionmaker) -> None:
+    """The reference proves the envelope's tenant too, not only its id, owner and role (the owner's M1 checkpoint)."""
+    tenant, wf, version = await seed_workflow(owner_sessionmaker)
+    other, _, _ = await seed_workflow(owner_sessionmaker, name="Other")
+    with pytest.raises(IntegrityError, match="run_requests_envelope"):
+        async with owner_sessionmaker() as s, s.begin():
+            values = request(tenant, wf, version)
+            values["envelope_id"] = await claim(s, other, values["id"], role="envelope", pointer=None)
+            await s.execute(INSERT_REQUEST, values)
```

### Task 2: No digest of a claim's value is kept; a rewrite decrypts the existing claim

**Commit:** `412fbc9` (prototype `proto/2b2-v2`); the replay's tree was identical: yes.

**Create:** `backend/migrations/versions/0018_claims_without_digest.py`

**Modify:** `backend/src/dewpoint/core/claims/service.py`, `backend/src/dewpoint/core/models/claims.py`, `backend/tests/core/claims/test_rls_claims.py`, `backend/tests/core/claims/test_service.py`, `backend/tests/core/requests/test_schema.py`, `docs/operations/deployment.md`

**What it does:**

`content_hash` was an unkeyed SHA-256 of each claim's canonical plaintext, sensitive claims included, in `run_inputs`
and `step_outputs`: anyone who could read those tables could test guesses for a low-entropy secret offline. Migration
0018 drops it. A write that finds its claim id taken now opens the existing claim, with the key version its ciphertext
names, and compares the canonical plaintext: a retry of the same value is a no-op, another value a conflict, across a
key rotation too. The migration's docstring and the deployment guide cover backups taken before it, which still hold
the hashes. Its downgrade brings the column back empty, since hashes can't be recomputed without the plaintext.


- [ ] **Step 1: its tests alone, before its code.** Run: `uv run pytest -n 4 tests/core/claims/test_rls_claims.py tests/core/claims/test_service.py tests/core/requests/test_schema.py`. Replay result (exit 1), shortened:

```
FAILED tests/core/claims/test_rls_claims.py::test_a_row_is_seen_only_within_its_tenant[step_outputs]
FAILED tests/core/claims/test_service.py::test_no_digest_of_a_claims_value_is_kept
FAILED tests/core/requests/test_schema.py::test_a_request_with_its_envelope_is_seen_only_within_its_tenant
FAILED tests/core/requests/test_schema.py::test_only_a_refused_request_has_no_envelope
FAILED tests/core/requests/test_schema.py::test_a_request_reaches_only_an_envelope_it_owns
FAILED tests/core/requests/test_schema.py::test_a_claim_has_a_pointer_and_an_envelope_none[claim-None]
FAILED tests/core/requests/test_schema.py::test_an_envelope_outlives_no_request_and_stands_alone_per_owner
FAILED tests/core/requests/test_schema.py::test_a_claim_has_a_pointer_and_an_envelope_none[envelope-]
FAILED tests/core/requests/test_schema.py::test_a_claim_has_a_pointer_and_an_envelope_none[envelope-/a]
FAILED tests/core/requests/test_schema.py::test_a_claim_has_a_pointer_and_an_envelope_none[other-]
FAILED tests/core/requests/test_schema.py::test_the_dispatcher_picks_from_every_tenant_seeing_only_what_it_needs
FAILED tests/core/requests/test_schema.py::test_the_api_updates_only_what_a_cancel_changes
FAILED tests/core/requests/test_schema.py::test_a_request_reaches_no_envelope_of_another_tenant
14 failed, 34 passed in 12.65s
```

- [ ] **Step 2: its code, then the same tests.** Replay result (exit 0), shortened:

```
................................................                         [100%]
48 passed in 12.84s
```

- [ ] **Step 3: commit.** `git cherry-pick --no-commit 412fbc9 && git commit -C 412fbc9`

The diff:

```diff
diff --git a/backend/migrations/versions/0018_claims_without_digest.py b/backend/migrations/versions/0018_claims_without_digest.py
new file mode 100644
index 0000000..2d21acb
--- /dev/null
+++ b/backend/migrations/versions/0018_claims_without_digest.py
@@ -0,0 +1,31 @@
+# SPDX-License-Identifier: Apache-2.0
+"""claims keep no digest of their value (#28; engine 2b spec §3.1, revision 7)
+
+`content_hash` was an unkeyed SHA-256 of each claim's plaintext, sensitive claims included: anyone who could read the
+claim tables could test guesses for a low-entropy secret offline. A rewrite of a claim's id is now checked by decrypting
+the existing claim. Dropping the column removes the hashes from the live database only: a backup taken before this
+migration still holds them, so it's handled as sensitive until it expires (docs/operations/deployment.md)."""
+
+import sqlalchemy as sa
+from alembic import op
+
+revision = "0018"
+down_revision = "0017"
+branch_labels = None
+depends_on = None
+
+
+def upgrade() -> None:
+    op.drop_constraint("run_inputs_hash", "run_inputs")
+    op.drop_constraint("step_outputs_hash", "step_outputs")
+    op.drop_column("run_inputs", "content_hash")
+    op.drop_column("step_outputs", "content_hash")
+
+
+def downgrade() -> None:
+    # The hashes can't be recomputed without the plaintext: the column comes back empty for every row (its check
+    # passes on an empty value).
+    op.add_column("step_outputs", sa.Column("content_hash", sa.LargeBinary))
+    op.add_column("run_inputs", sa.Column("content_hash", sa.LargeBinary))
+    op.create_check_constraint("step_outputs_hash", "step_outputs", "octet_length(content_hash) = 32")
+    op.create_check_constraint("run_inputs_hash", "run_inputs", "octet_length(content_hash) = 32")
diff --git a/backend/src/dewpoint/core/claims/service.py b/backend/src/dewpoint/core/claims/service.py
index 82477f8..0e30307 100644
--- a/backend/src/dewpoint/core/claims/service.py
+++ b/backend/src/dewpoint/core/claims/service.py
@@ -11,7 +11,6 @@ The caller opens the transaction under the tenant's scope (`tenant_scope`), and
 activity's server-built workflow id names (§3.3). Pointers and nested handles are the engine's (`engine.handles`):
 this module stores and returns whole values."""
 
-import hashlib
 import json
 import uuid
 from dataclasses import dataclass
@@ -58,14 +57,12 @@ async def _write(
     s: AsyncSession, cipher: ClaimCipher, tenant_id: uuid.UUID, model: Any, new: NewClaim, **extra: Any
 ) -> None:
     plain = _plain(new.value)
-    digest = hashlib.sha256(plain).digest()
     row = {
         "id": new.id,
         "tenant_id": tenant_id,
         "owner_run_id": new.owner_run_id,
         "root_run_id": new.root_run_id,
         "sensitive_pointers": list(new.sensitive_pointers),
-        "content_hash": digest,
         "ciphertext": await cipher.seal(str(tenant_id), str(new.id), plain),
         **extra,
     }
@@ -74,8 +71,10 @@ async def _write(
     )
     if written.scalar_one_or_none() is not None:
         return
-    existing = (await s.execute(select(model.content_hash).where(model.id == new.id))).scalar_one_or_none()
-    if existing != digest:
+    # Its id is taken: a retry writes the same value, anything else is a conflict. The existing claim is opened to
+    # tell, with the key version its ciphertext names: no digest of a value is kept (#28).
+    existing = (await s.execute(select(model.ciphertext).where(model.id == new.id))).scalar_one_or_none()
+    if existing is None or await cipher.open(str(tenant_id), str(new.id), existing) != plain:
         raise ClaimConflictError("A claim was written again with other content.")
 
 
diff --git a/backend/src/dewpoint/core/models/claims.py b/backend/src/dewpoint/core/models/claims.py
index 7adf020..dfa6677 100644
--- a/backend/src/dewpoint/core/models/claims.py
+++ b/backend/src/dewpoint/core/models/claims.py
@@ -23,7 +23,6 @@ class _Claim:
     owner_run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
     root_run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
     sensitive_pointers: Mapped[Any] = mapped_column(JSONB)  # the tainted pointers inside the value ("" is all of it)
-    content_hash: Mapped[bytes] = mapped_column(LargeBinary)
     ciphertext: Mapped[bytes] = mapped_column(LargeBinary)
     created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
 
diff --git a/backend/tests/core/claims/test_rls_claims.py b/backend/tests/core/claims/test_rls_claims.py
index c24befb..5118c81 100644
--- a/backend/tests/core/claims/test_rls_claims.py
+++ b/backend/tests/core/claims/test_rls_claims.py
@@ -2,7 +2,6 @@
 """The claim tables (engine 2b spec §3.1, §3.4, §3.7, §14): tenant-scoped under forced row-level security, written
 once and never changed, and reachable only by the roles that make and resolve claims."""
 
-import hashlib
 import uuid
 from typing import Any
 
@@ -32,8 +31,7 @@ def row(table: str, tenant: uuid.UUID) -> dict[str, Any]:
         return {"root_run_id": run, "tenant_id": tenant, "version": 1, "string_count": 0, "byte_count": 0,
                 "ciphertext": b"\x01"}  # fmt: skip
     claim = {"id": uuid.uuid4(), "tenant_id": tenant, "owner_run_id": run, "root_run_id": run,
-             "sensitive_pointers": "[]", "content_hash": hashlib.sha256(b"x").digest(),
-             "ciphertext": b"\x01"}  # fmt: skip
+             "sensitive_pointers": "[]", "ciphertext": b"\x01"}  # fmt: skip
     if table == "run_inputs":
         return {**claim, "pointer": ""}
     return {**claim, "kind": "output", "step_id": uuid.uuid4(), "iteration_key": "", "attempt": 1}
diff --git a/backend/tests/core/claims/test_service.py b/backend/tests/core/claims/test_service.py
index 5427d61..cfc2ca2 100644
--- a/backend/tests/core/claims/test_service.py
+++ b/backend/tests/core/claims/test_service.py
@@ -1,6 +1,7 @@
 # SPDX-License-Identifier: Apache-2.0
-"""The claim store (engine 2b spec §3.1, §3.3, §3.4): a claim is written once, idempotently and hash-checked; only its
-owner, or a run it was granted to, reads it; a run grants only what it owns or holds a grant on."""
+"""The claim store (engine 2b spec §3.1, §3.3, §3.4): a claim is written once, idempotently, a rewrite checked against
+the existing claim's decrypted value, never a digest of it (#28); only its owner, or a run it was granted to, reads it;
+a run grants only what it owns or holds a grant on."""
 
 import uuid
 from typing import Any
@@ -32,10 +33,10 @@ def claim(owner_run: uuid.UUID, value: Any = VALUE, sensitive: tuple[str, ...] =
     )
 
 
-async def write(sm: Any, tenant: uuid.UUID, new: service.NewClaim) -> None:
+async def write(sm: Any, tenant: uuid.UUID, new: service.NewClaim, cipher: ClaimCipher = CIPHER) -> None:
     async with sm() as s, s.begin():
         await tenant_scope(s, tenant)
-        await service.write_output(s, CIPHER, tenant, new, kind="output", step_id=uuid.UUID(int=1), iteration_key="",
+        await service.write_output(s, cipher, tenant, new, kind="output", step_id=uuid.UUID(int=1), iteration_key="",
                                    attempt=1)  # fmt: skip
 
 
@@ -70,6 +71,40 @@ async def test_writing_a_claim_again_is_a_no_op_and_another_value_under_its_id_i
     assert (await fetch(worker_sessionmaker, tenant, run, new.id)).value == VALUE
 
 
+async def test_no_digest_of_a_claims_value_is_kept(owner_sessionmaker) -> None:
+    """#28: an unkeyed SHA-256 of each claim's plaintext let anyone who reads the claim tables test guesses for a
+    low-entropy secret offline. The tables keep the ciphertext and nothing derived from the value."""
+    async with owner_sessionmaker() as s:
+        columns = (
+            await s.execute(
+                text(
+                    "select table_name, column_name from information_schema.columns "
+                    "where table_name in ('run_inputs', 'step_outputs') and column_name not in "
+                    "('id', 'tenant_id', 'owner_run_id', 'root_run_id', 'sensitive_pointers', 'ciphertext', "
+                    "'created_at', 'pointer', 'role', 'kind', 'step_id', 'iteration_key', 'attempt')"
+                )
+            )
+        ).all()
+    assert columns == []
+
+
+async def test_a_rewrite_is_checked_against_the_existing_claim_decrypted_across_a_key_rotation(
+    owner_sessionmaker, worker_sessionmaker
+) -> None:
+    """With no digest, a write that finds its id taken opens the existing claim, with the key version its ciphertext
+    names, and compares the canonical plaintext: the same value, its keys in another order, is a retry; another value
+    is refused, even after the tenant's key rotated."""
+    tenant, run = await a_tenant(owner_sessionmaker), uuid.uuid4()
+    new = claim(run)
+    await write(worker_sessionmaker, tenant, new)  # under key version 1
+    rotated = ClaimCipher(FixtureKeys(version=2))
+    reordered = service.NewClaim(**{**new.__dict__, "value": {"public": [1, 2], "token": "s3cret-value"}})
+    await write(worker_sessionmaker, tenant, reordered, rotated)
+    with pytest.raises(service.ClaimConflictError):
+        await write(worker_sessionmaker, tenant, service.NewClaim(**{**new.__dict__, "value": {"token": "x"}}), rotated)
+    assert (await fetch(worker_sessionmaker, tenant, run, new.id)).value == VALUE
+
+
 async def test_admission_writes_a_trigger_claim_the_run_then_reads(
     owner_sessionmaker, dispatch_sessionmaker, worker_sessionmaker
 ) -> None:
diff --git a/backend/tests/core/requests/test_schema.py b/backend/tests/core/requests/test_schema.py
index f1b9cc0..01ed65d 100644
--- a/backend/tests/core/requests/test_schema.py
+++ b/backend/tests/core/requests/test_schema.py
@@ -23,10 +23,10 @@ async def claim(
     claim_id = uuid.uuid4()
     await s.execute(
         text(
-            "insert into run_inputs (id, tenant_id, owner_run_id, root_run_id, sensitive_pointers, content_hash, "
-            "ciphertext, pointer, role) values (:id, :t, :o, :o, '[]', :h, :c, :p, :r)"
+            "insert into run_inputs (id, tenant_id, owner_run_id, root_run_id, sensitive_pointers, ciphertext, "
+            "pointer, role) values (:id, :t, :o, :o, '[]', :c, :p, :r)"
         ),
-        {"id": claim_id, "t": tenant, "o": owner, "h": b"\x00" * 32, "c": b"\x01", "p": pointer, "r": role},
+        {"id": claim_id, "t": tenant, "o": owner, "c": b"\x01", "p": pointer, "r": role},
     )
     return claim_id
 
diff --git a/docs/operations/deployment.md b/docs/operations/deployment.md
index eb6e052..7877035 100644
--- a/docs/operations/deployment.md
+++ b/docs/operations/deployment.md
@@ -181,6 +181,11 @@ types, task queues, timestamps, and a local activity's own bookkeeping (its type
   `run_secret_index` each run tree's known secrets, used to mask messages and rows. The worker's role reads and writes
   them; admission (the dispatch role) writes a run's input claims and seeds its index. No role updates or deletes a
   claim; tenant retention will (sub-project 2b-4).
+- **No digest of a claim's value is kept** (migration 0018, issue #28). Before it, each claim row held an unkeyed
+  SHA-256 of its plaintext, which let anyone who read the table test guesses for a short secret offline. The migration
+  drops the column from the live database, and a rewrite of a claim's id is checked by decrypting the existing claim.
+  A database backup taken before 0018 still holds those hashes: keep it under the same controls as a backup of the
+  data itself, and let it expire on your backup schedule rather than restoring it into a new environment.
 
 ## Worker health
```

### Task 3: A run request's idempotency digest, tenant-keyed

**Commit:** `c909822` (prototype `proto/2b2-v2`); the replay's tree was identical: yes.

**Create:** `backend/src/dewpoint/core/requests/__init__.py`, `backend/src/dewpoint/core/requests/digest.py`, `backend/tests/core/requests/test_digest.py`

**Modify:** `backend/src/dewpoint/apps/runs.py`, `backend/src/dewpoint/core/crypto/keys.py`, `backend/tests/apps/test_codec_keys.py`, `backend/tests/support/keys.py`

**What it does:**

Engine 2b spec §7.2: an HMAC over the canonical JSON of the source, the workflow, the mode and the input, with a key
derived from the tenant's data key (HKDF-SHA256, bound to the tenant and to this use), never an unkeyed hash of input
that may hold low-entropy secrets. `KeySource` gains `digest_key(tenant, version)`: `KeyringKeys` derives it from the
same read as the data key and caches it with it, so it expires with it; the fixture keys derive it too. `matches()`
recomputes a stored digest with the key version it was made with, so an exact retry is recognized after a rotation.


- [ ] **Step 1: its tests alone, before its code.** Run: `uv run pytest -n 4 tests/apps/test_codec_keys.py tests/core/requests/test_digest.py`. Replay result (exit 1), shortened:

```
_____________ ERROR collecting tests/core/requests/test_digest.py ______________
ImportError while importing test module '/private/tmp/claude-501/-Users-tmunzer-4-dev-mist-dewpoint/1e3145a1-199e-4b31-be1b-1e3bfd266be7/scratchpad/2b2-plan/replay/backend/tests/core/requests/test_digest.py'.
Hint: make sure your test modules/packages have valid Python names.
Traceback:
/opt/homebrew/Cellar/python@3.14/3.14.7/Frameworks/Python.framework/Versions/3.14/lib/python3.14/importlib/__init__.py:88: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
tests/core/requests/test_digest.py:9: in <module>
    from dewpoint.core.requests import digest as d
E   ModuleNotFoundError: No module named 'dewpoint.core.requests'
=========================== short test summary info ============================
ERROR tests/apps/test_codec_keys.py - ImportError while importing test module...
ERROR tests/core/requests/test_digest.py - ImportError while importing test m...
2 errors in 5.20s
```

- [ ] **Step 2: its code, then the same tests.** Replay result (exit 0), shortened:

```
..........                                                               [100%]
10 passed in 10.74s
```

- [ ] **Step 3: commit.** `git cherry-pick --no-commit c909822 && git commit -C c909822`

The diff:

```diff
diff --git a/backend/src/dewpoint/apps/runs.py b/backend/src/dewpoint/apps/runs.py
index 6ffc8f9..bd524a6 100644
--- a/backend/src/dewpoint/apps/runs.py
+++ b/backend/src/dewpoint/apps/runs.py
@@ -285,6 +285,9 @@ class _NoKeys:
     async def get(self, tenant_id: str, version: int) -> Any:
         raise NotAdmissibleError(["This process can't seal the run's input: it has no keys."])
 
+    async def digest_key(self, tenant_id: str, version: int | None) -> Any:
+        raise NotAdmissibleError(["This process can't seal the run's input: it has no keys."])
+
 
 _NO_KEYS = _NoKeys()
 
diff --git a/backend/src/dewpoint/core/crypto/keys.py b/backend/src/dewpoint/core/crypto/keys.py
index 32f0343..bdb4a98 100644
--- a/backend/src/dewpoint/core/crypto/keys.py
+++ b/backend/src/dewpoint/core/crypto/keys.py
@@ -8,13 +8,22 @@ from collections import OrderedDict
 from collections.abc import Callable
 from typing import Protocol
 
+from cryptography.hazmat.primitives import hashes
 from cryptography.hazmat.primitives.ciphers.aead import AESGCM
+from cryptography.hazmat.primitives.kdf.hkdf import HKDF
 from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
 
 from dewpoint.core.crypto.keyring import Keyring
 from dewpoint.core.db import tenant_scope
 
 
+def digest_key_of(raw: bytes, tenant_id: str) -> bytes:
+    """The key a tenant's run requests are digested with (engine 2b spec §7.2), derived from its data key `raw`: never
+    the data key itself, and bound to the tenant and to this one use."""
+    info = f"dewpoint|{tenant_id}|request-digest".encode()
+    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=info).derive(raw)
+
+
 class KeySource(Protocol):
     """A tenant's data keys, by version. Read-only: neither the codec nor the claim cipher creates a key (a tenant
     gets one when it's created)."""
@@ -23,6 +32,11 @@ class KeySource(Protocol):
 
     async def get(self, tenant_id: str, version: int) -> AESGCM: ...
 
+    async def digest_key(self, tenant_id: str, version: int | None) -> tuple[int, bytes]:
+        """The tenant's request-digest key derived from its data key of `version` (its active one when None), with
+        that version."""
+        ...
+
 
 class KeyringKeys:
     """Tenants' data keys from the keyring, read-only, cached unwrapped in this process and nowhere else: at most
@@ -43,28 +57,34 @@ class KeyringKeys:
     ) -> None:
         self._sessionmaker, self._keyring = sessionmaker, keyring
         self._size, self._ttl_s, self._clock = size, ttl_s, clock
-        self._cache: OrderedDict[tuple[str, int | None], tuple[float, int, AESGCM]] = OrderedDict()
+        # Each entry: when it expires, the key's version, the data key, and the request-digest key derived from it.
+        self._cache: OrderedDict[tuple[str, int | None], tuple[float, int, AESGCM, bytes]] = OrderedDict()
 
     async def active(self, tenant_id: str) -> tuple[int, AESGCM]:
-        return await self._read(tenant_id, None)
+        _, found, key, _ = await self._read(tenant_id, None)
+        return found, key
 
     async def get(self, tenant_id: str, version: int) -> AESGCM:
-        return (await self._read(tenant_id, version))[1]
+        return (await self._read(tenant_id, version))[2]
+
+    async def digest_key(self, tenant_id: str, version: int | None) -> tuple[int, bytes]:
+        _, found, _, derived = await self._read(tenant_id, version)
+        return found, derived
 
-    async def _read(self, tenant_id: str, version: int | None) -> tuple[int, AESGCM]:
+    async def _read(self, tenant_id: str, version: int | None) -> tuple[float, int, AESGCM, bytes]:
         now = self._clock()
         hit = self._cache.get((tenant_id, version))
         if hit is not None and hit[0] > now:
             self._cache.move_to_end((tenant_id, version))
-            return hit[1], hit[2]
+            return hit
         tenant = uuid.UUID(tenant_id)
         async with self._sessionmaker() as s, s.begin():
             await tenant_scope(s, tenant)
             found, raw = await self._keyring.read_dek(s, tenant, version)
-        entry = (now + self._ttl_s, found, AESGCM(raw))
+        entry = (now + self._ttl_s, found, AESGCM(raw), digest_key_of(raw, tenant_id))
         for k in {(tenant_id, version), (tenant_id, found)}:
             self._cache[k] = entry
             self._cache.move_to_end(k)
         while len(self._cache) > self._size:
             self._cache.popitem(last=False)
-        return found, entry[2]
+        return entry
diff --git a/backend/src/dewpoint/core/requests/__init__.py b/backend/src/dewpoint/core/requests/__init__.py
new file mode 100644
index 0000000..9881313
--- /dev/null
+++ b/backend/src/dewpoint/core/requests/__init__.py
@@ -0,0 +1 @@
+# SPDX-License-Identifier: Apache-2.0
diff --git a/backend/src/dewpoint/core/requests/digest.py b/backend/src/dewpoint/core/requests/digest.py
new file mode 100644
index 0000000..991c7f7
--- /dev/null
+++ b/backend/src/dewpoint/core/requests/digest.py
@@ -0,0 +1,45 @@
+# SPDX-License-Identifier: Apache-2.0
+"""A run request's idempotency digest (engine 2b spec §7.2): an HMAC with the tenant's request-digest key, derived from
+its data key, over the canonical JSON of the source, the workflow, the mode and the input. Never an unkeyed hash of
+input that may hold low-entropy secrets. A request stores the key version it was digested with, so an exact retry is
+recognized whatever has changed since, a key rotation included."""
+
+import hashlib
+import hmac
+import json
+import uuid
+from typing import Any
+
+from dewpoint.core.crypto.keys import KeySource
+
+
+def canonical(*, source: str, workflow_id: uuid.UUID, mode: str, input: Any) -> bytes:
+    """Sorted keys, no whitespace, UTF-8, no NaN: equal requests always give equal bytes."""
+    value = {"source": source, "workflow_id": str(workflow_id), "mode": mode, "input": input}
+    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
+
+
+async def digest(
+    keys: KeySource,
+    tenant_id: str,
+    *,
+    source: str,
+    workflow_id: uuid.UUID,
+    mode: str,
+    input: Any,
+    version: int | None = None,
+) -> tuple[int, bytes]:
+    """The request's digest with the tenant's key of `version` (its active one when None), and that version."""
+    found, key = await keys.digest_key(tenant_id, version)
+    message = canonical(source=source, workflow_id=workflow_id, mode=mode, input=input)
+    return found, hmac.new(key, message, hashlib.sha256).digest()
+
+
+async def matches(
+    keys: KeySource, tenant_id: str, stored: bytes, version: int, *, source: str, workflow_id: uuid.UUID, mode: str,
+    input: Any,
+) -> bool:  # fmt: skip
+    """Whether a request is the one `stored` was computed for, with the key version it was computed with."""
+    _, fresh = await digest(keys, tenant_id, source=source, workflow_id=workflow_id, mode=mode, input=input,
+                            version=version)  # fmt: skip
+    return hmac.compare_digest(fresh, stored)
diff --git a/backend/tests/apps/test_codec_keys.py b/backend/tests/apps/test_codec_keys.py
index f682922..a705854 100644
--- a/backend/tests/apps/test_codec_keys.py
+++ b/backend/tests/apps/test_codec_keys.py
@@ -12,6 +12,7 @@ from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
 from dewpoint.apps.codec import KeyringKeys, TenantCodec
 from dewpoint.core.crypto.kek import Kek, KekSet
 from dewpoint.core.crypto.keyring import Keyring, NoKeyError
+from dewpoint.core.crypto.keys import digest_key_of
 from dewpoint.core.db import tenant_scope
 from tests.apps.test_codec import payload, workflow
 
@@ -122,3 +123,20 @@ async def test_an_expired_key_is_never_used_while_the_database_doesnt_answer(
         await keys.active(str(tenant))
     with pytest.raises(ConnectionRefusedError):
         await keys.get(str(tenant), 1)
+
+
+async def test_a_tenants_digest_key_is_derived_from_its_data_key_and_cached_with_it(
+    owner_sessionmaker, worker_sessionmaker
+) -> None:
+    """The request digest's key (engine 2b spec §7.2) comes from the same read as the data key, expires with it, and is
+    derived from it, never the data key itself."""
+    tenant, now = uuid.uuid4(), [0.0]
+    await with_key(owner_sessionmaker, tenant)
+    counted = Counted(worker_sessionmaker)
+    keys = KeyringKeys(counted, KEYRING, ttl_s=60, clock=lambda: now[0])  # type: ignore[arg-type]
+    version, key = await keys.digest_key(str(tenant), None)
+    assert await keys.digest_key(str(tenant), 1) == (1, key) and (await keys.active(str(tenant)))[0] == version == 1
+    assert counted.opened == 1
+    async with owner_sessionmaker() as s, s.begin():
+        _, raw = await KEYRING.read_dek(s, tenant)
+    assert key == digest_key_of(raw, str(tenant)) and key != raw and len(key) == 32
diff --git a/backend/tests/core/requests/test_digest.py b/backend/tests/core/requests/test_digest.py
new file mode 100644
index 0000000..565cf9a
--- /dev/null
+++ b/backend/tests/core/requests/test_digest.py
@@ -0,0 +1,41 @@
+# SPDX-License-Identifier: Apache-2.0
+"""A run request's idempotency digest (engine 2b spec §7.2): an HMAC, with a key derived from the tenant's data key,
+over the canonical JSON of the source, workflow, mode and input, stored with its key version. Never an unkeyed hash of
+input that may hold low-entropy secrets: only a holder of the tenant's key can test a guess."""
+
+import hashlib
+import uuid
+
+from dewpoint.core.requests import digest as d
+from tests.support.keys import FixtureKeys
+
+TENANT, OTHER = str(uuid.UUID(int=1)), str(uuid.UUID(int=2))
+REQUEST = {"source": "manual", "workflow_id": uuid.UUID(int=3), "mode": "live", "input": {"pin": "1234", "site": "a"}}
+
+
+async def test_the_same_request_digests_the_same_and_any_change_differently() -> None:
+    keys = FixtureKeys()
+    version, first = await d.digest(keys, TENANT, **REQUEST)
+    assert version == 1 and len(first) == 32
+    reordered = {**REQUEST, "input": {"site": "a", "pin": "1234"}}
+    assert (await d.digest(keys, TENANT, **reordered))[1] == first  # canonical: key order doesn't count
+    for change in ({"source": "dev"}, {"mode": "simulate"}, {"workflow_id": uuid.UUID(int=4)},
+                   {"input": {"pin": "1235", "site": "a"}}):  # fmt: skip
+        assert (await d.digest(keys, TENANT, **{**REQUEST, **change}))[1] != first
+
+
+async def test_a_digest_is_keyed_by_the_tenant_never_an_unkeyed_hash() -> None:
+    keys = FixtureKeys()
+    _, mine = await d.digest(keys, TENANT, **REQUEST)
+    assert mine != (await d.digest(keys, OTHER, **REQUEST))[1]
+    assert mine != hashlib.sha256(d.canonical(**REQUEST)).digest()
+
+
+async def test_a_stored_digest_is_compared_with_its_own_key_version_after_a_rotation() -> None:
+    """An exact retry is found whatever has changed since, a key rotation included (§7.2, step 2)."""
+    _, stored = await d.digest(FixtureKeys(version=1), TENANT, **REQUEST)
+    rotated = FixtureKeys(version=2)
+    version, fresh = await d.digest(rotated, TENANT, **REQUEST)
+    assert version == 2 and fresh != stored
+    assert await d.matches(rotated, TENANT, stored, 1, **REQUEST)
+    assert not await d.matches(rotated, TENANT, stored, 1, **{**REQUEST, "mode": "simulate"})
diff --git a/backend/tests/support/keys.py b/backend/tests/support/keys.py
index da032cf..6786cb9 100644
--- a/backend/tests/support/keys.py
+++ b/backend/tests/support/keys.py
@@ -13,6 +13,7 @@ from temporalio.api.common.v1 import Payload
 from temporalio.converter import WorkflowSerializationContext
 
 from dewpoint.apps.codec import TENANT, TenantCodec, data_converter
+from dewpoint.core.crypto.keys import digest_key_of
 from dewpoint.engine.runtime.ids import run_workflow_id
 
 
@@ -27,9 +28,16 @@ class FixtureKeys:
         return self.version, await self.get(tenant_id, self.version)
 
     async def get(self, tenant_id: str, version: int) -> AESGCM:
+        return AESGCM(self._raw(tenant_id, version))
+
+    async def digest_key(self, tenant_id: str, version: int | None) -> tuple[int, bytes]:
+        found = self.version if version is None else version
+        return found, digest_key_of(self._raw(tenant_id, found), tenant_id)
+
+    def _raw(self, tenant_id: str, version: int) -> bytes:
         if tenant_id in self.missing:
             raise LookupError(f"no key for tenant {tenant_id}")
-        return AESGCM(hashlib.sha256(f"dewpoint-fixture-key|{tenant_id}|{version}".encode()).digest())
+        return hashlib.sha256(f"dewpoint-fixture-key|{tenant_id}|{version}".encode()).digest()
 
 
 # Every test server, recorder and replayer of Dewpoint's workflows uses it, as every process uses the keyring's.
```

### Task 4: A request's trigger envelope, stored beside its claims and never served as one

**Commit:** `33da4ff` (prototype `proto/2b2-v2`); the replay's tree was identical: yes.

**Create:** `backend/tests/core/requests/test_envelope.py`

**Modify:** `backend/src/dewpoint/core/claims/service.py`

**What it does:**

Revision 7 (§7.1), the owner's ruling: `write_envelope` stores a request's trigger envelope in `run_inputs`, encrypted
as a claim is, owned by the request, with the role `envelope` and no pointer. Claim lookup excludes envelopes, so
`fetch` refuses a handle that names one (`claim_unavailable`), even to its owner, and `grant`, with the closure a grant
walks, grants nothing that reaches one. `read_envelope` is the only way in: it follows the request's `envelope_id`,
in the caller's tenant, and nothing else. Tests attempt a handle read and a grant; both fail without the boundary.


- [ ] **Step 1: its tests alone, before its code.** Run: `uv run pytest -n 4 tests/core/requests/test_envelope.py`. Replay result (exit 1), shortened:

```
§14; revision 7)
/private/tmp/claude-501/-Users-tmunzer-4-dev-mist-dewpoint/1e3145a1-199e-4b31-be1b-1e3bfd266be7/scratchpad/2b2-plan/replay/backend/tests/core/requests/test_envelope.py:28: AttributeError: module 'dewpoint.core.claims.service' has no attribute 'write_envelope'
[gw0] darwin -- Python 3.14.7 /private/tmp/claude-501/-Users-tmunzer-4-dev-mist-dewpoint/1e3145a1-199e-4b31-be1b-1e3bfd266be7/scratchpad/2b2-plan/proto/backend/.venv/bin/python
E   AttributeError: module 'dewpoint.core.claims.service' has no attribute 'write_envelope'
---------------------------- Captured stderr setup -----------------------------
security, not by bypassing it (engine 2b spec §6.3, plan 2b-1a's review)
§14; revision 7)
/private/tmp/claude-501/-Users-tmunzer-4-dev-mist-dewpoint/1e3145a1-199e-4b31-be1b-1e3bfd266be7/scratchpad/2b2-plan/replay/backend/tests/core/requests/test_envelope.py:28: AttributeError: module 'dewpoint.core.claims.service' has no attribute 'write_envelope'
=========================== short test summary info ============================
FAILED tests/core/requests/test_envelope.py::test_the_envelope_is_read_through_its_request_and_tenant_only
FAILED tests/core/requests/test_envelope.py::test_the_database_holds_no_envelope_in_plain_text
FAILED tests/core/requests/test_envelope.py::test_a_grant_that_reaches_an_envelope_grants_nothing
FAILED tests/core/requests/test_envelope.py::test_a_handle_that_names_an_envelope_is_refused_even_to_its_owner
4 failed in 10.51s
```

- [ ] **Step 2: its code, then the same tests.** Replay result (exit 0), shortened:

```
....                                                                     [100%]
4 passed in 10.45s
```

- [ ] **Step 3: commit.** `git cherry-pick --no-commit 33da4ff && git commit -C 33da4ff`

The diff:

```diff
diff --git a/backend/src/dewpoint/core/claims/service.py b/backend/src/dewpoint/core/claims/service.py
index 0e30307..4b79f4b 100644
--- a/backend/src/dewpoint/core/claims/service.py
+++ b/backend/src/dewpoint/core/claims/service.py
@@ -2,14 +2,18 @@
 """The claim store (engine 2b spec §3.1, §3.3, §3.4).
 
 A claim is written once. Its id is derived by whoever makes it, so a retried write writes the same row; a row that
-already exists must hold the same content (its hash), or the write is refused and nothing changes. Only the claim's
+already exists must hold the same value, which is checked by decrypting it, never by a digest of it (#28), or the write
+is refused and nothing changes. Only the claim's
 owner, the run that produced it, or a run it was granted to reads it; a run grants only what it owns or holds a grant
 on. Every refusal looks the same from outside (`ClaimUnavailableError`): a claim that doesn't exist, belongs to another
 tenant (row-level security hides it) or to a run that may not read it.
 
 The caller opens the transaction under the tenant's scope (`tenant_scope`), and checks that the tenant is the one the
 activity's server-built workflow id names (§3.3). Pointers and nested handles are the engine's (`engine.handles`):
-this module stores and returns whole values."""
+this module stores and returns whole values.
+
+A request's trigger envelope sits in `run_inputs` too (revision 7, §7.1), and is never a claim: no claim read and no
+grant ever serves it, and only `read_envelope`, following its request, opens it."""
 
 import json
 import uuid
@@ -22,6 +26,7 @@ from sqlalchemy.ext.asyncio import AsyncSession
 
 from dewpoint.core.claims.cipher import ClaimCipher, ClaimUnreadableError
 from dewpoint.core.models.claims import ClaimGrant, InputClaim, OutputClaim
+from dewpoint.core.models.requests import RunRequest
 
 CLAIM_UNAVAILABLE = "claim_unavailable"
 
@@ -30,6 +35,11 @@ class ClaimUnavailableError(Exception):
     """A claim this run may not read, or that doesn't exist. The message is fixed: it never quotes a value."""
 
 
+class EnvelopeUnavailableError(Exception):
+    """A request's trigger envelope that isn't there for this tenant: no such request, a refused one, or one retention
+    has removed. The message is fixed."""
+
+
 class ClaimConflictError(Exception):
     """A claim written again under its id with other content: nothing was written. A bug, never a value's fault."""
 
@@ -102,12 +112,18 @@ async def write_output(
 
 
 async def _row(s: AsyncSession, claim_id: uuid.UUID) -> Any:
-    for model in (InputClaim, OutputClaim):
-        found = (
-            await s.execute(
-                select(model.owner_run_id, model.sensitive_pointers, model.ciphertext).where(model.id == claim_id)
-            )
-        ).first()
+    """A claim's row, never an envelope's: a handle that names an envelope is refused as any unreadable claim is, and
+    a grant that reaches one grants nothing (revision 7)."""
+    claims = (
+        select(InputClaim.owner_run_id, InputClaim.sensitive_pointers, InputClaim.ciphertext).where(
+            InputClaim.id == claim_id, InputClaim.role == "claim"
+        ),
+        select(OutputClaim.owner_run_id, OutputClaim.sensitive_pointers, OutputClaim.ciphertext).where(
+            OutputClaim.id == claim_id
+        ),
+    )
+    for query in claims:
+        found = (await s.execute(query)).first()
         if found is not None:
             return found
     return None
@@ -155,3 +171,40 @@ async def grant(
             for c in claim_ids
         ]
         await s.execute(insert(ClaimGrant).values(rows).on_conflict_do_nothing(index_elements=["claim_id", "run_id"]))
+
+
+async def write_envelope(
+    s: AsyncSession, cipher: ClaimCipher, tenant_id: uuid.UUID, *, request_id: uuid.UUID, envelope: Any
+) -> uuid.UUID:
+    """A request's trigger envelope, encrypted as a claim is and owned by the request (whose id is its run's), and its
+    id, for the request row. It holds no tainted pointer: every sensitive value is a claim it holds by handle."""
+    envelope_id = uuid.uuid4()
+    row = {
+        "id": envelope_id,
+        "tenant_id": tenant_id,
+        "owner_run_id": request_id,
+        "root_run_id": request_id,
+        "sensitive_pointers": [],
+        "ciphertext": await cipher.seal(str(tenant_id), str(envelope_id), _plain(envelope)),
+        "role": "envelope",
+        "pointer": None,
+    }
+    await s.execute(insert(InputClaim).values(row))
+    return envelope_id
+
+
+async def read_envelope(s: AsyncSession, cipher: ClaimCipher, tenant_id: uuid.UUID, *, request_id: uuid.UUID) -> Any:
+    """A request's trigger envelope: the one its row names and it owns, in the caller's tenant, and nothing else."""
+    found = (
+        await s.execute(
+            select(InputClaim.id, InputClaim.ciphertext)
+            .join(RunRequest, RunRequest.envelope_id == InputClaim.id)
+            .where(RunRequest.id == request_id, InputClaim.owner_run_id == request_id, InputClaim.role == "envelope")
+        )
+    ).first()
+    if found is None:
+        raise EnvelopeUnavailableError("A request whose trigger envelope isn't there.")
+    try:
+        return json.loads(await cipher.open(str(tenant_id), str(found.id), found.ciphertext))
+    except ClaimUnreadableError as e:
+        raise EnvelopeUnavailableError("A trigger envelope that doesn't open under its tenant.") from e
diff --git a/backend/tests/core/requests/test_envelope.py b/backend/tests/core/requests/test_envelope.py
new file mode 100644
index 0000000..1f701bc
--- /dev/null
+++ b/backend/tests/core/requests/test_envelope.py
@@ -0,0 +1,85 @@
+# SPDX-License-Identifier: Apache-2.0
+"""A request's trigger envelope (engine 2b spec revision 7, §7.1): stored encrypted beside its claims, never served as
+one. A handle that names it is refused, a grant that reaches it grants nothing, and it's read only through its own
+reader, scoped to its tenant and its request."""
+
+import uuid
+from typing import Any
+
+import pytest
+from sqlalchemy import text
+
+from dewpoint.core.claims import service
+from dewpoint.core.claims.cipher import ClaimCipher
+from dewpoint.core.db import tenant_scope
+from tests.support.keys import FixtureKeys
+from tests.support.workflows import seed_workflow
+
+CIPHER = ClaimCipher(FixtureKeys())
+ENVELOPE = {"site": "a", "token": {"$claim": str(uuid.UUID(int=9))}}
+
+
+async def admitted(owner: Any, dispatch: Any) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
+    """A queued request with its envelope, written as admission writes them: the tenant, the request, the envelope."""
+    tenant, wf, version = await seed_workflow(owner)
+    request = uuid.uuid4()
+    async with dispatch() as s, s.begin():
+        await tenant_scope(s, tenant)
+        envelope = await service.write_envelope(s, CIPHER, tenant, request_id=request, envelope=ENVELOPE)
+        await s.execute(
+            text(
+                "insert into run_requests (id, tenant_id, workflow_id, workflow_version_id, source, mode, "
+                "idempotency_key, digest, digest_key_version, status, envelope_id) "
+                "values (:r, :t, :w, :v, 'manual', 'live', 'k', :d, 1, 'queued', :e)"
+            ),
+            {"r": request, "t": tenant, "w": wf, "v": version, "d": b"\x00" * 32, "e": envelope},
+        )
+    return tenant, request, envelope
+
+
+async def test_a_handle_that_names_an_envelope_is_refused_even_to_its_owner(
+    owner_sessionmaker, dispatch_sessionmaker, worker_sessionmaker
+) -> None:
+    tenant, request, envelope = await admitted(owner_sessionmaker, dispatch_sessionmaker)
+    with pytest.raises(service.ClaimUnavailableError):
+        async with worker_sessionmaker() as s, s.begin():
+            await tenant_scope(s, tenant)
+            await service.fetch(s, CIPHER, tenant, run_id=request, claim_id=envelope)
+
+
+async def test_a_grant_that_reaches_an_envelope_grants_nothing(
+    owner_sessionmaker, dispatch_sessionmaker, worker_sessionmaker
+) -> None:
+    tenant, request, envelope = await admitted(owner_sessionmaker, dispatch_sessionmaker)
+    child = uuid.uuid4()
+    with pytest.raises(service.ClaimUnavailableError):
+        async with worker_sessionmaker() as s, s.begin():
+            await tenant_scope(s, tenant)
+            await service.grant(s, tenant, granted_by=request, to=child, claim_ids=[envelope], root_run_id=request)
+    async with owner_sessionmaker() as s:
+        assert (await s.execute(text("select count(*) from claim_grants"))).scalar_one() == 0
+
+
+async def test_the_envelope_is_read_through_its_request_and_tenant_only(
+    owner_sessionmaker, dispatch_sessionmaker
+) -> None:
+    tenant, request, _ = await admitted(owner_sessionmaker, dispatch_sessionmaker)
+    other, _, _ = await seed_workflow(owner_sessionmaker, name="Other")
+    async with dispatch_sessionmaker() as s, s.begin():
+        await tenant_scope(s, tenant)
+        assert await service.read_envelope(s, CIPHER, tenant, request_id=request) == ENVELOPE
+        with pytest.raises(service.EnvelopeUnavailableError):  # no such request in this tenant
+            await service.read_envelope(s, CIPHER, tenant, request_id=uuid.uuid4())
+    with pytest.raises(service.EnvelopeUnavailableError):
+        async with dispatch_sessionmaker() as s, s.begin():
+            await tenant_scope(s, other)
+            await service.read_envelope(s, CIPHER, other, request_id=request)
+
+
+async def test_the_database_holds_no_envelope_in_plain_text(owner_sessionmaker, dispatch_sessionmaker) -> None:
+    _, _, envelope = await admitted(owner_sessionmaker, dispatch_sessionmaker)
+    async with owner_sessionmaker() as s:
+        row = (
+            await s.execute(text("select ciphertext, pointer, role from run_inputs where id = :e"), {"e": envelope})
+        ).one()
+    assert b"site" not in row.ciphertext and (row.pointer, row.role) == (None, "envelope")
```

### Task 5: `admit_request` freezes a run request in its caller's transaction

**Commit:** `c37e6cc` (prototype `proto/2b2-v2`); the replay's tree was identical: yes.

**Create:** `backend/src/dewpoint/apps/admission.py`, `backend/tests/apps/test_admission.py`

**Modify:** `backend/src/dewpoint/apps/inputs.py`, `backend/tests/apps/test_admission_gate.py`

**What it does:**

Engine 2b spec §7.2 and revision 7, in order:
- the idempotency key first: an existing request is compared with its own stored key version, and an exact retry
  returns it as it is now, whatever changed since (a key rotation, a disabled workflow); another request under the key
  is `IdempotencyConflictError`;
- for a new key, the mutable checks: the tenant isn't erasing; the gate, for an interactive source; the workflow's
  admission lock, enabled, its active version; the ABI against the current-build record the dispatcher keeps, failing
  closed when it's missing or older than two minutes (the owner's ruling); the closure executable under the lifecycle
  locks; the input schema, refused with locations and rules only;
- then, in one savepoint, the trigger claimed under the request's id (the run's), the secret index seeded, the
  envelope stored, the request inserted `ON CONFLICT DO NOTHING` and audited (`run.request`): a concurrent insert that
  won the key rolls this call back, claims and envelope included, and the winner is compared instead.

A durable source's refusal is kept as a `refused` request with its reason and no envelope; an interactive one's is
raised (`AdmissionRefusedError`), leaving nothing. Reason codes: `tenant_erasing`, `production_runs_disabled`,
`environment_not_recorded`, `workflow_disabled`, `not_active`, `no_current_build`, `version_unusable`,
`node_type_retired`, `cel_profile_retired`, `input_invalid`, `secret_index_limit`. `InputRefusedError` carries its
code.


- [ ] **Step 1: its tests alone, before its code.** Run: `uv run pytest -n 4 tests/apps/test_admission.py tests/apps/test_admission_gate.py`. Replay result (exit 1), shortened:

```
______________ ERROR collecting tests/apps/test_admission_gate.py ______________
ImportError while importing test module '/private/tmp/claude-501/-Users-tmunzer-4-dev-mist-dewpoint/1e3145a1-199e-4b31-be1b-1e3bfd266be7/scratchpad/2b2-plan/replay/backend/tests/apps/test_admission_gate.py'.
Hint: make sure your test modules/packages have valid Python names.
Traceback:
/opt/homebrew/Cellar/python@3.14/3.14.7/Frameworks/Python.framework/Versions/3.14/lib/python3.14/importlib/__init__.py:88: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
tests/apps/test_admission_gate.py:11: in <module>
    from dewpoint.apps import admission
E   ImportError: cannot import name 'admission' from 'dewpoint.apps' (/private/tmp/claude-501/-Users-tmunzer-4-dev-mist-dewpoint/1e3145a1-199e-4b31-be1b-1e3bfd266be7/scratchpad/2b2-plan/replay/backend/src/dewpoint/apps/__init__.py)
=========================== short test summary info ============================
ERROR tests/apps/test_admission.py - ImportError while importing test module ...
ERROR tests/apps/test_admission_gate.py - ImportError while importing test mo...
2 errors in 5.27s
```

- [ ] **Step 2: its code, then the same tests.** Replay result (exit 0), shortened:

```
......................                                                   [100%]
22 passed in 13.54s
```

- [ ] **Step 3: commit.** `git cherry-pick --no-commit c37e6cc && git commit -C c37e6cc`

The diff:

```diff
diff --git a/backend/src/dewpoint/apps/admission.py b/backend/src/dewpoint/apps/admission.py
new file mode 100644
index 0000000..e29d37c
--- /dev/null
+++ b/backend/src/dewpoint/apps/admission.py
@@ -0,0 +1,271 @@
+# SPDX-License-Identifier: Apache-2.0
+"""Admission (engine 2b spec §7.2; revision 7): a run request frozen inside its caller's READ COMMITTED transaction,
+which it never commits. The caller has authorized it (`run.start` for an interactive source; a durable source by its
+binding or schedule) and commits it with whatever else it writes.
+
+In §7.2's order:
+1. the idempotency key is looked up first: an existing request is compared, with its own stored key version, and an
+   exact retry returns it as it is now, whatever changed since (a rotation, the gate, the active version, a disable);
+   another request under the key is a conflict;
+2. a new key passes the mutable checks: the tenant isn't erasing; the gate, for an interactive source; the workflow's
+   admission lock, enabled, its active version, the current build's ABI (as the dispatcher last recorded it: a missing
+   or stale record fails closed), the closure executable under the lifecycle locks; the input schema;
+3. it's digested with the tenant's active key version, its trigger claimed, the secret index seeded, its envelope
+   stored and the request inserted, `ON CONFLICT DO NOTHING`, with one audit entry, all in one savepoint: a concurrent
+   insert that won the key rolls this call back, claims and envelope included, and the winner is compared instead.
+
+A durable source's refusal is kept as a `refused` request with its reason, never lost; an interactive one's is raised.
+The request's id is its run's, once it starts: its claims and envelope are owned by it from the start."""
+
+import uuid
+from dataclasses import dataclass
+from datetime import timedelta
+from typing import Any
+
+from sqlalchemy import func, select
+from sqlalchemy.dialects.postgresql import insert
+from sqlalchemy.ext.asyncio import AsyncSession
+
+from dewpoint.apps.inputs import InputRefusedError, claim_input
+from dewpoint.apps.workflow_ops import abi_reasons
+from dewpoint.core.audit import service as audit
+from dewpoint.core.claims import service as claims
+from dewpoint.core.claims.cipher import ClaimCipher
+from dewpoint.core.crypto.keys import KeySource
+from dewpoint.core.db import tenant_scope
+from dewpoint.core.models.requests import CurrentBuild, RunRequest
+from dewpoint.core.models.tenancy import Tenant
+from dewpoint.core.models.workflows import WorkflowVersion
+from dewpoint.core.platform.service import NOT_RECORDED, PRODUCTION, recorded
+from dewpoint.core.plugins import lifecycle
+from dewpoint.core.requests import digest as digests
+from dewpoint.core.workflows.service import lock_for_admission, other_abi
+from dewpoint.engine.runtime.activities import LIVE, SIMULATE
+
+INTERACTIVE = ("manual", "rerun", "dev")  # refused while the gate is off; a refusal is raised
+DURABLE = ("schedule", "webhook")  # recorded while the gate is off (§2.5); a refusal is a `refused` request
+# A current-build record older than this is no record (the owner's ruling). Aged by the statement's time, never the
+# transaction's start: a caller that admits several requests in one long transaction sees it go stale.
+BUILD_STALE = timedelta(minutes=2)
+
+TENANT_ERASING = "tenant_erasing"
+PRODUCTION_RUNS_DISABLED = "production_runs_disabled"
+ENVIRONMENT_NOT_RECORDED = "environment_not_recorded"
+WORKFLOW_DISABLED = "workflow_disabled"
+NOT_ACTIVE = "not_active"
+NO_CURRENT_BUILD = "no_current_build"
+VERSION_UNUSABLE = "version_unusable"
+NODE_TYPE_RETIRED = "node_type_retired"
+CEL_PROFILE_RETIRED = "cel_profile_retired"
+
+GATE_OFF = (
+    "Production runs are off in this deployment: no run starts in a production deployment until its gate lifts "
+    "(engine 2b spec §2)."
+)
+NO_BUILD = (
+    "No current build has been recorded lately, so this run's engine ABI can't be checked: the dispatcher records "
+    "it while it runs."
+)
+
+
+class AdmissionRefusedError(Exception):
+    """An interactive request admission refused: its `reason` code (§9) and what to tell the caller."""
+
+    def __init__(self, reason: str, messages: list[str]) -> None:
+        super().__init__("; ".join(messages))
+        self.reason, self.messages = reason, messages
+
+
+class IdempotencyConflictError(Exception):
+    """Another request under the same idempotency key (409 `idempotency_conflict`)."""
+
+
+class WorkflowNotFoundError(LookupError):
+    """No such workflow in the caller's tenant."""
+
+
+@dataclass(frozen=True)
+class Admitted:
+    request: RunRequest
+    new: bool  # False: an exact retry, the frozen request as it is now
+
+
+class _Refused(Exception):
+    def __init__(self, reason: str, messages: list[str], version_id: uuid.UUID | None = None) -> None:
+        self.reason, self.messages, self.version_id = reason, messages, version_id
+
+
+async def _before_insert() -> None:
+    """Runs between a new request's claims and its insert. A no-op; the race tests commit a competing request here."""
+
+
+async def admit_request(
+    s: AsyncSession,
+    keys: KeySource,
+    *,
+    tenant_id: uuid.UUID,
+    workflow_id: uuid.UUID,
+    source: str,
+    actor_id: uuid.UUID | None,
+    mode: str,
+    idempotency_key: str,
+    input: dict[str, Any],
+) -> Admitted:
+    """The request under `idempotency_key`: an exact retry's, or a new one, frozen. Raises IdempotencyConflictError,
+    WorkflowNotFoundError, or, for an interactive source, AdmissionRefusedError."""
+    if source not in INTERACTIVE + DURABLE or mode not in (LIVE, SIMULATE):
+        raise ValueError(f"no such source or mode: {source}, {mode}")
+    await lifecycle.assert_read_committed(s)
+    await tenant_scope(s, tenant_id)
+    fields: dict[str, Any] = {"source": source, "workflow_id": workflow_id, "mode": mode, "input": input}
+    existing = await _by_key(s, idempotency_key)
+    if existing is not None:
+        return await _retry(keys, tenant_id, existing, fields)
+    request_id = uuid.uuid4()
+    savepoint = await s.begin_nested()
+    try:
+        version_id, envelope_id = await _frozen(s, keys, tenant_id, request_id, fields)
+    except _Refused as refused:
+        await savepoint.rollback()
+        if source in INTERACTIVE:
+            raise AdmissionRefusedError(refused.reason, refused.messages) from None
+        return await _insert(s, keys, tenant_id, request_id, actor_id, idempotency_key, fields, None, None, refused)
+    await _before_insert()
+    admitted = await _insert(s, keys, tenant_id, request_id, actor_id, idempotency_key, fields, version_id, envelope_id)
+    if admitted.new:
+        await savepoint.commit()
+    else:
+        await savepoint.rollback()  # another transaction won the key: this call's claims and envelope go with it
+        return await _retry(keys, tenant_id, await _winner(s, idempotency_key), fields)
+    return admitted
+
+
+async def _by_key(s: AsyncSession, idempotency_key: str) -> RunRequest | None:
+    query = (
+        select(RunRequest)
+        .where(RunRequest.idempotency_key == idempotency_key)
+        .execution_options(populate_existing=True)
+    )
+    return (await s.execute(query)).scalar_one_or_none()
+
+
+async def _winner(s: AsyncSession, idempotency_key: str) -> RunRequest:
+    """The request a concurrent transaction froze under the key, which this one's insert just ran into."""
+    winner = await _by_key(s, idempotency_key)
+    if winner is None:
+        raise RuntimeError("An idempotency key taken by a request that isn't there.")
+    return winner
+
+
+async def _retry(keys: KeySource, tenant_id: uuid.UUID, existing: RunRequest, fields: dict[str, Any]) -> Admitted:
+    if not await digests.matches(keys, str(tenant_id), existing.digest, existing.digest_key_version, **fields):
+        raise IdempotencyConflictError("Another request was made under this idempotency key.")
+    return Admitted(existing, new=False)
+
+
+async def _frozen(
+    s: AsyncSession, keys: KeySource, tenant_id: uuid.UUID, request_id: uuid.UUID, fields: dict[str, Any]
+) -> tuple[uuid.UUID, uuid.UUID]:
+    """The mutable checks, then the trigger claimed and its envelope stored: the frozen version and the envelope."""
+    tenant = await s.get(Tenant, tenant_id, populate_existing=True)
+    if tenant is None:
+        raise WorkflowNotFoundError(str(fields["workflow_id"]))
+    if tenant.status == "erasing":
+        raise _Refused(TENANT_ERASING, ["This tenant is being erased: it starts no run."])
+    if fields["source"] in INTERACTIVE:
+        platform = await recorded(s)
+        if platform is None:
+            raise _Refused(ENVIRONMENT_NOT_RECORDED, [NOT_RECORDED])
+        if platform.environment == PRODUCTION and not platform.production_runs:
+            raise _Refused(PRODUCTION_RUNS_DISABLED, [GATE_OFF])
+    workflow = await lock_for_admission(s, tenant_id, fields["workflow_id"])  # stands until the request is frozen
+    if workflow is None:
+        raise WorkflowNotFoundError(str(fields["workflow_id"]))
+    if not workflow.enabled:
+        raise _Refused(WORKFLOW_DISABLED, ["The workflow is disabled."])
+    if workflow.active_version_id is None:
+        raise _Refused(NOT_ACTIVE, ["The workflow has no active version."])
+    version = await s.get(WorkflowVersion, workflow.active_version_id)
+    if version is None:
+        raise RuntimeError("A workflow's active version that isn't there.")
+    build = (
+        await s.execute(
+            select(CurrentBuild.engine_abi).where(CurrentBuild.observed_at >= func.statement_timestamp() - BUILD_STALE)
+        )
+    ).scalar_one_or_none()
+    if build is None:
+        raise _Refused(NO_CURRENT_BUILD, [NO_BUILD], version.id)
+    stale = await other_abi(s, version.closure_version_ids, build)  # versions never change: no lock needed
+    if stale:
+        raise _Refused(VERSION_UNUSABLE, abi_reasons(version.id, stale, build), version.id)
+    entries = lifecycle.entries_for(version.closure_node_refs, version.closure_cel_profiles)
+    await lifecycle.lock_shared(s, entries)
+    blocked = lifecycle.not_executable(await lifecycle.states(s, entries))
+    if blocked:
+        reason = NODE_TYPE_RETIRED if any(e.kind == "node" for e in blocked) else CEL_PROFILE_RETIRED
+        raise _Refused(reason, [f"{entry} has been retired." for entry in blocked], version.id)
+    schema = (version.graph.get("settings") or {}).get("input_schema", {"type": "object"})
+    try:
+        envelope = await claim_input(
+            s, keys, tenant_id=tenant_id, run_id=request_id, root_run_id=request_id, schema=schema,
+            value=fields["input"],
+        )  # fmt: skip
+    except InputRefusedError as e:
+        raise _Refused(e.reason, e.reasons, version.id) from None
+    envelope_id = await claims.write_envelope(s, ClaimCipher(keys), tenant_id, request_id=request_id, envelope=envelope)
+    return version.id, envelope_id
+
+
+async def _insert(
+    s: AsyncSession,
+    keys: KeySource,
+    tenant_id: uuid.UUID,
+    request_id: uuid.UUID,
+    actor_id: uuid.UUID | None,
+    idempotency_key: str,
+    fields: dict[str, Any],
+    version_id: uuid.UUID | None,
+    envelope_id: uuid.UUID | None,
+    refused: _Refused | None = None,
+) -> Admitted:
+    """The request row, queued or refused, and its audit entry; `new` False when another transaction won the key."""
+    key_version, digest = await digests.digest(keys, str(tenant_id), **fields)  # the tenant's active key (§7.2)
+    status = "refused" if refused else "queued"
+    row = {
+        "id": request_id,
+        "tenant_id": tenant_id,
+        "workflow_id": fields["workflow_id"],
+        "workflow_version_id": refused.version_id if refused else version_id,
+        "source": fields["source"],
+        "actor_id": actor_id,
+        "mode": fields["mode"],
+        "idempotency_key": idempotency_key,
+        "digest": digest,
+        "digest_key_version": key_version,
+        "status": status,
+        "reason": refused.reason if refused else None,
+        "ended_at": func.now() if refused else None,
+        "envelope_id": envelope_id,
+    }
+    written = await s.execute(
+        insert(RunRequest)
+        .values(row)
+        .on_conflict_do_nothing(constraint="run_requests_idempotency")
+        .returning(RunRequest.id)
+    )
+    if written.scalar_one_or_none() is None:
+        if refused:
+            return await _retry(keys, tenant_id, await _winner(s, idempotency_key), fields)
+        return Admitted(RunRequest(id=request_id), new=False)
+    details: dict[str, object] = {"workflow_id": str(fields["workflow_id"]), "source": fields["source"],
+                                  "mode": fields["mode"], "status": status}  # fmt: skip
+    if row["workflow_version_id"]:
+        details["version_id"] = str(row["workflow_version_id"])
+    if refused:
+        details["reason"] = refused.reason
+    await audit.record(s, tenant_id=tenant_id, actor_id=actor_id, action="run.request", target_type="run_request",
+                       target_id=str(request_id), details=details)  # fmt: skip
+    request = await s.get(RunRequest, request_id, populate_existing=True)
+    if request is None:
+        raise RuntimeError("A request this transaction inserted that isn't there.")
+    return Admitted(request, new=True)
diff --git a/backend/src/dewpoint/apps/inputs.py b/backend/src/dewpoint/apps/inputs.py
index 9c869aa..ee733c5 100644
--- a/backend/src/dewpoint/apps/inputs.py
+++ b/backend/src/dewpoint/apps/inputs.py
@@ -18,6 +18,7 @@ from sqlalchemy.ext.asyncio import AsyncSession
 from dewpoint.core.claims import secret_index
 from dewpoint.core.claims import service as claims
 from dewpoint.core.claims.cipher import ClaimCipher
+from dewpoint.core.claims.secret_index import SECRET_INDEX_LIMIT
 from dewpoint.core.crypto.keys import KeySource
 from dewpoint.engine.handles import contains_marker
 from dewpoint.engine.runtime.projection import location
@@ -27,10 +28,15 @@ FORGED = "The run's input holds the reserved key `$claim`, which only Dewpoint w
 _REASONS = 5  # an input that breaks more rules is told about the first ones
 
 
+INPUT_INVALID = "input_invalid"
+
+
 class InputRefusedError(Exception):
-    def __init__(self, reasons: list[str]) -> None:
+    """`reasons`: what to tell the caller, places and rules only; `reason`: its code (engine 2b spec §9)."""
+
+    def __init__(self, reasons: list[str], reason: str = INPUT_INVALID) -> None:
         super().__init__("; ".join(reasons))
-        self.reasons = reasons
+        self.reasons, self.reason = reasons, reason
 
 
 def reasons(schema: Mapping[str, Any], value: Any) -> list[str]:
@@ -76,5 +82,5 @@ async def claim_input(
         try:
             await secret_index.extend(s, index, tenant_id, root_run_id, list(done.secrets))
         except secret_index.SecretIndexLimitError as e:
-            raise InputRefusedError([str(e)]) from None
+            raise InputRefusedError([str(e)], SECRET_INDEX_LIMIT) from None
     return done.envelope
diff --git a/backend/tests/apps/test_admission.py b/backend/tests/apps/test_admission.py
new file mode 100644
index 0000000..af31842
--- /dev/null
+++ b/backend/tests/apps/test_admission.py
@@ -0,0 +1,269 @@
+# SPDX-License-Identifier: Apache-2.0
+"""Admission (engine 2b spec §7.2, revision 7): a request frozen in its caller's transaction. An exact retry under the
+same idempotency key is the frozen request as it is now, whatever changed since; another request under the key is a
+conflict; a new key passes the mutable checks, is digested with the tenant's key, has its trigger claimed and its
+envelope stored, and is inserted, all in one savepoint that a lost race discards whole. A durable source's refusal is
+kept as a `refused` request; an interactive one's is raised."""
+
+import uuid
+from datetime import timedelta
+from typing import Any
+
+import pytest
+from sqlalchemy import text
+
+from dewpoint.apps import admission
+from dewpoint.core.claims import secret_index
+from dewpoint.core.claims import service as claims
+from dewpoint.core.claims.cipher import ClaimCipher
+from dewpoint.core.db import tenant_scope
+from dewpoint.core.plugins import lifecycle
+from dewpoint.engine import ENGINE_ABI
+from tests.apps.test_workflow_ops import ECHO_GRAPH, actor, create, publish, update
+from tests.support.graphs import G
+from tests.support.keys import FixtureKeys
+from tests.support.registry import sync_test_plugins
+
+pytestmark = pytest.mark.usefixtures("development_deployment")
+
+KEYS = FixtureKeys()
+TOKEN = "t0ken-value-1"
+SCHEMA = {
+    "type": "object",
+    "properties": {"token": {"type": "string", "x-sensitive": True}, "site": {"type": "string"}},
+    "required": ["token"],
+    "additionalProperties": False,
+}
+TOKEN_GRAPH = G().node("a", "testkit.echo@1", {"value": 1}).data() | {"settings": {"input_schema": SCHEMA}}
+
+
+async def published(owner: Any, api: Any, admin: Any, settings: Any, graph: Any = TOKEN_GRAPH) -> tuple[Any, uuid.UUID]:
+    await sync_test_plugins(admin)
+    ctx = await actor(owner)
+    wf = await create(api, ctx, graph)
+    assert (await publish(api, ctx, wf, settings)).version is not None
+    return ctx, wf
+
+
+async def current(dispatch: Any, *, abi: int = ENGINE_ABI, age: timedelta = timedelta()) -> None:
+    """The current build as the dispatcher last recorded it, which admission checks the ABI against."""
+    async with dispatch() as s, s.begin():
+        await s.execute(
+            text("insert into current_build (id, build_id, engine_abi, observed_at) "
+                 "values (1, 'b', :a, now() - cast(:age as interval)) "
+                 "on conflict (id) do update set engine_abi = excluded.engine_abi, observed_at = excluded.observed_at"),
+            {"a": abi, "age": age},
+        )  # fmt: skip
+
+
+async def admit(api: Any, ctx: Any, wf: uuid.UUID, *, key: str = "k1", keys: Any = KEYS, **request: Any) -> Any:
+    fields = {"source": "manual", "mode": "live", "input": {"token": TOKEN, "site": "a"}, **request}
+    async with api() as s, s.begin():
+        return await admission.admit_request(
+            s, keys, tenant_id=ctx.tenant_id, workflow_id=wf, actor_id=ctx.user.id, idempotency_key=key, **fields
+        )
+
+
+async def count(owner: Any, table: str) -> int:
+    async with owner() as s:
+        return int((await s.execute(text(f"select count(*) from {table}"))).scalar_one())
+
+
+@pytest.fixture
+async def ready(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings) -> Any:
+    ctx, wf = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings)
+    await current(dispatch_sessionmaker)
+    return ctx, wf
+
+
+async def test_a_new_request_is_frozen_on_the_active_version_with_its_envelope_and_claims(
+    ready, owner_sessionmaker, api_sessionmaker, dispatch_sessionmaker
+) -> None:
+    ctx, wf = ready
+    admitted = await admit(api_sessionmaker, ctx, wf)
+    r = admitted.request
+    assert admitted.new and (r.status, r.source, r.mode, r.actor_id, r.digest_key_version) == (
+        "queued", "manual", "live", ctx.user.id, 1,
+    )  # fmt: skip
+    async with dispatch_sessionmaker() as s, s.begin():
+        await tenant_scope(s, ctx.tenant_id)
+        active = (await s.execute(text("select active_version_id from workflows where id = :w"), {"w": wf})).scalar()
+        envelope = await claims.read_envelope(s, ClaimCipher(KEYS), ctx.tenant_id, request_id=r.id)
+        handle = envelope["token"]["$claim"]
+        token = await claims.fetch(s, ClaimCipher(KEYS), ctx.tenant_id, run_id=r.id, claim_id=uuid.UUID(handle))
+    assert r.workflow_version_id == active and envelope["site"] == "a" and token.value == TOKEN
+    async with owner_sessionmaker() as s:
+        audit = (await s.execute(text("select action, target_id, details from audit_log"))).all()
+        index = (await s.execute(text("select root_run_id from run_secret_index"))).scalars().all()
+    assert [(a.action, a.target_id) for a in audit if a.action.startswith("run.")] == [("run.request", str(r.id))]
+    assert index == [r.id]  # the run tree's secret index is seeded under the request's id, the run's
+    assert await count(owner_sessionmaker, "runs") == 0  # the dispatcher writes the run's row (§7.3)
+
+
+async def test_an_exact_retry_is_the_frozen_request_whatever_changed_since(
+    ready, owner_sessionmaker, api_sessionmaker
+) -> None:
+    """A key rotation and a disabled workflow don't change what an exact retry returns (§7.2, step 2)."""
+    ctx, wf = ready
+    first = (await admit(api_sessionmaker, ctx, wf)).request
+    stored = await count(owner_sessionmaker, "run_inputs")
+    await update(api_sessionmaker, ctx, wf, enabled=False)
+    again = await admit(api_sessionmaker, ctx, wf, keys=FixtureKeys(version=2))
+    assert (again.new, again.request.id, again.request.status) == (False, first.id, "queued")
+    assert await count(owner_sessionmaker, "run_inputs") == stored
+
+
+async def test_another_request_under_the_same_key_is_a_conflict(ready, api_sessionmaker) -> None:
+    ctx, wf = ready
+    await admit(api_sessionmaker, ctx, wf)
+    for other in ({"input": {"token": "another-token", "site": "a"}}, {"mode": "simulate"}):
+        with pytest.raises(admission.IdempotencyConflictError):
+            await admit(api_sessionmaker, ctx, wf, **other)
+
+
+@pytest.mark.parametrize("same", [True, False])
+async def test_a_concurrent_admission_under_the_key_returns_the_winner_and_leaves_nothing_of_its_own(
+    ready, owner_sessionmaker, api_sessionmaker, monkeypatch, same
+) -> None:
+    """Another transaction freezes a request under the key between this one's lookup and its insert: the insert
+    conflicts, the savepoint is rolled back with this call's claims and envelope, and the winner is compared with its
+    own stored key version (§7.2, step 6)."""
+    ctx, wf = ready
+    winner: list[Any] = []
+
+    async def race() -> None:
+        if not winner:
+            winner.append(None)
+            winner[0] = (await admit(api_sessionmaker, ctx, wf, input={"token": TOKEN if same else "x" * 9})).request
+
+    monkeypatch.setattr(admission, "_before_insert", race)
+    if same:
+        admitted = await admit(api_sessionmaker, ctx, wf, input={"token": TOKEN})
+        assert (admitted.new, admitted.request.id) == (False, winner[0].id)
+    else:
+        with pytest.raises(admission.IdempotencyConflictError):
+            await admit(api_sessionmaker, ctx, wf, input={"token": TOKEN})
+    async with owner_sessionmaker() as s:
+        owners = (await s.execute(text("select distinct owner_run_id from run_inputs"))).scalars().all()
+    assert owners == [winner[0].id]
+
+
+@pytest.mark.parametrize(
+    ("breaks", "reason"),
+    [
+        ("erasing", "tenant_erasing"),
+        ("disabled", "workflow_disabled"),
+        ("retired", "node_type_retired"),
+        ("no_build", "no_current_build"),
+        ("stale_build", "no_current_build"),
+        ("other_abi", "version_unusable"),
+        ("input", "input_invalid"),
+    ],  # fmt: skip
+)
+async def test_a_refused_interactive_request_is_raised_and_leaves_nothing(
+    ready, owner_sessionmaker, api_sessionmaker, dispatch_sessionmaker, breaks, reason
+) -> None:
+    ctx, wf = ready
+    request: dict[str, Any] = {}
+    async with owner_sessionmaker() as s, s.begin():
+        if breaks == "erasing":
+            await s.execute(text("update tenants set status = 'erasing' where id = :t"), {"t": ctx.tenant_id})
+        elif breaks == "retired":
+            await s.execute(
+                text("update node_type_versions set state = 'retired' where type = 'testkit.echo' and version = 1")
+            )
+        elif breaks == "no_build":
+            await s.execute(text("delete from current_build"))
+    if breaks == "disabled":
+        await update(api_sessionmaker, ctx, wf, enabled=False)
+    elif breaks == "stale_build":
+        await current(dispatch_sessionmaker, age=timedelta(minutes=10))
+    elif breaks == "other_abi":
+        await current(dispatch_sessionmaker, abi=ENGINE_ABI + 1)
+    elif breaks == "input":
+        request["input"] = {"token": 7, "secret-key-name": "v"}
+    with pytest.raises(admission.AdmissionRefusedError) as refused:
+        await admit(api_sessionmaker, ctx, wf, **request)
+    assert refused.value.reason == reason and refused.value.messages
+    if breaks == "input":  # locations and rules only, never a value nor a key the data supplied (§3.5)
+        assert not any("secret-key-name" in m or "7" in m.split("at ")[-1] for m in refused.value.messages)
+    assert (await count(owner_sessionmaker, "run_requests"), await count(owner_sessionmaker, "run_inputs")) == (0, 0)
+
+
+async def test_a_workflow_with_no_active_version_admits_nothing(
+    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker
+) -> None:
+    await sync_test_plugins(admin_sessionmaker)
+    ctx = await actor(owner_sessionmaker)
+    wf = await create(api_sessionmaker, ctx, ECHO_GRAPH)  # never published
+    await current(dispatch_sessionmaker)
+    with pytest.raises(admission.AdmissionRefusedError) as refused:
+        await admit(api_sessionmaker, ctx, wf, input={})
+    assert refused.value.reason == "not_active"
+
+
+@pytest.mark.parametrize("breaks", ["disabled", "input"])
+async def test_a_durable_sources_refusal_is_kept_as_a_refused_request(
+    ready, owner_sessionmaker, api_sessionmaker, breaks
+) -> None:
+    """A schedule tick's or a webhook event's refusal is never lost (§7.2): a `refused` request with its reason, no
+    envelope and no claims, audited. It's frozen like any request: retried under its key, it's the same refusal."""
+    ctx, wf = ready
+    request: dict[str, Any] = {"source": "schedule"}
+    if breaks == "disabled":
+        await update(api_sessionmaker, ctx, wf, enabled=False)
+    else:
+        request["input"] = {"token": 7}
+    admitted = await admit(api_sessionmaker, ctx, wf, **request)
+    r = admitted.request
+    assert admitted.new and (r.status, r.reason, r.envelope_id) == (
+        "refused", "workflow_disabled" if breaks == "disabled" else "input_invalid", None,
+    )  # fmt: skip
+    assert await count(owner_sessionmaker, "run_inputs") == 0
+    again = await admit(api_sessionmaker, ctx, wf, **request)
+    assert (again.new, again.request.id) == (False, r.id)
+
+
+async def test_an_input_past_the_secret_index_bound_is_refused_and_its_claims_discarded(
+    ready, owner_sessionmaker, api_sessionmaker, monkeypatch
+) -> None:
+    ctx, wf = ready
+    monkeypatch.setattr(secret_index, "MAX_STRINGS", 0)
+    with pytest.raises(admission.AdmissionRefusedError) as refused:
+        await admit(api_sessionmaker, ctx, wf)
+    assert refused.value.reason == "secret_index_limit"
+    assert await count(owner_sessionmaker, "run_inputs") == 0
+
+
+async def test_admission_refuses_a_repeatable_read_transaction(ready, api_sessionmaker) -> None:
+    """Its locks serialize with retirement and workflow changes only at READ COMMITTED (engine-core §4.5)."""
+    ctx, wf = ready
+    with pytest.raises(lifecycle.IsolationError):
+        async with api_sessionmaker() as s, s.begin():
+            await s.execute(text("set transaction isolation level repeatable read"))
+            await admission.admit_request(
+                s, KEYS, tenant_id=ctx.tenant_id, workflow_id=wf, actor_id=ctx.user.id, idempotency_key="k",
+                source="manual", mode="live", input={"token": TOKEN},
+            )  # fmt: skip
+
+
+async def test_the_build_record_ages_with_the_clock_not_the_callers_transaction(
+    ready, api_sessionmaker, monkeypatch
+) -> None:
+    """A caller admitting several requests in one transaction (2b-3's matcher) sees the record go stale while it holds
+    the transaction: the check reads the statement's time, not the transaction's start (the owner's M1 checkpoint)."""
+    ctx, wf = ready
+    monkeypatch.setattr(admission, "BUILD_STALE", timedelta(seconds=1))
+    async with api_sessionmaker() as s, s.begin():
+        first = await admission.admit_request(
+            s, KEYS, tenant_id=ctx.tenant_id, workflow_id=wf, actor_id=ctx.user.id, idempotency_key="a",
+            source="manual", mode="live", input={"token": TOKEN},
+        )  # fmt: skip
+        assert first.new
+        await s.execute(text("select pg_sleep(1.2)"))
+        with pytest.raises(admission.AdmissionRefusedError) as stale:
+            await admission.admit_request(
+                s, KEYS, tenant_id=ctx.tenant_id, workflow_id=wf, actor_id=ctx.user.id, idempotency_key="b",
+                source="manual", mode="live", input={"token": TOKEN},
+            )  # fmt: skip
+    assert stale.value.reason == "no_current_build"
diff --git a/backend/tests/apps/test_admission_gate.py b/backend/tests/apps/test_admission_gate.py
index 447d6ff..b410973 100644
--- a/backend/tests/apps/test_admission_gate.py
+++ b/backend/tests/apps/test_admission_gate.py
@@ -8,10 +8,13 @@ from typing import Any
 import pytest
 from sqlalchemy import func, select, text
 
+from dewpoint.apps import admission
 from dewpoint.apps.runs import PRODUCTION_RUNS_DISABLED, NotAdmissibleError, start_run
 from dewpoint.core.models.runs import Run
 from dewpoint.core.platform.service import NOT_RECORDED, PRODUCTION, record_environment
 from dewpoint.engine.runtime.activities import SIMULATE
+from tests.apps.test_admission import admit, current
+from tests.apps.test_admission import published as published_workflow
 from tests.apps.test_runs import FakeClient, published
 
 
@@ -64,3 +67,20 @@ async def test_a_deployment_that_never_recorded_its_environment_admits_nothing(
     reasons, client = await refused(dispatch_sessionmaker, api_settings, ctx, version)
     assert reasons == [NOT_RECORDED]
     assert (client.calls, await run_count(owner_sessionmaker)) == ([], 0)
+
+
+async def test_admission_refuses_an_interactive_request_and_queues_a_durable_one_while_the_gate_is_off(
+    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings
+) -> None:
+    """Engine 2b spec §2.3, §2.5: the run API, the CLI and re-runs are refused with `production_runs_disabled`; a
+    schedule tick or a webhook event still records its work, queued, which waits for the gate."""
+    async with owner_sessionmaker() as s, s.begin():
+        await record_environment(s, environment=PRODUCTION, namespace="default")
+    ctx, wf = await published_workflow(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings)
+    await current(dispatch_sessionmaker)
+    for source in ("manual", "rerun", "dev"):
+        with pytest.raises(admission.AdmissionRefusedError) as gate:
+            await admit(api_sessionmaker, ctx, wf, key=source, source=source)
+        assert gate.value.reason == "production_runs_disabled"
+    durable = await admit(api_sessionmaker, ctx, wf, key="tick", source="schedule")
+    assert (durable.new, durable.request.status) == (True, "queued")
```

### Task 6: Retirement counts the requests that haven't started, and a forced one cancels the queued

**Commit:** `3d0a477` (prototype `proto/2b2-v2`); the replay's tree was identical: yes.

**Create:** `backend/migrations/versions/0019_retirement_cancels_requests.py`, `backend/tests/apps/test_admission_retirement.py`

**Modify:** `backend/src/dewpoint/core/plugins/lifecycle.py`, `backend/tests/core/plugins/test_lifecycle.py`, `backend/tests/core/requests/test_schema.py`

**What it does:**

Engine-core §4.5: a request that hasn't started references its frozen version's closure. A `queued` or `starting`
request now blocks normal retirement, whether or not its workflow is still enabled; the preview lists them. A forced,
confirmed retirement cancels each queued one explicitly (`cancelled`, `node_type_retired` or `cel_profile_retired`),
and each tenant's audit entry names its cancelled requests, so none turns into a failure later. A `starting` request
is left alone: it either starts, and a started run is never broken, or comes back to the queue, where dispatch's
defensive check cancels it. Migration 0019 lets the key admin read every tenant's requests and move a request only from
`queued` to `cancelled`, a cancel's columns only.


- [ ] **Step 1: its tests alone, before its code.** Run: `uv run pytest -n 4 tests/apps/test_admission_retirement.py tests/core/plugins/test_lifecycle.py tests/core/requests/test_schema.py`. Replay result (exit 1), shortened:

```
    assert False == ('select' in {'select', 'update'})
     +  where {'select', 'update'} = <built-in method get of dict object at 0x1113b60c0>(('admin', 'run_requests'), set())
     +    where <built-in method get of dict object at 0x1113b60c0> = {('admin', 'run_requests'): {'select', 'update'}, ('api', 'run_requests'): {'insert', 'select', 'update'}, ('api', 'tenant_run_limits'): {'select'}, ('api', 'run_slots'): {'select'}, ...}.get
     +    and   set() = set()
/private/tmp/claude-501/-Users-tmunzer-4-dev-mist-dewpoint/1e3145a1-199e-4b31-be1b-1e3bfd266be7/scratchpad/2b2-plan/replay/backend/tests/core/requests/test_schema.py:273: AssertionError: ('admin', 'run_requests', 'select')
=========================== short test summary info ============================
FAILED tests/apps/test_admission_retirement.py::test_the_admin_cancels_only_a_queued_request_even_within_a_tenant_scope[started]
FAILED tests/apps/test_admission_retirement.py::test_a_queued_request_blocks_normal_retirement_even_once_its_workflow_is_disabled
FAILED tests/apps/test_admission_retirement.py::test_a_starting_request_blocks_normal_retirement_and_survives_a_forced_one
FAILED tests/apps/test_admission_retirement.py::test_the_admin_cancels_only_a_queued_request_even_within_a_tenant_scope[starting]
FAILED tests/apps/test_admission_retirement.py::test_a_forced_retirement_lists_then_cancels_queued_requests_in_their_tenants
FAILED tests/core/plugins/test_lifecycle.py::test_forced_retirement_previews_then_applies
FAILED tests/core/requests/test_schema.py::test_each_role_has_exactly_its_privileges[run_requests]
7 failed, 28 passed in 13.88s
```

- [ ] **Step 2: its code, then the same tests.** Replay result (exit 0), shortened:

```
...................................                                      [100%]
35 passed in 12.85s
```

- [ ] **Step 3: commit.** `git cherry-pick --no-commit 3d0a477 && git commit -C 3d0a477`

The diff:

```diff
diff --git a/backend/migrations/versions/0019_retirement_cancels_requests.py b/backend/migrations/versions/0019_retirement_cancels_requests.py
new file mode 100644
index 0000000..654425f
--- /dev/null
+++ b/backend/migrations/versions/0019_retirement_cancels_requests.py
@@ -0,0 +1,30 @@
+# SPDX-License-Identifier: Apache-2.0
+"""retirement reads every tenant's unstarted requests and cancels the queued ones (engine-core §4.5, engine 2b spec §7)
+
+A forced retirement runs as the key admin across tenants: it lists the requests that haven't started whose frozen
+closure uses the entry, and cancels each queued one explicitly. The admin may move a request only from `queued` to
+`cancelled`, and only a cancel's columns."""
+
+from alembic import op
+
+revision = "0019"
+down_revision = "0018"
+branch_labels = None
+depends_on = None
+
+
+def upgrade() -> None:
+    op.execute("CREATE POLICY run_requests_platform_read ON run_requests FOR SELECT TO dewpoint_admin USING (true)")
+    op.execute(
+        "CREATE POLICY run_requests_platform_cancel ON run_requests FOR UPDATE TO dewpoint_admin "
+        "USING (status = 'queued') WITH CHECK (status = 'cancelled')"
+    )
+    op.execute("GRANT SELECT ON run_requests TO dewpoint_admin")
+    op.execute("GRANT UPDATE (status, reason, ended_at) ON run_requests TO dewpoint_admin")
+
+
+def downgrade() -> None:
+    op.execute("REVOKE UPDATE (status, reason, ended_at) ON run_requests FROM dewpoint_admin")
+    op.execute("REVOKE SELECT ON run_requests FROM dewpoint_admin")
+    op.execute("DROP POLICY run_requests_platform_cancel ON run_requests")
+    op.execute("DROP POLICY run_requests_platform_read ON run_requests")
diff --git a/backend/src/dewpoint/core/plugins/lifecycle.py b/backend/src/dewpoint/core/plugins/lifecycle.py
index a5df964..ef2f537 100644
--- a/backend/src/dewpoint/core/plugins/lifecycle.py
+++ b/backend/src/dewpoint/core/plugins/lifecycle.py
@@ -19,6 +19,7 @@ from sqlalchemy.orm import InstrumentedAttribute
 from dewpoint.core.audit.service import record
 from dewpoint.core.db import tenant_scope
 from dewpoint.core.models.plugins import CelProfile, NodeTypeVersion
+from dewpoint.core.models.requests import RunRequest
 from dewpoint.core.models.workflows import Workflow, WorkflowVersion
 from dewpoint.core.plugins.registry import split_ref
 
@@ -116,6 +117,18 @@ class AffectedVersion:
     enabled: bool  # its workflow is enabled
 
 
+@dataclass(frozen=True)
+class QueuedRef:
+    """A run request that hasn't started, frozen on a version whose closure uses the entry: a `queued` one, which a
+    forced retirement cancels, or a `starting` one, which may still reach Temporal and is left to start or come back."""
+
+    tenant_id: uuid.UUID
+    request_id: uuid.UUID
+    workflow_id: uuid.UUID
+    version_id: uuid.UUID
+    status: str
+
+
 @dataclass(frozen=True)
 class RetirePreview:
     entry: Entry
@@ -123,12 +136,15 @@ class RetirePreview:
     active_refs: tuple[ActiveRef, ...]  # enabled workflows whose active closure uses the entry
     affected: tuple[AffectedVersion, ...]  # every version whose closure uses it, per tenant (spec §4.5 preview)
     applied: bool = False
-    # Sub-project 2b adds the queued run requests a forced retirement would cancel.
+    queued: tuple[QueuedRef, ...] = ()  # requests that haven't started: a forced retirement cancels the queued ones
 
 
 class ReferencedError(RuntimeError):
     def __init__(self, preview: RetirePreview) -> None:
-        super().__init__(f"{preview.entry} is used by {len(preview.active_refs)} active workflow(s)")
+        super().__init__(
+            f"{preview.entry} is used by {len(preview.active_refs)} active workflow(s) and "
+            f"{len(preview.queued)} run request(s) that haven't started"
+        )
         self.preview = preview
 
 
@@ -160,7 +176,14 @@ async def _preview(s: AsyncSession, entry: Entry, state: str) -> RetirePreview:
         .order_by(Workflow.tenant_id, Workflow.name, WorkflowVersion.number)
     )
     versions = tuple(AffectedVersion(*row) for row in affected)
-    return RetirePreview(entry=entry, state=state, active_refs=refs, affected=versions)
+    unstarted = await s.execute(
+        select(RunRequest.tenant_id, RunRequest.id, RunRequest.workflow_id, WorkflowVersion.id, RunRequest.status)
+        .join(WorkflowVersion, WorkflowVersion.id == RunRequest.workflow_version_id)
+        .where(uses, RunRequest.status.in_(("queued", "starting")))
+        .order_by(RunRequest.tenant_id, RunRequest.queued_at, RunRequest.id)
+    )
+    queued = tuple(QueuedRef(*row) for row in unstarted)
+    return RetirePreview(entry=entry, state=state, active_refs=refs, affected=versions, queued=queued)
 
 
 async def _set_state(s: AsyncSession, entry: Entry, state: str) -> None:
@@ -190,9 +213,12 @@ async def deprecate(s: AsyncSession, entry: Entry, *, actor_id: uuid.UUID | None
 async def retire(
     s: AsyncSession, entry: Entry, *, force: bool = False, confirm: bool = False, actor_id: uuid.UUID | None = None
 ) -> RetirePreview:
-    """Normal path: refuse while an enabled workflow's active closure uses the entry. Forced path: return the
-    preview unless `confirm`; with `confirm`, affected workflows stop being startable and each tenant gets an audit
-    entry. Runs inside the caller's transaction (READ COMMITTED); the caller commits."""
+    """Normal path: refuse while an enabled workflow's active closure, or a request that hasn't started, uses the
+    entry. Forced path: return the preview unless `confirm`; with `confirm`, affected workflows stop being startable,
+    every queued request on them is cancelled explicitly (`node_type_retired`, `cel_profile_retired`), and each tenant
+    gets an audit entry. A `starting` request is left alone: it either starts, and a started run is never broken, or
+    comes back to the queue, where dispatch's defensive check cancels it. Runs inside the caller's transaction (READ
+    COMMITTED); the caller commits."""
     await lock_exclusive(s, entry)  # first: every statement below sees references committed before the lock
     current = (await states(s, [entry]))[entry]
     if current == "missing":
@@ -200,11 +226,20 @@ async def retire(
     preview = await _preview(s, entry, current)
     if current == "retired":
         return replace(preview, applied=True)
-    if preview.active_refs and not force:
+    referenced = bool(preview.active_refs or preview.queued)
+    if referenced and not force:
         raise ReferencedError(preview)
-    if preview.active_refs and not confirm:
+    if referenced and not confirm:
         return preview
     await _set_state(s, entry, "retired")
+    cancelled = [q for q in preview.queued if q.status == "queued"]
+    if cancelled:
+        reason = "node_type_retired" if entry.kind == "node" else "cel_profile_retired"
+        await s.execute(
+            update(RunRequest)
+            .where(RunRequest.id.in_([q.request_id for q in cancelled]), RunRequest.status == "queued")
+            .values(status="cancelled", reason=reason, ended_at=func.now())
+        )
     await record(
         s,
         tenant_id=None,
@@ -212,12 +247,15 @@ async def retire(
         action="lifecycle.retire",
         target_type=entry.kind,
         target_id=entry.key,
-        details={"forced": bool(preview.active_refs), "active_workflows": len(preview.active_refs)},
+        details={"forced": referenced, "active_workflows": len(preview.active_refs), "requests": len(cancelled)},
     )
-    by_tenant: dict[uuid.UUID, list[str]] = {}
+    workflows: dict[uuid.UUID, list[str]] = {}
+    requests: dict[uuid.UUID, list[str]] = {}
     for ref in preview.active_refs:
-        by_tenant.setdefault(ref.tenant_id, []).append(str(ref.workflow_id))
-    for tenant_id, workflow_ids in sorted(by_tenant.items()):
+        workflows.setdefault(ref.tenant_id, []).append(str(ref.workflow_id))
+    for q in cancelled:
+        requests.setdefault(q.tenant_id, []).append(str(q.request_id))
+    for tenant_id in sorted(workflows.keys() | requests.keys()):
         await tenant_scope(s, tenant_id)  # tenant audit entries need the tenant context; nothing reads after this
         await record(
             s,
@@ -226,6 +264,10 @@ async def retire(
             action="lifecycle.retire",
             target_type=entry.kind,
             target_id=entry.key,
-            details={"forced": True, "workflows": workflow_ids},
+            details={
+                "forced": True,
+                "workflows": workflows.get(tenant_id, []),
+                "requests": requests.get(tenant_id, []),
+            },
         )
     return replace(preview, applied=True)
diff --git a/backend/tests/apps/test_admission_retirement.py b/backend/tests/apps/test_admission_retirement.py
new file mode 100644
index 0000000..98cfe21
--- /dev/null
+++ b/backend/tests/apps/test_admission_retirement.py
@@ -0,0 +1,111 @@
+# SPDX-License-Identifier: Apache-2.0
+"""Retirement and queued requests (engine-core §4.5): a request that hasn't started references its frozen version's
+closure. It blocks normal retirement, whether or not its workflow is still enabled; a forced retirement lists it in its
+preview, then cancels it explicitly, audited in its tenant, so it never turns into a failure later. A request already
+`starting` may still reach Temporal: it isn't cancelled, and a run that starts is never broken by a retirement."""
+
+import uuid
+from typing import Any
+
+import pytest
+from sqlalchemy import text
+from sqlalchemy.exc import DBAPIError
+
+from dewpoint.core.db import tenant_scope
+from dewpoint.core.plugins import lifecycle
+from tests.apps.test_admission import admit, current, published
+from tests.apps.test_workflow_ops import ECHO_GRAPH, update
+from tests.core.requests.test_schema import INSERT_REQUEST, claim
+from tests.core.requests.test_schema import request as request_row
+from tests.support.workflows import seed_workflow
+
+pytestmark = pytest.mark.usefixtures("development_deployment")
+ECHO = lifecycle.Entry("node", "testkit.echo@1")
+
+
+async def queued(owner: Any, api: Any, admin: Any, dispatch: Any, settings: Any) -> tuple[Any, uuid.UUID, Any]:
+    ctx, wf = await published(owner, api, admin, settings, graph=ECHO_GRAPH)
+    await current(dispatch)
+    return ctx, wf, (await admit(api, ctx, wf, input={})).request
+
+
+async def status(owner: Any, request_id: uuid.UUID) -> tuple[str, str | None, bool]:
+    async with owner() as s:
+        row = (await s.execute(text("select status, reason, ended_at is not null from run_requests where id = :i"),
+                               {"i": request_id})).one()  # fmt: skip
+    return row[0], row[1], row[2]
+
+
+async def test_a_queued_request_blocks_normal_retirement_even_once_its_workflow_is_disabled(
+    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings
+) -> None:
+    ctx, wf, request = await queued(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker,
+                                    api_settings)  # fmt: skip
+    await update(api_sessionmaker, ctx, wf, enabled=False)  # no active reference left: the queued one remains
+    with pytest.raises(lifecycle.ReferencedError) as blocked:
+        async with admin_sessionmaker() as s, s.begin():
+            await lifecycle.retire(s, ECHO)
+    assert [(q.tenant_id, q.request_id) for q in blocked.value.preview.queued] == [(ctx.tenant_id, request.id)]
+
+
+async def test_a_forced_retirement_lists_then_cancels_queued_requests_in_their_tenants(
+    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings
+) -> None:
+    made = [await queued(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings)
+            for _ in range(2)]  # fmt: skip
+    async with admin_sessionmaker() as s, s.begin():
+        preview = await lifecycle.retire(s, ECHO, force=True)
+    assert not preview.applied and {q.request_id for q in preview.queued} == {r.id for _, _, r in made}
+    async with admin_sessionmaker() as s, s.begin():
+        assert (await lifecycle.retire(s, ECHO, force=True, confirm=True)).applied
+    for ctx, _, request in made:
+        assert await status(owner_sessionmaker, request.id) == ("cancelled", "node_type_retired", True)
+        async with owner_sessionmaker() as s:
+            details = (await s.execute(text("select details from audit_log where tenant_id = :t and action = "
+                                            "'lifecycle.retire'"), {"t": ctx.tenant_id})).scalar_one()  # fmt: skip
+        assert details["requests"] == [str(request.id)]
+
+
+async def test_a_starting_request_blocks_normal_retirement_and_survives_a_forced_one(
+    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings
+) -> None:
+    ctx, wf, request = await queued(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker,
+                                    api_settings)  # fmt: skip
+    await update(api_sessionmaker, ctx, wf, enabled=False)  # only the request references the entry
+    async with owner_sessionmaker() as s, s.begin():
+        await s.execute(text("update run_requests set status = 'starting' where id = :i"), {"i": request.id})
+    with pytest.raises(lifecycle.ReferencedError):
+        async with admin_sessionmaker() as s, s.begin():
+            await lifecycle.retire(s, ECHO)
+    async with admin_sessionmaker() as s, s.begin():
+        assert (await lifecycle.retire(s, ECHO, force=True, confirm=True)).applied
+    assert await status(owner_sessionmaker, request.id) == ("starting", None, False)
+
+
+@pytest.mark.parametrize("status", ["starting", "started"])
+async def test_the_admin_cancels_only_a_queued_request_even_within_a_tenant_scope(
+    owner_sessionmaker, admin_sessionmaker, status
+) -> None:
+    """The general policy is the operational roles': the admin's only update is a forced retirement's, `queued` to
+    `cancelled`, whatever tenant scope its session has set (the owner's M1 checkpoint)."""
+    tenant, wf, version = await seed_workflow(owner_sessionmaker)
+    values = request_row(tenant, wf, version, status=status)
+    async with owner_sessionmaker() as s, s.begin():
+        values["envelope_id"] = await claim(s, tenant, values["id"], role="envelope", pointer=None)
+        await s.execute(INSERT_REQUEST, values)
+    cancel = text("update run_requests set status = 'cancelled', reason = 'r', ended_at = now() where id = :i")
+    async with admin_sessionmaker() as s, s.begin():
+        await tenant_scope(s, tenant)
+        assert (await s.execute(cancel, {"i": values["id"]})).rowcount == 0
+    async with owner_sessionmaker() as s:
+        current = (await s.execute(text("select status from run_requests where id = :i"), {"i": values["id"]})).scalar()
+    assert current == status
+    queued = request_row(tenant, wf, version)
+    async with owner_sessionmaker() as s, s.begin():
+        queued["envelope_id"] = await claim(s, tenant, queued["id"], role="envelope", pointer=None)
+        await s.execute(INSERT_REQUEST, queued)
+    with pytest.raises(DBAPIError, match="row-level security"):  # and only into `cancelled`
+        async with admin_sessionmaker() as s, s.begin():
+            await tenant_scope(s, tenant)
+            await s.execute(text("update run_requests set status = 'dead', ended_at = now() where id = :i"),
+                            {"i": queued["id"]})  # fmt: skip
diff --git a/backend/tests/core/plugins/test_lifecycle.py b/backend/tests/core/plugins/test_lifecycle.py
index 1d9ef24..442327e 100644
--- a/backend/tests/core/plugins/test_lifecycle.py
+++ b/backend/tests/core/plugins/test_lifecycle.py
@@ -86,7 +86,7 @@ async def test_forced_retirement_previews_then_applies(admin_sessionmaker, owner
             )
         ).all()
     assert [r.tenant_id for r in rows] == [None, tenant]
-    assert rows[1].details == {"forced": True, "workflows": [str(wf)]}
+    assert rows[1].details == {"forced": True, "workflows": [str(wf)], "requests": []}  # no queued request
 
 
 async def test_retirement_requires_read_committed(admin_sessionmaker) -> None:
diff --git a/backend/tests/core/requests/test_schema.py b/backend/tests/core/requests/test_schema.py
index 01ed65d..1039023 100644
--- a/backend/tests/core/requests/test_schema.py
+++ b/backend/tests/core/requests/test_schema.py
@@ -241,6 +241,7 @@ async def test_a_tenant_is_active_until_it_is_erased(owner_sessionmaker) -> None
 # dispatcher moves requests, reserves slots under the limits row and records the current build; the worker's end write
 # releases a slot. Column-level grants narrow the API's updates to a cancel's columns.
 ALLOWED = {
+    ("admin", "run_requests"): {"select", "update"},  # a forced retirement cancels queued requests (engine-core §4.5)
     ("api", "run_requests"): {"select", "insert", "update"},
     ("api", "tenant_run_limits"): {"select"},
     ("api", "run_slots"): {"select"},
```

**Checkpoint (milestone 1).** Focused: `tests/core`, the admission and retirement tests, the claims and worker store tests (141 at `3d0a477`); the migrations 0016 → head → 0016 → head over a pre-2b-2 run. The owner held it for three corrections (the policies scoped to the operational roles, the tenant in the envelope's foreign key, the build record aged by the statement's clock), folded into Tasks 1 and 5, then approved it as a prototype checkpoint (2026-10-03).

## Milestone 2 — The dispatcher

### Task 7: The dispatcher process observes the current build, checks its workers and reports

**Commit:** `d975653` (prototype `proto/2b2-v2`); the replay's tree was identical: yes.

**Create:** `backend/migrations/versions/0020_dispatcher_reports.py`, `backend/src/dewpoint/apps/dispatcher/__init__.py`, `backend/src/dewpoint/apps/dispatcher/main.py`, `backend/src/dewpoint/apps/dispatcher/observe.py`, `backend/tests/apps/dispatcher/__init__.py`, `backend/tests/apps/dispatcher/test_observe.py`

**Modify:** `backend/src/dewpoint/apps/cli/main.py`, `backend/src/dewpoint/core/models/platform.py`, `backend/src/dewpoint/core/platform/service.py`, `backend/tests/apps/test_environment.py`, `backend/tests/core/platform/test_workers.py`

**What it does:**

Engine 2b spec §2.1, §2.7, §7.3, §10.6:
- `dewpoint dispatcher` checks the deployment's environment before it connects to Temporal (exit 2), and encrypts
  with the tenants' keys through its role.
- Each cycle it reads the current build from Temporal and records it with when it was observed: admission's ABI check
  (the owner's ruling), which fails closed once the record ages; no current build records nothing.
- `workers_ready` says what holds a build back: every live instance (checked within 90 s, by the statement's clock) is
  healthy and holds every required capability, and at least one exists. Dispatch runs it in every starting
  transaction.
- Migration 0020: `dispatcher_reports`, each instance's last report, health evidence 2b-4's readiness checks read,
  claiming nothing by itself.


- [ ] **Step 1: its tests alone, before its code.** Run: `uv run pytest -n 4 tests/apps/dispatcher/test_observe.py tests/apps/test_environment.py tests/core/platform/test_workers.py`. Replay result (exit 1), shortened:

```
/private/tmp/claude-501/-Users-tmunzer-4-dev-mist-dewpoint/1e3145a1-199e-4b31-be1b-1e3bfd266be7/scratchpad/2b2-plan/replay/backend/tests/core/platform/test_workers.py:52: ImportError: cannot import name 'workers_ready' from 'dewpoint.core.platform.service' (/private/tmp/claude-501/-Users-tmunzer-4-dev-mist-dewpoint/1e3145a1-199e-4b31-be1b-1e3bfd266be7/scratchpad/2b2-plan/replay/backend/src/dewpoint/core/platform/service.py)
[gw3] darwin -- Python 3.14.7 /private/tmp/claude-501/-Users-tmunzer-4-dev-mist-dewpoint/1e3145a1-199e-4b31-be1b-1e3bfd266be7/scratchpad/2b2-plan/proto/backend/.venv/bin/python
E   ImportError: cannot import name 'workers_ready' from 'dewpoint.core.platform.service' (/private/tmp/claude-501/-Users-tmunzer-4-dev-mist-dewpoint/1e3145a1-199e-4b31-be1b-1e3bfd266be7/scratchpad/2b2-plan/replay/backend/src/dewpoint/core/platform/service.py)
---------------------------- Captured stderr setup -----------------------------
security, not by bypassing it (engine 2b spec §6.3, plan 2b-1a's review)
§14; revision 7)
/private/tmp/claude-501/-Users-tmunzer-4-dev-mist-dewpoint/1e3145a1-199e-4b31-be1b-1e3bfd266be7/scratchpad/2b2-plan/replay/backend/tests/core/platform/test_workers.py:52: ImportError: cannot import name 'workers_ready' from 'dewpoint.core.platform.service' (/private/tmp/claude-501/-Users-tmunzer-4-dev-mist-dewpoint/1e3145a1-199e-4b31-be1b-1e3bfd266be7/scratchpad/2b2-plan/replay/backend/src/dewpoint/core/platform/service.py)
=========================== short test summary info ============================
FAILED tests/core/platform/test_workers.py::test_the_current_build_is_ready_when_every_live_instance_is_healthy_and_capable
FAILED tests/core/platform/test_workers.py::test_one_live_instance_unhealthy_or_lacking_a_capability_holds_the_build[capabilities0-False]
FAILED tests/core/platform/test_workers.py::test_one_live_instance_unhealthy_or_lacking_a_capability_holds_the_build[capabilities1-True]
ERROR tests/apps/dispatcher/test_observe.py - ImportError while importing tes...
ERROR tests/apps/test_environment.py - ImportError while importing test modul...
3 failed, 1 passed, 2 errors in 11.37s
```

- [ ] **Step 2: its code, then the same tests.** Replay result (exit 0), shortened:

```
...........                                                              [100%]
11 passed in 11.95s
```

- [ ] **Step 3: commit.** `git cherry-pick --no-commit d975653 && git commit -C d975653`

The diff:

```diff
diff --git a/backend/migrations/versions/0020_dispatcher_reports.py b/backend/migrations/versions/0020_dispatcher_reports.py
new file mode 100644
index 0000000..ea0b613
--- /dev/null
+++ b/backend/migrations/versions/0020_dispatcher_reports.py
@@ -0,0 +1,33 @@
+# SPDX-License-Identifier: Apache-2.0
+"""the dispatcher's and the reconciler's reports: health evidence 2b-4's readiness checks read (engine 2b spec §10.6)
+
+Each dispatcher instance records what it last did and when. A report claims nothing: 2b-4's readiness check decides
+what's recent enough. No row-level security: like `worker_instances`, it's the platform's, not a tenant's."""
+
+import sqlalchemy as sa
+from alembic import op
+from sqlalchemy.dialects import postgresql as pg
+
+revision = "0020"
+down_revision = "0019"
+branch_labels = None
+depends_on = None
+
+
+def upgrade() -> None:
+    op.create_table(
+        "dispatcher_reports",
+        sa.Column("instance_id", pg.UUID(as_uuid=True), primary_key=True),
+        sa.Column("kind", sa.String(16), nullable=False),
+        sa.Column("build_id", sa.Text, nullable=False),
+        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
+        sa.Column("reported_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
+        sa.Column("details", pg.JSONB, nullable=False, server_default="{}"),
+        sa.CheckConstraint("kind IN ('dispatcher', 'reconciler')", name="dispatcher_reports_kind"),
+    )
+    op.execute("GRANT SELECT, INSERT, UPDATE ON dispatcher_reports TO dewpoint_dispatch")
+    op.execute("GRANT SELECT ON dispatcher_reports TO dewpoint_admin")
+
+
+def downgrade() -> None:
+    op.drop_table("dispatcher_reports")
diff --git a/backend/src/dewpoint/apps/cli/main.py b/backend/src/dewpoint/apps/cli/main.py
index e952839..0f0f97d 100644
--- a/backend/src/dewpoint/apps/cli/main.py
+++ b/backend/src/dewpoint/apps/cli/main.py
@@ -351,6 +351,18 @@ def lifecycle_retire(
     typer.echo(f"{entry}: retired")
 
 
+@app.command("dispatcher")
+def dispatcher() -> None:
+    """Run the dispatcher: it starts every admitted run within its tenant's slots (engine 2b spec §7.3)."""
+    from dewpoint.apps.dispatcher.main import run as run_dispatcher
+
+    try:
+        asyncio.run(run_dispatcher(get_settings()))
+    except (EnvironmentNotRecordedError, EnvironmentMismatchError) as e:
+        typer.echo(f"ERROR: {e}")
+        raise typer.Exit(2) from None
+
+
 @app.command("worker")
 def worker() -> None:
     """Run the Temporal worker: RunGraph and its activities, and cel.evaluate when DEWPOINT_CEL_SOCKET is set."""
diff --git a/backend/src/dewpoint/apps/dispatcher/__init__.py b/backend/src/dewpoint/apps/dispatcher/__init__.py
new file mode 100644
index 0000000..a11bcc0
--- /dev/null
+++ b/backend/src/dewpoint/apps/dispatcher/__init__.py
@@ -0,0 +1,2 @@
+# SPDX-License-Identifier: Apache-2.0
+"""`dewpoint dispatcher` (engine 2b spec §7.3): the only process that starts runs."""
diff --git a/backend/src/dewpoint/apps/dispatcher/main.py b/backend/src/dewpoint/apps/dispatcher/main.py
new file mode 100644
index 0000000..034f91f
--- /dev/null
+++ b/backend/src/dewpoint/apps/dispatcher/main.py
@@ -0,0 +1,53 @@
+# SPDX-License-Identifier: Apache-2.0
+"""The dispatcher process (engine 2b spec §7.3), role `dewpoint_dispatch`. It checks the deployment's environment
+before it connects to Temporal (§2.1), encrypts every start with the tenant's key (§6.2), and each cycle observes the
+current build, dispatches what's due, and reports."""
+
+import asyncio
+import uuid
+
+import structlog
+from temporalio.client import Client
+from temporalio.service import RPCError, RPCStatusCode
+
+from dewpoint.apps.codec import KeyringKeys, data_converter
+from dewpoint.apps.dispatcher.observe import observe, report
+from dewpoint.apps.environment import verify_environment
+from dewpoint.apps.worker.deployment import describe, this_build
+from dewpoint.core.config import Settings
+from dewpoint.core.crypto.kek import KekSet
+from dewpoint.core.crypto.keyring import Keyring
+from dewpoint.core.db import make_engine, make_sessionmaker
+
+log = structlog.get_logger("dewpoint.dispatcher")
+CYCLE_S = 1.0  # between cycles
+
+
+async def current_build(client: Client) -> str | None:
+    """The build new runs start on, as Temporal reports it; None when none is current yet."""
+    try:
+        return (await describe(client)).current
+    except RPCError as e:
+        if e.status == RPCStatusCode.NOT_FOUND:
+            return None
+        raise
+
+
+async def run(settings: Settings) -> None:
+    """Raises EnvironmentNotRecordedError or EnvironmentMismatchError before connecting to Temporal."""
+    engine = make_engine(settings.database_url)
+    try:
+        sessionmaker = make_sessionmaker(engine)
+        await verify_environment(sessionmaker, settings)
+        keys = KeyringKeys(sessionmaker, Keyring(KekSet.from_settings(settings)))
+        client = await Client.connect(
+            settings.temporal_address, namespace=settings.temporal_namespace, data_converter=data_converter(keys)
+        )
+        instance = uuid.uuid4()
+        log.info("dispatcher_started", instance=str(instance), build=this_build())
+        while True:
+            build = await observe(sessionmaker, await current_build(client))
+            await report(sessionmaker, instance, build.build_id if build else "", {"current_build": bool(build)})
+            await asyncio.sleep(CYCLE_S)
+    finally:
+        await engine.dispose()
diff --git a/backend/src/dewpoint/apps/dispatcher/observe.py b/backend/src/dewpoint/apps/dispatcher/observe.py
new file mode 100644
index 0000000..64ffd45
--- /dev/null
+++ b/backend/src/dewpoint/apps/dispatcher/observe.py
@@ -0,0 +1,45 @@
+# SPDX-License-Identifier: Apache-2.0
+"""What the dispatcher observes each cycle, before any dispatch transaction (engine 2b spec §2.7, §7.3): the
+deployment's current build, as Temporal reports it, recorded with when it was observed for admission's ABI check (the
+owner's ruling on 2b-2); and the dispatcher's own report, health evidence for 2b-4's readiness checks."""
+
+import uuid
+from dataclasses import dataclass
+
+from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
+
+from dewpoint.core.platform.service import record_current_build, record_dispatcher
+from dewpoint.engine.runtime.build import abi_of
+
+# What every live instance of the current build must hold before anything is dispatched to it (§2.7).
+REQUIRED = ("cel_request_size_guard", "claim_check", "payload_codec")
+
+
+@dataclass(frozen=True)
+class Build:
+    build_id: str
+    engine_abi: int
+
+
+async def observe(sessionmaker: async_sessionmaker[AsyncSession], current: str | None) -> Build | None:
+    """The current build Temporal reported (`current`), recorded; None when there's none. An old record is then left
+    to age, so admission fails closed once it's stale. Whether its workers are ready is checked at every dispatch."""
+    abi = abi_of(current) if current else None
+    if current is None or abi is None:  # none current, or not a Dewpoint build's id
+        return None
+    build = Build(current, abi)
+    async with sessionmaker() as s, s.begin():
+        await record_current_build(s, build.build_id, build.engine_abi)
+    return build
+
+
+async def report(
+    sessionmaker: async_sessionmaker[AsyncSession],
+    instance_id: uuid.UUID,
+    build_id: str,
+    details: dict[str, object],
+    *,
+    kind: str = "dispatcher",
+) -> None:
+    async with sessionmaker() as s, s.begin():
+        await record_dispatcher(s, instance_id=instance_id, kind=kind, build_id=build_id, details=details)
diff --git a/backend/src/dewpoint/core/models/platform.py b/backend/src/dewpoint/core/models/platform.py
index 5947900..570e1bd 100644
--- a/backend/src/dewpoint/core/models/platform.py
+++ b/backend/src/dewpoint/core/models/platform.py
@@ -3,7 +3,7 @@ import uuid
 from datetime import datetime
 
 from sqlalchemy import Boolean, DateTime, SmallInteger, String, Text, func
-from sqlalchemy.dialects.postgresql import ARRAY, UUID
+from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
 from sqlalchemy.orm import Mapped, mapped_column
 
 from dewpoint.core.models.base import Base
@@ -33,3 +33,16 @@ class WorkerInstance(Base):
     healthy: Mapped[bool] = mapped_column(Boolean)
     started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
     checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
+
+
+class DispatcherReport(Base):
+    """A dispatcher instance's last report (engine 2b spec §10.6): what it did and when, as health evidence 2b-4's
+    readiness checks read. It claims nothing by itself."""
+
+    __tablename__ = "dispatcher_reports"
+    instance_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
+    kind: Mapped[str] = mapped_column(String(16))  # dispatcher | reconciler
+    build_id: Mapped[str] = mapped_column(Text)
+    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
+    reported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
+    details: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
diff --git a/backend/src/dewpoint/core/platform/service.py b/backend/src/dewpoint/core/platform/service.py
index b98ddfe..bea9021 100644
--- a/backend/src/dewpoint/core/platform/service.py
+++ b/backend/src/dewpoint/core/platform/service.py
@@ -7,12 +7,14 @@ operator's job. Its engine worker instances record what they can do (§2.7)."""
 
 import uuid
 from collections.abc import Sequence
+from datetime import timedelta
 
-from sqlalchemy import func
+from sqlalchemy import func, select
 from sqlalchemy.dialects.postgresql import insert
 from sqlalchemy.ext.asyncio import AsyncSession
 
-from dewpoint.core.models.platform import PlatformSettings, WorkerInstance
+from dewpoint.core.models.platform import DispatcherReport, PlatformSettings, WorkerInstance
+from dewpoint.core.models.requests import CurrentBuild
 
 PRODUCTION = "production"
 DEVELOPMENT = "development"
@@ -79,3 +81,57 @@ async def record_worker(
     await s.execute(
         statement.on_conflict_do_update(index_elements=["instance_id"], set_={**values, "checked_at": func.now()})
     )
+
+
+LIVE_WINDOW = timedelta(seconds=90)  # an instance that hasn't checked in since isn't live (engine 2b spec §2.7)
+
+
+async def workers_ready(s: AsyncSession, build_id: str, required: Sequence[str]) -> list[str]:
+    """What holds `build_id` back from running new work, empty when nothing does (engine 2b spec §2.7): every live
+    instance of it (checked within LIVE_WINDOW, by the statement's clock) is healthy and holds every capability in
+    `required`, and at least one exists. One fresh healthy row can't hide another live instance that lacks one."""
+    live = (
+        (
+            await s.execute(
+                select(WorkerInstance).where(
+                    WorkerInstance.build_id == build_id,
+                    WorkerInstance.checked_at >= func.statement_timestamp() - LIVE_WINDOW,
+                )
+            )
+        )
+        .scalars()
+        .all()
+    )
+    if not live:
+        return [f"No live engine worker instance of build {build_id}."]
+    problems = []
+    for instance in sorted(live, key=lambda i: str(i.instance_id)):
+        missing = sorted(set(required) - set(instance.capabilities))
+        if not instance.healthy:
+            problems.append(f"Engine worker instance {instance.instance_id} of build {build_id} isn't healthy.")
+        elif missing:
+            problems.append(
+                f"Engine worker instance {instance.instance_id} of build {build_id} lacks {', '.join(missing)}."
+            )
+    return problems
+
+
+async def record_current_build(s: AsyncSession, build_id: str, engine_abi: int) -> None:
+    """The current build as the dispatcher just read it from Temporal, and when: admission's ABI check (the owner's
+    ruling on 2b-2), which fails closed once the record is stale."""
+    values = {"build_id": build_id, "engine_abi": engine_abi, "observed_at": func.statement_timestamp()}
+    statement = insert(CurrentBuild).values(id=1, **values)
+    await s.execute(statement.on_conflict_do_update(index_elements=["id"], set_=values))
+
+
+async def record_dispatcher(
+    s: AsyncSession, *, instance_id: uuid.UUID, kind: str, build_id: str, details: dict[str, object]
+) -> None:
+    """A dispatcher instance's report, written each cycle (engine 2b spec §10.6)."""
+    statement = insert(DispatcherReport).values(instance_id=instance_id, kind=kind, build_id=build_id, details=details)
+    await s.execute(
+        statement.on_conflict_do_update(
+            index_elements=["instance_id"],
+            set_={"kind": kind, "build_id": build_id, "details": details, "reported_at": func.now()},
+        )
+    )
diff --git a/backend/tests/apps/dispatcher/__init__.py b/backend/tests/apps/dispatcher/__init__.py
new file mode 100644
index 0000000..e69de29
diff --git a/backend/tests/apps/dispatcher/test_observe.py b/backend/tests/apps/dispatcher/test_observe.py
new file mode 100644
index 0000000..7b18b08
--- /dev/null
+++ b/backend/tests/apps/dispatcher/test_observe.py
@@ -0,0 +1,44 @@
+# SPDX-License-Identifier: Apache-2.0
+"""What the dispatcher observes and records each cycle (engine 2b spec §2.7, §10.6; the owner's rulings on 2b-2): the
+current build as Temporal reports it, recorded with when it was observed for admission's ABI check, and its own report,
+health evidence that claims nothing about 2b-4's readiness gate."""
+
+import uuid
+
+import pytest
+from sqlalchemy import text
+from sqlalchemy.exc import DBAPIError
+
+from dewpoint.apps.dispatcher import observe
+
+
+async def test_the_current_build_is_recorded_with_when_it_was_observed(dispatch_sessionmaker, api_sessionmaker) -> None:
+    build = await observe.observe(dispatch_sessionmaker, "dewpoint-0.2.0+abi6")
+    assert build is not None and (build.build_id, build.engine_abi) == ("dewpoint-0.2.0+abi6", 6)
+    async with api_sessionmaker() as s:  # what admission reads
+        row = (await s.execute(text("select build_id, engine_abi, observed_at > now() - interval '5 seconds' "
+                                    "from current_build"))).one()  # fmt: skip
+    assert tuple(row) == ("dewpoint-0.2.0+abi6", 6, True)
+
+
+async def test_no_current_build_records_nothing_and_leaves_the_old_record_to_age(
+    dispatch_sessionmaker, owner_sessionmaker
+) -> None:
+    await observe.observe(dispatch_sessionmaker, "dewpoint-0.2.0+abi6")
+    assert await observe.observe(dispatch_sessionmaker, None) is None
+    async with owner_sessionmaker() as s:
+        assert (await s.execute(text("select count(*) from current_build"))).scalar_one() == 1
+
+
+async def test_the_dispatcher_reports_each_cycle_and_the_admin_reads_it(
+    dispatch_sessionmaker, admin_sessionmaker, api_sessionmaker
+) -> None:
+    instance = uuid.uuid4()
+    for dispatched in (1, 3):
+        await observe.report(dispatch_sessionmaker, instance, "dewpoint-0.2.0+abi6", {"dispatched": dispatched})
+    async with admin_sessionmaker() as s:  # 2b-4's readiness checks read it
+        row = (await s.execute(text("select kind, details, reported_at >= started_at from dispatcher_reports"))).one()
+    assert tuple(row) == ("dispatcher", {"dispatched": 3}, True)
+    with pytest.raises(DBAPIError, match="permission denied"):
+        async with api_sessionmaker() as s:
+            await s.execute(text("select count(*) from dispatcher_reports"))
diff --git a/backend/tests/apps/test_environment.py b/backend/tests/apps/test_environment.py
index 4743c1b..c8fada9 100644
--- a/backend/tests/apps/test_environment.py
+++ b/backend/tests/apps/test_environment.py
@@ -9,6 +9,7 @@ from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
 from typer.testing import CliRunner
 
 from dewpoint.apps.cli import main as cli
+from dewpoint.apps.dispatcher.main import run as run_dispatcher
 from dewpoint.apps.worker.main import run
 from dewpoint.core.config import Settings, get_settings
 from dewpoint.core.platform.service import (
@@ -56,3 +57,14 @@ def test_the_clis_temporal_commands_wont_connect_before_the_record(
     result = CliRunner().invoke(cli.app, ["deployment", "status"])
     assert result.exit_code == 2
     assert "isn't recorded" in result.output
+
+
+@pytest.mark.usefixtures("_test_users")
+async def test_a_dispatcher_wont_drive_another_namespace(
+    pg_url: str, owner_sessionmaker: async_sessionmaker[AsyncSession]
+) -> None:
+    """Engine 2b spec §2.1: every process that talks to Temporal checks its namespace first, the dispatcher too."""
+    async with owner_sessionmaker() as s, s.begin():
+        await record_environment(s, environment=DEVELOPMENT, namespace="dewpoint-dev")
+    with pytest.raises(EnvironmentMismatchError, match="configured for `default`"):
+        await run_dispatcher(worker_settings(pg_url))
diff --git a/backend/tests/core/platform/test_workers.py b/backend/tests/core/platform/test_workers.py
index 749b284..6851b5e 100644
--- a/backend/tests/core/platform/test_workers.py
+++ b/backend/tests/core/platform/test_workers.py
@@ -4,6 +4,7 @@ the dispatcher reads them."""
 
 import uuid
 
+import pytest
 from sqlalchemy import select
 
 from dewpoint.core.models.platform import WorkerInstance
@@ -28,3 +29,47 @@ async def test_an_instance_records_itself_and_each_check_updates_its_row(
         False,
     )
     assert row.checked_at >= row.started_at
+
+
+BUILD = "dewpoint-0.2.0+abi6"
+CAPABILITIES = ("cel_request_size_guard", "claim_check", "payload_codec")
+
+
+async def instances(owner, *rows: tuple[str, tuple[str, ...], bool, int]) -> None:
+    """Instance rows: their build, capabilities, health, and how many seconds ago they last checked."""
+    from sqlalchemy import text
+
+    async with owner() as s, s.begin():
+        for build, capabilities, healthy, age in rows:
+            await s.execute(
+                text("insert into worker_instances (instance_id, build_id, capabilities, healthy, checked_at) "
+                     "values (:i, :b, :c, :h, now() - make_interval(secs => :a))"),
+                {"i": uuid.uuid4(), "b": build, "c": list(capabilities), "h": healthy, "a": age},
+            )  # fmt: skip
+
+
+async def problems(dispatch) -> list[str]:
+    from dewpoint.core.platform.service import workers_ready
+
+    async with dispatch() as s, s.begin():
+        return await workers_ready(s, BUILD, CAPABILITIES)
+
+
+async def test_the_current_build_is_ready_when_every_live_instance_is_healthy_and_capable(
+    owner_sessionmaker, dispatch_sessionmaker
+) -> None:
+    """Engine 2b spec §2.7: every instance of the current build that checked in the last 90 seconds is healthy and
+    holds every required capability, and at least one does. A stale row isn't a live instance; another build's
+    instances don't count."""
+    assert await problems(dispatch_sessionmaker) == ["No live engine worker instance of build dewpoint-0.2.0+abi6."]
+    await instances(owner_sessionmaker, (BUILD, CAPABILITIES, True, 5), (BUILD, (), False, 600),
+                    ("dewpoint-0.1.0+abi5", (), False, 1))  # fmt: skip
+    assert await problems(dispatch_sessionmaker) == []
+
+
+@pytest.mark.parametrize(("capabilities", "healthy"), [(CAPABILITIES, False), (("claim_check", "payload_codec"), True)])
+async def test_one_live_instance_unhealthy_or_lacking_a_capability_holds_the_build(
+    owner_sessionmaker, dispatch_sessionmaker, capabilities, healthy
+) -> None:
+    await instances(owner_sessionmaker, (BUILD, CAPABILITIES, True, 1), (BUILD, capabilities, healthy, 2))
+    assert len(await problems(dispatch_sessionmaker)) == 1
```

### Task 8: The starting transaction, under the gate's and the tenant's locks

**Commit:** `4952a20` (prototype `proto/2b2-v2`); the replay's tree was identical: yes.

**Create:** `backend/src/dewpoint/apps/dispatcher/dispatch.py`, `backend/tests/apps/dispatcher/test_begin.py`

**Modify:** `backend/src/dewpoint/core/runs/service.py`

**What it does:**

Engine 2b spec §7.3, §7.8, §2.3–2.5; engine-core §4.5. One due request, locked with SKIP LOCKED after the production
gate's and its tenant's shared advisory locks, becomes `starting` only when every critical condition holds again: the
gate (none in development), the tenant active, every live worker instance of the current build healthy and capable,
a free slot under the tenant's limits row (its override, else the platform's default), and the tenant's key, which
opens the envelope and seals the start. Otherwise it waits, queued, no attempt counted and nothing written: waiting
isn't failing. A frozen version of another ABI is cancelled (`engine_abi_changed`, audited with both ABIs); a closure
found retired is cancelled by the defensive check (`node_type_retired`, `cel_profile_retired`) — the owner's M2
condition: a `starting` request that a forced retirement left alone and that came back to the queue is cancelled, not
started, and its earlier attempt's run row becomes terminal. Then the slot is reserved, the run's row written (an
earlier attempt's reused) and the request marked `starting`, together; the start goes out after the commit.


- [ ] **Step 1: its tests alone, before its code.** Run: `uv run pytest -n 4 tests/apps/dispatcher/test_begin.py`. Replay result (exit 1), shortened:

```
==================================== ERRORS ====================================
_____________ ERROR collecting tests/apps/dispatcher/test_begin.py _____________
ImportError while importing test module '/private/tmp/claude-501/-Users-tmunzer-4-dev-mist-dewpoint/1e3145a1-199e-4b31-be1b-1e3bfd266be7/scratchpad/2b2-plan/replay/backend/tests/apps/dispatcher/test_begin.py'.
Hint: make sure your test modules/packages have valid Python names.
Traceback:
/opt/homebrew/Cellar/python@3.14/3.14.7/Frameworks/Python.framework/Versions/3.14/lib/python3.14/importlib/__init__.py:88: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
tests/apps/dispatcher/test_begin.py:15: in <module>
    from dewpoint.apps.dispatcher import dispatch
E   ImportError: cannot import name 'dispatch' from 'dewpoint.apps.dispatcher' (/private/tmp/claude-501/-Users-tmunzer-4-dev-mist-dewpoint/1e3145a1-199e-4b31-be1b-1e3bfd266be7/scratchpad/2b2-plan/replay/backend/src/dewpoint/apps/dispatcher/__init__.py)
=========================== short test summary info ============================
ERROR tests/apps/dispatcher/test_begin.py - ImportError while importing test ...
1 error in 5.31s
```

- [ ] **Step 2: its code, then the same tests.** Replay result (exit 0), shortened:

```
...........                                                              [100%]
11 passed in 13.20s
```

- [ ] **Step 3: commit.** `git cherry-pick --no-commit 4952a20 && git commit -C 4952a20`

The diff:

```diff
diff --git a/backend/src/dewpoint/apps/dispatcher/dispatch.py b/backend/src/dewpoint/apps/dispatcher/dispatch.py
new file mode 100644
index 0000000..5367cba
--- /dev/null
+++ b/backend/src/dewpoint/apps/dispatcher/dispatch.py
@@ -0,0 +1,216 @@
+# SPDX-License-Identifier: Apache-2.0
+"""Dispatch (engine 2b spec §7.3, §7.8, §2.3–2.5; engine-core §4.5): the transaction that marks one request `starting`.
+
+It takes the production gate's lock and the request's tenant's lock, both shared (disabling the gate and erasing a
+tenant take them exclusively, §2.4, §6.5), then locks the request itself with SKIP LOCKED: another dispatcher holding
+it is passed by. In it, every critical condition is checked again (§2.3): the gate, the tenant, the current build's
+live workers and their capabilities, the frozen version executable and of the current build's ABI, a free slot, and
+the tenant's key, which seals the start. A condition that doesn't hold leaves the request queued, no attempt counted:
+waiting isn't failing (§2.5). A version the current build can't run (`engine_abi_changed`), or whose closure was
+retired (the defensive check, which should never fire), cancels the request explicitly, audited. Otherwise the slot is
+reserved, the run's row written (or an earlier attempt's reused) and the request marked `starting`, together; the start
+itself is sent after the commit, with no lock held across the call to Temporal."""
+
+import uuid
+from collections.abc import Awaitable, Callable
+from dataclasses import dataclass
+from datetime import UTC, datetime
+
+import structlog
+from sqlalchemy import func, select, text
+from sqlalchemy.dialects.postgresql import insert
+from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
+from temporalio.converter import DataConverter, WorkflowSerializationContext
+
+from dewpoint.apps.dispatcher.observe import REQUIRED, Build
+from dewpoint.core.audit import service as audit
+from dewpoint.core.claims import service as claims
+from dewpoint.core.claims.cipher import ClaimCipher
+from dewpoint.core.config import Settings
+from dewpoint.core.crypto.keys import KeySource
+from dewpoint.core.db import tenant_scope
+from dewpoint.core.models.platform import PlatformSettings
+from dewpoint.core.models.requests import RunRequest, RunSlot, TenantRunLimits
+from dewpoint.core.models.tenancy import Tenant
+from dewpoint.core.models.workflows import WorkflowVersion
+from dewpoint.core.platform.service import PRODUCTION, workers_ready
+from dewpoint.core.plugins import lifecycle
+from dewpoint.core.runs import service as runs
+from dewpoint.core.workflows.service import other_abi
+from dewpoint.engine.runtime.activities import RunInput
+from dewpoint.engine.runtime.ids import run_workflow_id
+
+log = structlog.get_logger("dewpoint.dispatcher")
+GATE_LOCK = "dewpoint:production-gate"
+
+
+def tenant_lock(tenant_id: uuid.UUID) -> str:
+    return f"dewpoint:tenant:{tenant_id}"
+
+
+@dataclass(frozen=True)
+class Starting:
+    """A request marked `starting`: what its start sends."""
+
+    request_id: uuid.UUID
+    tenant_id: uuid.UUID
+    start: RunInput
+
+
+@dataclass(frozen=True)
+class Waiting:
+    """A request left queued, no attempt counted: `gate_off`, `environment_not_recorded`, `tenant_erasing`,
+    `workers_not_ready`, `no_slot` or `key_unusable`."""
+
+    reason: str
+
+
+@dataclass(frozen=True)
+class Cancelled:
+    """A request cancelled at dispatch: `engine_abi_changed`, `node_type_retired` or `cel_profile_retired`."""
+
+    reason: str
+
+
+Seal = Callable[[RunInput], Awaitable[None]]
+
+
+def sealer(converter: DataConverter, namespace: str) -> Seal:
+    """Encrypts a start as its client will, with its tenant's key (§6.2): a key that doesn't work stops the start
+    before anything is written (§2.3). Raises whatever the codec raises."""
+
+    async def seal(start: RunInput) -> None:
+        context = WorkflowSerializationContext(
+            namespace=namespace, workflow_id=run_workflow_id(start.tenant_id, start.run_id)
+        )
+        await converter.with_context(context).encode([start])
+
+    return seal
+
+
+async def _lock(s: AsyncSession, key: str) -> None:
+    await s.execute(text("select pg_advisory_xact_lock_shared(hashtextextended(:k, 0))"), {"k": key})
+
+
+async def begin(
+    sessionmaker: async_sessionmaker[AsyncSession],
+    seal: Seal,
+    settings: Settings,
+    keys: KeySource | None = None,
+    *,
+    tenant_id: uuid.UUID,
+    request_id: uuid.UUID,
+    build: Build,
+) -> Starting | Waiting | Cancelled | None:
+    """One due request's starting transaction. None: no longer due, or another dispatcher holds it."""
+    async with sessionmaker() as s, s.begin():
+        outcome = await _begin(s, seal, settings, keys, tenant_id, request_id, build)
+        if isinstance(outcome, Waiting):
+            await s.rollback()  # nothing it wrote stays: the request waits as it was
+        return outcome
+
+
+async def _begin(
+    s: AsyncSession,
+    seal: Seal,
+    settings: Settings,
+    keys: KeySource | None,
+    tenant_id: uuid.UUID,
+    request_id: uuid.UUID,
+    build: Build,
+) -> Starting | Waiting | Cancelled | None:
+    await lifecycle.assert_read_committed(s)
+    await tenant_scope(s, tenant_id)
+    await _lock(s, GATE_LOCK)
+    await _lock(s, tenant_lock(tenant_id))
+    request = (
+        await s.execute(
+            select(RunRequest)
+            .where(
+                RunRequest.id == request_id,
+                RunRequest.status == "queued",
+                RunRequest.next_attempt_at <= func.statement_timestamp(),
+            )
+            .with_for_update(skip_locked=True)
+            .execution_options(populate_existing=True)
+        )
+    ).scalar_one_or_none()
+    if request is None or request.workflow_version_id is None:
+        return None
+    platform = await s.get(PlatformSettings, 1, populate_existing=True)
+    if platform is None:
+        return Waiting("environment_not_recorded")
+    if platform.environment == PRODUCTION and not platform.production_runs:
+        return Waiting("gate_off")
+    tenant = await s.get(Tenant, tenant_id, populate_existing=True)
+    if tenant is None or tenant.status != "active":
+        return Waiting("tenant_erasing")
+    problems = await workers_ready(s, build.build_id, REQUIRED)
+    if problems:
+        log.warning("dispatch_waiting", reason="workers_not_ready", problems=problems)
+        return Waiting("workers_not_ready")
+    version = await s.get(WorkflowVersion, request.workflow_version_id)
+    if version is None:
+        raise RuntimeError("A request frozen on a version that isn't there.")
+    entries = lifecycle.entries_for(version.closure_node_refs, version.closure_cel_profiles)
+    await lifecycle.lock_shared(s, entries)
+    blocked = lifecycle.not_executable(await lifecycle.states(s, entries))
+    if blocked:  # the defensive check: admission's locks make this impossible, but for a request that came back
+        reason = "node_type_retired" if any(e.kind == "node" for e in blocked) else "cel_profile_retired"
+        log.warning("dispatch_defensive_cancel", request_id=str(request.id), reason=reason)
+        return await _cancel(s, request, reason, {"reason": reason})
+    stale = await other_abi(s, version.closure_version_ids, build.engine_abi)
+    if stale:
+        details: dict[str, object] = {"reason": "engine_abi_changed", "version_abi": version.engine_abi,
+                                      "build_abi": build.engine_abi}  # fmt: skip
+        return await _cancel(s, request, "engine_abi_changed", details)
+    if not await _slot_free(s, tenant_id, platform):
+        return Waiting("no_slot")
+    if keys is None:
+        raise RuntimeError("Dispatch reads envelopes with the tenants' keys.")
+    try:  # the tenant's key opens the envelope and seals the start: one that doesn't work stops it (§2.3)
+        envelope = await claims.read_envelope(s, ClaimCipher(keys), tenant_id, request_id=request.id)
+        start = RunInput(
+            tenant_id=str(tenant_id),
+            run_id=str(request.id),
+            version_id=str(version.id),
+            trigger=envelope,
+            mode=request.mode,
+            max_run_duration_s=settings.max_run_duration_days * 86_400,
+            cel_schedule_to_start_s=settings.cel_schedule_to_start_s,
+        )
+        await seal(start)
+    except claims.EnvelopeUnavailableError:
+        raise  # the request's foreign key keeps its envelope: a bug, never a key's fault
+    except Exception as e:
+        log.warning("dispatch_waiting", reason="key_unusable", error=type(e).__name__)
+        return Waiting("key_unusable")
+    s.add(RunSlot(run_id=request.id, tenant_id=tenant_id))
+    await runs.precreate_run(
+        s, run_id=request.id, tenant_id=tenant_id, workflow_id=request.workflow_id, version_id=version.id,
+        mode=request.mode, started_by=request.actor_id, queued_at=request.queued_at,
+    )  # fmt: skip
+    request.status = "starting"
+    await s.flush()
+    return Starting(request.id, tenant_id, start)
+
+
+async def _slot_free(s: AsyncSession, tenant_id: uuid.UUID, platform: PlatformSettings) -> bool:
+    """Whether the tenant runs fewer root runs than its limit, under its limits row's lock (§7.5)."""
+    await s.execute(insert(TenantRunLimits).values(tenant_id=tenant_id).on_conflict_do_nothing())
+    limits = (
+        await s.execute(select(TenantRunLimits).where(TenantRunLimits.tenant_id == tenant_id).with_for_update())
+    ).scalar_one()
+    held = (await s.execute(select(func.count()).select_from(RunSlot).where(RunSlot.tenant_id == tenant_id))).scalar()
+    return int(held or 0) < (limits.max_concurrent or platform.max_concurrent_runs)
+
+
+async def _cancel(s: AsyncSession, request: RunRequest, reason: str, details: dict[str, object]) -> Cancelled:
+    """`queued` → `cancelled`, explicit and audited; the run's row an earlier attempt wrote becomes terminal (§7.8)."""
+    request.status, request.reason, request.ended_at = "cancelled", reason, datetime.now(UTC)
+    await runs.finish_run(s, request.id, status="cancelled", ended_at=datetime.now(UTC), error_code=reason,
+                          if_running=True)  # fmt: skip
+    await audit.record(s, tenant_id=request.tenant_id, actor_id=None, action="run.request.cancel",
+                       target_type="run_request", target_id=str(request.id), details=details)  # fmt: skip
+    await s.flush()
+    return Cancelled(reason)
diff --git a/backend/src/dewpoint/core/runs/service.py b/backend/src/dewpoint/core/runs/service.py
index 99b4fac..1758b1f 100644
--- a/backend/src/dewpoint/core/runs/service.py
+++ b/backend/src/dewpoint/core/runs/service.py
@@ -82,6 +82,33 @@ async def insert_run(
     return run
 
 
+async def precreate_run(
+    s: AsyncSession,
+    *,
+    run_id: uuid.UUID,
+    tenant_id: uuid.UUID,
+    workflow_id: uuid.UUID,
+    version_id: uuid.UUID,
+    mode: str,
+    started_by: uuid.UUID | None,
+    queued_at: datetime,
+) -> None:
+    """A root run's row, written at dispatch before Temporal answers (engine 2b spec §7.3): queued with its request,
+    not yet started. An earlier attempt's row is reused: a retried dispatch changes nothing."""
+    statement = insert(Run).values(
+        id=run_id,
+        tenant_id=tenant_id,
+        workflow_id=workflow_id,
+        workflow_version_id=version_id,
+        mode=mode,
+        status="running",
+        iterations=0,
+        started_by=started_by,
+        queued_at=queued_at,
+    )
+    await s.execute(statement.on_conflict_do_nothing(index_elements=["id"]))
+
+
 async def ensure_run(
     s: AsyncSession,
     *,
diff --git a/backend/tests/apps/dispatcher/test_begin.py b/backend/tests/apps/dispatcher/test_begin.py
new file mode 100644
index 0000000..c2a6843
--- /dev/null
+++ b/backend/tests/apps/dispatcher/test_begin.py
@@ -0,0 +1,180 @@
+# SPDX-License-Identifier: Apache-2.0
+"""The starting transaction (engine 2b spec §7.3, §7.8, §2.3–2.5; engine-core §4.5): one due request, locked with
+SKIP LOCKED under the gate's and its tenant's shared locks, becomes `starting` only when every critical condition holds;
+its slot is reserved and its run's row written in the same transaction. A condition that doesn't hold leaves it
+queued, no attempt counted: waiting isn't failing. A frozen version the current build can't run, or whose closure was
+retired, is cancelled explicitly, never started."""
+
+import uuid
+from typing import Any
+
+import pytest
+from sqlalchemy import text
+
+from dewpoint.apps.codec import data_converter
+from dewpoint.apps.dispatcher import dispatch
+from dewpoint.apps.dispatcher.observe import REQUIRED, Build
+from dewpoint.apps.worker.deployment import this_build
+from dewpoint.core.plugins import lifecycle
+from dewpoint.engine import ENGINE_ABI
+from tests.apps.test_admission import KEYS, TOKEN, admit, current, published
+from tests.apps.test_workflow_ops import update
+from tests.support.keys import FixtureKeys
+
+pytestmark = pytest.mark.usefixtures("development_deployment")
+BUILD = Build(this_build(), ENGINE_ABI)
+REQUEUE = text("update run_requests set status = 'queued', attempts = 1 where id = :i")
+
+
+async def workers(owner: Any, *, capabilities: tuple[str, ...] = REQUIRED, healthy: bool = True) -> None:
+    async with owner() as s, s.begin():
+        await s.execute(
+            text("insert into worker_instances (instance_id, build_id, capabilities, healthy) values (:i, :b, :c, :h)"),
+            {"i": uuid.uuid4(), "b": BUILD.build_id, "c": list(capabilities), "h": healthy},
+        )
+
+
+@pytest.fixture
+async def queued(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings) -> Any:
+    """A tenant with one admitted request, and the current build's workers ready."""
+    ctx, wf = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings)
+    await current(dispatch_sessionmaker)
+    await workers(owner_sessionmaker)
+    return ctx, wf, (await admit(api_sessionmaker, ctx, wf)).request
+
+
+async def begin(
+    dispatch_sessionmaker: Any, request: Any, settings: Any, *, keys: Any = KEYS, build: Build = BUILD
+) -> Any:
+    seal = dispatch.sealer(data_converter(keys), "default")
+    return await dispatch.begin(
+        dispatch_sessionmaker, seal, settings, keys, tenant_id=request.tenant_id, request_id=request.id, build=build
+    )
+
+
+async def state(owner: Any, request_id: uuid.UUID) -> dict[str, Any]:
+    async with owner() as s:
+        r = (await s.execute(text("select status, reason, attempts from run_requests where id = :i"),
+                             {"i": request_id})).one()  # fmt: skip
+        run = (await s.execute(text("select status, started_at, queued_at from runs where id = :i"),
+                               {"i": request_id})).first()  # fmt: skip
+        slot = (await s.execute(text("select count(*) from run_slots where run_id = :i"), {"i": request_id})).scalar()
+    return {"request": tuple(r), "run": tuple(run) if run else None, "slot": slot}
+
+
+async def test_a_due_request_becomes_starting_with_its_slot_and_its_runs_row(
+    queued, owner_sessionmaker, dispatch_sessionmaker, api_settings
+) -> None:
+    ctx, _, request = queued
+    starting = await begin(dispatch_sessionmaker, request, api_settings)
+    assert isinstance(starting, dispatch.Starting)
+    start = starting.start
+    assert (start.tenant_id, start.run_id, start.version_id) == (
+        str(ctx.tenant_id), str(request.id), str(request.workflow_version_id),
+    )  # fmt: skip
+    assert set(start.trigger) == {"token", "site"} and TOKEN not in str(start.trigger)  # the envelope, with a handle
+    after = await state(owner_sessionmaker, request.id)
+    assert after["request"] == ("starting", None, 0) and after["slot"] == 1
+    assert after["run"][:2] == ("running", None) and after["run"][2] == request.queued_at  # queued, not yet started
+
+
+async def test_a_runs_row_from_an_earlier_attempt_is_reused(
+    queued, owner_sessionmaker, dispatch_sessionmaker, api_settings
+) -> None:
+    _, _, request = queued
+    assert isinstance(await begin(dispatch_sessionmaker, request, api_settings), dispatch.Starting)
+    async with owner_sessionmaker() as s, s.begin():  # a confirmed refusal put it back in the queue (§7.8)
+        await s.execute(
+            text("update run_requests set status = 'queued', attempts = 1 where id = :i"), {"i": request.id}
+        )
+        await s.execute(text("delete from run_slots"))
+    assert isinstance(await begin(dispatch_sessionmaker, request, api_settings), dispatch.Starting)
+    async with owner_sessionmaker() as s:
+        assert (await s.execute(text("select count(*) from runs"))).scalar_one() == 1
+
+
+@pytest.mark.parametrize("breaks", ["gate_off", "workers_not_ready", "no_slot", "tenant_erasing", "key_unusable"])
+async def test_a_condition_that_doesnt_hold_leaves_the_request_queued_without_an_attempt(
+    queued, owner_sessionmaker, dispatch_sessionmaker, api_settings, breaks
+) -> None:
+    ctx, _, request = queued
+    keys: Any = KEYS
+    async with owner_sessionmaker() as s, s.begin():
+        if breaks == "gate_off":  # a production deployment's gate (§2.3); a development one has none
+            await s.execute(text("alter table platform_settings disable trigger user"))
+            await s.execute(text("update platform_settings set environment = 'production', production_runs = false"))
+            await s.execute(text("alter table platform_settings enable trigger user"))
+        elif breaks == "workers_not_ready":
+            await s.execute(text("update worker_instances set healthy = false"))
+        elif breaks == "no_slot":
+            await s.execute(text("insert into tenant_run_limits (tenant_id, max_concurrent) values (:t, 1)"),
+                            {"t": ctx.tenant_id})  # fmt: skip
+            await s.execute(text("insert into run_slots (run_id, tenant_id) values (:r, :t)"),
+                            {"r": uuid.uuid4(), "t": ctx.tenant_id})  # fmt: skip
+        elif breaks == "tenant_erasing":
+            await s.execute(text("update tenants set status = 'erasing' where id = :t"), {"t": ctx.tenant_id})
+    if breaks == "key_unusable":  # the start is sealed with the tenant's key before anything is written (§2.3)
+        keys = FixtureKeys(missing={str(ctx.tenant_id)})
+    waiting = await begin(dispatch_sessionmaker, request, api_settings, keys=keys)
+    assert waiting == dispatch.Waiting(breaks)
+    assert await state(owner_sessionmaker, request.id) == {"request": ("queued", None, 0), "run": None, "slot": 0}
+
+
+async def test_the_platforms_default_limit_holds_without_a_tenant_override(
+    queued, owner_sessionmaker, api_sessionmaker, dispatch_sessionmaker, api_settings
+) -> None:
+    ctx, wf, first = queued
+    async with owner_sessionmaker() as s, s.begin():
+        await s.execute(text("update platform_settings set max_concurrent_runs = 1"))
+    second = (await admit(api_sessionmaker, ctx, wf, key="k2")).request
+    assert isinstance(await begin(dispatch_sessionmaker, first, api_settings), dispatch.Starting)
+    assert await begin(dispatch_sessionmaker, second, api_settings) == dispatch.Waiting("no_slot")
+
+
+async def test_a_frozen_version_the_current_build_cant_run_is_cancelled_at_dispatch(
+    queued, owner_sessionmaker, dispatch_sessionmaker, api_settings
+) -> None:
+    """Engine-core §4.5: `engine_abi_changed`, explicit and audited with both ABIs, never a failure later."""
+    ctx, _, request = queued
+    other = Build(f"dewpoint-9.9.9+abi{ENGINE_ABI + 1}", ENGINE_ABI + 1)
+    await workers(owner_sessionmaker)
+    async with owner_sessionmaker() as s, s.begin():
+        await s.execute(text("update worker_instances set build_id = :b"), {"b": other.build_id})
+    assert await begin(dispatch_sessionmaker, request, api_settings, build=other) == dispatch.Cancelled(
+        "engine_abi_changed"
+    )
+    assert (await state(owner_sessionmaker, request.id))["request"][:2] == ("cancelled", "engine_abi_changed")
+    async with owner_sessionmaker() as s:
+        details = (await s.execute(text("select details from audit_log where action = 'run.request.cancel'"))).scalar()
+    assert details == {"reason": "engine_abi_changed", "version_abi": ENGINE_ABI, "build_abi": ENGINE_ABI + 1}
+
+
+async def test_a_starting_request_back_in_the_queue_after_its_closure_was_retired_is_cancelled_not_started(
+    queued, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings
+) -> None:
+    """The owner's M2 condition: a forced retirement leaves a `starting` request alone; if it comes back to the queue
+    (a confirmed refusal), dispatch's defensive check cancels it, audited, and the run's row an earlier attempt wrote
+    becomes terminal with it (§7.8). Nothing starts."""
+    ctx, wf, request = queued
+    assert isinstance(await begin(dispatch_sessionmaker, request, api_settings), dispatch.Starting)
+    await update(api_sessionmaker, ctx, wf, enabled=False)
+    async with admin_sessionmaker() as s, s.begin():
+        assert (await lifecycle.retire(s, lifecycle.Entry("node", "testkit.echo@1"), force=True, confirm=True)).applied
+    assert (await state(owner_sessionmaker, request.id))["request"][0] == "starting"  # left alone
+    async with owner_sessionmaker() as s, s.begin():  # Temporal refused it: back in the queue, its slot released
+        await s.execute(
+            text("update run_requests set status = 'queued', attempts = 1 where id = :i"), {"i": request.id}
+        )
+        await s.execute(text("delete from run_slots"))
+    assert await begin(dispatch_sessionmaker, request, api_settings) == dispatch.Cancelled("node_type_retired")
+    after = await state(owner_sessionmaker, request.id)
+    assert after["request"][:2] == ("cancelled", "node_type_retired") and after["slot"] == 0
+    assert after["run"][0] == "cancelled"
+
+
+async def test_a_request_another_dispatcher_holds_is_skipped(queued, dispatch_sessionmaker, api_settings) -> None:
+    _, _, request = queued
+    async with dispatch_sessionmaker() as s, s.begin():
+        await s.execute(text("select set_config('app.tenant_id', :t, true)"), {"t": str(request.tenant_id)})
+        await s.execute(text("select 1 from run_requests where id = :i for update"), {"i": request.id})
+        assert await begin(dispatch_sessionmaker, request, api_settings) is None
```

### Task 9: Start a starting request, apply its outcome, and run a dispatch cycle

**Commit:** `1f55f0e` (prototype `proto/2b2-v2`); the replay's tree was identical: yes.

**Create:** `backend/tests/apps/dispatcher/conftest.py`, `backend/tests/apps/dispatcher/support.py`, `backend/tests/apps/dispatcher/test_start.py`

**Modify:** `backend/src/dewpoint/apps/dispatcher/dispatch.py`, `backend/src/dewpoint/apps/dispatcher/main.py`, `backend/tests/apps/dispatcher/test_begin.py`, `backend/tests/apps/test_runs.py`

**What it does:**

A start is REJECT_DUPLICATE under the run's server-built id with its own
deadline; its answer is classified with no transaction open. A confirmed
refusal counts an attempt and backs off (5 s doubling, capped at 10 min);
the 10th makes the request dead and fails its run with start_failed. A
throttled start re-queues with no attempt; an uncertain one stays
starting with its slot held. Already-started counts only once the
execution's started event decodes to this request; anything else is an
id collision. Confirmation is idempotent and late-safe.


- [ ] **Step 1: its tests alone, before its code.** Run: `uv run pytest -n 4 tests/apps/dispatcher/test_begin.py tests/apps/dispatcher/test_start.py tests/apps/test_runs.py`. Replay result (exit 1), shortened:

```
=========================== short test summary info ============================
FAILED tests/apps/dispatcher/test_start.py::test_an_accepted_start_marks_the_request_started_and_its_run_started
FAILED tests/apps/dispatcher/test_start.py::test_a_confirmed_refusal_counts_an_attempt_and_waits_its_backoff_with_the_slot_released
FAILED tests/apps/dispatcher/test_start.py::test_a_late_confirmation_never_changes_a_run_that_already_ended
FAILED tests/apps/dispatcher/test_start.py::test_an_uncertain_start_counts_nothing_and_holds_its_slot[answer1]
FAILED tests/apps/dispatcher/test_start.py::test_a_cycle_starts_each_tenants_oldest_due_request
FAILED tests/apps/dispatcher/test_start.py::test_the_backoff_doubles_from_5_seconds_and_stops_at_10_minutes
FAILED tests/apps/dispatcher/test_start.py::test_an_uncertain_start_counts_nothing_and_holds_its_slot[answer2]
FAILED tests/apps/dispatcher/test_start.py::test_the_tenth_confirmed_refusal_makes_the_request_dead_and_fails_its_run
FAILED tests/apps/dispatcher/test_start.py::test_already_started_is_verified_from_the_executions_own_start
FAILED tests/apps/dispatcher/test_start.py::test_a_busy_temporal_puts_the_request_back_without_an_attempt
FAILED tests/apps/dispatcher/test_start.py::test_an_uncertain_start_counts_nothing_and_holds_its_slot[answer0]
FAILED tests/apps/dispatcher/test_start.py::test_another_execution_under_the_runs_id_is_an_id_collision
12 failed, 40 passed in 15.75s
```

- [ ] **Step 2: its code, then the same tests.** Replay result (exit 0), shortened:

```
....................................................                     [100%]
52 passed in 15.47s
```

- [ ] **Step 3: commit.** `git cherry-pick --no-commit 1f55f0e && git commit -C 1f55f0e`

The diff:

```diff
diff --git a/backend/src/dewpoint/apps/dispatcher/dispatch.py b/backend/src/dewpoint/apps/dispatcher/dispatch.py
index 5367cba..c0e43c1 100644
--- a/backend/src/dewpoint/apps/dispatcher/dispatch.py
+++ b/backend/src/dewpoint/apps/dispatcher/dispatch.py
@@ -12,16 +12,23 @@ reserved, the run's row written (or an earlier attempt's reused) and the request
 itself is sent after the commit, with no lock held across the call to Temporal."""
 
 import uuid
+from collections import Counter
 from collections.abc import Awaitable, Callable
 from dataclasses import dataclass
-from datetime import UTC, datetime
+from datetime import UTC, datetime, timedelta
+from typing import Any
 
 import structlog
 from sqlalchemy import func, select, text
 from sqlalchemy.dialects.postgresql import insert
 from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
+from temporalio.client import Client
+from temporalio.common import WorkflowIDReusePolicy
 from temporalio.converter import DataConverter, WorkflowSerializationContext
+from temporalio.exceptions import WorkflowAlreadyStartedError
+from temporalio.service import RPCError, RPCStatusCode
 
+from dewpoint.apps.codec import CodecRefusedError
 from dewpoint.apps.dispatcher.observe import REQUIRED, Build
 from dewpoint.core.audit import service as audit
 from dewpoint.core.claims import service as claims
@@ -37,11 +44,26 @@ from dewpoint.core.platform.service import PRODUCTION, workers_ready
 from dewpoint.core.plugins import lifecycle
 from dewpoint.core.runs import service as runs
 from dewpoint.core.workflows.service import other_abi
-from dewpoint.engine.runtime.activities import RunInput
+from dewpoint.engine.runtime.activities import ENGINE_QUEUE, RunInput
 from dewpoint.engine.runtime.ids import run_workflow_id
+from dewpoint.engine.runtime.workflow import RunGraph
 
 log = structlog.get_logger("dewpoint.dispatcher")
 GATE_LOCK = "dewpoint:production-gate"
+START_DEADLINE = timedelta(seconds=10)  # a start's own deadline: the reconciler's grace period is longer (§7.6)
+MAX_ATTEMPTS = 10  # confirmed refusals before a request is dead (§7.4)
+CANDIDATES = 50  # tenants picked per cycle, each its oldest due request
+START_REFUSED = "start_refused"
+ID_COLLISION = "id_collision"
+START_FAILED = "start_failed"
+REFUSED_MESSAGE = "Temporal refused the run's start 10 times (engine 2b spec §7.4)."
+COLLISION_MESSAGE = "Another execution holds this run's workflow id (engine 2b spec §7.4)."
+# A status Temporal answers with when it certainly refused the start (2a's rule, `apps.runs`).
+REFUSED = {
+    RPCStatusCode.INVALID_ARGUMENT, RPCStatusCode.NOT_FOUND, RPCStatusCode.PERMISSION_DENIED,
+    RPCStatusCode.UNAUTHENTICATED, RPCStatusCode.FAILED_PRECONDITION, RPCStatusCode.OUT_OF_RANGE,
+    RPCStatusCode.UNIMPLEMENTED,
+}  # fmt: skip
 
 
 def tenant_lock(tenant_id: uuid.UUID) -> str:
@@ -214,3 +236,151 @@ async def _cancel(s: AsyncSession, request: RunRequest, reason: str, details: di
                        target_type="run_request", target_id=str(request.id), details=details)  # fmt: skip
     await s.flush()
     return Cancelled(reason)
+
+
+# --- the start, and what its outcome does (§7.4, §7.8) -------------------------------------------------------------
+
+
+@dataclass(frozen=True)
+class Outcome:
+    """What a start's answer means: `started` (accepted, or a verified duplicate, at `at` when Temporal says),
+    `refused` (an attempt), `throttled` (certainly not started, no attempt), `collision` or `uncertain`."""
+
+    kind: str
+    at: datetime | None = None
+    detail: str = ""
+
+
+def backoff(attempts: int) -> timedelta:
+    """The wait before the next attempt after `attempts` confirmed refusals: 5 s, doubling, capped at 10 min."""
+    return timedelta(seconds=min(5 * 2 ** (attempts - 1), 600))
+
+
+async def start(client: Client, starting: Starting) -> Outcome:
+    """One start, `REJECT_DUPLICATE` under the run's server-built id (§6.1), with its own deadline. Its answer is
+    classified, never acted on here: no transaction is open across the call."""
+    workflow_id = run_workflow_id(starting.start.tenant_id, starting.start.run_id)
+    try:
+        await client.start_workflow(
+            RunGraph.run, starting.start, id=workflow_id, task_queue=ENGINE_QUEUE,
+            id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE, rpc_timeout=START_DEADLINE,
+        )  # fmt: skip
+        return Outcome("started")
+    except WorkflowAlreadyStartedError:
+        return await verify(client, starting)
+    except CodecRefusedError:  # the client seals the start again, and failed: it was never sent
+        return Outcome("throttled", detail="unsealed")
+    except RPCError as e:
+        if e.status in REFUSED:
+            return Outcome("refused", detail=e.status.name)
+        if e.status == RPCStatusCode.RESOURCE_EXHAUSTED:  # throttled before anything was created
+            return Outcome("throttled", detail=e.status.name)
+        return Outcome("uncertain", detail=e.status.name)
+    except Exception as e:  # a lost connection or a timeout: it may have been accepted
+        return Outcome("uncertain", detail=type(e).__name__)
+
+
+async def verify(client: Client, starting: Starting) -> Outcome:
+    """ "Already started" counts only once the execution's own start names this request (§7.4): its started event's
+    input, decoded with the tenant's key, has the request's tenant, run id, frozen version, mode and envelope.
+    Anything else is an id collision, which the server-built ids make impossible. A history that can't be read leaves
+    the start uncertain, for the reconciler."""
+    workflow_id = run_workflow_id(starting.start.tenant_id, starting.start.run_id)
+    try:
+        first: Any = None
+        async for event in client.get_workflow_handle(workflow_id).fetch_history_events():
+            first = event
+            break
+        attributes = first.workflow_execution_started_event_attributes
+        context = WorkflowSerializationContext(namespace=client.namespace, workflow_id=workflow_id)
+        [found] = await client.data_converter.with_context(context).decode(attributes.input.payloads, [RunInput])
+    except Exception as e:
+        return Outcome("uncertain", detail=f"unverified ({type(e).__name__})")
+    ours, theirs = starting.start, found
+    same = (theirs.tenant_id, theirs.run_id, theirs.version_id, theirs.mode, theirs.trigger) == (
+        ours.tenant_id, ours.run_id, ours.version_id, ours.mode, ours.trigger,
+    )  # fmt: skip
+    if not same:
+        return Outcome("collision")
+    return Outcome("started", at=first.event_time.ToDatetime(tzinfo=UTC))
+
+
+async def settle(sessionmaker: async_sessionmaker[AsyncSession], starting: Starting, outcome: Outcome) -> str:
+    """The outcome applied to the request, its slot and its run's row in one transaction (§7.8); what happened, for
+    the cycle's report. A request no longer `starting` (the reconciler settled it) is left as it is."""
+    async with sessionmaker() as s, s.begin():
+        await tenant_scope(s, starting.tenant_id)
+        request = (
+            await s.execute(
+                select(RunRequest)
+                .where(RunRequest.id == starting.request_id)
+                .with_for_update()
+                .execution_options(populate_existing=True)
+            )
+        ).scalar_one()
+        if request.status != "starting":
+            return "moved"
+        if outcome.kind == "started":
+            await confirm(s, request, outcome.at)
+            return "started"
+        if outcome.kind == "uncertain":
+            log.warning("start_uncertain", request_id=str(request.id), detail=outcome.detail)
+            return "uncertain"  # starting, its slot held, for the reconciler (§7.6)
+        await _release(s, request.id)
+        if outcome.kind == "throttled":
+            request.status, request.next_attempt_at = "queued", datetime.now(UTC) + backoff(1)
+            return "throttled"
+        if outcome.kind == "collision":
+            log.error("start_id_collision", request_id=str(request.id))
+            await _dead(s, request, ID_COLLISION, COLLISION_MESSAGE)
+            return "dead"
+        request.attempts += 1
+        if request.attempts >= MAX_ATTEMPTS:
+            await _dead(s, request, START_REFUSED, REFUSED_MESSAGE)
+            return "dead"
+        request.status, request.next_attempt_at = "queued", datetime.now(UTC) + backoff(request.attempts)
+        return "refused"
+
+
+async def confirm(s: AsyncSession, request: RunRequest, at: datetime | None) -> None:
+    """`starting` → `started`, idempotent and late-safe (§7.8): the run's `started_at` is set only if it has none, a
+    terminal status is never overwritten, and no slot is reserved again (the root's end write releases it)."""
+    request.status = "started"
+    await s.execute(
+        text("update runs set started_at = coalesce(started_at, :at) where id = :i"),
+        {"at": at or datetime.now(UTC), "i": request.id},
+    )
+
+
+async def _release(s: AsyncSession, run_id: uuid.UUID) -> None:
+    await s.execute(text("delete from run_slots where run_id = :i"), {"i": run_id})
+
+
+async def _dead(s: AsyncSession, request: RunRequest, reason: str, message: str) -> None:
+    """`starting` → `dead`: terminal, its run failed with `start_failed`, its slot released (§7.8). Admins see it; a
+    retry is a re-run."""
+    request.status, request.reason, request.ended_at = "dead", reason, datetime.now(UTC)
+    await runs.finish_run(s, request.id, status="failed", ended_at=datetime.now(UTC), error_code=START_FAILED,
+                          error_message=message, if_running=True)  # fmt: skip
+    await audit.record(s, tenant_id=request.tenant_id, actor_id=None, action="run.request.dead",
+                       target_type="run_request", target_id=str(request.id), details={"reason": reason})  # fmt: skip
+
+
+async def dispatch_once(
+    sessionmaker: async_sessionmaker[AsyncSession], client: Client, keys: KeySource, settings: Settings, build: Build
+) -> dict[str, int]:
+    """One cycle: each tenant's oldest due request, picked through `dispatch_candidates` (queue-selection metadata
+    only), begun, started and settled in turn. What happened, counted, for the report."""
+    seal = sealer(client.data_converter, client.namespace)
+    async with sessionmaker() as s:
+        picked = (await s.execute(text("select tenant_id, request_id from dispatch_candidates(:n)"),
+                                  {"n": CANDIDATES})).all()  # fmt: skip
+    counts: Counter[str] = Counter()
+    for tenant_id, request_id in picked:
+        outcome = await begin(sessionmaker, seal, settings, keys, tenant_id=tenant_id, request_id=request_id,
+                              build=build)  # fmt: skip
+        if isinstance(outcome, Starting):
+            counts[await settle(sessionmaker, outcome, await start(client, outcome))] += 1
+        elif outcome is not None:
+            counts[outcome.reason] += 1
+    return dict(counts)
diff --git a/backend/src/dewpoint/apps/dispatcher/main.py b/backend/src/dewpoint/apps/dispatcher/main.py
index 034f91f..2755058 100644
--- a/backend/src/dewpoint/apps/dispatcher/main.py
+++ b/backend/src/dewpoint/apps/dispatcher/main.py
@@ -11,6 +11,7 @@ from temporalio.client import Client
 from temporalio.service import RPCError, RPCStatusCode
 
 from dewpoint.apps.codec import KeyringKeys, data_converter
+from dewpoint.apps.dispatcher.dispatch import dispatch_once
 from dewpoint.apps.dispatcher.observe import observe, report
 from dewpoint.apps.environment import verify_environment
 from dewpoint.apps.worker.deployment import describe, this_build
@@ -47,7 +48,10 @@ async def run(settings: Settings) -> None:
         log.info("dispatcher_started", instance=str(instance), build=this_build())
         while True:
             build = await observe(sessionmaker, await current_build(client))
-            await report(sessionmaker, instance, build.build_id if build else "", {"current_build": bool(build)})
+            done = await dispatch_once(sessionmaker, client, keys, settings, build) if build else {}
+            await report(
+                sessionmaker, instance, build.build_id if build else "", {"current_build": bool(build), **done}
+            )
             await asyncio.sleep(CYCLE_S)
     finally:
         await engine.dispose()
diff --git a/backend/tests/apps/dispatcher/conftest.py b/backend/tests/apps/dispatcher/conftest.py
new file mode 100644
index 0000000..733d2b5
--- /dev/null
+++ b/backend/tests/apps/dispatcher/conftest.py
@@ -0,0 +1,17 @@
+# SPDX-License-Identifier: Apache-2.0
+from typing import Any
+
+import pytest
+
+from tests.apps.dispatcher.support import workers
+from tests.apps.test_admission import admit, current, published
+from tests.apps.worker.conftest import env  # noqa: F401  (the time-skipping test server, for the start tests)
+
+
+@pytest.fixture
+async def queued(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings) -> Any:
+    """A tenant with one admitted request, and the current build's workers ready."""
+    ctx, wf = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings)
+    await current(dispatch_sessionmaker)
+    await workers(owner_sessionmaker)
+    return ctx, wf, (await admit(api_sessionmaker, ctx, wf)).request
diff --git a/backend/tests/apps/dispatcher/support.py b/backend/tests/apps/dispatcher/support.py
new file mode 100644
index 0000000..1359a71
--- /dev/null
+++ b/backend/tests/apps/dispatcher/support.py
@@ -0,0 +1,43 @@
+# SPDX-License-Identifier: Apache-2.0
+"""Shared helpers for the dispatcher's tests: the current build, its ready workers, one begin, and a request's state."""
+
+import uuid
+from typing import Any
+
+from sqlalchemy import text
+
+from dewpoint.apps.codec import data_converter
+from dewpoint.apps.dispatcher import dispatch
+from dewpoint.apps.dispatcher.observe import REQUIRED, Build
+from dewpoint.apps.worker.deployment import this_build
+from dewpoint.engine import ENGINE_ABI
+from tests.apps.test_admission import KEYS
+
+BUILD = Build(this_build(), ENGINE_ABI)
+
+
+async def workers(owner: Any, *, capabilities: tuple[str, ...] = REQUIRED, healthy: bool = True) -> None:
+    async with owner() as s, s.begin():
+        await s.execute(
+            text("insert into worker_instances (instance_id, build_id, capabilities, healthy) values (:i, :b, :c, :h)"),
+            {"i": uuid.uuid4(), "b": BUILD.build_id, "c": list(capabilities), "h": healthy},
+        )
+
+
+async def begin(
+    dispatch_sessionmaker: Any, request: Any, settings: Any, *, keys: Any = KEYS, build: Build = BUILD
+) -> Any:
+    seal = dispatch.sealer(data_converter(keys), "default")
+    return await dispatch.begin(
+        dispatch_sessionmaker, seal, settings, keys, tenant_id=request.tenant_id, request_id=request.id, build=build
+    )
+
+
+async def state(owner: Any, request_id: uuid.UUID) -> dict[str, Any]:
+    async with owner() as s:
+        r = (await s.execute(text("select status, reason, attempts from run_requests where id = :i"),
+                             {"i": request_id})).one()  # fmt: skip
+        run = (await s.execute(text("select status, started_at, queued_at from runs where id = :i"),
+                               {"i": request_id})).first()  # fmt: skip
+        slot = (await s.execute(text("select count(*) from run_slots where run_id = :i"), {"i": request_id})).scalar()
+    return {"request": tuple(r), "run": tuple(run) if run else None, "slot": slot}
diff --git a/backend/tests/apps/dispatcher/test_begin.py b/backend/tests/apps/dispatcher/test_begin.py
index c2a6843..d620108 100644
--- a/backend/tests/apps/dispatcher/test_begin.py
+++ b/backend/tests/apps/dispatcher/test_begin.py
@@ -11,55 +11,16 @@ from typing import Any
 import pytest
 from sqlalchemy import text
 
-from dewpoint.apps.codec import data_converter
 from dewpoint.apps.dispatcher import dispatch
-from dewpoint.apps.dispatcher.observe import REQUIRED, Build
-from dewpoint.apps.worker.deployment import this_build
+from dewpoint.apps.dispatcher.observe import Build
 from dewpoint.core.plugins import lifecycle
 from dewpoint.engine import ENGINE_ABI
-from tests.apps.test_admission import KEYS, TOKEN, admit, current, published
+from tests.apps.dispatcher.support import begin, state, workers
+from tests.apps.test_admission import KEYS, TOKEN, admit
 from tests.apps.test_workflow_ops import update
 from tests.support.keys import FixtureKeys
 
 pytestmark = pytest.mark.usefixtures("development_deployment")
-BUILD = Build(this_build(), ENGINE_ABI)
-REQUEUE = text("update run_requests set status = 'queued', attempts = 1 where id = :i")
-
-
-async def workers(owner: Any, *, capabilities: tuple[str, ...] = REQUIRED, healthy: bool = True) -> None:
-    async with owner() as s, s.begin():
-        await s.execute(
-            text("insert into worker_instances (instance_id, build_id, capabilities, healthy) values (:i, :b, :c, :h)"),
-            {"i": uuid.uuid4(), "b": BUILD.build_id, "c": list(capabilities), "h": healthy},
-        )
-
-
-@pytest.fixture
-async def queued(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings) -> Any:
-    """A tenant with one admitted request, and the current build's workers ready."""
-    ctx, wf = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings)
-    await current(dispatch_sessionmaker)
-    await workers(owner_sessionmaker)
-    return ctx, wf, (await admit(api_sessionmaker, ctx, wf)).request
-
-
-async def begin(
-    dispatch_sessionmaker: Any, request: Any, settings: Any, *, keys: Any = KEYS, build: Build = BUILD
-) -> Any:
-    seal = dispatch.sealer(data_converter(keys), "default")
-    return await dispatch.begin(
-        dispatch_sessionmaker, seal, settings, keys, tenant_id=request.tenant_id, request_id=request.id, build=build
-    )
-
-
-async def state(owner: Any, request_id: uuid.UUID) -> dict[str, Any]:
-    async with owner() as s:
-        r = (await s.execute(text("select status, reason, attempts from run_requests where id = :i"),
-                             {"i": request_id})).one()  # fmt: skip
-        run = (await s.execute(text("select status, started_at, queued_at from runs where id = :i"),
-                               {"i": request_id})).first()  # fmt: skip
-        slot = (await s.execute(text("select count(*) from run_slots where run_id = :i"), {"i": request_id})).scalar()
-    return {"request": tuple(r), "run": tuple(run) if run else None, "slot": slot}
 
 
 async def test_a_due_request_becomes_starting_with_its_slot_and_its_runs_row(
diff --git a/backend/tests/apps/dispatcher/test_start.py b/backend/tests/apps/dispatcher/test_start.py
new file mode 100644
index 0000000..03ae6de
--- /dev/null
+++ b/backend/tests/apps/dispatcher/test_start.py
@@ -0,0 +1,165 @@
+# SPDX-License-Identifier: Apache-2.0
+"""A start and its outcome (engine 2b spec §7.4, §7.8): only a confirmed refusal counts as an attempt, backing off
+(5 s, doubling, capped at 10 min) until the 10th makes the request `dead` and fails its run with `start_failed`; an
+uncertain start counts as nothing and stays `starting`, its slot held, for the reconciler; "already started" is
+verified from the execution's own start before it counts, else it's an id collision. Confirmation is idempotent and
+late-safe: it never changes a run that already ended, nor reserves its slot again."""
+
+import uuid
+from datetime import timedelta
+from typing import Any
+
+import pytest
+from sqlalchemy import text
+from temporalio.common import WorkflowIDReusePolicy
+from temporalio.service import RPCStatusCode
+
+from dewpoint.apps.dispatcher import dispatch
+from dewpoint.engine.runtime.activities import ENGINE_QUEUE
+from dewpoint.engine.runtime.ids import run_workflow_id
+from dewpoint.engine.runtime.workflow import RunGraph
+from tests.apps.dispatcher.support import BUILD, begin, state, workers
+from tests.apps.test_admission import KEYS, admit, current, published
+from tests.apps.test_runs import FakeClient, LostAck, rpc
+
+pytestmark = pytest.mark.usefixtures("development_deployment")
+
+
+async def started(dispatch_sessionmaker: Any, request: Any, settings: Any) -> dispatch.Starting:
+    starting = await begin(dispatch_sessionmaker, request, settings)
+    assert isinstance(starting, dispatch.Starting)
+    return starting
+
+
+async def through(dispatch_sessionmaker: Any, starting: dispatch.Starting, client: Any) -> str:
+    return await dispatch.settle(dispatch_sessionmaker, starting, await dispatch.start(client, starting))
+
+
+async def test_an_accepted_start_marks_the_request_started_and_its_run_started(
+    queued, owner_sessionmaker, dispatch_sessionmaker, api_settings
+) -> None:
+    _, _, request = queued
+    client = FakeClient()
+    assert await through(dispatch_sessionmaker, await started(dispatch_sessionmaker, request, api_settings),
+                         client) == "started"  # fmt: skip
+    assert client.calls == [(run_workflow_id(str(request.tenant_id), str(request.id)),
+                             WorkflowIDReusePolicy.REJECT_DUPLICATE)]  # fmt: skip
+    after = await state(owner_sessionmaker, request.id)
+    assert after["request"] == ("started", None, 0) and after["run"][1] is not None and after["slot"] == 1
+
+
+async def test_a_confirmed_refusal_counts_an_attempt_and_waits_its_backoff_with_the_slot_released(
+    queued, owner_sessionmaker, dispatch_sessionmaker, api_settings
+) -> None:
+    _, _, request = queued
+    starting = await started(dispatch_sessionmaker, request, api_settings)
+    assert await through(dispatch_sessionmaker, starting, FakeClient(rpc(RPCStatusCode.INVALID_ARGUMENT))) == "refused"
+    after = await state(owner_sessionmaker, request.id)
+    assert after["request"] == ("queued", None, 1) and after["slot"] == 0 and after["run"][:2] == ("running", None)
+    async with owner_sessionmaker() as s:
+        wait = (await s.execute(text("select next_attempt_at - now() from run_requests"))).scalar_one()
+    assert timedelta(seconds=4) < wait <= timedelta(seconds=5)
+    assert await begin(dispatch_sessionmaker, request, api_settings) is None  # not due before its backoff ends
+
+
+def test_the_backoff_doubles_from_5_seconds_and_stops_at_10_minutes() -> None:
+    assert [dispatch.backoff(n).total_seconds() for n in (1, 2, 3, 8, 9, 10)] == [5, 10, 20, 600, 600, 600]
+
+
+async def test_the_tenth_confirmed_refusal_makes_the_request_dead_and_fails_its_run(
+    queued, owner_sessionmaker, dispatch_sessionmaker, api_settings
+) -> None:
+    _, _, request = queued
+    starting = await started(dispatch_sessionmaker, request, api_settings)
+    async with owner_sessionmaker() as s, s.begin():
+        await s.execute(text("update run_requests set attempts = 9"))
+    assert await through(dispatch_sessionmaker, starting, FakeClient(rpc(RPCStatusCode.FAILED_PRECONDITION))) == "dead"
+    after = await state(owner_sessionmaker, request.id)
+    assert after["request"] == ("dead", "start_refused", 10) and after["slot"] == 0 and after["run"][0] == "failed"
+    async with owner_sessionmaker() as s:
+        run = (await s.execute(text("select error_code from runs"))).scalar_one()
+        audited = (await s.execute(text("select count(*) from audit_log where action = 'run.request.dead'"))).scalar()
+    assert (run, audited) == ("start_failed", 1)
+
+
+@pytest.mark.parametrize("answer", [rpc(RPCStatusCode.UNAVAILABLE), LostAck(TimeoutError()), ConnectionResetError()])
+async def test_an_uncertain_start_counts_nothing_and_holds_its_slot(
+    queued, owner_sessionmaker, dispatch_sessionmaker, api_settings, answer
+) -> None:
+    _, _, request = queued
+    starting = await started(dispatch_sessionmaker, request, api_settings)
+    assert await through(dispatch_sessionmaker, starting, FakeClient(answer)) == "uncertain"
+    after = await state(owner_sessionmaker, request.id)
+    assert after["request"] == ("starting", None, 0) and after["slot"] == 1 and after["run"][:2] == ("running", None)
+
+
+async def test_a_busy_temporal_puts_the_request_back_without_an_attempt(
+    queued, owner_sessionmaker, dispatch_sessionmaker, api_settings
+) -> None:
+    _, _, request = queued
+    starting = await started(dispatch_sessionmaker, request, api_settings)
+    client = FakeClient(rpc(RPCStatusCode.RESOURCE_EXHAUSTED))
+    assert await through(dispatch_sessionmaker, starting, client) == "throttled"
+    after = await state(owner_sessionmaker, request.id)
+    assert after["request"] == ("queued", None, 0) and after["slot"] == 0
+
+
+async def test_a_late_confirmation_never_changes_a_run_that_already_ended(
+    queued, owner_sessionmaker, dispatch_sessionmaker, api_settings
+) -> None:
+    """A fast run finishes, its end write making its row terminal and releasing its slot, before the dispatcher
+    records `started` (§7.8)."""
+    _, _, request = queued
+    starting = await started(dispatch_sessionmaker, request, api_settings)
+    outcome = await dispatch.start(FakeClient(), starting)
+    async with owner_sessionmaker() as s, s.begin():  # the run's end write
+        await s.execute(text("update runs set status = 'succeeded', ended_at = now() where id = :i"), {"i": request.id})
+        await s.execute(text("delete from run_slots where run_id = :i"), {"i": request.id})
+    assert await dispatch.settle(dispatch_sessionmaker, starting, outcome) == "started"
+    after = await state(owner_sessionmaker, request.id)
+    assert after["request"][0] == "started" and after["run"][0] == "succeeded" and after["slot"] == 0
+
+
+async def test_already_started_is_verified_from_the_executions_own_start(
+    queued, owner_sessionmaker, dispatch_sessionmaker, api_settings, env
+) -> None:
+    """A start whose answer was lost, sent again: Temporal refuses the duplicate id, and the execution's started event,
+    decoded with the tenant's key, names this request: it's `started` (§7.4)."""
+    _, _, request = queued
+    starting = await started(dispatch_sessionmaker, request, api_settings)
+    await env.client.start_workflow(
+        RunGraph.run,
+        starting.start,
+        id=run_workflow_id(starting.start.tenant_id, starting.start.run_id),
+        task_queue=ENGINE_QUEUE,
+    )  # fmt: skip  (the lost one)
+    assert await through(dispatch_sessionmaker, starting, env.client) == "started"
+    assert (await state(owner_sessionmaker, request.id))["request"][0] == "started"
+
+
+async def test_another_execution_under_the_runs_id_is_an_id_collision(
+    queued, owner_sessionmaker, dispatch_sessionmaker, api_settings, env
+) -> None:
+    _, _, request = queued
+    starting = await started(dispatch_sessionmaker, request, api_settings)
+    impostor = starting.start.__class__(**{**starting.start.__dict__, "version_id": str(uuid.uuid4())})
+    await env.client.start_workflow(RunGraph.run, impostor, id=run_workflow_id(impostor.tenant_id, impostor.run_id),
+                                    task_queue=ENGINE_QUEUE)  # fmt: skip
+    assert await through(dispatch_sessionmaker, starting, env.client) == "dead"
+    after = await state(owner_sessionmaker, request.id)
+    assert after["request"][:2] == ("dead", "id_collision") and after["run"][0] == "failed" and after["slot"] == 0
+
+
+async def test_a_cycle_starts_each_tenants_oldest_due_request(
+    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings
+) -> None:
+    tenants = []
+    for _ in range(2):
+        ctx, wf = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings)
+        tenants.append((ctx, wf))
+    await current(dispatch_sessionmaker)
+    await workers(owner_sessionmaker)
+    first = [(await admit(api_sessionmaker, ctx, wf, key=f"{n}")).request for n, (ctx, wf) in enumerate(tenants)]
+    client = FakeClient()
+    counts = await dispatch.dispatch_once(dispatch_sessionmaker, client, KEYS, api_settings, BUILD)
+    assert counts == {"started": 2} and {a.run_id for a, _, _ in client.started} == {str(r.id) for r in first}
diff --git a/backend/tests/apps/test_runs.py b/backend/tests/apps/test_runs.py
index 6c70d51..2a4f140 100644
--- a/backend/tests/apps/test_runs.py
+++ b/backend/tests/apps/test_runs.py
@@ -112,7 +112,7 @@ class FakeClient:
         self.calls: list[tuple[str, WorkflowIDReusePolicy]] = []
 
     async def start_workflow(
-        self, _run: Any, arg: RunInput, *, id: str, task_queue: str, id_reuse_policy: WorkflowIDReusePolicy
+        self, _run: Any, arg: RunInput, *, id: str, task_queue: str, id_reuse_policy: WorkflowIDReusePolicy, **_: Any
     ) -> None:
         self.calls.append((id, id_reuse_policy))
         answer = self.answers.pop(0) if self.answers else None
```

### Task 10: A root run's end write releases its slot in the same transaction

**Commit:** `31891bd` (prototype `proto/2b2-v2`); the replay's tree was identical: yes.

**Create:** `backend/tests/apps/worker/test_slot_release.py`

**Modify:** `backend/src/dewpoint/apps/worker/store.py`

**What it does:**

A sub-run holds no slot and releases nothing. A refused end write is
still logged and skipped, and its slot is released: the execution ended
either way.


- [ ] **Step 1: its tests alone, before its code.** Run: `uv run pytest -n 4 tests/apps/worker/test_slot_release.py`. Replay result (exit 1), shortened:

```
[gw2] darwin -- Python 3.14.7 /private/tmp/claude-501/-Users-tmunzer-4-dev-mist-dewpoint/1e3145a1-199e-4b31-be1b-1e3bfd266be7/scratchpad/2b2-plan/proto/backend/.venv/bin/python
E   AssertionError: assert [UUID('e0115b...c842466d134')] == []
      Left contains one more item: UUID('e0115b33-e9d1-4a9b-ac0b-4c842466d134')
      Use -v to get more diff
---------------------------- Captured stderr setup -----------------------------
security, not by bypassing it (engine 2b spec §6.3, plan 2b-1a's review)
§14; revision 7)
----------------------------- Captured stdout call -----------------------------
2026-10-03 21:47:12 [warning  ] projection_run_refused         run_id=e0115b33-e9d1-4a9b-ac0b-4c842466d134 sqlstate=23514
/private/tmp/claude-501/-Users-tmunzer-4-dev-mist-dewpoint/1e3145a1-199e-4b31-be1b-1e3bfd266be7/scratchpad/2b2-plan/replay/backend/tests/apps/worker/test_slot_release.py:72: AssertionError: assert [UUID('e0115b...c842466d134')] == []
=========================== short test summary info ============================
FAILED tests/apps/worker/test_slot_release.py::test_a_root_runs_end_write_releases_its_slot
FAILED tests/apps/worker/test_slot_release.py::test_an_end_write_the_database_refuses_still_releases_its_slot
2 failed, 1 passed in 10.83s
```

- [ ] **Step 2: its code, then the same tests.** Replay result (exit 0), shortened:

```
...                                                                      [100%]
3 passed in 10.88s
```

- [ ] **Step 3: commit.** `git cherry-pick --no-commit 31891bd && git commit -C 31891bd`

The diff:

```diff
diff --git a/backend/src/dewpoint/apps/worker/store.py b/backend/src/dewpoint/apps/worker/store.py
index 0d38bec..d36de73 100644
--- a/backend/src/dewpoint/apps/worker/store.py
+++ b/backend/src/dewpoint/apps/worker/store.py
@@ -11,7 +11,7 @@ from datetime import datetime
 from typing import Any
 
 import structlog
-from sqlalchemy import select
+from sqlalchemy import delete, select
 from sqlalchemy.exc import DBAPIError
 from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
 from temporalio.exceptions import ApplicationError
@@ -22,6 +22,7 @@ from dewpoint.core.claims.cipher import ClaimCipher
 from dewpoint.core.crypto.keys import KeySource
 from dewpoint.core.db import tenant_scope
 from dewpoint.core.models.claims import SecretIndex
+from dewpoint.core.models.requests import RunSlot
 from dewpoint.core.models.workflows import WorkflowVersion
 from dewpoint.core.plugins.registry import load_node_types
 from dewpoint.core.runs import service as runs
@@ -185,6 +186,7 @@ class DbRunStore:
                 await runs.upsert_steps(s, tenant, [_row(r) for r in data.steps])
                 if data.run is not None:
                     await _finish(s, data.run)
+                    await _release(s, data.run)
         except DBAPIError as e:
             if _refused(e) is None:
                 raise
@@ -227,6 +229,7 @@ class DbRunStore:
                     if state is None:
                         raise
                     _log.warning("projection_run_refused", run_id=data.run.run_id, sqlstate=state)
+                await _release(s, data.run)  # the execution ended either way
 
 
 async def _start(s: AsyncSession, tenant: uuid.UUID, start: RunStart) -> None:
@@ -245,6 +248,12 @@ async def _start(s: AsyncSession, tenant: uuid.UUID, start: RunStart) -> None:
     )
 
 
+async def _release(s: AsyncSession, run: RunSummary) -> None:
+    """A root run's end frees its tenant's slot in the end write's own transaction (engine 2b spec §7.5); a sub-run
+    holds none, so this matches nothing for it."""
+    await s.execute(delete(RunSlot).where(RunSlot.run_id == uuid.UUID(run.run_id)))
+
+
 async def _finish(s: AsyncSession, run: RunSummary) -> None:
     await runs.finish_run(
         s,
diff --git a/backend/tests/apps/worker/test_slot_release.py b/backend/tests/apps/worker/test_slot_release.py
new file mode 100644
index 0000000..4847fd5
--- /dev/null
+++ b/backend/tests/apps/worker/test_slot_release.py
@@ -0,0 +1,72 @@
+# SPDX-License-Identifier: Apache-2.0
+"""A root run's slot (engine 2b spec §7.5): its end write releases it in the same transaction, so the tenant's next
+request can start as soon as the run's row is terminal. A sub-run holds no slot of its own and never releases its
+root's."""
+
+import uuid
+from datetime import UTC, datetime
+from typing import Any
+
+from sqlalchemy import text
+
+from dewpoint.apps.worker.store import DbRunStore
+from dewpoint.core.db import tenant_scope
+from dewpoint.core.runs import service as runs
+from dewpoint.engine.runtime.activities import ProjectInput, RunSummary
+from tests.core.runs.test_service import seeded_run
+from tests.support.keys import FixtureKeys
+
+
+async def held(owner: Any, tenant: uuid.UUID, run_id: uuid.UUID) -> None:
+    async with owner() as s, s.begin():
+        await s.execute(text("insert into run_slots (run_id, tenant_id) values (:r, :t)"), {"r": run_id, "t": tenant})
+
+
+async def slots(owner: Any) -> list[uuid.UUID]:
+    async with owner() as s:
+        return list((await s.execute(text("select run_id from run_slots"))).scalars())
+
+
+async def status(owner: Any, tenant: uuid.UUID, run_id: uuid.UUID) -> str | None:
+    async with owner() as s, s.begin():
+        await tenant_scope(s, tenant)
+        run = await runs.get_run(s, run_id)
+    return run.status if run else None
+
+
+def ended(run_id: uuid.UUID, status: str = "succeeded", *, if_running: bool = False) -> RunSummary:
+    return RunSummary(str(run_id), status, datetime.now(UTC).isoformat(), if_running=if_running)
+
+
+async def test_a_root_runs_end_write_releases_its_slot(
+    owner_sessionmaker, dispatch_sessionmaker, worker_sessionmaker
+) -> None:
+    tenant, run_id = await seeded_run(owner_sessionmaker, dispatch_sessionmaker)
+    await held(owner_sessionmaker, tenant, run_id)
+    await DbRunStore(worker_sessionmaker, FixtureKeys()).project(ProjectInput(str(tenant), [], ended(run_id)))
+    assert await status(owner_sessionmaker, tenant, run_id) == "succeeded"
+    assert await slots(owner_sessionmaker) == []
+
+
+async def test_a_sub_runs_end_leaves_its_roots_slot_held(
+    owner_sessionmaker, dispatch_sessionmaker, worker_sessionmaker
+) -> None:
+    """A parent writing the end of a child that ended without one (`if_running`): only the root's own end frees it."""
+    tenant, root = await seeded_run(owner_sessionmaker, dispatch_sessionmaker)
+    _, child = await seeded_run(owner_sessionmaker, dispatch_sessionmaker)
+    await held(owner_sessionmaker, tenant, root)
+    store = DbRunStore(worker_sessionmaker, FixtureKeys())
+    await store.project(ProjectInput(str(tenant), [], ended(child, "cancelled", if_running=True)))
+    assert await slots(owner_sessionmaker) == [root]
+
+
+async def test_an_end_write_the_database_refuses_still_releases_its_slot(
+    owner_sessionmaker, dispatch_sessionmaker, worker_sessionmaker
+) -> None:
+    """The execution ended either way: a refused end write is logged and skipped (2a's rule), and holding its slot
+    would only starve the tenant until the reconciler noticed."""
+    tenant, run_id = await seeded_run(owner_sessionmaker, dispatch_sessionmaker)
+    await held(owner_sessionmaker, tenant, run_id)
+    await DbRunStore(worker_sessionmaker, FixtureKeys()).project(ProjectInput(str(tenant), [], ended(run_id, "bogus")))
+    assert await status(owner_sessionmaker, tenant, run_id) == "running"  # refused: the reconciler ends it (§7.6)
+    assert await slots(owner_sessionmaker) == []
```

### Task 11: The owner's M2 regression returns the request to the queue through a confirmed refusal

**Commit:** `cb5ef14` (prototype `proto/2b2-v2`); the replay's tree was identical: yes.

**Modify:** `backend/tests/apps/dispatcher/test_begin.py`

**What it does:**

test(dispatcher): the owner's M2 regression returns the request to the queue through a confirmed refusal

- [ ] **Step 1: its tests alone, before its code.** Run: `uv run pytest -n 4 tests/apps/dispatcher/test_begin.py`. Replay result (exit 0), shortened:

```
...........                                                              [100%]
11 passed in 11.86s
```

- [ ] **Step 2: its code, then the same tests.** Replay result (exit 0), shortened:

```
...........                                                              [100%]
11 passed in 13.02s
```

Evidence beyond the replay: with the defensive check removed, the request starts, and this test fails.

- [ ] **Step 3: commit.** `git cherry-pick --no-commit cb5ef14 && git commit -C cb5ef14`

The diff:

```diff
diff --git a/backend/tests/apps/dispatcher/test_begin.py b/backend/tests/apps/dispatcher/test_begin.py
index d620108..4672ff1 100644
--- a/backend/tests/apps/dispatcher/test_begin.py
+++ b/backend/tests/apps/dispatcher/test_begin.py
@@ -117,16 +117,19 @@ async def test_a_starting_request_back_in_the_queue_after_its_closure_was_retire
     (a confirmed refusal), dispatch's defensive check cancels it, audited, and the run's row an earlier attempt wrote
     becomes terminal with it (§7.8). Nothing starts."""
     ctx, wf, request = queued
-    assert isinstance(await begin(dispatch_sessionmaker, request, api_settings), dispatch.Starting)
+    starting = await begin(dispatch_sessionmaker, request, api_settings)
+    assert isinstance(starting, dispatch.Starting)
     await update(api_sessionmaker, ctx, wf, enabled=False)
     async with admin_sessionmaker() as s, s.begin():
         assert (await lifecycle.retire(s, lifecycle.Entry("node", "testkit.echo@1"), force=True, confirm=True)).applied
     assert (await state(owner_sessionmaker, request.id))["request"][0] == "starting"  # left alone
-    async with owner_sessionmaker() as s, s.begin():  # Temporal refused it: back in the queue, its slot released
-        await s.execute(
-            text("update run_requests set status = 'queued', attempts = 1 where id = :i"), {"i": request.id}
-        )
-        await s.execute(text("delete from run_slots"))
+    # Temporal refused it: back in the queue, one attempt counted, its slot released
+    assert await dispatch.settle(dispatch_sessionmaker, starting, dispatch.Outcome("refused")) == "refused"
+    assert await state(owner_sessionmaker, request.id) == {
+        "request": ("queued", None, 1), "slot": 0, "run": (await state(owner_sessionmaker, request.id))["run"],
+    }  # fmt: skip
+    async with owner_sessionmaker() as s, s.begin():  # its backoff over
+        await s.execute(text("update run_requests set next_attempt_at = now() where id = :i"), {"i": request.id})
     assert await begin(dispatch_sessionmaker, request, api_settings) == dispatch.Cancelled("node_type_retired")
     after = await state(owner_sessionmaker, request.id)
     assert after["request"][:2] == ("cancelled", "node_type_retired") and after["slot"] == 0
```

### Task 12: An admitted request runs to its end through a dispatch cycle and frees its slot

**Commit:** `7151289` (prototype `proto/2b2-v2`); the replay's tree was identical: yes.

**Create:** `backend/tests/apps/dispatcher/test_end_to_end.py`

**What it does:**

test(dispatcher): an admitted request runs to its end through a dispatch cycle and frees its slot

- [ ] **Step 1: its tests alone, before its code.** Run: `uv run pytest -n 4 tests/apps/dispatcher/test_end_to_end.py`. Replay result (exit 0), shortened:

```
.                                                                        [100%]
1 passed in 12.08s
```

- [ ] **Step 2: its code, then the same tests.** Replay result (exit 0), shortened:

```
.                                                                        [100%]
1 passed in 11.89s
```

Evidence beyond the replay: with the root's slot release removed, the slot stays held, and this test fails.

- [ ] **Step 3: commit.** `git cherry-pick --no-commit 7151289 && git commit -C 7151289`

The diff:

```diff
diff --git a/backend/tests/apps/dispatcher/test_end_to_end.py b/backend/tests/apps/dispatcher/test_end_to_end.py
new file mode 100644
index 0000000..1b9af06
--- /dev/null
+++ b/backend/tests/apps/dispatcher/test_end_to_end.py
@@ -0,0 +1,33 @@
+# SPDX-License-Identifier: Apache-2.0
+"""M2's whole path on the time-skipping server (engine 2b spec §7.3–7.8): an admitted request is started by a dispatch
+cycle, run by a worker with its envelope's handles resolved, and its end write frees the tenant's slot."""
+
+import asyncio
+
+import pytest
+
+from dewpoint.apps.dispatcher import dispatch
+from dewpoint.apps.worker.store import DbRunStore
+from dewpoint.engine.runtime.ids import run_workflow_id
+from dewpoint.engine.runtime.workflow import RunGraph
+from tests.apps.dispatcher.support import BUILD, state
+from tests.apps.test_admission import KEYS
+from tests.apps.worker.harness import workers
+
+pytestmark = pytest.mark.usefixtures("development_deployment")
+
+
+async def test_an_admitted_request_runs_to_its_end_and_frees_its_slot(
+    queued, env, owner_sessionmaker, dispatch_sessionmaker, worker_sessionmaker, api_settings
+) -> None:
+    ctx, _, request = queued
+    async with workers(env.client, DbRunStore(worker_sessionmaker, KEYS)):
+        done = await dispatch.dispatch_once(dispatch_sessionmaker, env.client, KEYS, api_settings, BUILD)
+        assert done == {"started": 1}
+        handle = env.client.get_workflow_handle_for(RunGraph.run, run_workflow_id(str(ctx.tenant_id), str(request.id)))
+        result = await asyncio.wait_for(handle.result(), 30)
+    assert result.status == "succeeded"
+    after = await state(owner_sessionmaker, request.id)
+    assert after["request"] == ("started", None, 0) and after["slot"] == 0
+    assert after["run"][0] == "succeeded" and after["run"][1] is not None  # started, then ended
+    assert await dispatch.dispatch_once(dispatch_sessionmaker, env.client, KEYS, api_settings, BUILD) == {}
```

### Task 13: A key that can't be read, a broken envelope and a bug are told apart (the owner's milestone-2 review)

**Commit:** `745adb8` (prototype `proto/2b2-v2`); the replay's tree was identical: yes.

**Create:** `backend/tests/apps/dispatcher/test_envelope_failures.py`

**Modify:** `backend/src/dewpoint/apps/dispatcher/dispatch.py`, `backend/src/dewpoint/core/claims/service.py`

**What it does:**

Only a failure reading the tenant's key (wrapped where the key is read)
or the codec's refusal to seal the start waits as key_unusable. An
envelope whose ciphertext doesn't open, or whose plaintext isn't JSON,
is broken for good: its request is dead (envelope_unreadable), audited.
Anything else (a bug, an envelope its foreign key should have kept, an
outage) raises out of the starting transaction, and the cycle isolates
it: logged, the request left queued, the other tenants dispatched.


- [ ] **Step 1: its tests alone, before its code.** Run: `uv run pytest -n 4 tests/apps/dispatcher/test_envelope_failures.py`. Replay result (exit 1), shortened:

```
----------------------------- Captured stdout call -----------------------------
2026-10-03 21:48:47 [warning  ] dispatch_waiting               error=TypeError reason=key_unusable
/private/tmp/claude-501/-Users-tmunzer-4-dev-mist-dewpoint/1e3145a1-199e-4b31-be1b-1e3bfd266be7/scratchpad/2b2-plan/replay/backend/tests/apps/dispatcher/test_envelope_failures.py:133: AssertionError: assert {'key_unusabl... 'started': 1} == {'error': 1, 'started': 1}
[gw2] darwin -- Python 3.14.7 /private/tmp/claude-501/-Users-tmunzer-4-dev-mist-dewpoint/1e3145a1-199e-4b31-be1b-1e3bfd266be7/scratchpad/2b2-plan/proto/backend/.venv/bin/python
E   dewpoint.core.claims.service.EnvelopeUnavailableError: missing
/private/tmp/claude-501/-Users-tmunzer-4-dev-mist-dewpoint/1e3145a1-199e-4b31-be1b-1e3bfd266be7/scratchpad/2b2-plan/replay/backend/tests/apps/dispatcher/test_envelope_failures.py:127: dewpoint.core.claims.service.EnvelopeUnavailableError: missing
=========================== short test summary info ============================
FAILED tests/apps/dispatcher/test_envelope_failures.py::test_a_broken_envelope_makes_its_request_dead_never_a_key_outage[not_json]
FAILED tests/apps/dispatcher/test_envelope_failures.py::test_a_broken_envelope_makes_its_request_dead_never_a_key_outage[tampered]
FAILED tests/apps/dispatcher/test_envelope_failures.py::test_a_broken_envelope_never_stops_the_cycle_for_other_tenants
FAILED tests/apps/dispatcher/test_envelope_failures.py::test_a_bug_while_building_the_start_is_never_a_key_outage
FAILED tests/apps/dispatcher/test_envelope_failures.py::test_a_failure_dispatch_cant_classify_is_isolated_and_its_request_stays_queued[error0]
FAILED tests/apps/dispatcher/test_envelope_failures.py::test_a_failure_dispatch_cant_classify_is_isolated_and_its_request_stays_queued[error1]
6 failed, 1 passed in 11.96s
```

- [ ] **Step 2: its code, then the same tests.** Replay result (exit 0), shortened:

```
.......                                                                  [100%]
7 passed in 12.01s
```

- [ ] **Step 3: commit.** `git cherry-pick --no-commit 745adb8 && git commit -C 745adb8`

The diff:

```diff
diff --git a/backend/src/dewpoint/apps/dispatcher/dispatch.py b/backend/src/dewpoint/apps/dispatcher/dispatch.py
index c0e43c1..186fe08 100644
--- a/backend/src/dewpoint/apps/dispatcher/dispatch.py
+++ b/backend/src/dewpoint/apps/dispatcher/dispatch.py
@@ -19,6 +19,7 @@ from datetime import UTC, datetime, timedelta
 from typing import Any
 
 import structlog
+from cryptography.hazmat.primitives.ciphers.aead import AESGCM
 from sqlalchemy import func, select, text
 from sqlalchemy.dialects.postgresql import insert
 from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
@@ -56,6 +57,9 @@ CANDIDATES = 50  # tenants picked per cycle, each its oldest due request
 START_REFUSED = "start_refused"
 ID_COLLISION = "id_collision"
 START_FAILED = "start_failed"
+ENVELOPE_UNREADABLE = "envelope_unreadable"
+KEY_UNUSABLE = "key_unusable"
+ENVELOPE_MESSAGE = "The request's trigger envelope doesn't open (engine 2b spec §7.1)."
 REFUSED_MESSAGE = "Temporal refused the run's start 10 times (engine 2b spec §7.4)."
 COLLISION_MESSAGE = "Another execution holds this run's workflow id (engine 2b spec §7.4)."
 # A status Temporal answers with when it certainly refused the start (2a's rule, `apps.runs`).
@@ -87,6 +91,13 @@ class Waiting:
     reason: str
 
 
+@dataclass(frozen=True)
+class Dead:
+    """The request can never start (a broken envelope): `dead`, audited, an earlier attempt's run row failed."""
+
+    reason: str
+
+
 @dataclass(frozen=True)
 class Cancelled:
     """A request cancelled at dispatch: `engine_abi_changed`, `node_type_retired` or `cel_profile_retired`."""
@@ -110,6 +121,36 @@ def sealer(converter: DataConverter, namespace: str) -> Seal:
     return seal
 
 
+class KeyUnusableError(Exception):
+    """A tenant's key that couldn't be read: no such key, or the keyring didn't answer. Its cause says which."""
+
+
+class KeyFailures:
+    """A `KeySource` whose every failure is the key's own, as KeyUnusableError: wrapping only the key's read, so an
+    envelope that doesn't open, or a bug around it, is never taken for a key outage."""
+
+    def __init__(self, keys: KeySource) -> None:
+        self._keys = keys
+
+    async def active(self, tenant_id: str) -> tuple[int, AESGCM]:
+        try:
+            return await self._keys.active(tenant_id)
+        except Exception as e:
+            raise KeyUnusableError("The tenant's active key can't be read.") from e
+
+    async def get(self, tenant_id: str, version: int) -> AESGCM:
+        try:
+            return await self._keys.get(tenant_id, version)
+        except Exception as e:
+            raise KeyUnusableError("A tenant's key can't be read.") from e
+
+    async def digest_key(self, tenant_id: str, version: int | None) -> tuple[int, bytes]:
+        try:
+            return await self._keys.digest_key(tenant_id, version)
+        except Exception as e:
+            raise KeyUnusableError("A tenant's digest key can't be read.") from e
+
+
 async def _lock(s: AsyncSession, key: str) -> None:
     await s.execute(text("select pg_advisory_xact_lock_shared(hashtextextended(:k, 0))"), {"k": key})
 
@@ -123,8 +164,9 @@ async def begin(
     tenant_id: uuid.UUID,
     request_id: uuid.UUID,
     build: Build,
-) -> Starting | Waiting | Cancelled | None:
-    """One due request's starting transaction. None: no longer due, or another dispatcher holds it."""
+) -> Starting | Waiting | Cancelled | Dead | None:
+    """One due request's starting transaction. None: no longer due, or another dispatcher holds it. Anything it
+    can't classify (a bug, an envelope its foreign key should have kept, an outage) raises; nothing it wrote stays."""
     async with sessionmaker() as s, s.begin():
         outcome = await _begin(s, seal, settings, keys, tenant_id, request_id, build)
         if isinstance(outcome, Waiting):
@@ -140,7 +182,7 @@ async def _begin(
     tenant_id: uuid.UUID,
     request_id: uuid.UUID,
     build: Build,
-) -> Starting | Waiting | Cancelled | None:
+) -> Starting | Waiting | Cancelled | Dead | None:
     await lifecycle.assert_read_committed(s)
     await tenant_scope(s, tenant_id)
     await _lock(s, GATE_LOCK)
@@ -190,23 +232,32 @@ async def _begin(
         return Waiting("no_slot")
     if keys is None:
         raise RuntimeError("Dispatch reads envelopes with the tenants' keys.")
-    try:  # the tenant's key opens the envelope and seals the start: one that doesn't work stops it (§2.3)
-        envelope = await claims.read_envelope(s, ClaimCipher(keys), tenant_id, request_id=request.id)
-        start = RunInput(
-            tenant_id=str(tenant_id),
-            run_id=str(request.id),
-            version_id=str(version.id),
-            trigger=envelope,
-            mode=request.mode,
-            max_run_duration_s=settings.max_run_duration_days * 86_400,
-            cel_schedule_to_start_s=settings.cel_schedule_to_start_s,
-        )
+    # The tenant's key opens the envelope and seals the start: one that can't be read waits (§2.3). Each failure is
+    # told apart where it happens, so a broken envelope or a bug never reads as a key outage (the owner's M2 review).
+    try:
+        envelope = await claims.read_envelope(s, ClaimCipher(KeyFailures(keys)), tenant_id, request_id=request.id)
+    except KeyUnusableError as e:
+        log.warning("dispatch_waiting", reason=KEY_UNUSABLE, error=type(e.__cause__).__name__)
+        return Waiting(KEY_UNUSABLE)
+    except claims.EnvelopeUnreadableError:  # broken for good: no retry mends it
+        log.error("dispatch_envelope_unreadable", request_id=str(request.id))
+        await _dead(s, request, ENVELOPE_UNREADABLE, ENVELOPE_MESSAGE)
+        await s.flush()
+        return Dead(ENVELOPE_UNREADABLE)
+    start = RunInput(
+        tenant_id=str(tenant_id),
+        run_id=str(request.id),
+        version_id=str(version.id),
+        trigger=envelope,
+        mode=request.mode,
+        max_run_duration_s=settings.max_run_duration_days * 86_400,
+        cel_schedule_to_start_s=settings.cel_schedule_to_start_s,
+    )
+    try:
         await seal(start)
-    except claims.EnvelopeUnavailableError:
-        raise  # the request's foreign key keeps its envelope: a bug, never a key's fault
-    except Exception as e:
-        log.warning("dispatch_waiting", reason="key_unusable", error=type(e).__name__)
-        return Waiting("key_unusable")
+    except CodecRefusedError as e:  # the codec's refusal: its tenant is in the id built here, so its key can't be read
+        log.warning("dispatch_waiting", reason=KEY_UNUSABLE, error=type(e.__cause__).__name__)
+        return Waiting(KEY_UNUSABLE)
     s.add(RunSlot(run_id=request.id, tenant_id=tenant_id))
     await runs.precreate_run(
         s, run_id=request.id, tenant_id=tenant_id, workflow_id=request.workflow_id, version_id=version.id,
@@ -377,10 +428,23 @@ async def dispatch_once(
                                   {"n": CANDIDATES})).all()  # fmt: skip
     counts: Counter[str] = Counter()
     for tenant_id, request_id in picked:
-        outcome = await begin(sessionmaker, seal, settings, keys, tenant_id=tenant_id, request_id=request_id,
-                              build=build)  # fmt: skip
-        if isinstance(outcome, Starting):
-            counts[await settle(sessionmaker, outcome, await start(client, outcome))] += 1
-        elif outcome is not None:
-            counts[outcome.reason] += 1
+        try:
+            happened = await _dispatch(sessionmaker, client, seal, keys, settings, build, tenant_id, request_id)
+        except Exception as e:  # a bug or an outage: the request stays as it was, and the cycle goes on (M2 review)
+            log.error("dispatch_failed", tenant_id=str(tenant_id), request_id=str(request_id), error=type(e).__name__)
+            counts["error"] += 1
+            continue
+        if happened is not None:
+            counts[happened] += 1
     return dict(counts)
+
+
+async def _dispatch(
+    sessionmaker: async_sessionmaker[AsyncSession], client: Client, seal: Seal, keys: KeySource, settings: Settings,
+    build: Build, tenant_id: uuid.UUID, request_id: uuid.UUID,
+) -> str | None:  # fmt: skip
+    """One candidate begun, started and settled: what happened to it; None when another dispatcher had it."""
+    outcome = await begin(sessionmaker, seal, settings, keys, tenant_id=tenant_id, request_id=request_id, build=build)
+    if isinstance(outcome, Starting):
+        return await settle(sessionmaker, outcome, await start(client, outcome))
+    return outcome.reason if outcome is not None else None
diff --git a/backend/src/dewpoint/core/claims/service.py b/backend/src/dewpoint/core/claims/service.py
index 4b79f4b..38cf19e 100644
--- a/backend/src/dewpoint/core/claims/service.py
+++ b/backend/src/dewpoint/core/claims/service.py
@@ -40,6 +40,11 @@ class EnvelopeUnavailableError(Exception):
     has removed. The message is fixed."""
 
 
+class EnvelopeUnreadableError(EnvelopeUnavailableError):
+    """A request's trigger envelope that is there but broken: its ciphertext doesn't open under its tenant and id, or
+    what it opens to isn't JSON. Reading it again never mends it. The message is fixed."""
+
+
 class ClaimConflictError(Exception):
     """A claim written again under its id with other content: nothing was written. A bug, never a value's fault."""
 
@@ -205,6 +210,10 @@ async def read_envelope(s: AsyncSession, cipher: ClaimCipher, tenant_id: uuid.UU
     if found is None:
         raise EnvelopeUnavailableError("A request whose trigger envelope isn't there.")
     try:
-        return json.loads(await cipher.open(str(tenant_id), str(found.id), found.ciphertext))
+        plain = await cipher.open(str(tenant_id), str(found.id), found.ciphertext)
     except ClaimUnreadableError as e:
-        raise EnvelopeUnavailableError("A trigger envelope that doesn't open under its tenant.") from e
+        raise EnvelopeUnreadableError("A trigger envelope that doesn't open under its tenant.") from e
+    try:
+        return json.loads(plain)
+    except ValueError:  # not UTF-8, or not JSON
+        raise EnvelopeUnreadableError("A trigger envelope that isn't JSON.") from None
diff --git a/backend/tests/apps/dispatcher/test_envelope_failures.py b/backend/tests/apps/dispatcher/test_envelope_failures.py
new file mode 100644
index 0000000..69035c4
--- /dev/null
+++ b/backend/tests/apps/dispatcher/test_envelope_failures.py
@@ -0,0 +1,135 @@
+# SPDX-License-Identifier: Apache-2.0
+"""What stops a start before anything is written, told apart (the owner's M2 checkpoint): a tenant key that can't be
+read waits, queued, with no attempt (§2.3); an envelope that doesn't open, or isn't JSON, is broken for good, so its
+request is `dead`, audited; a bug is neither, and it stays queued. None of them stops a cycle for the other tenants."""
+
+import uuid
+from typing import Any
+
+import pytest
+from sqlalchemy import text
+
+from dewpoint.apps.dispatcher import dispatch
+from dewpoint.core.claims import service as claims
+from dewpoint.core.claims.cipher import ClaimCipher
+from tests.apps.dispatcher.support import BUILD, begin, state
+from tests.apps.test_admission import KEYS, admit, published
+from tests.apps.test_runs import FakeClient
+from tests.support.keys import FixtureKeys
+
+pytestmark = pytest.mark.usefixtures("development_deployment")
+
+
+async def envelope_id(owner: Any, request_id: uuid.UUID) -> uuid.UUID:
+    async with owner() as s:
+        found = await s.execute(text("select envelope_id from run_requests where id = :r"), {"r": request_id})
+        return found.scalar_one()
+
+
+async def break_envelope(owner: Any, request: Any, how: str) -> None:
+    """`tampered`: one bit of its ciphertext flipped. `not_json`: a sound ciphertext of bytes that aren't JSON."""
+    eid = await envelope_id(owner, request.id)
+    async with owner() as s, s.begin():
+        if how == "tampered":
+            await s.execute(
+                text("update run_inputs set ciphertext = set_byte(ciphertext, length(ciphertext) - 1,"
+                     " get_byte(ciphertext, length(ciphertext) - 1) # 1) where id = :i"),
+                {"i": eid},
+            )  # fmt: skip
+        else:
+            sealed = await ClaimCipher(KEYS).seal(str(request.tenant_id), str(eid), b"\xff not json")
+            await s.execute(text("update run_inputs set ciphertext = :c where id = :i"), {"c": sealed, "i": eid})
+
+
+async def second_tenant(owner: Any, api: Any, admin: Any, settings: Any) -> Any:
+    ctx, wf = await published(owner, api, admin, settings)
+    return (await admit(api, ctx, wf, key="other")).request
+
+
+async def audited(owner: Any, action: str) -> list[Any]:
+    async with owner() as s:
+        rows = await s.execute(text("select target_id, details from audit_log where action = :a"), {"a": action})
+        return [tuple(r) for r in rows]
+
+
+@pytest.mark.parametrize("how", ["tampered", "not_json"])
+async def test_a_broken_envelope_makes_its_request_dead_never_a_key_outage(
+    queued, owner_sessionmaker, dispatch_sessionmaker, api_settings, how
+) -> None:
+    _, _, request = queued
+    await break_envelope(owner_sessionmaker, request, how)
+    assert await begin(dispatch_sessionmaker, request, api_settings) == dispatch.Dead("envelope_unreadable")
+    after = await state(owner_sessionmaker, request.id)
+    assert after == {"request": ("dead", "envelope_unreadable", 0), "run": None, "slot": 0}
+    assert await audited(owner_sessionmaker, "run.request.dead") == [
+        (str(request.id), {"reason": "envelope_unreadable"})
+    ]
+
+
+async def test_a_broken_envelope_never_stops_the_cycle_for_other_tenants(
+    queued, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings
+) -> None:
+    _, _, broken = queued  # the oldest due request: the cycle reaches it first
+    other = await second_tenant(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings)
+    await break_envelope(owner_sessionmaker, broken, "tampered")
+    client = FakeClient()
+    counts = await dispatch.dispatch_once(dispatch_sessionmaker, client, KEYS, api_settings, BUILD)
+    assert counts == {"envelope_unreadable": 1, "started": 1}
+    assert [a.run_id for a, _, _ in client.started] == [str(other.id)]
+
+
+class ActiveKeyGone(FixtureKeys):
+    """The envelope's key opens it, but the tenant's active key, which seals the start, can't be read."""
+
+    async def active(self, tenant_id: str) -> Any:
+        raise LookupError(f"no active key for tenant {tenant_id}")
+
+
+async def test_a_key_that_cant_seal_the_start_waits_queued(
+    queued, owner_sessionmaker, dispatch_sessionmaker, api_settings
+) -> None:
+    _, _, request = queued
+    assert await begin(dispatch_sessionmaker, request, api_settings, keys=ActiveKeyGone()) == dispatch.Waiting(
+        "key_unusable"
+    )
+    assert await state(owner_sessionmaker, request.id) == {"request": ("queued", None, 0), "run": None, "slot": 0}
+
+
+async def test_a_bug_while_building_the_start_is_never_a_key_outage(
+    queued, owner_sessionmaker, dispatch_sessionmaker, api_settings
+) -> None:
+    _, _, request = queued
+
+    async def broken(_: Any) -> None:
+        raise TypeError("a bug")
+
+    with pytest.raises(TypeError):
+        await dispatch.begin(
+            dispatch_sessionmaker, broken, api_settings, KEYS, tenant_id=request.tenant_id, request_id=request.id,
+            build=BUILD,
+        )  # fmt: skip
+    assert await state(owner_sessionmaker, request.id) == {"request": ("queued", None, 0), "run": None, "slot": 0}
+
+
+@pytest.mark.parametrize("error", [TypeError("a bug"), claims.EnvelopeUnavailableError("missing")])
+async def test_a_failure_dispatch_cant_classify_is_isolated_and_its_request_stays_queued(
+    queued, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings,
+    monkeypatch, error,
+) -> None:  # fmt: skip
+    """A bug, or an envelope its foreign key should have kept: logged as an error, the request left as it was, and
+    the cycle goes on to the next tenant."""
+    _, _, failing = queued
+    other = await second_tenant(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings)
+    read = claims.read_envelope
+
+    async def read_envelope(s: Any, cipher: Any, tenant_id: uuid.UUID, *, request_id: uuid.UUID) -> Any:
+        if request_id == failing.id:
+            raise error
+        return await read(s, cipher, tenant_id, request_id=request_id)
+
+    monkeypatch.setattr(claims, "read_envelope", read_envelope)
+    client = FakeClient()
+    counts = await dispatch.dispatch_once(dispatch_sessionmaker, client, KEYS, api_settings, BUILD)
+    assert counts == {"error": 1, "started": 1}
+    assert [a.run_id for a, _, _ in client.started] == [str(other.id)]
+    assert await state(owner_sessionmaker, failing.id) == {"request": ("queued", None, 0), "run": None, "slot": 0}
```

### Task 14: Only a key read's expected failures wait; a bug reading a key raises (the owner's milestone-2 review)

**Commit:** `f63b0e6` (prototype `proto/2b2-v2`); the replay's tree was identical: yes.

**Modify:** `backend/src/dewpoint/apps/dispatcher/dispatch.py`, `backend/src/dewpoint/core/crypto/keys.py`, `backend/src/dewpoint/core/db.py`, `backend/tests/apps/dispatcher/test_envelope_failures.py`, `backend/tests/apps/test_codec.py`, `backend/tests/support/keys.py`

**What it does:**

key_unreadable names how reading a tenant's key fails with nothing
wrong in the code: no key (NoKeyError), an unconfigured KEK
(UnknownKekError), a stored key that doesn't unwrap (InvalidTag), or a
keyring database that doesn't answer (core.db.unavailable: an
invalidated connection, SQLSTATE class 08/53/57, the network, a pool
timeout). Only those wait as key_unusable, on opening the envelope and,
through the codec refusal's cause, on sealing the start. Anything else
raises to the cycle's per-request isolation. The fixture key source now
raises NoKeyError, as the keyring does.


- [ ] **Step 1: its tests alone, before its code.** Run: `uv run pytest -n 4 tests/apps/dispatcher/test_envelope_failures.py tests/apps/test_codec.py`. Replay result (exit 1), shortened:

```
/private/tmp/claude-501/-Users-tmunzer-4-dev-mist-dewpoint/1e3145a1-199e-4b31-be1b-1e3bfd266be7/scratchpad/2b2-plan/replay/backend/tests/apps/dispatcher/test_envelope_failures.py:148: Failed: DID NOT RAISE Exception
[gw3] darwin -- Python 3.14.7 /private/tmp/claude-501/-Users-tmunzer-4-dev-mist-dewpoint/1e3145a1-199e-4b31-be1b-1e3bfd266be7/scratchpad/2b2-plan/proto/backend/.venv/bin/python
E   Failed: DID NOT RAISE Exception
----------------------------- Captured stdout call -----------------------------
2026-10-03 21:49:20 [warning  ] dispatch_waiting               error=DBAPIError reason=key_unusable
/private/tmp/claude-501/-Users-tmunzer-4-dev-mist-dewpoint/1e3145a1-199e-4b31-be1b-1e3bfd266be7/scratchpad/2b2-plan/replay/backend/tests/apps/dispatcher/test_envelope_failures.py:148: Failed: DID NOT RAISE Exception
=========================== short test summary info ============================
FAILED tests/apps/dispatcher/test_envelope_failures.py::test_a_bug_reading_a_key_is_never_a_key_outage[type_error-active]
FAILED tests/apps/dispatcher/test_envelope_failures.py::test_a_bug_reading_a_key_is_never_a_key_outage[key_error-get]
FAILED tests/apps/dispatcher/test_envelope_failures.py::test_a_bug_reading_a_key_is_never_a_key_outage[type_error-get]
FAILED tests/apps/dispatcher/test_envelope_failures.py::test_a_bug_reading_a_key_is_never_a_key_outage[key_error-active]
FAILED tests/apps/dispatcher/test_envelope_failures.py::test_a_bug_reading_a_key_is_never_a_key_outage[sql_error-get]
FAILED tests/apps/dispatcher/test_envelope_failures.py::test_a_bug_reading_a_key_is_never_a_key_outage[sql_error-active]
6 failed, 37 passed in 13.95s
```

- [ ] **Step 2: its code, then the same tests.** Replay result (exit 0), shortened:

```
...........................................                              [100%]
43 passed in 13.88s
```

- [ ] **Step 3: commit.** `git cherry-pick --no-commit f63b0e6 && git commit -C f63b0e6`

The diff:

```diff
diff --git a/backend/src/dewpoint/apps/dispatcher/dispatch.py b/backend/src/dewpoint/apps/dispatcher/dispatch.py
index 186fe08..cbc84fd 100644
--- a/backend/src/dewpoint/apps/dispatcher/dispatch.py
+++ b/backend/src/dewpoint/apps/dispatcher/dispatch.py
@@ -35,7 +35,7 @@ from dewpoint.core.audit import service as audit
 from dewpoint.core.claims import service as claims
 from dewpoint.core.claims.cipher import ClaimCipher
 from dewpoint.core.config import Settings
-from dewpoint.core.crypto.keys import KeySource
+from dewpoint.core.crypto.keys import KeySource, key_unreadable
 from dewpoint.core.db import tenant_scope
 from dewpoint.core.models.platform import PlatformSettings
 from dewpoint.core.models.requests import RunRequest, RunSlot, TenantRunLimits
@@ -59,7 +59,9 @@ ID_COLLISION = "id_collision"
 START_FAILED = "start_failed"
 ENVELOPE_UNREADABLE = "envelope_unreadable"
 KEY_UNUSABLE = "key_unusable"
-ENVELOPE_MESSAGE = "The request's trigger envelope doesn't open (engine 2b spec §7.1)."
+ENVELOPE_MESSAGE = (
+    "The request's trigger envelope doesn't open or isn't JSON; repairing a key never reopens it (engine 2b spec §7.1)."
+)
 REFUSED_MESSAGE = "Temporal refused the run's start 10 times (engine 2b spec §7.4)."
 COLLISION_MESSAGE = "Another execution holds this run's workflow id (engine 2b spec §7.4)."
 # A status Temporal answers with when it certainly refused the start (2a's rule, `apps.runs`).
@@ -93,7 +95,8 @@ class Waiting:
 
 @dataclass(frozen=True)
 class Dead:
-    """The request can never start (a broken envelope): `dead`, audited, an earlier attempt's run row failed."""
+    """The request can never start (a broken envelope): `dead`, audited, an earlier attempt's run row failed. Terminal:
+    repairing a key later (a wrong key fails as a tampered envelope does) never reopens it; a re-run is a new one."""
 
     reason: str
 
@@ -122,12 +125,14 @@ def sealer(converter: DataConverter, namespace: str) -> Seal:
 
 
 class KeyUnusableError(Exception):
-    """A tenant's key that couldn't be read: no such key, or the keyring didn't answer. Its cause says which."""
+    """A tenant's key that couldn't be read (`key_unreadable`): no such key, one that doesn't unwrap, or the keyring
+    didn't answer. Its cause says which."""
 
 
 class KeyFailures:
-    """A `KeySource` whose every failure is the key's own, as KeyUnusableError: wrapping only the key's read, so an
-    envelope that doesn't open, or a bug around it, is never taken for a key outage."""
+    """A `KeySource` whose expected failures (`key_unreadable`) say they're the key's, as KeyUnusableError: only the
+    key's read is wrapped, so an envelope that doesn't open is never taken for a key outage, and a bug in reading the
+    key raises as it is (the owner's M2 review)."""
 
     def __init__(self, keys: KeySource) -> None:
         self._keys = keys
@@ -136,18 +141,24 @@ class KeyFailures:
         try:
             return await self._keys.active(tenant_id)
         except Exception as e:
+            if not key_unreadable(e):
+                raise
             raise KeyUnusableError("The tenant's active key can't be read.") from e
 
     async def get(self, tenant_id: str, version: int) -> AESGCM:
         try:
             return await self._keys.get(tenant_id, version)
         except Exception as e:
+            if not key_unreadable(e):
+                raise
             raise KeyUnusableError("A tenant's key can't be read.") from e
 
     async def digest_key(self, tenant_id: str, version: int | None) -> tuple[int, bytes]:
         try:
             return await self._keys.digest_key(tenant_id, version)
         except Exception as e:
+            if not key_unreadable(e):
+                raise
             raise KeyUnusableError("A tenant's digest key can't be read.") from e
 
 
@@ -255,7 +266,9 @@ async def _begin(
     )
     try:
         await seal(start)
-    except CodecRefusedError as e:  # the codec's refusal: its tenant is in the id built here, so its key can't be read
+    except CodecRefusedError as e:  # the codec wraps whatever stopped it: only a key that can't be read waits
+        if not key_unreadable(e.__cause__):
+            raise
         log.warning("dispatch_waiting", reason=KEY_UNUSABLE, error=type(e.__cause__).__name__)
         return Waiting(KEY_UNUSABLE)
     s.add(RunSlot(run_id=request.id, tenant_id=tenant_id))
diff --git a/backend/src/dewpoint/core/crypto/keys.py b/backend/src/dewpoint/core/crypto/keys.py
index bdb4a98..d32f030 100644
--- a/backend/src/dewpoint/core/crypto/keys.py
+++ b/backend/src/dewpoint/core/crypto/keys.py
@@ -8,13 +8,15 @@ from collections import OrderedDict
 from collections.abc import Callable
 from typing import Protocol
 
+from cryptography.exceptions import InvalidTag
 from cryptography.hazmat.primitives import hashes
 from cryptography.hazmat.primitives.ciphers.aead import AESGCM
 from cryptography.hazmat.primitives.kdf.hkdf import HKDF
 from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
 
-from dewpoint.core.crypto.keyring import Keyring
-from dewpoint.core.db import tenant_scope
+from dewpoint.core.crypto.kek import UnknownKekError
+from dewpoint.core.crypto.keyring import Keyring, NoKeyError
+from dewpoint.core.db import tenant_scope, unavailable
 
 
 def digest_key_of(raw: bytes, tenant_id: str) -> bytes:
@@ -24,9 +26,18 @@ def digest_key_of(raw: bytes, tenant_id: str) -> bytes:
     return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=info).derive(raw)
 
 
+def key_unreadable(e: BaseException | None) -> bool:
+    """Whether `e` is how reading a tenant's key fails with nothing wrong in the code (a `KeySource`'s contract): no
+    such key (`NoKeyError`), its KEK not configured (`UnknownKekError`), a stored key that doesn't unwrap under its KEK
+    (`InvalidTag`), or a keyring database that doesn't answer (`core.db.unavailable`). A bug in the reader is none."""
+    if e is None:
+        return False
+    return isinstance(e, (NoKeyError, UnknownKekError, InvalidTag)) or unavailable(e)
+
+
 class KeySource(Protocol):
     """A tenant's data keys, by version. Read-only: neither the codec nor the claim cipher creates a key (a tenant
-    gets one when it's created)."""
+    gets one when it's created). A key that can't be read raises what `key_unreadable` accepts."""
 
     async def active(self, tenant_id: str) -> tuple[int, AESGCM]: ...
 
diff --git a/backend/src/dewpoint/core/db.py b/backend/src/dewpoint/core/db.py
index d3fb49c..c8c0193 100644
--- a/backend/src/dewpoint/core/db.py
+++ b/backend/src/dewpoint/core/db.py
@@ -2,8 +2,13 @@
 import uuid
 
 from sqlalchemy import text
+from sqlalchemy.exc import DBAPIError
+from sqlalchemy.exc import TimeoutError as PoolTimeoutError
 from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
 
+# SQLSTATE classes of a server that doesn't serve: connection exception, insufficient resources, operator intervention
+UNAVAILABLE_STATES = ("08", "53", "57")
+
 
 def make_engine(url: str) -> AsyncEngine:
     return create_async_engine(url, pool_pre_ping=True)
@@ -13,6 +18,16 @@ def make_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
     return async_sessionmaker(engine, expire_on_commit=False)
 
 
+def unavailable(e: BaseException) -> bool:
+    """Whether `e` says the database didn't answer, never that a statement was wrong: a connection the driver lost
+    (SQLAlchemy invalidates it), a server refusing to serve (`UNAVAILABLE_STATES`), the network, or no pooled connection
+    in time. A statement's own error (a syntax error, a constraint) is none of them."""
+    if isinstance(e, DBAPIError):
+        state = getattr(e.orig, "sqlstate", None)
+        return e.connection_invalidated or (isinstance(state, str) and state[:2] in UNAVAILABLE_STATES)
+    return isinstance(e, (OSError, PoolTimeoutError))
+
+
 async def _set_scope(session: AsyncSession, tenant: str, user: str) -> None:
     await session.execute(
         text("select set_config('app.tenant_id', :t, true), set_config('app.user_id', :u, true)"),
diff --git a/backend/tests/apps/dispatcher/test_envelope_failures.py b/backend/tests/apps/dispatcher/test_envelope_failures.py
index 69035c4..b49fcca 100644
--- a/backend/tests/apps/dispatcher/test_envelope_failures.py
+++ b/backend/tests/apps/dispatcher/test_envelope_failures.py
@@ -7,11 +7,17 @@ import uuid
 from typing import Any
 
 import pytest
+from cryptography.exceptions import InvalidTag
 from sqlalchemy import text
+from sqlalchemy.exc import DBAPIError
+from sqlalchemy.exc import TimeoutError as PoolTimeoutError
 
+from dewpoint.apps.codec import CodecRefusedError
 from dewpoint.apps.dispatcher import dispatch
 from dewpoint.core.claims import service as claims
 from dewpoint.core.claims.cipher import ClaimCipher
+from dewpoint.core.crypto.kek import UnknownKekError
+from dewpoint.core.crypto.keyring import NoKeyError
 from tests.apps.dispatcher.support import BUILD, begin, state
 from tests.apps.test_admission import KEYS, admit, published
 from tests.apps.test_runs import FakeClient
@@ -78,20 +84,72 @@ async def test_a_broken_envelope_never_stops_the_cycle_for_other_tenants(
     assert [a.run_id for a, _, _ in client.started] == [str(other.id)]
 
 
-class ActiveKeyGone(FixtureKeys):
-    """The envelope's key opens it, but the tenant's active key, which seals the start, can't be read."""
+class Orig(Exception):
+    """A driver error, as SQLAlchemy wraps one, with its SQLSTATE."""
+
+    def __init__(self, sqlstate: str) -> None:
+        super().__init__(sqlstate)
+        self.sqlstate = sqlstate
+
+
+class FailingKeys(FixtureKeys):
+    """Fixture keys whose `get` (opening the envelope) or `active` (sealing the start) raises `error`."""
+
+    def __init__(self, method: str, error: BaseException) -> None:
+        super().__init__()
+        self.method, self.error = method, error
+
+    async def get(self, tenant_id: str, version: int) -> Any:
+        if self.method == "get":
+            raise self.error
+        return await super().get(tenant_id, version)
 
     async def active(self, tenant_id: str) -> Any:
-        raise LookupError(f"no active key for tenant {tenant_id}")
+        if self.method == "active":
+            raise self.error
+        return await super().active(tenant_id)
+
+
+EXPECTED = {  # how reading a tenant's key fails when nothing is wrong with the code
+    "no_key": NoKeyError("no key"),
+    "unknown_kek": UnknownKekError("kek-2"),
+    "unwraps_not": InvalidTag(),
+    "refused_connection": ConnectionRefusedError(),
+    "connection_lost": DBAPIError("select", None, Orig("08006"), connection_invalidated=True),
+    "cannot_connect_now": DBAPIError("select", None, Orig("57P03")),
+    "too_many_connections": DBAPIError("select", None, Orig("53300")),
+    "pool_timeout": PoolTimeoutError(),
+}
+BUGS = {  # how a bug in reading it fails: never a key outage (the owner's M2 review)
+    "type_error": TypeError("a bug"),
+    "key_error": KeyError("version"),
+    "sql_error": DBAPIError("select", None, Orig("42601")),
+}
+
+
+@pytest.mark.parametrize("method", ["get", "active"])
+@pytest.mark.parametrize("error", EXPECTED.values(), ids=EXPECTED.keys())
+async def test_a_key_that_cant_be_read_waits_queued(
+    queued, owner_sessionmaker, dispatch_sessionmaker, api_settings, method, error
+) -> None:
+    _, _, request = queued
+    keys = FailingKeys(method, error)
+    assert await begin(dispatch_sessionmaker, request, api_settings, keys=keys) == dispatch.Waiting("key_unusable")
+    assert await state(owner_sessionmaker, request.id) == {"request": ("queued", None, 0), "run": None, "slot": 0}
 
 
-async def test_a_key_that_cant_seal_the_start_waits_queued(
-    queued, owner_sessionmaker, dispatch_sessionmaker, api_settings
+@pytest.mark.parametrize("method", ["get", "active"])
+@pytest.mark.parametrize("error", BUGS.values(), ids=BUGS.keys())
+async def test_a_bug_reading_a_key_is_never_a_key_outage(
+    queued, owner_sessionmaker, dispatch_sessionmaker, api_settings, method, error
 ) -> None:
+    """Opening the envelope raises the bug itself; sealing the start raises the codec's refusal, caused by it."""
     _, _, request = queued
-    assert await begin(dispatch_sessionmaker, request, api_settings, keys=ActiveKeyGone()) == dispatch.Waiting(
-        "key_unusable"
-    )
+    with pytest.raises(Exception) as raised:
+        await begin(dispatch_sessionmaker, request, api_settings, keys=FailingKeys(method, error))
+    found = raised.value if method == "get" else raised.value.__cause__
+    assert found is error
+    assert method == "get" or isinstance(raised.value, CodecRefusedError)
     assert await state(owner_sessionmaker, request.id) == {"request": ("queued", None, 0), "run": None, "slot": 0}
 
 
diff --git a/backend/tests/apps/test_codec.py b/backend/tests/apps/test_codec.py
index 4eb85a9..1b3a564 100644
--- a/backend/tests/apps/test_codec.py
+++ b/backend/tests/apps/test_codec.py
@@ -19,6 +19,7 @@ from dewpoint.apps.codec import (
     CodecRefusedError,
     TenantCodec,
 )
+from dewpoint.core.crypto.keyring import NoKeyError
 from dewpoint.engine.runtime.ids import run_workflow_id
 from dewpoint.engine.runtime.size import CODEC_OVERHEAD
 from tests.support.keys import FixtureKeys
@@ -116,9 +117,9 @@ async def test_a_tenant_without_a_key_is_refused() -> None:
     """Every failure to encode is the codec's refusal, so a client that sends what it encodes knows nothing was sent
     (owner's review, Task 6); the cause stays chained."""
     c = codec(FixtureKeys(missing={A})).with_context(workflow(A))
-    with pytest.raises(CodecRefusedError, match=r"couldn't be encrypted \(LookupError\)") as e:
+    with pytest.raises(CodecRefusedError, match=r"couldn't be encrypted \(NoKeyError\)") as e:
         await c.encode([payload(1)])
-    assert isinstance(e.value.__cause__, LookupError)
+    assert isinstance(e.value.__cause__, NoKeyError)
 
 
 @pytest.mark.parametrize("size", [0, 1, 1_000, 65_536, 1_835_008, 2_097_152])
diff --git a/backend/tests/support/keys.py b/backend/tests/support/keys.py
index 6786cb9..69b033d 100644
--- a/backend/tests/support/keys.py
+++ b/backend/tests/support/keys.py
@@ -13,6 +13,7 @@ from temporalio.api.common.v1 import Payload
 from temporalio.converter import WorkflowSerializationContext
 
 from dewpoint.apps.codec import TENANT, TenantCodec, data_converter
+from dewpoint.core.crypto.keyring import NoKeyError
 from dewpoint.core.crypto.keys import digest_key_of
 from dewpoint.engine.runtime.ids import run_workflow_id
 
@@ -36,7 +37,7 @@ class FixtureKeys:
 
     def _raw(self, tenant_id: str, version: int) -> bytes:
         if tenant_id in self.missing:
-            raise LookupError(f"no key for tenant {tenant_id}")
+            raise NoKeyError(f"no key for tenant {tenant_id}")  # as the keyring says it
         return hashlib.sha256(f"dewpoint-fixture-key|{tenant_id}|{version}".encode()).digest()
```

**Checkpoint (milestone 2).** Focused: the dispatcher, admission, requests, runs, worker slot, store and health tests, environment, lifecycle and CLI (200 at `7151289`; 133 after Task 13, 215 after Task 14); the migrations up to 0020 and back. The owner held it twice: Task 13 (a broken envelope or a bug never reads as a key outage, and never stops the cycle) and Task 14 (only a key read's expected failures wait), then approved it (2026-10-03).

## Milestone 3 — The reconciler, cancels and the gate

### Task 15: The reconciler settles uncertain starts, ended runs and leaked slots

**Commit:** `bd94021` (prototype `proto/2b2-v2`); the replay's tree was identical: yes.

**Create:** `backend/migrations/versions/0021_reconciler.py`, `backend/src/dewpoint/apps/dispatcher/reconcile.py`, `backend/tests/apps/dispatcher/test_reconcile.py`, `backend/tests/apps/dispatcher/test_reconcile_runs.py`

**Modify:** `backend/src/dewpoint/apps/dispatcher/dispatch.py`, `backend/src/dewpoint/apps/dispatcher/main.py`, `backend/src/dewpoint/core/models/requests.py`

**What it does:**

One leader among the dispatchers, by a session-level advisory lock on a
connection of its own. It reads across tenants only through
reconcile_candidates() (ids and a kind) and asks about each request at
most once per recheck interval (run_requests.checked_at, 0021).

An uncertain start past its grace period: an execution it finds is
verified as the dispatcher verifies one and the request is started; a
NOT_FOUND from a namespace that answers puts it back in the queue, due
at once, no attempt counted; anything else leaves it starting. Each is
audited (run.request.reconciled).

A started run whose row is still running, once the logical run's latest
execution is closed: COMPLETED records its own result, CANCELED
cancelled, TERMINATED failed/terminated, FAILED or TIMED_OUT
failed/internal_error with an alert; the slot is released in the same
transaction. This ends a run whose end write was lost or refused.

A slot whose run's row ended is released once its execution is closed
or absent. Failures are isolated per request, as the dispatcher's are.


- [ ] **Step 1: its tests alone, before its code.** Run: `uv run pytest -n 4 tests/apps/dispatcher/test_reconcile.py tests/apps/dispatcher/test_reconcile_runs.py`. Replay result (exit 1), shortened:

```
________ ERROR collecting tests/apps/dispatcher/test_reconcile_runs.py _________
ImportError while importing test module '/private/tmp/claude-501/-Users-tmunzer-4-dev-mist-dewpoint/1e3145a1-199e-4b31-be1b-1e3bfd266be7/scratchpad/2b2-plan/replay/backend/tests/apps/dispatcher/test_reconcile_runs.py'.
Hint: make sure your test modules/packages have valid Python names.
Traceback:
/opt/homebrew/Cellar/python@3.14/3.14.7/Frameworks/Python.framework/Versions/3.14/lib/python3.14/importlib/__init__.py:88: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
tests/apps/dispatcher/test_reconcile_runs.py:15: in <module>
    from dewpoint.apps.dispatcher import dispatch, reconcile
E   ImportError: cannot import name 'reconcile' from 'dewpoint.apps.dispatcher' (/private/tmp/claude-501/-Users-tmunzer-4-dev-mist-dewpoint/1e3145a1-199e-4b31-be1b-1e3bfd266be7/scratchpad/2b2-plan/replay/backend/src/dewpoint/apps/dispatcher/__init__.py)
=========================== short test summary info ============================
ERROR tests/apps/dispatcher/test_reconcile.py - ImportError while importing t...
ERROR tests/apps/dispatcher/test_reconcile_runs.py - ImportError while import...
2 errors in 5.55s
```

- [ ] **Step 2: its code, then the same tests.** Replay result (exit 0), shortened:

```
.................                                                        [100%]
17 passed in 14.64s
```

- [ ] **Step 3: commit.** `git cherry-pick --no-commit bd94021 && git commit -C bd94021`

The diff:

```diff
diff --git a/backend/migrations/versions/0021_reconciler.py b/backend/migrations/versions/0021_reconciler.py
new file mode 100644
index 0000000..99c5839
--- /dev/null
+++ b/backend/migrations/versions/0021_reconciler.py
@@ -0,0 +1,49 @@
+# SPDX-License-Identifier: Apache-2.0
+"""the reconciler's view across tenants and its round robin (engine 2b spec §7.6)
+
+`run_requests.checked_at`: when the reconciler last asked Temporal about a request, so each one is asked at most once
+per recheck interval. `reconcile_candidates()`: like `dispatch_candidates()`, ids and a kind only, never a request's
+contents: uncertain starts past their grace period, started runs whose rows are still `running`, and slots held by
+runs whose rows have ended."""
+
+import sqlalchemy as sa
+from alembic import op
+
+revision = "0021"
+down_revision = "0020"
+branch_labels = None
+depends_on = None
+
+CANDIDATES = """
+CREATE FUNCTION reconcile_candidates(grace interval, recheck interval, max_rows integer)
+RETURNS TABLE (tenant_id uuid, request_id uuid, kind text)
+LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
+  SELECT c.tenant_id, c.request_id, c.kind FROM (
+    SELECT r.tenant_id, r.id AS request_id, 'starting'::text AS kind, s.reserved_at AS since
+    FROM run_requests r JOIN run_slots s ON s.run_id = r.id
+    WHERE r.status = 'starting' AND s.reserved_at < statement_timestamp() - grace
+    UNION ALL
+    SELECT r.tenant_id, r.id, 'open', u.queued_at
+    FROM run_requests r JOIN runs u ON u.id = r.id
+    WHERE r.status = 'started' AND u.status = 'running'
+    UNION ALL
+    SELECT s.tenant_id, s.run_id, 'slot', s.reserved_at
+    FROM run_slots s JOIN runs u ON u.id = s.run_id JOIN run_requests r ON r.id = s.run_id
+    WHERE r.status <> 'starting' AND u.status <> 'running'
+  ) c JOIN run_requests q ON q.id = c.request_id
+  WHERE q.checked_at IS NULL OR q.checked_at < statement_timestamp() - recheck
+  ORDER BY q.checked_at NULLS FIRST, c.since, c.request_id
+  LIMIT max_rows
+$$"""
+
+
+def upgrade() -> None:
+    op.add_column("run_requests", sa.Column("checked_at", sa.DateTime(timezone=True)))
+    op.execute(CANDIDATES)
+    op.execute("REVOKE ALL ON FUNCTION reconcile_candidates(interval, interval, integer) FROM PUBLIC")
+    op.execute("GRANT EXECUTE ON FUNCTION reconcile_candidates(interval, interval, integer) TO dewpoint_dispatch")
+
+
+def downgrade() -> None:
+    op.execute("DROP FUNCTION reconcile_candidates(interval, interval, integer)")
+    op.drop_column("run_requests", "checked_at")
diff --git a/backend/src/dewpoint/apps/dispatcher/dispatch.py b/backend/src/dewpoint/apps/dispatcher/dispatch.py
index cbc84fd..3b9dfbd 100644
--- a/backend/src/dewpoint/apps/dispatcher/dispatch.py
+++ b/backend/src/dewpoint/apps/dispatcher/dispatch.py
@@ -16,7 +16,7 @@ from collections import Counter
 from collections.abc import Awaitable, Callable
 from dataclasses import dataclass
 from datetime import UTC, datetime, timedelta
-from typing import Any
+from typing import Any, Protocol
 
 import structlog
 from cryptography.hazmat.primitives.ciphers.aead import AESGCM
@@ -93,6 +93,24 @@ class Waiting:
     reason: str
 
 
+class Target(Protocol):
+    """A request a start's outcome is applied to."""
+
+    @property
+    def request_id(self) -> uuid.UUID: ...
+
+    @property
+    def tenant_id(self) -> uuid.UUID: ...
+
+
+@dataclass(frozen=True)
+class Ref:
+    """A request, by id: what the reconciler settles when it has no start of its own (§7.6)."""
+
+    request_id: uuid.UUID
+    tenant_id: uuid.UUID
+
+
 @dataclass(frozen=True)
 class Dead:
     """The request can never start (a broken envelope): `dead`, audited, an earlier attempt's run row failed. Terminal:
@@ -255,15 +273,7 @@ async def _begin(
         await _dead(s, request, ENVELOPE_UNREADABLE, ENVELOPE_MESSAGE)
         await s.flush()
         return Dead(ENVELOPE_UNREADABLE)
-    start = RunInput(
-        tenant_id=str(tenant_id),
-        run_id=str(request.id),
-        version_id=str(version.id),
-        trigger=envelope,
-        mode=request.mode,
-        max_run_duration_s=settings.max_run_duration_days * 86_400,
-        cel_schedule_to_start_s=settings.cel_schedule_to_start_s,
-    )
+    start = run_input(request, version.id, envelope, settings)
     try:
         await seal(start)
     except CodecRefusedError as e:  # the codec wraps whatever stopped it: only a key that can't be read waits
@@ -281,6 +291,19 @@ async def _begin(
     return Starting(request.id, tenant_id, start)
 
 
+def run_input(request: RunRequest, version_id: uuid.UUID, envelope: Any, settings: Settings) -> RunInput:
+    """A request's start: its frozen version and its envelope, with the deployment's run bounds."""
+    return RunInput(
+        tenant_id=str(request.tenant_id),
+        run_id=str(request.id),
+        version_id=str(version_id),
+        trigger=envelope,
+        mode=request.mode,
+        max_run_duration_s=settings.max_run_duration_days * 86_400,
+        cel_schedule_to_start_s=settings.cel_schedule_to_start_s,
+    )
+
+
 async def _slot_free(s: AsyncSession, tenant_id: uuid.UUID, platform: PlatformSettings) -> bool:
     """Whether the tenant runs fewer root runs than its limit, under its limits row's lock (§7.5)."""
     await s.execute(insert(TenantRunLimits).values(tenant_id=tenant_id).on_conflict_do_nothing())
@@ -369,41 +392,57 @@ async def verify(client: Client, starting: Starting) -> Outcome:
     return Outcome("started", at=first.event_time.ToDatetime(tzinfo=UTC))
 
 
-async def settle(sessionmaker: async_sessionmaker[AsyncSession], starting: Starting, outcome: Outcome) -> str:
+async def settle(
+    sessionmaker: async_sessionmaker[AsyncSession], starting: Target, outcome: Outcome, *, audited: bool = False
+) -> str:
     """The outcome applied to the request, its slot and its run's row in one transaction (§7.8); what happened, for
-    the cycle's report. A request no longer `starting` (the reconciler settled it) is left as it is."""
+    the cycle's report. A request no longer `starting` (the other of the dispatcher and the reconciler settled it) is
+    left as it is. `audited`: the reconciler's settlements are audited (§2.4), a dead one as every dead one is."""
     async with sessionmaker() as s, s.begin():
-        await tenant_scope(s, starting.tenant_id)
-        request = (
-            await s.execute(
-                select(RunRequest)
-                .where(RunRequest.id == starting.request_id)
-                .with_for_update()
-                .execution_options(populate_existing=True)
-            )
-        ).scalar_one()
-        if request.status != "starting":
-            return "moved"
-        if outcome.kind == "started":
-            await confirm(s, request, outcome.at)
-            return "started"
-        if outcome.kind == "uncertain":
-            log.warning("start_uncertain", request_id=str(request.id), detail=outcome.detail)
-            return "uncertain"  # starting, its slot held, for the reconciler (§7.6)
-        await _release(s, request.id)
-        if outcome.kind == "throttled":
-            request.status, request.next_attempt_at = "queued", datetime.now(UTC) + backoff(1)
-            return "throttled"
-        if outcome.kind == "collision":
-            log.error("start_id_collision", request_id=str(request.id))
-            await _dead(s, request, ID_COLLISION, COLLISION_MESSAGE)
-            return "dead"
-        request.attempts += 1
-        if request.attempts >= MAX_ATTEMPTS:
-            await _dead(s, request, START_REFUSED, REFUSED_MESSAGE)
-            return "dead"
-        request.status, request.next_attempt_at = "queued", datetime.now(UTC) + backoff(request.attempts)
-        return "refused"
+        happened = await _settle(s, starting, outcome)
+        if audited and happened in ("started", "absent"):
+            await audit.record(s, tenant_id=starting.tenant_id, actor_id=None, action="run.request.reconciled",
+                               target_type="run_request", target_id=str(starting.request_id),
+                               details={"outcome": happened})  # fmt: skip
+        return happened
+
+
+async def _settle(s: AsyncSession, starting: Target, outcome: Outcome) -> str:
+    await tenant_scope(s, starting.tenant_id)
+    request = (
+        await s.execute(
+            select(RunRequest)
+            .where(RunRequest.id == starting.request_id)
+            .with_for_update()
+            .execution_options(populate_existing=True)
+        )
+    ).scalar_one()
+    if request.status != "starting":
+        return "moved"
+    if outcome.kind == "started":
+        await confirm(s, request, outcome.at)
+        return "started"
+    if outcome.kind == "uncertain":
+        log.warning("start_uncertain", request_id=str(request.id), detail=outcome.detail)
+        return "uncertain"  # starting, its slot held, for the reconciler (§7.6)
+    await release(s, request.id)
+    if outcome.kind == "throttled":
+        request.status, request.next_attempt_at = "queued", datetime.now(UTC) + backoff(1)
+        return "throttled"
+    if outcome.kind == "absent":  # a trustworthy absence (§7.6): back in the queue, due at once, no attempt
+        log.warning("start_absent", request_id=str(request.id))
+        request.status, request.next_attempt_at = "queued", datetime.now(UTC)
+        return "absent"
+    if outcome.kind == "collision":
+        log.error("start_id_collision", request_id=str(request.id))
+        await _dead(s, request, ID_COLLISION, COLLISION_MESSAGE)
+        return "dead"
+    request.attempts += 1
+    if request.attempts >= MAX_ATTEMPTS:
+        await _dead(s, request, START_REFUSED, REFUSED_MESSAGE)
+        return "dead"
+    request.status, request.next_attempt_at = "queued", datetime.now(UTC) + backoff(request.attempts)
+    return "refused"
 
 
 async def confirm(s: AsyncSession, request: RunRequest, at: datetime | None) -> None:
@@ -416,7 +455,7 @@ async def confirm(s: AsyncSession, request: RunRequest, at: datetime | None) ->
     )
 
 
-async def _release(s: AsyncSession, run_id: uuid.UUID) -> None:
+async def release(s: AsyncSession, run_id: uuid.UUID) -> None:
     await s.execute(text("delete from run_slots where run_id = :i"), {"i": run_id})
 
 
diff --git a/backend/src/dewpoint/apps/dispatcher/main.py b/backend/src/dewpoint/apps/dispatcher/main.py
index 2755058..a132a8d 100644
--- a/backend/src/dewpoint/apps/dispatcher/main.py
+++ b/backend/src/dewpoint/apps/dispatcher/main.py
@@ -1,7 +1,8 @@
 # SPDX-License-Identifier: Apache-2.0
 """The dispatcher process (engine 2b spec §7.3), role `dewpoint_dispatch`. It checks the deployment's environment
 before it connects to Temporal (§2.1), encrypts every start with the tenant's key (§6.2), and each cycle observes the
-current build, dispatches what's due, and reports."""
+current build, dispatches what's due, and reports; the one that leads the reconciler (§7.6) also settles what starts
+left uncertain, and reports that apart."""
 
 import asyncio
 import uuid
@@ -13,6 +14,7 @@ from temporalio.service import RPCError, RPCStatusCode
 from dewpoint.apps.codec import KeyringKeys, data_converter
 from dewpoint.apps.dispatcher.dispatch import dispatch_once
 from dewpoint.apps.dispatcher.observe import observe, report
+from dewpoint.apps.dispatcher.reconcile import Leader, reconcile_once
 from dewpoint.apps.environment import verify_environment
 from dewpoint.apps.worker.deployment import describe, this_build
 from dewpoint.core.config import Settings
@@ -45,13 +47,19 @@ async def run(settings: Settings) -> None:
             settings.temporal_address, namespace=settings.temporal_namespace, data_converter=data_converter(keys)
         )
         instance = uuid.uuid4()
+        reconciler, leader = uuid.uuid5(instance, "reconciler"), Leader(engine)
         log.info("dispatcher_started", instance=str(instance), build=this_build())
-        while True:
-            build = await observe(sessionmaker, await current_build(client))
-            done = await dispatch_once(sessionmaker, client, keys, settings, build) if build else {}
-            await report(
-                sessionmaker, instance, build.build_id if build else "", {"current_build": bool(build), **done}
-            )
-            await asyncio.sleep(CYCLE_S)
+        try:
+            while True:
+                build = await observe(sessionmaker, await current_build(client))
+                build_id = build.build_id if build else ""
+                done = await dispatch_once(sessionmaker, client, keys, settings, build) if build else {}
+                await report(sessionmaker, instance, build_id, {"current_build": bool(build), **done})
+                if await leader.leading():
+                    settled = await reconcile_once(sessionmaker, client, keys, settings)
+                    await report(sessionmaker, reconciler, build_id, {**settled}, kind="reconciler")
+                await asyncio.sleep(CYCLE_S)
+        finally:
+            await leader.close()
     finally:
         await engine.dispose()
diff --git a/backend/src/dewpoint/apps/dispatcher/reconcile.py b/backend/src/dewpoint/apps/dispatcher/reconcile.py
new file mode 100644
index 0000000..908457f
--- /dev/null
+++ b/backend/src/dewpoint/apps/dispatcher/reconcile.py
@@ -0,0 +1,288 @@
+# SPDX-License-Identifier: Apache-2.0
+"""The reconciler (engine 2b spec §7.6): inside the dispatcher, one leader at a time, it settles what starts left
+uncertain, records the end of runs whose workflow closed without their end write, and releases leaked slots.
+
+It reads across tenants only through `reconcile_candidates()` (ids and a kind), then works tenant-scoped, one
+request per transaction, with no transaction open across a call to Temporal. It asks about each request at most once
+per `RECHECK`. A failure it can't classify is logged and isolated, as the dispatcher's are."""
+
+import uuid
+from collections import Counter
+from dataclasses import dataclass
+from datetime import UTC, datetime, timedelta
+from typing import Any
+
+import structlog
+from sqlalchemy import select, text
+from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession, async_sessionmaker
+from temporalio.api.workflowservice.v1 import DescribeNamespaceRequest
+from temporalio.client import Client, WorkflowExecutionStatus
+from temporalio.service import RPCError, RPCStatusCode
+
+from dewpoint.apps.dispatcher import dispatch
+from dewpoint.core.claims import service as claims
+from dewpoint.core.claims.cipher import ClaimCipher
+from dewpoint.core.config import Settings
+from dewpoint.core.crypto.keys import KeySource
+from dewpoint.core.db import tenant_scope
+from dewpoint.core.models.requests import RunRequest, RunSlot
+from dewpoint.core.runs import service as runs
+from dewpoint.engine.runtime.activities import RunResult
+from dewpoint.engine.runtime.execution import CANCELLED, INTERNAL_ERROR, TERMINATED
+from dewpoint.engine.runtime.ids import run_workflow_id
+
+log = structlog.get_logger("dewpoint.reconciler")
+LEADER_LOCK = "dewpoint:reconciler"
+GRACE = timedelta(seconds=30)  # longer than a start's own deadline (dispatch.START_DEADLINE), so none is in flight
+RECHECK = timedelta(seconds=30)  # each request asked about at most once in this long
+ALERT_AFTER = timedelta(minutes=10)  # an uncertain start still unresolved this long after it was made: an error
+BATCH = 50  # requests per pass
+TERMINATED_MESSAGE = "The run's workflow was terminated outside Dewpoint."
+FAILED_MESSAGE = "The run's workflow failed outside its own code (engine 2b spec §7.6)."
+LIVE = (WorkflowExecutionStatus.RUNNING, WorkflowExecutionStatus.CONTINUED_AS_NEW)  # its successor is starting
+
+
+class Leader:
+    """The reconciler's one leader among the dispatchers: a session-level advisory lock on a connection of its own,
+    held while that connection lives. Losing the connection loses the lock; closing drops the connection, so the lock
+    is never left on a pooled one."""
+
+    def __init__(self, engine: AsyncEngine) -> None:
+        self._engine = engine
+        self._connection: AsyncConnection | None = None
+
+    async def leading(self) -> bool:
+        if self._connection is not None:
+            try:
+                await self._connection.execute(text("select 1"))
+                await self._connection.commit()
+                return True
+            except Exception as e:  # the connection, and its lock, are gone
+                log.warning("reconciler_leadership_lost", error=type(e).__name__)
+                await self.close()
+        connection = await self._engine.connect()
+        try:
+            found = await connection.execute(
+                text("select pg_try_advisory_lock(hashtextextended(:k, 0))"), {"k": LEADER_LOCK}
+            )
+            got = bool(found.scalar())
+            await connection.commit()
+        except BaseException:
+            await connection.invalidate()
+            await connection.close()
+            raise
+        if got:
+            self._connection = connection
+            return True
+        await connection.close()
+        return False
+
+    async def close(self) -> None:
+        connection, self._connection = self._connection, None
+        if connection is not None:
+            await connection.invalidate()  # the server ends the session, and its lock with it
+            await connection.close()
+
+
+async def reconcile_once(
+    sessionmaker: async_sessionmaker[AsyncSession], client: Client, keys: KeySource, settings: Settings
+) -> dict[str, int]:
+    """One pass over what needs settling: what happened, counted, for the reconciler's report."""
+    async with sessionmaker() as s:
+        picked = (
+            await s.execute(
+                text("select tenant_id, request_id, kind from reconcile_candidates(:grace, :recheck, :n)"),
+                {"grace": GRACE, "recheck": RECHECK, "n": BATCH},
+            )
+        ).all()
+    counts: Counter[str] = Counter()
+    for tenant_id, request_id, kind in picked:
+        try:
+            if kind == "starting":
+                happened = await _starting(sessionmaker, client, keys, settings, tenant_id, request_id)
+            elif kind == "open":
+                happened = await _open(sessionmaker, client, tenant_id, request_id)
+            else:
+                happened = await _slot(sessionmaker, client, tenant_id, request_id)
+        except Exception as e:  # a bug or an outage: left as it was, asked about again after RECHECK
+            log.error("reconcile_failed", tenant_id=str(tenant_id), request_id=str(request_id), kind=kind,
+                      error=type(e).__name__)  # fmt: skip
+            counts["error"] += 1
+            await _checked_alone(sessionmaker, tenant_id, request_id)
+            continue
+        counts[happened] += 1
+    return dict(counts)
+
+
+# --- uncertain starts ----------------------------------------------------------------------------------------------
+
+
+async def _starting(
+    sessionmaker: async_sessionmaker[AsyncSession], client: Client, keys: KeySource, settings: Settings,
+    tenant_id: uuid.UUID, request_id: uuid.UUID,
+) -> str:  # fmt: skip
+    """A request still `starting` past its grace period: found and verified, `started`; absent from a namespace that
+    answers, back in the queue; anything else, left `starting`."""
+    handle = client.get_workflow_handle(run_workflow_id(str(tenant_id), str(request_id)))
+    try:
+        await handle.describe()
+    except RPCError as e:
+        if e.status == RPCStatusCode.NOT_FOUND and await _namespace_answers(client):
+            return await dispatch.settle(sessionmaker, dispatch.Ref(request_id, tenant_id), dispatch.Outcome("absent"),
+                                         audited=True)  # fmt: skip
+        return await _unresolved(sessionmaker, tenant_id, request_id, e.status.name)
+    except Exception as e:  # a lost connection or a timeout: nothing is known
+        return await _unresolved(sessionmaker, tenant_id, request_id, type(e).__name__)
+    try:
+        expected = await _expected(sessionmaker, keys, settings, tenant_id, request_id)
+    except dispatch.KeyUnusableError:
+        return await _unresolved(sessionmaker, tenant_id, request_id, "key_unusable")
+    if expected is None:
+        return "moved"
+    outcome = await dispatch.verify(client, expected)
+    if outcome.kind == "uncertain":
+        return await _unresolved(sessionmaker, tenant_id, request_id, outcome.detail)
+    # Started: a closed execution's end is recorded by the next pass, which finds the row still `running`.
+    return await dispatch.settle(sessionmaker, expected, outcome, audited=True)
+
+
+async def _expected(
+    sessionmaker: async_sessionmaker[AsyncSession], keys: KeySource, settings: Settings, tenant_id: uuid.UUID,
+    request_id: uuid.UUID,
+) -> dispatch.Starting | None:  # fmt: skip
+    """The start the request would have sent, to verify a found execution against (§7.4); None once it isn't
+    `starting`."""
+    async with sessionmaker() as s, s.begin():
+        await tenant_scope(s, tenant_id)
+        request = (
+            await s.execute(select(RunRequest).where(RunRequest.id == request_id, RunRequest.status == "starting"))
+        ).scalar_one_or_none()
+        if request is None or request.workflow_version_id is None:
+            return None
+        cipher = ClaimCipher(dispatch.KeyFailures(keys))
+        envelope = await claims.read_envelope(s, cipher, tenant_id, request_id=request_id)
+        start = dispatch.run_input(request, request.workflow_version_id, envelope, settings)
+    return dispatch.Starting(request_id, tenant_id, start)
+
+
+async def _namespace_answers(client: Client) -> bool:
+    """Whether the namespace is reachable, so a NOT_FOUND is about the execution (§7.6). Any failure: it isn't known."""
+    try:
+        await client.workflow_service.describe_namespace(DescribeNamespaceRequest(namespace=client.namespace))
+    except Exception:
+        return False
+    return True
+
+
+async def _unresolved(
+    sessionmaker: async_sessionmaker[AsyncSession], tenant_id: uuid.UUID, request_id: uuid.UUID, detail: str
+) -> str:
+    """Left `starting`, its slot held; an error once it has been so for ALERT_AFTER."""
+    async with sessionmaker() as s, s.begin():
+        await tenant_scope(s, tenant_id)
+        age = (
+            await s.execute(
+                select(text("statement_timestamp() - reserved_at"))
+                .select_from(RunSlot)
+                .where(RunSlot.run_id == request_id)
+            )
+        ).scalar()
+        await _checked(s, request_id)
+    if isinstance(age, timedelta) and age >= ALERT_AFTER:
+        log.error("start_unresolved", request_id=str(request_id), detail=detail, age_s=int(age.total_seconds()))
+    else:
+        log.warning("start_unresolved", request_id=str(request_id), detail=detail)
+    return "unresolved"
+
+
+# --- runs whose workflow closed, and leaked slots ------------------------------------------------------------------
+
+
+@dataclass(frozen=True)
+class Ended:
+    status: str
+    error_code: str | None = None
+    error_message: str | None = None
+    iterations: int = 0
+
+
+async def _open(
+    sessionmaker: async_sessionmaker[AsyncSession], client: Client, tenant_id: uuid.UUID, run_id: uuid.UUID
+) -> str:
+    """A started run whose row is still `running`: once the logical run's latest execution is closed, the end Temporal
+    reports is recorded, and its slot released, in one transaction. Its own end write wins: never over an ended row."""
+    handle = client.get_workflow_handle(run_workflow_id(str(tenant_id), str(run_id)), result_type=RunResult)
+    try:
+        described = await handle.describe()  # no run id: the latest execution, past every continue-as-new
+    except Exception as e:
+        log.warning("reconcile_unanswered", run_id=str(run_id), error=type(e).__name__)
+        await _checked_alone(sessionmaker, tenant_id, run_id)
+        return "unresolved"
+    if described.status is None or described.status in LIVE:
+        await _checked_alone(sessionmaker, tenant_id, run_id)
+        return "running"
+    ended = await _ended(handle, described.status, run_id)
+    async with sessionmaker() as s, s.begin():
+        await tenant_scope(s, tenant_id)
+        await runs.finish_run(
+            s, run_id, status=ended.status, ended_at=described.close_time or datetime.now(UTC),
+            error_code=ended.error_code, error_message=ended.error_message, iterations=ended.iterations,
+            if_running=True,
+        )  # fmt: skip
+        await dispatch.release(s, run_id)
+        await _checked(s, run_id)
+    return "ended"
+
+
+async def _ended(handle: Any, status: WorkflowExecutionStatus, run_id: uuid.UUID) -> Ended:
+    """The end Temporal reports for a closed execution (§7.6)."""
+    if status == WorkflowExecutionStatus.COMPLETED:
+        result: RunResult = await handle.result()  # the run's own end, which its end write should have recorded
+        error = result.error or {}
+        return Ended(result.status, error.get("code"), error.get("message"), result.iterations)
+    if status == WorkflowExecutionStatus.CANCELED:
+        return Ended("cancelled", CANCELLED.code, CANCELLED.message)
+    if status == WorkflowExecutionStatus.TERMINATED:
+        return Ended("failed", TERMINATED, TERMINATED_MESSAGE)
+    log.error("run_execution_failed", run_id=str(run_id), status=status.name)  # Dewpoint sets no execution timeout
+    return Ended("failed", INTERNAL_ERROR, FAILED_MESSAGE)
+
+
+async def _slot(
+    sessionmaker: async_sessionmaker[AsyncSession], client: Client, tenant_id: uuid.UUID, run_id: uuid.UUID
+) -> str:
+    """A slot whose run's row has ended: released only once the logical run's latest execution is closed, or absent
+    from a namespace that answers."""
+    try:
+        described = await client.get_workflow_handle(run_workflow_id(str(tenant_id), str(run_id))).describe()
+    except RPCError as e:
+        if not (e.status == RPCStatusCode.NOT_FOUND and await _namespace_answers(client)):
+            log.warning("reconcile_unanswered", run_id=str(run_id), error=e.status.name)
+            await _checked_alone(sessionmaker, tenant_id, run_id)
+            return "unresolved"
+    except Exception as e:
+        log.warning("reconcile_unanswered", run_id=str(run_id), error=type(e).__name__)
+        await _checked_alone(sessionmaker, tenant_id, run_id)
+        return "unresolved"
+    else:
+        if described.status is None or described.status in LIVE:
+            log.warning("slot_execution_live", run_id=str(run_id))  # its row ended, its execution didn't
+            await _checked_alone(sessionmaker, tenant_id, run_id)
+            return "live"
+    async with sessionmaker() as s, s.begin():
+        await tenant_scope(s, tenant_id)
+        await dispatch.release(s, run_id)
+        await _checked(s, run_id)
+    return "released"
+
+
+async def _checked(s: AsyncSession, request_id: uuid.UUID) -> None:
+    await s.execute(text("update run_requests set checked_at = statement_timestamp() where id = :i"), {"i": request_id})
+
+
+async def _checked_alone(
+    sessionmaker: async_sessionmaker[AsyncSession], tenant_id: uuid.UUID, request_id: uuid.UUID
+) -> None:
+    async with sessionmaker() as s, s.begin():
+        await tenant_scope(s, tenant_id)
+        await _checked(s, request_id)
diff --git a/backend/src/dewpoint/core/models/requests.py b/backend/src/dewpoint/core/models/requests.py
index e965234..47a7ab2 100644
--- a/backend/src/dewpoint/core/models/requests.py
+++ b/backend/src/dewpoint/core/models/requests.py
@@ -40,6 +40,7 @@ class RunRequest(Base):
     queued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
     ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
     cancel_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
+    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # the reconciler's last look
     envelope_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
 
 
diff --git a/backend/tests/apps/dispatcher/test_reconcile.py b/backend/tests/apps/dispatcher/test_reconcile.py
new file mode 100644
index 0000000..e4ab42d
--- /dev/null
+++ b/backend/tests/apps/dispatcher/test_reconcile.py
@@ -0,0 +1,185 @@
+# SPDX-License-Identifier: Apache-2.0
+"""The reconciler (engine 2b spec §7.6): one leader among the dispatchers settles what a start left uncertain. An
+execution it finds is verified as a dispatcher verifies one, and its request is `started`; a request goes back to the
+queue, no attempt counted, only after a trustworthy absence (a describe after the grace period, from a namespace that
+answers); any error leaves it `starting`, its slot held. A slot is released only once its run's latest execution is
+closed. Every request it settles is audited (§2.4)."""
+
+import uuid
+from datetime import timedelta
+from typing import Any
+
+import pytest
+from sqlalchemy import text
+from temporalio.service import RPCStatusCode
+
+from dewpoint.apps.dispatcher import dispatch, reconcile
+from dewpoint.engine.runtime.activities import ENGINE_QUEUE
+from dewpoint.engine.runtime.ids import run_workflow_id
+from dewpoint.engine.runtime.workflow import RunGraph
+from tests.apps.dispatcher.support import begin, state
+from tests.apps.test_admission import KEYS
+from tests.apps.test_runs import rpc
+
+pytestmark = pytest.mark.usefixtures("development_deployment")
+
+
+async def starting(dispatch_sessionmaker: Any, request: Any, settings: Any) -> dispatch.Starting:
+    found = await begin(dispatch_sessionmaker, request, settings)
+    assert isinstance(found, dispatch.Starting)
+    return found
+
+
+async def aged(owner: Any, request_id: uuid.UUID, by: timedelta = reconcile.GRACE + timedelta(seconds=5)) -> None:
+    """The start was made `by` ago: its slot was reserved then."""
+    async with owner() as s, s.begin():
+        await s.execute(
+            text("update run_slots set reserved_at = reserved_at - cast(:by as interval) where run_id = :i"),
+            {"by": by, "i": request_id},
+        )
+
+
+async def reconciled(owner: Any) -> list[Any]:
+    async with owner() as s:
+        rows = await s.execute(text("select target_id, details from audit_log where action = 'run.request.reconciled'"))
+        return [tuple(r) for r in rows]
+
+
+async def once(dispatch_sessionmaker: Any, client: Any, settings: Any) -> dict[str, int]:
+    return await reconcile.reconcile_once(dispatch_sessionmaker, client, KEYS, settings)
+
+
+class Handle:
+    def __init__(self, error: BaseException | None) -> None:
+        self.error = error
+
+    async def describe(self) -> Any:
+        if self.error is not None:
+            raise self.error
+        raise AssertionError("no execution in this fake")
+
+
+class Service:
+    def __init__(self, namespace_error: BaseException | None) -> None:
+        self.namespace_error = namespace_error
+
+    async def describe_namespace(self, _: Any) -> Any:
+        if self.namespace_error is not None:
+            raise self.namespace_error
+        return object()
+
+
+class DescribeFails:
+    """A client whose describe fails with `error`, and whose namespace answers unless `namespace_error`."""
+
+    namespace = "default"
+
+    def __init__(self, error: BaseException, namespace_error: BaseException | None = None) -> None:
+        self.error, self.workflow_service = error, Service(namespace_error)
+
+    def get_workflow_handle(self, _: str) -> Handle:
+        return Handle(self.error)
+
+
+async def test_one_dispatcher_leads_the_reconciler_at_a_time(dispatch_sessionmaker) -> None:
+    engine = dispatch_sessionmaker.kw["bind"]
+    first, second = reconcile.Leader(engine), reconcile.Leader(engine)
+    try:
+        assert await first.leading() and not await second.leading()
+        assert await first.leading()  # still its own
+        await first.close()
+        assert await second.leading()
+    finally:
+        await first.close()
+        await second.close()
+
+
+async def test_an_uncertain_start_whose_execution_exists_is_verified_and_started(
+    queued, owner_sessionmaker, dispatch_sessionmaker, api_settings, env
+) -> None:
+    _, _, request = queued
+    lost = await starting(dispatch_sessionmaker, request, api_settings)
+    assert (await dispatch.start(env.client, lost)).kind == "started"  # accepted; its answer never settled
+    await aged(owner_sessionmaker, request.id)
+    assert await once(dispatch_sessionmaker, env.client, api_settings) == {"started": 1}
+    after = await state(owner_sessionmaker, request.id)
+    assert after["request"] == ("started", None, 0) and after["slot"] == 1  # the root's end write releases it
+    assert after["run"][0] == "running" and after["run"][1] is not None
+    assert await reconciled(owner_sessionmaker) == [(str(request.id), {"outcome": "started"})]
+
+
+async def test_an_uncertain_start_absent_after_its_grace_goes_back_to_the_queue(
+    queued, owner_sessionmaker, dispatch_sessionmaker, api_settings, env
+) -> None:
+    _, _, request = queued
+    await starting(dispatch_sessionmaker, request, api_settings)  # never reached Temporal
+    await aged(owner_sessionmaker, request.id)
+    assert await once(dispatch_sessionmaker, env.client, api_settings) == {"absent": 1}
+    after = await state(owner_sessionmaker, request.id)
+    assert after["request"] == ("queued", None, 0) and after["slot"] == 0  # no attempt counted
+    assert after["run"][0] == "running"  # kept, non-terminal, hidden behind the request (§7.8)
+    assert await reconciled(owner_sessionmaker) == [(str(request.id), {"outcome": "absent"})]
+    assert isinstance(await begin(dispatch_sessionmaker, request, api_settings), dispatch.Starting)  # due at once
+
+
+async def test_an_uncertain_start_within_its_grace_is_left_alone(
+    queued, owner_sessionmaker, dispatch_sessionmaker, api_settings, env
+) -> None:
+    _, _, request = queued
+    await starting(dispatch_sessionmaker, request, api_settings)
+    assert await once(dispatch_sessionmaker, env.client, api_settings) == {}
+    assert (await state(owner_sessionmaker, request.id))["request"][0] == "starting"
+
+
+@pytest.mark.parametrize(
+    "client",
+    [
+        DescribeFails(rpc(RPCStatusCode.UNAVAILABLE)),
+        DescribeFails(rpc(RPCStatusCode.NOT_FOUND), namespace_error=rpc(RPCStatusCode.UNAVAILABLE)),
+        DescribeFails(ConnectionResetError()),
+    ],
+    ids=["unavailable", "namespace_unreachable", "connection_reset"],
+)
+async def test_an_absence_that_cant_be_trusted_keeps_the_start_unresolved(
+    queued, owner_sessionmaker, dispatch_sessionmaker, api_settings, client
+) -> None:
+    _, _, request = queued
+    await starting(dispatch_sessionmaker, request, api_settings)
+    await aged(owner_sessionmaker, request.id)
+    assert await once(dispatch_sessionmaker, client, api_settings) == {"unresolved": 1}
+    after = await state(owner_sessionmaker, request.id)
+    assert after["request"] == ("starting", None, 0) and after["slot"] == 1
+    assert await once(dispatch_sessionmaker, client, api_settings) == {}  # checked: not again before RECHECK
+
+
+async def test_another_execution_found_under_the_runs_id_is_an_id_collision(
+    queued, owner_sessionmaker, dispatch_sessionmaker, api_settings, env
+) -> None:
+    _, _, request = queued
+    lost = await starting(dispatch_sessionmaker, request, api_settings)
+    impostor = lost.start.__class__(**{**lost.start.__dict__, "version_id": str(uuid.uuid4())})
+    await env.client.start_workflow(RunGraph.run, impostor, id=run_workflow_id(impostor.tenant_id, impostor.run_id),
+                                    task_queue=ENGINE_QUEUE)  # fmt: skip
+    await aged(owner_sessionmaker, request.id)
+    assert await once(dispatch_sessionmaker, env.client, api_settings) == {"dead": 1}
+    after = await state(owner_sessionmaker, request.id)
+    assert after["request"][:2] == ("dead", "id_collision") and after["slot"] == 0
+
+
+async def test_a_leaked_slot_is_released_only_once_its_runs_execution_is_closed(
+    queued, owner_sessionmaker, dispatch_sessionmaker, api_settings, env
+) -> None:
+    """A slot whose run's row already ended (here by hand): released once Temporal says its execution closed, never
+    while it still runs."""
+    _, _, request = queued
+    started = await starting(dispatch_sessionmaker, request, api_settings)
+    assert await dispatch.settle(dispatch_sessionmaker, started, await dispatch.start(env.client, started)) == "started"
+    async with owner_sessionmaker() as s, s.begin():
+        await s.execute(text("update runs set status = 'failed', ended_at = now() where id = :i"), {"i": request.id})
+    assert await once(dispatch_sessionmaker, env.client, api_settings) == {"live": 1}
+    assert (await state(owner_sessionmaker, request.id))["slot"] == 1
+    await env.client.get_workflow_handle(run_workflow_id(str(request.tenant_id), str(request.id))).terminate()
+    async with owner_sessionmaker() as s, s.begin():
+        await s.execute(text("update run_requests set checked_at = null where id = :i"), {"i": request.id})
+    assert await once(dispatch_sessionmaker, env.client, api_settings) == {"released": 1}
+    assert (await state(owner_sessionmaker, request.id))["slot"] == 0
diff --git a/backend/tests/apps/dispatcher/test_reconcile_runs.py b/backend/tests/apps/dispatcher/test_reconcile_runs.py
new file mode 100644
index 0000000..1f41038
--- /dev/null
+++ b/backend/tests/apps/dispatcher/test_reconcile_runs.py
@@ -0,0 +1,128 @@
+# SPDX-License-Identifier: Apache-2.0
+"""Rows left `running` whose workflow closed (engine 2b spec §7.6): the reconciler follows the logical run to its
+latest execution and records the end Temporal reports, releasing the slot in the same transaction. This is how a run
+whose end write never landed, or was refused after its slot was released (the owner's M2 ruling), still ends."""
+
+import asyncio
+import dataclasses
+from types import SimpleNamespace
+from typing import Any
+
+import pytest
+from sqlalchemy import text
+from temporalio.client import WorkflowExecutionStatus
+
+from dewpoint.apps.dispatcher import dispatch, reconcile
+from dewpoint.apps.worker.store import DbRunStore
+from dewpoint.engine.runtime.activities import ProjectInput
+from dewpoint.engine.runtime.ids import run_workflow_id
+from dewpoint.engine.runtime.workflow import RunGraph
+from tests.apps.dispatcher.support import BUILD, begin, state
+from tests.apps.test_admission import KEYS
+from tests.apps.worker.harness import workers
+
+pytestmark = pytest.mark.usefixtures("development_deployment")
+
+
+async def started(dispatch_sessionmaker: Any, request: Any, settings: Any, client: Any = None) -> dispatch.Starting:
+    """`started`, its slot held and its row `running`: through a real start on `client`, or confirmed without one."""
+    found = await begin(dispatch_sessionmaker, request, settings)
+    assert isinstance(found, dispatch.Starting)
+    outcome = await dispatch.start(client, found) if client is not None else dispatch.Outcome("started")
+    assert await dispatch.settle(dispatch_sessionmaker, found, outcome) == "started"
+    return found
+
+
+async def ended(owner: Any, run_id: Any) -> tuple[Any, ...]:
+    async with owner() as s:
+        row = await s.execute(text("select status, error_code from runs where id = :i"), {"i": run_id})
+        return tuple(row.one())
+
+
+class NoEndWrite(DbRunStore):
+    """The worker's projection, but the root's end write never lands (a worker gone between its last step and it)."""
+
+    async def project(self, data: ProjectInput) -> None:
+        await super().project(dataclasses.replace(data, run=None))
+
+
+class Described:
+    """A client whose execution has closed with `status`."""
+
+    namespace = "default"
+
+    def __init__(self, status: WorkflowExecutionStatus) -> None:
+        self.status = status
+
+    def get_workflow_handle(self, _: str, **__: Any) -> Any:
+        status = self.status
+
+        class Handle:
+            async def describe(self) -> Any:
+                return SimpleNamespace(status=status, close_time=None)
+
+        return Handle()
+
+
+async def test_a_run_whose_execution_was_terminated_is_recorded_terminated_and_frees_its_slot(
+    queued, owner_sessionmaker, dispatch_sessionmaker, api_settings, env
+) -> None:
+    _, _, request = queued
+    await started(dispatch_sessionmaker, request, api_settings, env.client)
+    await env.client.get_workflow_handle(run_workflow_id(str(request.tenant_id), str(request.id))).terminate()
+    assert await reconcile.reconcile_once(dispatch_sessionmaker, env.client, KEYS, api_settings) == {"ended": 1}
+    assert await ended(owner_sessionmaker, request.id) == ("failed", "terminated")
+    assert (await state(owner_sessionmaker, request.id))["slot"] == 0
+
+
+@pytest.mark.parametrize("refused", [False, True], ids=["end_write_lost", "end_write_refused"])
+async def test_a_completed_run_whose_end_write_never_landed_ends_with_its_own_result(
+    queued, owner_sessionmaker, dispatch_sessionmaker, worker_sessionmaker, api_settings, env, refused
+) -> None:
+    ctx, _, request = queued
+    async with workers(env.client, NoEndWrite(worker_sessionmaker, KEYS)):
+        assert await dispatch.dispatch_once(dispatch_sessionmaker, env.client, KEYS, api_settings, BUILD) == {
+            "started": 1
+        }
+        handle = env.client.get_workflow_handle_for(RunGraph.run, run_workflow_id(str(ctx.tenant_id), str(request.id)))
+        assert (await asyncio.wait_for(handle.result(), 30)).status == "succeeded"
+    assert (await ended(owner_sessionmaker, request.id))[0] == "running"
+    if refused:  # the refused end write released its slot already (the owner's ruling on Task 10)
+        async with owner_sessionmaker() as s, s.begin():
+            await s.execute(text("delete from run_slots where run_id = :i"), {"i": request.id})
+    assert await reconcile.reconcile_once(dispatch_sessionmaker, env.client, KEYS, api_settings) == {"ended": 1}
+    assert await ended(owner_sessionmaker, request.id) == ("succeeded", None)
+    assert (await state(owner_sessionmaker, request.id))["slot"] == 0
+
+
+@pytest.mark.parametrize(
+    ("status", "recorded"),
+    [
+        (WorkflowExecutionStatus.CANCELED, ("cancelled", "cancelled")),
+        (WorkflowExecutionStatus.FAILED, ("failed", "internal_error")),
+        (WorkflowExecutionStatus.TIMED_OUT, ("failed", "internal_error")),
+    ],
+    ids=["canceled", "failed", "timed_out"],
+)
+async def test_the_end_temporal_reports_is_recorded(
+    queued, owner_sessionmaker, dispatch_sessionmaker, api_settings, status, recorded
+) -> None:
+    _, _, request = queued
+    await started(dispatch_sessionmaker, request, api_settings)
+    assert await reconcile.reconcile_once(dispatch_sessionmaker, Described(status), KEYS, api_settings) == {"ended": 1}
+    assert await ended(owner_sessionmaker, request.id) == recorded
+    assert (await state(owner_sessionmaker, request.id))["slot"] == 0
+
+
+@pytest.mark.parametrize("status", [WorkflowExecutionStatus.RUNNING, WorkflowExecutionStatus.CONTINUED_AS_NEW])
+async def test_a_live_logical_run_is_left_running(
+    queued, owner_sessionmaker, dispatch_sessionmaker, api_settings, status
+) -> None:
+    """Continued as new: its successor is the logical run's latest execution, still to be followed."""
+    _, _, request = queued
+    await started(dispatch_sessionmaker, request, api_settings)
+    assert await reconcile.reconcile_once(dispatch_sessionmaker, Described(status), KEYS, api_settings) == {
+        "running": 1
+    }
+    assert await ended(owner_sessionmaker, request.id) == ("running", None)
+    assert (await state(owner_sessionmaker, request.id))["slot"] == 1
```

### Task 16: Cancels — a queued request at once, a starting one when it resolves, a running run through the dispatcher

**Commit:** `c5024d8` (prototype `proto/2b2-v2`); the replay's tree was identical: yes.

**Create:** `backend/migrations/versions/0022_cancels.py`, `backend/src/dewpoint/apps/cancels.py`, `backend/src/dewpoint/apps/dispatcher/cancels.py`, `backend/tests/apps/dispatcher/test_cancels.py`

**Modify:** `backend/src/dewpoint/apps/dispatcher/dispatch.py`, `backend/src/dewpoint/apps/dispatcher/main.py`, `backend/src/dewpoint/apps/dispatcher/reconcile.py`, `backend/src/dewpoint/core/models/requests.py`

**What it does:**

cancel_request runs in its caller's transaction (the API's, M4). A
queued request is cancelled at once (user_cancelled), audited, and the
row an earlier attempt wrote ends with it through end_unstarted_run():
the API holds no write on runs, and the function ends a row only for a
request of the caller's tenant already cancelled. A starting request or
a running run has its cancel recorded, once, audited: settle applies it
when the start doesn't happen (refused, throttled, absent), and the
reconciler's leader sends a started run's cancel to Temporal once
(cancel_sent_at, cancel_candidates(), 0022).


- [ ] **Step 1: its tests alone, before its code.** Run: `uv run pytest -n 4 tests/apps/dispatcher/test_cancels.py`. Replay result (exit 1), shortened:

```
==================================== ERRORS ====================================
____________ ERROR collecting tests/apps/dispatcher/test_cancels.py ____________
ImportError while importing test module '/private/tmp/claude-501/-Users-tmunzer-4-dev-mist-dewpoint/1e3145a1-199e-4b31-be1b-1e3bfd266be7/scratchpad/2b2-plan/replay/backend/tests/apps/dispatcher/test_cancels.py'.
Hint: make sure your test modules/packages have valid Python names.
Traceback:
/opt/homebrew/Cellar/python@3.14/3.14.7/Frameworks/Python.framework/Versions/3.14/lib/python3.14/importlib/__init__.py:88: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
tests/apps/dispatcher/test_cancels.py:14: in <module>
    from dewpoint.apps import cancels
E   ImportError: cannot import name 'cancels' from 'dewpoint.apps' (/private/tmp/claude-501/-Users-tmunzer-4-dev-mist-dewpoint/1e3145a1-199e-4b31-be1b-1e3bfd266be7/scratchpad/2b2-plan/replay/backend/src/dewpoint/apps/__init__.py)
=========================== short test summary info ============================
ERROR tests/apps/dispatcher/test_cancels.py - ImportError while importing tes...
1 error in 5.23s
```

- [ ] **Step 2: its code, then the same tests.** Replay result (exit 0), shortened:

```
............                                                             [100%]
12 passed in 11.77s
```

- [ ] **Step 3: commit.** `git cherry-pick --no-commit c5024d8 && git commit -C c5024d8`

The diff:

```diff
diff --git a/backend/migrations/versions/0022_cancels.py b/backend/migrations/versions/0022_cancels.py
new file mode 100644
index 0000000..5806015
--- /dev/null
+++ b/backend/migrations/versions/0022_cancels.py
@@ -0,0 +1,53 @@
+# SPDX-License-Identifier: Apache-2.0
+"""cancels (engine 2b spec §7.7, §7.8): the API cancels a queued request at once, and a started run through the
+dispatcher
+
+`run_requests.cancel_sent_at`: when the dispatcher sent a recorded cancel to Temporal, so it's sent once.
+`end_unstarted_run()`: the API holds no write on `runs`; this ends the row an earlier attempt wrote, in the cancel's
+own transaction, and only for a request of the caller's tenant already `cancelled` (a request that never started).
+`cancel_candidates()`: ids only, as `dispatch_candidates()`: started runs, still running, with a cancel to send."""
+
+import sqlalchemy as sa
+from alembic import op
+
+revision = "0022"
+down_revision = "0021"
+branch_labels = None
+depends_on = None
+
+END_UNSTARTED = """
+CREATE FUNCTION end_unstarted_run(run uuid) RETURNS void
+LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path = public, pg_temp AS $$
+  UPDATE runs SET status = 'cancelled', ended_at = statement_timestamp(), error_code = 'user_cancelled'
+  WHERE id = run AND tenant_id = app_tenant_id() AND status = 'running'
+    AND EXISTS (
+      SELECT 1 FROM run_requests r WHERE r.id = run AND r.tenant_id = app_tenant_id() AND r.status = 'cancelled'
+    )
+$$"""
+
+CANDIDATES = """
+CREATE FUNCTION cancel_candidates(max_rows integer)
+RETURNS TABLE (tenant_id uuid, request_id uuid)
+LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
+  SELECT r.tenant_id, r.id FROM run_requests r JOIN runs u ON u.id = r.id
+  WHERE r.status = 'started' AND r.cancel_requested_at IS NOT NULL AND r.cancel_sent_at IS NULL
+    AND u.status = 'running'
+  ORDER BY r.cancel_requested_at, r.id
+  LIMIT max_rows
+$$"""
+
+
+def upgrade() -> None:
+    op.add_column("run_requests", sa.Column("cancel_sent_at", sa.DateTime(timezone=True)))
+    op.execute(END_UNSTARTED)
+    op.execute("REVOKE ALL ON FUNCTION end_unstarted_run(uuid) FROM PUBLIC")
+    op.execute("GRANT EXECUTE ON FUNCTION end_unstarted_run(uuid) TO dewpoint_api")
+    op.execute(CANDIDATES)
+    op.execute("REVOKE ALL ON FUNCTION cancel_candidates(integer) FROM PUBLIC")
+    op.execute("GRANT EXECUTE ON FUNCTION cancel_candidates(integer) TO dewpoint_dispatch")
+
+
+def downgrade() -> None:
+    op.execute("DROP FUNCTION cancel_candidates(integer)")
+    op.execute("DROP FUNCTION end_unstarted_run(uuid)")
+    op.drop_column("run_requests", "cancel_sent_at")
diff --git a/backend/src/dewpoint/apps/cancels.py b/backend/src/dewpoint/apps/cancels.py
new file mode 100644
index 0000000..0e58ffc
--- /dev/null
+++ b/backend/src/dewpoint/apps/cancels.py
@@ -0,0 +1,61 @@
+# SPDX-License-Identifier: Apache-2.0
+"""A user's cancel (engine 2b spec §7.7, §7.8), in its caller's transaction (the API's): a queued request is
+cancelled at once, audited, with the row an earlier attempt wrote; a `starting` request or a running run has its cancel
+recorded, once, for the dispatcher, which applies it when the start resolves or sends it to Temporal. The API needs no
+Temporal client and no write on `runs`."""
+
+import uuid
+from datetime import UTC, datetime
+
+from sqlalchemy import select, text
+from sqlalchemy.ext.asyncio import AsyncSession
+
+from dewpoint.core.audit import service as audit
+from dewpoint.core.db import tenant_scope
+from dewpoint.core.models.requests import RunRequest
+
+USER_CANCELLED = "user_cancelled"
+
+
+class RequestNotFoundError(Exception):
+    """No such request in this tenant. The message is fixed."""
+
+
+async def cancel_request(s: AsyncSession, *, tenant_id: uuid.UUID, request_id: uuid.UUID, actor_id: uuid.UUID) -> str:
+    """`cancelled` (it was queued), `requested` (recorded for the dispatcher), or `ended` (nothing left to cancel).
+    Raises RequestNotFoundError."""
+    await tenant_scope(s, tenant_id)
+    request = (
+        await s.execute(
+            select(RunRequest)
+            .where(RunRequest.id == request_id)
+            .with_for_update()
+            .execution_options(populate_existing=True)
+        )
+    ).scalar_one_or_none()
+    if request is None:
+        raise RequestNotFoundError("No such run request.")
+    if request.status == "queued":  # the dispatcher skips a request locked here, and re-reads it after
+        now = datetime.now(UTC)
+        request.status, request.reason, request.ended_at = "cancelled", USER_CANCELLED, now
+        request.cancel_requested_at = now
+        await s.flush()
+        await s.execute(text("select end_unstarted_run(:i)"), {"i": request.id})
+        await _audited(s, request, actor_id, "run.request.cancel")
+        return "cancelled"
+    if request.status == "starting" or (request.status == "started" and await _running(s, request.id)):
+        if request.cancel_requested_at is None:
+            request.cancel_requested_at = datetime.now(UTC)
+            await _audited(s, request, actor_id, "run.cancel.requested")
+        return "requested"
+    return "ended"
+
+
+async def _running(s: AsyncSession, run_id: uuid.UUID) -> bool:
+    found = await s.execute(text("select status from runs where id = :i"), {"i": run_id})
+    return found.scalar() == "running"
+
+
+async def _audited(s: AsyncSession, request: RunRequest, actor_id: uuid.UUID, action: str) -> None:
+    await audit.record(s, tenant_id=request.tenant_id, actor_id=actor_id, action=action, target_type="run_request",
+                       target_id=str(request.id), details={"reason": USER_CANCELLED})  # fmt: skip
diff --git a/backend/src/dewpoint/apps/dispatcher/cancels.py b/backend/src/dewpoint/apps/dispatcher/cancels.py
new file mode 100644
index 0000000..2d7d1a8
--- /dev/null
+++ b/backend/src/dewpoint/apps/dispatcher/cancels.py
@@ -0,0 +1,47 @@
+# SPDX-License-Identifier: Apache-2.0
+"""Sending recorded cancels to Temporal (engine 2b spec §7.7): the dispatcher's, so the API has no Temporal client. A
+started run with a recorded cancel, still running, gets one cancel request; the run then ends as cancelled through its
+own end write (or the reconciler, §7.6). Ids reach it only through `cancel_candidates()`."""
+
+from collections import Counter
+
+import structlog
+from sqlalchemy import text
+from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
+from temporalio.client import Client
+from temporalio.service import RPCError, RPCStatusCode
+
+from dewpoint.apps.dispatcher.reconcile import namespace_answers
+from dewpoint.core.db import tenant_scope
+from dewpoint.engine.runtime.ids import run_workflow_id
+
+log = structlog.get_logger("dewpoint.dispatcher")
+BATCH = 50  # cancels per cycle
+
+
+async def send_cancels(sessionmaker: async_sessionmaker[AsyncSession], client: Client) -> dict[str, int]:
+    """What happened, counted: `sent`, `closed` (its execution had already ended), `unsent` (tried again next cycle)."""
+    async with sessionmaker() as s:
+        picked = (await s.execute(text("select tenant_id, request_id from cancel_candidates(:n)"), {"n": BATCH})).all()
+    counts: Counter[str] = Counter()
+    for tenant_id, request_id in picked:
+        happened = "sent"
+        try:
+            await client.get_workflow_handle(run_workflow_id(str(tenant_id), str(request_id))).cancel()
+        except RPCError as e:
+            if not (e.status == RPCStatusCode.NOT_FOUND and await namespace_answers(client)):
+                log.warning("cancel_unsent", request_id=str(request_id), error=e.status.name)
+                counts["unsent"] += 1
+                continue
+            happened = "closed"  # nothing left to cancel: the reconciler records its end
+        except Exception as e:
+            log.warning("cancel_unsent", request_id=str(request_id), error=type(e).__name__)
+            counts["unsent"] += 1
+            continue
+        async with sessionmaker() as s, s.begin():
+            await tenant_scope(s, tenant_id)
+            await s.execute(
+                text("update run_requests set cancel_sent_at = statement_timestamp() where id = :i"), {"i": request_id}
+            )
+        counts[happened] += 1
+    return dict(counts)
diff --git a/backend/src/dewpoint/apps/dispatcher/dispatch.py b/backend/src/dewpoint/apps/dispatcher/dispatch.py
index 3b9dfbd..2250c7e 100644
--- a/backend/src/dewpoint/apps/dispatcher/dispatch.py
+++ b/backend/src/dewpoint/apps/dispatcher/dispatch.py
@@ -29,6 +29,7 @@ from temporalio.converter import DataConverter, WorkflowSerializationContext
 from temporalio.exceptions import WorkflowAlreadyStartedError
 from temporalio.service import RPCError, RPCStatusCode
 
+from dewpoint.apps.cancels import USER_CANCELLED
 from dewpoint.apps.codec import CodecRefusedError
 from dewpoint.apps.dispatcher.observe import REQUIRED, Build
 from dewpoint.core.audit import service as audit
@@ -426,6 +427,11 @@ async def _settle(s: AsyncSession, starting: Target, outcome: Outcome) -> str:
         log.warning("start_uncertain", request_id=str(request.id), detail=outcome.detail)
         return "uncertain"  # starting, its slot held, for the reconciler (§7.6)
     await release(s, request.id)
+    if outcome.kind in ("refused", "throttled", "absent") and request.cancel_requested_at is not None:
+        # A cancel recorded while it was starting, applied now that it didn't start (§7.8). A 10th refusal is
+        # cancelled too: the user asked first.
+        await _cancel(s, request, USER_CANCELLED, {"reason": USER_CANCELLED})
+        return "cancelled"
     if outcome.kind == "throttled":
         request.status, request.next_attempt_at = "queued", datetime.now(UTC) + backoff(1)
         return "throttled"
diff --git a/backend/src/dewpoint/apps/dispatcher/main.py b/backend/src/dewpoint/apps/dispatcher/main.py
index a132a8d..d02332f 100644
--- a/backend/src/dewpoint/apps/dispatcher/main.py
+++ b/backend/src/dewpoint/apps/dispatcher/main.py
@@ -12,6 +12,7 @@ from temporalio.client import Client
 from temporalio.service import RPCError, RPCStatusCode
 
 from dewpoint.apps.codec import KeyringKeys, data_converter
+from dewpoint.apps.dispatcher.cancels import send_cancels
 from dewpoint.apps.dispatcher.dispatch import dispatch_once
 from dewpoint.apps.dispatcher.observe import observe, report
 from dewpoint.apps.dispatcher.reconcile import Leader, reconcile_once
@@ -57,6 +58,7 @@ async def run(settings: Settings) -> None:
                 await report(sessionmaker, instance, build_id, {"current_build": bool(build), **done})
                 if await leader.leading():
                     settled = await reconcile_once(sessionmaker, client, keys, settings)
+                    settled.update({f"cancel_{k}": v for k, v in (await send_cancels(sessionmaker, client)).items()})
                     await report(sessionmaker, reconciler, build_id, {**settled}, kind="reconciler")
                 await asyncio.sleep(CYCLE_S)
         finally:
diff --git a/backend/src/dewpoint/apps/dispatcher/reconcile.py b/backend/src/dewpoint/apps/dispatcher/reconcile.py
index 908457f..353e0f0 100644
--- a/backend/src/dewpoint/apps/dispatcher/reconcile.py
+++ b/backend/src/dewpoint/apps/dispatcher/reconcile.py
@@ -127,7 +127,7 @@ async def _starting(
     try:
         await handle.describe()
     except RPCError as e:
-        if e.status == RPCStatusCode.NOT_FOUND and await _namespace_answers(client):
+        if e.status == RPCStatusCode.NOT_FOUND and await namespace_answers(client):
             return await dispatch.settle(sessionmaker, dispatch.Ref(request_id, tenant_id), dispatch.Outcome("absent"),
                                          audited=True)  # fmt: skip
         return await _unresolved(sessionmaker, tenant_id, request_id, e.status.name)
@@ -165,7 +165,7 @@ async def _expected(
     return dispatch.Starting(request_id, tenant_id, start)
 
 
-async def _namespace_answers(client: Client) -> bool:
+async def namespace_answers(client: Client) -> bool:
     """Whether the namespace is reachable, so a NOT_FOUND is about the execution (§7.6). Any failure: it isn't known."""
     try:
         await client.workflow_service.describe_namespace(DescribeNamespaceRequest(namespace=client.namespace))
@@ -256,7 +256,7 @@ async def _slot(
     try:
         described = await client.get_workflow_handle(run_workflow_id(str(tenant_id), str(run_id))).describe()
     except RPCError as e:
-        if not (e.status == RPCStatusCode.NOT_FOUND and await _namespace_answers(client)):
+        if not (e.status == RPCStatusCode.NOT_FOUND and await namespace_answers(client)):
             log.warning("reconcile_unanswered", run_id=str(run_id), error=e.status.name)
             await _checked_alone(sessionmaker, tenant_id, run_id)
             return "unresolved"
diff --git a/backend/src/dewpoint/core/models/requests.py b/backend/src/dewpoint/core/models/requests.py
index 47a7ab2..14903c1 100644
--- a/backend/src/dewpoint/core/models/requests.py
+++ b/backend/src/dewpoint/core/models/requests.py
@@ -40,6 +40,7 @@ class RunRequest(Base):
     queued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
     ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
     cancel_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
+    cancel_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
     checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # the reconciler's last look
     envelope_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
 
diff --git a/backend/tests/apps/dispatcher/test_cancels.py b/backend/tests/apps/dispatcher/test_cancels.py
new file mode 100644
index 0000000..870de86
--- /dev/null
+++ b/backend/tests/apps/dispatcher/test_cancels.py
@@ -0,0 +1,154 @@
+# SPDX-License-Identifier: Apache-2.0
+"""Cancels (engine 2b spec §7.7, §7.8): a queued request is cancelled at once, audited, with the row an earlier attempt
+wrote; a `starting` one has its cancel recorded and applied when the start resolves (`cancelled` if it didn't start,
+sent to Temporal if it did); a started run's cancel is recorded and the dispatcher sends it, once, so the API needs no
+Temporal client. The API ends a run's row only for a request it cancelled."""
+
+import uuid
+from typing import Any
+
+import pytest
+from sqlalchemy import text
+from temporalio.api.enums.v1 import EventType
+
+from dewpoint.apps import cancels
+from dewpoint.apps.dispatcher import cancels as sending
+from dewpoint.apps.dispatcher import dispatch
+from dewpoint.core.db import tenant_scope
+from dewpoint.engine.runtime.ids import run_workflow_id
+from tests.apps.dispatcher.support import begin, state
+
+pytestmark = pytest.mark.usefixtures("development_deployment")
+
+
+async def cancel(api: Any, ctx: Any, request_id: uuid.UUID) -> str:
+    async with api() as s, s.begin():
+        return await cancels.cancel_request(s, tenant_id=ctx.tenant_id, request_id=request_id, actor_id=ctx.user.id)
+
+
+async def audited(owner: Any, action: str) -> list[Any]:
+    async with owner() as s:
+        rows = await s.execute(
+            text("select target_id, actor_id, details from audit_log where action = :a order by seq"), {"a": action}
+        )
+        return [tuple(r) for r in rows]
+
+
+async def row(owner: Any, run_id: uuid.UUID) -> tuple[Any, ...] | None:
+    async with owner() as s:
+        found = (await s.execute(text("select status, error_code from runs where id = :i"), {"i": run_id})).first()
+        return tuple(found) if found else None
+
+
+async def starting(dispatch_sessionmaker: Any, request: Any, settings: Any) -> dispatch.Starting:
+    found = await begin(dispatch_sessionmaker, request, settings)
+    assert isinstance(found, dispatch.Starting)
+    return found
+
+
+async def test_a_queued_request_is_cancelled_at_once(
+    queued, owner_sessionmaker, api_sessionmaker, dispatch_sessionmaker, api_settings
+) -> None:
+    ctx, _, request = queued
+    assert await cancel(api_sessionmaker, ctx, request.id) == "cancelled"
+    assert await state(owner_sessionmaker, request.id) == {
+        "request": ("cancelled", "user_cancelled", 0), "run": None, "slot": 0,
+    }  # fmt: skip
+    assert await audited(owner_sessionmaker, "run.request.cancel") == [
+        (str(request.id), ctx.user.id, {"reason": "user_cancelled"})
+    ]
+    assert await begin(dispatch_sessionmaker, request, api_settings) is None  # never dispatched
+
+
+async def test_a_queued_requests_row_from_an_earlier_attempt_ends_with_it(
+    queued, owner_sessionmaker, api_sessionmaker, dispatch_sessionmaker, api_settings
+) -> None:
+    ctx, _, request = queued
+    lost = await starting(dispatch_sessionmaker, request, api_settings)
+    assert await dispatch.settle(dispatch_sessionmaker, lost, dispatch.Outcome("refused")) == "refused"
+    assert await row(owner_sessionmaker, request.id) == ("running", None)  # kept, hidden behind the request
+    assert await cancel(api_sessionmaker, ctx, request.id) == "cancelled"
+    assert await row(owner_sessionmaker, request.id) == ("cancelled", "user_cancelled")
+
+
+async def test_the_api_ends_no_row_but_a_cancelled_requests(
+    queued, owner_sessionmaker, api_sessionmaker, dispatch_sessionmaker, api_settings
+) -> None:
+    """The API holds no write on `runs`: `end_unstarted_run` ends a row only when its request is `cancelled`."""
+    ctx, _, request = queued
+    lost = await starting(dispatch_sessionmaker, request, api_settings)
+    assert await dispatch.settle(dispatch_sessionmaker, lost, dispatch.Outcome("started")) == "started"
+    async with api_sessionmaker() as s, s.begin():
+        await tenant_scope(s, ctx.tenant_id)
+        await s.execute(text("select end_unstarted_run(:i)"), {"i": request.id})
+    assert await row(owner_sessionmaker, request.id) == ("running", None)
+
+
+@pytest.mark.parametrize("outcome", ["refused", "throttled", "absent"])
+async def test_a_starting_requests_cancel_is_applied_when_it_doesnt_start(
+    queued, owner_sessionmaker, api_sessionmaker, dispatch_sessionmaker, api_settings, outcome
+) -> None:
+    ctx, _, request = queued
+    lost = await starting(dispatch_sessionmaker, request, api_settings)
+    assert await cancel(api_sessionmaker, ctx, request.id) == "requested"
+    assert (await state(owner_sessionmaker, request.id))["request"][0] == "starting"  # recorded, not yet applied
+    assert await dispatch.settle(dispatch_sessionmaker, lost, dispatch.Outcome(outcome)) == "cancelled"
+    after = await state(owner_sessionmaker, request.id)
+    assert after["request"][:2] == ("cancelled", "user_cancelled") and after["slot"] == 0
+    assert await row(owner_sessionmaker, request.id) == ("cancelled", "user_cancelled")
+    assert [a[0] for a in await audited(owner_sessionmaker, "run.cancel.requested")] == [str(request.id)]
+
+
+async def test_a_started_runs_cancel_is_sent_to_temporal_once(
+    queued, owner_sessionmaker, api_sessionmaker, dispatch_sessionmaker, api_settings, env
+) -> None:
+    ctx, _, request = queued
+    lost = await starting(dispatch_sessionmaker, request, api_settings)
+    assert await cancel(api_sessionmaker, ctx, request.id) == "requested"  # while starting
+    assert await dispatch.settle(dispatch_sessionmaker, lost, await dispatch.start(env.client, lost)) == "started"
+    assert await sending.send_cancels(dispatch_sessionmaker, env.client) == {"sent": 1}
+    assert await sending.send_cancels(dispatch_sessionmaker, env.client) == {}
+    handle = env.client.get_workflow_handle(run_workflow_id(str(ctx.tenant_id), str(request.id)))
+    kinds = [e.event_type async for e in handle.fetch_history_events()]
+    assert EventType.EVENT_TYPE_WORKFLOW_EXECUTION_CANCEL_REQUESTED in kinds
+
+
+async def test_a_running_runs_cancel_is_recorded_for_the_dispatcher(
+    queued, owner_sessionmaker, api_sessionmaker, dispatch_sessionmaker, api_settings, env
+) -> None:
+    ctx, _, request = queued
+    lost = await starting(dispatch_sessionmaker, request, api_settings)
+    assert await dispatch.settle(dispatch_sessionmaker, lost, await dispatch.start(env.client, lost)) == "started"
+    assert await cancel(api_sessionmaker, ctx, request.id) == "requested"
+    assert await cancel(api_sessionmaker, ctx, request.id) == "requested"  # again: one request, one audit entry
+    assert len(await audited(owner_sessionmaker, "run.cancel.requested")) == 1
+    assert await sending.send_cancels(dispatch_sessionmaker, env.client) == {"sent": 1}
+
+
+@pytest.mark.parametrize("ended", ["cancelled", "dead", "run_ended"])
+async def test_an_ended_request_has_nothing_to_cancel(
+    queued, owner_sessionmaker, api_sessionmaker, dispatch_sessionmaker, api_settings, ended
+) -> None:
+    ctx, _, request = queued
+    if ended == "cancelled":
+        await cancel(api_sessionmaker, ctx, request.id)
+    else:
+        lost = await starting(dispatch_sessionmaker, request, api_settings)
+        outcome = "collision" if ended == "dead" else "started"
+        await dispatch.settle(dispatch_sessionmaker, lost, dispatch.Outcome(outcome))
+        async with owner_sessionmaker() as s, s.begin():
+            await s.execute(text("update runs set status = 'succeeded', ended_at = now() where id = :i"),
+                            {"i": request.id})  # fmt: skip
+    assert await cancel(api_sessionmaker, ctx, request.id) == "ended"
+
+
+async def test_another_tenants_request_cant_be_cancelled(
+    queued, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings
+) -> None:
+    from tests.apps.test_admission import published
+
+    _, _, request = queued
+    other, _ = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings)
+    with pytest.raises(cancels.RequestNotFoundError):
+        await cancel(api_sessionmaker, other, request.id)
+    assert (await state(owner_sessionmaker, request.id))["request"][0] == "queued"
```

### Task 17: `dewpoint platform disable-production-runs`, under the gate's exclusive lock

**Commit:** `f54a086` (prototype `proto/2b2-v2`); the replay's tree was identical: yes.

**Create:** `backend/migrations/versions/0023_gate_disable.py`, `backend/src/dewpoint/apps/dispatcher/gate.py`, `backend/tests/apps/dispatcher/test_gate.py`

**Modify:** `backend/src/dewpoint/apps/cli/main.py`

**What it does:**

disable_production_runs() (0023, dewpoint_admin only, SECURITY DEFINER)
takes dewpoint:production-gate exclusively, so it waits for any
starting transaction holding it shared; once it commits no request
becomes starting. It's audited with whether the gate was on. The
command then waits for starts already made to settle, up to the
dispatcher's start deadline, and exits 3 with the ids of any still
unresolved; the gate stays off and the reconciler settles and audits
them. No role updates platform_settings itself: enabling stays 2b-4's.


- [ ] **Step 1: its tests alone, before its code.** Run: `uv run pytest -n 4 tests/apps/dispatcher/test_gate.py`. Replay result (exit 1), shortened:

```
==================================== ERRORS ====================================
_____________ ERROR collecting tests/apps/dispatcher/test_gate.py ______________
ImportError while importing test module '/private/tmp/claude-501/-Users-tmunzer-4-dev-mist-dewpoint/1e3145a1-199e-4b31-be1b-1e3bfd266be7/scratchpad/2b2-plan/replay/backend/tests/apps/dispatcher/test_gate.py'.
Hint: make sure your test modules/packages have valid Python names.
Traceback:
/opt/homebrew/Cellar/python@3.14/3.14.7/Frameworks/Python.framework/Versions/3.14/lib/python3.14/importlib/__init__.py:88: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
tests/apps/dispatcher/test_gate.py:18: in <module>
    from dewpoint.apps.dispatcher import dispatch, gate
E   ImportError: cannot import name 'gate' from 'dewpoint.apps.dispatcher' (/private/tmp/claude-501/-Users-tmunzer-4-dev-mist-dewpoint/1e3145a1-199e-4b31-be1b-1e3bfd266be7/scratchpad/2b2-plan/replay/backend/src/dewpoint/apps/dispatcher/__init__.py)
=========================== short test summary info ============================
ERROR tests/apps/dispatcher/test_gate.py - ImportError while importing test m...
1 error in 5.43s
```

- [ ] **Step 2: its code, then the same tests.** Replay result (exit 0), shortened:

```
.....                                                                    [100%]
5 passed in 11.48s
```

- [ ] **Step 3: commit.** `git cherry-pick --no-commit f54a086 && git commit -C f54a086`

The diff:

```diff
diff --git a/backend/migrations/versions/0023_gate_disable.py b/backend/migrations/versions/0023_gate_disable.py
new file mode 100644
index 0000000..970e02f
--- /dev/null
+++ b/backend/migrations/versions/0023_gate_disable.py
@@ -0,0 +1,37 @@
+# SPDX-License-Identifier: Apache-2.0
+"""disabling production runs (engine 2b spec §2.2, §2.4): the admin role turns the gate off, and only off
+
+`disable_production_runs()` takes `dewpoint:production-gate` exclusively, so it waits for every starting transaction
+holding it shared; once its caller commits, no request becomes `starting`. It returns whether the gate was on. No role
+updates `platform_settings` itself: enabling is 2b-4's audited command, with its readiness checks."""
+
+from alembic import op
+
+revision = "0023"
+down_revision = "0022"
+branch_labels = None
+depends_on = None
+
+DISABLE = """
+CREATE FUNCTION disable_production_runs() RETURNS boolean
+LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = public, pg_temp AS $$
+DECLARE was boolean;
+BEGIN
+  PERFORM pg_advisory_xact_lock(hashtextextended('dewpoint:production-gate', 0));
+  SELECT production_runs INTO was FROM platform_settings WHERE id = 1 FOR UPDATE;
+  IF NOT FOUND THEN
+    RAISE EXCEPTION 'the deployment''s environment is not recorded';
+  END IF;
+  UPDATE platform_settings SET production_runs = false WHERE id = 1;
+  RETURN was;
+END $$"""
+
+
+def upgrade() -> None:
+    op.execute(DISABLE)
+    op.execute("REVOKE ALL ON FUNCTION disable_production_runs() FROM PUBLIC")
+    op.execute("GRANT EXECUTE ON FUNCTION disable_production_runs() TO dewpoint_admin")
+
+
+def downgrade() -> None:
+    op.execute("DROP FUNCTION disable_production_runs()")
diff --git a/backend/src/dewpoint/apps/cli/main.py b/backend/src/dewpoint/apps/cli/main.py
index 0f0f97d..6ef0e97 100644
--- a/backend/src/dewpoint/apps/cli/main.py
+++ b/backend/src/dewpoint/apps/cli/main.py
@@ -17,6 +17,8 @@ from sqlalchemy.ext.asyncio import AsyncSession
 from temporalio.client import Client
 
 from dewpoint.apps.codec import KeyringKeys, data_converter
+from dewpoint.apps.dispatcher.dispatch import START_DEADLINE
+from dewpoint.apps.dispatcher.gate import disable_and_wait
 from dewpoint.apps.environment import verify_environment
 from dewpoint.apps.plugin_loader import PluginLoadError, installed_plugins, prepare
 from dewpoint.apps.runs import NotAdmissibleError, StartRefusedError, StartUncertainError, start_run
@@ -429,6 +431,32 @@ def platform_init_environment(
     typer.echo(f"this deployment is {env}, with the Temporal namespace `{ns}`")
 
 
+@platform_cli.command("disable-production-runs")
+def platform_disable_production_runs(
+    wait: float = typer.Option(
+        START_DEADLINE.total_seconds(), "--wait", help="seconds to wait for starts already made to settle"
+    ),
+) -> None:
+    """Turn production runs off (engine 2b spec §2.4), audited: queued requests wait, started runs continue. Then wait
+    for the starts already made to settle; exit 3, with their ids, while any is unresolved (the gate stays off). Run
+    as dewpoint_admin. Turning them on is 2b-4's, with its readiness checks."""
+    settings = get_settings()
+
+    async def _go() -> list[uuid.UUID]:
+        engine = make_engine(settings.database_url)
+        try:
+            return await disable_and_wait(make_sessionmaker(engine), deadline=timedelta(seconds=wait))
+        finally:
+            await engine.dispose()
+
+    left = asyncio.run(_go())
+    if left:
+        many = "start is" if len(left) == 1 else "starts are"
+        typer.echo(f"production runs are off; {len(left)} {many} still unresolved: {', '.join(map(str, left))}")
+        raise typer.Exit(3)
+    typer.echo("production runs are off; no start is left unresolved")
+
+
 @deployment_cli.command("set-current")
 def deployment_set_current(
     build: str | None = typer.Option(None, "--build-id", help="the build new runs start on (default: this one)"),
diff --git a/backend/src/dewpoint/apps/dispatcher/gate.py b/backend/src/dewpoint/apps/dispatcher/gate.py
new file mode 100644
index 0000000..ba20457
--- /dev/null
+++ b/backend/src/dewpoint/apps/dispatcher/gate.py
@@ -0,0 +1,49 @@
+# SPDX-License-Identifier: Apache-2.0
+"""Turning production runs off (engine 2b spec §2.2, §2.4), as `dewpoint_admin`: the gate goes off at once, audited,
+and the command then waits for the starts already made to settle (started, or back in the queue), up to the
+dispatcher's start deadline. A start still unsettled is reported unresolved: the gate stays off, the reconciler
+settles it and audits that (§7.6), and the disable is never reported as fully settled meanwhile."""
+
+import asyncio
+import uuid
+from datetime import timedelta
+
+from sqlalchemy import select, text
+from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
+
+from dewpoint.apps.dispatcher.dispatch import START_DEADLINE
+from dewpoint.core.audit import service as audit
+from dewpoint.core.models.requests import RunRequest
+
+POLL_S = 0.25  # between looks at what's still starting
+
+
+async def disable_production_runs(s: AsyncSession, *, actor_id: uuid.UUID | None) -> bool:
+    """The gate off, in the caller's transaction, under the gate's exclusive lock, audited. Whether it was on."""
+    was = bool((await s.execute(text("select disable_production_runs()"))).scalar_one())
+    await audit.record(s, tenant_id=None, actor_id=actor_id, action="platform.production_runs.disable",
+                       target_type="platform", target_id="production_runs", details={"was_on": was})  # fmt: skip
+    return was
+
+
+async def starting(s: AsyncSession) -> list[uuid.UUID]:
+    """Every tenant's requests still `starting` (the admin's platform-wide read, 0019)."""
+    found = await s.execute(select(RunRequest.id).where(RunRequest.status == "starting").order_by(RunRequest.id))
+    return list(found.scalars())
+
+
+async def disable_and_wait(
+    sessionmaker: async_sessionmaker[AsyncSession], *, actor_id: uuid.UUID | None = None,
+    deadline: timedelta = START_DEADLINE,
+) -> list[uuid.UUID]:  # fmt: skip
+    """The gate off, then the starts still unsettled once `deadline` has passed: none, when every one settled."""
+    async with sessionmaker() as s, s.begin():
+        await disable_production_runs(s, actor_id=actor_id)
+    loop = asyncio.get_running_loop()
+    until = loop.time() + deadline.total_seconds()
+    while True:
+        async with sessionmaker() as s:
+            left = await starting(s)
+        if not left or loop.time() >= until:
+            return left
+        await asyncio.sleep(POLL_S)
diff --git a/backend/tests/apps/dispatcher/test_gate.py b/backend/tests/apps/dispatcher/test_gate.py
new file mode 100644
index 0000000..d34ff1d
--- /dev/null
+++ b/backend/tests/apps/dispatcher/test_gate.py
@@ -0,0 +1,131 @@
+# SPDX-License-Identifier: Apache-2.0
+"""The gate-off race (engine 2b spec §2.4): disabling takes `dewpoint:production-gate` exclusively, so it waits for
+any starting transaction holding it shared, and once it commits no request becomes `starting`. The command then waits
+for the starts already made to settle, up to the dispatcher's start deadline; one still unsettled is reported
+unresolved, and the gate stays off. Disabling is audited; the admin role can disable and nothing else."""
+
+import asyncio
+import base64
+from datetime import timedelta
+from typing import Any
+
+import pytest
+from sqlalchemy import text
+from sqlalchemy.exc import DBAPIError
+from typer.testing import CliRunner
+
+from dewpoint.apps.cli import main as cli
+from dewpoint.apps.dispatcher import dispatch, gate
+from dewpoint.core.config import get_settings
+from tests.apps.dispatcher.support import begin, state
+from tests.apps.test_lifecycle_races import until_someone_waits_for_a_lock
+from tests.conftest import _url_for
+
+
+@pytest.fixture
+async def production_on(development_deployment, owner_sessionmaker) -> None:
+    """The recorded deployment made production, its gate on: the dispatcher's every start depends on it."""
+    async with owner_sessionmaker() as s, s.begin():
+        await s.execute(text("alter table platform_settings disable trigger user"))
+        await s.execute(text("update platform_settings set environment = 'production', production_runs = true"))
+        await s.execute(text("alter table platform_settings enable trigger user"))
+
+
+async def gate_on(owner: Any) -> bool:
+    async with owner() as s:
+        return bool((await s.execute(text("select production_runs from platform_settings"))).scalar())
+
+
+async def disable(admin: Any) -> bool:
+    async with admin() as s, s.begin():
+        return await gate.disable_production_runs(s, actor_id=None)
+
+
+@pytest.mark.usefixtures("production_on")
+async def test_disabling_waits_for_a_starting_transaction_and_nothing_starts_after(
+    queued, owner_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings
+) -> None:
+    _, _, request = queued
+    async with dispatch_sessionmaker() as held, held.begin():  # a starting transaction, under the shared lock
+        await held.execute(
+            text("select pg_advisory_xact_lock_shared(hashtextextended(:k, 0))"), {"k": dispatch.GATE_LOCK}
+        )
+        disabling = asyncio.create_task(disable(admin_sessionmaker))
+        await until_someone_waits_for_a_lock(owner_sessionmaker)
+        assert not disabling.done() and await gate_on(owner_sessionmaker)
+    assert await disabling is True  # it was on
+    assert not await gate_on(owner_sessionmaker)
+    assert await begin(dispatch_sessionmaker, request, api_settings) == dispatch.Waiting("gate_off")
+    async with owner_sessionmaker() as s:
+        details = (await s.execute(text(
+            "select details from audit_log where action = 'platform.production_runs.disable'"
+        ))).scalar_one()  # fmt: skip
+    assert details == {"was_on": True}
+
+
+@pytest.mark.usefixtures("production_on")
+async def test_a_start_that_doesnt_settle_in_time_is_reported_unresolved(
+    queued, owner_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings
+) -> None:
+    _, _, request = queued
+    assert isinstance(await begin(dispatch_sessionmaker, request, api_settings), dispatch.Starting)
+    left = await gate.disable_and_wait(admin_sessionmaker, deadline=timedelta(milliseconds=300))
+    assert left == [request.id]
+    assert not await gate_on(owner_sessionmaker)  # off either way
+
+
+@pytest.mark.usefixtures("production_on")
+async def test_disabling_waits_for_the_starts_already_made_to_settle(
+    queued, owner_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings
+) -> None:
+    _, _, request = queued
+    starting = await begin(dispatch_sessionmaker, request, api_settings)
+    assert isinstance(starting, dispatch.Starting)
+
+    async def refused_soon() -> None:
+        await asyncio.sleep(0.3)
+        await dispatch.settle(dispatch_sessionmaker, starting, dispatch.Outcome("refused"))
+
+    left, _ = await asyncio.gather(
+        gate.disable_and_wait(admin_sessionmaker, deadline=timedelta(seconds=5)), refused_soon()
+    )
+    assert left == []
+    assert (await state(owner_sessionmaker, request.id))["request"][0] == "queued"
+
+
+@pytest.mark.usefixtures("production_on")
+async def test_the_admin_role_can_disable_the_gate_and_nothing_else(admin_sessionmaker) -> None:
+    with pytest.raises(DBAPIError, match="permission denied"):
+        async with admin_sessionmaker() as s, s.begin():
+            await s.execute(text("update platform_settings set production_runs = true"))
+
+
+@pytest.fixture
+def admin_cli(monkeypatch: pytest.MonkeyPatch, pg_url: str, admin_sessionmaker: Any) -> Any:
+    """The CLI, run as `dewpoint_admin` (as the operations docs say), in a thread: it runs its own event loop."""
+    monkeypatch.setenv("DEWPOINT_DATABASE_URL", _url_for(pg_url, "dewpoint_admin"))
+    monkeypatch.setenv("DEWPOINT_KEK_B64", base64.b64encode(b"k" * 32).decode())
+    monkeypatch.setenv("DEWPOINT_PUBLIC_ORIGIN", "https://dewpoint.test")
+    get_settings.cache_clear()
+
+    async def invoke(*args: str) -> Any:
+        return await asyncio.to_thread(CliRunner().invoke, cli.app, list(args))
+
+    yield invoke
+    get_settings.cache_clear()
+
+
+@pytest.mark.usefixtures("production_on")
+async def test_the_command_says_whether_a_start_is_left_unresolved(
+    queued, admin_cli, dispatch_sessionmaker, api_settings
+) -> None:
+    _, _, request = queued
+    starting = await begin(dispatch_sessionmaker, request, api_settings)
+    assert isinstance(starting, dispatch.Starting)
+    unresolved = await admin_cli("platform", "disable-production-runs", "--wait", "0")
+    assert (unresolved.exit_code, unresolved.output) == (
+        3, f"production runs are off; 1 start is still unresolved: {request.id}\n",
+    )  # fmt: skip
+    await dispatch.settle(dispatch_sessionmaker, starting, dispatch.Outcome("refused"))
+    settled = await admin_cli("platform", "disable-production-runs", "--wait", "0")
+    assert (settled.exit_code, settled.output) == (0, "production runs are off; no start is left unresolved\n")
```

### Task 18: An uncertain start is found by when it became starting, never by its slot (the owner's milestone-3 review)

**Commit:** `48ceec4` (prototype `proto/2b2-v2`); the replay's tree was identical: yes.

**Modify:** `backend/migrations/versions/0021_reconciler.py`, `backend/src/dewpoint/apps/dispatcher/dispatch.py`, `backend/src/dewpoint/apps/dispatcher/reconcile.py`, `backend/src/dewpoint/core/models/requests.py`, `backend/tests/apps/dispatcher/test_reconcile.py`, `backend/tests/apps/dispatcher/test_reconcile_runs.py`, `backend/tests/apps/test_admission_retirement.py`, `backend/tests/core/requests/test_schema.py`

**What it does:**

A start accepted whose reply was lost can finish quickly: its end write
releases the slot while the request is still starting, and the
reconciler, which found uncertain starts through their slots, never saw
it again. run_requests.starting_at (0021, with a check that a starting
request has one, and a partial index) is set in the starting
transaction; the grace period and the unresolved alert's age run from
it.

A started run whose history Temporal no longer has is left unresolved
with an error-level alert, and so is a leaked slot whose history is
gone: no outcome is invented and no slot released from missing history
alone (the owner's ruling); an operator recovers it.


- [ ] **Step 1: its tests alone, before its code.** Run: `uv run pytest -n 4 tests/apps/dispatcher/test_reconcile.py tests/apps/dispatcher/test_reconcile_runs.py tests/apps/test_admission_retirement.py tests/core/requests/test_schema.py`. Replay result (exit 1), shortened:

```
FAILED tests/apps/test_admission_retirement.py::test_the_admin_cancels_only_a_queued_request_even_within_a_tenant_scope[starting]
FAILED tests/core/requests/test_schema.py::test_a_request_with_its_envelope_is_seen_only_within_its_tenant
FAILED tests/apps/test_admission_retirement.py::test_the_admin_cancels_only_a_queued_request_even_within_a_tenant_scope[started]
FAILED tests/core/requests/test_schema.py::test_only_a_refused_request_has_no_envelope
FAILED tests/core/requests/test_schema.py::test_a_request_reaches_only_an_envelope_it_owns
FAILED tests/apps/dispatcher/test_reconcile.py::test_a_lost_reply_whose_run_already_ended_is_still_reconciled
FAILED tests/core/requests/test_schema.py::test_an_envelope_outlives_no_request_and_stands_alone_per_owner
FAILED tests/apps/dispatcher/test_reconcile.py::test_a_leaked_slot_whose_history_is_gone_is_kept_with_an_alert
FAILED tests/core/requests/test_schema.py::test_an_idempotency_key_is_one_request_per_tenant
FAILED tests/apps/dispatcher/test_reconcile.py::test_a_starting_request_always_says_when_it_became_starting
FAILED tests/core/requests/test_schema.py::test_the_dispatcher_picks_from_every_tenant_seeing_only_what_it_needs
FAILED tests/core/requests/test_schema.py::test_the_api_updates_only_what_a_cancel_changes
FAILED tests/core/requests/test_schema.py::test_a_request_reaches_no_envelope_of_another_tenant
21 failed, 29 passed in 14.81s
```

- [ ] **Step 2: its code, then the same tests.** Replay result (exit 0), shortened:

```
..................................................                       [100%]
50 passed in 15.07s
```

- [ ] **Step 3: commit.** `git cherry-pick --no-commit 48ceec4 && git commit -C 48ceec4`

The diff:

```diff
diff --git a/backend/migrations/versions/0021_reconciler.py b/backend/migrations/versions/0021_reconciler.py
index 99c5839..2d360bc 100644
--- a/backend/migrations/versions/0021_reconciler.py
+++ b/backend/migrations/versions/0021_reconciler.py
@@ -1,8 +1,10 @@
 # SPDX-License-Identifier: Apache-2.0
 """the reconciler's view across tenants and its round robin (engine 2b spec §7.6)
 
-`run_requests.checked_at`: when the reconciler last asked Temporal about a request, so each one is asked at most once
-per recheck interval. `reconcile_candidates()`: like `dispatch_candidates()`, ids and a kind only, never a request's
+`run_requests.starting_at`: when the request last became `starting`, kept apart from its slot: a start accepted whose
+reply was lost can finish, and its end write release the slot, while the request is still `starting` (the owner's M3
+checkpoint). `run_requests.checked_at`: when the reconciler last asked Temporal about a request, so each one is asked at
+most once per recheck interval. `reconcile_candidates()`: like `dispatch_candidates()`, ids and a kind only, never a request's
 contents: uncertain starts past their grace period, started runs whose rows are still `running`, and slots held by
 runs whose rows have ended."""
 
@@ -19,9 +21,9 @@ CREATE FUNCTION reconcile_candidates(grace interval, recheck interval, max_rows
 RETURNS TABLE (tenant_id uuid, request_id uuid, kind text)
 LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
   SELECT c.tenant_id, c.request_id, c.kind FROM (
-    SELECT r.tenant_id, r.id AS request_id, 'starting'::text AS kind, s.reserved_at AS since
-    FROM run_requests r JOIN run_slots s ON s.run_id = r.id
-    WHERE r.status = 'starting' AND s.reserved_at < statement_timestamp() - grace
+    SELECT r.tenant_id, r.id AS request_id, 'starting'::text AS kind, r.starting_at AS since
+    FROM run_requests r
+    WHERE r.status = 'starting' AND r.starting_at < statement_timestamp() - grace
     UNION ALL
     SELECT r.tenant_id, r.id, 'open', u.queued_at
     FROM run_requests r JOIN runs u ON u.id = r.id
@@ -38,6 +40,17 @@ $$"""
 
 
 def upgrade() -> None:
+    op.add_column("run_requests", sa.Column("starting_at", sa.DateTime(timezone=True)))
+    op.execute(
+        "UPDATE run_requests r SET starting_at = coalesce("
+        "(SELECT s.reserved_at FROM run_slots s WHERE s.run_id = r.id), now()) WHERE r.status = 'starting'"
+    )
+    op.create_check_constraint(
+        "run_requests_starting_since", "run_requests", "status <> 'starting' OR starting_at IS NOT NULL"
+    )
+    op.create_index(
+        "run_requests_starting", "run_requests", ["starting_at"], postgresql_where=sa.text("status = 'starting'")
+    )
     op.add_column("run_requests", sa.Column("checked_at", sa.DateTime(timezone=True)))
     op.execute(CANDIDATES)
     op.execute("REVOKE ALL ON FUNCTION reconcile_candidates(interval, interval, integer) FROM PUBLIC")
@@ -47,3 +60,6 @@ def upgrade() -> None:
 def downgrade() -> None:
     op.execute("DROP FUNCTION reconcile_candidates(interval, interval, integer)")
     op.drop_column("run_requests", "checked_at")
+    op.drop_index("run_requests_starting", table_name="run_requests")
+    op.drop_constraint("run_requests_starting_since", "run_requests", type_="check")
+    op.drop_column("run_requests", "starting_at")
diff --git a/backend/src/dewpoint/apps/dispatcher/dispatch.py b/backend/src/dewpoint/apps/dispatcher/dispatch.py
index 2250c7e..4e51518 100644
--- a/backend/src/dewpoint/apps/dispatcher/dispatch.py
+++ b/backend/src/dewpoint/apps/dispatcher/dispatch.py
@@ -288,6 +288,7 @@ async def _begin(
         mode=request.mode, started_by=request.actor_id, queued_at=request.queued_at,
     )  # fmt: skip
     request.status = "starting"
+    request.starting_at = func.statement_timestamp()  # the reconciler's grace runs from here, slot or not (§7.6)
     await s.flush()
     return Starting(request.id, tenant_id, start)
 
diff --git a/backend/src/dewpoint/apps/dispatcher/reconcile.py b/backend/src/dewpoint/apps/dispatcher/reconcile.py
index 353e0f0..c9c0392 100644
--- a/backend/src/dewpoint/apps/dispatcher/reconcile.py
+++ b/backend/src/dewpoint/apps/dispatcher/reconcile.py
@@ -4,7 +4,8 @@ uncertain, records the end of runs whose workflow closed without their end write
 
 It reads across tenants only through `reconcile_candidates()` (ids and a kind), then works tenant-scoped, one
 request per transaction, with no transaction open across a call to Temporal. It asks about each request at most once
-per `RECHECK`. A failure it can't classify is logged and isolated, as the dispatcher's are."""
+per `RECHECK`. An uncertain start is found by when it became `starting`, never by its slot, which a quick run's end
+write may already have released. A failure it can't classify is logged and isolated, as the dispatcher's are."""
 
 import uuid
 from collections import Counter
@@ -25,7 +26,7 @@ from dewpoint.core.claims.cipher import ClaimCipher
 from dewpoint.core.config import Settings
 from dewpoint.core.crypto.keys import KeySource
 from dewpoint.core.db import tenant_scope
-from dewpoint.core.models.requests import RunRequest, RunSlot
+from dewpoint.core.models.requests import RunRequest
 from dewpoint.core.runs import service as runs
 from dewpoint.engine.runtime.activities import RunResult
 from dewpoint.engine.runtime.execution import CANCELLED, INTERNAL_ERROR, TERMINATED
@@ -180,13 +181,8 @@ async def _unresolved(
     """Left `starting`, its slot held; an error once it has been so for ALERT_AFTER."""
     async with sessionmaker() as s, s.begin():
         await tenant_scope(s, tenant_id)
-        age = (
-            await s.execute(
-                select(text("statement_timestamp() - reserved_at"))
-                .select_from(RunSlot)
-                .where(RunSlot.run_id == request_id)
-            )
-        ).scalar()
+        since = select(text("statement_timestamp() - starting_at")).select_from(RunRequest)
+        age = (await s.execute(since.where(RunRequest.id == request_id))).scalar()  # its slot may be gone already
         await _checked(s, request_id)
     if isinstance(age, timedelta) and age >= ALERT_AFTER:
         log.error("start_unresolved", request_id=str(request_id), detail=detail, age_s=int(age.total_seconds()))
@@ -215,7 +211,7 @@ async def _open(
     try:
         described = await handle.describe()  # no run id: the latest execution, past every continue-as-new
     except Exception as e:
-        log.warning("reconcile_unanswered", run_id=str(run_id), error=type(e).__name__)
+        await _missing_or_unanswered(client, e, run_id, "run_history_missing")
         await _checked_alone(sessionmaker, tenant_id, run_id)
         return "unresolved"
     if described.status is None or described.status in LIVE:
@@ -251,24 +247,18 @@ async def _ended(handle: Any, status: WorkflowExecutionStatus, run_id: uuid.UUID
 async def _slot(
     sessionmaker: async_sessionmaker[AsyncSession], client: Client, tenant_id: uuid.UUID, run_id: uuid.UUID
 ) -> str:
-    """A slot whose run's row has ended: released only once the logical run's latest execution is closed, or absent
-    from a namespace that answers."""
+    """A slot whose run's row has ended: released only once the logical run's latest execution is closed. Its history
+    gone is an alert, never a release (the owner's ruling)."""
     try:
         described = await client.get_workflow_handle(run_workflow_id(str(tenant_id), str(run_id))).describe()
-    except RPCError as e:
-        if not (e.status == RPCStatusCode.NOT_FOUND and await namespace_answers(client)):
-            log.warning("reconcile_unanswered", run_id=str(run_id), error=e.status.name)
-            await _checked_alone(sessionmaker, tenant_id, run_id)
-            return "unresolved"
     except Exception as e:
-        log.warning("reconcile_unanswered", run_id=str(run_id), error=type(e).__name__)
+        await _missing_or_unanswered(client, e, run_id, "slot_history_missing")
         await _checked_alone(sessionmaker, tenant_id, run_id)
         return "unresolved"
-    else:
-        if described.status is None or described.status in LIVE:
-            log.warning("slot_execution_live", run_id=str(run_id))  # its row ended, its execution didn't
-            await _checked_alone(sessionmaker, tenant_id, run_id)
-            return "live"
+    if described.status is None or described.status in LIVE:
+        log.warning("slot_execution_live", run_id=str(run_id))  # its row ended, its execution didn't
+        await _checked_alone(sessionmaker, tenant_id, run_id)
+        return "live"
     async with sessionmaker() as s, s.begin():
         await tenant_scope(s, tenant_id)
         await dispatch.release(s, run_id)
@@ -276,6 +266,17 @@ async def _slot(
     return "released"
 
 
+async def _missing_or_unanswered(client: Client, e: Exception, run_id: uuid.UUID, missing: str) -> None:
+    """A started run's history Temporal no longer has (NOT_FOUND, from a namespace that answers) is an alert: no outcome
+    is invented and no slot released from missing history alone; an operator recovers it (the owner's ruling). Any other
+    failure: unanswered this time."""
+    if isinstance(e, RPCError) and e.status == RPCStatusCode.NOT_FOUND and await namespace_answers(client):
+        log.error(missing, run_id=str(run_id))
+        return
+    error = e.status.name if isinstance(e, RPCError) else type(e).__name__
+    log.warning("reconcile_unanswered", run_id=str(run_id), error=error)
+
+
 async def _checked(s: AsyncSession, request_id: uuid.UUID) -> None:
     await s.execute(text("update run_requests set checked_at = statement_timestamp() where id = :i"), {"i": request_id})
 
diff --git a/backend/src/dewpoint/core/models/requests.py b/backend/src/dewpoint/core/models/requests.py
index 14903c1..5f5913c 100644
--- a/backend/src/dewpoint/core/models/requests.py
+++ b/backend/src/dewpoint/core/models/requests.py
@@ -41,6 +41,7 @@ class RunRequest(Base):
     ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
     cancel_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
     cancel_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
+    starting_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # when it last became starting
     checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # the reconciler's last look
     envelope_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
 
diff --git a/backend/tests/apps/dispatcher/test_reconcile.py b/backend/tests/apps/dispatcher/test_reconcile.py
index e4ab42d..d0a22e8 100644
--- a/backend/tests/apps/dispatcher/test_reconcile.py
+++ b/backend/tests/apps/dispatcher/test_reconcile.py
@@ -2,24 +2,30 @@
 """The reconciler (engine 2b spec §7.6): one leader among the dispatchers settles what a start left uncertain. An
 execution it finds is verified as a dispatcher verifies one, and its request is `started`; a request goes back to the
 queue, no attempt counted, only after a trustworthy absence (a describe after the grace period, from a namespace that
-answers); any error leaves it `starting`, its slot held. A slot is released only once its run's latest execution is
-closed. Every request it settles is audited (§2.4)."""
+answers); any error leaves it `starting`, its slot held. Its grace runs from when it became `starting`, slot or not. A
+slot is released only once its run's latest execution is closed, never because its history is gone. Every request it
+settles is audited (§2.4)."""
 
+import asyncio
 import uuid
 from datetime import timedelta
 from typing import Any
 
 import pytest
+import structlog
 from sqlalchemy import text
+from sqlalchemy.exc import IntegrityError
 from temporalio.service import RPCStatusCode
 
 from dewpoint.apps.dispatcher import dispatch, reconcile
+from dewpoint.apps.worker.store import DbRunStore
 from dewpoint.engine.runtime.activities import ENGINE_QUEUE
 from dewpoint.engine.runtime.ids import run_workflow_id
 from dewpoint.engine.runtime.workflow import RunGraph
 from tests.apps.dispatcher.support import begin, state
 from tests.apps.test_admission import KEYS
 from tests.apps.test_runs import rpc
+from tests.apps.worker.harness import workers
 
 pytestmark = pytest.mark.usefixtures("development_deployment")
 
@@ -31,10 +37,10 @@ async def starting(dispatch_sessionmaker: Any, request: Any, settings: Any) -> d
 
 
 async def aged(owner: Any, request_id: uuid.UUID, by: timedelta = reconcile.GRACE + timedelta(seconds=5)) -> None:
-    """The start was made `by` ago: its slot was reserved then."""
+    """The request became `starting` `by` ago."""
     async with owner() as s, s.begin():
         await s.execute(
-            text("update run_slots set reserved_at = reserved_at - cast(:by as interval) where run_id = :i"),
+            text("update run_requests set starting_at = starting_at - cast(:by as interval) where id = :i"),
             {"by": by, "i": request_id},
         )
 
@@ -77,7 +83,7 @@ class DescribeFails:
     def __init__(self, error: BaseException, namespace_error: BaseException | None = None) -> None:
         self.error, self.workflow_service = error, Service(namespace_error)
 
-    def get_workflow_handle(self, _: str) -> Handle:
+    def get_workflow_handle(self, _: str, **__: Any) -> Handle:
         return Handle(self.error)
 
 
@@ -183,3 +189,53 @@ async def test_a_leaked_slot_is_released_only_once_its_runs_execution_is_closed(
         await s.execute(text("update run_requests set checked_at = null where id = :i"), {"i": request.id})
     assert await once(dispatch_sessionmaker, env.client, api_settings) == {"released": 1}
     assert (await state(owner_sessionmaker, request.id))["slot"] == 0
+
+
+async def test_a_lost_reply_whose_run_already_ended_is_still_reconciled(
+    queued, owner_sessionmaker, dispatch_sessionmaker, worker_sessionmaker, api_settings, env, monkeypatch
+) -> None:
+    """The owner's M3 checkpoint: a start accepted, its reply lost, and the run so quick that its end write released
+    the slot while the request was still `starting`. The reconciler finds it by when it entered `starting`, never by a
+    slot it no longer has."""
+    ctx, _, request = queued
+    monkeypatch.setattr(reconcile, "GRACE", timedelta(0))  # its grace period over at once
+    async with workers(env.client, DbRunStore(worker_sessionmaker, KEYS)):
+        lost = await starting(dispatch_sessionmaker, request, api_settings)
+        assert (await dispatch.start(env.client, lost)).kind == "started"  # accepted; its reply never settled
+        handle = env.client.get_workflow_handle_for(RunGraph.run, run_workflow_id(str(ctx.tenant_id), str(request.id)))
+        assert (await asyncio.wait_for(handle.result(), 30)).status == "succeeded"
+    before = await state(owner_sessionmaker, request.id)
+    assert (before["request"][0], before["slot"], before["run"][0]) == ("starting", 0, "succeeded")
+    assert await once(dispatch_sessionmaker, env.client, api_settings) == {"started": 1}
+    after = await state(owner_sessionmaker, request.id)
+    assert (after["request"][0], after["slot"], after["run"][0]) == ("started", 0, "succeeded")
+    assert after["run"][1] is not None  # its started_at, from the execution's own start
+    assert await once(dispatch_sessionmaker, env.client, api_settings) == {}  # nothing left to settle
+
+
+async def test_a_leaked_slot_whose_history_is_gone_is_kept_with_an_alert(
+    queued, owner_sessionmaker, dispatch_sessionmaker, api_settings
+) -> None:
+    """The owner's ruling: a slot is never released solely because Temporal no longer has the run's history; it's left
+    unresolved, with an alert, for an operator."""
+    _, _, request = queued
+    found = await starting(dispatch_sessionmaker, request, api_settings)
+    assert await dispatch.settle(dispatch_sessionmaker, found, dispatch.Outcome("started")) == "started"
+    async with owner_sessionmaker() as s, s.begin():
+        await s.execute(text("update runs set status = 'failed', ended_at = now() where id = :i"), {"i": request.id})
+    with structlog.testing.capture_logs() as seen:
+        assert await once(dispatch_sessionmaker, DescribeFails(rpc(RPCStatusCode.NOT_FOUND)), api_settings) == {
+            "unresolved": 1
+        }
+    assert (await state(owner_sessionmaker, request.id))["slot"] == 1
+    assert {"event": "slot_history_missing", "log_level": "error"}.items() <= next(
+        e for e in seen if e["event"] == "slot_history_missing"
+    ).items()
+
+
+async def test_a_starting_request_always_says_when_it_became_starting(queued, owner_sessionmaker) -> None:
+    """The reconciler's grace depends on it: the schema refuses a `starting` request without it."""
+    _, _, request = queued
+    with pytest.raises(IntegrityError, match="run_requests_starting_since"):
+        async with owner_sessionmaker() as s, s.begin():
+            await s.execute(text("update run_requests set status = 'starting' where id = :i"), {"i": request.id})
diff --git a/backend/tests/apps/dispatcher/test_reconcile_runs.py b/backend/tests/apps/dispatcher/test_reconcile_runs.py
index 1f41038..df6ecd1 100644
--- a/backend/tests/apps/dispatcher/test_reconcile_runs.py
+++ b/backend/tests/apps/dispatcher/test_reconcile_runs.py
@@ -9,8 +9,10 @@ from types import SimpleNamespace
 from typing import Any
 
 import pytest
+import structlog
 from sqlalchemy import text
 from temporalio.client import WorkflowExecutionStatus
+from temporalio.service import RPCStatusCode
 
 from dewpoint.apps.dispatcher import dispatch, reconcile
 from dewpoint.apps.worker.store import DbRunStore
@@ -18,7 +20,9 @@ from dewpoint.engine.runtime.activities import ProjectInput
 from dewpoint.engine.runtime.ids import run_workflow_id
 from dewpoint.engine.runtime.workflow import RunGraph
 from tests.apps.dispatcher.support import BUILD, begin, state
+from tests.apps.dispatcher.test_reconcile import DescribeFails
 from tests.apps.test_admission import KEYS
+from tests.apps.test_runs import rpc
 from tests.apps.worker.harness import workers
 
 pytestmark = pytest.mark.usefixtures("development_deployment")
@@ -126,3 +130,18 @@ async def test_a_live_logical_run_is_left_running(
     }
     assert await ended(owner_sessionmaker, request.id) == ("running", None)
     assert (await state(owner_sessionmaker, request.id))["slot"] == 1
+
+
+async def test_a_started_run_whose_history_is_gone_is_left_unresolved_with_an_alert(
+    queued, owner_sessionmaker, dispatch_sessionmaker, api_settings
+) -> None:
+    """The owner's ruling: no outcome is invented and no slot released from missing history alone; an operator
+    recovers it."""
+    _, _, request = queued
+    await started(dispatch_sessionmaker, request, api_settings)
+    gone = DescribeFails(rpc(RPCStatusCode.NOT_FOUND))
+    with structlog.testing.capture_logs() as seen:
+        assert await reconcile.reconcile_once(dispatch_sessionmaker, gone, KEYS, api_settings) == {"unresolved": 1}
+    assert await ended(owner_sessionmaker, request.id) == ("running", None)
+    assert (await state(owner_sessionmaker, request.id))["slot"] == 1
+    assert any(e["event"] == "run_history_missing" and e["log_level"] == "error" for e in seen)
diff --git a/backend/tests/apps/test_admission_retirement.py b/backend/tests/apps/test_admission_retirement.py
index 98cfe21..bbba7d5 100644
--- a/backend/tests/apps/test_admission_retirement.py
+++ b/backend/tests/apps/test_admission_retirement.py
@@ -73,7 +73,9 @@ async def test_a_starting_request_blocks_normal_retirement_and_survives_a_forced
                                     api_settings)  # fmt: skip
     await update(api_sessionmaker, ctx, wf, enabled=False)  # only the request references the entry
     async with owner_sessionmaker() as s, s.begin():
-        await s.execute(text("update run_requests set status = 'starting' where id = :i"), {"i": request.id})
+        await s.execute(
+            text("update run_requests set status = 'starting', starting_at = now() where id = :i"), {"i": request.id}
+        )
     with pytest.raises(lifecycle.ReferencedError):
         async with admin_sessionmaker() as s, s.begin():
             await lifecycle.retire(s, ECHO)
diff --git a/backend/tests/core/requests/test_schema.py b/backend/tests/core/requests/test_schema.py
index 1039023..243a796 100644
--- a/backend/tests/core/requests/test_schema.py
+++ b/backend/tests/core/requests/test_schema.py
@@ -39,9 +39,10 @@ def request(tenant: uuid.UUID, wf: uuid.UUID, version: uuid.UUID | None, **extra
 
 INSERT_REQUEST = text(
     "insert into run_requests (id, tenant_id, workflow_id, workflow_version_id, source, mode, idempotency_key, digest, "
-    "digest_key_version, status, envelope_id, ended_at) values (:id, :tenant_id, :workflow_id, :workflow_version_id, "
-    ":source, :mode, :idempotency_key, :digest, :digest_key_version, cast(:status as varchar), :envelope_id, "
-    "case when cast(:status as varchar) in ('cancelled', 'refused', 'dead') then now() end)"
+    "digest_key_version, status, envelope_id, ended_at, starting_at) values (:id, :tenant_id, :workflow_id, "
+    ":workflow_version_id, :source, :mode, :idempotency_key, :digest, :digest_key_version, cast(:status as varchar), "
+    ":envelope_id, case when cast(:status as varchar) in ('cancelled', 'refused', 'dead') then now() end, "
+    "case when cast(:status as varchar) = 'starting' then now() end)"
 )
```

### Task 19: A starting request whose run already ended is never queued again on a missing history (the owner's milestone-3 review)

**Commit:** `a3e1ec1` (prototype `proto/2b2-v2`); the replay's tree was identical: yes.

**Modify:** `backend/src/dewpoint/apps/dispatcher/dispatch.py`, `backend/src/dewpoint/apps/dispatcher/reconcile.py`, `backend/tests/apps/dispatcher/test_reconcile.py`

**What it does:**

A NOT_FOUND from a namespace that answers puts an uncertain start back
in the queue only while its pre-created run row hasn't ended. A row that
records an end means a start did happen and only its history is gone:
the request is left starting, unresolved, with an error-level alert for
an operator. The check runs in settle's transaction, under the
request's lock.


- [ ] **Step 1: its tests alone, before its code.** Run: `uv run pytest -n 4 tests/apps/dispatcher/test_reconcile.py`. Replay result (exit 1), shortened:

```
[gw2] darwin -- Python 3.14.7 /private/tmp/claude-501/-Users-tmunzer-4-dev-mist-dewpoint/1e3145a1-199e-4b31-be1b-1e3bfd266be7/scratchpad/2b2-plan/proto/backend/.venv/bin/python
E   AssertionError: assert {'absent': 1} == {'unresolved': 1}
      Left contains 1 more item:
      {'absent': 1}
      Right contains 1 more item:
      {'unresolved': 1}
      Use -v to get more diff
----------------------------- Captured stdout call -----------------------------
[2m2026-10-03T19:51:52.840048Z[0m [33m WARN[0m [2mtemporalio_sdk_core::worker[0m[2m:[0m Temporal Server 1.16.0 or newer is required to guarantee that the latest heartbeat details are preserved when an activity fails; the server did not advertise the activity_failure_include_heartbeat capability, so heartbeat details may be lost on failure
[2m2026-10-03T19:51:52.840072Z[0m [33m WARN[0m [2mtemporalio_sdk_core::worker[0m[2m:[0m Temporal Server 1.16.0 or newer is required to guarantee that the latest heartbeat details are preserved when an activity fails; the server did not advertise the activity_failure_include_heartbeat capability, so heartbeat details may be lost on failure
/private/tmp/claude-501/-Users-tmunzer-4-dev-mist-dewpoint/1e3145a1-199e-4b31-be1b-1e3bfd266be7/scratchpad/2b2-plan/replay/backend/tests/apps/dispatcher/test_reconcile.py:212: AssertionError: assert {'absent': 1} == {'unresolved': 1}
=========================== short test summary info ============================
FAILED tests/apps/dispatcher/test_reconcile.py::test_a_lost_reply_whose_run_already_ended_is_still_reconciled
1 failed, 11 passed in 13.78s
```

- [ ] **Step 2: its code, then the same tests.** Replay result (exit 0), shortened:

```
............                                                             [100%]
12 passed in 13.93s
```

- [ ] **Step 3: commit.** `git cherry-pick --no-commit a3e1ec1 && git commit -C a3e1ec1`

The diff:

```diff
diff --git a/backend/src/dewpoint/apps/dispatcher/dispatch.py b/backend/src/dewpoint/apps/dispatcher/dispatch.py
index 4e51518..28edffd 100644
--- a/backend/src/dewpoint/apps/dispatcher/dispatch.py
+++ b/backend/src/dewpoint/apps/dispatcher/dispatch.py
@@ -427,6 +427,10 @@ async def _settle(s: AsyncSession, starting: Target, outcome: Outcome) -> str:
     if outcome.kind == "uncertain":
         log.warning("start_uncertain", request_id=str(request.id), detail=outcome.detail)
         return "uncertain"  # starting, its slot held, for the reconciler (§7.6)
+    if outcome.kind == "absent" and await _run_ended(s, request.id):
+        # Its run's row records an end: a start did happen, and only its history is gone. Never queued or started
+        # again; left as it is for an operator (the owner's M3 review).
+        return "history_missing"
     await release(s, request.id)
     if outcome.kind in ("refused", "throttled", "absent") and request.cancel_requested_at is not None:
         # A cancel recorded while it was starting, applied now that it didn't start (§7.8). A 10th refusal is
@@ -452,6 +456,11 @@ async def _settle(s: AsyncSession, starting: Target, outcome: Outcome) -> str:
     return "refused"
 
 
+async def _run_ended(s: AsyncSession, run_id: uuid.UUID) -> bool:
+    status = (await s.execute(text("select status from runs where id = :i"), {"i": run_id})).scalar()
+    return status is not None and status != "running"
+
+
 async def confirm(s: AsyncSession, request: RunRequest, at: datetime | None) -> None:
     """`starting` → `started`, idempotent and late-safe (§7.8): the run's `started_at` is set only if it has none, a
     terminal status is never overwritten, and no slot is reserved again (the root's end write releases it)."""
diff --git a/backend/src/dewpoint/apps/dispatcher/reconcile.py b/backend/src/dewpoint/apps/dispatcher/reconcile.py
index c9c0392..b421bf1 100644
--- a/backend/src/dewpoint/apps/dispatcher/reconcile.py
+++ b/backend/src/dewpoint/apps/dispatcher/reconcile.py
@@ -129,8 +129,13 @@ async def _starting(
         await handle.describe()
     except RPCError as e:
         if e.status == RPCStatusCode.NOT_FOUND and await namespace_answers(client):
-            return await dispatch.settle(sessionmaker, dispatch.Ref(request_id, tenant_id), dispatch.Outcome("absent"),
-                                         audited=True)  # fmt: skip
+            ref = dispatch.Ref(request_id, tenant_id)
+            happened = await dispatch.settle(sessionmaker, ref, dispatch.Outcome("absent"), audited=True)
+            if happened != "history_missing":
+                return happened
+            log.error("start_history_missing", request_id=str(request_id))  # its row ended: an operator recovers it
+            await _checked_alone(sessionmaker, tenant_id, request_id)
+            return "unresolved"
         return await _unresolved(sessionmaker, tenant_id, request_id, e.status.name)
     except Exception as e:  # a lost connection or a timeout: nothing is known
         return await _unresolved(sessionmaker, tenant_id, request_id, type(e).__name__)
diff --git a/backend/tests/apps/dispatcher/test_reconcile.py b/backend/tests/apps/dispatcher/test_reconcile.py
index d0a22e8..7566072 100644
--- a/backend/tests/apps/dispatcher/test_reconcile.py
+++ b/backend/tests/apps/dispatcher/test_reconcile.py
@@ -206,6 +206,17 @@ async def test_a_lost_reply_whose_run_already_ended_is_still_reconciled(
         assert (await asyncio.wait_for(handle.result(), 30)).status == "succeeded"
     before = await state(owner_sessionmaker, request.id)
     assert (before["request"][0], before["slot"], before["run"][0]) == ("starting", 0, "succeeded")
+    # Its history unavailable (NOT_FOUND from a namespace that answers): its row records an end, so a start did happen.
+    # Never back in the queue, never started again: unresolved, with an alert, for an operator (the owner's M3 review).
+    with structlog.testing.capture_logs() as seen:
+        assert await once(dispatch_sessionmaker, DescribeFails(rpc(RPCStatusCode.NOT_FOUND)), api_settings) == {
+            "unresolved": 1
+        }
+    assert await state(owner_sessionmaker, request.id) == before
+    assert any(e["event"] == "start_history_missing" and e["log_level"] == "error" for e in seen)
+    assert await begin(dispatch_sessionmaker, request, api_settings) is None  # not due: it isn't queued
+    async with owner_sessionmaker() as s, s.begin():  # its history back: asked again without waiting for RECHECK
+        await s.execute(text("update run_requests set checked_at = null where id = :i"), {"i": request.id})
     assert await once(dispatch_sessionmaker, env.client, api_settings) == {"started": 1}
     after = await state(owner_sessionmaker, request.id)
     assert (after["request"][0], after["slot"], after["run"][0]) == ("started", 0, "succeeded")
```

### Task 20: An absence requeues only on evidence read under the end write's locks; an ended run is never started again (the owner's milestone-3 review)

**Commit:** `b873fc3` (prototype `proto/2b2-v2`); the replay's tree was identical: yes.

**Modify:** `backend/src/dewpoint/apps/dispatcher/dispatch.py`, `backend/tests/apps/dispatcher/test_reconcile.py`

**What it does:**

A refused end write leaves the run's row running but releases its slot,
so a running row alone is no evidence that no start happened. An absence
now requeues a starting request only while its pre-created row is still
running and its reserved slot still held (only the root's end write
releases it while the request is starting). Both are read under those
rows' locks, in the end write's own order (row, then slot), so an end
write in flight is waited for and then seen; otherwise the request stays
starting, unresolved, with an alert.

For the one ordering locks can't cover (an end write landing after an
absence requeued the request), the starting transaction never starts a
queued request whose row already records an end: it goes back to
starting, without a slot, with an alert, for the reconciler.


- [ ] **Step 1: its tests alone, before its code.** Run: `uv run pytest -n 4 tests/apps/dispatcher/test_reconcile.py`. Replay result (exit 1), shortened:

```
/private/tmp/claude-501/-Users-tmunzer-4-dev-mist-dewpoint/1e3145a1-199e-4b31-be1b-1e3bfd266be7/scratchpad/2b2-plan/replay/backend/tests/apps/dispatcher/test_reconcile.py:225: AssertionError: assert {'absent': 1} == {'unresolved': 1}
[gw2] darwin -- Python 3.14.7 /private/tmp/claude-501/-Users-tmunzer-4-dev-mist-dewpoint/1e3145a1-199e-4b31-be1b-1e3bfd266be7/scratchpad/2b2-plan/proto/backend/.venv/bin/python
E   AssertionError: assert 'absent' == 'history_missing'
      - history_missing
      + absent
----------------------------- Captured stdout call -----------------------------
2026-10-03 21:52:29 [warning  ] start_absent                   request_id=6d1995ed-47b7-48b7-9e93-e3f24eaa84a3
/private/tmp/claude-501/-Users-tmunzer-4-dev-mist-dewpoint/1e3145a1-199e-4b31-be1b-1e3bfd266be7/scratchpad/2b2-plan/replay/backend/tests/apps/dispatcher/test_reconcile.py:275: AssertionError: assert 'absent' == 'history_missing'
=========================== short test summary info ============================
FAILED tests/apps/dispatcher/test_reconcile.py::test_an_end_write_in_flight_is_waited_for_before_an_absence_requeues[recorded]
FAILED tests/apps/dispatcher/test_reconcile.py::test_a_queued_request_whose_run_already_ended_is_never_started_again
FAILED tests/apps/dispatcher/test_reconcile.py::test_a_lost_reply_whose_run_already_ended_is_still_reconciled[refused]
FAILED tests/apps/dispatcher/test_reconcile.py::test_an_end_write_in_flight_is_waited_for_before_an_absence_requeues[refused]
4 failed, 12 passed in 14.50s
```

- [ ] **Step 2: its code, then the same tests.** Replay result (exit 0), shortened:

```
................                                                         [100%]
16 passed in 14.14s
```

- [ ] **Step 3: commit.** `git cherry-pick --no-commit b873fc3 && git commit -C b873fc3`

The diff:

```diff
diff --git a/backend/src/dewpoint/apps/dispatcher/dispatch.py b/backend/src/dewpoint/apps/dispatcher/dispatch.py
index 28edffd..66c8121 100644
--- a/backend/src/dewpoint/apps/dispatcher/dispatch.py
+++ b/backend/src/dewpoint/apps/dispatcher/dispatch.py
@@ -59,6 +59,7 @@ START_REFUSED = "start_refused"
 ID_COLLISION = "id_collision"
 START_FAILED = "start_failed"
 ENVELOPE_UNREADABLE = "envelope_unreadable"
+RUN_ENDED = "run_ended"
 KEY_UNUSABLE = "key_unusable"
 ENVELOPE_MESSAGE = (
     "The request's trigger envelope doesn't open or isn't JSON; repairing a key never reopens it (engine 2b spec §7.1)."
@@ -120,6 +121,14 @@ class Dead:
     reason: str
 
 
+@dataclass(frozen=True)
+class Held:
+    """Never started: its run's row already records an end (an end write that landed after an absence requeued it).
+    Back to `starting`, without a slot, with an alert, for the reconciler to verify or leave for an operator."""
+
+    reason: str
+
+
 @dataclass(frozen=True)
 class Cancelled:
     """A request cancelled at dispatch: `engine_abi_changed`, `node_type_retired` or `cel_profile_retired`."""
@@ -194,7 +203,7 @@ async def begin(
     tenant_id: uuid.UUID,
     request_id: uuid.UUID,
     build: Build,
-) -> Starting | Waiting | Cancelled | Dead | None:
+) -> Starting | Waiting | Cancelled | Dead | Held | None:
     """One due request's starting transaction. None: no longer due, or another dispatcher holds it. Anything it
     can't classify (a bug, an envelope its foreign key should have kept, an outage) raises; nothing it wrote stays."""
     async with sessionmaker() as s, s.begin():
@@ -212,7 +221,7 @@ async def _begin(
     tenant_id: uuid.UUID,
     request_id: uuid.UUID,
     build: Build,
-) -> Starting | Waiting | Cancelled | Dead | None:
+) -> Starting | Waiting | Cancelled | Dead | Held | None:
     await lifecycle.assert_read_committed(s)
     await tenant_scope(s, tenant_id)
     await _lock(s, GATE_LOCK)
@@ -231,6 +240,12 @@ async def _begin(
     ).scalar_one_or_none()
     if request is None or request.workflow_version_id is None:
         return None
+    ran = (await s.execute(text("select status from runs where id = :i for update"), {"i": request.id})).scalar()
+    if ran is not None and ran != "running":  # an earlier attempt's execution ran to its end: never a second start
+        log.error("start_after_end", request_id=str(request.id))
+        request.status, request.starting_at = "starting", func.statement_timestamp()
+        await s.flush()
+        return Held(RUN_ENDED)
     platform = await s.get(PlatformSettings, 1, populate_existing=True)
     if platform is None:
         return Waiting("environment_not_recorded")
@@ -427,9 +442,9 @@ async def _settle(s: AsyncSession, starting: Target, outcome: Outcome) -> str:
     if outcome.kind == "uncertain":
         log.warning("start_uncertain", request_id=str(request.id), detail=outcome.detail)
         return "uncertain"  # starting, its slot held, for the reconciler (§7.6)
-    if outcome.kind == "absent" and await _run_ended(s, request.id):
-        # Its run's row records an end: a start did happen, and only its history is gone. Never queued or started
-        # again; left as it is for an operator (the owner's M3 review).
+    if outcome.kind == "absent" and not await _unstarted(s, request.id):
+        # Its end write ran (its row records an end, or its slot was released): a start did happen, and only its
+        # history is gone. Never queued or started again; left as it is for an operator (the owner's M3 reviews).
         return "history_missing"
     await release(s, request.id)
     if outcome.kind in ("refused", "throttled", "absent") and request.cancel_requested_at is not None:
@@ -456,9 +471,16 @@ async def _settle(s: AsyncSession, starting: Target, outcome: Outcome) -> str:
     return "refused"
 
 
-async def _run_ended(s: AsyncSession, run_id: uuid.UUID) -> bool:
-    status = (await s.execute(text("select status from runs where id = :i"), {"i": run_id})).scalar()
-    return status is not None and status != "running"
+async def _unstarted(s: AsyncSession, run_id: uuid.UUID) -> bool:
+    """An absence's evidence that no start happened: the run's pre-created row still `running` and the slot reserved at
+    dispatch still held, which only the root's end write releases while a request is `starting`. Read under those rows'
+    locks, taken in the end write's own order (row, then slot): an end write in flight is waited for and then seen. The
+    slot is released here when it was held."""
+    status = (await s.execute(text("select status from runs where id = :i for update"), {"i": run_id})).scalar()
+    if status != "running":
+        return False
+    held = await s.execute(text("delete from run_slots where run_id = :i returning run_id"), {"i": run_id})
+    return held.first() is not None
 
 
 async def confirm(s: AsyncSession, request: RunRequest, at: datetime | None) -> None:
diff --git a/backend/tests/apps/dispatcher/test_reconcile.py b/backend/tests/apps/dispatcher/test_reconcile.py
index 7566072..1553d20 100644
--- a/backend/tests/apps/dispatcher/test_reconcile.py
+++ b/backend/tests/apps/dispatcher/test_reconcile.py
@@ -7,6 +7,7 @@ slot is released only once its run's latest execution is closed, never because i
 settles is audited (§2.4)."""
 
 import asyncio
+import dataclasses
 import uuid
 from datetime import timedelta
 from typing import Any
@@ -19,7 +20,7 @@ from temporalio.service import RPCStatusCode
 
 from dewpoint.apps.dispatcher import dispatch, reconcile
 from dewpoint.apps.worker.store import DbRunStore
-from dewpoint.engine.runtime.activities import ENGINE_QUEUE
+from dewpoint.engine.runtime.activities import ENGINE_QUEUE, ProjectInput
 from dewpoint.engine.runtime.ids import run_workflow_id
 from dewpoint.engine.runtime.workflow import RunGraph
 from tests.apps.dispatcher.support import begin, state
@@ -191,23 +192,35 @@ async def test_a_leaked_slot_is_released_only_once_its_runs_execution_is_closed(
     assert (await state(owner_sessionmaker, request.id))["slot"] == 0
 
 
+class RefusedEndWrite(DbRunStore):
+    """The worker's projection, but the database refuses the root's end write: logged and skipped, its row left
+    `running`, its slot released all the same (the owner's ruling on M2's Task 10)."""
+
+    async def project(self, data: ProjectInput) -> None:
+        refused = dataclasses.replace(data.run, status="bogus") if data.run is not None else None
+        await super().project(dataclasses.replace(data, run=refused))
+
+
+@pytest.mark.parametrize("end_write", ["recorded", "refused"])
 async def test_a_lost_reply_whose_run_already_ended_is_still_reconciled(
-    queued, owner_sessionmaker, dispatch_sessionmaker, worker_sessionmaker, api_settings, env, monkeypatch
+    queued, owner_sessionmaker, dispatch_sessionmaker, worker_sessionmaker, api_settings, env, monkeypatch, end_write
 ) -> None:
-    """The owner's M3 checkpoint: a start accepted, its reply lost, and the run so quick that its end write released
-    the slot while the request was still `starting`. The reconciler finds it by when it entered `starting`, never by a
-    slot it no longer has."""
+    """The owner's M3 checkpoints: a start accepted, its reply lost, and the run so quick that its end write (recorded,
+    or refused) released the slot while the request was still `starting`. The reconciler finds it by when it entered
+    `starting`, never by a slot it no longer has; with its history unavailable it's never queued or started again."""
     ctx, _, request = queued
     monkeypatch.setattr(reconcile, "GRACE", timedelta(0))  # its grace period over at once
-    async with workers(env.client, DbRunStore(worker_sessionmaker, KEYS)):
+    store = DbRunStore if end_write == "recorded" else RefusedEndWrite
+    async with workers(env.client, store(worker_sessionmaker, KEYS)):
         lost = await starting(dispatch_sessionmaker, request, api_settings)
         assert (await dispatch.start(env.client, lost)).kind == "started"  # accepted; its reply never settled
         handle = env.client.get_workflow_handle_for(RunGraph.run, run_workflow_id(str(ctx.tenant_id), str(request.id)))
         assert (await asyncio.wait_for(handle.result(), 30)).status == "succeeded"
     before = await state(owner_sessionmaker, request.id)
-    assert (before["request"][0], before["slot"], before["run"][0]) == ("starting", 0, "succeeded")
-    # Its history unavailable (NOT_FOUND from a namespace that answers): its row records an end, so a start did happen.
-    # Never back in the queue, never started again: unresolved, with an alert, for an operator (the owner's M3 review).
+    row = "succeeded" if end_write == "recorded" else "running"
+    assert (before["request"][0], before["slot"], before["run"][0]) == ("starting", 0, row)
+    # Its history unavailable (NOT_FOUND from a namespace that answers), and its slot gone: its end write ran, so a
+    # start did happen. Never back in the queue, never started again: unresolved, with an alert, for an operator.
     with structlog.testing.capture_logs() as seen:
         assert await once(dispatch_sessionmaker, DescribeFails(rpc(RPCStatusCode.NOT_FOUND)), api_settings) == {
             "unresolved": 1
@@ -219,9 +232,71 @@ async def test_a_lost_reply_whose_run_already_ended_is_still_reconciled(
         await s.execute(text("update run_requests set checked_at = null where id = :i"), {"i": request.id})
     assert await once(dispatch_sessionmaker, env.client, api_settings) == {"started": 1}
     after = await state(owner_sessionmaker, request.id)
-    assert (after["request"][0], after["slot"], after["run"][0]) == ("started", 0, "succeeded")
+    assert (after["request"][0], after["slot"]) == ("started", 0)
     assert after["run"][1] is not None  # its started_at, from the execution's own start
-    assert await once(dispatch_sessionmaker, env.client, api_settings) == {}  # nothing left to settle
+    # A recorded end leaves nothing to settle; a refused one leaves a running row, ended from Temporal's result (§7.6).
+    assert await once(dispatch_sessionmaker, env.client, api_settings) == (
+        {} if end_write == "recorded" else {"ended": 1}
+    )
+    assert (await state(owner_sessionmaker, request.id))["run"][0] == "succeeded"
+
+
+async def until_someone_waits(owner: Any) -> None:
+    """Until a transaction waits for a lock someone else holds (a row's, here)."""
+    for _ in range(200):
+        async with owner() as s:
+            if (await s.execute(text("select count(*) from pg_locks where not granted"))).scalar_one():
+                return
+        await asyncio.sleep(0.05)
+    raise AssertionError("nobody is waiting for a lock")
+
+
+@pytest.mark.parametrize("end_write", ["recorded", "refused"])
+async def test_an_end_write_in_flight_is_waited_for_before_an_absence_requeues(
+    queued, owner_sessionmaker, dispatch_sessionmaker, worker_sessionmaker, api_settings, end_write
+) -> None:
+    """The owner's M3 review: the request's lock doesn't hold back the worker's own writes to the run's row and slot.
+    An absence's evidence (the row still `running`, the slot still held) is read under those rows' locks, so an end
+    write in flight is waited for, and then seen: no requeue."""
+    ctx, _, request = queued
+    await starting(dispatch_sessionmaker, request, api_settings)
+    async with worker_sessionmaker() as w, w.begin():  # the end write, not yet committed
+        await w.execute(text("select set_config('app.tenant_id', :t, true)"), {"t": str(ctx.tenant_id)})
+        if end_write == "recorded":
+            await w.execute(
+                text("update runs set status = 'succeeded', ended_at = now() where id = :i"), {"i": request.id}
+            )
+        await w.execute(text("delete from run_slots where run_id = :i"), {"i": request.id})
+        settling = asyncio.create_task(
+            dispatch.settle(dispatch_sessionmaker, dispatch.Ref(request.id, ctx.tenant_id), dispatch.Outcome("absent"))
+        )
+        await until_someone_waits(owner_sessionmaker)
+        assert not settling.done()
+    assert await settling == "history_missing"
+    assert (await state(owner_sessionmaker, request.id))["request"][0] == "starting"
+
+
+async def test_a_queued_request_whose_run_already_ended_is_never_started_again(
+    queued, owner_sessionmaker, dispatch_sessionmaker, api_settings, env
+) -> None:
+    """An end write that lands only after an absence requeued its request (Temporal said NOT_FOUND for an execution
+    that was in fact live): the dispatcher never starts it again. It goes back to `starting`, without a slot, with an
+    alert, for the reconciler to verify or leave for an operator."""
+    ctx, _, request = queued
+    lost = await starting(dispatch_sessionmaker, request, api_settings)
+    assert await dispatch.settle(dispatch_sessionmaker, lost, dispatch.Outcome("absent")) == "absent"
+    async with owner_sessionmaker() as s, s.begin():  # the late end write
+        await s.execute(text("update runs set status = 'succeeded', ended_at = now() where id = :i"), {"i": request.id})
+    with structlog.testing.capture_logs() as seen:
+        assert await begin(dispatch_sessionmaker, request, api_settings) == dispatch.Held("run_ended")
+    after = await state(owner_sessionmaker, request.id)
+    assert (after["request"][0], after["slot"], after["run"][0]) == ("starting", 0, "succeeded")
+    assert any(e["event"] == "start_after_end" and e["log_level"] == "error" for e in seen)
+    async with owner_sessionmaker() as s, s.begin():
+        await s.execute(text("update run_requests set starting_at = now() - interval '1 hour' where id = :i"),
+                        {"i": request.id})  # fmt: skip
+    gone = DescribeFails(rpc(RPCStatusCode.NOT_FOUND))
+    assert await once(dispatch_sessionmaker, gone, api_settings) == {"unresolved": 1}  # never back in the queue
 
 
 async def test_a_leaked_slot_whose_history_is_gone_is_kept_with_an_alert(
```

### Task 21: A run's end write holds its row locked until its slot is released, in one transaction (the owner's milestone-3 review)

**Commit:** `cdb772e` (prototype `proto/2b2-v2`); the replay's tree was identical: yes.

**Modify:** `backend/src/dewpoint/apps/worker/store.py`, `backend/tests/apps/dispatcher/test_reconcile.py`

**What it does:**

A refused end write rolled back its savepoint, and the row lock taken
inside it, before releasing the slot; and the row-by-row retry of a
refused projection ran in a second transaction, with no lock held in
between. In either gap the reconciler could see a running row and a
held slot, take the slot itself and requeue a start that had happened.

The projection is now one transaction: a run's end locks its row first
(in the order the reconciler takes it, row then slot), the batch and its
row-by-row retry run as savepoints inside it, and the lock holds until
the slot is released and the transaction commits.


- [ ] **Step 1: its tests alone, before its code.** Run: `uv run pytest -n 4 tests/apps/dispatcher/test_reconcile.py`. Replay result (exit 1), shortened:

```
..........F......                                                        [100%]
=================================== FAILURES ===================================
[gw0] darwin -- Python 3.14.7 /private/tmp/claude-501/-Users-tmunzer-4-dev-mist-dewpoint/1e3145a1-199e-4b31-be1b-1e3bfd266be7/scratchpad/2b2-plan/proto/backend/.venv/bin/python
E   AssertionError: settled during the end write: absent
    assert not {<Task finished name='Task-86' coro=<settle() done, defined at /private/tmp/claude-501/-Users-tmunzer-4-dev-mist-dewpo...31-be1b-1e3bfd266be7/scratchpad/2b2-plan/replay/backend/src/dewpoint/apps/dispatcher/dispatch.py:412> result='absent'>}
----------------------------- Captured stdout call -----------------------------
2026-10-03 21:53:02 [warning  ] projection_run_refused         run_id=c442b4a7-351e-44ae-8e54-cefcfa56c6dd sqlstate=23514
2026-10-03 21:53:02 [warning  ] start_absent                   request_id=c442b4a7-351e-44ae-8e54-cefcfa56c6dd
/private/tmp/claude-501/-Users-tmunzer-4-dev-mist-dewpoint/1e3145a1-199e-4b31-be1b-1e3bfd266be7/scratchpad/2b2-plan/replay/backend/tests/apps/dispatcher/test_reconcile.py:307: AssertionError: settled during the end write: absent
=========================== short test summary info ============================
FAILED tests/apps/dispatcher/test_reconcile.py::test_a_refused_end_write_keeps_its_row_locked_until_its_slot_is_released
1 failed, 16 passed in 14.27s
```

- [ ] **Step 2: its code, then the same tests.** Replay result (exit 0), shortened:

```
.................                                                        [100%]
17 passed in 14.30s
```

- [ ] **Step 3: commit.** `git cherry-pick --no-commit cdb772e && git commit -C cdb772e`

The diff:

```diff
diff --git a/backend/src/dewpoint/apps/worker/store.py b/backend/src/dewpoint/apps/worker/store.py
index d36de73..8f244ae 100644
--- a/backend/src/dewpoint/apps/worker/store.py
+++ b/backend/src/dewpoint/apps/worker/store.py
@@ -11,7 +11,7 @@ from datetime import datetime
 from typing import Any
 
 import structlog
-from sqlalchemy import delete, select
+from sqlalchemy import delete, select, text
 from sqlalchemy.exc import DBAPIError
 from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
 from temporalio.exceptions import ApplicationError
@@ -177,59 +177,70 @@ class DbRunStore:
             )
 
     async def project(self, data: ProjectInput) -> None:
+        """One transaction. A projection the database refuses (a deterministic error) is written again row by row in
+        the same transaction, and a row refused again is logged and skipped. A run's end holds its row locked from the
+        start, past any refused savepoint, until its slot is released: the reconciler, which reads both before it puts
+        a start back in the queue, never sees one without the other (the owner's M3 review)."""
         tenant = uuid.UUID(data.tenant_id)
-        try:
-            async with self.sessionmaker() as s, s.begin():
-                await tenant_scope(s, tenant)
-                if data.start is not None:
-                    await _start(s, tenant, data.start)
-                await runs.upsert_steps(s, tenant, [_row(r) for r in data.steps])
-                if data.run is not None:
-                    await _finish(s, data.run)
-                    await _release(s, data.run)
-        except DBAPIError as e:
-            if _refused(e) is None:
-                raise
-            await self._one_by_one(tenant, data)
-
-    async def _one_by_one(self, tenant: uuid.UUID, data: ProjectInput) -> None:
         async with self.sessionmaker() as s, s.begin():
             await tenant_scope(s, tenant)
-            if data.start is not None:
-                try:
-                    async with s.begin_nested():
-                        await _start(s, tenant, data.start)
-                except DBAPIError as e:
-                    state = _refused(e)
-                    if state is None:
-                        raise
-                    _log.warning("projection_start_refused", run_id=data.start.run_id, sqlstate=state)
-            for row in data.steps:
-                try:
-                    async with s.begin_nested():
-                        await runs.upsert_steps(s, tenant, [_row(row)])
-                except DBAPIError as e:
-                    state = _refused(e)
-                    if state is None:
-                        raise
-                    _log.warning(
-                        "projection_row_refused",
-                        run_id=row.run_id,
-                        step_id=row.step_id,
-                        iteration_key=row.iteration_key,
-                        attempt=row.attempt,
-                        sqlstate=state,
-                    )
             if data.run is not None:
-                try:
-                    async with s.begin_nested():
+                await _hold(s, data.run)
+            try:
+                async with s.begin_nested():
+                    if data.start is not None:
+                        await _start(s, tenant, data.start)
+                    await runs.upsert_steps(s, tenant, [_row(r) for r in data.steps])
+                    if data.run is not None:
                         await _finish(s, data.run)
-                except DBAPIError as e:
-                    state = _refused(e)
-                    if state is None:
-                        raise
-                    _log.warning("projection_run_refused", run_id=data.run.run_id, sqlstate=state)
-                await _release(s, data.run)  # the execution ended either way
+                        await _release(s, data.run)
+            except DBAPIError as e:
+                if _refused(e) is None:
+                    raise
+                await self._one_by_one(s, tenant, data)
+
+    async def _one_by_one(self, s: AsyncSession, tenant: uuid.UUID, data: ProjectInput) -> None:
+        if data.start is not None:
+            try:
+                async with s.begin_nested():
+                    await _start(s, tenant, data.start)
+            except DBAPIError as e:
+                state = _refused(e)
+                if state is None:
+                    raise
+                _log.warning("projection_start_refused", run_id=data.start.run_id, sqlstate=state)
+        for row in data.steps:
+            try:
+                async with s.begin_nested():
+                    await runs.upsert_steps(s, tenant, [_row(row)])
+            except DBAPIError as e:
+                state = _refused(e)
+                if state is None:
+                    raise
+                _log.warning(
+                    "projection_row_refused",
+                    run_id=row.run_id,
+                    step_id=row.step_id,
+                    iteration_key=row.iteration_key,
+                    attempt=row.attempt,
+                    sqlstate=state,
+                )
+        if data.run is not None:
+            try:
+                async with s.begin_nested():
+                    await _finish(s, data.run)
+            except DBAPIError as e:
+                state = _refused(e)
+                if state is None:
+                    raise
+                _log.warning("projection_run_refused", run_id=data.run.run_id, sqlstate=state)
+            await _release(s, data.run)  # the execution ended either way
+
+
+async def _hold(s: AsyncSession, run: RunSummary) -> None:
+    """The run's row locked for the whole end write, in the outer transaction: a savepoint's rollback never releases
+    it. Taken first, in the order the reconciler takes it too (row, then slot)."""
+    await s.execute(text("select 1 from runs where id = :i for update"), {"i": uuid.UUID(run.run_id)})
 
 
 async def _start(s: AsyncSession, tenant: uuid.UUID, start: RunStart) -> None:
diff --git a/backend/tests/apps/dispatcher/test_reconcile.py b/backend/tests/apps/dispatcher/test_reconcile.py
index 1553d20..3b5c44d 100644
--- a/backend/tests/apps/dispatcher/test_reconcile.py
+++ b/backend/tests/apps/dispatcher/test_reconcile.py
@@ -9,7 +9,7 @@ settles is audited (§2.4)."""
 import asyncio
 import dataclasses
 import uuid
-from datetime import timedelta
+from datetime import UTC, datetime, timedelta
 from typing import Any
 
 import pytest
@@ -19,8 +19,9 @@ from sqlalchemy.exc import IntegrityError
 from temporalio.service import RPCStatusCode
 
 from dewpoint.apps.dispatcher import dispatch, reconcile
+from dewpoint.apps.worker import store
 from dewpoint.apps.worker.store import DbRunStore
-from dewpoint.engine.runtime.activities import ENGINE_QUEUE, ProjectInput
+from dewpoint.engine.runtime.activities import ENGINE_QUEUE, ProjectInput, RunSummary
 from dewpoint.engine.runtime.ids import run_workflow_id
 from dewpoint.engine.runtime.workflow import RunGraph
 from tests.apps.dispatcher.support import begin, state
@@ -276,6 +277,42 @@ async def test_an_end_write_in_flight_is_waited_for_before_an_absence_requeues(
     assert (await state(owner_sessionmaker, request.id))["request"][0] == "starting"
 
 
+async def test_a_refused_end_write_keeps_its_row_locked_until_its_slot_is_released(
+    queued, owner_sessionmaker, dispatch_sessionmaker, worker_sessionmaker, api_settings, monkeypatch
+) -> None:
+    """The owner's M3 review: a refused end write rolls back its savepoint, and the row lock taken inside it, before it
+    releases the slot. Its outer transaction keeps the run's row locked across both, so an absence checked in between
+    waits, then finds the slot released: no requeue."""
+    ctx, _, request = queued
+    await starting(dispatch_sessionmaker, request, api_settings)
+    paused, go = asyncio.Event(), asyncio.Event()
+    release = store._release
+
+    async def release_when_told(s: Any, run: Any) -> None:  # paused after the refused savepoint, before the release
+        paused.set()
+        await go.wait()
+        await release(s, run)
+
+    monkeypatch.setattr(store, "_release", release_when_told)
+    refused = RunSummary(str(request.id), "bogus", datetime.now(UTC).isoformat())
+    writing = asyncio.create_task(
+        DbRunStore(worker_sessionmaker, KEYS).project(ProjectInput(str(ctx.tenant_id), [], refused))
+    )
+    try:
+        await asyncio.wait_for(paused.wait(), 10)
+        settling = asyncio.create_task(
+            dispatch.settle(dispatch_sessionmaker, dispatch.Ref(request.id, ctx.tenant_id), dispatch.Outcome("absent"))
+        )
+        done, _ = await asyncio.wait({settling}, timeout=1.0)
+        assert not done, f"settled during the end write: {settling.result()}"  # it waits for the row's lock
+    finally:
+        go.set()
+        await writing
+    assert await settling == "history_missing"
+    after = await state(owner_sessionmaker, request.id)
+    assert (after["request"][0], after["slot"], after["run"][0]) == ("starting", 0, "running")
+
+
 async def test_a_queued_request_whose_run_already_ended_is_never_started_again(
     queued, owner_sessionmaker, dispatch_sessionmaker, api_settings, env
 ) -> None:
```

**Checkpoint (milestone 3).** Focused: as milestone 2, plus the reconciler, cancels and the gate (334 at `f54a086`; 338, 129, 136 and 163 after Tasks 18–21); the migrations up to 0023 and back. The owner held it four times — a slotless `starting` request (Task 18), an ended run's request requeued on a missing history (Task 19), a refused end write's released slot and the worker's concurrent writes (Task 20), the refused savepoint's lock (Task 21) — accepted the recovery transition for §7.8, and approved it (2026-10-03).

## Milestone 4 — The run API, the CLI and Compose

### Task 22: Start a run and read its start form

**Commit:** `60d2db9` (prototype `proto/2b2-v2`); the replay's tree was identical: yes.

**Create:** `backend/src/dewpoint/apps/api/routes/run_requests.py`, `backend/src/dewpoint/apps/forms.py`, `backend/tests/apps/api/test_run_requests_api.py`, `backend/tests/apps/test_forms.py`

**Modify:** `backend/src/dewpoint/apps/api/main.py`

**What it does:**

POST /t/{tid}/workflows/{wid}/runs (run.start) admits a request in the
API's own transaction with an Idempotency-Key (428 without one) and
answers 202 with it; the dispatcher starts it. An exact retry returns
the same request; another body under the key is 409
idempotency_conflict. A refusal answers with its code and fixed
messages: 503 while runs can't start (production_runs_disabled,
environment_not_recorded, no_current_build), 422 for an input, 409 for
the workflow's state. The API gets a keyring key source for admission.

GET .../start-form describes the active version's input as typed
fields, a sensitive field's default and enum masked, x-dewpoint-picker
passed through; CSV comes with 2b-3.


- [ ] **Step 1: its tests alone, before its code.** Run: `uv run pytest -n 4 tests/apps/api/test_run_requests_api.py tests/apps/test_forms.py`. Replay result (exit 1), shortened:

```
/private/tmp/claude-501/-Users-tmunzer-4-dev-mist-dewpoint/1e3145a1-199e-4b31-be1b-1e3bfd266be7/scratchpad/2b2-plan/replay/backend/tests/apps/api/test_run_requests_api.py:166: AssertionError: {"error":"not_found"}
=========================== short test summary info ============================
FAILED tests/apps/api/test_run_requests_api.py::test_a_start_without_an_idempotency_key_is_refused
FAILED tests/apps/api/test_run_requests_api.py::test_a_body_with_unknown_fields_is_refused
FAILED tests/apps/api/test_run_requests_api.py::test_an_operator_starts_a_run_and_gets_its_queued_request
FAILED tests/apps/api/test_run_requests_api.py::test_a_disabled_workflow_answers_409_with_its_reason
FAILED tests/apps/api/test_run_requests_api.py::test_an_input_that_doesnt_match_its_schema_is_422_with_its_places_never_its_values
FAILED tests/apps/api/test_run_requests_api.py::test_an_exact_retry_returns_the_same_request_and_another_body_is_a_conflict
FAILED tests/apps/api/test_run_requests_api.py::test_production_runs_off_answers_503
FAILED tests/apps/api/test_run_requests_api.py::test_a_viewer_cant_start_a_run
FAILED tests/apps/api/test_run_requests_api.py::test_a_workflow_without_an_active_version_has_no_start_form
FAILED tests/apps/api/test_run_requests_api.py::test_the_start_form_describes_the_active_versions_input
ERROR tests/apps/test_forms.py - ImportError while importing test module '/pr...
10 failed, 1 passed, 1 error in 11.50s
```

- [ ] **Step 2: its code, then the same tests.** Replay result (exit 0), shortened:

```
.............                                                            [100%]
13 passed in 11.64s
```

- [ ] **Step 3: commit.** `git cherry-pick --no-commit 60d2db9 && git commit -C 60d2db9`

The diff:

```diff
diff --git a/backend/src/dewpoint/apps/api/main.py b/backend/src/dewpoint/apps/api/main.py
index 245f5d9..d419786 100644
--- a/backend/src/dewpoint/apps/api/main.py
+++ b/backend/src/dewpoint/apps/api/main.py
@@ -17,6 +17,7 @@ from dewpoint.apps.api.routes import (
     mfa,
     node_types,
     passkeys,
+    run_requests,
     runs,
     tenants,
     workflows,
@@ -24,6 +25,7 @@ from dewpoint.apps.api.routes import (
 from dewpoint.core.config import Settings, get_settings
 from dewpoint.core.crypto.kek import KekSet
 from dewpoint.core.crypto.keyring import Keyring
+from dewpoint.core.crypto.keys import KeyringKeys
 from dewpoint.core.db import make_engine, make_sessionmaker
 
 
@@ -43,6 +45,7 @@ def create_app(settings: Settings | None = None) -> FastAPI:
     app.state.engine = make_engine(settings.database_url)
     app.state.sessionmaker = make_sessionmaker(app.state.engine)
     app.state.keyring = Keyring(KekSet.from_settings(settings))
+    app.state.keys = KeyringKeys(app.state.sessionmaker, app.state.keyring)  # admission's: claims, envelopes, digests
     # Created eagerly (not in the lifespan) so ASGI test transports, which skip lifespan, get it too.
     app.state.http = httpx.AsyncClient(timeout=10, follow_redirects=False)
     app.add_middleware(
@@ -63,6 +66,7 @@ def create_app(settings: Settings | None = None) -> FastAPI:
         connections.router,
         node_types.router,
         workflows.router,
+        run_requests.router,
         runs.router,
     ):
         app.include_router(router)
diff --git a/backend/src/dewpoint/apps/api/routes/run_requests.py b/backend/src/dewpoint/apps/api/routes/run_requests.py
new file mode 100644
index 0000000..43f51f9
--- /dev/null
+++ b/backend/src/dewpoint/apps/api/routes/run_requests.py
@@ -0,0 +1,119 @@
+# SPDX-License-Identifier: Apache-2.0
+"""Starting runs (engine 2b spec §7.7): a request is admitted in the API's own transaction and the dispatcher starts
+it, so the API has no Temporal client. Every start carries an `Idempotency-Key`: an exact retry returns the same
+request, another body under the key is a 409. A refusal answers with its code (§9) and fixed messages that never quote
+a value: 503 while the deployment can't start runs, 422 for an input, 409 for the workflow's state."""
+
+import uuid
+from datetime import datetime
+from typing import Any, Literal
+
+from fastapi import APIRouter, Depends, Header, HTTPException, Request
+from pydantic import BaseModel, ConfigDict, Field
+from sqlalchemy.ext.asyncio import AsyncSession
+
+from dewpoint.apps import admission
+from dewpoint.apps.forms import form_fields
+from dewpoint.apps.inputs import INPUT_INVALID
+from dewpoint.core.authz.permissions import P
+from dewpoint.core.claims.secret_index import SECRET_INDEX_LIMIT
+from dewpoint.core.crypto.keys import KeySource
+from dewpoint.core.http import TenantContext, get_db, require
+from dewpoint.core.models.requests import RunRequest
+from dewpoint.core.models.workflows import Workflow, WorkflowVersion
+
+router = APIRouter(prefix="/api/v1", tags=["runs"])
+KEY_MAX = 255
+UNAVAILABLE = {admission.PRODUCTION_RUNS_DISABLED, admission.ENVIRONMENT_NOT_RECORDED, admission.NO_CURRENT_BUILD}
+INVALID = {INPUT_INVALID, SECRET_INDEX_LIMIT}
+
+
+class StartIn(BaseModel):
+    model_config = ConfigDict(extra="forbid")
+    input: dict[str, Any] = Field(default_factory=dict)
+    mode: Literal["live", "simulate"] = "live"
+
+
+def get_keys(request: Request) -> KeySource:
+    return request.app.state.keys  # type: ignore[no-any-return]
+
+
+def idempotency_key(key: str | None = Header(None, alias="Idempotency-Key")) -> str:
+    if not key:
+        raise HTTPException(428, detail={"error": "idempotency_key_required"})
+    if len(key) > KEY_MAX:
+        raise HTTPException(422, detail={"error": "invalid", "fields": ["Idempotency-Key"]})
+    return key
+
+
+def _when(value: datetime | None) -> str | None:
+    return value.isoformat() if value else None
+
+
+def request_body(r: RunRequest) -> dict[str, object]:
+    """A request as the API shows it: its state and its frozen version, never its input."""
+    return {
+        "id": str(r.id),
+        "workflow_id": str(r.workflow_id),
+        "version_id": str(r.workflow_version_id) if r.workflow_version_id else None,
+        "mode": r.mode,
+        "source": r.source,
+        "status": r.status,
+        "reason": r.reason,
+        "queued_at": _when(r.queued_at),
+        "ended_at": _when(r.ended_at),
+    }
+
+
+async def admit(
+    db: AsyncSession, keys: KeySource, ctx: TenantContext, workflow_id: uuid.UUID, source: str, body: StartIn, key: str
+) -> RunRequest:
+    try:
+        admitted = await admission.admit_request(
+            db, keys, tenant_id=ctx.tenant_id, workflow_id=workflow_id, source=source, actor_id=ctx.user.id,
+            mode=body.mode, idempotency_key=key, input=body.input,
+        )  # fmt: skip
+    except admission.WorkflowNotFoundError:
+        raise HTTPException(404, detail={"error": "not_found"}) from None
+    except admission.IdempotencyConflictError:
+        raise HTTPException(409, detail={"error": "idempotency_conflict"}) from None
+    except admission.AdmissionRefusedError as e:
+        status = 503 if e.reason in UNAVAILABLE else 422 if e.reason in INVALID else 409
+        raise HTTPException(status, detail={"error": e.reason, "messages": e.messages}) from None
+    return admitted.request
+
+
+@router.post("/t/{tenant_id}/workflows/{workflow_id}/runs", status_code=202)
+async def start_run(
+    workflow_id: uuid.UUID,
+    body: StartIn,
+    key: str = Depends(idempotency_key),
+    ctx: TenantContext = Depends(require(P.RUN_START)),
+    db: AsyncSession = Depends(get_db, scope="function"),
+    keys: KeySource = Depends(get_keys),
+) -> dict[str, object]:
+    """202 with the request, queued for the dispatcher (or as an exact retry finds it now)."""
+    return request_body(await admit(db, keys, ctx, workflow_id, "manual", body, key))
+
+
+@router.get("/t/{tenant_id}/workflows/{workflow_id}/start-form")
+async def start_form(
+    workflow_id: uuid.UUID,
+    ctx: TenantContext = Depends(require(P.RUN_START)),
+    db: AsyncSession = Depends(get_db, scope="function"),
+) -> dict[str, object]:
+    """The active version's input, as a form: its typed fields, sensitive ones masked. CSV starts come with 2b-3."""
+    workflow = await db.get(Workflow, workflow_id)  # row-level security: the caller's tenant's only
+    if workflow is None:
+        raise HTTPException(404, detail={"error": "not_found"})
+    if workflow.active_version_id is None:
+        raise HTTPException(409, detail={"error": admission.NOT_ACTIVE})
+    version = await db.get(WorkflowVersion, workflow.active_version_id)
+    if version is None:
+        raise HTTPException(409, detail={"error": admission.NOT_ACTIVE})
+    return {
+        "workflow_id": str(workflow.id),
+        "version_id": str(version.id),
+        "fields": form_fields(version.input_schema or {}),
+        "csv": None,
+    }
diff --git a/backend/src/dewpoint/apps/forms.py b/backend/src/dewpoint/apps/forms.py
new file mode 100644
index 0000000..a3d2530
--- /dev/null
+++ b/backend/src/dewpoint/apps/forms.py
@@ -0,0 +1,36 @@
+# SPDX-License-Identifier: Apache-2.0
+"""A start form's fields (engine 2b spec §7.7): the typed top-level fields of a version's `input_schema`, for the UI.
+A sensitive field shows its type and whether it's required, never a value the schema holds for it: its default and
+its enum are masked (publish refuses a sensitive literal anyway, §3.8). `x-dewpoint-picker` is passed through for
+sub-project 3's pickers."""
+
+from collections.abc import Mapping
+from typing import Any
+
+SENSITIVE = "x-sensitive"
+PICKER = "x-dewpoint-picker"
+
+
+def form_fields(schema: Mapping[str, Any]) -> list[dict[str, Any]]:
+    required = set(schema.get("required") or ())
+    fields: list[dict[str, Any]] = []
+    for name, prop in (schema.get("properties") or {}).items():
+        sensitive = bool(prop.get(SENSITIVE))
+        field: dict[str, Any] = {"name": name, "type": prop.get("type"), "required": name in required,
+                                 "sensitive": sensitive}  # fmt: skip
+        for key in ("title", "description"):
+            if key in prop:
+                field[key] = prop[key]
+        if sensitive:
+            if "default" in prop:
+                field["default_masked"] = True
+            if "enum" in prop:
+                field["enum_masked"] = True
+        else:
+            for key in ("enum", "default"):
+                if key in prop:
+                    field[key] = prop[key]
+        if PICKER in prop:
+            field["picker"] = prop[PICKER]
+        fields.append(field)
+    return fields
diff --git a/backend/tests/apps/api/test_run_requests_api.py b/backend/tests/apps/api/test_run_requests_api.py
new file mode 100644
index 0000000..67be2e8
--- /dev/null
+++ b/backend/tests/apps/api/test_run_requests_api.py
@@ -0,0 +1,187 @@
+# SPDX-License-Identifier: Apache-2.0
+"""Starting a run through the API (engine 2b spec §7.7): `POST /t/{tid}/workflows/{wid}/runs` admits a request in the
+API's own transaction (`run.start`, an `Idempotency-Key`), answers 202 with it, and leaves the start to the dispatcher;
+the API has no Temporal client. An exact retry returns the same request; another body under the key is a 409. A
+refusal says why, with a code and fixed messages that never quote a value. `GET .../start-form` describes the active
+version's input, masking what's sensitive."""
+
+import uuid
+from typing import Any
+
+import pytest
+from sqlalchemy import text
+
+from tests.apps.api.helpers import member_client
+from tests.apps.test_admission import KEYS, TOKEN, count, current, published
+from tests.apps.test_workflow_ops import update
+from tests.support.graphs import G
+
+pytestmark = pytest.mark.usefixtures("development_deployment")
+BODY = {"input": {"token": TOKEN, "site": "a"}, "mode": "live"}
+
+
+@pytest.fixture
+def keyed_app(app: Any) -> Any:
+    """The API with fixture keys: its tenants here have no keyring keys, and the dispatcher's tests read with these."""
+    app.state.keys = KEYS
+    return app
+
+
+@pytest.fixture
+async def ready(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings) -> Any:
+    ctx, wf = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings)
+    await current(dispatch_sessionmaker)
+    return ctx, wf
+
+
+async def as_role(app: Any, owner: Any, settings: Any, ctx: Any, role: str = "operator") -> Any:
+    client, _ = await member_client(app, owner, settings, ctx.tenant_id, role)
+    return client
+
+
+def runs_url(ctx: Any, wf: uuid.UUID) -> str:
+    return f"/api/v1/t/{ctx.tenant_id}/workflows/{wf}/runs"
+
+
+async def test_an_operator_starts_a_run_and_gets_its_queued_request(
+    keyed_app, ready, owner_sessionmaker, api_settings
+) -> None:
+    ctx, wf = ready
+    client = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx)
+    answer = await client.post(runs_url(ctx, wf), json=BODY, headers={"Idempotency-Key": "k1"})
+    assert answer.status_code == 202, answer.text
+    body = answer.json()
+    assert {k: body[k] for k in ("status", "workflow_id", "mode", "source")} == {
+        "status": "queued", "workflow_id": str(wf), "mode": "live", "source": "manual",
+    }  # fmt: skip
+    assert body["version_id"] and body["queued_at"] and body["reason"] is None
+    assert TOKEN not in answer.text
+    async with owner_sessionmaker() as s:
+        status = (await s.execute(text("select status from run_requests where id = :i"), {"i": body["id"]})).scalar()
+    assert status == "queued"
+
+
+async def test_an_exact_retry_returns_the_same_request_and_another_body_is_a_conflict(
+    keyed_app, ready, owner_sessionmaker, api_settings
+) -> None:
+    ctx, wf = ready
+    client = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx)
+    first = await client.post(runs_url(ctx, wf), json=BODY, headers={"Idempotency-Key": "k1"})
+    again = await client.post(runs_url(ctx, wf), json=BODY, headers={"Idempotency-Key": "k1"})
+    assert (again.status_code, again.json()["id"]) == (202, first.json()["id"])
+    other = {**BODY, "input": {"token": TOKEN, "site": "b"}}
+    conflict = await client.post(runs_url(ctx, wf), json=other, headers={"Idempotency-Key": "k1"})
+    assert (conflict.status_code, conflict.json()["error"]) == (409, "idempotency_conflict")
+    assert await count(owner_sessionmaker, "run_requests") == 1
+
+
+async def test_a_start_without_an_idempotency_key_is_refused(
+    keyed_app, ready, owner_sessionmaker, api_settings
+) -> None:
+    ctx, wf = ready
+    client = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx)
+    answer = await client.post(runs_url(ctx, wf), json=BODY)
+    assert (answer.status_code, answer.json()) == (428, {"error": "idempotency_key_required"})
+
+
+async def test_an_input_that_doesnt_match_its_schema_is_422_with_its_places_never_its_values(
+    keyed_app, ready, owner_sessionmaker, api_settings
+) -> None:
+    ctx, wf = ready
+    client = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx)
+    answer = await client.post(
+        runs_url(ctx, wf), json={"input": {"site": "x" * 5, "extra": TOKEN}, "mode": "live"},
+        headers={"Idempotency-Key": "k1"},
+    )  # fmt: skip
+    assert answer.status_code == 422 and answer.json()["error"] == "input_invalid"
+    assert answer.json()["messages"] and TOKEN not in answer.text
+    assert await count(owner_sessionmaker, "run_requests") == 0  # an interactive refusal records nothing
+
+
+async def test_a_body_with_unknown_fields_is_refused(keyed_app, ready, owner_sessionmaker, api_settings) -> None:
+    """CSV starts are 2b-3's: a `csv` field isn't accepted yet."""
+    ctx, wf = ready
+    client = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx)
+    answer = await client.post(runs_url(ctx, wf), json={**BODY, "csv": "u1"}, headers={"Idempotency-Key": "k1"})
+    assert (answer.status_code, answer.json()["error"]) == (422, "invalid")
+
+
+async def test_production_runs_off_answers_503(keyed_app, ready, owner_sessionmaker, api_settings) -> None:
+    ctx, wf = ready
+    async with owner_sessionmaker() as s, s.begin():
+        await s.execute(text("alter table platform_settings disable trigger user"))
+        await s.execute(text("update platform_settings set environment = 'production', production_runs = false"))
+        await s.execute(text("alter table platform_settings enable trigger user"))
+    client = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx)
+    answer = await client.post(runs_url(ctx, wf), json=BODY, headers={"Idempotency-Key": "k1"})
+    assert (answer.status_code, answer.json()["error"]) == (503, "production_runs_disabled")
+
+
+async def test_a_disabled_workflow_answers_409_with_its_reason(
+    keyed_app, ready, owner_sessionmaker, api_sessionmaker, api_settings
+) -> None:
+    ctx, wf = ready
+    await update(api_sessionmaker, ctx, wf, enabled=False)
+    client = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx)
+    answer = await client.post(runs_url(ctx, wf), json=BODY, headers={"Idempotency-Key": "k1"})
+    assert (answer.status_code, answer.json()["error"]) == (409, "workflow_disabled")
+
+
+async def test_a_viewer_cant_start_a_run(keyed_app, ready, owner_sessionmaker, api_settings) -> None:
+    ctx, wf = ready
+    client = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "viewer")
+    answer = await client.post(runs_url(ctx, wf), json=BODY, headers={"Idempotency-Key": "k1"})
+    assert answer.status_code == 403
+
+
+async def test_another_tenants_workflow_isnt_found(
+    keyed_app, ready, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings
+) -> None:
+    ctx, wf = ready
+    other, _ = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings)
+    client = await as_role(keyed_app, owner_sessionmaker, api_settings, other)
+    answer = await client.post(runs_url(other, wf), json=BODY, headers={"Idempotency-Key": "k1"})
+    assert (answer.status_code, answer.json()["error"]) == (404, "not_found")
+
+
+FORM_SCHEMA = {
+    "type": "object",
+    "properties": {
+        "token": {"type": "string", "x-sensitive": True, "title": "API token"},
+        "site": {"type": "string", "enum": ["a", "b"], "default": "a", "x-dewpoint-picker": {"kind": "site"}},
+        "count": {"type": "integer", "description": "How many"},
+    },
+    "required": ["token", "site"],
+    "additionalProperties": False,
+}
+
+
+async def test_the_start_form_describes_the_active_versions_input(
+    keyed_app, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings
+) -> None:
+    graph = G().node("a", "testkit.echo@1", {"value": 1}).data() | {"settings": {"input_schema": FORM_SCHEMA}}
+    ctx, wf = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings, graph)
+    client = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx)
+    answer = await client.get(f"/api/v1/t/{ctx.tenant_id}/workflows/{wf}/start-form")
+    assert answer.status_code == 200, answer.text
+    form = answer.json()
+    assert form["workflow_id"] == str(wf) and form["version_id"] and form["csv"] is None
+    assert {f["name"]: f for f in form["fields"]} == {
+        "token": {"name": "token", "type": "string", "required": True, "sensitive": True, "title": "API token"},
+        "site": {"name": "site", "type": "string", "required": True, "sensitive": False, "enum": ["a", "b"],
+                 "default": "a", "picker": {"kind": "site"}},
+        "count": {"name": "count", "type": "integer", "required": False, "sensitive": False,
+                  "description": "How many"},
+    }  # fmt: skip
+
+
+async def test_a_workflow_without_an_active_version_has_no_start_form(
+    keyed_app, owner_sessionmaker, api_sessionmaker, api_settings
+) -> None:
+    from tests.apps.test_workflow_ops import actor, create
+
+    ctx = await actor(owner_sessionmaker)
+    wf = await create(api_sessionmaker, ctx, G().node("a", "testkit.echo@1", {"value": 1}).data())
+    client = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx)
+    answer = await client.get(f"/api/v1/t/{ctx.tenant_id}/workflows/{wf}/start-form")
+    assert (answer.status_code, answer.json()["error"]) == (409, "not_active")
diff --git a/backend/tests/apps/test_forms.py b/backend/tests/apps/test_forms.py
new file mode 100644
index 0000000..505f4fc
--- /dev/null
+++ b/backend/tests/apps/test_forms.py
@@ -0,0 +1,24 @@
+# SPDX-License-Identifier: Apache-2.0
+"""A start form's fields (engine 2b spec §7.7): a sensitive field never shows a value its schema holds."""
+
+from dewpoint.apps.forms import form_fields
+
+
+def test_a_sensitive_fields_default_and_enum_are_masked() -> None:
+    schema = {
+        "properties": {
+            "token": {"type": "string", "x-sensitive": True, "default": "d3fault-secret", "enum": ["s1", "s2"]},
+            "site": {"type": ["string", "null"], "default": None},
+        },
+        "required": ["token"],
+    }
+    assert form_fields(schema) == [
+        {"name": "token", "type": "string", "required": True, "sensitive": True, "default_masked": True,
+         "enum_masked": True},
+        {"name": "site", "type": ["string", "null"], "required": False, "sensitive": False, "default": None},
+    ]  # fmt: skip
+    assert "d3fault-secret" not in str(form_fields(schema)) and "s1" not in str(form_fields(schema))
+
+
+def test_a_schema_without_fields_has_an_empty_form() -> None:
+    assert form_fields({}) == [] and form_fields({"type": "object"}) == []
```

### Task 23: Cancel a run request and re-run one by its request

**Commit:** `f992a27` (prototype `proto/2b2-v2`); the replay's tree was identical: yes.

**Modify:** `backend/src/dewpoint/apps/api/routes/run_requests.py`, `backend/src/dewpoint/core/authz/permissions.py`, `backend/src/dewpoint/core/claims/service.py`, `backend/tests/apps/api/test_run_requests_api.py`, `backend/tests/core/requests/test_envelope.py`

**What it does:**

POST /t/{tid}/runs/{id}/cancel (the new run.cancel, operators and up):
200 cancelled for a queued request, 202 requested for a starting one or
a running run (the dispatcher applies or sends it), 409 run_ended.

POST /t/{tid}/runs/{id}/rerun (run.start, an Idempotency-Key) names the
old request: its envelope is read through its own reader and every
handle resolved through read_request_claim (the request's own input
claims in run_inputs, nothing else), the complete input held in memory
only, then admitted as a new request (source rerun) on the active
version and claimed again: no old handle is reused. 410
input_not_retained for a run from before 2b-2, a refused request, or an
envelope or claim retention removed.

A tenant key that can't be read answers 503 key_unusable on every
admission path, classified as the dispatcher classifies one.


- [ ] **Step 1: its tests alone, before its code.** Run: `uv run pytest -n 4 tests/apps/api/test_run_requests_api.py tests/core/requests/test_envelope.py`. Replay result (exit 1), shortened:

```
NoKeyError: no key for tenant 04c8a3dc-cc99-4398-a9ba-851a413dd36b
/private/tmp/claude-501/-Users-tmunzer-4-dev-mist-dewpoint/1e3145a1-199e-4b31-be1b-1e3bfd266be7/scratchpad/2b2-plan/replay/backend/tests/support/keys.py:40: dewpoint.core.crypto.keyring.NoKeyError: no key for tenant 04c8a3dc-cc99-4398-a9ba-851a413dd36b
=========================== short test summary info ============================
FAILED tests/apps/api/test_run_requests_api.py::test_an_operator_cancels_a_queued_request_at_once
FAILED tests/apps/api/test_run_requests_api.py::test_a_rerun_admits_the_complete_original_input_as_a_new_request_with_new_claims
FAILED tests/apps/api/test_run_requests_api.py::test_a_viewer_cant_cancel_and_an_unknown_request_isnt_found
FAILED tests/apps/api/test_run_requests_api.py::test_a_rerun_whose_input_isnt_retained_is_410[pre_2b2_run]
FAILED tests/apps/api/test_run_requests_api.py::test_a_rerun_whose_input_isnt_retained_is_410[refused]
FAILED tests/apps/api/test_run_requests_api.py::test_a_starting_requests_cancel_is_recorded_for_the_dispatcher
FAILED tests/apps/api/test_run_requests_api.py::test_a_rerun_whose_input_isnt_retained_is_410[claim_removed]
FAILED tests/apps/api/test_run_requests_api.py::test_a_rerun_needs_an_idempotency_key_and_an_existing_request
FAILED tests/core/requests/test_envelope.py::test_a_reruns_reader_reads_only_its_requests_own_input_claims
FAILED tests/apps/api/test_run_requests_api.py::test_a_tenant_whose_key_cant_be_read_answers_503
10 failed, 15 passed in 15.94s
```

- [ ] **Step 2: its code, then the same tests.** Replay result (exit 0), shortened:

```
.........................                                                [100%]
25 passed in 13.06s
```

- [ ] **Step 3: commit.** `git cherry-pick --no-commit f992a27 && git commit -C f992a27`

The diff:

```diff
diff --git a/backend/src/dewpoint/apps/api/routes/run_requests.py b/backend/src/dewpoint/apps/api/routes/run_requests.py
index 43f51f9..7171387 100644
--- a/backend/src/dewpoint/apps/api/routes/run_requests.py
+++ b/backend/src/dewpoint/apps/api/routes/run_requests.py
@@ -2,30 +2,36 @@
 """Starting runs (engine 2b spec §7.7): a request is admitted in the API's own transaction and the dispatcher starts
 it, so the API has no Temporal client. Every start carries an `Idempotency-Key`: an exact retry returns the same
 request, another body under the key is a 409. A refusal answers with its code (§9) and fixed messages that never quote
-a value: 503 while the deployment can't start runs, 422 for an input, 409 for the workflow's state."""
+a value: 503 while the deployment can't start runs (or the tenant's key can't be read), 422 for an input, 409 for the
+workflow's state. A cancel and a re-run name a request: its id is its run's, if it has one."""
 
 import uuid
 from datetime import datetime
 from typing import Any, Literal
 
-from fastapi import APIRouter, Depends, Header, HTTPException, Request
+from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
 from pydantic import BaseModel, ConfigDict, Field
 from sqlalchemy.ext.asyncio import AsyncSession
 
-from dewpoint.apps import admission
+from dewpoint.apps import admission, cancels
 from dewpoint.apps.forms import form_fields
 from dewpoint.apps.inputs import INPUT_INVALID
 from dewpoint.core.authz.permissions import P
+from dewpoint.core.claims import service as claims
+from dewpoint.core.claims.cipher import ClaimCipher
 from dewpoint.core.claims.secret_index import SECRET_INDEX_LIMIT
-from dewpoint.core.crypto.keys import KeySource
+from dewpoint.core.crypto.keys import KeySource, key_unreadable
 from dewpoint.core.http import TenantContext, get_db, require
 from dewpoint.core.models.requests import RunRequest
+from dewpoint.core.models.runs import Run
 from dewpoint.core.models.workflows import Workflow, WorkflowVersion
+from dewpoint.engine.handles import NestingError, StoredClaim, resolve_value
 
 router = APIRouter(prefix="/api/v1", tags=["runs"])
 KEY_MAX = 255
 UNAVAILABLE = {admission.PRODUCTION_RUNS_DISABLED, admission.ENVIRONMENT_NOT_RECORDED, admission.NO_CURRENT_BUILD}
 INVALID = {INPUT_INVALID, SECRET_INDEX_LIMIT}
+INPUT_NOT_RETAINED = "input_not_retained"
 
 
 class StartIn(BaseModel):
@@ -34,6 +40,18 @@ class StartIn(BaseModel):
     mode: Literal["live", "simulate"] = "live"
 
 
+class RerunIn(BaseModel):
+    model_config = ConfigDict(extra="forbid")
+    mode: Literal["live", "simulate"] | None = None  # the old request's when not given
+
+
+def key_unusable(e: Exception) -> HTTPException:
+    """The tenant's key couldn't be read (`key_unreadable`): 503, the request recorded nothing. Anything else raises."""
+    if not key_unreadable(e):
+        raise e
+    return HTTPException(503, detail={"error": "key_unusable"})
+
+
 def get_keys(request: Request) -> KeySource:
     return request.app.state.keys  # type: ignore[no-any-return]
 
@@ -80,6 +98,8 @@ async def admit(
     except admission.AdmissionRefusedError as e:
         status = 503 if e.reason in UNAVAILABLE else 422 if e.reason in INVALID else 409
         raise HTTPException(status, detail={"error": e.reason, "messages": e.messages}) from None
+    except Exception as e:
+        raise key_unusable(e) from None
     return admitted.request
 
 
@@ -117,3 +137,73 @@ async def start_form(
         "fields": form_fields(version.input_schema or {}),
         "csv": None,
     }
+
+
+@router.post("/t/{tenant_id}/runs/{request_id}/cancel")
+async def cancel_run(
+    request_id: uuid.UUID,
+    response: Response,
+    ctx: TenantContext = Depends(require(P.RUN_CANCEL)),
+    db: AsyncSession = Depends(get_db, scope="function"),
+) -> dict[str, object]:
+    """200, `cancelled`: it was queued. 202, `requested`: recorded, for the dispatcher to apply when its start resolves
+    or to send to Temporal. 409 `run_ended`: nothing left to cancel."""
+    try:
+        happened = await cancels.cancel_request(
+            db, tenant_id=ctx.tenant_id, request_id=request_id, actor_id=ctx.user.id
+        )
+    except cancels.RequestNotFoundError:
+        raise HTTPException(404, detail={"error": "not_found"}) from None
+    if happened == "ended":
+        raise HTTPException(409, detail={"error": "run_ended"})
+    request = await db.get(RunRequest, request_id)
+    if request is None:
+        raise HTTPException(404, detail={"error": "not_found"})
+    response.status_code = 200 if happened == "cancelled" else 202
+    return {"cancel": happened, "request": request_body(request)}
+
+
+@router.post("/t/{tenant_id}/runs/{request_id}/rerun", status_code=202)
+async def rerun(
+    request_id: uuid.UUID,
+    body: RerunIn | None = None,
+    key: str = Depends(idempotency_key),
+    ctx: TenantContext = Depends(require(P.RUN_START)),
+    db: AsyncSession = Depends(get_db, scope="function"),
+    keys: KeySource = Depends(get_keys),
+) -> dict[str, object]:
+    """A new admission (source `rerun`) on the workflow's active version, with the old request's complete input,
+    validated and claimed again under the new request: no old handle is reused. 410 `input_not_retained` when it can't
+    be rebuilt: a run from before 2b-2, a refused request, an envelope or a claim retention has removed."""
+    old = await db.get(RunRequest, request_id)  # row-level security: the caller's tenant's only
+    if old is None:
+        if await db.get(Run, request_id) is not None:  # a run 2a started: no request, no envelope
+            raise HTTPException(410, detail={"error": INPUT_NOT_RETAINED})
+        raise HTTPException(404, detail={"error": "not_found"})
+    value = await original_input(db, keys, ctx.tenant_id, old)
+    mode = body.mode if body is not None and body.mode is not None else old.mode
+    start = StartIn(input=value, mode=mode)
+    return request_body(await admit(db, keys, ctx, old.workflow_id, "rerun", start, key))
+
+
+async def original_input(db: AsyncSession, keys: KeySource, tenant_id: uuid.UUID, old: RunRequest) -> dict[str, Any]:
+    """A request's complete input, held in memory only: its envelope read through its own reader and every handle in
+    it resolved, as the request that owns the claims (§7.7)."""
+    if old.envelope_id is None:  # refused: admission kept no envelope
+        raise HTTPException(410, detail={"error": INPUT_NOT_RETAINED})
+    cipher = ClaimCipher(keys)
+
+    async def fetch(claim_id: str) -> StoredClaim:
+        stored = await claims.read_request_claim(db, cipher, tenant_id, request_id=old.id, claim_id=uuid.UUID(claim_id))
+        return StoredClaim(stored.value, stored.sensitive_pointers)
+
+    try:
+        envelope = await claims.read_envelope(db, cipher, tenant_id, request_id=old.id)
+        resolved = await resolve_value(envelope, fetch)
+    except (claims.EnvelopeUnavailableError, claims.ClaimUnavailableError, NestingError):
+        raise HTTPException(410, detail={"error": INPUT_NOT_RETAINED}) from None
+    except Exception as e:
+        raise key_unusable(e) from None
+    if not isinstance(resolved.value, dict):
+        raise HTTPException(410, detail={"error": INPUT_NOT_RETAINED})
+    return resolved.value
diff --git a/backend/src/dewpoint/core/authz/permissions.py b/backend/src/dewpoint/core/authz/permissions.py
index dcc000d..49e4242 100644
--- a/backend/src/dewpoint/core/authz/permissions.py
+++ b/backend/src/dewpoint/core/authz/permissions.py
@@ -17,12 +17,13 @@ class P(StrEnum):
     WORKFLOW_DECLASSIFY = "workflow.declassify"  # publishing a version that lists declassified sites (2b §4.3)
     RUN_START = "run.start"
     RUN_VIEW = "run.view"
+    RUN_CANCEL = "run.cancel"  # a queued request at once, a running run through the dispatcher (2b §7.7)
     APPROVAL_DECIDE = "approval.decide"
     AGENT_GRANT = "agent.grant"
 
 
 _VIEWER = frozenset({P.TENANT_VIEW, P.WORKFLOW_VIEW, P.RUN_VIEW, P.CONNECTION_VIEW, P.MEMBER_VIEW})
-_OPERATOR = _VIEWER | {P.RUN_START, P.APPROVAL_DECIDE}
+_OPERATOR = _VIEWER | {P.RUN_START, P.RUN_CANCEL, P.APPROVAL_DECIDE}
 _EDITOR = _OPERATOR | {P.WORKFLOW_EDIT, P.WORKFLOW_PUBLISH, P.CONNECTION_USE}
 _ADMIN = _EDITOR | {
     P.TENANT_MANAGE,
diff --git a/backend/src/dewpoint/core/claims/service.py b/backend/src/dewpoint/core/claims/service.py
index 38cf19e..d81281e 100644
--- a/backend/src/dewpoint/core/claims/service.py
+++ b/backend/src/dewpoint/core/claims/service.py
@@ -217,3 +217,24 @@ async def read_envelope(s: AsyncSession, cipher: ClaimCipher, tenant_id: uuid.UU
         return json.loads(plain)
     except ValueError:  # not UTF-8, or not JSON
         raise EnvelopeUnreadableError("A trigger envelope that isn't JSON.") from None
+
+
+async def read_request_claim(
+    s: AsyncSession, cipher: ClaimCipher, tenant_id: uuid.UUID, *, request_id: uuid.UUID, claim_id: uuid.UUID
+) -> Stored:
+    """One of a request's own input claims, for a re-run rebuilding its input (engine 2b spec §7.7): in `run_inputs`,
+    owned by the request, never its envelope; nothing else is read. Raises ClaimUnavailableError, as `fetch` does."""
+    found = (
+        await s.execute(
+            select(InputClaim.sensitive_pointers, InputClaim.ciphertext).where(
+                InputClaim.id == claim_id, InputClaim.owner_run_id == request_id, InputClaim.role == "claim"
+            )
+        )
+    ).first()
+    if found is None:
+        raise ClaimUnavailableError("A claim this request doesn't own, or that doesn't exist.")
+    try:
+        plain = await cipher.open(str(tenant_id), str(claim_id), found.ciphertext)
+    except ClaimUnreadableError as e:
+        raise ClaimUnavailableError("A claim that doesn't open under its tenant.") from e
+    return Stored(json.loads(plain), tuple(found.sensitive_pointers))
diff --git a/backend/tests/apps/api/test_run_requests_api.py b/backend/tests/apps/api/test_run_requests_api.py
index 67be2e8..ec3875b 100644
--- a/backend/tests/apps/api/test_run_requests_api.py
+++ b/backend/tests/apps/api/test_run_requests_api.py
@@ -11,8 +11,13 @@ from typing import Any
 import pytest
 from sqlalchemy import text
 
+from dewpoint.core.claims import service as claims
+from dewpoint.core.claims.cipher import ClaimCipher
+from dewpoint.core.db import tenant_scope
+from dewpoint.core.runs import service as runs
+from dewpoint.engine.handles import StoredClaim, resolve_value
 from tests.apps.api.helpers import member_client
-from tests.apps.test_admission import KEYS, TOKEN, count, current, published
+from tests.apps.test_admission import KEYS, TOKEN, admit, count, current, published
 from tests.apps.test_workflow_ops import update
 from tests.support.graphs import G
 
@@ -185,3 +190,141 @@ async def test_a_workflow_without_an_active_version_has_no_start_form(
     client = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx)
     answer = await client.get(f"/api/v1/t/{ctx.tenant_id}/workflows/{wf}/start-form")
     assert (answer.status_code, answer.json()["error"]) == (409, "not_active")
+
+
+# --- cancel and re-run (§7.7) -----------------------------------------------------------------------------------------
+
+
+async def started_request(client: Any, ctx: Any, wf: uuid.UUID, key: str = "k1") -> dict[str, Any]:
+    answer = await client.post(runs_url(ctx, wf), json=BODY, headers={"Idempotency-Key": key})
+    assert answer.status_code == 202, answer.text
+    return answer.json()  # type: ignore[no-any-return]
+
+
+async def envelope_of(api: Any, ctx: Any, request_id: str) -> Any:
+    async with api() as s, s.begin():
+        await tenant_scope(s, ctx.tenant_id)
+        return await claims.read_envelope(s, ClaimCipher(KEYS), ctx.tenant_id, request_id=uuid.UUID(request_id))
+
+
+async def test_an_operator_cancels_a_queued_request_at_once(keyed_app, ready, owner_sessionmaker, api_settings) -> None:
+    ctx, wf = ready
+    client = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx)
+    request = await started_request(client, ctx, wf)
+    answer = await client.post(f"/api/v1/t/{ctx.tenant_id}/runs/{request['id']}/cancel")
+    assert answer.status_code == 200, answer.text
+    assert answer.json()["cancel"] == "cancelled"
+    assert (answer.json()["request"]["status"], answer.json()["request"]["reason"]) == ("cancelled", "user_cancelled")
+    again = await client.post(f"/api/v1/t/{ctx.tenant_id}/runs/{request['id']}/cancel")
+    assert (again.status_code, again.json()["error"]) == (409, "run_ended")
+
+
+async def test_a_starting_requests_cancel_is_recorded_for_the_dispatcher(
+    keyed_app, ready, owner_sessionmaker, dispatch_sessionmaker, api_settings
+) -> None:
+    from tests.apps.dispatcher.support import begin, workers
+
+    ctx, wf = ready
+    client = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx)
+    request = await started_request(client, ctx, wf)
+    await workers(owner_sessionmaker)
+    async with owner_sessionmaker() as s:
+        row = (await s.execute(text("select * from run_requests where id = :i"), {"i": request["id"]})).one()
+    assert (await begin(dispatch_sessionmaker, row, api_settings)).__class__.__name__ == "Starting"
+    answer = await client.post(f"/api/v1/t/{ctx.tenant_id}/runs/{request['id']}/cancel")
+    assert (answer.status_code, answer.json()["cancel"], answer.json()["request"]["status"]) == (
+        202, "requested", "starting",
+    )  # fmt: skip
+
+
+async def test_a_viewer_cant_cancel_and_an_unknown_request_isnt_found(
+    keyed_app, ready, owner_sessionmaker, api_settings
+) -> None:
+    ctx, wf = ready
+    operator = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx)
+    request = await started_request(operator, ctx, wf)
+    viewer = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "viewer")
+    assert (await viewer.post(f"/api/v1/t/{ctx.tenant_id}/runs/{request['id']}/cancel")).status_code == 403
+    unknown = await operator.post(f"/api/v1/t/{ctx.tenant_id}/runs/{uuid.uuid4()}/cancel")
+    assert (unknown.status_code, unknown.json()["error"]) == (404, "not_found")
+
+
+async def test_a_rerun_admits_the_complete_original_input_as_a_new_request_with_new_claims(
+    keyed_app, ready, owner_sessionmaker, api_sessionmaker, api_settings
+) -> None:
+    ctx, wf = ready
+    client = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx)
+    old = await started_request(client, ctx, wf)
+    answer = await client.post(f"/api/v1/t/{ctx.tenant_id}/runs/{old['id']}/rerun", headers={"Idempotency-Key": "r1"})
+    assert answer.status_code == 202, answer.text
+    new = answer.json()
+    assert new["id"] != old["id"] and (new["source"], new["status"], new["mode"]) == ("rerun", "queued", "live")
+    assert TOKEN not in answer.text
+    before, after = (
+        await envelope_of(api_sessionmaker, ctx, old["id"]),
+        await envelope_of(api_sessionmaker, ctx, new["id"]),
+    )
+    assert after["site"] == "a" and after["token"] != before["token"]  # claimed again: no old handle is reused
+    async with api_sessionmaker() as s, s.begin():
+        await tenant_scope(s, ctx.tenant_id)
+        token = await resolve_value(after["token"], fetcher(s, ctx, uuid.UUID(new["id"])))
+    assert token.value == TOKEN
+
+
+def fetcher(s: Any, ctx: Any, run_id: uuid.UUID) -> Any:
+    async def fetch(claim_id: str) -> StoredClaim:
+        stored = await claims.fetch(s, ClaimCipher(KEYS), ctx.tenant_id, run_id=run_id, claim_id=uuid.UUID(claim_id))
+        return StoredClaim(stored.value, stored.sensitive_pointers)
+
+    return fetch
+
+
+@pytest.mark.parametrize("gone", ["pre_2b2_run", "refused", "claim_removed"])
+async def test_a_rerun_whose_input_isnt_retained_is_410(
+    keyed_app, ready, owner_sessionmaker, api_sessionmaker, dispatch_sessionmaker, api_settings, gone
+) -> None:
+    ctx, wf = ready
+    client = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx)
+    if gone == "pre_2b2_run":  # a run 2a's start_run wrote: no request, no envelope
+        async with owner_sessionmaker() as s:
+            version = (
+                await s.execute(text("select active_version_id from workflows where id = :w"), {"w": wf})
+            ).scalar()
+        async with dispatch_sessionmaker() as s, s.begin():
+            await tenant_scope(s, ctx.tenant_id)
+            run = await runs.insert_run(s, run_id=uuid.uuid4(), tenant_id=ctx.tenant_id, workflow_id=wf,
+                                        version_id=version, mode="live")  # fmt: skip
+        target = str(run.id)
+    elif gone == "refused":  # a durable source's refusal keeps a request with no envelope
+        await update(api_sessionmaker, ctx, wf, enabled=False)
+        target = str((await admit(api_sessionmaker, ctx, wf, source="schedule")).request.id)
+        await update(api_sessionmaker, ctx, wf, enabled=True)
+    else:  # retention removed one of its claims
+        target = (await started_request(client, ctx, wf))["id"]
+        async with owner_sessionmaker() as s, s.begin():
+            await s.execute(text("delete from run_inputs where owner_run_id = :i and role = 'claim'"), {"i": target})
+    answer = await client.post(f"/api/v1/t/{ctx.tenant_id}/runs/{target}/rerun", headers={"Idempotency-Key": "r1"})
+    assert (answer.status_code, answer.json()["error"]) == (410, "input_not_retained")
+
+
+async def test_a_rerun_needs_an_idempotency_key_and_an_existing_request(
+    keyed_app, ready, owner_sessionmaker, api_settings
+) -> None:
+    ctx, wf = ready
+    client = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx)
+    old = await started_request(client, ctx, wf)
+    assert (await client.post(f"/api/v1/t/{ctx.tenant_id}/runs/{old['id']}/rerun")).status_code == 428
+    unknown = await client.post(
+        f"/api/v1/t/{ctx.tenant_id}/runs/{uuid.uuid4()}/rerun", headers={"Idempotency-Key": "r"}
+    )
+    assert (unknown.status_code, unknown.json()["error"]) == (404, "not_found")
+
+
+async def test_a_tenant_whose_key_cant_be_read_answers_503(keyed_app, ready, owner_sessionmaker, api_settings) -> None:
+    from tests.support.keys import FixtureKeys
+
+    ctx, wf = ready
+    keyed_app.state.keys = FixtureKeys(missing={str(ctx.tenant_id)})
+    client = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx)
+    answer = await client.post(runs_url(ctx, wf), json=BODY, headers={"Idempotency-Key": "k1"})
+    assert (answer.status_code, answer.json()) == (503, {"error": "key_unusable"})
diff --git a/backend/tests/core/requests/test_envelope.py b/backend/tests/core/requests/test_envelope.py
index 1f701bc..b4dd2f9 100644
--- a/backend/tests/core/requests/test_envelope.py
+++ b/backend/tests/core/requests/test_envelope.py
@@ -83,3 +83,26 @@ async def test_the_database_holds_no_envelope_in_plain_text(owner_sessionmaker,
             await s.execute(text("select ciphertext, pointer, role from run_inputs where id = :e"), {"e": envelope})
         ).one()
     assert b"site" not in row.ciphertext and (row.pointer, row.role) == (None, "envelope")
+
+
+async def test_a_reruns_reader_reads_only_its_requests_own_input_claims(
+    owner_sessionmaker, dispatch_sessionmaker, api_sessionmaker
+) -> None:
+    """The re-run's reader (§7.7), as the API role: a claim the request owns in `run_inputs`; never its envelope,
+    another run's claim, or anything outside `run_inputs`."""
+    tenant, request, envelope = await admitted(owner_sessionmaker, dispatch_sessionmaker)
+    mine, others = uuid.uuid4(), uuid.uuid4()
+    async with dispatch_sessionmaker() as s, s.begin():
+        await tenant_scope(s, tenant)
+        await service.write_input(s, CIPHER, tenant, service.NewClaim(mine, "t0ken", ("",), request, request),
+                                  pointer="/token")  # fmt: skip
+        stranger = uuid.uuid4()
+        await service.write_input(s, CIPHER, tenant, service.NewClaim(others, "x", ("",), stranger, stranger),
+                                  pointer="/token")  # fmt: skip
+    async with api_sessionmaker() as s, s.begin():
+        await tenant_scope(s, tenant)
+        stored = await service.read_request_claim(s, CIPHER, tenant, request_id=request, claim_id=mine)
+        assert (stored.value, stored.sensitive_pointers) == ("t0ken", ("",))
+        for claim_id in (envelope, others, uuid.uuid4()):
+            with pytest.raises(service.ClaimUnavailableError):
+                await service.read_request_claim(s, CIPHER, tenant, request_id=request, claim_id=claim_id)
```

### Task 24: The runs list shows requests and runs together by (queued_at, id)

**Commit:** `710e3b1` (prototype `proto/2b2-v2`); the replay's tree was identical: yes.

**Modify:** `backend/src/dewpoint/apps/api/routes/runs.py`, `backend/src/dewpoint/core/runs/service.py`, `backend/tests/apps/api/test_runs_api.py`

**What it does:**

GET /t/{tid}/runs lists top-level runs and requests that haven't
started in one stable order, newest first by (queued_at, id); the paired
cursor is now before = the last item's queued_at, with before_id. A run
from before 2b-2 has no request; a started request's item is its run,
with the request's status, source and reason; a request that hasn't
started (queued, starting, cancelled, refused, dead) is shown as itself,
never as the row an attempt pre-created (§7.3), in the list and in GET
/runs/{id}.


- [ ] **Step 1: its tests alone, before its code.** Run: `uv run pytest -n 4 tests/apps/api/test_runs_api.py`. Replay result (exit 1), shortened:

```
security, not by bypassing it (engine 2b spec §6.3, plan 2b-1a's review)
§14; revision 7)
dispatcher
/private/tmp/claude-501/-Users-tmunzer-4-dev-mist-dewpoint/1e3145a1-199e-4b31-be1b-1e3bfd266be7/scratchpad/2b2-plan/replay/backend/tests/apps/api/test_runs_api.py:78: AssertionError: assert ['6778403e-68...91a091c34df9'] == ['97172477-cd...91a091c34df9']
[gw0] darwin -- Python 3.14.7 /private/tmp/claude-501/-Users-tmunzer-4-dev-mist-dewpoint/1e3145a1-199e-4b31-be1b-1e3bfd266be7/scratchpad/2b2-plan/proto/backend/.venv/bin/python
E   AssertionError: assert [('7d72169f-9...nning', None)] == [('7d72169f-9...ueued', None)]
      At index 0 diff: ('7d72169f-9fd0-47cf-82ac-96e8096d7484', 'running', None) != ('7d72169f-9fd0-47cf-82ac-96e8096d7484', 'queued', None)
      Use -v to get more diff
/private/tmp/claude-501/-Users-tmunzer-4-dev-mist-dewpoint/1e3145a1-199e-4b31-be1b-1e3bfd266be7/scratchpad/2b2-plan/replay/backend/tests/apps/api/test_runs_api.py:99: AssertionError: assert [('7d72169f-9...nning', None)] == [('7d72169f-9...ueued', None)]
=========================== short test summary info ============================
FAILED tests/apps/api/test_runs_api.py::test_the_runs_list_pages_past_runs_that_started_in_the_same_instant
FAILED tests/apps/api/test_runs_api.py::test_requests_and_runs_are_listed_together_newest_first
FAILED tests/apps/api/test_runs_api.py::test_a_request_that_never_started_is_shown_as_its_request_never_as_its_row
3 failed, 2 passed in 11.27s
```

- [ ] **Step 2: its code, then the same tests.** Replay result (exit 0), shortened:

```
.....                                                                    [100%]
5 passed in 11.23s
```

- [ ] **Step 3: commit.** `git cherry-pick --no-commit 710e3b1 && git commit -C 710e3b1`

The diff:

```diff
diff --git a/backend/src/dewpoint/apps/api/routes/runs.py b/backend/src/dewpoint/apps/api/routes/runs.py
index e4471e4..d2aff70 100644
--- a/backend/src/dewpoint/apps/api/routes/runs.py
+++ b/backend/src/dewpoint/apps/api/routes/runs.py
@@ -1,7 +1,8 @@
 # SPDX-License-Identifier: Apache-2.0
-"""Runs, read-only (spec §8): the list of top-level runs, and one run with its steps and the sub-runs it started (its
-sub-flows and failure handler). The UI reads this projection, never Temporal history. Starting runs isn't public
-until 2b."""
+"""Runs, read-only (spec §8; engine 2b spec §7.7): requests and top-level runs listed together, and one with its steps
+and the sub-runs it started (its sub-flows and failure handler). The UI reads this projection, never Temporal history.
+A request that hasn't started is shown as its request, never as the row an attempt pre-created. Starting a run is
+`run_requests`'s."""
 
 import uuid
 from datetime import datetime
@@ -11,6 +12,7 @@ from sqlalchemy.ext.asyncio import AsyncSession
 
 from dewpoint.core.authz.permissions import P
 from dewpoint.core.http import TenantContext, get_db, require
+from dewpoint.core.models.requests import RunRequest
 from dewpoint.core.models.runs import Run, RunStep
 from dewpoint.core.runs import service
 
@@ -21,6 +23,47 @@ def _when(value: datetime | None) -> str | None:
     return value.isoformat() if value else None
 
 
+def _request(r: RunRequest | None) -> dict[str, object] | None:
+    return {"status": r.status, "source": r.source, "reason": r.reason} if r is not None else None
+
+
+def _item(i: service.Listed) -> dict[str, object]:
+    return {
+        "id": str(i.id),
+        "workflow_id": str(i.workflow_id),
+        "version_id": str(i.version_id) if i.version_id else None,
+        "mode": i.mode,
+        "status": i.status,
+        "queued_at": _when(i.queued_at),
+        "started_at": _when(i.started_at),
+        "ended_at": _when(i.ended_at),
+        "error": {"code": i.error_code, "message": i.error_message} if i.error_code else None,
+        "iterations": i.iterations,
+        "kind": i.kind,
+        "parent_run_id": None,
+        "request": {"status": i.request_status, "source": i.source, "reason": i.reason} if i.request_status else None,
+    }
+
+
+def _unstarted(r: RunRequest) -> dict[str, object]:
+    """A request that hasn't started, as the list shows it: its own status, no run yet."""
+    return {
+        "id": str(r.id),
+        "workflow_id": str(r.workflow_id),
+        "version_id": str(r.workflow_version_id) if r.workflow_version_id else None,
+        "mode": r.mode,
+        "status": r.status,
+        "queued_at": _when(r.queued_at),
+        "started_at": None,
+        "ended_at": _when(r.ended_at),
+        "error": None,
+        "iterations": 0,
+        "kind": "run",
+        "parent_run_id": None,
+        "request": _request(r),
+    }
+
+
 def _run(r: Run) -> dict[str, object]:
     return {
         "id": str(r.id),
@@ -28,6 +71,7 @@ def _run(r: Run) -> dict[str, object]:
         "version_id": str(r.workflow_version_id),
         "mode": r.mode,
         "status": r.status,
+        "queued_at": _when(r.queued_at),
         "started_at": _when(r.started_at),
         "ended_at": _when(r.ended_at),
         "error": {"code": r.error_code, "message": r.error_message} if r.error_code else None,
@@ -71,13 +115,14 @@ async def list_runs(
     ctx: TenantContext = Depends(require(P.RUN_VIEW)),
     db: AsyncSession = Depends(get_db, scope="function"),
 ) -> list[dict[str, object]]:
-    """Newest first. The next page: `before` and `before_id`, the last run's `started_at` and `id`, always together:
-    runs can start in the same instant, so the time alone would skip some."""
+    """Requests and runs, newest first by `(queued_at, id)`. The next page: `before` and `before_id`, the last item's
+    `queued_at` and `id`, always together: items can be queued in the same instant, so the time alone would skip
+    some."""
     if (before is None) != (before_id is None):
         raise HTTPException(422, detail={"error": "invalid_cursor", "message": "Give before and before_id together."})
     cursor = (before, before_id) if before is not None and before_id is not None else None
-    runs = await service.list_runs(db, workflow_id=workflow_id, before=cursor, limit=limit)
-    return [_run(r) for r in runs]
+    items = await service.list_items(db, workflow_id=workflow_id, before=cursor, limit=limit)
+    return [_item(i) for i in items]
 
 
 @router.get("/t/{tenant_id}/runs/{run_id}")
@@ -86,11 +131,15 @@ async def get_run(
     ctx: TenantContext = Depends(require(P.RUN_VIEW)),
     db: AsyncSession = Depends(get_db, scope="function"),
 ) -> dict[str, object]:
+    request = await db.get(RunRequest, run_id)  # row-level security: the caller's tenant's only
+    if request is not None and request.status != "started":
+        return {**_unstarted(request), "steps": [], "children": []}
     run = await service.get_run(db, run_id)
     if run is None or run.tenant_id != ctx.tenant_id:
         raise HTTPException(404, detail={"error": "not_found"})
     return {
         **_run(run),
+        "request": _request(request),
         "steps": [_step(r) for r in await service.run_steps(db, run.id)],
         "children": [_child(c) for c in await service.children(db, run.id)],
     }
diff --git a/backend/src/dewpoint/core/runs/service.py b/backend/src/dewpoint/core/runs/service.py
index 1758b1f..48ecb8a 100644
--- a/backend/src/dewpoint/core/runs/service.py
+++ b/backend/src/dewpoint/core/runs/service.py
@@ -7,13 +7,15 @@ import math
 import re
 import uuid
 from collections.abc import Iterable, Mapping
+from dataclasses import dataclass
 from datetime import datetime
 from typing import Any
 
-from sqlalchemy import func, select, tuple_, update
+from sqlalchemy import func, literal, null, or_, select, tuple_, union_all, update
 from sqlalchemy.dialects.postgresql import insert
 from sqlalchemy.ext.asyncio import AsyncSession
 
+from dewpoint.core.models.requests import RunRequest
 from dewpoint.core.models.runs import Run, RunStep
 
 MESSAGE_LIMIT = 500
@@ -214,6 +216,64 @@ async def list_runs(
     return list((await s.execute(q)).scalars())
 
 
+@dataclass(frozen=True)
+class Listed:
+    """One item of the runs list (engine 2b spec §7.7): a top-level run, or a request that hasn't started. `status` is
+    the run's once its request started (or when it has none, from before 2b-2), else the request's."""
+
+    id: uuid.UUID
+    workflow_id: uuid.UUID
+    version_id: uuid.UUID | None
+    mode: str
+    status: str
+    queued_at: datetime
+    started_at: datetime | None
+    ended_at: datetime | None
+    error_code: str | None
+    error_message: str | None
+    iterations: int
+    kind: str
+    request_status: str | None
+    source: str | None
+    reason: str | None
+
+
+async def list_items(
+    s: AsyncSession,
+    *,
+    workflow_id: uuid.UUID | None = None,
+    before: tuple[datetime, uuid.UUID] | None = None,
+    limit: int = 50,
+) -> list[Listed]:
+    """Requests and runs together, newest first by `(queued_at, id)`; the next page starts after the last item of this
+    one. A request's pre-created row is never shown until its request has started (§7.3): the request is."""
+    runs = (
+        select(
+            Run.id, Run.workflow_id, Run.workflow_version_id.label("version_id"), Run.mode, Run.status, Run.queued_at,
+            Run.started_at, Run.ended_at, Run.error_code, Run.error_message, Run.iterations, Run.kind,
+            RunRequest.status.label("request_status"), RunRequest.source, RunRequest.reason,
+        )
+        .outerjoin(RunRequest, RunRequest.id == Run.id)
+        .where(Run.parent_run_id.is_(None), or_(RunRequest.id.is_(None), RunRequest.status == "started"))
+    )  # fmt: skip
+    requests = select(
+        RunRequest.id, RunRequest.workflow_id, RunRequest.workflow_version_id.label("version_id"), RunRequest.mode,
+        RunRequest.status, RunRequest.queued_at, null().label("started_at"), RunRequest.ended_at,
+        null().label("error_code"), null().label("error_message"), literal(0).label("iterations"),
+        literal("run").label("kind"), RunRequest.status.label("request_status"), RunRequest.source, RunRequest.reason,
+    ).where(RunRequest.status != "started")  # fmt: skip
+    if workflow_id is not None:
+        runs, requests = (
+            runs.where(Run.workflow_id == workflow_id),
+            requests.where(RunRequest.workflow_id == workflow_id),
+        )
+    both = union_all(runs, requests).subquery()
+    q = select(both).order_by(both.c.queued_at.desc(), both.c.id.desc()).limit(limit)
+    if before is not None:
+        q = q.where(tuple_(both.c.queued_at, both.c.id) < tuple_(*before))
+    return [Listed(**row._mapping) for row in await s.execute(q)]
+
+
 async def children(s: AsyncSession, run_id: uuid.UUID) -> list[Run]:
     """The sub-runs a run started, in the order they started."""
     q = select(Run).where(Run.parent_run_id == run_id).order_by(Run.started_at, Run.id)
diff --git a/backend/tests/apps/api/test_runs_api.py b/backend/tests/apps/api/test_runs_api.py
index b7b115a..5fc0611 100644
--- a/backend/tests/apps/api/test_runs_api.py
+++ b/backend/tests/apps/api/test_runs_api.py
@@ -1,14 +1,21 @@
 # SPDX-License-Identifier: Apache-2.0
-"""`GET /runs` pages by (start time, id): `before` and `before_id` name the last run of the previous page, and go
-together."""
+"""`GET /runs` (engine 2b spec §7.7) lists requests and runs together, newest first by one stable key, `(queued_at,
+id)`: a request's `queued_at` is when it was created, its run shares its id and `queued_at`, and a run from before 2b
+got `queued_at = started_at`. `before` and `before_id` name the last item of the previous page, and go together. A
+request that never started is shown as its request, never as the row an attempt pre-created (§7.3)."""
 
 import uuid
+from typing import Any
 
 import pytest
+from sqlalchemy import text
 
+from dewpoint.apps.dispatcher import dispatch
 from dewpoint.core.db import tenant_scope
 from dewpoint.core.runs import service
 from tests.apps.api.helpers import member_client
+from tests.apps.dispatcher.support import begin, workers
+from tests.apps.test_admission import TOKEN, admit, current, published
 from tests.apps.test_workflow_ops import actor
 from tests.support.workflows import seed_workflow
 
@@ -27,7 +34,7 @@ async def test_the_runs_list_pages_past_runs_that_started_in_the_same_instant(
     viewer, _ = await member_client(app, owner_sessionmaker, api_settings, ctx.tenant_id, "viewer")
     first = (await viewer.get(f"/api/v1/t/{ctx.tenant_id}/runs", params={"limit": 2})).json()
     last = first[-1]
-    params = {"limit": 2, "before": last["started_at"], "before_id": last["id"]}
+    params = {"limit": 2, "before": last["queued_at"], "before_id": last["id"]}
     rest = (await viewer.get(f"/api/v1/t/{ctx.tenant_id}/runs", params=params)).json()
     assert len({r["id"] for r in first + rest}) == 3
 
@@ -41,3 +48,62 @@ async def test_half_a_cursor_is_refused(app, owner_sessionmaker, api_settings, h
     response = await viewer.get(f"/api/v1/t/{ctx.tenant_id}/runs", params={half: value})
     assert response.status_code == 422
     assert response.json()["error"] == "invalid_cursor"
+
+
+async def listed(app: Any, owner: Any, settings: Any, ctx: Any) -> tuple[Any, list[dict[str, Any]]]:
+    viewer, _ = await member_client(app, owner, settings, ctx.tenant_id, "viewer")
+    answer = await viewer.get(f"/api/v1/t/{ctx.tenant_id}/runs")
+    assert answer.status_code == 200, answer.text
+    return viewer, answer.json()
+
+
+@pytest.mark.usefixtures("development_deployment")
+async def test_requests_and_runs_are_listed_together_newest_first(
+    app, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings
+) -> None:
+    ctx, wf = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings)
+    await current(dispatch_sessionmaker)
+    await workers(owner_sessionmaker)
+    async with owner_sessionmaker() as s:
+        version = (await s.execute(text("select active_version_id from workflows where id = :w"), {"w": wf})).scalar()
+    async with dispatch_sessionmaker() as s, s.begin():  # a run 2a started: no request
+        await tenant_scope(s, ctx.tenant_id)
+        old = await service.insert_run(s, run_id=uuid.uuid4(), tenant_id=ctx.tenant_id, workflow_id=wf,
+                                       version_id=version, mode="live")  # fmt: skip
+    first = (await admit(api_sessionmaker, ctx, wf, key="a")).request
+    starting = await begin(dispatch_sessionmaker, first, api_settings)
+    assert await dispatch.settle(dispatch_sessionmaker, starting, dispatch.Outcome("started")) == "started"
+    queued = (await admit(api_sessionmaker, ctx, wf, key="b")).request
+    _, items = await listed(app, owner_sessionmaker, api_settings, ctx)
+    assert [i["id"] for i in items] == [str(queued.id), str(first.id), str(old.id)]
+    assert (items[0]["status"], items[0]["started_at"], items[0]["request"]) == (
+        "queued", None, {"status": "queued", "source": "manual", "reason": None},
+    )  # fmt: skip
+    assert (items[1]["status"], items[1]["request"]["status"]) == ("running", "started")
+    assert items[1]["started_at"] is not None and items[1]["queued_at"] == first.queued_at.isoformat()
+    assert items[2]["request"] is None and items[2]["queued_at"] == items[2]["started_at"]
+    assert TOKEN not in str(items)
+
+
+@pytest.mark.usefixtures("development_deployment")
+async def test_a_request_that_never_started_is_shown_as_its_request_never_as_its_row(
+    app, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings
+) -> None:
+    ctx, wf = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings)
+    await current(dispatch_sessionmaker)
+    await workers(owner_sessionmaker)
+    request = (await admit(api_sessionmaker, ctx, wf)).request
+    starting = await begin(dispatch_sessionmaker, request, api_settings)
+    assert await dispatch.settle(dispatch_sessionmaker, starting, dispatch.Outcome("refused")) == "refused"
+    viewer, items = await listed(app, owner_sessionmaker, api_settings, ctx)  # its pre-created row is `running`
+    assert [(i["id"], i["status"], i["started_at"]) for i in items] == [(str(request.id), "queued", None)]
+    detail = (await viewer.get(f"/api/v1/t/{ctx.tenant_id}/runs/{request.id}")).json()
+    assert (detail["status"], detail["steps"], detail["children"]) == ("queued", [], [])
+    async with owner_sessionmaker() as s, s.begin():  # its backoff over
+        await s.execute(text("update run_requests set next_attempt_at = now() where id = :i"), {"i": request.id})
+    starting = await begin(dispatch_sessionmaker, request, api_settings)
+    _, items = await listed(app, owner_sessionmaker, api_settings, ctx)
+    assert items[0]["status"] == "starting"
+    assert await dispatch.settle(dispatch_sessionmaker, starting, dispatch.Outcome("collision")) == "dead"
+    _, items = await listed(app, owner_sessionmaker, api_settings, ctx)
+    assert (items[0]["status"], items[0]["request"]["reason"]) == ("dead", "id_collision")
```

### Task 25: `dewpoint dev run` admits a workflow and waits for its recorded end

**Commit:** `8456f2d` (prototype `proto/2b2-v2`); the replay's tree was identical: yes.

**Create:** `backend/src/dewpoint/apps/dev_run.py`

**Modify:** `backend/src/dewpoint/apps/cli/main.py`, `backend/tests/apps/cli/test_deployment_cli.py`, `backend/tests/apps/cli/test_dev_run_cli.py`, `backend/tests/apps/worker/test_dev_run.py`

**What it does:**

dewpoint dev run WORKFLOW_ID admits the active version with the source
dev, as the dispatch role, with a new idempotency key per invocation
unless one is given; the dispatcher starts it. --wait SECONDS is bounded
and reports the end the database records: the request's own when it
never started (cancelled, refused, dead), else its run's. Exit 0
admitted or succeeded, 1 ended otherwise, 2 not admitted, 3 the wait ran
out. The command no longer talks to Temporal, and no command exposes
start_run, which stays a test helper.


- [ ] **Step 1: its tests alone, before its code.** Run: `uv run pytest -n 4 tests/apps/cli/test_deployment_cli.py tests/apps/cli/test_dev_run_cli.py tests/apps/worker/test_dev_run.py`. Replay result (exit 1), shortened:

```
ImportError while importing test module '/private/tmp/claude-501/-Users-tmunzer-4-dev-mist-dewpoint/1e3145a1-199e-4b31-be1b-1e3bfd266be7/scratchpad/2b2-plan/replay/backend/tests/apps/worker/test_dev_run.py'.
Hint: make sure your test modules/packages have valid Python names.
Traceback:
/opt/homebrew/Cellar/python@3.14/3.14.7/Frameworks/Python.framework/Versions/3.14/lib/python3.14/importlib/__init__.py:88: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
tests/apps/worker/test_dev_run.py:11: in <module>
    from dewpoint.apps import admission, dev_run
E   ImportError: cannot import name 'dev_run' from 'dewpoint.apps' (/private/tmp/claude-501/-Users-tmunzer-4-dev-mist-dewpoint/1e3145a1-199e-4b31-be1b-1e3bfd266be7/scratchpad/2b2-plan/replay/backend/src/dewpoint/apps/__init__.py)
=========================== short test summary info ============================
ERROR tests/apps/cli/test_deployment_cli.py - ImportError while importing tes...
ERROR tests/apps/cli/test_dev_run_cli.py - ImportError while importing test m...
ERROR tests/apps/worker/test_dev_run.py - ImportError while importing test mo...
3 errors in 5.78s
```

- [ ] **Step 2: its code, then the same tests.** Replay result (exit 0), shortened:

```
.................                                                        [100%]
17 passed in 13.79s
```

- [ ] **Step 3: commit.** `git cherry-pick --no-commit 8456f2d && git commit -C 8456f2d`

The diff:

```diff
diff --git a/backend/src/dewpoint/apps/cli/main.py b/backend/src/dewpoint/apps/cli/main.py
index 6ef0e97..4d8fbd8 100644
--- a/backend/src/dewpoint/apps/cli/main.py
+++ b/backend/src/dewpoint/apps/cli/main.py
@@ -6,7 +6,6 @@ import os
 import uuid
 from collections.abc import AsyncIterator, Awaitable, Callable
 from contextlib import asynccontextmanager
-from dataclasses import asdict
 from datetime import timedelta
 from pathlib import Path
 
@@ -16,18 +15,18 @@ from sqlalchemy import select
 from sqlalchemy.ext.asyncio import AsyncSession
 from temporalio.client import Client
 
+from dewpoint.apps import admission, dev_run
 from dewpoint.apps.codec import KeyringKeys, data_converter
 from dewpoint.apps.dispatcher.dispatch import START_DEADLINE
 from dewpoint.apps.dispatcher.gate import disable_and_wait
 from dewpoint.apps.environment import verify_environment
 from dewpoint.apps.plugin_loader import PluginLoadError, installed_plugins, prepare
-from dewpoint.apps.runs import NotAdmissibleError, StartRefusedError, StartUncertainError, start_run
 from dewpoint.apps.worker.deployment import Deployment, describe, set_current, this_build
 from dewpoint.apps.worker.health import WorkerUnhealthyError
 from dewpoint.apps.worker.main import run as run_worker
 from dewpoint.core.audit.anchor import FileAnchorSink, anchor_all, anchor_freshness, verify_anchors
 from dewpoint.core.auth.users import PasswordPolicyError, create_user
-from dewpoint.core.config import Settings, get_settings
+from dewpoint.core.config import get_settings
 from dewpoint.core.crypto.kek import KekSet, UnknownKekError
 from dewpoint.core.crypto.keyring import Keyring
 from dewpoint.core.db import make_engine, make_sessionmaker
@@ -44,9 +43,6 @@ from dewpoint.core.plugins.registry import (
 )
 from dewpoint.core.tenancy.service import NotKeyAdminError, ensure_tenant_keys
 from dewpoint.engine.cel.profile import CURRENT_CEL_PROFILE
-from dewpoint.engine.runtime.activities import LIVE, SIMULATE, RunResult
-from dewpoint.engine.runtime.ids import run_workflow_id
-from dewpoint.engine.runtime.workflow import RunGraph
 from dewpoint.sdk import ManifestError
 
 app = typer.Typer(no_args_is_help=True)
@@ -487,76 +483,56 @@ def deployment_status() -> None:
         typer.echo(f"{v.build_id}  {v.status}")
 
 
-async def dev_run_version(
-    settings: Settings,
-    client: Client,
-    *,
-    tenant_id: uuid.UUID,
-    version_id: uuid.UUID,
-    trigger: dict[str, object],
-    simulate: bool = False,
-    wait: bool = True,
-) -> tuple[uuid.UUID, RunResult | None]:
-    engine = make_engine(settings.database_url)
-    try:
-        run_id = await start_run(
-            make_sessionmaker(engine),
-            client,
-            settings,
-            tenant_id=tenant_id,
-            version_id=version_id,
-            trigger=trigger,
-            mode=SIMULATE if simulate else LIVE,
-        )
-    finally:
-        await engine.dispose()
-    if not wait:
-        return run_id, None
-    return run_id, await client.get_workflow_handle_for(
-        RunGraph.run, run_workflow_id(str(tenant_id), str(run_id))
-    ).result()
-
-
 @dev_cli.command("run")
-def dev_run(
-    version_id: uuid.UUID,
+def dev_run_command(
+    workflow_id: uuid.UUID,
     tenant: str = typer.Option(..., "--tenant", help="tenant id"),
-    input_file: str | None = typer.Option(None, "--input", help="JSON trigger payload (test data only until 2b)"),
+    input_file: str | None = typer.Option(None, "--input", help="JSON input for the active version"),
     simulate: bool = typer.Option(False, "--simulate", help="Plugin steps call simulate(): nothing is sent"),
-    wait: bool = typer.Option(True, "--wait/--no-wait"),
+    wait: float = typer.Option(0.0, "--wait", help="seconds to wait for the end the database records (0: don't)"),
+    idempotency_key: str | None = typer.Option(None, "--idempotency-key", help="retry a request (default: a new one)"),
 ) -> None:
-    """Start a run of a workflow's active version. Development only: 2b brings admission and triggers."""
-    trigger = json.loads(Path(input_file).read_text()) if input_file else {}
-    if not isinstance(trigger, dict):  # a run's trigger is an object: anything else could never start
+    """Admit a run of a workflow's active version (source `dev`); the dispatcher starts it. Run as dewpoint_dispatch.
+    Exit 0 when admitted (or, with --wait, when the run succeeded), 1 when it ended otherwise, 2 when it wasn't
+    admitted, 3 when the wait ran out."""
+    payload = json.loads(Path(input_file).read_text()) if input_file else {}
+    if not isinstance(payload, dict):  # a run's input is an object: anything else could never start
         typer.echo("ERROR: --input must hold a JSON object")
         raise typer.Exit(2)
+    settings = get_settings()
+    tenant_id = uuid.UUID(tenant)
 
-    async def _go() -> tuple[uuid.UUID, RunResult | None]:
-        async with _temporal() as client:
-            return await dev_run_version(
-                get_settings(),
-                client,
-                tenant_id=uuid.UUID(tenant),
-                version_id=version_id,
-                trigger=trigger,
-                simulate=simulate,
-                wait=wait,
-            )
+    async def _go() -> tuple[uuid.UUID, dev_run.Ended | None]:
+        engine = make_engine(settings.database_url)
+        try:
+            sessionmaker = make_sessionmaker(engine)
+            keys = KeyringKeys(sessionmaker, Keyring(KekSet.from_settings(settings)))
+            request = await dev_run.admit(
+                sessionmaker, keys, tenant_id=tenant_id, workflow_id=workflow_id, input=payload, simulate=simulate,
+                idempotency_key=idempotency_key or str(uuid.uuid4()),
+            )  # fmt: skip
+            if wait <= 0:
+                return request.id, None
+            return request.id, await dev_run.wait_for_end(sessionmaker, tenant_id, request.id, within=wait)
+        finally:
+            await engine.dispose()
 
     try:
-        run_id, result = asyncio.run(_go())
-    except NotAdmissibleError as e:
-        for reason in e.reasons:
-            typer.echo(f"ERROR: {reason}")
+        request_id, end = asyncio.run(_go())
+    except admission.AdmissionRefusedError as e:
+        for message in e.messages:
+            typer.echo(f"ERROR: {message}")
         raise typer.Exit(2) from None
-    except StartRefusedError as e:
-        typer.echo(f"ERROR: {e}")
-        raise typer.Exit(1) from None
-    except StartUncertainError as e:
-        typer.echo(f"WARNING: {e}")
-        raise typer.Exit(3) from None
-    typer.echo(f"run {run_id}")
-    if result is not None:
-        typer.echo(json.dumps(asdict(result), indent=2, sort_keys=True))
-        if result.status != "succeeded":
-            raise typer.Exit(1)
+    except (admission.WorkflowNotFoundError, admission.IdempotencyConflictError) as e:
+        typer.echo(f"ERROR: {e or type(e).__name__}")
+        raise typer.Exit(2) from None
+    if wait <= 0:
+        typer.echo(f"request {request_id} queued")
+        return
+    if end is None:
+        typer.echo(f"WARNING: request {request_id} hasn't ended after {wait:g} s")
+        raise typer.Exit(3)
+    detail = ": ".join(part for part in (end.code, end.message) if part)
+    typer.echo(f"{end.what} {request_id} {end.status}" + (f": {detail}" if detail else ""))
+    if (end.what, end.status) != ("run", "succeeded"):
+        raise typer.Exit(1)
diff --git a/backend/src/dewpoint/apps/dev_run.py b/backend/src/dewpoint/apps/dev_run.py
new file mode 100644
index 0000000..6a23d35
--- /dev/null
+++ b/backend/src/dewpoint/apps/dev_run.py
@@ -0,0 +1,76 @@
+# SPDX-License-Identifier: Apache-2.0
+"""The dev CLI's run (engine 2b spec §7.7): it admits a workflow's active version with the source `dev`, in its own
+transaction, as the dispatch role, and the dispatcher starts it like any other request. Its wait is bounded and
+reports the end the database records (the request's, when it never started; else its run's), not merely a start."""
+
+import asyncio
+import uuid
+from dataclasses import dataclass
+from typing import Any
+
+from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
+
+from dewpoint.apps import admission
+from dewpoint.core.crypto.keys import KeySource
+from dewpoint.core.db import tenant_scope
+from dewpoint.core.models.requests import RunRequest
+from dewpoint.core.models.runs import Run
+from dewpoint.engine.runtime.activities import LIVE, SIMULATE
+
+ENDED = ("cancelled", "refused", "dead")  # a request's own ends: it never started
+
+
+@dataclass(frozen=True)
+class Ended:
+    """What ended: the `request` (it never started) with its status and reason, or its `run`, with its own."""
+
+    what: str
+    status: str
+    code: str | None
+    message: str | None
+
+
+async def admit(
+    sessionmaker: async_sessionmaker[AsyncSession], keys: KeySource, *, tenant_id: uuid.UUID, workflow_id: uuid.UUID,
+    input: dict[str, Any], simulate: bool, idempotency_key: str,
+) -> RunRequest:  # fmt: skip
+    """The request, queued. Raises admission's errors, AdmissionRefusedError with its reason and messages first."""
+    async with sessionmaker() as s, s.begin():
+        admitted = await admission.admit_request(
+            s, keys, tenant_id=tenant_id, workflow_id=workflow_id, source="dev", actor_id=None,
+            mode=SIMULATE if simulate else LIVE, idempotency_key=idempotency_key, input=input,
+        )  # fmt: skip
+        return admitted.request
+
+
+async def ended(
+    sessionmaker: async_sessionmaker[AsyncSession], tenant_id: uuid.UUID, request_id: uuid.UUID
+) -> Ended | None:
+    """The end the database records for a request, or None while it's queued, starting or running."""
+    async with sessionmaker() as s, s.begin():
+        await tenant_scope(s, tenant_id)
+        request = await s.get(RunRequest, request_id)
+        if request is None:
+            raise LookupError("No such run request.")
+        if request.status in ENDED:
+            return Ended("request", request.status, request.reason, None)
+        if request.status != "started":
+            return None
+        run = await s.get(Run, request_id)
+        if run is None or run.status == "running":
+            return None
+        return Ended("run", run.status, run.error_code, run.error_message)
+
+
+async def wait_for_end(
+    sessionmaker: async_sessionmaker[AsyncSession], tenant_id: uuid.UUID, request_id: uuid.UUID, *, within: float,
+    poll: float = 0.5,
+) -> Ended | None:  # fmt: skip
+    """The recorded end, looked for until `within` seconds have passed; None if there's none by then."""
+    loop = asyncio.get_running_loop()
+    until = loop.time() + within
+    while True:
+        found = await ended(sessionmaker, tenant_id, request_id)
+        if found is not None or loop.time() >= until:
+            return found
+        await asyncio.sleep(poll)
diff --git a/backend/tests/apps/cli/test_deployment_cli.py b/backend/tests/apps/cli/test_deployment_cli.py
index 0f2b9d0..b38a19f 100644
--- a/backend/tests/apps/cli/test_deployment_cli.py
+++ b/backend/tests/apps/cli/test_deployment_cli.py
@@ -15,7 +15,23 @@ from dewpoint.engine.runtime.build import build_id
 from tests.apps.cli.test_dev_run_cli import cli_env  # noqa: F401  (a fixture)
 
 
-@pytest.mark.usefixtures("cli_env")
+class _Client:
+    @staticmethod
+    async def connect(*args: Any, **kwargs: Any) -> "_Client":
+        return _Client()
+
+
+async def _recorded(*args: Any) -> None:
+    """A deployment whose record matches: the CLI's Temporal commands check it before connecting (2b spec §2.1)."""
+
+
+@pytest.fixture
+def temporal_stand_in(cli_env: None, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
+    monkeypatch.setattr(cli, "Client", _Client)
+    monkeypatch.setattr(cli, "verify_environment", _recorded)  # the check itself: tests/apps/test_environment.py
+
+
+@pytest.mark.usefixtures("temporal_stand_in")
 def test_set_current_defaults_to_this_build(monkeypatch: pytest.MonkeyPatch) -> None:
     seen: list[tuple[str, float]] = []
 
@@ -31,7 +47,7 @@ def test_set_current_defaults_to_this_build(monkeypatch: pytest.MonkeyPatch) ->
     assert seen == [(this, 60.0), ("b-2", 5.0)]
 
 
-@pytest.mark.usefixtures("cli_env")
+@pytest.mark.usefixtures("temporal_stand_in")
 def test_status_lists_every_version(monkeypatch: pytest.MonkeyPatch) -> None:
     async def describe(client: Any) -> Deployment:
         return Deployment("b-2", [Version("b-1", "draining"), Version("b-2", "current")])
diff --git a/backend/tests/apps/cli/test_dev_run_cli.py b/backend/tests/apps/cli/test_dev_run_cli.py
index ff54ece..131800f 100644
--- a/backend/tests/apps/cli/test_dev_run_cli.py
+++ b/backend/tests/apps/cli/test_dev_run_cli.py
@@ -1,31 +1,24 @@
 # SPDX-License-Identifier: Apache-2.0
-"""`dewpoint dev run`'s exit codes: 0 when the run succeeded, 1 when it ended otherwise or Temporal refused it, 2 when
-it wasn't admitted, 3 when Temporal never confirmed the start. The run itself is covered by
-tests/apps/worker/test_dev_run.py; here Temporal and the run are stand-ins."""
+"""`dewpoint dev run` (engine 2b spec §7.7): it admits a workflow with the source `dev` and, with `--wait`, waits a
+bounded time for the end the database records. Exit codes: 0 admitted (or, waited, the run succeeded), 1 it ended
+otherwise, 2 it wasn't admitted, 3 the wait ran out. The path itself is covered by tests/apps/worker/test_dev_run.py;
+here admission and the wait are stand-ins. No command starts a run itself."""
 
 import base64
 import json
 import uuid
 from pathlib import Path
+from types import SimpleNamespace
 from typing import Any
 
 import pytest
-from temporalio.converter import DefaultFailureConverterWithEncodedAttributes
 from typer.testing import CliRunner
 
+from dewpoint.apps import admission, dev_run
 from dewpoint.apps.cli import main as cli
-from dewpoint.apps.codec import TenantCodec
-from dewpoint.apps.runs import NotAdmissibleError, StartRefusedError, StartUncertainError
 from dewpoint.core.config import get_settings
-from dewpoint.engine.runtime.activities import RunResult
 
-RUN = uuid.UUID(int=7)
-
-
-class _Client:
-    @staticmethod
-    async def connect(*args: Any, **kwargs: Any) -> "_Client":
-        return _Client()
+REQUEST = uuid.UUID(int=7)
 
 
 @pytest.fixture
@@ -33,110 +26,90 @@ def cli_env(monkeypatch: pytest.MonkeyPatch) -> None:
     monkeypatch.setenv("DEWPOINT_DATABASE_URL", "postgresql+asyncpg://nobody@localhost/none")
     monkeypatch.setenv("DEWPOINT_KEK_B64", base64.b64encode(b"k" * 32).decode())
     monkeypatch.setenv("DEWPOINT_PUBLIC_ORIGIN", "https://dewpoint.test")
-    monkeypatch.setattr(cli, "Client", _Client)
-    monkeypatch.setattr(cli, "verify_environment", _recorded)  # the check itself: tests/apps/test_environment.py
     get_settings.cache_clear()
 
 
-async def _recorded(*args: Any) -> None:
-    """A deployment whose record matches: the CLI's Temporal commands check it before connecting (2b spec §2.1)."""
+def answer(monkeypatch: pytest.MonkeyPatch, admitted: Any, ended: Any, seen: dict[str, Any]) -> None:
+    async def admit(sessionmaker: Any, keys: Any, **kwargs: Any) -> Any:
+        seen.update(kwargs)
+        if isinstance(admitted, Exception):
+            raise admitted
+        return SimpleNamespace(id=REQUEST, status="queued")
+
+    async def wait_for_end(sessionmaker: Any, tenant_id: Any, request_id: Any, *, within: float, **_: Any) -> Any:
+        seen["within"] = within
+        return ended
 
+    monkeypatch.setattr(dev_run, "admit", admit)
+    monkeypatch.setattr(dev_run, "wait_for_end", wait_for_end)
 
-def _answer(monkeypatch: pytest.MonkeyPatch, outcome: RunResult | Exception, seen: dict[str, Any]) -> None:
-    async def dev_run_version(settings: Any, client: Any, **kwargs: Any) -> tuple[uuid.UUID, RunResult | None]:
-        seen.update(kwargs)
-        if isinstance(outcome, Exception):
-            raise outcome
-        return RUN, outcome if kwargs["wait"] else None
 
-    monkeypatch.setattr(cli, "dev_run_version", dev_run_version)
+def run(*args: str) -> Any:
+    return CliRunner().invoke(cli.app, ["dev", "run", str(uuid.UUID(int=1)), "--tenant", str(uuid.UUID(int=2)), *args])
 
 
 @pytest.mark.usefixtures("cli_env")
-def test_a_succeeded_run_prints_its_result(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
+def test_without_wait_it_prints_the_queued_request(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
     seen: dict[str, Any] = {}
-    _answer(monkeypatch, RunResult("succeeded", {"v": 2}), seen)
-    payload = tmp_path / "trigger.json"
+    answer(monkeypatch, None, None, seen)
+    payload = tmp_path / "input.json"
     payload.write_text(json.dumps({"x": 1}))
-    tenant, version = uuid.uuid4(), uuid.uuid4()
-    result = CliRunner().invoke(
-        cli.app, ["dev", "run", str(version), "--tenant", str(tenant), "--input", str(payload), "--simulate"]
-    )
-    assert result.exit_code == 0, result.output
-    assert f"run {RUN}" in result.output and '"status": "succeeded"' in result.output
-    assert seen == {"tenant_id": tenant, "version_id": version, "trigger": {"x": 1}, "simulate": True, "wait": True}
+    result = run("--input", str(payload), "--simulate", "--idempotency-key", "k1")
+    assert (result.exit_code, result.output) == (0, f"request {REQUEST} queued\n")
+    assert seen == {"tenant_id": uuid.UUID(int=2), "workflow_id": uuid.UUID(int=1), "input": {"x": 1},
+                    "simulate": True, "idempotency_key": "k1"}  # fmt: skip
 
 
 @pytest.mark.usefixtures("cli_env")
-def test_a_run_that_did_not_succeed_exits_1(monkeypatch: pytest.MonkeyPatch) -> None:
-    _answer(monkeypatch, RunResult("failed", error={"code": "workflow_failed", "message": "no"}), {})
-    result = CliRunner().invoke(cli.app, ["dev", "run", str(uuid.uuid4()), "--tenant", str(uuid.uuid4())])
-    assert result.exit_code == 1 and '"code": "workflow_failed"' in result.output
-
-
-@pytest.mark.usefixtures("cli_env")
-def test_a_refused_run_exits_2_with_its_reasons(monkeypatch: pytest.MonkeyPatch) -> None:
-    _answer(monkeypatch, NotAdmissibleError(["the workflow is disabled"]), {})
-    result = CliRunner().invoke(cli.app, ["dev", "run", str(uuid.uuid4()), "--tenant", str(uuid.uuid4())])
-    assert result.exit_code == 2 and "ERROR: the workflow is disabled" in result.output
+@pytest.mark.parametrize(
+    ("ended", "code", "said"),
+    [
+        (dev_run.Ended("run", "succeeded", None, None), 0, f"run {REQUEST} succeeded"),
+        (dev_run.Ended("run", "failed", "workflow_failed", "no"), 1, f"run {REQUEST} failed: workflow_failed: no"),
+        (dev_run.Ended("request", "dead", "start_refused", None), 1, f"request {REQUEST} dead: start_refused"),
+        (None, 3, f"WARNING: request {REQUEST} hasn't ended after 5 s"),
+    ],
+    ids=["succeeded", "failed", "dead", "wait_ran_out"],
+)
+def test_waiting_reports_the_end_the_database_records(
+    monkeypatch: pytest.MonkeyPatch, ended: Any, code: int, said: str
+) -> None:
+    seen: dict[str, Any] = {}
+    answer(monkeypatch, None, ended, seen)
+    result = run("--wait", "5")
+    assert result.exit_code == code and said in result.output and seen["within"] == 5.0
 
 
 @pytest.mark.usefixtures("cli_env")
-def test_no_wait_prints_only_the_run_id(monkeypatch: pytest.MonkeyPatch) -> None:
-    _answer(monkeypatch, RunResult("succeeded"), {})
-    args = ["dev", "run", str(uuid.uuid4()), "--tenant", str(uuid.uuid4()), "--no-wait"]
-    result = CliRunner().invoke(cli.app, args)
-    assert (result.exit_code, result.output.strip()) == (0, f"run {RUN}")
+def test_a_refused_admission_exits_2_with_its_reasons(monkeypatch: pytest.MonkeyPatch) -> None:
+    answer(monkeypatch, admission.AdmissionRefusedError("workflow_disabled", ["The workflow is disabled."]), None, {})
+    result = run()
+    assert result.exit_code == 2 and "ERROR: The workflow is disabled." in result.output
 
 
 @pytest.mark.usefixtures("cli_env")
-@pytest.mark.parametrize(
-    ("error", "code", "said"),
-    [
-        (StartRefusedError("Temporal refused the run (INVALID_ARGUMENT)."), 1, "ERROR: Temporal refused the run"),
-        (StartUncertainError(RUN), 3, f"WARNING: Temporal didn't confirm or refuse run {RUN}"),
-    ],
-)
-def test_a_start_temporal_refused_or_never_confirmed(
-    monkeypatch: pytest.MonkeyPatch, error: Exception, code: int, said: str
-) -> None:
-    _answer(monkeypatch, error, {})
-    result = CliRunner().invoke(cli.app, ["dev", "run", str(uuid.uuid4()), "--tenant", str(uuid.uuid4())])
-    assert result.exit_code == code and said in result.output
+def test_each_invocation_gets_its_own_idempotency_key_unless_given(monkeypatch: pytest.MonkeyPatch) -> None:
+    seen: dict[str, Any] = {}
+    answer(monkeypatch, None, None, seen)
+    run()
+    first = seen["idempotency_key"]
+    run()
+    assert first and seen["idempotency_key"] != first
 
 
 @pytest.mark.usefixtures("cli_env")
 @pytest.mark.parametrize("payload", ["[1, 2]", '"text"', "3"])
-def test_an_input_that_isnt_a_json_object_is_refused_before_anything_starts(
+def test_an_input_that_isnt_a_json_object_is_refused_before_admission(
     monkeypatch: pytest.MonkeyPatch, tmp_path: Path, payload: str
 ) -> None:
-    """2a-3a's final review, M4: a trigger that isn't an object (a list, a string) left the run failing its first
-    workflow task forever, so it hung. The CLI refuses it."""
     seen: dict[str, Any] = {}
-    _answer(monkeypatch, RunResult("succeeded", {}), seen)
-    trigger = tmp_path / "trigger.json"
+    answer(monkeypatch, None, None, seen)
+    trigger = tmp_path / "input.json"
     trigger.write_text(payload)
-    result = CliRunner().invoke(
-        cli.app, ["dev", "run", str(uuid.uuid4()), "--tenant", str(uuid.uuid4()), "--input", str(trigger)]
-    )
+    result = run("--input", str(trigger))
     assert (result.exit_code, result.output) == (2, "ERROR: --input must hold a JSON object\n") and seen == {}
 
 
-@pytest.mark.usefixtures("cli_env")
-def test_the_cli_connects_with_the_tenant_codec(monkeypatch: pytest.MonkeyPatch) -> None:
-    """Engine 2b spec §6.2: the dev CLI's start and its result go through the codec, failures too."""
-    connected: dict[str, Any] = {}
-
-    class Recording(_Client):
-        @staticmethod
-        async def connect(*args: Any, **kwargs: Any) -> "_Client":
-            connected.update(kwargs)
-            return _Client()
-
-    monkeypatch.setattr(cli, "Client", Recording)
-    _answer(monkeypatch, RunResult("succeeded", {}), {})
-    result = CliRunner().invoke(cli.app, ["dev", "run", str(uuid.uuid4()), "--tenant", str(uuid.uuid4())])
-    assert result.exit_code == 0, result.output
-    converter = connected["data_converter"]
-    assert isinstance(converter.payload_codec, TenantCodec)
-    assert converter.failure_converter_class is DefaultFailureConverterWithEncodedAttributes
+def test_no_command_starts_a_run_itself() -> None:
+    """2b-2: every packaged start goes through admission and the dispatcher; `start_run` is a test helper."""
+    assert "start_run" not in vars(cli) and "dev_run_version" not in vars(cli)
diff --git a/backend/tests/apps/worker/test_dev_run.py b/backend/tests/apps/worker/test_dev_run.py
index 6d64f8c..4c76628 100644
--- a/backend/tests/apps/worker/test_dev_run.py
+++ b/backend/tests/apps/worker/test_dev_run.py
@@ -1,24 +1,25 @@
 # SPDX-License-Identifier: Apache-2.0
-"""`dev_run_version` (spec §9): the dev CLI's path, through the dispatch role, to a run of the active version."""
+"""`dewpoint dev run`'s path (engine 2b spec §7.7): the dev CLI admits a workflow's active version with the source
+`dev`, as the dispatch role; the dispatcher starts it; the CLI's bounded wait reports the end the database records, not
+merely that it started. No command starts a run itself: `start_run` is a test helper."""
 
 from typing import Any
 
 import pytest
 from temporalio.testing import WorkflowEnvironment
 
-from dewpoint.apps.cli.main import dev_run_version
+from dewpoint.apps import admission, dev_run
+from dewpoint.apps.dispatcher.dispatch import dispatch_once
 from dewpoint.apps.worker.store import DbRunStore
-from dewpoint.engine.handles import ClaimRef
-from dewpoint.engine.runtime.ids import run_workflow_id
-from tests.apps.test_workflow_ops import actor, create, publish
+from tests.apps.dispatcher.support import BUILD
+from tests.apps.dispatcher.support import workers as ready_workers
+from tests.apps.test_admission import KEYS, current
+from tests.apps.test_workflow_ops import actor, create, publish, update
 from tests.apps.worker.harness import workers
-from tests.conftest import _url_for
 from tests.support.graphs import G, cel, ref
-from tests.support.keys import FixtureKeys
 from tests.support.registry import sync_test_plugins
 
-# its run starts on the time-skipping server, in a development deployment (engine 2b spec §2.3)
-pytestmark = pytest.mark.usefixtures("this_build_is_current", "development_deployment")
+pytestmark = pytest.mark.usefixtures("development_deployment")
 
 
 def graph() -> dict[str, Any]:
@@ -30,27 +31,60 @@ def graph() -> dict[str, Any]:
     return g.node("a", "testkit.echo@1", {"value": cel("trigger.x + 1")}).data()
 
 
-async def test_dev_run_starts_the_active_version(
-    env: WorkflowEnvironment,
-    pg_url: str,
-    owner_sessionmaker: Any,
-    api_sessionmaker: Any,
-    admin_sessionmaker: Any,
-    worker_sessionmaker: Any,
-    api_settings: Any,
-) -> None:
+@pytest.fixture
+async def workflow(
+    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings
+) -> Any:
     await sync_test_plugins(admin_sessionmaker)
     ctx = await actor(owner_sessionmaker)
-    out = await publish(api_sessionmaker, ctx, await create(api_sessionmaker, ctx, graph()), api_settings)
-    assert out.version is not None
-    settings = api_settings.model_copy(update={"database_url": _url_for(pg_url, "dewpoint_dispatch")})
-    common: dict[str, Any] = {"tenant_id": ctx.tenant_id, "version_id": out.version.id, "trigger": {"x": 1}}
-    async with workers(env.client, DbRunStore(worker_sessionmaker, FixtureKeys())):
-        _, waited = await dev_run_version(settings, env.client, **common)
-        _, simulated = await dev_run_version(settings, env.client, simulate=True, **common)
-        started, nothing = await dev_run_version(settings, env.client, wait=False, **common)
-        await env.client.get_workflow_handle(run_workflow_id(str(ctx.tenant_id), str(started))).result()
-    assert waited is not None and (waited.status, waited.outputs) == ("succeeded", {"v": 2})
-    assert simulated is not None and simulated.outputs is not None
-    assert ClaimRef.of(simulated.outputs["v"]) is not None  # an echo's output is undeclared: claimed whole (C1)
-    assert nothing is None
+    wf = await create(api_sessionmaker, ctx, graph())
+    assert (await publish(api_sessionmaker, ctx, wf, api_settings)).version is not None
+    await current(dispatch_sessionmaker)
+    await ready_workers(owner_sessionmaker)
+    return ctx, wf
+
+
+async def test_dev_run_admits_the_workflow_and_waits_for_the_end_the_database_records(
+    env: WorkflowEnvironment, workflow, dispatch_sessionmaker, worker_sessionmaker, api_settings
+) -> None:
+    ctx, wf = workflow
+    request = await dev_run.admit(dispatch_sessionmaker, KEYS, tenant_id=ctx.tenant_id, workflow_id=wf,
+                                  input={"x": 1}, simulate=False, idempotency_key="d1")  # fmt: skip
+    assert (request.source, request.status, request.mode) == ("dev", "queued", "live")
+    assert await dev_run.wait_for_end(dispatch_sessionmaker, ctx.tenant_id, request.id, within=0) is None
+    async with workers(env.client, DbRunStore(worker_sessionmaker, KEYS)):
+        assert await dispatch_once(dispatch_sessionmaker, env.client, KEYS, api_settings, BUILD) == {"started": 1}
+        ended = await dev_run.wait_for_end(dispatch_sessionmaker, ctx.tenant_id, request.id, within=30, poll=0.1)
+    assert ended == dev_run.Ended("run", "succeeded", None, None)
+
+
+async def test_dev_run_simulates_when_asked(workflow, dispatch_sessionmaker) -> None:
+    ctx, wf = workflow
+    request = await dev_run.admit(dispatch_sessionmaker, KEYS, tenant_id=ctx.tenant_id, workflow_id=wf,
+                                  input={"x": 1}, simulate=True, idempotency_key="d2")  # fmt: skip
+    assert (request.source, request.mode) == ("dev", "simulate")
+
+
+async def test_a_dev_run_admission_refuses_says_why(workflow, api_sessionmaker, dispatch_sessionmaker) -> None:
+    ctx, wf = workflow
+    await update(api_sessionmaker, ctx, wf, enabled=False)
+    with pytest.raises(admission.AdmissionRefusedError) as refused:
+        await dev_run.admit(dispatch_sessionmaker, KEYS, tenant_id=ctx.tenant_id, workflow_id=wf, input={"x": 1},
+                            simulate=False, idempotency_key="d3")  # fmt: skip
+    assert refused.value.reason == "workflow_disabled"
+
+
+async def test_a_request_that_ends_without_starting_reports_its_own_end(
+    workflow, dispatch_sessionmaker, api_settings
+) -> None:
+    from tests.apps.dispatcher.support import begin
+
+    ctx, wf = workflow
+    request = await dev_run.admit(dispatch_sessionmaker, KEYS, tenant_id=ctx.tenant_id, workflow_id=wf,
+                                  input={"x": 1}, simulate=False, idempotency_key="d4")  # fmt: skip
+    from dewpoint.apps.dispatcher import dispatch
+
+    starting = await begin(dispatch_sessionmaker, request, api_settings)
+    assert await dispatch.settle(dispatch_sessionmaker, starting, dispatch.Outcome("collision")) == "dead"
+    ended = await dev_run.wait_for_end(dispatch_sessionmaker, ctx.tenant_id, request.id, within=0)
+    assert ended == dev_run.Ended("request", "dead", "id_collision", None)
```

### Task 26: The dispatcher in Compose, a development override, and the operations docs for admission

**Commit:** `79c8c5f` (prototype `proto/2b2-v2`); the replay's tree was identical: yes.

**Create:** `deploy/compose/docker-compose.dev.yml`

**Modify:** `.github/workflows/ci.yml`, `README.md`, `backend/tests/deploy/test_compose.py`, `deploy/compose/docker-compose.yml`, `docs/operations/deployment.md`, `docs/operations/runs.md`

**What it does:**

Compose runs dewpoint dispatcher as dewpoint_dispatch_login, after the
migrate step and a healthy Temporal, with a stop grace longer than a
start's deadline. docker-compose.dev.yml records development (engine 2b
spec §2.1) and changes nothing else; CI's e2e job uses it for every
compose command (COMPOSE_FILE). Plain Compose stays production, gated.

docs/operations/runs.md: starting a run through the API and the start
form, the dispatcher and its reconciler, cancels and re-runs, the new
dev run, and the runs list's new (queued_at, id) order and cursor.
deployment.md: the dispatcher among Temporal's clients, turning
production runs off, Compose's dispatcher and development override.


- [ ] **Step 1: its tests alone, before its code.** Run: `uv run pytest -n 4 tests/deploy/test_compose.py`. Replay result (exit 1), shortened:

```
dispatcher
/private/tmp/claude-501/-Users-tmunzer-4-dev-mist-dewpoint/1e3145a1-199e-4b31-be1b-1e3bfd266be7/scratchpad/2b2-plan/replay/backend/tests/deploy/test_compose.py:42: KeyError: 'dispatcher'
[gw0] darwin -- Python 3.14.7 /private/tmp/claude-501/-Users-tmunzer-4-dev-mist-dewpoint/1e3145a1-199e-4b31-be1b-1e3bfd266be7/scratchpad/2b2-plan/proto/backend/.venv/bin/python
E   FileNotFoundError: [Errno 2] No such file or directory: '/private/tmp/claude-501/-Users-tmunzer-4-dev-mist-dewpoint/1e3145a1-199e-4b31-be1b-1e3bfd266be7/scratchpad/2b2-plan/replay/deploy/compose/docker-compose.dev.yml'
/opt/homebrew/Cellar/python@3.14/3.14.7/Frameworks/Python.framework/Versions/3.14/lib/python3.14/pathlib/__init__.py:771: FileNotFoundError: [Errno 2] No such file or directory: '/private/tmp/claude-501/-Users-tmunzer-4-dev-mist-dewpoint/1e3145a1-199e-4b31-be1b-1e3bfd266be7/scratchpad/2b2-plan/replay/deploy/compose/docker-compose.dev.yml'
[gw1] darwin -- Python 3.14.7 /private/tmp/claude-501/-Users-tmunzer-4-dev-mist-dewpoint/1e3145a1-199e-4b31-be1b-1e3bfd266be7/scratchpad/2b2-plan/proto/backend/.venv/bin/python
E   KeyError: 'env'
/private/tmp/claude-501/-Users-tmunzer-4-dev-mist-dewpoint/1e3145a1-199e-4b31-be1b-1e3bfd266be7/scratchpad/2b2-plan/replay/backend/tests/deploy/test_compose.py:99: KeyError: 'env'
=========================== short test summary info ============================
FAILED tests/deploy/test_compose.py::test_the_dispatcher_runs_as_the_dispatch_role_on_the_recorded_namespace
FAILED tests/deploy/test_compose.py::test_a_stopping_dispatcher_outlasts_a_starts_deadline
FAILED tests/deploy/test_compose.py::test_plain_compose_is_production_and_the_development_override_initializes_development
FAILED tests/deploy/test_compose.py::test_ci_runs_every_compose_command_with_the_development_override
4 failed, 2 passed in 10.45s
```

- [ ] **Step 2: its code, then the same tests.** Replay result (exit 0), shortened:

```
......                                                                   [100%]
6 passed in 10.31s
```

- [ ] **Step 3: commit.** `git cherry-pick --no-commit 79c8c5f && git commit -C 79c8c5f`

The diff:

```diff
diff --git a/.github/workflows/ci.yml b/.github/workflows/ci.yml
index ba4c78f..4c35327 100644
--- a/.github/workflows/ci.yml
+++ b/.github/workflows/ci.yml
@@ -72,6 +72,8 @@ jobs:
   e2e:
     runs-on: ubuntu-latest
     needs: [backend, frontend]
+    # A development deployment (engine 2b spec §2.1): every compose command below uses the override.
+    env: { COMPOSE_FILE: "docker-compose.yml:docker-compose.dev.yml" }
     steps:
       - uses: actions/checkout@v4
       - name: Write CI env
diff --git a/README.md b/README.md
index acd89a6..9d844ba 100644
--- a/README.md
+++ b/README.md
@@ -46,10 +46,11 @@ CEL expressions that can't run inline go to the `cel-evaluator` service: no secr
 
 ## Runs
 
-Until sub-project 2b brings triggers, runs start only from `dewpoint dev run` and the tests; `dewpoint worker` executes
-them on Temporal. Settings, how a run ends, and this build's limits:
+Runs are admitted through the run API (`POST /api/v1/t/{tenant}/workflows/{workflow}/runs`) or `dewpoint dev run`;
+`dewpoint dispatcher` starts them within each tenant's slots, and `dewpoint worker` executes them on Temporal.
+Settings, how a run ends, and this build's limits:
 [`docs/operations/runs.md`](docs/operations/runs.md). Compose runs Temporal's dev server (Web UI at
-<http://127.0.0.1:8233>) and one worker; rolling out a new build, and upgrading Compose:
+<http://127.0.0.1:8233>), one worker and one dispatcher; rolling out a new build, and upgrading Compose:
 [`docs/operations/deployment.md`](docs/operations/deployment.md).
 
 ## Audit integrity
diff --git a/backend/tests/deploy/test_compose.py b/backend/tests/deploy/test_compose.py
index 90c8f0e..29fe376 100644
--- a/backend/tests/deploy/test_compose.py
+++ b/backend/tests/deploy/test_compose.py
@@ -61,3 +61,39 @@ def test_the_migrate_step_gives_tenants_keys_as_the_key_admin() -> None:
     assert environment("migrate")["DEWPOINT_ADMIN_DATABASE_URL"] == (
         "postgresql+asyncpg://dewpoint_admin_login:admin-pw@postgres/dewpoint"
     )
+
+
+OVERRIDE = COMPOSE.with_name("docker-compose.dev.yml")
+CI = COMPOSE.parents[2] / ".github" / "workflows" / "ci.yml"
+
+
+def test_the_dispatcher_runs_as_the_dispatch_role_on_the_recorded_namespace() -> None:
+    """Engine 2b spec §7.3, §14: `dewpoint dispatcher` (with its reconciler) logs in as `dewpoint_dispatch`, and checks
+    the namespace the migrate step recorded before it connects to Temporal (§2.1)."""
+    dispatcher, env = service("dispatcher"), environment("dispatcher")
+    assert dispatcher["command"] == ["dewpoint", "dispatcher"]
+    assert env["DEWPOINT_DATABASE_URL"] == "postgresql+asyncpg://dewpoint_dispatch_login:dispatch-pw@postgres/dewpoint"
+    assert (env["DEWPOINT_TEMPORAL_ADDRESS"], env["DEWPOINT_TEMPORAL_NAMESPACE"]) == ("temporal:7233", "dewpoint-ci")
+    assert dispatcher["depends_on"]["migrate"] == {"condition": "service_completed_successfully"}
+    assert dispatcher["depends_on"]["temporal"] == {"condition": "service_healthy"}
+
+
+def test_a_stopping_dispatcher_outlasts_a_starts_deadline() -> None:
+    """A start in flight when the dispatcher is stopped gets its answer, or its deadline, before the process goes."""
+    from dewpoint.apps.dispatcher.dispatch import START_DEADLINE
+
+    grace = service("dispatcher")["stop_grace_period"]
+    assert grace.endswith("s") and int(grace[:-1]) > START_DEADLINE.total_seconds()
+
+
+def test_plain_compose_is_production_and_the_development_override_initializes_development() -> None:
+    """§2.1: ordinary Compose is `production`, and gated; CI and local development opt in through their own override,
+    which changes nothing else."""
+    assert environment("migrate")["DEWPOINT_ENVIRONMENT"] == "production"
+    override: dict[str, Any] = yaml.safe_load(OVERRIDE.read_text())
+    assert override["services"] == {"migrate": {"environment": {"DEWPOINT_ENVIRONMENT": "development"}}}
+
+
+def test_ci_runs_every_compose_command_with_the_development_override() -> None:
+    e2e = yaml.safe_load(CI.read_text())["jobs"]["e2e"]
+    assert e2e["env"]["COMPOSE_FILE"] == "docker-compose.yml:docker-compose.dev.yml"
diff --git a/deploy/compose/docker-compose.dev.yml b/deploy/compose/docker-compose.dev.yml
new file mode 100644
index 0000000..a6cd027
--- /dev/null
+++ b/deploy/compose/docker-compose.dev.yml
@@ -0,0 +1,11 @@
+# SPDX-License-Identifier: Apache-2.0
+# Development (engine 2b spec §2.1): CI and local work opt in with
+#   docker compose -f docker-compose.yml -f docker-compose.dev.yml up
+# on a database created for it (a Compose project's own volume) and its own Temporal namespace
+# (DEWPOINT_TEMPORAL_NAMESPACE). The migrate step then records `development`: runs start with no gate, and every
+# process that talks to Temporal refuses any other namespace. The label proves nothing about the data: synthetic
+# fixtures only. Plain Compose stays `production`, and gated.
+services:
+  migrate:
+    environment:
+      DEWPOINT_ENVIRONMENT: development
diff --git a/deploy/compose/docker-compose.yml b/deploy/compose/docker-compose.yml
index 8b36fcf..17d5ef8 100644
--- a/deploy/compose/docker-compose.yml
+++ b/deploy/compose/docker-compose.yml
@@ -122,6 +122,20 @@ services:
       temporal: { condition: service_healthy }
       cel-evaluator: { condition: service_healthy }
 
+  dispatcher:
+    <<: *app
+    # Starts admitted runs within each tenant's slots, and leads the reconciler when no other dispatcher does
+    # (engine 2b spec §7.3, §7.6; docs/operations/runs.md). The API admits runs but never talks to Temporal.
+    command: ["dewpoint", "dispatcher"]
+    environment:
+      <<: *appenv
+      DEWPOINT_DATABASE_URL: postgresql+asyncpg://dewpoint_dispatch_login:${DEWPOINT_DISPATCH_DB_PASSWORD}@postgres/dewpoint
+      DEWPOINT_TEMPORAL_ADDRESS: temporal:7233
+    stop_grace_period: 15s  # longer than a start's own deadline (10 s): a start in flight gets its answer
+    depends_on:
+      migrate: { condition: service_completed_successfully }
+      temporal: { condition: service_healthy }
+
   cel-evaluator:
     image: ${DEWPOINT_CEL_EVALUATOR_IMAGE:-dewpoint-cel-evaluator:dev}
     build: { context: ../.., dockerfile: deploy/docker/cel-evaluator.Dockerfile }
diff --git a/docs/operations/deployment.md b/docs/operations/deployment.md
index 7877035..cc63569 100644
--- a/docs/operations/deployment.md
+++ b/docs/operations/deployment.md
@@ -143,14 +143,26 @@ dewpoint platform init-environment --environment production --temporal-namespace
 
 - The defaults are `DEWPOINT_ENVIRONMENT` (else `production`) and `DEWPOINT_TEMPORAL_NAMESPACE` (else `default`).
   Running it again with the same values changes nothing; with other values it refuses: neither can change.
-- Every process that talks to Temporal — the worker and the CLI's Temporal commands — compares its configured
-  namespace with the record before it connects, and exits 2 when there's no record or it doesn't match. So a
+- Every process that talks to Temporal — the worker, the dispatcher and the CLI's Temporal commands — compares its
+  configured namespace with the record before it connects, and exits 2 when there's no record or it doesn't match. So a
   development database can't drive a namespace it wasn't set up for, and a production database can't either. The
   label proves nothing about the data: keep development's database and namespace apart from production's, with
   synthetic data only.
 - In `production`, no run starts until the production gate is lifted (sub-project 2b-4, after its readiness checks):
-  `dewpoint dev run` is refused, exit 2, with "Production runs are off in this deployment". In `development`, runs
-  start freely.
+  the run API answers 503 `production_runs_disabled` and `dewpoint dev run` exits 2, with "Production runs are off in
+  this deployment"; the dispatcher starts nothing, and queued requests wait. In `development`, runs start freely.
+
+### Turning production runs off
+
+```bash
+dewpoint platform disable-production-runs --wait 10
+```
+
+As `dewpoint_admin`, it turns the gate off at once, audited (`platform.production_runs.disable`): queued requests wait
+and started runs continue. It waits for any starting transaction to finish first, so no request becomes `starting`
+after it. Then it waits up to `--wait` seconds (the dispatcher's start deadline by default) for the starts already made
+to settle, and exits 3 with the ids of any still unresolved: the gate stays off, and the reconciler settles and audits
+them. No role turns the gate on outside 2b-4's command.
 
 ## Encrypted payloads
 
@@ -161,8 +173,8 @@ every run, a sub-flow and a failure handler included, and `t:<tenant>:run:<run i
 for a loop's batch. Temporal's Web UI shows ciphertext; what stays readable there is the ids, workflow and activity
 types, task queues, timestamps, and a local activity's own bookkeeping (its type and times).
 
-- The worker and `dewpoint dev run` need the KEK (`DEWPOINT_KEK_B64`, `DEWPOINT_KEK_ID`) and read tenants' data keys
-  through their database roles; they cache them for at most 5 minutes, and never longer, so a rotation reaches every
+- The worker, the dispatcher, the API and `dewpoint dev run` need the KEK (`DEWPOINT_KEK_B64`, `DEWPOINT_KEK_ID`) and
+  read tenants' data keys through their database roles; they cache them for at most 5 minutes, and never longer, so a rotation reaches every
   process within 5 minutes ([`key-rotation.md`](key-rotation.md)).
 - **Runs don't ride out a long database outage.** A key whose 5 minutes are up is read again, and while the database
   doesn't answer, it can't be: that tenant's payloads stop. An activity that starts or finishes then fails its
@@ -206,13 +218,19 @@ and reads each tenant's key the way the workers do, first.
 ## Docker Compose (evaluation)
 
 Compose runs Temporal's dev server (the `temporal` service: its state in SQLite on the `temporal-data` volume, its Web
-UI at <http://127.0.0.1:8233>) and one `worker`. Production uses a Temporal cluster instead.
+UI at <http://127.0.0.1:8233>), one `worker` and one `dispatcher`. Production uses a Temporal cluster instead.
 
 Its `migrate` service upgrades the schema, records the environment (`DEWPOINT_ENVIRONMENT`, `production` unless set)
 with the Temporal namespace (`DEWPOINT_TEMPORAL_NAMESPACE`, `default` unless set), and gives every tenant a data key as
 `dewpoint_admin_login`. Set the namespace in `.env`: every service takes it from there, and the worker exits 2 unless
-its own matches the record. Ordinary Compose is `production`, so no run starts; CI and local development set
-`DEWPOINT_ENVIRONMENT=development` through their own override, on a database of their own.
+its own matches the record. Ordinary Compose is `production`, so no run starts; CI and local development use the
+development override, on a database of their own (a project's own volume), with synthetic data only:
+
+```bash
+docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d
+```
+
+It records `development` (`DEWPOINT_ENVIRONMENT`); CI sets `COMPOSE_FILE` to both files.
 
 Compose runs one build at a time, so its worker makes its own build current as it starts
 (`DEWPOINT_WORKER_SET_CURRENT=true`). Replacing the `worker` container with a new image removes the old build's only
@@ -220,7 +238,7 @@ worker: **let runs end before upgrading**, or their build's worker must come bac
 image has a new engine ABI, publish every workflow again after upgrading (above). Leave the setting off wherever builds
 overlap.
 
-The worker and `dewpoint dev run` log in as `dewpoint_worker_login` and `dewpoint_dispatch_login`
+The worker, and the dispatcher and `dewpoint dev run`, log in as `dewpoint_worker_login` and `dewpoint_dispatch_login`
 (`DEWPOINT_WORKER_DB_PASSWORD`, `DEWPOINT_DISPATCH_DB_PASSWORD`). A fresh install creates both. An install whose
 database predates them creates them once, as the database owner:
 
diff --git a/docs/operations/runs.md b/docs/operations/runs.md
index 029b9a9..750cfee 100644
--- a/docs/operations/runs.md
+++ b/docs/operations/runs.md
@@ -1,15 +1,113 @@
-# Runs: the worker, development runs and the runs API
+# Runs: admission, the dispatcher, the worker and the runs API
 
 Spec: `docs/superpowers/specs/2026-09-25-engine-core-design.md` §6 (the interpreter), §8 (projection), §9 (starting
-runs), and `2026-09-29-engine-2b-design.md` §3–§5 (claims, taint, sizes).
+runs), and `2026-09-29-engine-2b-design.md` §3–§5 (claims, taint, sizes) and §7 (admission and dispatch).
 
 A run executes one published version of a workflow on Temporal. `RunGraph`, the interpreter, walks the graph: control
 nodes (`if`, `switch`, `loop`, …) run inside the workflow, and each attempt of a plugin step runs as an activity.
 Every step's progress is copied into the database (`run_steps`), which is what the UI reads; Temporal's own history is
 never shown.
 
-**2a runs are internal.** Only `dewpoint dev run` and the tests start runs. Triggers, schedules, webhooks and the
-public run API arrive with sub-project 2b, and so do admission control and idempotency keys.
+A run starts as a **request**: the run API and `dewpoint dev run` admit it, in their own transaction, and
+`dewpoint dispatcher` starts it on Temporal within its tenant's slots. Nothing else starts a run. Schedules, webhooks
+and CSV starts arrive with sub-project 2b-3.
+
+## Starting a run
+
+`POST /api/v1/t/{tenant}/workflows/{workflow}/runs`, with the `run.start` permission (operators and up), an
+`Idempotency-Key` header (at most 255 characters; without one, 428 `idempotency_key_required`) and the body
+`{"input": {...}, "mode": "live" | "simulate"}`, admits a request and answers 202 with it, `queued`. The API never
+talks to Temporal.
+
+- The same key with the same body returns the same request, as it is now; another body under the key is 409
+  `idempotency_conflict`. Retrying after a lost answer is safe.
+- Admission takes the workflow's active version, if the workflow is enabled, and freezes it in the request. It checks
+  the deployment's environment is recorded and, in `production`, that production runs are on; that the dispatcher
+  recorded a current build within the last 2 minutes, of the version's engine ABI; that nothing the version uses is
+  retired; and the input, against the version's input schema. Then it claims the input, as any run's
+  ([below](#sensitive-and-large-values-claims)), and keeps the request's input, with handles in place of its claimed
+  values, encrypted beside them (its trigger envelope).
+- A refusal answers with its code and fixed messages that never quote a value: 503 `production_runs_disabled`,
+  `environment_not_recorded`, `no_current_build` or `key_unusable` (the tenant's data key can't be read); 422
+  `input_invalid` or `secret_index_limit`, with each place and rule the input breaks; 409 `workflow_disabled`,
+  `not_active`, `version_unusable`, `node_type_retired`, `cel_profile_retired` or `tenant_erasing`; 404 for a workflow
+  that isn't the tenant's. A refused start leaves no request.
+
+`GET /api/v1/t/{tenant}/workflows/{workflow}/start-form` (`run.start`) describes the active version's input for a
+form: its typed top-level fields, each with its `type`, whether it's `required`, its `title`, `description`, `enum`
+and `default`, and `x-dewpoint-picker` as `picker`. A sensitive field never shows a value its schema holds:
+`default_masked` and `enum_masked` say there is one. 409 `not_active` without an active version.
+
+## The dispatcher
+
+`dewpoint dispatcher` starts admitted requests. Run one or more. It needs `DEWPOINT_DATABASE_URL` with a login in the
+`dewpoint_dispatch` role, `DEWPOINT_TEMPORAL_ADDRESS` and `DEWPOINT_TEMPORAL_NAMESPACE` (checked against the recorded
+namespace before it connects: exit 2 otherwise, [`deployment.md`](deployment.md)), and the KEK. Every second it:
+
+1. reads the current build from Temporal and records it, for admission's engine ABI check;
+2. picks each tenant's oldest due request (through `dispatch_candidates()`, which returns ids only) and, in one
+   transaction under the production gate's and the tenant's shared locks, checks again what must hold at a start:
+   - production runs on (in `production`), and the tenant not being erased;
+   - every live worker of the current build healthy, with every capability the build needs;
+   - nothing the frozen version uses retired, else the request is `cancelled` (`node_type_retired`,
+     `cel_profile_retired`), and the version of the build's engine ABI, else `cancelled` (`engine_abi_changed`);
+   - a free slot: a tenant runs at most `max_concurrent` top-level runs at once (`tenant_run_limits`, else the
+     platform's default, 5);
+   - the tenant's key: it opens the request's envelope and encrypts the start with it.
+
+   A check that doesn't hold leaves the request queued, no attempt counted: waiting isn't failing. An envelope that
+   doesn't open, or isn't JSON, makes the request `dead` (`envelope_unreadable`), audited; repairing a key never
+   reopens it: re-run it;
+3. reserves the slot, writes the run's row (`running`, no start time yet), marks the request `starting`, and starts the
+   workflow under its run's id, refusing a duplicate, with a 10-second deadline.
+
+What Temporal answers decides what follows:
+
+- accepted: `started`, and the run's start time recorded;
+- refused: back in the queue after 5 seconds, doubling up to 10 minutes; the 10th refusal makes it `dead`
+  (`start_refused`), audited, and its run `failed` with `start_failed`;
+- busy (`RESOURCE_EXHAUSTED`), or the start couldn't be encrypted: back in the queue, no attempt counted;
+- already started: it counts only once the execution's own start decodes to this request; anything else is an id
+  collision, which the server-built ids make impossible: `dead` (`id_collision`), with an alert;
+- no answer: it stays `starting`, its slot held, for the reconciler.
+
+The root run's end write releases its slot. A failure the dispatcher can't classify is logged (`dispatch_failed`, its
+type only) and leaves that request as it was; the cycle goes on with the other tenants. Each instance records its
+last cycle in `dispatcher_reports`.
+
+### The reconciler
+
+One dispatcher at a time also leads the reconciler (an advisory lock held on a connection of its own; another takes
+over when it goes). It asks Temporal about each request at most once every 30 seconds:
+
+- **A request still `starting` 30 seconds after it became so.** An execution found is verified as above, and the
+  request is `started`. A `NOT_FOUND` from a namespace that answers puts it back in the queue, no attempt counted,
+  with a warning, but only while its run's row is still `running` and its slot still held: when its row records an end
+  or its slot is gone, its end write ran, and it's left `starting` with an error (`start_history_missing`) for an
+  operator. Any other answer leaves it `starting`; still so 10 minutes on, an error (`start_unresolved`). Each one it
+  settles is audited (`run.request.reconciled`).
+- **A started run whose row is still `running`,** once Temporal says the logical run's latest execution closed:
+  completed records the run's own result; cancelled, `cancelled`; terminated, `failed` with `terminated`; failed or
+  timed out, `failed` with `internal_error`, and an alert. Its slot is released in the same transaction. This is how a
+  run whose end write was lost, or refused, ends.
+- **A slot whose run's row has ended:** released once its execution is closed.
+- **History Temporal no longer has**, for a started run or a held slot: left as it is, with an error
+  (`run_history_missing`, `slot_history_missing`); no outcome is invented and no slot released. Recover it by hand.
+- **Cancels:** it sends each recorded cancel to Temporal, once.
+
+## Cancelling and re-running
+
+`POST /api/v1/t/{tenant}/runs/{id}/cancel`, with `run.cancel` (operators and up), names a request (its id is also its
+run's): a queued request is cancelled at once, 200 `cancelled` (reason `user_cancelled`), audited; a starting request
+or a running run has its cancel recorded, 202 `requested`, audited once: the dispatcher applies it when the start
+doesn't happen, or sends it to Temporal and the run ends `cancelled`. 409 `run_ended` when there's nothing left to
+cancel.
+
+`POST /api/v1/t/{tenant}/runs/{id}/rerun`, with `run.start` and an `Idempotency-Key`, admits a new request (source
+`rerun`) on the workflow's active version with the old request's complete input: rebuilt from its envelope and its
+claims in memory only, then validated and claimed again, so no old handle is reused. The body `{"mode": ...}` is
+optional (the old request's by default). 410 `input_not_retained` for a run from before 2b-2, a refused request, or an
+input retention has removed.
 
 ## The worker
 
@@ -55,39 +153,42 @@ started on. Rolling out a build, and what Docker Compose runs (Temporal's dev se
 ## Starting a development run
 
 ```bash
-dewpoint dev run <version-id> --tenant <tenant-id> --input trigger.json
+dewpoint dev run <workflow-id> --tenant <tenant-id> --input input.json --wait 60
 ```
 
-- The version must be the **active** version of an **enabled** workflow, and nothing it uses may be retired. It,
-  and the sub-flows and failure handler it runs, must have been published for the engine ABI of the deployment's
-  current build, where the run starts ([`deployment.md`](deployment.md)).
+It admits the workflow's active version with the source `dev`, as any start is admitted
+([above](#starting-a-run)), and the dispatcher starts it: one must be running.
+
 - `--simulate` calls each plugin node's `simulate()` instead of `run()`: nothing is sent anywhere. A node without a
   simulation fails its step with `simulation_unavailable`. Timers still wait, as they would in a live run.
-- By default the command waits and prints the result. `--no-wait` prints the run id and returns.
-- Exit codes: 0 when the run succeeded; 1 when it ended otherwise, or its start was refused (by Temporal, or because
-  it couldn't be encrypted); 2 when it wasn't admitted (each reason is printed: in a `production` deployment,
-  "Production runs are off in this deployment"; a trigger that doesn't match the workflow's input schema, each place
-  and rule it breaks, never a value, a map's key shown as `*`; a trigger that holds the key `$claim`; a `dewpoint` of another engine ABI than
-  the current build's, [`deployment.md`](deployment.md)); 3 when Temporal never confirmed the start (see below).
-- It needs `DEWPOINT_DATABASE_URL` with a login in the `dewpoint_dispatch` role, the Temporal settings above, and the
-  KEK: it encrypts the trigger's claims and the start with the tenant's data key.
-
-The trigger is checked against the version's input schema when the run is admitted, then claimed
+- `--wait SECONDS` waits up to that long for the end the database records: its run's (status, code and message), or,
+  when it never started, the request's own (`cancelled`, `refused` or `dead`, with its reason). Without it, the
+  command prints the queued request and returns.
+- `--idempotency-key` retries a request; by default each invocation admits a new one.
+- Exit codes: 0 when it was admitted (with `--wait`: when its run succeeded); 1 when it ended otherwise; 2 when it
+  wasn't admitted (each message is printed, never a value: in a `production` deployment, "Production runs are off in
+  this deployment"; an input that doesn't match the workflow's input schema, each place and rule it breaks, a map's key
+  shown as `*`; an input that holds the key `$claim`; a version of another engine ABI than the current build's,
+  [`deployment.md`](deployment.md)); 3 when the wait ran out.
+- It needs `DEWPOINT_DATABASE_URL` with a login in the `dewpoint_dispatch` role and the KEK: it claims the input with
+  the tenant's data key. It doesn't talk to Temporal.
+
+The input is checked against the version's input schema when the request is admitted, then claimed
 ([below](#sensitive-and-large-values-claims)): its sensitive values, the positions its schema doesn't declare, and any
 value over 64 KiB are stored encrypted in `run_inputs`, and the run starts with handles in their place. A refused
-trigger leaves no run.
-
-**An unconfirmed start.** A start whose answer is lost looks like a failure, so it's retried with the same workflow id
-(`t:<tenant>:run:<run id>`), which Temporal refuses as a duplicate if the first attempt went through. A run is recorded
-as failed (`start_failed`) only when its start certainly never began: Temporal refused it, or the start couldn't be
-encrypted, so it was never sent (for example, the tenant has no data key: `dewpoint keys ensure-tenants` gives it
-one). If no attempt is answered at all, the run may be executing: it stays `running`, and the command exits 3.
+input leaves no request.
 
 ## Reading runs
 
-`GET /api/v1/t/{tenant}/runs` lists top-level runs, newest first (`workflow_id`, `before` and `limit` filter and page
-them). `GET /api/v1/t/{tenant}/runs/{run_id}` returns one run with its steps (one row per step, loop iteration and
-attempt) and its `children`: the sub-runs it started. The `iteration_key` is the loop step's key and the item's index,
+`GET /api/v1/t/{tenant}/runs` lists requests and top-level runs together, newest first by `(queued_at, id)`
+(`workflow_id`, `before`, `before_id` and `limit` filter and page them). A request's `queued_at` is when it was
+admitted; its run shares its id and `queued_at`; a run from before 2b-2 has its `started_at`. **The order changed in
+2b-2:** it was by start time, and the next page's cursor is now the last item's `queued_at` with its `id`, given
+together (else 422 `invalid_cursor`). Each item's `request` holds its `status`, `source` and `reason` (none for a run
+from before 2b-2). A request that hasn't started is shown as itself — `queued`, `starting`, `cancelled`, `refused` or
+`dead` — never as the row an attempt pre-created. `GET /api/v1/t/{tenant}/runs/{run_id}` returns one run with its
+steps (one row per step, loop iteration and attempt) and its `children`: the sub-runs it started (a request that hasn't
+started has neither). The `iteration_key` is the loop step's key and the item's index,
 like `each_ap:3`, or `outer:1/inner:4` when nested. Both need the `run.view` permission.
 
 Every run has a `kind`. A sub-flow's run (`subflow`) and a failure handler's (`failure_handler`) are runs of their
```

### Task 27: A re-run's key is checked before its old input is rebuilt; a re-run may take new input (the owner's milestone-4 review)

**Commit:** `22ade08` (prototype `proto/2b2-v2`); the replay's tree was identical: yes.

**Modify:** `backend/src/dewpoint/apps/admission.py`, `backend/src/dewpoint/apps/api/routes/run_requests.py`, `backend/tests/apps/api/test_run_requests_api.py`, `docs/operations/runs.md`

**What it does:**

A re-run's idempotency digest covers what was asked (the request it
re-runs, the mode, any new input: admission.Rerun) in place of the
input it admits, and the route looks the key up before rebuilding
anything (admitted_under). An exact retry returns the request it
admitted even once retention removed the old input; another re-run
under the key is 409 idempotency_conflict.

The re-run body takes optional new input: admitted on the active
version, validated and claimed as any start's, whatever the old
request's input retained (a removed claim, a refused request, a run
from before 2b-2). The audit entry names the request re-run (rerun_of).


- [ ] **Step 1: its tests alone, before its code.** Run: `uv run pytest -n 4 tests/apps/api/test_run_requests_api.py`. Replay result (exit 1), shortened:

```
[gw0] darwin -- Python 3.14.7 /private/tmp/claude-501/-Users-tmunzer-4-dev-mist-dewpoint/1e3145a1-199e-4b31-be1b-1e3bfd266be7/scratchpad/2b2-plan/proto/backend/.venv/bin/python
E   AssertionError: assert (422, 'invalid') == (422, 'input_invalid')
      At index 1 diff: 'invalid' != 'input_invalid'
      Use -v to get more diff
/private/tmp/claude-501/-Users-tmunzer-4-dev-mist-dewpoint/1e3145a1-199e-4b31-be1b-1e3bfd266be7/scratchpad/2b2-plan/replay/backend/tests/apps/api/test_run_requests_api.py:412: AssertionError: assert (422, 'invalid') == (422, 'input_invalid')
=========================== short test summary info ============================
FAILED tests/apps/api/test_run_requests_api.py::test_an_exact_rerun_retry_returns_the_admitted_request_even_once_the_old_input_is_gone
FAILED tests/apps/api/test_run_requests_api.py::test_a_reused_rerun_key_for_another_rerun_is_a_conflict_even_once_the_old_input_is_gone[other0]
FAILED tests/apps/api/test_run_requests_api.py::test_a_reused_rerun_key_for_another_rerun_is_a_conflict_even_once_the_old_input_is_gone[other1]
FAILED tests/apps/api/test_run_requests_api.py::test_a_rerun_with_new_input_needs_no_retained_input[pre_2b2_run]
FAILED tests/apps/api/test_run_requests_api.py::test_a_rerun_with_new_input_needs_no_retained_input[claim_removed]
FAILED tests/apps/api/test_run_requests_api.py::test_a_rerun_with_new_input_needs_no_retained_input[refused]
FAILED tests/apps/api/test_run_requests_api.py::test_a_reruns_new_input_is_validated_as_any_start
7 failed, 20 passed in 13.33s
```

- [ ] **Step 2: its code, then the same tests.** Replay result (exit 0), shortened:

```
...........................                                              [100%]
27 passed in 13.16s
```

- [ ] **Step 3: commit.** `git cherry-pick --no-commit 22ade08 && git commit -C 22ade08`

The diff:

```diff
diff --git a/backend/src/dewpoint/apps/admission.py b/backend/src/dewpoint/apps/admission.py
index e29d37c..803a0ff 100644
--- a/backend/src/dewpoint/apps/admission.py
+++ b/backend/src/dewpoint/apps/admission.py
@@ -84,6 +84,19 @@ class WorkflowNotFoundError(LookupError):
     """No such workflow in the caller's tenant."""
 
 
+@dataclass(frozen=True)
+class Rerun:
+    """A re-run's identity: the request (or, from before 2b-2, the run) it re-runs, and the new input it was given,
+    if any. Its idempotency digest covers this in place of the input it admits, so an exact retry is recognized, and
+    another request under the key refused, without rebuilding the old input, which retention may have removed."""
+
+    of: uuid.UUID
+    input: dict[str, Any] | None = None
+
+    def digested(self) -> dict[str, Any]:
+        return {"rerun_of": str(self.of), "input": self.input}
+
+
 @dataclass(frozen=True)
 class Admitted:
     request: RunRequest
@@ -110,17 +123,20 @@ async def admit_request(
     mode: str,
     idempotency_key: str,
     input: dict[str, Any],
+    rerun: Rerun | None = None,
 ) -> Admitted:
-    """The request under `idempotency_key`: an exact retry's, or a new one, frozen. Raises IdempotencyConflictError,
-    WorkflowNotFoundError, or, for an interactive source, AdmissionRefusedError."""
+    """The request under `idempotency_key`: an exact retry's, or a new one, frozen. A re-run's digest covers its
+    `rerun` identity in place of `input`. Raises IdempotencyConflictError, WorkflowNotFoundError, or, for an
+    interactive source, AdmissionRefusedError."""
     if source not in INTERACTIVE + DURABLE or mode not in (LIVE, SIMULATE):
         raise ValueError(f"no such source or mode: {source}, {mode}")
     await lifecycle.assert_read_committed(s)
     await tenant_scope(s, tenant_id)
     fields: dict[str, Any] = {"source": source, "workflow_id": workflow_id, "mode": mode, "input": input}
+    digested = {**fields, "input": rerun.digested()} if rerun is not None else fields
     existing = await _by_key(s, idempotency_key)
     if existing is not None:
-        return await _retry(keys, tenant_id, existing, fields)
+        return await _retry(keys, tenant_id, existing, digested)
     request_id = uuid.uuid4()
     savepoint = await s.begin_nested()
     try:
@@ -129,17 +145,33 @@ async def admit_request(
         await savepoint.rollback()
         if source in INTERACTIVE:
             raise AdmissionRefusedError(refused.reason, refused.messages) from None
-        return await _insert(s, keys, tenant_id, request_id, actor_id, idempotency_key, fields, None, None, refused)
+        return await _insert(s, keys, tenant_id, request_id, actor_id, idempotency_key, digested, None, None, refused,
+                             rerun)  # fmt: skip
     await _before_insert()
-    admitted = await _insert(s, keys, tenant_id, request_id, actor_id, idempotency_key, fields, version_id, envelope_id)
+    admitted = await _insert(s, keys, tenant_id, request_id, actor_id, idempotency_key, digested, version_id,
+                             envelope_id, rerun=rerun)  # fmt: skip
     if admitted.new:
         await savepoint.commit()
     else:
         await savepoint.rollback()  # another transaction won the key: this call's claims and envelope go with it
-        return await _retry(keys, tenant_id, await _winner(s, idempotency_key), fields)
+        return await _retry(keys, tenant_id, await _winner(s, idempotency_key), digested)
     return admitted
 
 
+async def admitted_under(
+    s: AsyncSession, keys: KeySource, *, tenant_id: uuid.UUID, idempotency_key: str, source: str,
+    workflow_id: uuid.UUID, mode: str, rerun: Rerun,
+) -> RunRequest | None:  # fmt: skip
+    """The request an exact retry of this re-run finds under its key, before its input is rebuilt; None when the key
+    is free. Raises IdempotencyConflictError for another request under the key."""
+    await tenant_scope(s, tenant_id)
+    existing = await _by_key(s, idempotency_key)
+    if existing is None:
+        return None
+    fields = {"source": source, "workflow_id": workflow_id, "mode": mode, "input": rerun.digested()}
+    return (await _retry(keys, tenant_id, existing, fields)).request
+
+
 async def _by_key(s: AsyncSession, idempotency_key: str) -> RunRequest | None:
     query = (
         select(RunRequest)
@@ -227,6 +259,7 @@ async def _insert(
     version_id: uuid.UUID | None,
     envelope_id: uuid.UUID | None,
     refused: _Refused | None = None,
+    rerun: Rerun | None = None,
 ) -> Admitted:
     """The request row, queued or refused, and its audit entry; `new` False when another transaction won the key."""
     key_version, digest = await digests.digest(keys, str(tenant_id), **fields)  # the tenant's active key (§7.2)
@@ -263,6 +296,8 @@ async def _insert(
         details["version_id"] = str(row["workflow_version_id"])
     if refused:
         details["reason"] = refused.reason
+    if rerun is not None:
+        details["rerun_of"] = str(rerun.of)
     await audit.record(s, tenant_id=tenant_id, actor_id=actor_id, action="run.request", target_type="run_request",
                        target_id=str(request_id), details=details)  # fmt: skip
     request = await s.get(RunRequest, request_id, populate_existing=True)
diff --git a/backend/src/dewpoint/apps/api/routes/run_requests.py b/backend/src/dewpoint/apps/api/routes/run_requests.py
index 7171387..b2c683e 100644
--- a/backend/src/dewpoint/apps/api/routes/run_requests.py
+++ b/backend/src/dewpoint/apps/api/routes/run_requests.py
@@ -43,6 +43,7 @@ class StartIn(BaseModel):
 class RerunIn(BaseModel):
     model_config = ConfigDict(extra="forbid")
     mode: Literal["live", "simulate"] | None = None  # the old request's when not given
+    input: dict[str, Any] | None = None  # new input; else the original, rebuilt while it's retained
 
 
 def key_unusable(e: Exception) -> HTTPException:
@@ -84,12 +85,13 @@ def request_body(r: RunRequest) -> dict[str, object]:
 
 
 async def admit(
-    db: AsyncSession, keys: KeySource, ctx: TenantContext, workflow_id: uuid.UUID, source: str, body: StartIn, key: str
-) -> RunRequest:
+    db: AsyncSession, keys: KeySource, ctx: TenantContext, workflow_id: uuid.UUID, source: str, body: StartIn, key: str,
+    rerun: admission.Rerun | None = None,
+) -> RunRequest:  # fmt: skip
     try:
         admitted = await admission.admit_request(
             db, keys, tenant_id=ctx.tenant_id, workflow_id=workflow_id, source=source, actor_id=ctx.user.id,
-            mode=body.mode, idempotency_key=key, input=body.input,
+            mode=body.mode, idempotency_key=key, input=body.input, rerun=rerun,
         )  # fmt: skip
     except admission.WorkflowNotFoundError:
         raise HTTPException(404, detail={"error": "not_found"}) from None
@@ -172,18 +174,38 @@ async def rerun(
     db: AsyncSession = Depends(get_db, scope="function"),
     keys: KeySource = Depends(get_keys),
 ) -> dict[str, object]:
-    """A new admission (source `rerun`) on the workflow's active version, with the old request's complete input,
-    validated and claimed again under the new request: no old handle is reused. 410 `input_not_retained` when it can't
-    be rebuilt: a run from before 2b-2, a refused request, an envelope or a claim retention has removed."""
+    """A new admission (source `rerun`) on the workflow's active version, with new input, or else the old request's
+    complete input, validated and claimed again under the new request: no old handle is reused. The key is checked
+    first: an exact retry returns the request it admitted, whatever retention has removed since; another request under
+    the key is a 409. 410 `input_not_retained` when the original input can't be rebuilt: a run from before 2b-2, a
+    refused request, an envelope or a claim retention has removed. New input needs none of it."""
+    given = body or RerunIn()
     old = await db.get(RunRequest, request_id)  # row-level security: the caller's tenant's only
-    if old is None:
-        if await db.get(Run, request_id) is not None:  # a run 2a started: no request, no envelope
-            raise HTTPException(410, detail={"error": INPUT_NOT_RETAINED})
+    run = await db.get(Run, request_id) if old is None else None  # a run 2a started: no request, no envelope
+    named = old if old is not None else run
+    if named is None:
         raise HTTPException(404, detail={"error": "not_found"})
-    value = await original_input(db, keys, ctx.tenant_id, old)
-    mode = body.mode if body is not None and body.mode is not None else old.mode
+    workflow_id, mode = named.workflow_id, given.mode or named.mode
+    again = admission.Rerun(request_id, given.input)
+    try:
+        existing = await admission.admitted_under(
+            db, keys, tenant_id=ctx.tenant_id, idempotency_key=key, source="rerun", workflow_id=workflow_id,
+            mode=mode, rerun=again,
+        )  # fmt: skip
+    except admission.IdempotencyConflictError:
+        raise HTTPException(409, detail={"error": "idempotency_conflict"}) from None
+    except Exception as e:
+        raise key_unusable(e) from None
+    if existing is not None:
+        return request_body(existing)
+    if given.input is not None:
+        value = given.input
+    elif old is None:
+        raise HTTPException(410, detail={"error": INPUT_NOT_RETAINED})
+    else:
+        value = await original_input(db, keys, ctx.tenant_id, old)
     start = StartIn(input=value, mode=mode)
-    return request_body(await admit(db, keys, ctx, old.workflow_id, "rerun", start, key))
+    return request_body(await admit(db, keys, ctx, workflow_id, "rerun", start, key, rerun=again))
 
 
 async def original_input(db: AsyncSession, keys: KeySource, tenant_id: uuid.UUID, old: RunRequest) -> dict[str, Any]:
diff --git a/backend/tests/apps/api/test_run_requests_api.py b/backend/tests/apps/api/test_run_requests_api.py
index ec3875b..be49930 100644
--- a/backend/tests/apps/api/test_run_requests_api.py
+++ b/backend/tests/apps/api/test_run_requests_api.py
@@ -328,3 +328,85 @@ async def test_a_tenant_whose_key_cant_be_read_answers_503(keyed_app, ready, own
     client = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx)
     answer = await client.post(runs_url(ctx, wf), json=BODY, headers={"Idempotency-Key": "k1"})
     assert (answer.status_code, answer.json()) == (503, {"error": "key_unusable"})
+
+
+async def remove_claims(owner: Any, request_id: str) -> None:
+    """Retention removed a request's claims (its envelope stays while a request refers to it)."""
+    async with owner() as s, s.begin():
+        await s.execute(text("delete from run_inputs where owner_run_id = :i and role = 'claim'"), {"i": request_id})
+
+
+async def test_an_exact_rerun_retry_returns_the_admitted_request_even_once_the_old_input_is_gone(
+    keyed_app, ready, owner_sessionmaker, api_settings
+) -> None:
+    """The owner's M4 review: the key is checked before the old input is rebuilt."""
+    ctx, wf = ready
+    client = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx)
+    old = await started_request(client, ctx, wf)
+    url = f"/api/v1/t/{ctx.tenant_id}/runs/{old['id']}/rerun"
+    first = await client.post(url, headers={"Idempotency-Key": "r1"})
+    assert first.status_code == 202, first.text
+    await remove_claims(owner_sessionmaker, old["id"])
+    again = await client.post(url, headers={"Idempotency-Key": "r1"})
+    assert (again.status_code, again.json()["id"]) == (202, first.json()["id"])
+    async with owner_sessionmaker() as s:
+        details = (await s.execute(text("select details from audit_log where action = 'run.request' and "
+                                        "target_id = :i"), {"i": first.json()["id"]})).scalar_one()  # fmt: skip
+    assert details["source"] == "rerun" and details["rerun_of"] == old["id"]
+
+
+@pytest.mark.parametrize("other", [{"mode": "simulate"}, {"input": {"token": TOKEN, "site": "b"}}])
+async def test_a_reused_rerun_key_for_another_rerun_is_a_conflict_even_once_the_old_input_is_gone(
+    keyed_app, ready, owner_sessionmaker, api_settings, other
+) -> None:
+    ctx, wf = ready
+    client = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx)
+    old = await started_request(client, ctx, wf)
+    url = f"/api/v1/t/{ctx.tenant_id}/runs/{old['id']}/rerun"
+    assert (await client.post(url, headers={"Idempotency-Key": "r1"})).status_code == 202
+    await remove_claims(owner_sessionmaker, old["id"])
+    conflict = await client.post(url, json=other, headers={"Idempotency-Key": "r1"})
+    assert (conflict.status_code, conflict.json()["error"]) == (409, "idempotency_conflict")
+
+
+@pytest.mark.parametrize("gone", ["claim_removed", "refused", "pre_2b2_run"])
+async def test_a_rerun_with_new_input_needs_no_retained_input(
+    keyed_app, ready, owner_sessionmaker, api_sessionmaker, dispatch_sessionmaker, api_settings, gone
+) -> None:
+    """Re-running with new input is always offered (§7.7): only the original input depends on retention."""
+    ctx, wf = ready
+    client = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx)
+    if gone == "claim_removed":
+        target = (await started_request(client, ctx, wf))["id"]
+        await remove_claims(owner_sessionmaker, target)
+    elif gone == "refused":
+        await update(api_sessionmaker, ctx, wf, enabled=False)
+        target = str((await admit(api_sessionmaker, ctx, wf, source="schedule")).request.id)
+        await update(api_sessionmaker, ctx, wf, enabled=True)
+    else:
+        async with owner_sessionmaker() as s:
+            version = (
+                await s.execute(text("select active_version_id from workflows where id = :w"), {"w": wf})
+            ).scalar()
+        async with dispatch_sessionmaker() as s, s.begin():
+            await tenant_scope(s, ctx.tenant_id)
+            target = str((await runs.insert_run(s, run_id=uuid.uuid4(), tenant_id=ctx.tenant_id, workflow_id=wf,
+                                                version_id=version, mode="live")).id)  # fmt: skip
+    answer = await client.post(
+        f"/api/v1/t/{ctx.tenant_id}/runs/{target}/rerun", json={"input": {"token": TOKEN, "site": "b"}},
+        headers={"Idempotency-Key": "r1"},
+    )  # fmt: skip
+    assert answer.status_code == 202, answer.text
+    assert answer.json()["source"] == "rerun" and TOKEN not in answer.text
+    assert (await envelope_of(api_sessionmaker, ctx, answer.json()["id"]))["site"] == "b"
+
+
+async def test_a_reruns_new_input_is_validated_as_any_start(keyed_app, ready, owner_sessionmaker, api_settings) -> None:
+    ctx, wf = ready
+    client = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx)
+    old = await started_request(client, ctx, wf)
+    answer = await client.post(
+        f"/api/v1/t/{ctx.tenant_id}/runs/{old['id']}/rerun", json={"input": {"site": "b"}},
+        headers={"Idempotency-Key": "r1"},
+    )  # fmt: skip
+    assert (answer.status_code, answer.json()["error"]) == (422, "input_invalid")
diff --git a/docs/operations/runs.md b/docs/operations/runs.md
index 750cfee..2439266 100644
--- a/docs/operations/runs.md
+++ b/docs/operations/runs.md
@@ -104,10 +104,13 @@ doesn't happen, or sends it to Temporal and the run ends `cancelled`. 409 `run_e
 cancel.
 
 `POST /api/v1/t/{tenant}/runs/{id}/rerun`, with `run.start` and an `Idempotency-Key`, admits a new request (source
-`rerun`) on the workflow's active version with the old request's complete input: rebuilt from its envelope and its
-claims in memory only, then validated and claimed again, so no old handle is reused. The body `{"mode": ...}` is
-optional (the old request's by default). 410 `input_not_retained` for a run from before 2b-2, a refused request, or an
-input retention has removed.
+`rerun`) on the workflow's active version. With `{"input": {...}}` it uses that new input, offered whatever was
+retained. Without it, it uses the old request's complete input: rebuilt from its envelope and its claims in memory
+only, then validated and claimed again, so no old handle is reused; 410 `input_not_retained` for a run from before
+2b-2, a refused request, or an input retention has removed. `{"mode": ...}` is optional (the old one's by default).
+The key covers what was asked (the request re-run, the mode, any new input), and is checked before anything is
+rebuilt: an exact retry returns the request it admitted even once retention has removed the old input, and another
+re-run under the key is 409 `idempotency_conflict`. The audit entry names the request re-run (`rerun_of`).
 
 ## The worker
```

**Checkpoint (milestone 4).** Focused: the API, CLI, deploy, dispatcher, admission, forms, runs, codec and core tests (417 at `79c8c5f`; 255 after Task 27). The owner held it on the re-run contract (Task 27), accepted new-input re-runs of runs from before 2b-2, and approved it (2026-10-03).

## Milestone 5 — Proofs

### Task 28: Every §7.8 transition with a tenant limit of 1; a forced retirement ends its cancelled requests' rows

**Commit:** `78ebc28` (prototype `proto/2b2-v2`); the replay's tree was identical: yes.

**Create:** `backend/migrations/versions/0024_retirement_ends_rows.py`, `backend/tests/apps/dispatcher/test_transitions.py`

**Modify:** `backend/src/dewpoint/core/plugins/lifecycle.py`

**What it does:**

The proofs: after each request, slot and row transition, the tenant's
next request starts exactly when the slot is free (queued -> starting,
started until the root's end write, uncertain, back to the queue on a
refusal or an absence, dead on a 10th refusal or a collision, a user's
cancel, engine_abi_changed, a forced retirement, a durable refusal, a
fast completion before the start's reply, and the recovery transition
for an ended run).

They found a forced retirement cancelling a queued request but leaving
the row an earlier attempt pre-created running. end_unstarted_run() now
ends the row with its request's own reason, the key admin may call it,
and the retirement does, in each tenant's scope (0024).


- [ ] **Step 1: its tests alone, before its code.** Run: `uv run pytest -n 4 tests/apps/dispatcher/test_transitions.py`. Replay result (exit 1), shortened:

```
......F......                                                            [100%]
=================================== FAILURES ===================================
[gw3] darwin -- Python 3.14.7 /private/tmp/claude-501/-Users-tmunzer-4-dev-mist-dewpoint/1e3145a1-199e-4b31-be1b-1e3bfd266be7/scratchpad/2b2-plan/proto/backend/.venv/bin/python
E   AssertionError: assert ('running', None) == ('cancelled',...type_retired')
      At index 0 diff: 'running' != 'cancelled'
      Use -v to get more diff
/private/tmp/claude-501/-Users-tmunzer-4-dev-mist-dewpoint/1e3145a1-199e-4b31-be1b-1e3bfd266be7/scratchpad/2b2-plan/replay/backend/tests/apps/dispatcher/test_transitions.py:174: AssertionError: assert ('running', None) == ('cancelled',...type_retired')
=========================== short test summary info ============================
FAILED tests/apps/dispatcher/test_transitions.py::test_a_forced_retirement_cancels_a_queued_request_and_an_earlier_attempts_row
1 failed, 12 passed in 11.54s
```

- [ ] **Step 2: its code, then the same tests.** Replay result (exit 0), shortened:

```
.............                                                            [100%]
13 passed in 11.48s
```

Evidence beyond the replay: the forced-retirement proof failed first (its row stayed `running`), fixed here; with `settle`'s slot release removed, five transition proofs fail.

- [ ] **Step 3: commit.** `git cherry-pick --no-commit 78ebc28 && git commit -C 78ebc28`

The diff:

```diff
diff --git a/backend/migrations/versions/0024_retirement_ends_rows.py b/backend/migrations/versions/0024_retirement_ends_rows.py
new file mode 100644
index 0000000..a8c589f
--- /dev/null
+++ b/backend/migrations/versions/0024_retirement_ends_rows.py
@@ -0,0 +1,44 @@
+# SPDX-License-Identifier: Apache-2.0
+"""a forced retirement ends the rows of the requests it cancels (engine 2b spec §7.8)
+
+A queued request a forced retirement cancels may have a row an earlier attempt pre-created; it's made terminal with
+its request, so it can't stay `running` forever (M5's transition proofs found it left so). `end_unstarted_run()` now
+ends the row with its request's own reason (`user_cancelled`, `node_type_retired`, `cel_profile_retired`), and the key
+admin, which runs retirements, may call it. It still ends only the row of a request of the caller's tenant scope
+that is already `cancelled`."""
+
+from alembic import op
+
+revision = "0024"
+down_revision = "0023"
+branch_labels = None
+depends_on = None
+
+BY_REASON = """
+CREATE OR REPLACE FUNCTION end_unstarted_run(run uuid) RETURNS void
+LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path = public, pg_temp AS $$
+  UPDATE runs u SET status = 'cancelled', ended_at = statement_timestamp(), error_code = r.reason
+  FROM run_requests r
+  WHERE u.id = run AND r.id = run AND u.tenant_id = app_tenant_id() AND r.tenant_id = app_tenant_id()
+    AND u.status = 'running' AND r.status = 'cancelled'
+$$"""
+
+USER_CANCELLED = """
+CREATE OR REPLACE FUNCTION end_unstarted_run(run uuid) RETURNS void
+LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path = public, pg_temp AS $$
+  UPDATE runs SET status = 'cancelled', ended_at = statement_timestamp(), error_code = 'user_cancelled'
+  WHERE id = run AND tenant_id = app_tenant_id() AND status = 'running'
+    AND EXISTS (
+      SELECT 1 FROM run_requests r WHERE r.id = run AND r.tenant_id = app_tenant_id() AND r.status = 'cancelled'
+    )
+$$"""
+
+
+def upgrade() -> None:
+    op.execute(BY_REASON)
+    op.execute("GRANT EXECUTE ON FUNCTION end_unstarted_run(uuid) TO dewpoint_admin")
+
+
+def downgrade() -> None:
+    op.execute("REVOKE EXECUTE ON FUNCTION end_unstarted_run(uuid) FROM dewpoint_admin")
+    op.execute(USER_CANCELLED)
diff --git a/backend/src/dewpoint/core/plugins/lifecycle.py b/backend/src/dewpoint/core/plugins/lifecycle.py
index ef2f537..b735307 100644
--- a/backend/src/dewpoint/core/plugins/lifecycle.py
+++ b/backend/src/dewpoint/core/plugins/lifecycle.py
@@ -257,6 +257,8 @@ async def retire(
         requests.setdefault(q.tenant_id, []).append(str(q.request_id))
     for tenant_id in sorted(workflows.keys() | requests.keys()):
         await tenant_scope(s, tenant_id)  # tenant audit entries need the tenant context; nothing reads after this
+        for request_id in requests.get(tenant_id, []):  # an earlier attempt's row ends with its request (§7.8)
+            await s.execute(text("select end_unstarted_run(:i)"), {"i": uuid.UUID(request_id)})
         await record(
             s,
             tenant_id=tenant_id,
diff --git a/backend/tests/apps/dispatcher/test_transitions.py b/backend/tests/apps/dispatcher/test_transitions.py
new file mode 100644
index 0000000..0651f61
--- /dev/null
+++ b/backend/tests/apps/dispatcher/test_transitions.py
@@ -0,0 +1,217 @@
+# SPDX-License-Identifier: Apache-2.0
+"""Every request, slot and row transition of engine 2b spec §7.8, with a tenant limit of 1 (M5's proofs): after each,
+the tenant's next request starts exactly when the slot is free. The first request is `first`, the next `second`."""
+
+import uuid
+from datetime import UTC, datetime
+from typing import Any
+
+import pytest
+from sqlalchemy import text
+
+from dewpoint.apps import cancels
+from dewpoint.apps.dispatcher import dispatch
+from dewpoint.apps.worker.store import DbRunStore
+from dewpoint.core.plugins import lifecycle
+from dewpoint.engine import ENGINE_ABI
+from dewpoint.engine.runtime.activities import ProjectInput, RunSummary
+from tests.apps.dispatcher.support import begin, state, workers
+from tests.apps.test_admission import KEYS, admit, current, published
+from tests.apps.test_workflow_ops import update
+
+pytestmark = pytest.mark.usefixtures("development_deployment")
+
+
+@pytest.fixture
+async def limited(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings) -> Any:
+    """A tenant limited to one run at a time, with two admitted requests, the first older."""
+    ctx, wf = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings)
+    await current(dispatch_sessionmaker)
+    await workers(owner_sessionmaker)
+    async with owner_sessionmaker() as s, s.begin():
+        await s.execute(text("insert into tenant_run_limits (tenant_id, max_concurrent) values (:t, 1)"),
+                        {"t": ctx.tenant_id})  # fmt: skip
+    first = (await admit(api_sessionmaker, ctx, wf, key="first")).request
+    second = (await admit(api_sessionmaker, ctx, wf, key="second")).request
+    return ctx, wf, first, second
+
+
+async def started(dispatch_sessionmaker: Any, request: Any, settings: Any) -> dispatch.Starting:
+    found = await begin(dispatch_sessionmaker, request, settings)
+    assert isinstance(found, dispatch.Starting), found
+    return found
+
+
+async def second_starts(dispatch_sessionmaker: Any, second: Any, settings: Any) -> bool:
+    """Whether the tenant's next request starts now; it's put back as it was either way, for the next look."""
+    found = await begin(dispatch_sessionmaker, second, settings)
+    if isinstance(found, dispatch.Starting):
+        assert await dispatch.settle(dispatch_sessionmaker, found, dispatch.Outcome("throttled")) == "throttled"
+        return True
+    assert found == dispatch.Waiting("no_slot"), found
+    return False
+
+
+async def due(owner: Any, request_id: uuid.UUID) -> None:
+    async with owner() as s, s.begin():
+        await s.execute(text("update run_requests set next_attempt_at = now() where id = :i"), {"i": request_id})
+
+
+async def row(owner: Any, run_id: uuid.UUID) -> tuple[Any, ...] | None:
+    async with owner() as s:
+        found = await s.execute(text("select status, error_code, started_at from runs where id = :i"), {"i": run_id})
+        first = found.first()
+        return tuple(first) if first else None
+
+
+async def end_write(worker: Any, ctx: Any, run_id: uuid.UUID, status: str = "succeeded") -> None:
+    summary = RunSummary(str(run_id), status, datetime.now(UTC).isoformat())
+    await DbRunStore(worker, KEYS).project(ProjectInput(str(ctx.tenant_id), [], summary))
+
+
+async def test_queued_to_starting_reserves_the_slot_and_writes_the_row(
+    limited, owner_sessionmaker, dispatch_sessionmaker, api_settings
+) -> None:
+    _, _, first, second = limited
+    await started(dispatch_sessionmaker, first, api_settings)
+    assert await state(owner_sessionmaker, first.id) == {
+        "request": ("starting", None, 0), "run": ("running", None, first.queued_at), "slot": 1,
+    }  # fmt: skip
+    await due(owner_sessionmaker, second.id)
+    assert not await second_starts(dispatch_sessionmaker, second, api_settings)
+
+
+async def test_starting_to_started_keeps_the_slot_until_the_roots_end_write(
+    limited, owner_sessionmaker, dispatch_sessionmaker, worker_sessionmaker, api_settings
+) -> None:
+    ctx, _, first, second = limited
+    found = await started(dispatch_sessionmaker, first, api_settings)
+    assert await dispatch.settle(dispatch_sessionmaker, found, dispatch.Outcome("started")) == "started"
+    assert not await second_starts(dispatch_sessionmaker, second, api_settings)
+    await end_write(worker_sessionmaker, ctx, first.id)
+    assert await second_starts(dispatch_sessionmaker, second, api_settings)
+
+
+async def test_an_uncertain_start_keeps_its_slot(
+    limited, owner_sessionmaker, dispatch_sessionmaker, api_settings
+) -> None:
+    _, _, first, second = limited
+    found = await started(dispatch_sessionmaker, first, api_settings)
+    assert await dispatch.settle(dispatch_sessionmaker, found, dispatch.Outcome("uncertain")) == "uncertain"
+    assert (await state(owner_sessionmaker, first.id))["request"][0] == "starting"
+    assert not await second_starts(dispatch_sessionmaker, second, api_settings)
+
+
+@pytest.mark.parametrize("outcome", ["refused", "absent"])
+async def test_back_to_the_queue_frees_the_slot_at_once_and_keeps_the_row_hidden(
+    limited, owner_sessionmaker, dispatch_sessionmaker, api_settings, outcome
+) -> None:
+    _, _, first, second = limited
+    found = await started(dispatch_sessionmaker, first, api_settings)
+    assert await dispatch.settle(dispatch_sessionmaker, found, dispatch.Outcome(outcome)) == outcome
+    after = await state(owner_sessionmaker, first.id)
+    assert (after["request"][0], after["slot"], after["run"][0]) == ("queued", 0, "running")
+    assert after["request"][2] == (1 if outcome == "refused" else 0)  # only a confirmed refusal is an attempt
+    assert await second_starts(dispatch_sessionmaker, second, api_settings)
+
+
+@pytest.mark.parametrize("cause", ["tenth_refusal", "collision"])
+async def test_dead_frees_the_slot_and_fails_the_row(
+    limited, owner_sessionmaker, dispatch_sessionmaker, api_settings, cause
+) -> None:
+    _, _, first, second = limited
+    found = await started(dispatch_sessionmaker, first, api_settings)
+    if cause == "tenth_refusal":
+        async with owner_sessionmaker() as s, s.begin():
+            await s.execute(text("update run_requests set attempts = 9 where id = :i"), {"i": first.id})
+    outcome = dispatch.Outcome("refused" if cause == "tenth_refusal" else "collision")
+    assert await dispatch.settle(dispatch_sessionmaker, found, outcome) == "dead"
+    reason = "start_refused" if cause == "tenth_refusal" else "id_collision"
+    assert (await state(owner_sessionmaker, first.id))["request"][:2] == ("dead", reason)
+    assert (await row(owner_sessionmaker, first.id))[:2] == ("failed", "start_failed")
+    assert await second_starts(dispatch_sessionmaker, second, api_settings)
+
+
+async def test_a_users_cancel_of_a_queued_request_ends_an_earlier_attempts_row(
+    limited, owner_sessionmaker, api_sessionmaker, dispatch_sessionmaker, api_settings
+) -> None:
+    ctx, _, first, second = limited
+    found = await started(dispatch_sessionmaker, first, api_settings)
+    assert await dispatch.settle(dispatch_sessionmaker, found, dispatch.Outcome("refused")) == "refused"
+    async with api_sessionmaker() as s, s.begin():
+        assert await cancels.cancel_request(s, tenant_id=ctx.tenant_id, request_id=first.id,
+                                            actor_id=ctx.user.id) == "cancelled"  # fmt: skip
+    assert (await row(owner_sessionmaker, first.id))[:2] == ("cancelled", "user_cancelled")
+    assert await second_starts(dispatch_sessionmaker, second, api_settings)
+
+
+async def test_a_build_of_another_abi_cancels_a_queued_request_holding_nothing(
+    limited, owner_sessionmaker, dispatch_sessionmaker, api_settings
+) -> None:
+    from dewpoint.apps.dispatcher.observe import Build
+
+    _, _, first, second = limited
+    other = Build(f"dewpoint-9.9.9+abi{ENGINE_ABI + 1}", ENGINE_ABI + 1)
+    async with owner_sessionmaker() as s, s.begin():
+        await s.execute(text("update worker_instances set build_id = :b"), {"b": other.build_id})
+    assert await begin(dispatch_sessionmaker, first, api_settings, build=other) == dispatch.Cancelled(
+        "engine_abi_changed"
+    )
+    assert (await state(owner_sessionmaker, first.id))["slot"] == 0
+
+
+async def test_a_forced_retirement_cancels_a_queued_request_and_an_earlier_attempts_row(
+    limited, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings
+) -> None:
+    ctx, wf, first, second = limited
+    found = await started(dispatch_sessionmaker, first, api_settings)
+    assert await dispatch.settle(dispatch_sessionmaker, found, dispatch.Outcome("refused")) == "refused"
+    await update(api_sessionmaker, ctx, wf, enabled=False)
+    async with admin_sessionmaker() as s, s.begin():
+        assert (await lifecycle.retire(s, lifecycle.Entry("node", "testkit.echo@1"), force=True, confirm=True)).applied
+    after = await state(owner_sessionmaker, first.id)
+    assert (after["request"][:2], after["slot"]) == (("cancelled", "node_type_retired"), 0)
+    assert (await row(owner_sessionmaker, first.id))[:2] == ("cancelled", "node_type_retired")
+
+
+async def test_a_durable_sources_refusal_holds_no_slot_and_writes_no_row(
+    limited, owner_sessionmaker, api_sessionmaker, dispatch_sessionmaker, api_settings
+) -> None:
+    ctx, wf, _, second = limited
+    await update(api_sessionmaker, ctx, wf, enabled=False)
+    refused = (await admit(api_sessionmaker, ctx, wf, key="tick", source="schedule")).request
+    assert (refused.status, refused.reason) == ("refused", "workflow_disabled")
+    assert await state(owner_sessionmaker, refused.id) == {
+        "request": ("refused", "workflow_disabled", 0), "run": None, "slot": 0,
+    }  # fmt: skip
+
+
+async def test_a_fast_completion_before_the_starts_reply_is_never_undone(
+    limited, owner_sessionmaker, dispatch_sessionmaker, worker_sessionmaker, api_settings
+) -> None:
+    """§7.8: the run finishes, its end write making its row terminal and freeing the slot, before the start's reply is
+    settled. Confirming then only sets the request's status and a null start time: the row stays ended, and no slot
+    comes back, so the tenant's next request starts."""
+    ctx, _, first, second = limited
+    found = await started(dispatch_sessionmaker, first, api_settings)
+    await end_write(worker_sessionmaker, ctx, first.id)
+    assert await dispatch.settle(dispatch_sessionmaker, found, dispatch.Outcome("started")) == "started"
+    after = await state(owner_sessionmaker, first.id)
+    assert (after["request"][0], after["slot"], after["run"][0]) == ("started", 0, "succeeded")
+    assert after["run"][1] is not None
+    assert await second_starts(dispatch_sessionmaker, second, api_settings)
+
+
+async def test_an_ended_runs_request_back_in_the_queue_goes_to_starting_holding_nothing(
+    limited, owner_sessionmaker, dispatch_sessionmaker, worker_sessionmaker, api_settings
+) -> None:
+    """The recovery transition the owner accepted for revision 7's §7.8: `queued` -> `starting` without a slot, for a
+    request whose run already ended."""
+    ctx, _, first, second = limited
+    found = await started(dispatch_sessionmaker, first, api_settings)
+    assert await dispatch.settle(dispatch_sessionmaker, found, dispatch.Outcome("absent")) == "absent"
+    await end_write(worker_sessionmaker, ctx, first.id)  # a late end write
+    assert await begin(dispatch_sessionmaker, first, api_settings) == dispatch.Held("run_ended")
+    after = await state(owner_sessionmaker, first.id)
+    assert (after["request"][0], after["slot"]) == ("starting", 0)
+    assert await second_starts(dispatch_sessionmaker, second, api_settings)
```

### Task 29: The starting transaction tries the closure's lifecycle locks, never waits on them; races proven

**Commit:** `5980df4` (prototype `proto/2b2-v2`); the replay's tree was identical: yes.

**Create:** `backend/tests/apps/dispatcher/test_races.py`

**Modify:** `backend/src/dewpoint/apps/dispatcher/dispatch.py`, `backend/src/dewpoint/core/plugins/lifecycle.py`

**What it does:**

A retirement holding a closure entry's lock exclusively cancels the
queued requests that use it; a starting transaction that had locked
such a request and then waited for the entry's shared lock deadlocked
with it. The starting transaction now tries the lifecycle locks
(lifecycle.try_lock_shared): when a retirement holds one, the request
waits a cycle (Waiting retiring), its transaction releasing the row,
and the retirement cancels it.

The race proofs, in both orders: admission first holds a normal
retirement back and is cancelled by a forced one; retirement first
refuses admission (a durable source's refusal kept); dispatch first
holds a retirement back and its starting request survives a forced one;
retirement first cancels the queued request without a deadlock; an
admission that read the gate on just before it went off queues a
request that never starts.


- [ ] **Step 1: its tests alone, before its code.** Run: `uv run pytest -n 4 tests/apps/dispatcher/test_races.py`. Replay result (exit 1), shortened:

```
E   AttributeError: <module 'dewpoint.apps.dispatcher.dispatch' from '/private/tmp/claude-501/-Users-tmunzer-4-dev-mist-dewpoint/1e3145a1-199e-4b31-be1b-1e3bfd266be7/scratchpad/2b2-plan/replay/backend/src/dewpoint/apps/dispatcher/dispatch.py'> has no attribute '_after_lifecycle_lock'
/private/tmp/claude-501/-Users-tmunzer-4-dev-mist-dewpoint/1e3145a1-199e-4b31-be1b-1e3bfd266be7/scratchpad/2b2-plan/replay/backend/tests/apps/dispatcher/test_races.py:48: AttributeError: <module 'dewpoint.apps.dispatcher.dispatch' from '/private/tmp/claude-501/-Users-tmunzer-4-dev-mist-dewpoint/1e3145a1-199e-4b31-be1b-1e3bfd266be7/scratchpad/2b2-plan/replay/backend/src/dewpoint/apps/dispatcher/dispatch.py'> has no attribute '_after_lifecycle_lock'
[gw3] darwin -- Python 3.14.7 /private/tmp/claude-501/-Users-tmunzer-4-dev-mist-dewpoint/1e3145a1-199e-4b31-be1b-1e3bfd266be7/scratchpad/2b2-plan/proto/backend/.venv/bin/python
E   assert (set())
---------------------------- Captured stderr setup -----------------------------
security, not by bypassing it (engine 2b spec §6.3, plan 2b-1a's review)
§14; revision 7)
dispatcher
/private/tmp/claude-501/-Users-tmunzer-4-dev-mist-dewpoint/1e3145a1-199e-4b31-be1b-1e3bfd266be7/scratchpad/2b2-plan/replay/backend/tests/apps/dispatcher/test_races.py:133: assert (set())
=========================== short test summary info ============================
FAILED tests/apps/dispatcher/test_races.py::test_dispatch_first_holds_a_retirement_until_its_request_is_starting[normal]
FAILED tests/apps/dispatcher/test_races.py::test_dispatch_first_holds_a_retirement_until_its_request_is_starting[forced]
FAILED tests/apps/dispatcher/test_races.py::test_retirement_first_cancels_a_queued_request_without_deadlocking_a_starting_transaction
3 failed, 5 passed in 14.16s
```

- [ ] **Step 2: its code, then the same tests.** Replay result (exit 0), shortened:

```
........                                                                 [100%]
8 passed in 11.61s
```

- [ ] **Step 3: commit.** `git cherry-pick --no-commit 5980df4 && git commit -C 5980df4`

The diff:

```diff
diff --git a/backend/src/dewpoint/apps/dispatcher/dispatch.py b/backend/src/dewpoint/apps/dispatcher/dispatch.py
index 66c8121..06fe384 100644
--- a/backend/src/dewpoint/apps/dispatcher/dispatch.py
+++ b/backend/src/dewpoint/apps/dispatcher/dispatch.py
@@ -60,6 +60,7 @@ ID_COLLISION = "id_collision"
 START_FAILED = "start_failed"
 ENVELOPE_UNREADABLE = "envelope_unreadable"
 RUN_ENDED = "run_ended"
+RETIRING = "retiring"  # a retirement holds the closure's lifecycle lock: back next cycle
 KEY_UNUSABLE = "key_unusable"
 ENVELOPE_MESSAGE = (
     "The request's trigger envelope doesn't open or isn't JSON; repairing a key never reopens it (engine 2b spec §7.1)."
@@ -190,6 +191,10 @@ class KeyFailures:
             raise KeyUnusableError("A tenant's digest key can't be read.") from e
 
 
+async def _after_lifecycle_lock() -> None:
+    """Runs right after the starting transaction takes its lifecycle locks. A no-op; the race tests pause here."""
+
+
 async def _lock(s: AsyncSession, key: str) -> None:
     await s.execute(text("select pg_advisory_xact_lock_shared(hashtextextended(:k, 0))"), {"k": key})
 
@@ -262,7 +267,10 @@ async def _begin(
     if version is None:
         raise RuntimeError("A request frozen on a version that isn't there.")
     entries = lifecycle.entries_for(version.closure_node_refs, version.closure_cel_profiles)
-    await lifecycle.lock_shared(s, entries)
+    # Never waited for: this transaction holds the request's row, which a retirement holding these locks cancels.
+    if not await lifecycle.try_lock_shared(s, entries):
+        return Waiting(RETIRING)
+    await _after_lifecycle_lock()
     blocked = lifecycle.not_executable(await lifecycle.states(s, entries))
     if blocked:  # the defensive check: admission's locks make this impossible, but for a request that came back
         reason = "node_type_retired" if any(e.kind == "node" for e in blocked) else "cel_profile_retired"
diff --git a/backend/src/dewpoint/core/plugins/lifecycle.py b/backend/src/dewpoint/core/plugins/lifecycle.py
index b735307..6ced1ac 100644
--- a/backend/src/dewpoint/core/plugins/lifecycle.py
+++ b/backend/src/dewpoint/core/plugins/lifecycle.py
@@ -63,6 +63,20 @@ async def lock_shared(s: AsyncSession, entries: Iterable[Entry]) -> None:
         await s.execute(text("select pg_advisory_xact_lock_shared(hashtextextended(:k, 0))"), {"k": entry.lock_key})
 
 
+async def try_lock_shared(s: AsyncSession, entries: Iterable[Entry]) -> bool:
+    """`lock_shared` without waiting: False as soon as one entry is held exclusively (a retirement in progress). The
+    locks it got stay held until the transaction ends. For a caller that holds row locks a retirement may need (a
+    starting transaction holds its request's): waiting there could deadlock with the retirement."""
+    await assert_read_committed(s)
+    for entry in sorted(set(entries)):
+        found = await s.execute(
+            text("select pg_try_advisory_xact_lock_shared(hashtextextended(:k, 0))"), {"k": entry.lock_key}
+        )
+        if not found.scalar_one():
+            return False
+    return True
+
+
 async def lock_exclusive(s: AsyncSession, entry: Entry) -> None:
     await assert_read_committed(s)
     await s.execute(text("select pg_advisory_xact_lock(hashtextextended(:k, 0))"), {"k": entry.lock_key})
diff --git a/backend/tests/apps/dispatcher/test_races.py b/backend/tests/apps/dispatcher/test_races.py
new file mode 100644
index 0000000..7bbec48
--- /dev/null
+++ b/backend/tests/apps/dispatcher/test_races.py
@@ -0,0 +1,161 @@
+# SPDX-License-Identifier: Apache-2.0
+"""Admission and dispatch against retirement and the gate (engine 2b spec §2.4, §7.2, §7.3; engine-core §4.5), in
+both orders (M5's proofs). Admission and the starting transaction take the closure's lifecycle locks shared, a
+retirement takes them exclusively: whichever is first, the other sees what it committed. A request admitted first
+holds a normal retirement back and is cancelled by a forced one; one already `starting` survives a forced retirement
+for the defensive check; a retirement first refuses admission and cancels a queued request before dispatch sees it,
+never deadlocking with a starting transaction that has locked the request. An admission that read the gate on just
+before it was turned off queues a request that never starts."""
+
+import asyncio
+from typing import Any
+
+import pytest
+from sqlalchemy import text
+
+from dewpoint.apps import admission
+from dewpoint.apps.dispatcher import dispatch, gate
+from dewpoint.core.plugins import lifecycle
+from tests.apps.dispatcher.support import begin, state
+from tests.apps.test_admission import admit, count, current, published
+from tests.apps.test_lifecycle_races import until_someone_waits_for_a_lock
+
+pytestmark = pytest.mark.usefixtures("development_deployment")
+ECHO = lifecycle.Entry("node", "testkit.echo@1")
+
+
+@pytest.fixture
+async def ready(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings) -> Any:
+    ctx, wf = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings)
+    await current(dispatch_sessionmaker)
+    return ctx, wf
+
+
+@pytest.fixture
+def pause(monkeypatch: pytest.MonkeyPatch) -> Any:
+    """Pause admission (after its locks, before its insert) or the starting transaction (after its lifecycle locks),
+    once armed: `pause("admission")` or `pause("dispatch")`."""
+    reached, release = asyncio.Event(), asyncio.Event()
+
+    async def paused() -> None:
+        reached.set()
+        await release.wait()
+
+    def arm(where: str) -> tuple[asyncio.Event, asyncio.Event]:
+        if where == "admission":
+            monkeypatch.setattr(admission, "_before_insert", paused)
+        else:
+            monkeypatch.setattr(dispatch, "_after_lifecycle_lock", paused)
+        return reached, release
+
+    return arm
+
+
+async def retire(admin: Any, *, force: bool) -> lifecycle.RetirePreview:
+    async with admin() as a, a.begin():
+        return await lifecycle.retire(a, ECHO, force=force, confirm=force)
+
+
+@pytest.mark.parametrize("force", [False, True], ids=["normal", "forced"])
+async def test_admission_first_holds_a_retirement_until_its_request_is_committed(
+    ready, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, pause, force
+) -> None:
+    ctx, wf = ready
+    reached, release = pause("admission")
+    admitting = asyncio.create_task(admit(api_sessionmaker, ctx, wf))
+    await asyncio.wait_for(reached.wait(), 10)
+    retiring = asyncio.create_task(retire(admin_sessionmaker, force=force))
+    await until_someone_waits_for_a_lock(owner_sessionmaker)
+    release.set()
+    request = (await asyncio.wait_for(admitting, 10)).request
+    if not force:
+        with pytest.raises(lifecycle.ReferencedError) as refused:
+            await asyncio.wait_for(retiring, 10)
+        assert [q.request_id for q in refused.value.preview.queued] == [request.id]
+        return
+    preview = await asyncio.wait_for(retiring, 10)
+    assert preview.applied and [q.request_id for q in preview.queued] == [request.id]
+    assert (await state(owner_sessionmaker, request.id))["request"][:2] == ("cancelled", "node_type_retired")
+
+
+@pytest.mark.parametrize("source", ["manual", "schedule"])
+async def test_retirement_first_refuses_admission(
+    ready, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, source
+) -> None:
+    """An interactive source is refused; a durable one's refusal is kept as a `refused` request (§2.5)."""
+    ctx, wf = ready
+    async with admin_sessionmaker() as a, a.begin():
+        await lifecycle.lock_exclusive(a, ECHO)
+        admitting = asyncio.create_task(admit(api_sessionmaker, ctx, wf, source=source))
+        await until_someone_waits_for_a_lock(owner_sessionmaker)
+        assert (await lifecycle.retire(a, ECHO, force=True, confirm=True)).applied
+    if source == "manual":
+        with pytest.raises(admission.AdmissionRefusedError) as refused:
+            await asyncio.wait_for(admitting, 10)
+        assert refused.value.reason == "node_type_retired"
+        assert await count(owner_sessionmaker, "run_requests") == 0
+    else:
+        request = (await asyncio.wait_for(admitting, 10)).request
+        assert (request.status, request.reason) == ("refused", "node_type_retired")
+
+
+@pytest.mark.parametrize("force", [False, True], ids=["normal", "forced"])
+async def test_dispatch_first_holds_a_retirement_until_its_request_is_starting(
+    queued, owner_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings, pause, force
+) -> None:
+    _, _, request = queued
+    reached, release = pause("dispatch")
+    beginning = asyncio.create_task(begin(dispatch_sessionmaker, request, api_settings))
+    await asyncio.wait_for(reached.wait(), 10)
+    retiring = asyncio.create_task(retire(admin_sessionmaker, force=force))
+    await until_someone_waits_for_a_lock(owner_sessionmaker)
+    release.set()
+    assert isinstance(await asyncio.wait_for(beginning, 10), dispatch.Starting)
+    if not force:
+        with pytest.raises(lifecycle.ReferencedError) as refused:
+            await asyncio.wait_for(retiring, 10)
+        assert [(q.request_id, q.status) for q in refused.value.preview.queued] == [(request.id, "starting")]
+        return
+    assert (await asyncio.wait_for(retiring, 10)).applied
+    assert (await state(owner_sessionmaker, request.id))["request"][0] == "starting"  # for the defensive check
+
+
+async def test_retirement_first_cancels_a_queued_request_without_deadlocking_a_starting_transaction(
+    queued, owner_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings
+) -> None:
+    """The retirement holds the closure's lock when a starting transaction, having locked the request, reaches it: the
+    starting transaction waits a cycle, never on the lock, so the retirement can cancel the request it holds."""
+    _, _, request = queued
+    async with admin_sessionmaker() as a, a.begin():
+        await lifecycle.lock_exclusive(a, ECHO)
+        beginning = asyncio.create_task(begin(dispatch_sessionmaker, request, api_settings))
+        done, _ = await asyncio.wait({beginning}, timeout=3)
+        assert done and beginning.result() == dispatch.Waiting("retiring")
+        preview = await lifecycle.retire(a, ECHO, force=True, confirm=True)
+    assert preview.applied and [q.request_id for q in preview.queued] == [request.id]
+    assert (await state(owner_sessionmaker, request.id))["request"][:2] == ("cancelled", "node_type_retired")
+    assert await begin(dispatch_sessionmaker, request, api_settings) is None  # nothing left to start
+
+
+async def test_an_admission_that_read_the_gate_on_queues_a_request_that_never_starts(
+    ready, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings, pause
+) -> None:
+    """§2.4: admission reads the gate without its lock; one in flight when the gate goes off still queues its request,
+    and the starting transaction, under the gate's lock, never starts it."""
+    from tests.apps.dispatcher.support import workers
+
+    ctx, wf = ready
+    await workers(owner_sessionmaker)
+    async with owner_sessionmaker() as s, s.begin():
+        await s.execute(text("alter table platform_settings disable trigger user"))
+        await s.execute(text("update platform_settings set environment = 'production', production_runs = true"))
+        await s.execute(text("alter table platform_settings enable trigger user"))
+    reached, release = pause("admission")
+    admitting = asyncio.create_task(admit(api_sessionmaker, ctx, wf))
+    await asyncio.wait_for(reached.wait(), 10)
+    async with admin_sessionmaker() as a, a.begin():
+        assert await gate.disable_production_runs(a, actor_id=None) is True
+    release.set()
+    request = (await asyncio.wait_for(admitting, 10)).request
+    assert request.status == "queued"
+    assert await begin(dispatch_sessionmaker, request, api_settings) == dispatch.Waiting("gate_off")
```

### Task 30: The dev server's proofs, and a run end to end with the keyring's real keys

**Commit:** `826931b` (prototype `proto/2b2-v2`); the replay's tree was identical: yes.

**Create:** `backend/tests/apps/dispatcher/test_dev_server.py`

**What it does:**

On Temporal's CLI dev server (this module's own): a lost reply verified
and a start that never arrived found absent behind a real namespace
check; a namespace that doesn't exist never read as an absence;
"already started" verified from a real history; a real termination
recorded; and the reconciler following a run that continued as new to
its latest execution's own result.

End to end with real keys (the owner's M4 condition): the API admits
with its keyring, the dispatcher seals each start with the tenant's
data key, a versioned worker of a current build opens it and the
claims, and the re-run rebuilds its input through the API; history
holds only sealed payloads and no response quotes the secret.


- [ ] **Step 1: its tests alone, before its code.** Run: `uv run pytest -n 4 tests/apps/dispatcher/test_dev_server.py`. Replay result (exit 0), shortened:

```
......                                                                   [100%]
6 passed in 18.43s
```

- [ ] **Step 2: its code, then the same tests.** Replay result (exit 0), shortened:

```
......                                                                   [100%]
6 passed in 18.12s
```

Evidence beyond the replay: the continue-as-new proof caught a wrong first-execution read while it was written; the end-to-end proof failed until the worker was a versioned worker of a current build, as a real server requires.

- [ ] **Step 3: commit.** `git cherry-pick --no-commit 826931b && git commit -C 826931b`

The diff:

```diff
diff --git a/backend/tests/apps/dispatcher/test_dev_server.py b/backend/tests/apps/dispatcher/test_dev_server.py
new file mode 100644
index 0000000..d71bf51
--- /dev/null
+++ b/backend/tests/apps/dispatcher/test_dev_server.py
@@ -0,0 +1,206 @@
+# SPDX-License-Identifier: Apache-2.0
+"""M5's proofs on Temporal's CLI dev server (engine 2b spec §7.4, §7.6, §12): a trustworthy absence behind a real
+namespace check, and none from a namespace that doesn't exist; "already started" verified from a real history; the
+reconciler's mapping of a real termination, and of a run that continued as new, to the logical run's latest
+execution; and a run, then its re-run, end to end through the API, the dispatcher and the worker, with the keyring's
+real keys everywhere (the owner's M4 condition for M5). The server is this module's own: no other test's builds
+route its tasks."""
+
+import asyncio
+import dataclasses
+import uuid
+from collections.abc import AsyncIterator
+from datetime import timedelta
+from typing import Any
+
+import pytest
+from sqlalchemy import text
+from temporalio.client import Client
+from temporalio.testing import WorkflowEnvironment
+
+from dewpoint.apps.codec import ENCODING, data_converter
+from dewpoint.apps.dispatcher import dispatch, reconcile
+from dewpoint.apps.worker.store import DbRunStore
+from dewpoint.core.crypto.kek import KekSet
+from dewpoint.core.crypto.keyring import Keyring
+from dewpoint.core.crypto.keys import KeyringKeys
+from dewpoint.core.tenancy.service import ensure_tenant_keys
+from dewpoint.engine.runtime.ids import run_workflow_id
+from dewpoint.engine.runtime.workflow import RunGraph
+from tests.apps.api.helpers import member_client
+from tests.apps.dispatcher.support import BUILD, begin, state
+from tests.apps.dispatcher.test_reconcile_runs import NoEndWrite
+from tests.apps.test_admission import KEYS, SCHEMA, TOKEN, current, published
+from tests.apps.worker.test_real_server import serving  # a versioned engine worker of a build made current
+from tests.support.graphs import G, ref
+from tests.support.keys import FIXTURE_CONVERTER
+
+pytestmark = pytest.mark.usefixtures("development_deployment")
+BODY = {"input": {"token": TOKEN, "site": "a"}, "mode": "live"}
+
+
+@pytest.fixture(scope="module")
+async def server() -> AsyncIterator[WorkflowEnvironment]:
+    async with await WorkflowEnvironment.start_local(data_converter=FIXTURE_CONVERTER) as environment:
+        yield environment
+
+
+@pytest.fixture
+async def ready(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings) -> Any:
+    from tests.apps.dispatcher.support import workers as ready_workers
+
+    ctx, wf = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings)
+    await current(dispatch_sessionmaker)
+    await ready_workers(owner_sessionmaker)
+    return ctx, wf
+
+
+async def admitted(api: Any, ctx: Any, wf: uuid.UUID, key: str) -> Any:
+    from tests.apps.test_admission import admit
+
+    return (await admit(api, ctx, wf, key=key)).request
+
+
+async def starting(dispatch_sessionmaker: Any, request: Any, settings: Any) -> dispatch.Starting:
+    found = await begin(dispatch_sessionmaker, request, settings)
+    assert isinstance(found, dispatch.Starting), found
+    return found
+
+
+async def ended(owner: Any, run_id: uuid.UUID) -> tuple[Any, ...]:
+    async with owner() as s:
+        row = await s.execute(text("select status, error_code from runs where id = :i"), {"i": run_id})
+        return tuple(row.one())
+
+
+async def test_a_lost_reply_is_verified_and_a_start_that_never_arrived_found_absent(
+    server, ready, owner_sessionmaker, api_sessionmaker, dispatch_sessionmaker, api_settings, monkeypatch
+) -> None:
+    ctx, wf = ready
+    lost = await starting(dispatch_sessionmaker, await admitted(api_sessionmaker, ctx, wf, "a"), api_settings)
+    never = await starting(dispatch_sessionmaker, await admitted(api_sessionmaker, ctx, wf, "b"), api_settings)
+    assert (await dispatch.start(server.client, lost)).kind == "started"  # accepted; its reply never settled
+    monkeypatch.setattr(reconcile, "GRACE", timedelta(0))
+    counts = await reconcile.reconcile_once(dispatch_sessionmaker, server.client, KEYS, api_settings)
+    assert counts == {"started": 1, "absent": 1}
+    assert (await state(owner_sessionmaker, lost.request_id))["request"][0] == "started"
+    assert (await state(owner_sessionmaker, never.request_id))["request"][0] == "queued"
+
+
+async def test_a_namespace_that_doesnt_exist_never_reads_as_an_absence(
+    server, ready, owner_sessionmaker, api_sessionmaker, dispatch_sessionmaker, api_settings, monkeypatch
+) -> None:
+    """Its NOT_FOUND is the namespace's, not the execution's: the start stays unresolved, its slot held."""
+    ctx, wf = ready
+    request = await admitted(api_sessionmaker, ctx, wf, "a")
+    await starting(dispatch_sessionmaker, request, api_settings)
+    target = server.client.service_client.config.target_host
+    ghost = await Client.connect(target, namespace=f"dewpoint-ghost-{uuid.uuid4().hex[:8]}",
+                                 data_converter=FIXTURE_CONVERTER)  # fmt: skip
+    monkeypatch.setattr(reconcile, "GRACE", timedelta(0))
+    assert await reconcile.reconcile_once(dispatch_sessionmaker, ghost, KEYS, api_settings) == {"unresolved": 1}
+    after = await state(owner_sessionmaker, request.id)
+    assert (after["request"][0], after["slot"]) == ("starting", 1)
+
+
+async def test_already_started_is_verified_from_the_real_history(
+    server, ready, api_sessionmaker, dispatch_sessionmaker, api_settings
+) -> None:
+    ctx, wf = ready
+    found = await starting(dispatch_sessionmaker, await admitted(api_sessionmaker, ctx, wf, "a"), api_settings)
+    assert (await dispatch.start(server.client, found)).kind == "started"
+    again = await dispatch.start(server.client, found)  # the same start, sent again: Temporal refuses the duplicate
+    assert again.kind == "started" and again.at is not None
+
+
+async def test_the_reconciler_records_a_real_termination(
+    server, ready, owner_sessionmaker, api_sessionmaker, dispatch_sessionmaker, api_settings
+) -> None:
+    ctx, wf = ready
+    found = await starting(dispatch_sessionmaker, await admitted(api_sessionmaker, ctx, wf, "a"), api_settings)
+    assert await dispatch.settle(dispatch_sessionmaker, found, await dispatch.start(server.client, found)) == "started"
+    await server.client.get_workflow_handle(run_workflow_id(str(ctx.tenant_id), str(found.request_id))).terminate()
+    assert await reconcile.reconcile_once(dispatch_sessionmaker, server.client, KEYS, api_settings) == {"ended": 1}
+    assert await ended(owner_sessionmaker, found.request_id) == ("failed", "terminated")
+    assert (await state(owner_sessionmaker, found.request_id))["slot"] == 0
+
+
+async def test_the_reconciler_follows_continue_as_new_to_the_latest_executions_end(
+    server, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, worker_sessionmaker,
+    api_settings,
+) -> None:  # fmt: skip
+    """The first execution closed by continuing as new, which never ends the run: the end is its successor's."""
+    from tests.apps.dispatcher.support import workers as ready_workers
+
+    graph = G().node("l", "flow.loop@1", {"items": list(range(40)), "collect": ref("steps.x.output.value")})
+    graph.node("x", "testkit.echo@1", {"value": ref("item")}).edge("l", "x", "body")  # long enough to continue
+    ctx, wf = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings,
+                              graph.data() | {"settings": {"input_schema": SCHEMA}})  # fmt: skip
+    await current(dispatch_sessionmaker)
+    await ready_workers(owner_sessionmaker)
+    found = await starting(dispatch_sessionmaker, await admitted(api_sessionmaker, ctx, wf, "a"), api_settings)
+    eager = dispatch.Starting(
+        found.request_id, found.tenant_id, dataclasses.replace(found.start, checkpoint_events=120)
+    )
+    workflow_id = run_workflow_id(str(ctx.tenant_id), str(found.request_id))
+    async with serving(server.client, NoEndWrite(worker_sessionmaker, KEYS)):  # type: ignore[arg-type]
+        outcome = await dispatch.start(server.client, eager)
+        assert await dispatch.settle(dispatch_sessionmaker, eager, outcome) == "started"
+        handle = server.client.get_workflow_handle_for(RunGraph.run, workflow_id)
+        assert (await asyncio.wait_for(handle.result(), 60)).status == "succeeded"
+    latest = (await server.client.get_workflow_handle(workflow_id).fetch_history()).events[0]
+    previous = latest.workflow_execution_started_event_attributes.continued_execution_run_id
+    assert previous, "the run never continued as new"
+    first = server.client.get_workflow_handle(workflow_id, run_id=previous)
+    assert (await first.describe()).status.name == "CONTINUED_AS_NEW"
+    assert await ended(owner_sessionmaker, found.request_id) == ("running", None)  # its end write never landed
+    assert await reconcile.reconcile_once(dispatch_sessionmaker, server.client, KEYS, api_settings) == {"ended": 1}
+    assert await ended(owner_sessionmaker, found.request_id) == ("succeeded", None)
+
+
+async def until_ended(client: Any, url: str) -> dict[str, Any]:
+    for _ in range(300):
+        found = (await client.get(url)).json()
+        if found["status"] not in ("queued", "starting", "running"):
+            return found  # type: ignore[no-any-return]
+        await asyncio.sleep(0.1)
+    raise AssertionError(f"still {found['status']}")
+
+
+async def test_a_run_and_its_rerun_end_to_end_with_the_keyrings_real_keys(
+    server, ready, app, owner_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, worker_sessionmaker,
+    api_settings,
+) -> None:  # fmt: skip
+    """The API admits with its keyring (no fixture keys), the dispatcher seals each start with the tenant's real data
+    key, the worker opens it and the claims with its own, and the re-run rebuilds the input through the API's."""
+    ctx, wf = ready
+    keyring = Keyring(KekSet.from_settings(api_settings))
+    async with admin_sessionmaker() as s, s.begin():
+        assert ctx.tenant_id in await ensure_tenant_keys(s, keyring)  # a real data key, wrapped by the KEK
+    dispatch_keys, worker_keys = KeyringKeys(dispatch_sessionmaker, keyring), KeyringKeys(worker_sessionmaker, keyring)
+    target, namespace = server.client.service_client.config.target_host, server.client.namespace
+    dispatcher = await Client.connect(target, namespace=namespace, data_converter=data_converter(dispatch_keys))
+    worker = await Client.connect(target, namespace=namespace, data_converter=data_converter(worker_keys))
+    operator, _ = await member_client(app, owner_sessionmaker, api_settings, ctx.tenant_id, "operator")
+    answer = await operator.post(f"/api/v1/t/{ctx.tenant_id}/workflows/{wf}/runs", json=BODY,
+                                 headers={"Idempotency-Key": "e2e-1"})  # fmt: skip
+    assert answer.status_code == 202, answer.text
+    request_id = answer.json()["id"]
+    async with serving(worker, DbRunStore(worker_sessionmaker, worker_keys)):  # type: ignore[arg-type]
+        assert await dispatch.dispatch_once(dispatch_sessionmaker, dispatcher, dispatch_keys, api_settings, BUILD) == {
+            "started": 1
+        }
+        run = await until_ended(operator, f"/api/v1/t/{ctx.tenant_id}/runs/{request_id}")
+        rerun = await operator.post(f"/api/v1/t/{ctx.tenant_id}/runs/{request_id}/rerun",
+                                    headers={"Idempotency-Key": "e2e-2"})  # fmt: skip
+        assert rerun.status_code == 202, rerun.text
+        assert await dispatch.dispatch_once(dispatch_sessionmaker, dispatcher, dispatch_keys, api_settings, BUILD) == {
+            "started": 1
+        }
+        again = await until_ended(operator, f"/api/v1/t/{ctx.tenant_id}/runs/{rerun.json()['id']}")
+    assert (run["status"], again["status"], again["request"]["source"]) == ("succeeded", "succeeded", "rerun")
+    history = server.client.get_workflow_handle(run_workflow_id(str(ctx.tenant_id), request_id))
+    started_event = (await history.fetch_history()).events[0].workflow_execution_started_event_attributes
+    assert started_event.input.payloads[0].metadata["encoding"] == ENCODING  # sealed, never plain JSON
+    listed = (await operator.get(f"/api/v1/t/{ctx.tenant_id}/runs")).text
+    assert TOKEN not in listed and TOKEN not in str(run) and TOKEN not in str(again)
```

### Task 31: The real-keyring proof scans both executions' whole raw histories for the secret (the owner's milestone-5 review)

**Commit:** `b4bca47` (prototype `proto/2b2-v2`); the replay's tree was identical: yes.

**Modify:** `backend/tests/apps/dispatcher/test_dev_server.py`

**What it does:**

Every execution of the run and of its re-run, back through any
continue-as-new: each history, every event as the server stores it, as
raw bytes, never holds the canary; each holds the tenant's id (its
workflow ids), so the scan reads the real histories whole.


- [ ] **Step 1: its tests alone, before its code.** Run: `uv run pytest -n 4 tests/apps/dispatcher/test_dev_server.py`. Replay result (exit 0), shortened:

```
......                                                                   [100%]
6 passed in 18.38s
```

- [ ] **Step 2: its code, then the same tests.** Replay result (exit 0), shortened:

```
......                                                                   [100%]
6 passed in 18.41s
```

Evidence beyond the replay: it reads each execution's whole raw history, and finds the tenant's id there, so the scan reads real histories; the canary is in none.

- [ ] **Step 3: commit.** `git cherry-pick --no-commit b4bca47 && git commit -C b4bca47`

The diff:

```diff
diff --git a/backend/tests/apps/dispatcher/test_dev_server.py b/backend/tests/apps/dispatcher/test_dev_server.py
index d71bf51..22f8552 100644
--- a/backend/tests/apps/dispatcher/test_dev_server.py
+++ b/backend/tests/apps/dispatcher/test_dev_server.py
@@ -158,6 +158,19 @@ async def test_the_reconciler_follows_continue_as_new_to_the_latest_executions_e
     assert await ended(owner_sessionmaker, found.request_id) == ("succeeded", None)
 
 
+async def raw_histories(client: Any, workflow_id: str) -> list[bytes]:
+    """Every execution of a logical run, the latest first and back through continue-as-new: each one's whole history,
+    every event as the server stores it, as raw bytes."""
+    out: list[bytes] = []
+    run_id: str | None = None
+    while True:
+        history = await client.get_workflow_handle(workflow_id, run_id=run_id).fetch_history()
+        out.append(b"".join(event.SerializeToString() for event in history.events))
+        run_id = history.events[0].workflow_execution_started_event_attributes.continued_execution_run_id or None
+        if run_id is None:
+            return out
+
+
 async def until_ended(client: Any, url: str) -> dict[str, Any]:
     for _ in range(300):
         found = (await client.get(url)).json()
@@ -199,6 +212,10 @@ async def test_a_run_and_its_rerun_end_to_end_with_the_keyrings_real_keys(
         }
         again = await until_ended(operator, f"/api/v1/t/{ctx.tenant_id}/runs/{rerun.json()['id']}")
     assert (run["status"], again["status"], again["request"]["source"]) == ("succeeded", "succeeded", "rerun")
+    for run_id in (request_id, rerun.json()["id"]):  # the owner's M5 review: both executions' whole histories
+        raws = await raw_histories(server.client, run_workflow_id(str(ctx.tenant_id), run_id))
+        assert raws and all(TOKEN.encode() not in raw for raw in raws)
+        assert all(str(ctx.tenant_id).encode() in raw for raw in raws)  # real histories, read whole
     history = server.client.get_workflow_handle(run_workflow_id(str(ctx.tenant_id), request_id))
     started_event = (await history.fetch_history()).events[0].workflow_execution_started_event_attributes
     assert started_event.input.payloads[0].metadata["encoding"] == ENCODING  # sealed, never plain JSON
```

### Task 32: A run through the Compose dispatcher, as the dispatch login, must succeed (the owner's milestone-5 review)

**Commit:** `85c39dc` (prototype `proto/2b2-v2`); the replay's tree was identical: yes.

**Create:** `backend/tests/deploy/conftest.py`, `backend/tests/deploy/test_compose_seed.py`, `deploy/compose/ci/seed-workflow.py`

**Modify:** `.github/workflows/ci.yml`

**What it does:**

A bounded step (5 minutes) after the worker's build is current: the
registry synced as the admin login; a synthetic tenant, with its data
key, and a published workflow of the shipped flow plugin's nodes only,
made as the API's login (deploy/compose/ci/seed-workflow.py, piped into
the API's image); then dewpoint dev run --wait 120 inside the
dispatcher's container, with its dispatch login, which exits 0 only when
the run the database records succeeded.

Locally, the seed runs against the test database and its workflow
through admission, the dispatcher and a worker to success; the step's
shape is tested. The Compose run itself happens in the implementation
PR's CI.


- [ ] **Step 1: its tests alone, before its code.** Run: `uv run pytest -n 4 tests/deploy/test_compose_seed.py`. Replay result (exit 1), shortened:

```
§14; revision 7)
dispatcher
<frozen importlib._bootstrap_external>:950: FileNotFoundError: [Errno 2] No such file or directory: '/private/tmp/claude-501/-Users-tmunzer-4-dev-mist-dewpoint/1e3145a1-199e-4b31-be1b-1e3bfd266be7/scratchpad/2b2-plan/replay/deploy/compose/ci/seed-workflow.py'
[gw1] darwin -- Python 3.14.7 /private/tmp/claude-501/-Users-tmunzer-4-dev-mist-dewpoint/1e3145a1-199e-4b31-be1b-1e3bfd266be7/scratchpad/2b2-plan/proto/backend/.venv/bin/python
E   ValueError: not enough values to unpack (expected 1, got 0)
---------------------------- Captured stderr setup -----------------------------
security, not by bypassing it (engine 2b spec §6.3, plan 2b-1a's review)
§14; revision 7)
dispatcher
/private/tmp/claude-501/-Users-tmunzer-4-dev-mist-dewpoint/1e3145a1-199e-4b31-be1b-1e3bfd266be7/scratchpad/2b2-plan/replay/backend/tests/deploy/test_compose_seed.py:61: ValueError: not enough values to unpack (expected 1, got 0)
=========================== short test summary info ============================
FAILED tests/deploy/test_compose_seed.py::test_the_seeded_workflow_runs_to_success_through_the_dispatcher
FAILED tests/deploy/test_compose_seed.py::test_ci_proves_a_run_through_the_compose_dispatcher_with_the_dispatch_login
2 failed in 10.04s
```

- [ ] **Step 2: its code, then the same tests.** Replay result (exit 0), shortened:

```
..                                                                       [100%]
2 passed in 13.04s
```

- [ ] **Step 3: commit.** `git cherry-pick --no-commit 85c39dc && git commit -C 85c39dc`

The diff:

```diff
diff --git a/.github/workflows/ci.yml b/.github/workflows/ci.yml
index 4c35327..496d6cd 100644
--- a/.github/workflows/ci.yml
+++ b/.github/workflows/ci.yml
@@ -105,6 +105,19 @@ jobs:
             sleep 2
           done
           exit 1
+      - name: A run through the Compose dispatcher (engine 2b spec §12)
+        working-directory: deploy/compose
+        timeout-minutes: 5
+        run: |
+          set -a; . ./.env; set +a
+          # The registry, as on every deploy; then a synthetic tenant and a published workflow, as the API's login.
+          docker compose run --rm \
+            -e DEWPOINT_DATABASE_URL="postgresql+asyncpg://dewpoint_admin_login:${DEWPOINT_ADMIN_DB_PASSWORD}@postgres/dewpoint" \
+            api dewpoint plugins sync
+          read -r tenant workflow < <(docker compose run --rm -T api python - < ci/seed-workflow.py | tail -n 1)
+          # Admitted as the dispatcher's login, started by the Compose dispatcher, run by the worker: exit 0 only when
+          # the run the database records succeeded.
+          docker compose exec -T dispatcher dewpoint dev run "$workflow" --tenant "$tenant" --wait 120
       - uses: pnpm/action-setup@b906affcce14559ad1aafd4ab0e942779e9f58b1 # v4  (version comes from package.json "packageManager")
         with: { package_json_file: frontend/package.json }
       - uses: actions/setup-node@v4
diff --git a/backend/tests/deploy/conftest.py b/backend/tests/deploy/conftest.py
new file mode 100644
index 0000000..663c2ea
--- /dev/null
+++ b/backend/tests/deploy/conftest.py
@@ -0,0 +1,2 @@
+# SPDX-License-Identifier: Apache-2.0
+from tests.apps.worker.conftest import env  # noqa: F401  (the time-skipping test server, for the Compose proof)
diff --git a/backend/tests/deploy/test_compose_seed.py b/backend/tests/deploy/test_compose_seed.py
new file mode 100644
index 0000000..8aa9803
--- /dev/null
+++ b/backend/tests/deploy/test_compose_seed.py
@@ -0,0 +1,68 @@
+# SPDX-License-Identifier: Apache-2.0
+"""CI's Compose proof (engine 2b spec §12; the owner's M5 condition): `deploy/compose/ci/seed-workflow.py` makes a
+synthetic tenant, with its data key, and a published workflow of the shipped `flow` plugin's nodes only, as the API's
+login; then `dewpoint dev run --wait`, as the dispatcher's login, must end with the run succeeded. Here the seed runs
+against the test database and its workflow through admission, the dispatcher and a worker; CI runs the same against
+the Compose stack."""
+
+import importlib.util
+from pathlib import Path
+from typing import Any
+
+import pytest
+import yaml
+
+from dewpoint.apps import dev_run
+from dewpoint.apps.dispatcher.dispatch import dispatch_once
+from dewpoint.apps.worker.store import DbRunStore
+from dewpoint.core.crypto.kek import KekSet
+from dewpoint.core.crypto.keyring import Keyring
+from dewpoint.core.crypto.keys import KeyringKeys
+from tests.apps.dispatcher.support import BUILD, workers
+from tests.apps.test_admission import current
+from tests.apps.worker.harness import workers as engine_workers
+from tests.support.registry import sync_test_plugins
+
+ROOT = Path(__file__).parents[3]
+SEED = ROOT / "deploy" / "compose" / "ci" / "seed-workflow.py"
+CI = ROOT / ".github" / "workflows" / "ci.yml"
+
+
+def seeding() -> Any:
+    spec = importlib.util.spec_from_file_location("seed_workflow", SEED)
+    assert spec is not None and spec.loader is not None
+    module = importlib.util.module_from_spec(spec)
+    spec.loader.exec_module(module)
+    return module
+
+
+@pytest.mark.usefixtures("development_deployment")
+async def test_the_seeded_workflow_runs_to_success_through_the_dispatcher(
+    env, owner_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, worker_sessionmaker, api_settings
+) -> None:
+    await sync_test_plugins(admin_sessionmaker)  # Compose: `dewpoint plugins sync`, as the admin login
+    tenant_id, workflow_id = await seeding().seed(api_settings)
+    await current(dispatch_sessionmaker)
+    await workers(owner_sessionmaker)
+    keyring = Keyring(KekSet.from_settings(api_settings))
+    dispatch_keys, worker_keys = KeyringKeys(dispatch_sessionmaker, keyring), KeyringKeys(worker_sessionmaker, keyring)
+    request = await dev_run.admit(dispatch_sessionmaker, dispatch_keys, tenant_id=tenant_id, workflow_id=workflow_id,
+                                  input={}, simulate=False, idempotency_key="ci-proof")  # fmt: skip
+    async with engine_workers(env.client, DbRunStore(worker_sessionmaker, worker_keys)):
+        assert await dispatch_once(dispatch_sessionmaker, env.client, dispatch_keys, api_settings, BUILD) == {
+            "started": 1
+        }
+        ended = await dev_run.wait_for_end(dispatch_sessionmaker, tenant_id, request.id, within=30, poll=0.1)
+    assert ended == dev_run.Ended("run", "succeeded", None, None)
+
+
+def test_ci_proves_a_run_through_the_compose_dispatcher_with_the_dispatch_login() -> None:
+    steps = yaml.safe_load(CI.read_text())["jobs"]["e2e"]["steps"]
+    [proof] = [s for s in steps if s.get("name", "").startswith("A run through the Compose dispatcher")]
+    assert proof["timeout-minutes"] <= 5  # bounded
+    script = proof["run"]
+    assert "dewpoint_admin_login" in script and "dewpoint plugins sync" in script
+    assert "python - < ci/seed-workflow.py" in script
+    assert "docker compose exec -T dispatcher dewpoint dev run" in script and "--wait" in script
+    names = [s.get("name", "") for s in steps]
+    assert names.index(proof["name"]) > names.index("The worker's build is current")
diff --git a/deploy/compose/ci/seed-workflow.py b/deploy/compose/ci/seed-workflow.py
new file mode 100644
index 0000000..8ce7863
--- /dev/null
+++ b/deploy/compose/ci/seed-workflow.py
@@ -0,0 +1,75 @@
+# SPDX-License-Identifier: Apache-2.0
+"""CI's synthetic data for the Compose proof (engine 2b spec §12): a tenant with its data key, its owner, and a
+published workflow of the shipped `flow` plugin's nodes only. Nothing here is real data. Run in the API's image, as
+the API's database login, after `dewpoint plugins sync`:
+
+    docker compose run --rm -T api python - < ci/seed-workflow.py
+
+It prints the tenant's id and the workflow's, on its last line."""
+
+import asyncio
+import secrets
+import uuid
+from typing import Any
+
+from dewpoint.apps import workflow_ops
+from dewpoint.core.auth.users import create_user
+from dewpoint.core.config import Settings, get_settings
+from dewpoint.core.crypto.kek import KekSet
+from dewpoint.core.crypto.keyring import Keyring
+from dewpoint.core.db import make_engine, make_sessionmaker, tenant_scope
+from dewpoint.core.http import TenantContext
+from dewpoint.core.tenancy.service import create_tenant
+from dewpoint.core.workflows import service as workflows
+
+GRAPH: dict[str, Any] = {
+    "graph_format": 1,
+    "nodes": [
+        {
+            "id": "5f0c6e2a-2b2b-4e2b-9c2b-2b2b2b2b2b2b",
+            "key": "t",
+            "type": "flow.transform@1",
+            "config": {"fields": {"answer": {"$value": {"kind": "cel", "expr": "1 + 1"}}}},
+            "options": {"on_error": "fail"},
+        }
+    ],
+    "edges": [],
+    "settings": {
+        "input_schema": {"type": "object"},
+        "outputs": {"answer": {"$value": {"kind": "cel", "expr": "steps.t.output.answer"}}},
+    },
+}
+
+
+async def seed(settings: Settings) -> tuple[uuid.UUID, uuid.UUID]:
+    """The synthetic tenant's id and its published workflow's."""
+    engine = make_engine(settings.database_url)
+    try:
+        sessionmaker = make_sessionmaker(engine)
+        mark = uuid.uuid4().hex[:8]
+        async with sessionmaker() as s, s.begin():
+            # A synthetic owner no one signs in as: a random password, never written down.
+            user = await create_user(s, email=f"ci-{mark}@example.com", password=secrets.token_urlsafe(24))
+            tenant = await create_tenant(s, Keyring(KekSet.from_settings(settings)), name="CI proof", slug=f"ci-{mark}",
+                                         owner_id=user.id)  # fmt: skip
+        ctx = TenantContext(tenant_id=tenant.id, user=user, role="owner", session=None)  # type: ignore[arg-type]
+        async with sessionmaker() as s, s.begin():
+            await tenant_scope(s, tenant.id)
+            workflow_id = (await workflows.create_workflow(s, ctx, name="CI proof", draft=GRAPH)).id
+        async with sessionmaker() as s, s.begin():
+            await tenant_scope(s, tenant.id)
+            workflow = await workflows.get_workflow(s, tenant.id, workflow_id, for_update=True)
+            if workflow is None:
+                raise SystemExit("the workflow just created isn't there")
+            published = await workflow_ops.publish(s, ctx, workflow, expected_revision=workflow.draft_revision,
+                                                   settings=settings)  # fmt: skip
+            if published.version is None:
+                raise SystemExit(f"publish refused: {[d.code for d in published.errors]}")
+        return tenant.id, workflow_id
+    finally:
+        await engine.dispose()
+
+
+if __name__ == "__main__":
+    tenant_id, workflow_id = asyncio.run(seed(get_settings()))
+    print(tenant_id, workflow_id)
```

**Checkpoint (milestone 5).** Focused: the dispatcher (transitions, races, the dev server), API, CLI, deploy, admission, lifecycle races, forms, runs, codec, worker and all of `tests/core` (516 at `826931b`); the migrations 0016 → 0024 → 0016 → 0024. The owner accepted Tasks 28–29's fixes and keeps milestone 5 open on two conditions: the real-keyring proof's whole-history scan (Task 31) and the Compose proof's CI step (Task 32) passing in this branch's pull request. Then the whole suite and the static checks once, and a fresh whole-branch review.
