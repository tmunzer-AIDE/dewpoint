# Engine 2b-3a: CSV Starts and Schedules — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Start runs from a manual start with a CSV file and from a schedule's tick. Each is admitted by
`admit_request` and started by the dispatcher; no trigger starts a run itself. Webhook ingress is 2b-3b, with its own
outline, prototype, plan and pull request.

**Architecture:**
- **The CSV declaration and the trigger schema (milestone 1).** `graph.settings.csv` declares a file's columns and
  caps, and publish checks it. A version's trigger schema adds `rows` and `row_count` to its input schema, and both
  names are reserved. A CSV workflow's input schema keeps a plain root, and a CSV version is no sub-flow's or failure
  handler's target. The no-declassify exception for a loop over `trigger.rows` needs a CSV declaration (#31). Publish
  refuses every literal a schema writes at a sensitive position (#32).
- **CSV uploads and starts (milestone 2).** The upload is a raw `text/csv` body, streamed with its cap enforced while
  it's read, parsed as data only and staged as sealed bytes for an hour. Each workflow keeps an encrypted default
  mapping, marked stale when a later version no longer fits it. A CSV start checks its key first and returns an exact
  retry to the upload's owner only. It locks, verifies and consumes the upload in admission's transaction, builds rows
  against the frozen version, and keeps a CSV record in `run_inputs`. The owner's milestone-2 review bounds the error
  detail, lifts the csv module's field limit to the byte cap, and stages the file's own bytes.
- **Schedules (milestone 3).** Contract tests come first: Temporal discards a stale update, a schedule's note shows the
  generation that landed, and cron is read as Temporal reads it. Then the `schedules` table and API; `ScheduleTick` and
  its activity, on the dispatcher's own unversioned worker; and the leader's sync, whose token-bearing updates complete
  only on a read-back of their marker, with tombstones and misses. The owner's milestone-3 reviews make a tick decide
  under its schedule's row, held exclusively, refuse a PATCH's nulls, and name the schedule in the tick's audit entry.
- **Proofs, Compose and docs (milestone 4).** End-to-end proofs on the dev server, with the keyring's real keys and
  canaries, a catch-up and the gate. A work-unit test counts a claimed CSV loop's `cel.evaluate`, and a CSV past the
  secret index's bound is refused. CI runs a schedule through Compose, and the operations docs are updated.

**Tech Stack:** Python 3.12, Temporal Python SDK 1.33.0 (Schedules) and CLI dev server 1.9.1, PostgreSQL 16 through
testcontainers (`postgres:16-alpine`), SQLAlchemy async with asyncpg, Alembic, `cryptography`, FastAPI, hypothesis
(fuzzing), typer, pytest with pytest-xdist, ruff, mypy strict, import-linter; `uv`. No new dependency.

**Spec:** `docs/superpowers/specs/2026-09-29-engine-2b-design.md`: revision 7 is approved (#29), and the revision 8
draft lands with this plan on branch `docs/engine-2b3-plan`. Sections: §3.8 (sensitive literals), §4.3 (the
`trigger.rows` exception), §4.6 (a schedule's visible metadata), §7.1 (the CSV record), §7.9 (open before
production), §8.1 (CSV), §8.2 (schedules), §9 (codes), §10.1 (retention), §12 (testing), §13 (earlier specs), §14
(tables, grants) and §15 (values). Also engine-core (`2026-09-25-engine-core-design.md`, revision 5.10) §9 and §11.11,
and the parent spec's §6.1 and §6.8.

## Global Constraints

- Every trigger ends in `admit_request`, and none starts a run; a CSV start comes only through the run API.
- No value from a file, a mapping or a schedule's input appears in plain metadata, a log, a code or a message. Codes
  are fixed; an error names a row, a column and a code, never a cell; a log names an exception's type, never its
  message.
- Every new table forces row-level security, with tenant-scoped policies for the operational roles only. Cross-tenant
  reads are functions returning ids only (`schedule_candidates`, `schedule_miss_candidates`). No role deletes an upload
  or a schedule: retention does, in 2b-4.
- The new key purposes are `csv.upload`, `csv.mapping` and `schedule.input`, each sealed with its row's id as context.
- No transaction is open across a call to Temporal, and every call in the sync is bounded at 10 s.
- `ENGINE_ABI` stays 6: there's no page activity (revision 8 replaces §8.1's). `ScheduleTick` is unversioned on
  `dewpoint-admission`, outside the Worker Deployment, and a replay golden pins it.
- Editing a Dewpoint schedule directly in Temporal isn't supported: the sync tells its own updates apart only by their
  `dewpoint generation <n>` note.
- Docker runs only the approved images (`postgres:16-alpine`, ryuk, `temporalio/temporal:1.9.1`, and the evaluator's
  bases for its image); the Compose proof runs in CI.
- Migrations 0026–0030 upgrade, downgrade and upgrade again over existing rows.
- Fix findings test-first. Run focused checks at each milestone, and the whole suite once, at the end.
- The 10,000-row durations are estimates (the owner, 2026-10-04), never stated as measured.

## Review Focus

These are the input classes and failure modes most likely to bite a person running this that no task's tests
exercise. §7.9 keeps them open before production, and the reviewer weighs each deliberately:
- **A Temporal that answers slowly.** Each cycle, the leader makes up to 200 serial schedule calls of up to 10 s
  each, which delays dispatch as well (§7.9). Expect it noted, not hidden.
- **A tenant being erased.** Its status changing doesn't pause its schedules: their ticks are skipped, with an audit
  entry, until the erasure transition raises their generations (§7.9).
- **Uploads at the cap.** The API reads a file whole, up to about 72 MB for a 5 MiB file, and concurrent uploads add
  up (§7.9, production sizing).
- **A 10,000-row CSV with CEL over a cell.** One `cel.evaluate` per row takes an estimated 23–25 minutes; with five
  sensitive columns, the start request holds for about 30 s (estimated).
- **A schedule edited directly in Temporal.** Drift under an intact note isn't detected; such edits aren't supported.

## File structure

New:
- `backend/migrations/versions/0026_csv_uploads.py` … `0030_schedule_sync.py`: uploads, default mappings, the CSV
  record's role, schedules, and the sync's candidates.
- `backend/src/dewpoint/engine/graph/csv.py`: the declaration's types, caps, reserved names, cell conversion and the
  trigger schema.
- `backend/src/dewpoint/apps/csv_input.py` (reading a file, building rows), `apps/csv_uploads.py` (staging, the
  default mapping), `apps/schedules.py` (the timing's rules, a schedule's writes).
- `backend/src/dewpoint/apps/api/routes/csv_uploads.py` (the streamed upload, the default mapping) and
  `routes/schedules.py`.
- `backend/src/dewpoint/apps/dispatcher/tick.py` (a tick's admission and activity), `tick_workflow.py`
  (`ScheduleTick`) and `schedule_sync.py` (the sync and the misses).
- `backend/src/dewpoint/core/models/uploads.py` (`CsvUpload`, `CsvMapping`) and `core/models/schedules.py`
  (`Schedule`).
- `deploy/compose/ci/schedule-proof.py`, and the tests listed in each task.

Changed:
- Engine: `engine/graph/model.py`, `engine/graph/validate.py`, `engine/runtime/ids.py`.
- Apps: `apps/admission.py`, `apps/forms.py`, `apps/inputs.py`, `apps/workflow_ops.py`, `apps/api/main.py`,
  `apps/api/middleware.py`, `apps/api/routes/run_requests.py`, `apps/api/routes/runs.py`, `apps/dispatcher/main.py`.
- Core: `core/claims/service.py`, `core/authz/permissions.py`, `core/requests/digest.py`, `core/models/__init__.py`.
- CI and docs: `.github/workflows/ci.yml`, `docs/operations/runs.md`, `docs/operations/deployment.md`.

## How the steps give code

Each task's code is given as a unified diff against the tree the previous task left, in the task's record. The diffs
are a prototype's commits, and each was replayed onto that tree in two steps. First its tests ran alone, and failed as
the record says (or passed, for a contract test or a proof of what earlier tasks built). Then the rest of the diff was
applied, and the tests passed. New files appear whole, as `new file mode` diffs. In the replay's outputs, local paths
are shortened to `<replay>` (the replay's checkout), `<venv>` and `<python>`.

The prototype is the local branch `proto/2b3a-v2`, cut from `main` at `85177d8`, with one commit per task. It
rebuilds `proto/2b3a-v1`, which was built milestone by milestone with the owner's checkpoint after each; all four
milestones were approved as prototype checkpoints. The rebuild folds in the single-task fix-ups: the milestone-1
review's two fixes go into Tasks 1 and 2, and the second milestone-3 review's lock fix into Task 16. The cross-task
review fixes stay their own tasks (9 and 16), and a note on each task they refine says what changes. The rebuild's
last tree is identical to `proto/2b3a-v1`'s. The replay (branch `replay/2b3a-v2`) reproduced every commit's tree
exactly.

Each commit was verified this way:
- its tree was reproduced exactly by the replay, its tests failing before its code and passing after, with the
  exceptions each record shows;
- ruff (without its cache), mypy and import-linter passed when the prototype's commit was made;
- at each checkpoint, the milestone's focused tests passed (the counts the checkpoints give), and the migrations went
  up, down and up again over existing rows.

Per the owner's ruling on the outline, the whole suite runs once, at the end, not at every task.

## Executing this plan

Run it inline, in one session, from the prototype's commits; the diffs aren't typed again. Work on `feat/engine-2b3a`,
cut from `main` once this plan's docs have merged (they change only `docs/superpowers`). For each task in order:
1. Read the task.
2. Run `git cherry-pick --no-commit <the task's commit>`, and check that nothing conflicts.
3. Commit with `git commit -C <the task's commit>`, which keeps the prototype's message.

The task's record (its tests, how they failed and passed, and its diff) is historical: it isn't run again for each
task.

**Checkpoints:** after Task 4 (the declaration and the trigger schema), Task 9 (uploads and starts), Task 16
(schedules) and Task 19 (proofs, Compose and docs), run the milestone's focused tests, then stop for the owner's
review. Group pytest's arguments by directory: pytest 9.1.1 loses a directory's conftest fixtures when the arguments
revisit it after a file of its parent. After Task 19, run the whole suite and the static checks once, then a fresh
reviewer reviews the whole branch.

**Milestone 4's open condition:** the Compose schedule proof's CI step (Task 19) runs in this branch's pull request;
the owner's approval doesn't claim it passed. Production sign-off stays separate (§7.9).

A conflict, a failing focused test or a failing final check is a finding: stop and report it, and don't patch around
it. The diffs below remain the plan's record of every change.

## The owner's rulings (2026-10-03)

Task numbers below are this plan's.

1–2. Split approved: CSV and schedules here; ingress gets its own outline, prototype, plan and PR. Prototype first,
     checkpoints after M1, M2 and M3, then M4 and a whole-branch review.
3. The page activity is deferred and ABI 6 kept, provided the prototype measures a 10,000-row CSV with a representative
   per-row condition (Task 18); revision 8 replaces §8.1's requirement explicitly.
4. A raw `text/csv` body, the cap enforced while reading (Task 6).
5. Key-first digest, consumption by UPDATE, encrypted request-owned CSV metadata; the upload locked and verified, one
   consumer, an exact retry returns its request (Task 8).
6. An encrypted workflow-level default, marked stale when a later version invalidates it, never silently ignored
   (Task 7).
7–8. The cell rules, the caps and API-only CSV starts; `rows` and `row_count` reserved (Tasks 2, 5, 8).
9. Fixed input, actor and catch-up bounds as proposed; cron as Temporal actually reads it; time-zone data verified in
   the shipped image (Tasks 12 and 13).
10. The separate unversioned admission worker; the activity verifies the row against both ids in its workflow's
    identity (Task 14).
11. File the `trigger.rows` issue and fix it in M1 (Task 3).
12. The bounded Compose schedule proof in CI (Task 19).
13. Ingress rulings deferred to 2b-3b's outline; its preview approved nothing.
Added by the owner for M3: the generation and recheck, the tombstone for late ticks, and misses past the catch-up
window detected and reported (Tasks 10, 11 and 15).

**What follows from the rulings, for the owner to check** (decided here, not by the owner):
- The reserved names apply to every version, CSV or not, so existing tests that declare `rows` by hand move to a CSV
  declaration; and a version declaring a CSV can't be a sub-flow's or failure handler's target, since no caller may
  supply its rows.
- Misses are read from Temporal's own counter (`ScheduleInfo.missed_catchup_window`); the tick's activity retries
  without limit and alerts past 10 minutes.

**The owner's corrections (2026-10-04)**, recorded above; filing the amended issue and starting M1 are approved, and the
schedule sync isn't settled until its conflict-token path is proven:
1. Schedule fencing: SDK 1.33.0's `ScheduleHandle.update()` sends no conflict token, so the sync uses a narrow, tested
   RPC path that sends the token from `DescribeScheduleResponse`, proven first in M3 (Tasks 10, 11 and 15). A post-call
   generation check alone can't keep a stale leader from overwriting a newer Temporal state.
2. Upload streaming: the middleware buffers a whole permitted body, so the CSV route streams itself, with the platform
   cap enforced as bytes arrive and the declaration's cap enforced before the remainder is buffered (Task 6).
3. Upload ownership on retries: the key-first lookup stays, without rebuilding rows, but an exact retry is returned
   only to the upload's owner (Task 8).

## The owner's milestone rulings (2026-10-04)

Each milestone was approved as a prototype checkpoint, not production sign-off. The schedule sync's conflict-token path,
provisional in the corrections above, was settled at milestone 3 (ruling 3 below).

1. **Milestone 1.** Accepted: 5 MiB read as 5,242,880 bytes, exact-match headers, no default on a required column, and
   2a's `runs.admit` helper keeping a version's own input schema. A CSV workflow's input schema keeps a plain root (Task
   2) and a sensitive column lists no values (Task 1). The plaintext literals at sensitive schema positions are a
   separate issue (#32), fixed test-first in milestone 1 (Task 4): `enum`, `const` and `examples` in `input_schema` and
   `vars_schema`, nested and behind local `$ref`s; `enum_masked` stays for versions published before it.
2. **Milestone 2.** The error detail grows with the row limit, never with rows times columns; a valid field past
   Python's default limit reads within the file cap; the upload is staged as its bytes (Task 9). The reader's memory,
   about 72 MB for a file at the cap, is deferred to production sizing (§7.9).
3. **Milestone 3, the gate.** Temporal discards a stale schedule update instead of refusing it (Task 10). The generation
   counter goes in the schedule's note, written in the same token-bearing update as the spec, the action and the pause
   state; a generation is marked synced only after a fresh describe shows its marker and a transaction confirms that the
   row still has it and the writer still leads (Tasks 11 and 15). The marker is evidence of a Dewpoint update, not drift
   detection: editing a schedule directly in Temporal isn't supported (§8.2, §4.6).
4. **Milestone 3, the reviews.** A tick decides under its schedule's row, taken exclusively; a PATCH's null is refused
   except for `cron` and `every_s`; a tick's audit entry names its schedule (Task 16). Before erasure ships, the
   transition that sets a tenant `erasing` must raise its schedules' generations in the same transaction, with a
   regression proving they pause; the sync's serial Temporal calls join §7.9's dispatch-latency gate.
5. **Milestone 4.** The 10,000-row measurement is waived: its durations stay labelled estimates, from the measured 1,000
   and 2,500-row points (§8.1, Task 18). The 10,000-row cap stays for v1 and the page activity is deferred. The approval
   doesn't claim the Compose proof has passed CI, and doesn't close §7.9.

## Milestone 1 — The CSV declaration and the trigger schema

### Task 1: A workflow's CSV declaration, checked at publish

**Commit:** `9768077` (prototype `proto/2b3a-v2`); the replay's tree was identical: yes.

**Create:** `backend/src/dewpoint/engine/graph/csv.py`, `backend/tests/engine/graph/test_csv_declaration.py`

**Modify:** `backend/src/dewpoint/engine/graph/model.py`, `backend/src/dewpoint/engine/graph/validate.py`

**What it does:**

`graph.settings.csv` lists the file's columns (header, variable name, type, required,
default, sensitive) and its caps, at most the platform's 10,000 rows and 5 MiB (engine 2b
spec §8.1). Publish refuses a default on a sensitive column, null and empty included, and
`values` on one (`sensitive.literal`: both would be literals in the published graph, §3.8),
duplicate headers or names, a name that isn't an identifier, a default that isn't its type's
canonical value, a required column with a default, and an enum without its values. A graph
without a declaration, and a column without a default, serialize as before, so existing
graph hashes don't change.

- [ ] **Step 1: its tests alone, before its code.** Run: `uv run pytest -n 8 tests/engine/graph/test_csv_declaration.py`. Replay result (exit 1), shortened:

```
FAILED tests/engine/graph/test_csv_declaration.py::test_a_default_must_be_its_types_canonical_value[ip-2001:db8::1-True]
FAILED tests/engine/graph/test_csv_declaration.py::test_a_default_must_be_its_types_canonical_value[mac-aa:bb-False]
FAILED tests/engine/graph/test_csv_declaration.py::test_a_default_must_be_its_types_canonical_value[cidr-10.0.0.0/8-True]
FAILED tests/engine/graph/test_csv_declaration.py::test_a_default_must_be_its_types_canonical_value[ip-010.0.0.1-False]
FAILED tests/engine/graph/test_csv_declaration.py::test_a_default_must_be_its_types_canonical_value[ip-2001:DB8:0::1-False]
FAILED tests/engine/graph/test_csv_declaration.py::test_a_default_must_be_its_types_canonical_value[string-x-True]
FAILED tests/engine/graph/test_csv_declaration.py::test_an_enum_needs_its_values_and_only_an_enum_has_them
FAILED tests/engine/graph/test_csv_declaration.py::test_caps_past_the_platforms_are_refused[caps0-max_rows]
FAILED tests/engine/graph/test_csv_declaration.py::test_a_default_must_be_its_types_canonical_value[string-1-False]
FAILED tests/engine/graph/test_csv_declaration.py::test_a_required_column_takes_no_default
FAILED tests/engine/graph/test_csv_declaration.py::test_caps_past_the_platforms_are_refused[caps1-max_bytes]
FAILED tests/engine/graph/test_csv_declaration.py::test_a_declaration_needs_a_column
FAILED tests/engine/graph/test_csv_declaration.py::test_caps_past_the_platforms_are_refused[caps2-max_rows]
36 failed, 1 passed in 4.58s
```

- [ ] **Step 2: its code, then the same tests.** Replay result (exit 0), shortened:

```
.....................................                                    [100%]
37 passed in 4.49s
```

- [ ] **Step 3: commit.** `git cherry-pick --no-commit 9768077 && git commit -C 9768077`

The diff:

```diff
diff --git a/backend/src/dewpoint/engine/graph/csv.py b/backend/src/dewpoint/engine/graph/csv.py
new file mode 100644
index 0000000..4409a25
--- /dev/null
+++ b/backend/src/dewpoint/engine/graph/csv.py
@@ -0,0 +1,52 @@
+# SPDX-License-Identifier: Apache-2.0
+"""A workflow's CSV input (engine 2b spec §8.1): the column types a declaration may use, the platform's caps, and each
+type's canonical value. A cell is converted to its column's canonical value once, by admission; a declared default
+must already be one, so the version holds exactly what a run would."""
+
+import ipaddress
+import re
+from typing import Any, Literal
+
+CsvType = Literal["string", "integer", "number", "boolean", "mac", "ip", "cidr", "enum"]
+MAX_ROWS = 10_000  # the platform's caps; a declaration may lower them, never raise them
+MAX_BYTES = 5 * 1024 * 1024
+INT_MIN, INT_MAX = -(2**63), 2**63 - 1  # CEL's int
+
+_MAC = re.compile(r"[0-9a-f]{2}(?::[0-9a-f]{2}){5}")  # the canonical form: lowercase, colon-separated
+
+
+def ip(text: str) -> str | None:
+    """`text` as `ipaddress` writes it (IPv6 compressed and lowercase); None if it isn't an address."""
+    try:
+        return str(ipaddress.ip_address(text))
+    except ValueError:
+        return None
+
+
+def cidr(text: str) -> str | None:
+    """`text` as `ipaddress` writes it; None if it isn't a network, or has host bits set."""
+    try:
+        return str(ipaddress.ip_network(text, strict=True))
+    except ValueError:
+        return None
+
+
+def is_canonical(type_: CsvType, value: Any, values: list[str] | None = None) -> bool:
+    """Whether `value` is a canonical value of `type_`: what converting a cell would give, and nothing else."""
+    if type_ == "integer":
+        return type(value) is int and INT_MIN <= value <= INT_MAX
+    if type_ == "number":
+        return type(value) in (int, float)
+    if type_ == "boolean":
+        return type(value) is bool
+    if not isinstance(value, str):
+        return False
+    if type_ == "enum":
+        return value in (values or ())
+    if type_ == "mac":
+        return _MAC.fullmatch(value) is not None
+    if type_ == "ip":
+        return ip(value) == value
+    if type_ == "cidr":
+        return cidr(value) == value
+    return True
diff --git a/backend/src/dewpoint/engine/graph/model.py b/backend/src/dewpoint/engine/graph/model.py
index 79b0789..644f4f6 100644
--- a/backend/src/dewpoint/engine/graph/model.py
+++ b/backend/src/dewpoint/engine/graph/model.py
@@ -4,11 +4,14 @@
 import math
 import uuid
 from collections.abc import Mapping
-from typing import Any, Literal
+from typing import Annotated, Any, Literal
 
-from pydantic import BaseModel, ConfigDict, Field, ValidationError
+from pydantic import BaseModel, ConfigDict, Field, SerializerFunctionWrapHandler, ValidationError, model_serializer
 
 from dewpoint.engine.canonical import sha256_hex
+from dewpoint.engine.graph.csv import MAX_BYTES as CSV_MAX_BYTES
+from dewpoint.engine.graph.csv import MAX_ROWS as CSV_MAX_ROWS
+from dewpoint.engine.graph.csv import CsvType
 from dewpoint.engine.graph.diagnostics import Diagnostic
 
 KEY_PATTERN = r"^[a-z][a-z0-9_]{0,62}$"
@@ -77,12 +80,46 @@ class DeclassifySite(_Strict):
     field: str = Field(max_length=200)
 
 
+class CsvColumn(_Strict):
+    """One column of a CSV declaration (engine 2b spec §8.1). Its `default` is omitted unless written: an omitted
+    default is allowed on a sensitive column, a written one (even null) isn't (§3.8), so the two stay distinct."""
+
+    header: str = Field(min_length=1, max_length=200)
+    name: str = Field(min_length=1, max_length=63)  # `item.<name>`: publish checks it's an identifier
+    type: CsvType
+    required: bool = False
+    default: Any = None
+    sensitive: bool = False
+    values: list[Annotated[str, Field(max_length=200)]] | None = Field(default=None, max_length=200)  # an enum's
+
+    @model_serializer(mode="wrap")
+    def _written_default(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
+        data: dict[str, Any] = handler(self)
+        if "default" not in self.model_fields_set:
+            data.pop("default", None)
+        return data
+
+
+class CsvSettings(_Strict):
+    columns: list[CsvColumn] = Field(min_length=1, max_length=200)
+    max_rows: int = Field(default=CSV_MAX_ROWS, ge=1, le=CSV_MAX_ROWS)
+    max_bytes: int = Field(default=CSV_MAX_BYTES, ge=1, le=CSV_MAX_BYTES)
+
+
 class GraphSettings(_Strict):
     input_schema: dict[str, Any] = Field(default_factory=_object_schema)
     vars_schema: dict[str, Any] = Field(default_factory=_vars_schema)  # every variable declares a default
     outputs: dict[str, Any] = Field(default_factory=dict)  # evaluated when the run succeeds
     failure_handler: uuid.UUID | None = None  # a workflow id, pinned to its active version at publish
     declassify: list[DeclassifySite] = Field(default_factory=list, max_length=200)  # §4.3: listed, never implied
+    csv: CsvSettings | None = None  # 2b spec §8.1; absent from the document unless declared, so hashes stay
+
+    @model_serializer(mode="wrap")
+    def _declared_csv(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
+        data: dict[str, Any] = handler(self)
+        if self.csv is None:
+            data.pop("csv", None)
+        return data
 
 
 class Graph(_Strict):
diff --git a/backend/src/dewpoint/engine/graph/validate.py b/backend/src/dewpoint/engine/graph/validate.py
index 385a783..72d1a47 100644
--- a/backend/src/dewpoint/engine/graph/validate.py
+++ b/backend/src/dewpoint/engine/graph/validate.py
@@ -16,8 +16,9 @@ from jsonschema.exceptions import SchemaError
 from dewpoint.engine.cel.record import ExpressionRecord
 from dewpoint.engine.graph import cel_check
 from dewpoint.engine.graph import liveness as lv
+from dewpoint.engine.graph.csv import is_canonical
 from dewpoint.engine.graph.diagnostics import Diagnostic, Severity
-from dewpoint.engine.graph.model import Graph, GraphNode
+from dewpoint.engine.graph.model import CsvSettings, Graph, GraphNode
 from dewpoint.engine.graph.schemas import (
     PathError,
     Resolved,
@@ -188,6 +189,19 @@ _SENSITIVE_LITERAL = (
 )
 
 
+_CSV_HEADER = "Another column already has this header: each header maps to one column."
+_CSV_NAME = "Another column already has this name: each column is one field of a row."
+_CSV_IDENT = "Column names are lowercase identifiers, and not `in`, `true`, `false` or `null`."
+_CSV_VALUES = "An `enum` column lists its values, and only an `enum` column has them."
+_CSV_SENSITIVE_VALUES = (
+    "A sensitive column can't list its values: they'd be written into the workflow. Make it a `string` column."
+)
+_CSV_REQUIRED = "A required column takes no default: an empty cell is refused, so the default would never apply."
+_CSV_DEFAULT = (
+    "The default isn't a value of the column's type, as a cell would be converted: a number for `integer` and "
+    "`number`, true or false for `boolean`, one of the values for `enum`, lowercase colon form for `mac`, and "
+    "an address or network as Python's `ipaddress` writes it for `ip` and `cidr` (no host bits set)."
+)
 _TIMER = "A wait's duration is visible in the run's history, so it can't come from sensitive data."
 _FAIL_MESSAGE = "A failure's message is recorded as it is, so it can't hold sensitive data."
 _SUBFLOW_INPUT = "This passes sensitive data into a field the sub-flow doesn't mark sensitive."
@@ -319,6 +333,37 @@ def _sensitive_defaults(label: str, schema: Mapping[str, Any]) -> list[Diagnosti
     ]
 
 
+def _csv_declaration(csv: CsvSettings | None) -> list[Diagnostic]:
+    """A CSV declaration's columns (engine 2b spec §8.1): unique headers and identifier names, an enum's values, and a
+    default that's its type's canonical value, never on a sensitive column (§3.8) nor beside `required`."""
+    out: list[Diagnostic] = []
+    headers: set[str] = set()
+    names: set[str] = set()
+    for i, c in enumerate(csv.columns if csv else ()):
+        where = f"/settings/csv/columns/{i}"
+        if c.header in headers:
+            out.append(Diagnostic(code="csv.duplicate_header", field=f"{where}/header", message=_CSV_HEADER))
+        if c.name in names:
+            out.append(Diagnostic(code="csv.duplicate_name", field=f"{where}/name", message=_CSV_NAME))
+        elif not IDENT.match(c.name) or c.name in CEL_KEYWORDS:
+            out.append(Diagnostic(code="csv.invalid_name", field=f"{where}/name", message=_CSV_IDENT))
+        headers.add(c.header)
+        names.add(c.name)
+        if (c.type == "enum") != (c.values is not None):
+            out.append(Diagnostic(code="csv.enum_values", field=f"{where}/values", message=_CSV_VALUES))
+        elif c.sensitive and c.values is not None:  # literals in the published graph (§3.8)
+            out.append(Diagnostic(code="sensitive.literal", field=f"{where}/values", message=_CSV_SENSITIVE_VALUES))
+        if "default" not in c.model_fields_set:
+            continue
+        if c.sensitive:
+            out.append(Diagnostic(code="sensitive.default", field=f"{where}/default", message=_SENSITIVE_LITERAL))
+        elif c.required:
+            out.append(Diagnostic(code="csv.required_default", field=f"{where}/default", message=_CSV_REQUIRED))
+        elif not is_canonical(c.type, c.default, c.values):
+            out.append(Diagnostic(code="csv.bad_default", field=f"{where}/default", message=_CSV_DEFAULT))
+    return out
+
+
 def _settings(graph: Graph) -> list[Diagnostic]:
     st = graph.settings
     out: list[Diagnostic] = []
@@ -358,6 +403,7 @@ def _settings(graph: Graph) -> list[Diagnostic]:
     for label, schema in (("input_schema", st.input_schema), ("vars_schema", st.vars_schema)):
         if not any((d.field or "").startswith(f"/settings/{label}") for d in out):
             out += _sensitive_defaults(label, schema)
+    out += _csv_declaration(st.csv)
     if any((d.field or "").startswith("/settings/vars_schema") for d in out):  # never run defaults through it
         return out
     props = st.vars_schema.get("properties", {})
diff --git a/backend/tests/engine/graph/test_csv_declaration.py b/backend/tests/engine/graph/test_csv_declaration.py
new file mode 100644
index 0000000..1de474b
--- /dev/null
+++ b/backend/tests/engine/graph/test_csv_declaration.py
@@ -0,0 +1,141 @@
+# SPDX-License-Identifier: Apache-2.0
+"""A workflow's CSV declaration (engine 2b spec §8.1): `graph.settings.csv` lists the file's columns (header, variable
+name, type, required, default, sensitive) and its caps, at most the platform's 10,000 rows and 5 MiB. Publish refuses a
+default on a sensitive column (§3.8), duplicate headers or names, a default its type rejects, and a required column with
+a default. A graph without a declaration serializes as it always did, so its hash doesn't change."""
+
+from typing import Any
+
+import pytest
+
+from dewpoint.engine.graph.model import GraphFormatError, graph_hash, graph_json, parse_graph
+from dewpoint.engine.graph.validate import ValidationContext, validate
+from dewpoint.plugins.flow import PLUGIN
+from tests.support.catalog import catalog
+from tests.support.graphs import G
+from tests.support.plugins.testkit import TESTKIT
+
+CAT = catalog(PLUGIN, TESTKIT)
+
+
+def column(name: str, type_: str = "string", **extra: Any) -> dict[str, Any]:
+    return {"header": name.title(), "name": name, "type": type_, **extra}
+
+
+def declared(*columns: dict[str, Any], **caps: Any) -> G:
+    g = G().node("a", "testkit.echo@1", {"value": 1})
+    g.settings = {"csv": {"columns": list(columns), **caps}}
+    return g
+
+
+def codes(g: G) -> list[tuple[str, str | None]]:
+    return [(d.code, d.field) for d in validate(g.build(), ValidationContext(catalog=CAT)).diagnostics]
+
+
+def test_a_graph_without_a_csv_serializes_as_before() -> None:
+    g = G().node("a", "testkit.echo@1", {"value": 1}).build()
+    assert "csv" not in graph_json(g)["settings"]
+    assert graph_hash(g) == graph_hash(parse_graph(graph_json(g)))
+
+
+def test_a_declaration_round_trips_and_an_omitted_default_stays_omitted() -> None:
+    g = declared(column("site"), column("vlan", "integer", default=1), column("psk", sensitive=True)).build()
+    dumped = graph_json(g)["settings"]["csv"]
+    assert "default" not in dumped["columns"][0] and "default" not in dumped["columns"][2]
+    assert dumped["columns"][1]["default"] == 1
+    assert (dumped["max_rows"], dumped["max_bytes"]) == (10_000, 5 * 1024 * 1024)
+    assert graph_json(parse_graph(graph_json(g))) == graph_json(g)
+
+
+def test_a_valid_declaration_publishes() -> None:
+    g = declared(
+        column("site", required=True),
+        column("mac", "mac"),
+        column("net", "cidr", default="10.0.0.0/8"),
+        column("kind", "enum", values=["ap", "switch"]),
+        column("psk", sensitive=True),
+    )
+    assert codes(g) == []
+
+
+@pytest.mark.parametrize("default", [None, "", "s3cret"])
+def test_publish_refuses_any_default_on_a_sensitive_column(default: Any) -> None:
+    assert codes(declared(column("site"), column("psk", sensitive=True, default=default))) == [
+        ("sensitive.default", "/settings/csv/columns/1/default")
+    ]
+
+
+def test_publish_refuses_the_values_of_a_sensitive_column() -> None:
+    """An enum's values are literals in the published graph (§3.8): a sensitive column can't list them, whatever the
+    start form masks."""
+    assert codes(declared(column("key", "enum", sensitive=True, values=["k1", "k2"]))) == [
+        ("sensitive.literal", "/settings/csv/columns/0/values")
+    ]
+
+
+def test_publish_refuses_duplicate_headers_and_names() -> None:
+    assert codes(declared(column("site"), {"header": "Site", "name": "other", "type": "string"})) == [
+        ("csv.duplicate_header", "/settings/csv/columns/1/header")
+    ]
+    assert codes(declared(column("site"), {"header": "Other", "name": "site", "type": "string"})) == [
+        ("csv.duplicate_name", "/settings/csv/columns/1/name")
+    ]
+
+
+@pytest.mark.parametrize("name", ["Site", "1st", "in", "null"])
+def test_publish_refuses_a_name_that_isnt_an_identifier(name: str) -> None:
+    assert codes(declared({"header": "H", "name": name, "type": "string"})) == [
+        ("csv.invalid_name", "/settings/csv/columns/0/name")
+    ]
+
+
+@pytest.mark.parametrize(
+    ("type_", "default", "ok"),
+    [
+        ("integer", 5, True), ("integer", "5", False), ("integer", True, False), ("integer", 2**63, False),
+        ("number", 1.5, True), ("number", "1.5", False),
+        ("boolean", False, True), ("boolean", "no", False),
+        ("mac", "aa:bb:cc:dd:ee:ff", True), ("mac", "AA-BB-CC-DD-EE-FF", False), ("mac", "aa:bb", False),
+        ("ip", "10.0.0.1", True), ("ip", "2001:db8::1", True), ("ip", "2001:DB8:0::1", False),
+        ("ip", "010.0.0.1", False),
+        ("cidr", "10.0.0.0/8", True), ("cidr", "10.0.0.1/8", False),
+        ("string", "x", True), ("string", 1, False),
+    ],
+)  # fmt: skip
+def test_a_default_must_be_its_types_canonical_value(type_: str, default: Any, ok: bool) -> None:
+    found = codes(declared(column("c", type_, default=default)))
+    assert found == ([] if ok else [("csv.bad_default", "/settings/csv/columns/0/default")])
+
+
+def test_an_enum_needs_its_values_and_only_an_enum_has_them() -> None:
+    assert codes(declared(column("kind", "enum"))) == [("csv.enum_values", "/settings/csv/columns/0/values")]
+    assert codes(declared(column("site", values=["a"]))) == [("csv.enum_values", "/settings/csv/columns/0/values")]
+    assert codes(declared(column("kind", "enum", values=["ap"], default="switch"))) == [
+        ("csv.bad_default", "/settings/csv/columns/0/default")
+    ]
+
+
+def test_a_required_column_takes_no_default() -> None:
+    assert codes(declared(column("vlan", "integer", required=True, default=1))) == [
+        ("csv.required_default", "/settings/csv/columns/0/default")
+    ]
+
+
+@pytest.mark.parametrize(
+    ("caps", "where"),
+    [
+        ({"max_rows": 10_001}, "max_rows"),
+        ({"max_bytes": 5 * 1024 * 1024 + 1}, "max_bytes"),
+        ({"max_rows": 0}, "max_rows"),
+    ],
+)
+def test_caps_past_the_platforms_are_refused(caps: dict[str, int], where: str) -> None:
+    with pytest.raises(GraphFormatError) as e:
+        declared(column("site"), **caps).build()
+    assert [d.field for d in e.value.diagnostics] == [f"/settings/csv/{where}"]
+
+
+def test_a_declaration_needs_a_column() -> None:
+    with pytest.raises(GraphFormatError) as e:
+        declared().build()
+    assert [d.field for d in e.value.diagnostics] == ["/settings/csv/columns"]
```

### Task 2: The trigger schema, with a CSV's rows and their count; both names reserved

**Commit:** `94d64db` (prototype `proto/2b3a-v2`); the replay's tree was identical: yes.

**Create:** `backend/tests/engine/graph/test_trigger_schema.py`

**Modify:** `backend/src/dewpoint/apps/admission.py`, `backend/src/dewpoint/apps/api/routes/run_requests.py`, `backend/src/dewpoint/apps/forms.py`, `backend/src/dewpoint/apps/inputs.py`, `backend/src/dewpoint/apps/workflow_ops.py`, `backend/src/dewpoint/engine/graph/csv.py`, `backend/src/dewpoint/engine/graph/validate.py`, `backend/tests/apps/api/test_run_requests_api.py`, `backend/tests/apps/test_admission.py`, `backend/tests/apps/test_workflow_ops.py`, `backend/tests/engine/graph/test_validate_declassify.py`, `backend/tests/engine/graph/test_validate_taint.py`

**What it does:**

A version's trigger schema is one pure function of its settings: its `input_schema`, plus,
for a version declaring a CSV, `rows` (closed row objects, sensitive columns marked, a column
with a default always filled in) and `row_count` (engine 2b spec §8.1). Publish types and
taints every `trigger.*` read by it, and admission validates and claims by it, so a CSV
workflow can't start without its rows.

`rows` and `row_count` are reserved: publish refuses them as input properties, CSV or not,
admission refuses a caller's input that holds either (any source), and a version declaring
a CSV is no sub-flow's or failure handler's target, since no caller may supply its rows.
A CSV workflow's input schema holds only `type`, `properties`, `required`,
`additionalProperties`, `$defs` and annotations at its root (`csv.input_schema`): any other
root keyword (a closed `allOf` branch, `not`, a root `$ref`, `unevaluatedProperties`,
`propertyNames`, `maxProperties`, `dependentRequired`, …) could refuse the rows, and a root
`x-sensitive` would taint their public count; a test proves the accepted shapes admit them.
The start form returns the declaration. The taint and declassification tests that declared
`rows` by hand now declare a CSV.

- [ ] **Step 1: its tests alone, before its code.** Run: `uv run pytest -n 8 tests/apps/api/test_run_requests_api.py tests/apps/test_admission.py tests/apps/test_workflow_ops.py tests/engine/graph/test_trigger_schema.py tests/engine/graph/test_validate_declassify.py tests/engine/graph/test_validate_taint.py`. Replay result (exit 1), shortened:

```
    assert False
     +  where False = ValidationResult(diagnostics=(Diagnostic(code='ref.unknown_field', message='`trigger.rows`: there is no field `rows`',...6e758d56-8496-5840-93d7-83ebc24f7e86', '/value'), ('6f64445c-334e-58c1-ad3e-d7531ec52741', '/value')), output_taint={}).ok
<replay>/backend/tests/engine/graph/test_validate_taint.py:42: AssertionError: (Diagnostic(code='ref.unknown_field', message='`trigger.rows`: there is no field `rows`', node=UUID('76b80920-b0b9-5f5...re is no field `rows`', node=UUID('fd15e408-aacd-59fe-a3cc-e6168b577030'), field='/value', fix=None, severity='error'))
=========================== short test summary info ============================
FAILED tests/engine/graph/test_validate_taint.py::test_item_takes_its_loops_element_taint_field_by_field_and_index_never
FAILED tests/engine/graph/test_validate_taint.py::test_collected_items_take_their_collect_taint_and_the_count_stays_plain
FAILED tests/engine/graph/test_validate_taint.py::test_the_workflows_outputs_record_their_taint
FAILED tests/apps/test_workflow_ops.py::test_publish_refuses_a_sub_flow_or_failure_handler_that_declares_a_csv
FAILED tests/engine/graph/test_validate_declassify.py::test_a_loop_over_tainted_items_must_be_listed_except_over_trigger_rows
FAILED tests/engine/graph/test_validate_taint.py::test_cel_and_templates_are_tainted_when_anything_they_read_is
ERROR tests/apps/api/test_run_requests_api.py - ImportError while importing t...
ERROR tests/apps/test_admission.py - ImportError while importing test module ...
ERROR tests/engine/graph/test_trigger_schema.py - ImportError while importing...
6 failed, 30 passed, 3 errors in 12.80s
```

- [ ] **Step 2: its code, then the same tests.** Replay result (exit 0), shortened:

```
........................................................................ [ 64%]
........................................                                 [100%]
112 passed in 15.54s
```

- [ ] **Step 3: commit.** `git cherry-pick --no-commit 94d64db && git commit -C 94d64db`

The diff:

```diff
diff --git a/backend/src/dewpoint/apps/admission.py b/backend/src/dewpoint/apps/admission.py
index 803a0ff..751b3cd 100644
--- a/backend/src/dewpoint/apps/admission.py
+++ b/backend/src/dewpoint/apps/admission.py
@@ -26,7 +26,7 @@ from sqlalchemy import func, select
 from sqlalchemy.dialects.postgresql import insert
 from sqlalchemy.ext.asyncio import AsyncSession
 
-from dewpoint.apps.inputs import InputRefusedError, claim_input
+from dewpoint.apps.inputs import INPUT_INVALID, RESERVED_INPUT, InputRefusedError, claim_input
 from dewpoint.apps.workflow_ops import abi_reasons
 from dewpoint.core.audit import service as audit
 from dewpoint.core.claims import service as claims
@@ -40,6 +40,7 @@ from dewpoint.core.platform.service import NOT_RECORDED, PRODUCTION, recorded
 from dewpoint.core.plugins import lifecycle
 from dewpoint.core.requests import digest as digests
 from dewpoint.core.workflows.service import lock_for_admission, other_abi
+from dewpoint.engine.graph.csv import RESERVED, trigger_schema
 from dewpoint.engine.runtime.activities import LIVE, SIMULATE
 
 INTERACTIVE = ("manual", "rerun", "dev")  # refused while the gate is off; a refusal is raised
@@ -236,7 +237,9 @@ async def _frozen(
     if blocked:
         reason = NODE_TYPE_RETIRED if any(e.kind == "node" for e in blocked) else CEL_PROFILE_RETIRED
         raise _Refused(reason, [f"{entry} has been retired." for entry in blocked], version.id)
-    schema = (version.graph.get("settings") or {}).get("input_schema", {"type": "object"})
+    if any(name in fields["input"] for name in RESERVED):  # only a CSV upload supplies them (§8.1)
+        raise _Refused(INPUT_INVALID, [RESERVED_INPUT], version.id)
+    schema = trigger_schema(version.graph.get("settings") or {})
     try:
         envelope = await claim_input(
             s, keys, tenant_id=tenant_id, run_id=request_id, root_run_id=request_id, schema=schema,
diff --git a/backend/src/dewpoint/apps/api/routes/run_requests.py b/backend/src/dewpoint/apps/api/routes/run_requests.py
index b2c683e..3ba5ad3 100644
--- a/backend/src/dewpoint/apps/api/routes/run_requests.py
+++ b/backend/src/dewpoint/apps/api/routes/run_requests.py
@@ -14,7 +14,7 @@ from pydantic import BaseModel, ConfigDict, Field
 from sqlalchemy.ext.asyncio import AsyncSession
 
 from dewpoint.apps import admission, cancels
-from dewpoint.apps.forms import form_fields
+from dewpoint.apps.forms import csv_form, form_fields
 from dewpoint.apps.inputs import INPUT_INVALID
 from dewpoint.core.authz.permissions import P
 from dewpoint.core.claims import service as claims
@@ -124,7 +124,7 @@ async def start_form(
     ctx: TenantContext = Depends(require(P.RUN_START)),
     db: AsyncSession = Depends(get_db, scope="function"),
 ) -> dict[str, object]:
-    """The active version's input, as a form: its typed fields, sensitive ones masked. CSV starts come with 2b-3."""
+    """The active version's input, as a form: its typed fields and its CSV declaration, sensitive ones masked."""
     workflow = await db.get(Workflow, workflow_id)  # row-level security: the caller's tenant's only
     if workflow is None:
         raise HTTPException(404, detail={"error": "not_found"})
@@ -137,7 +137,7 @@ async def start_form(
         "workflow_id": str(workflow.id),
         "version_id": str(version.id),
         "fields": form_fields(version.input_schema or {}),
-        "csv": None,
+        "csv": csv_form((version.graph.get("settings") or {}).get("csv")),
     }
 
 
diff --git a/backend/src/dewpoint/apps/forms.py b/backend/src/dewpoint/apps/forms.py
index a3d2530..40918fb 100644
--- a/backend/src/dewpoint/apps/forms.py
+++ b/backend/src/dewpoint/apps/forms.py
@@ -2,7 +2,8 @@
 """A start form's fields (engine 2b spec §7.7): the typed top-level fields of a version's `input_schema`, for the UI.
 A sensitive field shows its type and whether it's required, never a value the schema holds for it: its default and
 its enum are masked (publish refuses a sensitive literal anyway, §3.8). `x-dewpoint-picker` is passed through for
-sub-project 3's pickers."""
+sub-project 3's pickers. A CSV declaration (§8.1) is described with its columns: a sensitive one has no default and no
+values to show, since publish refuses them."""
 
 from collections.abc import Mapping
 from typing import Any
@@ -34,3 +35,19 @@ def form_fields(schema: Mapping[str, Any]) -> list[dict[str, Any]]:
             field["picker"] = prop[PICKER]
         fields.append(field)
     return fields
+
+
+def csv_form(csv: Mapping[str, Any] | None) -> dict[str, Any] | None:
+    """A version's CSV declaration, as the graph document holds it, for the upload and mapping step."""
+    if not csv:
+        return None
+    columns: list[dict[str, Any]] = []
+    for c in csv["columns"]:
+        column = {k: c[k] for k in ("header", "name", "type")}
+        column |= {"required": bool(c.get("required")), "sensitive": bool(c.get("sensitive"))}
+        if "default" in c:  # never on a sensitive column: publish refuses it (§3.8)
+            column["default"] = c["default"]
+        if c.get("values") is not None:  # never a sensitive column's: publish refuses them (§3.8)
+            column["values"] = c["values"]
+        columns.append(column)
+    return {"max_rows": csv["max_rows"], "max_bytes": csv["max_bytes"], "columns": columns}
diff --git a/backend/src/dewpoint/apps/inputs.py b/backend/src/dewpoint/apps/inputs.py
index ee733c5..299f772 100644
--- a/backend/src/dewpoint/apps/inputs.py
+++ b/backend/src/dewpoint/apps/inputs.py
@@ -25,6 +25,7 @@ from dewpoint.engine.runtime.projection import location
 from dewpoint.engine.split import split
 
 FORGED = "The run's input holds the reserved key `$claim`, which only Dewpoint writes."
+RESERVED_INPUT = "The run's input holds `rows` or `row_count`, which only a CSV upload supplies."
 _REASONS = 5  # an input that breaks more rules is told about the first ones
 
 
diff --git a/backend/src/dewpoint/apps/workflow_ops.py b/backend/src/dewpoint/apps/workflow_ops.py
index 1a754b8..5ca1a94 100644
--- a/backend/src/dewpoint/apps/workflow_ops.py
+++ b/backend/src/dewpoint/apps/workflow_ops.py
@@ -37,6 +37,11 @@ async def _lifecycle_locked() -> None:
     """Hook that runs right after the lifecycle locks are held. A no-op; the race tests pause here."""
 
 
+def declares_csv(graph: Mapping[str, Any]) -> bool:
+    """Whether a version's graph document declares a CSV (engine 2b spec §8.1)."""
+    return bool((graph.get("settings") or {}).get("csv"))
+
+
 @dataclass(frozen=True)
 class Checked:
     graph: Graph | None
@@ -56,7 +61,10 @@ async def check_draft(s: AsyncSession, tenant_id: uuid.UUID, draft: Any, setting
     ctx = ValidationContext(
         catalog=catalog,
         subflows={
-            wid: SubflowInfo(wid, v.id, v.input_schema, v.output_schema, v.output_taint) for wid, v in pins.items()
+            wid: SubflowInfo(
+                wid, v.id, v.input_schema, v.output_schema, v.output_taint, declares_csv=declares_csv(v.graph)
+            )
+            for wid, v in pins.items()
         },
         max_run_duration=timedelta(days=settings.max_run_duration_days),
     )
diff --git a/backend/src/dewpoint/engine/graph/csv.py b/backend/src/dewpoint/engine/graph/csv.py
index 4409a25..54f7ee9 100644
--- a/backend/src/dewpoint/engine/graph/csv.py
+++ b/backend/src/dewpoint/engine/graph/csv.py
@@ -5,12 +5,23 @@ must already be one, so the version holds exactly what a run would."""
 
 import ipaddress
 import re
+from collections.abc import Mapping
 from typing import Any, Literal
 
 CsvType = Literal["string", "integer", "number", "boolean", "mac", "ip", "cidr", "enum"]
 MAX_ROWS = 10_000  # the platform's caps; a declaration may lower them, never raise them
 MAX_BYTES = 5 * 1024 * 1024
 INT_MIN, INT_MAX = -(2**63), 2**63 - 1  # CEL's int
+RESERVED = ("rows", "row_count")  # a trigger's: only admission writes them, from a CSV upload
+# The keywords a CSV's input schema may hold at its root: none can refuse the `rows` and `row_count` the trigger
+# schema adds there (`additionalProperties` skips declared properties). Any other (a closed `allOf` branch, a `$ref`,
+# `propertyNames`, `maxProperties`, `x-sensitive`, ...) could refuse them or taint the public count.
+INPUT_ROOT = frozenset(
+    {"type", "properties", "required", "additionalProperties", "$defs", "$schema", "$comment"}
+    | {"title", "description", "examples", "default", "deprecated", "readOnly", "writeOnly"}
+)
+_JSON_TYPES = {"integer": "integer", "number": "number", "boolean": "boolean"}  # the others are strings
+_JSON_TYPES.update({t: "string" for t in ("string", "mac", "ip", "cidr", "enum")})
 
 _MAC = re.compile(r"[0-9a-f]{2}(?::[0-9a-f]{2}){5}")  # the canonical form: lowercase, colon-separated
 
@@ -50,3 +61,43 @@ def is_canonical(type_: CsvType, value: Any, values: list[str] | None = None) ->
     if type_ == "cidr":
         return cidr(value) == value
     return True
+
+
+def _column_schema(column: Mapping[str, Any]) -> dict[str, Any]:
+    type_ = column["type"]
+    schema: dict[str, Any] = {"type": _JSON_TYPES[type_], "title": column["header"]}
+    if type_ in ("mac", "ip", "cidr"):
+        schema["format"] = type_  # a hint: admission converted every cell to its canonical form already
+    if column.get("values") is not None:
+        schema["enum"] = list(column["values"])
+    if "default" in column:
+        schema["default"] = column["default"]
+    if column.get("sensitive"):
+        schema["x-sensitive"] = True
+    return schema
+
+
+def trigger_schema(settings: Mapping[str, Any]) -> dict[str, Any]:
+    """The schema of a run's trigger, from its version's settings (as the graph document holds them): the
+    `input_schema`, plus, when the version declares a CSV, `rows` (each a closed object of its columns, the sensitive
+    ones marked, a column with a default always filled in) and `row_count`. Publish types and taints `trigger.*` by
+    it, and admission validates and claims by it. `settings` is never changed."""
+    schema: dict[str, Any] = dict(settings.get("input_schema") or {"type": "object"})
+    csv = settings.get("csv")
+    if not csv:
+        return schema
+    columns = csv["columns"]
+    row = {
+        "type": "object",
+        "properties": {c["name"]: _column_schema(c) for c in columns},
+        "required": [c["name"] for c in columns if c.get("required") or "default" in c],
+        "additionalProperties": False,
+    }
+    max_rows = csv.get("max_rows", MAX_ROWS)
+    schema["properties"] = {
+        **(schema.get("properties") or {}),
+        "rows": {"type": "array", "maxItems": max_rows, "items": row},
+        "row_count": {"type": "integer", "minimum": 0, "maximum": max_rows},
+    }
+    schema["required"] = [*(schema.get("required") or ()), *RESERVED]
+    return schema
diff --git a/backend/src/dewpoint/engine/graph/validate.py b/backend/src/dewpoint/engine/graph/validate.py
index 72d1a47..6685ace 100644
--- a/backend/src/dewpoint/engine/graph/validate.py
+++ b/backend/src/dewpoint/engine/graph/validate.py
@@ -16,7 +16,9 @@ from jsonschema.exceptions import SchemaError
 from dewpoint.engine.cel.record import ExpressionRecord
 from dewpoint.engine.graph import cel_check
 from dewpoint.engine.graph import liveness as lv
-from dewpoint.engine.graph.csv import is_canonical
+from dewpoint.engine.graph.csv import INPUT_ROOT as CSV_INPUT_ROOT
+from dewpoint.engine.graph.csv import RESERVED as CSV_RESERVED
+from dewpoint.engine.graph.csv import is_canonical, trigger_schema
 from dewpoint.engine.graph.diagnostics import Diagnostic, Severity
 from dewpoint.engine.graph.model import CsvSettings, Graph, GraphNode
 from dewpoint.engine.graph.schemas import (
@@ -88,6 +90,7 @@ class SubflowInfo:
     input_schema: Mapping[str, Any]
     output_schema: Mapping[str, Any]
     output_taint: Mapping[str, Any] | None = None  # its version's: each output's `Shape` JSON; None: unknown
+    declares_csv: bool = False
 
 
 @dataclass(frozen=True)
@@ -196,12 +199,19 @@ _CSV_VALUES = "An `enum` column lists its values, and only an `enum` column has
 _CSV_SENSITIVE_VALUES = (
     "A sensitive column can't list its values: they'd be written into the workflow. Make it a `string` column."
 )
+_CSV_INPUT_ROOT = (
+    "A workflow that takes a CSV keeps its input schema plain at the root (`properties`, `required`, "
+    "`additionalProperties`, `$defs` and annotations): this keyword could refuse the file's `rows` and `row_count`, "
+    "or make their count sensitive. Move the constraint into a property's own schema."
+)
 _CSV_REQUIRED = "A required column takes no default: an empty cell is refused, so the default would never apply."
 _CSV_DEFAULT = (
     "The default isn't a value of the column's type, as a cell would be converted: a number for `integer` and "
     "`number`, true or false for `boolean`, one of the values for `enum`, lowercase colon form for `mac`, and "
     "an address or network as Python's `ipaddress` writes it for `ip` and `cidr` (no host bits set)."
 )
+_RESERVED = "`rows` and `row_count` are a CSV's: declare the file in `settings.csv`, and its rows arrive there."
+_CSV_TARGET = "This workflow takes a CSV file, which only a start with an upload supplies: no workflow can start it."
 _TIMER = "A wait's duration is visible in the run's history, so it can't come from sensitive data."
 _FAIL_MESSAGE = "A failure's message is recorded as it is, so it can't hold sensitive data."
 _SUBFLOW_INPUT = "This passes sensitive data into a field the sub-flow doesn't mark sensitive."
@@ -404,6 +414,17 @@ def _settings(graph: Graph) -> list[Diagnostic]:
         if not any((d.field or "").startswith(f"/settings/{label}") for d in out):
             out += _sensitive_defaults(label, schema)
     out += _csv_declaration(st.csv)
+    props = st.input_schema.get("properties")
+    out += [
+        Diagnostic(code="settings.reserved_name", field=f"/settings/input_schema/properties/{name}", message=_RESERVED)
+        for name in CSV_RESERVED
+        if isinstance(props, Mapping) and name in props
+    ]
+    out += [  # a schema that could refuse the generated `rows` would publish a CSV no start can satisfy
+        Diagnostic(code="csv.input_schema", field=f"/settings/input_schema/{key}", message=_CSV_INPUT_ROOT)
+        for key in st.input_schema
+        if st.csv is not None and key not in CSV_INPUT_ROOT
+    ]
     if any((d.field or "").startswith("/settings/vars_schema") for d in out):  # never run defaults through it
         return out
     props = st.vars_schema.get("properties", {})
@@ -485,7 +506,8 @@ class _Validator:
         self.availability: dict[tuple[Any, ...], bool] = {}
         self.expressions: list[ExpressionRecord] = []
         # taint (2b spec §4.1): its sources, each node's output, each loop's element, and what this pass learns
-        self.trigger_shape = from_schema(graph.settings.input_schema) if settings_ok else TAINTED
+        self.trigger_root = trigger_schema(graph.settings.model_dump(mode="json")) if settings_ok else {}
+        self.trigger_shape = from_schema(self.trigger_root) if settings_ok else TAINTED
         self.vars_shape = from_schema(self.vars_root)
         self.out_taint: dict[uuid.UUID, Shape] = {}
         self.item_taint: dict[uuid.UUID, Shape] = {}
@@ -667,6 +689,8 @@ class _Validator:
                     self._schema_errors(n.id, pointer_str(("assignments", name)), schema, value, inner)
         if spec.ref == C.RUN_WORKFLOW:
             info = self._subflow(n)
+            if info is not None and info.declares_csv:
+                self.err("subflow.csv_target", _CSV_TARGET, node=n.id, fld="/workflow_id")
             if info is not None:
                 inner = [p[1:] for p in envelopes if p[:1] == ("input",)]
                 self._schema_errors(n.id, "/input", info.input_schema, stripped.get("input", {}), inner)
@@ -889,7 +913,7 @@ class _Validator:
     def _resolve_typed(self, site: _Site, p: RefPath) -> Resolved | None:
         try:
             if p.root == "trigger":
-                return navigate(self.g.settings.input_schema, p.rest)
+                return navigate(self.trigger_root, p.rest)
             if p.root == "run":
                 return Resolved(RUN_SCHEMAS[str(p.section)], False)
             if p.root == "vars":
@@ -1041,7 +1065,7 @@ class _Validator:
         self, site: _Site, p: RefPath, find: Callable[[Any, Sequence[str | int], Any], tuple[int, ...]]
     ) -> tuple[int, ...]:
         if p.root == "trigger":
-            return find(self.g.settings.input_schema, p.rest, None)
+            return find(self.trigger_root, p.rest, None)
         if p.root == "vars" and p.name in self.vars:
             return find(self.vars_root, p.rest, self.vars[str(p.name)])
         if p.root in ("item", "loops") and p.section == "item":
@@ -1164,6 +1188,8 @@ class _Validator:
             )
         else:
             self.failure_handler_version_id = info.version_id
+            if info.declares_csv:
+                self.err("subflow.csv_target", _CSV_TARGET, fld="/settings/failure_handler")
 
 
 class _CelSite:
diff --git a/backend/tests/apps/api/test_run_requests_api.py b/backend/tests/apps/api/test_run_requests_api.py
index be49930..51b3b45 100644
--- a/backend/tests/apps/api/test_run_requests_api.py
+++ b/backend/tests/apps/api/test_run_requests_api.py
@@ -180,6 +180,38 @@ async def test_the_start_form_describes_the_active_versions_input(
     }  # fmt: skip
 
 
+async def test_the_start_form_describes_a_csv_declaration(
+    keyed_app, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings
+) -> None:
+    """The CSV declaration (engine 2b spec §8.1): each column, a sensitive one with neither default nor values."""
+    csv = {
+        "columns": [
+            {"header": "Site", "name": "site", "type": "string", "required": True},
+            {"header": "VLAN", "name": "vlan", "type": "integer", "default": 1},
+            {"header": "Kind", "name": "kind", "type": "enum", "values": ["ap", "switch"]},
+            {"header": "Key", "name": "key", "type": "string", "sensitive": True},
+        ],
+        "max_rows": 100,
+    }
+    settings = {"input_schema": FORM_SCHEMA, "csv": csv}
+    graph = G().node("a", "testkit.echo@1", {"value": 1}).data() | {"settings": settings}
+    ctx, wf = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings, graph)
+    client = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx)
+    form = (await client.get(f"/api/v1/t/{ctx.tenant_id}/workflows/{wf}/start-form")).json()
+    assert form["csv"] == {
+        "max_rows": 100,
+        "max_bytes": 5 * 1024 * 1024,
+        "columns": [
+            {"header": "Site", "name": "site", "type": "string", "required": True, "sensitive": False},
+            {"header": "VLAN", "name": "vlan", "type": "integer", "required": False, "sensitive": False, "default": 1},
+            {"header": "Kind", "name": "kind", "type": "enum", "required": False, "sensitive": False,
+             "values": ["ap", "switch"]},
+            {"header": "Key", "name": "key", "type": "string", "required": False, "sensitive": True},
+        ],
+    }  # fmt: skip
+    assert {f["name"] for f in form["fields"]} == {"token", "site", "count"}  # `rows` comes from the file
+
+
 async def test_a_workflow_without_an_active_version_has_no_start_form(
     keyed_app, owner_sessionmaker, api_sessionmaker, api_settings
 ) -> None:
diff --git a/backend/tests/apps/test_admission.py b/backend/tests/apps/test_admission.py
index af31842..c6f5d37 100644
--- a/backend/tests/apps/test_admission.py
+++ b/backend/tests/apps/test_admission.py
@@ -13,6 +13,7 @@ import pytest
 from sqlalchemy import text
 
 from dewpoint.apps import admission
+from dewpoint.apps.inputs import RESERVED_INPUT
 from dewpoint.core.claims import secret_index
 from dewpoint.core.claims import service as claims
 from dewpoint.core.claims.cipher import ClaimCipher
@@ -35,6 +36,10 @@ SCHEMA = {
     "additionalProperties": False,
 }
 TOKEN_GRAPH = G().node("a", "testkit.echo@1", {"value": 1}).data() | {"settings": {"input_schema": SCHEMA}}
+OPEN_GRAPH = G().node("a", "testkit.echo@1", {"value": 1}).data() | {"settings": {"input_schema": {"type": "object"}}}
+CSV_GRAPH = TOKEN_GRAPH | {
+    "settings": {"input_schema": SCHEMA, "csv": {"columns": [{"header": "Site", "name": "site", "type": "string"}]}}
+}
 
 
 async def published(owner: Any, api: Any, admin: Any, settings: Any, graph: Any = TOKEN_GRAPH) -> tuple[Any, uuid.UUID]:
@@ -267,3 +272,35 @@ async def test_the_build_record_ages_with_the_clock_not_the_callers_transaction(
                 source="manual", mode="live", input={"token": TOKEN},
             )  # fmt: skip
     assert stale.value.reason == "no_current_build"
+
+
+@pytest.mark.parametrize("name", ["rows", "row_count"])
+@pytest.mark.parametrize("source", ["manual", "schedule"])
+async def test_no_caller_supplies_rows_or_row_count(
+    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings, name, source
+) -> None:
+    """Only admission writes `rows` and `row_count`, from a CSV upload (engine 2b spec §8.1): a caller's input holding
+    either is refused, even where the workflow's input schema would take it."""
+    ctx, wf = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings, OPEN_GRAPH)
+    await current(dispatch_sessionmaker)
+    request = {"source": source, "input": {name: 1}}
+    if source == "manual":
+        with pytest.raises(admission.AdmissionRefusedError) as refused:
+            await admit(api_sessionmaker, ctx, wf, **request)
+        assert (refused.value.reason, refused.value.messages) == ("input_invalid", [RESERVED_INPUT])
+    else:
+        r = (await admit(api_sessionmaker, ctx, wf, **request)).request
+        assert (r.status, r.reason) == ("refused", "input_invalid")
+    assert await count(owner_sessionmaker, "run_inputs") == 0
+
+
+async def test_a_workflow_declaring_a_csv_isnt_started_without_one(
+    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings
+) -> None:
+    """Its trigger schema requires `rows` and `row_count` (engine 2b spec §8.1), which only a CSV upload supplies."""
+    ctx, wf = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings, CSV_GRAPH)
+    await current(dispatch_sessionmaker)
+    with pytest.raises(admission.AdmissionRefusedError) as refused:
+        await admit(api_sessionmaker, ctx, wf)
+    assert refused.value.reason == "input_invalid"
+    assert any("its root: it breaks `required`" in m for m in refused.value.messages)
diff --git a/backend/tests/apps/test_workflow_ops.py b/backend/tests/apps/test_workflow_ops.py
index 00a1b1f..1e4780d 100644
--- a/backend/tests/apps/test_workflow_ops.py
+++ b/backend/tests/apps/test_workflow_ops.py
@@ -490,3 +490,23 @@ async def test_declassifying_needs_its_permission_and_the_audit_entry_lists_each
             await s.execute(text("select details from audit_log where action = 'workflow.publish'"))
         ).scalar_one()
     assert details["declassify"] == [{"node": str(nid("c")), "field": "/condition", "reveals": "the branch taken"}]
+
+
+CSV_SETTINGS = {"csv": {"columns": [{"header": "Site", "name": "site", "type": "string"}]}}
+
+
+async def test_publish_refuses_a_sub_flow_or_failure_handler_that_declares_a_csv(
+    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings
+) -> None:
+    """Only a CSV upload supplies a CSV's rows (engine 2b spec §8.1), so no parent may start a version declaring one."""
+    await sync_test_plugins(admin_sessionmaker)
+    ctx = await actor(owner_sessionmaker)
+    child = await create(api_sessionmaker, ctx, ECHO_GRAPH | {"settings": CSV_SETTINGS}, name="child")
+    assert (await publish(api_sessionmaker, ctx, child, api_settings)).version is not None
+    for name, draft in (
+        ("parent", runs(child)),
+        ("handled", ECHO_GRAPH | {"settings": {"failure_handler": str(child)}}),
+    ):
+        wf = await create(api_sessionmaker, ctx, draft, name=name)
+        refused = await publish(api_sessionmaker, ctx, wf, api_settings)
+        assert refused.version is None and [d.code for d in refused.errors] == ["subflow.csv_target"]
diff --git a/backend/tests/engine/graph/test_trigger_schema.py b/backend/tests/engine/graph/test_trigger_schema.py
new file mode 100644
index 0000000..2a5733f
--- /dev/null
+++ b/backend/tests/engine/graph/test_trigger_schema.py
@@ -0,0 +1,183 @@
+# SPDX-License-Identifier: Apache-2.0
+"""The trigger schema (engine 2b spec §8.1): one pure function of a version's settings, its `input_schema` plus, for a
+version that declares a CSV, `rows` (closed row objects, sensitive columns marked) and `row_count`. Publish types,
+taints and checks every `trigger.*` read against it. `rows` and `row_count` are reserved: publish refuses them as input
+properties, CSV or not, and a version declaring a CSV can't be a sub-flow's or a failure handler's target, since only a
+CSV upload supplies its rows."""
+
+import copy
+import uuid
+from typing import Any
+
+import pytest
+from jsonschema import Draft202012Validator
+
+from dewpoint.engine.graph.csv import trigger_schema
+from dewpoint.engine.graph.validate import SubflowInfo, ValidationContext, ValidationResult, validate
+from dewpoint.plugins.flow import PLUGIN
+from tests.support.catalog import catalog
+from tests.support.graphs import G, cel, nid, ref
+from tests.support.plugins.testkit import TESTKIT
+
+CAT = catalog(PLUGIN, TESTKIT)
+ECHO, LOOP, RUN = "testkit.echo@1", "flow.loop@1", "flow.run_workflow@1"
+INPUT = {
+    "type": "object",
+    "properties": {"note": {"type": "string"}},
+    "required": ["note"],
+    "additionalProperties": False,
+}
+CSV = {
+    "columns": [
+        {"header": "Site", "name": "site", "type": "string", "required": True},
+        {"header": "VLAN", "name": "vlan", "type": "integer", "default": 1},
+        {"header": "Kind", "name": "kind", "type": "enum", "values": ["ap", "switch"]},
+        {"header": "MAC", "name": "mac", "type": "mac"},
+        {"header": "PSK", "name": "psk", "type": "string", "required": True, "sensitive": True},
+    ],
+    "max_rows": 500,
+}
+W, V = uuid.uuid4(), uuid.uuid4()
+
+
+def check(g: G, **ctx: Any) -> ValidationResult:
+    return validate(g.build(), ValidationContext(catalog=CAT, **ctx))
+
+
+def codes(g: G, **ctx: Any) -> list[tuple[str, str | None]]:
+    return [(d.code, d.field) for d in check(g, **ctx).diagnostics]
+
+
+def with_csv(g: G) -> G:
+    g.settings = {"input_schema": INPUT, "csv": CSV}
+    return g
+
+
+def loop(*body: tuple[str, Any]) -> G:
+    g = G().node("l", LOOP, {"items": ref("trigger.rows")})
+    for key, value in body:
+        g.node(key, ECHO, {"value": value}).edge("l", key, "body")
+    return with_csv(g)
+
+
+def test_without_a_csv_the_trigger_schema_is_the_input_schema() -> None:
+    assert trigger_schema({"input_schema": INPUT}) == INPUT
+    assert trigger_schema({}) == {"type": "object"}
+
+
+def test_a_csv_adds_closed_typed_rows_and_their_public_count() -> None:
+    before = copy.deepcopy(INPUT)
+    schema = trigger_schema({"input_schema": INPUT, "csv": CSV})
+    assert INPUT == before  # the settings are never changed
+    assert schema["required"] == ["note", "rows", "row_count"]
+    assert schema["properties"]["note"] == {"type": "string"}
+    assert schema["properties"]["row_count"] == {"type": "integer", "minimum": 0, "maximum": 500}
+    assert schema["properties"]["rows"] == {
+        "type": "array",
+        "maxItems": 500,
+        "items": {
+            "type": "object",
+            "properties": {
+                "site": {"type": "string", "title": "Site"},
+                "vlan": {"type": "integer", "title": "VLAN", "default": 1},
+                "kind": {"type": "string", "title": "Kind", "enum": ["ap", "switch"]},
+                "mac": {"type": "string", "title": "MAC", "format": "mac"},
+                "psk": {"type": "string", "title": "PSK", "x-sensitive": True},
+            },
+            "required": ["site", "vlan", "psk"],  # a column with a default is always filled in
+            "additionalProperties": False,
+        },
+    }
+
+
+def test_publish_types_the_rows_their_count_and_each_item() -> None:
+    assert codes(loop(("a", ref("item.vlan")), ("b", cel("item.site + ':' + trigger.note")))) == []
+    assert codes(with_csv(G().node("a", ECHO, {"value": cel("trigger.row_count > 0")}))) == []
+    assert [c for c, _ in codes(loop(("a", ref("item.nope"))))] == ["ref.unknown_field"]
+    assert [c for c, _ in codes(loop(("a", ref("item.mac"))))] == ["ref.conditional"]  # an optional column
+
+
+def test_a_sensitive_column_taints_its_cells_and_nothing_else() -> None:
+    result = check(loop(("a", ref("item.psk")), ("b", ref("item.site")), ("c", cel("trigger.row_count"))))
+    assert result.ok, result.diagnostics
+    # the loop reads the rows whole, so its `items` is tainted (§4.1); their length is public (§4.3)
+    assert {(n, f) for n, f in result.tainted_sites} == {(str(nid("a")), "/value"), (str(nid("l")), "/items")}
+
+
+@pytest.mark.parametrize("name", ["rows", "row_count"])
+@pytest.mark.parametrize("csv", [False, True])
+def test_rows_and_row_count_are_reserved_input_properties(name: str, csv: bool) -> None:
+    g = G().node("a", ECHO, {"value": 1})
+    g.settings = {"input_schema": {"type": "object", "properties": {name: {"type": "integer"}}}}
+    if csv:
+        g.settings["csv"] = CSV
+    assert codes(g) == [("settings.reserved_name", f"/settings/input_schema/properties/{name}")]
+
+
+def csv_child(declares_csv: bool) -> SubflowInfo:
+    return SubflowInfo(W, V, {"type": "object"}, {"type": "object", "properties": {}}, {}, declares_csv=declares_csv)
+
+
+def test_a_version_declaring_a_csv_is_no_sub_flows_target() -> None:
+    g = G().node("r", RUN, {"workflow_id": str(W), "input": {}})
+    assert codes(g, subflows={W: csv_child(False)}) == []
+    assert codes(g, subflows={W: csv_child(True)}) == [("subflow.csv_target", "/workflow_id")]
+
+
+def test_a_version_declaring_a_csv_is_no_failure_handler() -> None:
+    g = G().node("a", ECHO, {"value": 1})
+    g.settings = {"failure_handler": str(W)}
+    assert codes(g, subflows={W: csv_child(False)}) == []
+    assert codes(g, subflows={W: csv_child(True)}) == [("subflow.csv_target", "/settings/failure_handler")]
+
+
+CLOSED = {"properties": {"note": {"type": "string"}}, "additionalProperties": False}
+
+
+@pytest.mark.parametrize(
+    ("root", "keywords"),
+    [
+        ({"allOf": [CLOSED]}, "allOf"),  # the owner's reproduction: a closed branch refuses `rows`
+        ({"anyOf": [CLOSED]}, "anyOf"),
+        ({"oneOf": [CLOSED]}, "oneOf"),
+        ({"not": {"required": ["rows"]}}, "not"),
+        ({"if": {"required": ["note"]}, "then": CLOSED}, "if then"),
+        ({"$ref": "#/$defs/closed", "$defs": {"closed": CLOSED}}, "$ref"),
+        ({"unevaluatedProperties": False}, "unevaluatedProperties"),
+        ({"propertyNames": {"maxLength": 3}}, "propertyNames"),
+        ({"maxProperties": 1}, "maxProperties"),
+        ({"dependentRequired": {"rows": ["note"]}}, "dependentRequired"),
+        ({"x-sensitive": True}, "x-sensitive"),  # would taint the count that's public
+    ],
+)
+def test_a_csv_needs_an_input_schema_that_cant_refuse_its_rows(root: dict[str, Any], keywords: str) -> None:
+    """Publish refuses a CSV whose input schema could refuse the generated `rows` and `row_count`, rather than
+    publish a workflow no start can satisfy: at its root, only keywords that leave the two keys free."""
+    g = G().node("a", ECHO, {"value": 1})
+    g.settings = {"input_schema": {"type": "object", **root}}
+    assert codes(g) == []  # without a CSV, it's an ordinary schema
+    g.settings["csv"] = CSV
+    assert codes(g) == [("csv.input_schema", f"/settings/input_schema/{k}") for k in keywords.split()]
+
+
+ROW = {"site": "paris", "vlan": 1, "psk": "s3cret"}
+
+
+@pytest.mark.parametrize(
+    "root",
+    [
+        {},
+        {"properties": {"note": {"type": "string"}}, "required": ["note"], "additionalProperties": False},
+        {"properties": {"note": {"type": "string"}}, "additionalProperties": {"type": "string"}},
+        {"title": "T", "description": "D", "$defs": {"s": {"type": "string"}},
+         "properties": {"note": {"$ref": "#/$defs/s"}}, "additionalProperties": False},
+    ],
+)  # fmt: skip
+def test_every_input_schema_a_csv_accepts_admits_its_rows(root: dict[str, Any]) -> None:
+    """The keywords a CSV's input schema may hold at its root never refuse `rows` and `row_count`: the trigger schema
+    accepts the input with the rows admission builds."""
+    g = G().node("a", ECHO, {"value": 1})
+    g.settings = {"input_schema": {"type": "object", **root}, "csv": CSV}
+    assert codes(g) == []
+    schema = trigger_schema(g.build().settings.model_dump(mode="json"))
+    assert Draft202012Validator(schema).is_valid({"note": "n", "rows": [ROW], "row_count": 1})
diff --git a/backend/tests/engine/graph/test_validate_declassify.py b/backend/tests/engine/graph/test_validate_declassify.py
index 7ab7fc3..ba3c061 100644
--- a/backend/tests/engine/graph/test_validate_declassify.py
+++ b/backend/tests/engine/graph/test_validate_declassify.py
@@ -17,17 +17,19 @@ ECHO, IF, SWITCH, LOOP, FILTER = "testkit.echo@1", "flow.if@1", "flow.switch@1",
 SECRET = {"type": "string", "x-sensitive": True}
 ROW = {"type": "object", "properties": {"id": {"type": "integer"}, "card": SECRET}, "required": ["id", "card"],
        "additionalProperties": False}  # fmt: skip
+CARD = {"header": "Card", "name": "card", "type": "string", "required": True, "sensitive": True}
+CSV = {"columns": [{"header": "ID", "name": "id", "type": "integer", "required": True}, CARD]}
 INPUT = {
     "type": "object",
-    "properties": {"token": SECRET, "n": {"type": "integer"}, "rows": {"type": "array", "items": ROW},
-                   "list": {"type": "array", "items": ROW}},
-    "required": ["token", "n", "rows", "list"],
+    "properties": {"token": SECRET, "n": {"type": "integer"}, "list": {"type": "array", "items": ROW}},
+    "required": ["token", "n", "list"],
     "additionalProperties": False,
 }  # fmt: skip
 
 
 def check(g: G, *declassify: tuple[str, str]) -> ValidationResult:
-    g.settings = {"input_schema": INPUT, "declassify": [{"node": str(nid(k)), "field": f} for k, f in declassify]}
+    g.settings = {"input_schema": INPUT, "csv": CSV,
+                  "declassify": [{"node": str(nid(k)), "field": f} for k, f in declassify]}  # fmt: skip
     return validate(g.build(), ValidationContext(catalog=CAT))
 
 
diff --git a/backend/tests/engine/graph/test_validate_taint.py b/backend/tests/engine/graph/test_validate_taint.py
index 3a52284..19674e6 100644
--- a/backend/tests/engine/graph/test_validate_taint.py
+++ b/backend/tests/engine/graph/test_validate_taint.py
@@ -19,8 +19,8 @@ from tests.support.plugins.testkit import TESTKIT
 CAT = catalog(PLUGIN, TESTKIT)
 ECHO, LOOP, FILTER, SET = "testkit.echo@1", "flow.loop@1", "flow.filter@1", "flow.set_variables@1"
 SECRET = {"type": "string", "x-sensitive": True}
-ROWS = {"type": "array", "items": {"type": "object", "properties": {"id": {"type": "integer"}, "card": SECRET},
-                                  "required": ["id", "card"], "additionalProperties": False}}  # fmt: skip
+CARD = {"header": "Card", "name": "card", "type": "string", "required": True, "sensitive": True}
+CSV = {"columns": [{"header": "ID", "name": "id", "type": "integer", "required": True}, CARD]}
 INPUT = {
     "type": "object",
     "properties": {
@@ -28,17 +28,16 @@ INPUT = {
         "token": SECRET,
         "login": {"type": "object", "properties": {"user": {"type": "string"}, "pw": SECRET},
                   "required": ["user", "pw"], "additionalProperties": False},
-        "rows": ROWS,
         "extra": {"type": "object"},
     },
-    "required": ["name", "token", "login", "rows", "extra"],
+    "required": ["name", "token", "login", "extra"],
     "additionalProperties": False,
 }  # fmt: skip
 
 
 def checked(g: G, **ctx: Any) -> ValidationResult:
     if "input_schema" not in g.settings:
-        g.settings = {**g.settings, "input_schema": INPUT}
+        g.settings = {**g.settings, "input_schema": INPUT, "csv": CSV}  # `trigger.rows`: the CSV's
     result = validate(g.build(), ValidationContext(catalog=CAT, **ctx))
     assert result.ok, result.diagnostics
     return result
@@ -150,8 +149,9 @@ def test_a_sub_flows_outputs_follow_its_versions_taint_map_and_unknown_counts_as
 
 def test_the_workflows_outputs_record_their_taint() -> None:
     g = echoes(a=1)
-    g.settings = {"input_schema": INPUT, "outputs": {"secret": ref("trigger.token"), "plain": ref("trigger.name"),
-                                                     "count": cel("size(trigger.rows)")}}  # fmt: skip
+    g.settings = {"input_schema": INPUT, "csv": CSV,
+                  "outputs": {"secret": ref("trigger.token"), "plain": ref("trigger.name"),
+                              "count": cel("size(trigger.rows)")}}  # fmt: skip
     result = checked(g)
     assert result.output_taint == {"secret": True, "plain": False, "count": True}
```

### Task 3: A loop over trigger.rows skips its declassify entry only with a CSV declared (#31)

**Commit:** `b7d7e46` (prototype `proto/2b3a-v2`); the replay's tree was identical: yes.

**Modify:** `backend/src/dewpoint/engine/graph/validate.py`, `backend/tests/engine/graph/test_validate_declassify.py`, `docs/operations/runs.md`

**What it does:**

The exception of engine 2b spec §4.3 matched the path alone, so any version reading a
`trigger.rows` it didn't declare, or declared itself before the name was reserved, could
loop over a sensitive list and reveal its length without listing the site or holding
`workflow.declassify`. It now holds only for a version that declares a CSV, whose
`row_count` is public; elsewhere the loop needs its entry, as every tainted loop does.

Fixes #31.

- [ ] **Step 1: its tests alone, before its code.** Run: `uv run pytest -n 8 tests/engine/graph/test_validate_declassify.py`. Replay result (exit 1), shortened:

```
F.....                                                                   [100%]
=================================== FAILURES ===================================
[gw4] darwin -- Python 3.14.7 <venv>/bin/python
E   AssertionError: assert [] == [('taint.unde...d', '/items')]
      Right contains one more item: ('taint.undeclassified', '/items')
      Use -v to get more diff
<replay>/backend/tests/engine/graph/test_validate_declassify.py:88: AssertionError: assert [] == [('taint.unde...d', '/items')]
=========================== short test summary info ============================
FAILED tests/engine/graph/test_validate_declassify.py::test_without_a_csv_a_loop_over_trigger_rows_needs_its_entry
1 failed, 5 passed in 4.62s
```

- [ ] **Step 2: its code, then the same tests.** Replay result (exit 0), shortened:

```
......                                                                   [100%]
6 passed in 4.70s
```

- [ ] **Step 3: commit.** `git cherry-pick --no-commit b7d7e46 && git commit -C b7d7e46`

The diff:

```diff
diff --git a/backend/src/dewpoint/engine/graph/validate.py b/backend/src/dewpoint/engine/graph/validate.py
index 6685ace..7134e41 100644
--- a/backend/src/dewpoint/engine/graph/validate.py
+++ b/backend/src/dewpoint/engine/graph/validate.py
@@ -258,9 +258,12 @@ def _decision_sites(graph: Graph, s: Structure) -> dict[tuple[uuid.UUID, str], s
     return out
 
 
-def _public_length(n: GraphNode) -> bool:
-    """A loop over `trigger.rows` itself: its length is already public (`trigger.row_count`), so it needs no entry.
-    A derived or filtered list doesn't inherit that (§4.3)."""
+def _public_length(graph: Graph, n: GraphNode) -> bool:
+    """A loop over `trigger.rows` itself, in a version declaring a CSV: its length is already public
+    (`trigger.row_count`), so it needs no entry. A derived or filtered list doesn't inherit that (§4.3), and without a
+    CSV `trigger.rows` is whatever the caller sent, with no public count (#31)."""
+    if graph.settings.csv is None:
+        return False
     raw = n.config.get("items")
     body = raw.get(ENVELOPE) if isinstance(raw, Mapping) and is_envelope(raw) else None
     return isinstance(body, Mapping) and body.get("kind") == "ref" and body.get("path") == "trigger.rows"
@@ -276,7 +279,7 @@ def _declassify(
     for (node, fld), ref in sites.items():
         if not site_taint.get((node, fld)) or (node, fld) in listed:
             continue
-        if ref == C.LOOP and _public_length(s.nodes[node]):
+        if ref == C.LOOP and _public_length(graph, s.nodes[node]):
             continue
         out.append(
             Diagnostic(
diff --git a/backend/tests/engine/graph/test_validate_declassify.py b/backend/tests/engine/graph/test_validate_declassify.py
index ba3c061..294ac3d 100644
--- a/backend/tests/engine/graph/test_validate_declassify.py
+++ b/backend/tests/engine/graph/test_validate_declassify.py
@@ -2,7 +2,7 @@
 """Declassification (engine 2b spec §4.3): only a `flow.if` condition, a `flow.switch` case's `when`, a loop's
 `items` and a filter's `items` or `predicate` may turn tainted input into a plain decision, and each such site must be
 listed in `graph.settings.declassify`. Publish refuses an unlisted tainted decision and a stale entry. A loop over
-`trigger.rows`, whose length is already public, needs no entry."""
+the rows of a version's CSV, `trigger.rows`, whose length is already public (`trigger.row_count`), needs no entry."""
 
 from typing import Any
 
@@ -79,6 +79,17 @@ def test_a_loop_over_tainted_items_must_be_listed_except_over_trigger_rows() ->
     assert check(loop(ref("trigger.rows"))).ok  # its length is public: no entry needed
 
 
+def test_without_a_csv_a_loop_over_trigger_rows_needs_its_entry() -> None:
+    """#31: only a version declaring a CSV has a public `row_count`, so only its loop over `trigger.rows` skips the
+    entry (§4.3). Elsewhere `trigger.rows` is whatever the caller sent: here undeclared, so sensitive."""
+    rows = ref("trigger.rows", default=[])  # undeclared, so optional: the default makes it a direct reference still
+    g = G().node("l", LOOP, {"items": rows}).node("x", ECHO, {"value": 1}).edge("l", "x", "body")
+    g.settings = {"input_schema": {"type": "object"}}
+    assert codes(validate(g.build(), ValidationContext(catalog=CAT))) == [("taint.undeclassified", "/items")]
+    g.settings["declassify"] = [{"node": str(nid("l")), "field": "/items"}]
+    assert validate(g.build(), ValidationContext(catalog=CAT)).ok
+
+
 def test_a_filter_lists_each_tainted_field() -> None:
     g = G().node("f", FILTER, {"items": [1, 2, 3], "predicate": cel("size(trigger.token) > item")})
     assert codes(check(g)) == [("taint.undeclassified", "/predicate")]
diff --git a/docs/operations/runs.md b/docs/operations/runs.md
index 3562c57..e4140bd 100644
--- a/docs/operations/runs.md
+++ b/docs/operations/runs.md
@@ -253,10 +253,11 @@ claims are.
   `graph.settings.declassify`, and the decision is made where the claim is read. Publishing such a workflow needs the
   `workflow.declassify` permission (tenant admins and owners), and its audit entry lists what each site reveals. A
   decision comes back plain only as a decision, `true` or `false` for a condition or a case and a whole number for a
-  loop's count: anything else fails the step with `type_mismatch`, revealing nothing. A loop over a list itself
-  (`trigger.rows`) needs no entry: a list's length isn't secret. A loop over a list held as a handle (a reference's, or
-  CEL's that comes back claimed) gets each item as a handle into it. A filter over sensitive data runs whole in one
-  activity: the run sees the kept items' handle and the two counts, never a decision per item.
+  loop's count: anything else fails the step with `type_mismatch`, revealing nothing. A loop over a CSV's rows
+  themselves (`trigger.rows`, in a workflow that declares a CSV) needs no entry: their count, `trigger.row_count`, is
+  already public. A loop over any other sensitive list needs its entry. A loop over a list held as a handle (a
+  reference's, or CEL's that comes back claimed) gets each item as a handle into it. A filter over sensitive data runs
+  whole in one activity: the run sees the kept items' handle and the two counts, never a decision per item.
 - **Sub-flows and failure handlers.** A sub-flow's input is checked against the child's input schema
   (`input_invalid` when it doesn't match) and claimed as a trigger is, and the child is granted the parent's claims it
   holds; a sub-flow grants its parent the claims in its outputs. A failure handler is granted what its trigger holds.
```

### Task 4: Publish refuses enum, const and examples literals at sensitive schema positions (#32)

**Commit:** `d100219` (prototype `proto/2b3a-v2`); the replay's tree was identical: yes.

**Modify:** `backend/src/dewpoint/apps/forms.py`, `backend/src/dewpoint/engine/graph/validate.py`, `backend/tests/apps/test_forms.py`, `backend/tests/engine/graph/test_validate_sensitive.py`

**What it does:**

Engine 2b spec §3.8 refused only a `default` at a sensitive position of `input_schema` or
`vars_schema`: an `enum`'s values, a `const` and `examples` published there into the
plaintext graph, which the start form's masking never protected. The walk also never
followed a local `$ref` from a sensitive position, so a literal in a definition only a
sensitive position reaches, a default included, was accepted too.

Publish now refuses all four keywords at a sensitive position, or holding a part one
marks, in both schemas: nested, in a union's branch, or in a definition a sensitive position
reaches through a local `$ref`, each reported once where it's written. The start form keeps
`enum_masked`: versions published before this are immutable and may still hold them.

Fixes #32.

- [ ] **Step 1: its tests alone, before its code.** Run: `uv run pytest -n 8 tests/apps/test_forms.py tests/engine/graph/test_validate_sensitive.py`. Replay result (exit 1), shortened:

```
FAILED tests/engine/graph/test_validate_sensitive.py::test_an_enum_const_or_example_at_a_sensitive_position_is_refused[schema4-/properties/login/examples-input_schema]
FAILED tests/engine/graph/test_validate_sensitive.py::test_an_enum_const_or_example_at_a_sensitive_position_is_refused[schema3-/properties/login/properties/pw/enum-input_schema]
FAILED tests/engine/graph/test_validate_sensitive.py::test_an_enum_const_or_example_at_a_sensitive_position_is_refused[schema2-/properties/key/examples-vars_schema]
FAILED tests/engine/graph/test_validate_sensitive.py::test_an_enum_const_or_example_at_a_sensitive_position_is_refused[schema5-/properties/key/anyOf/1/enum-input_schema]
FAILED tests/engine/graph/test_validate_sensitive.py::test_an_enum_const_or_example_at_a_sensitive_position_is_refused[schema3-/properties/login/properties/pw/enum-vars_schema]
FAILED tests/engine/graph/test_validate_sensitive.py::test_an_enum_const_or_example_at_a_sensitive_position_is_refused[schema5-/properties/key/anyOf/1/enum-vars_schema]
FAILED tests/engine/graph/test_validate_sensitive.py::test_an_enum_const_or_example_at_a_sensitive_position_is_refused[schema7-/$defs/k/const-vars_schema]
FAILED tests/engine/graph/test_validate_sensitive.py::test_an_enum_const_or_example_at_a_sensitive_position_is_refused[schema4-/properties/login/examples-vars_schema]
FAILED tests/engine/graph/test_validate_sensitive.py::test_an_enum_const_or_example_at_a_sensitive_position_is_refused[schema6-/$defs/k/enum-vars_schema]
FAILED tests/engine/graph/test_validate_sensitive.py::test_an_enum_const_or_example_at_a_sensitive_position_is_refused[schema8-/$defs/login/properties/pw/examples-vars_schema]
FAILED tests/engine/graph/test_validate_sensitive.py::test_an_enum_const_or_example_at_a_sensitive_position_is_refused[schema6-/$defs/k/enum-input_schema]
FAILED tests/engine/graph/test_validate_sensitive.py::test_an_enum_const_or_example_at_a_sensitive_position_is_refused[schema7-/$defs/k/const-input_schema]
FAILED tests/engine/graph/test_validate_sensitive.py::test_an_enum_const_or_example_at_a_sensitive_position_is_refused[schema8-/$defs/login/properties/pw/examples-input_schema]
19 failed, 24 passed in 8.33s
```

- [ ] **Step 2: its code, then the same tests.** Replay result (exit 0), shortened:

```
...........................................                              [100%]
43 passed in 8.63s
```

- [ ] **Step 3: commit.** `git cherry-pick --no-commit d100219 && git commit -C d100219`

The diff:

```diff
diff --git a/backend/src/dewpoint/apps/forms.py b/backend/src/dewpoint/apps/forms.py
index 40918fb..774c152 100644
--- a/backend/src/dewpoint/apps/forms.py
+++ b/backend/src/dewpoint/apps/forms.py
@@ -1,7 +1,8 @@
 # SPDX-License-Identifier: Apache-2.0
 """A start form's fields (engine 2b spec §7.7): the typed top-level fields of a version's `input_schema`, for the UI.
 A sensitive field shows its type and whether it's required, never a value the schema holds for it: its default and
-its enum are masked (publish refuses a sensitive literal anyway, §3.8). `x-dewpoint-picker` is passed through for
+its enum are masked. Publish refuses both now (§3.8, #32), but versions published before that are immutable and may
+still hold them. `x-dewpoint-picker` is passed through for
 sub-project 3's pickers. A CSV declaration (§8.1) is described with its columns: a sensitive one has no default and no
 values to show, since publish refuses them."""
 
diff --git a/backend/src/dewpoint/engine/graph/validate.py b/backend/src/dewpoint/engine/graph/validate.py
index 7134e41..91334c6 100644
--- a/backend/src/dewpoint/engine/graph/validate.py
+++ b/backend/src/dewpoint/engine/graph/validate.py
@@ -61,8 +61,9 @@ from dewpoint.engine.graph.values import (
 from dewpoint.engine.handles import RESERVED, contains_marker
 from dewpoint.engine.registry import control as C
 from dewpoint.engine.registry.catalog import Catalog, NodeTypeSpec
+from dewpoint.engine.schema_refs import PREFIX as REF_PREFIX
 from dewpoint.engine.schema_refs import ref_problems, subschemas
-from dewpoint.engine.sensitive import SENSITIVE, expand, is_marked, marked_positions
+from dewpoint.engine.sensitive import SENSITIVE, expand, is_marked, marked_positions, resolve
 from dewpoint.engine.taint import CLEAN, TAINTED, Shape, from_schema, make
 from dewpoint.sdk.fields import KINDS
 
@@ -192,6 +193,10 @@ _SENSITIVE_LITERAL = (
 )
 
 
+_SCHEMA_LITERAL = (
+    "A sensitive position can't list values (`enum`, `const`, `examples`): they'd be written into the workflow in "
+    "plain text. Leave them out; check the value where it's used instead."
+)
 _CSV_HEADER = "Another column already has this header: each header maps to one column."
 _CSV_NAME = "Another column already has this name: each column is one field of a row."
 _CSV_IDENT = "Column names are lowercase identifiers, and not `in`, `true`, `false` or `null`."
@@ -323,26 +328,42 @@ def _writes_sensitive(
     return False
 
 
-def _sensitive_defaults(label: str, schema: Mapping[str, Any]) -> list[Diagnostic]:
-    """A `default` at a position the schema marks sensitive, or holding a part it does (engine 2b spec §3.8): a
-    secret written into the version, even null or empty: an omitted default is what's allowed."""
-    found: list[str] = []
+_SCHEMA_LITERALS = ("default", "enum", "const", "examples")  # what a schema writes of its instances
+
+
+def _sensitive_schema_literals(label: str, schema: Mapping[str, Any]) -> list[Diagnostic]:
+    """A literal a schema writes — a `default`, an `enum`'s values, a `const`, `examples` — at a position it marks
+    sensitive, or holding a part it does (engine 2b spec §3.8): a secret written into the version, even null or empty;
+    an omitted one is what's allowed. Each is found where it's written: nested, in a union's branch, or in a definition
+    that a sensitive position reaches through a local `$ref`. A start form masks a sensitive field's enum and default,
+    but that never protected the published graph; versions published before this rule keep their masking."""
+    found: dict[tuple[str, str], None] = {}  # (where, keyword), in document order
+    seen: set[tuple[str, bool]] = set()
+
+    def instances(node: Mapping[str, Any], key: str) -> list[Any]:
+        value = node[key]
+        return list(value) if key in ("enum", "examples") and isinstance(value, list) else [value]
 
     def walk(node: Any, path: str, inherited: bool) -> None:
-        if not isinstance(node, Mapping):
+        if not isinstance(node, Mapping) or (path, inherited) in seen:
             return
-        branches = expand(node, schema)
-        here = inherited or any(b.get(SENSITIVE) is True for b in branches)
-        defaults = [b["default"] for b in branches if "default" in b]
-        if defaults and (here or any(marked_positions(d, node, schema) for d in defaults)):
-            found.append(path)
+        seen.add((path, inherited))
+        here = inherited or any(b.get(SENSITIVE) is True for b in expand(node, schema))
+        for key in _SCHEMA_LITERALS:
+            if key in node and (here or any(marked_positions(v, node, schema) for v in instances(node, key))):
+                found[(path, key)] = None
         for suffix, sub in subschemas(node):
             walk(sub, path + suffix, here)
+        ref = node.get("$ref")
+        if here and isinstance(ref, str) and ref.startswith(REF_PREFIX):  # the definition, sensitive from here
+            walk(resolve(schema, ref), ref[1:], True)
 
     walk(schema, "", False)
     return [
         Diagnostic(code="sensitive.default", field=f"/settings/{label}{where}", message=_SENSITIVE_LITERAL)
-        for where in found
+        if key == "default"
+        else Diagnostic(code="sensitive.literal", field=f"/settings/{label}{where}/{key}", message=_SCHEMA_LITERAL)
+        for where, key in found
     ]
 
 
@@ -415,7 +436,7 @@ def _settings(graph: Graph) -> list[Diagnostic]:
         ]
     for label, schema in (("input_schema", st.input_schema), ("vars_schema", st.vars_schema)):
         if not any((d.field or "").startswith(f"/settings/{label}") for d in out):
-            out += _sensitive_defaults(label, schema)
+            out += _sensitive_schema_literals(label, schema)
     out += _csv_declaration(st.csv)
     props = st.input_schema.get("properties")
     out += [
diff --git a/backend/tests/apps/test_forms.py b/backend/tests/apps/test_forms.py
index 505f4fc..2453e38 100644
--- a/backend/tests/apps/test_forms.py
+++ b/backend/tests/apps/test_forms.py
@@ -5,6 +5,7 @@ from dewpoint.apps.forms import form_fields
 
 
 def test_a_sensitive_fields_default_and_enum_are_masked() -> None:
+    """Publish refuses both now (#32), but a version published before that is immutable: its form still masks them."""
     schema = {
         "properties": {
             "token": {"type": "string", "x-sensitive": True, "default": "d3fault-secret", "enum": ["s1", "s2"]},
diff --git a/backend/tests/engine/graph/test_validate_sensitive.py b/backend/tests/engine/graph/test_validate_sensitive.py
index 006d20e..100aeb5 100644
--- a/backend/tests/engine/graph/test_validate_sensitive.py
+++ b/backend/tests/engine/graph/test_validate_sensitive.py
@@ -1,9 +1,9 @@
 # SPDX-License-Identifier: Apache-2.0
 """Sensitive literals are refused at publish (engine 2b spec §3.8): a value written into the workflow at a position a
-schema marks sensitive — a node's config, a variable, a sub-flow's input — and a `default` at a sensitive position of
-`input_schema` or `vars_schema`. A secret comes in through a run's input instead. Null and the empty string are
-literals too: §3.8 has no exemption. A sensitive variable has no default: it's null until a step sets it, so its type
-must allow null."""
+schema marks sensitive — a node's config, a variable, a sub-flow's input — and a `default`, `enum`, `const` or
+`examples` at a sensitive position of `input_schema` or `vars_schema`, nested or behind a local `$ref`. A secret comes
+in through a run's input instead. Null and the empty string are literals too: §3.8 has no exemption. A sensitive
+variable has no default: it's null until a step sets it, so its type must allow null."""
 
 import uuid
 from typing import Any
@@ -79,6 +79,10 @@ def test_a_literal_into_a_sub_flows_sensitive_input_is_refused() -> None:
         ("vars_schema", {"type": "object", "properties": {"key": {
             "type": ["string", "null"], "x-sensitive": True, "default": None}}},
          "/settings/vars_schema/properties/key"),  # a written default, even null: omit it instead
+        ("input_schema", {"type": "object", "properties": {"login": {"x-sensitive": True, "$ref": "#/$defs/o"}},
+                          "$defs": {"o": {"type": "object",
+                                          "properties": {"pw": {"type": "string", "default": "pa55"}}}}},
+         "/settings/input_schema/$defs/o/properties/pw"),  # nested in a definition a sensitive site reaches
     ],
 )  # fmt: skip
 def test_a_default_at_a_sensitive_position_is_refused(label: str, schema: dict[str, Any], field: str) -> None:
@@ -87,6 +91,49 @@ def test_a_default_at_a_sensitive_position_is_refused(label: str, schema: dict[s
     assert ("sensitive.default", field) in diagnostics(g)
 
 
+def obj(**properties: Any) -> dict[str, Any]:
+    return {"type": "object", "properties": properties}
+
+
+@pytest.mark.parametrize("label", ["input_schema", "vars_schema"])
+@pytest.mark.parametrize(
+    ("schema", "field"),
+    [
+        (obj(key={**SECRET, "enum": ["k3y-one", "k3y-two"]}), "/properties/key/enum"),
+        (obj(key={**SECRET, "const": "k3y-one"}), "/properties/key/const"),
+        (obj(key={**SECRET, "examples": ["k3y-one"]}), "/properties/key/examples"),
+        (obj(login={"type": "object", "x-sensitive": True, "properties": {"pw": {"type": "string", "enum": ["pa55"]}}}),
+         "/properties/login/properties/pw/enum"),  # nested under a sensitive object
+        (obj(login={"type": "object", "properties": {"pw": SECRET}, "examples": [{"pw": "pa55word"}]}),
+         "/properties/login/examples"),  # an object literal with a sensitive part
+        (obj(key={"anyOf": [SECRET, {"type": "string", "enum": ["k3y-one"]}]}),
+         "/properties/key/anyOf/1/enum"),  # sensitive in one branch, sensitive in all
+        (obj(key={"x-sensitive": True, "$ref": "#/$defs/k"})
+         | {"$defs": {"k": {"type": "string", "enum": ["k3y-one"]}}},
+         "/$defs/k/enum"),  # behind a local `$ref` from a sensitive site
+        (obj(key={"$ref": "#/$defs/k"}) | {"$defs": {"k": {**SECRET, "const": "k3y-one"}}},
+         "/$defs/k/const"),  # a sensitive definition
+        (obj(login={"x-sensitive": True, "$ref": "#/$defs/login"})
+         | {"$defs": {"login": obj(pw={"type": "string", "examples": ["pa55word"]})}},
+         "/$defs/login/properties/pw/examples"),  # nested in a definition a sensitive site reaches
+    ],
+)  # fmt: skip
+def test_an_enum_const_or_example_at_a_sensitive_position_is_refused(
+    label: str, schema: dict[str, Any], field: str
+) -> None:
+    """They're literals in the published graph as a default is (§3.8), whatever the start form masks."""
+    g = G().node("s", SEND)
+    g.settings = {label: schema}
+    assert diagnostics(g).count(("sensitive.literal", f"/settings/{label}{field}")) == 1
+
+
+def test_an_enum_const_or_example_at_a_plain_position_is_fine() -> None:
+    g = G().node("s", SEND)
+    site = {"type": "string", "enum": ["a", "b"], "examples": ["a"]}
+    g.settings = {"input_schema": obj(site=site, kind={"type": "string", "const": "ap"}, tok=SECRET)}
+    assert diagnostics(g) == []
+
+
 def test_a_sensitive_variable_has_no_default_and_is_null_until_a_step_sets_it() -> None:
     """Its type allows null, or every read comes after a step sure to have set it: otherwise a read could see null
     where its type says it can't be."""
```

**Checkpoint (milestone 1).** Focused: `tests/engine/graph`, the replay, taint and splitter tests, `tests/apps/api`,
admission and its gate, workflow operations, forms and inputs (531 at the milestone's end), and the dispatcher and CLI
(154). No migration. The owner held it twice — a composed input schema that refused the rows and a sensitive column's
values (folded into Tasks 2 and 1), then the plaintext literals at sensitive schema positions (#32, Task 4) — and
approved it as a prototype checkpoint (2026-10-04).

## Milestone 2 — CSV uploads and CSV starts

### Task 5: A CSV file read as data only, and its rows built through a mapping

**Commit:** `75a389d` (prototype `proto/2b3a-v2`); the replay's tree was identical: yes.

**Create:** `backend/src/dewpoint/apps/csv_input.py`, `backend/tests/apps/test_csv_input.py`, `backend/tests/engine/graph/test_csv_cells.py`

**Modify:** `backend/src/dewpoint/engine/graph/csv.py`

**What it does:**

The file is decoded as UTF-8 (an optional BOM dropped), its delimiter detected among comma,
semicolon and tab from its header record read strictly, and read with strict quoting; blank
lines are skipped, NUL is refused whatever the Python version, and the caps are enforced
(bytes, then data records). Headers must be unique (engine 2b spec §8.1).

A mapping from declared column names to the file's headers is checked against the
declaration and the file, and builds the rows: each cell converted to its column's canonical
value (the owner's ruling 7), an empty cell absent, so its default or `required`. A record
that breaks a rule builds no row and is reported as its number, the column's declared name
and a fixed code, never a cell's text nor a header. Fuzzed: any bytes give a table or a file
code; built rows always match the trigger schema's row schema.

**Later tasks refine this.** Task 9 bounds the builder's error detail (the first 100 errors, each skipped row's number
and first code, and the count) and raises the csv module's field limit to the byte cap.

- [ ] **Step 1: its tests alone, before its code.** Run: `uv run pytest -n 8 tests/apps/test_csv_input.py tests/engine/graph/test_csv_cells.py`. Replay result (exit 1), shortened:

```
____________ ERROR collecting tests/engine/graph/test_csv_cells.py _____________
ImportError while importing test module '<replay>/backend/tests/engine/graph/test_csv_cells.py'.
Hint: make sure your test modules/packages have valid Python names.
Traceback:
<python>/lib/python3.14/importlib/__init__.py:88: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
tests/engine/graph/test_csv_cells.py:13: in <module>
    from dewpoint.engine.graph.csv import CELL_CODES, CsvType, convert, is_canonical
E   ImportError: cannot import name 'CELL_CODES' from 'dewpoint.engine.graph.csv' (<replay>/backend/src/dewpoint/engine/graph/csv.py)
=========================== short test summary info ============================
ERROR tests/apps/test_csv_input.py - ImportError while importing test module ...
ERROR tests/engine/graph/test_csv_cells.py - ImportError while importing test...
2 errors in 4.89s
```

- [ ] **Step 2: its code, then the same tests.** Replay result (exit 0), shortened:

```
..................................................................       [100%]
66 passed in 12.09s
```

- [ ] **Step 3: commit.** `git cherry-pick --no-commit 75a389d && git commit -C 75a389d`

The diff:

```diff
diff --git a/backend/src/dewpoint/apps/csv_input.py b/backend/src/dewpoint/apps/csv_input.py
new file mode 100644
index 0000000..838638b
--- /dev/null
+++ b/backend/src/dewpoint/apps/csv_input.py
@@ -0,0 +1,160 @@
+# SPDX-License-Identifier: Apache-2.0
+"""A CSV file as data only (engine 2b spec §8.1): no formula, no type guessing, nothing evaluated. It's decoded as UTF-8
+(an optional BOM dropped), its delimiter detected among comma, semicolon and tab from its header record, and read with
+strict quoting; blank lines are skipped. Its caps are enforced: bytes, then data records.
+
+A table's rows are built through a mapping from declared column names to the file's headers: each cell converted to its
+column's canonical value (`engine.graph.csv.convert`), an empty cell absent (its column's default, or `required`). What
+breaks a rule is reported as the record's number (1 is the first after the header), the column's declared name and a
+fixed code: never a cell's text nor a header, both of which are the file's data."""
+
+import csv
+import io
+from collections.abc import Iterator, Mapping, Sequence
+from dataclasses import dataclass
+from typing import Any
+
+from dewpoint.engine.graph.csv import convert
+
+DELIMITERS = (",", ";", "\t")  # tried in this order: a tie goes to the earlier one
+FILE_CODES = frozenset(
+    {"csv_encoding", "csv_empty", "csv_duplicate_header", "csv_malformed", "csv_too_many_rows", "csv_too_large"}
+)
+ROW_CODES = frozenset({"required", "cell_count"})  # beside a cell's conversion codes (`CELL_CODES`)
+MAPPING_CODES = frozenset({"required_unmapped", "unknown_column", "unknown_header", "header_reused"})
+
+
+class CsvFileError(Exception):
+    """A file that can't be read as a table: its code only (`FILE_CODES`)."""
+
+    def __init__(self, code: str) -> None:
+        super().__init__(code)
+        self.code = code
+
+
+@dataclass(frozen=True)
+class Table:
+    headers: list[str]
+    rows: list[list[str]]  # each record's cells, as the file holds them
+
+
+@dataclass(frozen=True)
+class RowError:
+    row: int  # the record's number: 1 is the first after the header
+    column: str | None  # the declared column's name; None for the record as a whole
+    code: str
+
+
+def _records(text: str, delimiter: str) -> Iterator[list[str]]:
+    return csv.reader(io.StringIO(text, newline=""), delimiter=delimiter, strict=True)
+
+
+def _delimiter(text: str) -> str:
+    """The candidate that splits the header record into the most fields, read strictly: a comma inside a quoted
+    semicolon-separated header doesn't count."""
+    best, most = DELIMITERS[0], 0
+    for candidate in DELIMITERS:
+        try:
+            fields = len(next(_records(text, candidate), []))
+        except csv.Error:
+            continue
+        if fields > most:
+            best, most = candidate, fields
+    return best
+
+
+def read_table(data: bytes, *, max_rows: int, max_bytes: int) -> Table:
+    """`data` as a table, or CsvFileError. The caller enforces `max_bytes` while it reads the body; it's checked here
+    again."""
+    if len(data) > max_bytes:
+        raise CsvFileError("csv_too_large")
+    try:
+        text = data.decode("utf-8-sig")
+    except UnicodeDecodeError:
+        raise CsvFileError("csv_encoding") from None
+    if "\x00" in text:  # the csv module's handling of NUL differs between Python versions
+        raise CsvFileError("csv_malformed")
+    records = _records(text, _delimiter(text))
+    headers: list[str] | None = None
+    rows: list[list[str]] = []
+    try:
+        for record in records:
+            if not record:
+                continue  # a blank line
+            if headers is None:
+                if len(set(record)) != len(record):
+                    raise CsvFileError("csv_duplicate_header")
+                headers = record
+                continue
+            if len(rows) == max_rows:
+                raise CsvFileError("csv_too_many_rows")
+            rows.append(record)
+    except csv.Error:
+        raise CsvFileError("csv_malformed") from None
+    if headers is None:
+        raise CsvFileError("csv_empty")
+    return Table(headers, rows)
+
+
+def exact_mapping(columns: Sequence[Mapping[str, Any]], headers: Sequence[str]) -> dict[str, str]:
+    """Each declared column whose header the file has exactly, mapped to it."""
+    present = set(headers)
+    return {c["name"]: c["header"] for c in columns if c["header"] in present}
+
+
+def mapping_problems(
+    columns: Sequence[Mapping[str, Any]], mapping: Mapping[str, str], headers: Sequence[str] | None
+) -> list[dict[str, str]]:
+    """What keeps `mapping` from building rows, each as a column's declared name and a code (`MAPPING_CODES`): a name
+    the declaration lacks, a required column left unmapped, and, given the file's `headers`, a header it doesn't have
+    or one mapped twice."""
+    declared = {c["name"] for c in columns}
+    problems = [{"column": name, "code": "unknown_column"} for name in mapping if name not in declared]
+    if headers is not None:
+        present, used = set(headers), set()
+        for name, header in mapping.items():
+            if name not in declared:
+                continue
+            if header not in present:
+                problems.append({"column": name, "code": "unknown_header"})
+            elif header in used:
+                problems.append({"column": name, "code": "header_reused"})
+            used.add(header)
+    problems += [{"column": c["name"], "code": "required_unmapped"} for c in columns
+                 if c.get("required") and c["name"] not in mapping]  # fmt: skip
+    return problems
+
+
+def build_rows(
+    table: Table, columns: Sequence[Mapping[str, Any]], mapping: Mapping[str, str]
+) -> tuple[list[dict[str, Any]], list[RowError]]:
+    """The rows `mapping` builds from `table` (its problems checked first, `mapping_problems`), and the errors of
+    every record that breaks a rule, which builds no row."""
+    position = {header: i for i, header in enumerate(table.headers)}
+    rows: list[dict[str, Any]] = []
+    errors: list[RowError] = []
+    for number, record in enumerate(table.rows, start=1):
+        if len(record) != len(table.headers):
+            errors.append(RowError(number, None, "cell_count"))
+            continue
+        row: dict[str, Any] = {}
+        broken = False
+        for c in columns:
+            header = mapping.get(c["name"])
+            text = record[position[header]] if header is not None else ""
+            if text == "":
+                if "default" in c:
+                    row[c["name"]] = c["default"]
+                elif c.get("required"):
+                    errors.append(RowError(number, c["name"], "required"))
+                    broken = True
+                continue
+            value, code = convert(c["type"], text, c.get("values"))
+            if code is not None:
+                errors.append(RowError(number, c["name"], code))
+                broken = True
+            else:
+                row[c["name"]] = value
+        if not broken:
+            rows.append(row)
+    return rows, errors
diff --git a/backend/src/dewpoint/engine/graph/csv.py b/backend/src/dewpoint/engine/graph/csv.py
index 54f7ee9..b7af324 100644
--- a/backend/src/dewpoint/engine/graph/csv.py
+++ b/backend/src/dewpoint/engine/graph/csv.py
@@ -4,6 +4,7 @@ type's canonical value. A cell is converted to its column's canonical value once
 must already be one, so the version holds exactly what a run would."""
 
 import ipaddress
+import math
 import re
 from collections.abc import Mapping
 from typing import Any, Literal
@@ -24,6 +25,27 @@ _JSON_TYPES = {"integer": "integer", "number": "number", "boolean": "boolean"}
 _JSON_TYPES.update({t: "string" for t in ("string", "mac", "ip", "cidr", "enum")})
 
 _MAC = re.compile(r"[0-9a-f]{2}(?::[0-9a-f]{2}){5}")  # the canonical form: lowercase, colon-separated
+_MAC_FORMS = (
+    re.compile(r"[0-9a-f]{2}([:-])[0-9a-f]{2}(?:\1[0-9a-f]{2}){4}"),  # aa:bb:cc:dd:ee:ff, aa-bb-cc-dd-ee-ff
+    re.compile(r"[0-9a-f]{4}\.[0-9a-f]{4}\.[0-9a-f]{4}"),  # aabb.ccdd.eeff
+    re.compile(r"[0-9a-f]{12}"),  # aabbccddeeff
+)
+_INTEGER = re.compile(r"[+-]?[0-9]+")  # ASCII digits only: Python's int() also takes other scripts and underscores
+_NUMBER = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")
+_TRUE, _FALSE = ("true", "yes", "1"), ("false", "no", "0")
+# What a cell that doesn't convert gives: fixed codes, never the cell's text (a cell may hold a secret).
+CELL_CODES = frozenset(
+    {"not_integer", "out_of_range", "not_number", "not_boolean", "not_mac", "not_ip", "not_cidr", "not_in_enum"}
+)
+
+
+def mac(text: str) -> str | None:
+    """`text` in lowercase colon form, from any of the usual spellings; None if it isn't a MAC address."""
+    lowered = text.lower()
+    if not any(form.fullmatch(lowered) for form in _MAC_FORMS):
+        return None
+    digits = re.sub(r"[:.-]", "", lowered)
+    return ":".join(digits[i : i + 2] for i in range(0, 12, 2))
 
 
 def ip(text: str) -> str | None:
@@ -42,6 +64,27 @@ def cidr(text: str) -> str | None:
         return None
 
 
+def convert(type_: CsvType, text: str, values: list[str] | None = None) -> tuple[Any, str | None]:
+    """A non-empty cell's canonical value, and None; or None and the code saying why it doesn't convert."""
+    if type_ == "string":
+        return text, None
+    if type_ == "integer":
+        if not _INTEGER.fullmatch(text):
+            return None, "not_integer"
+        number = int(text)
+        return (number, None) if INT_MIN <= number <= INT_MAX else (None, "out_of_range")
+    if type_ == "number":
+        real = float(text) if _NUMBER.fullmatch(text) else math.inf
+        return (real, None) if math.isfinite(real) else (None, "not_number")
+    if type_ == "boolean":
+        lowered = text.lower()
+        return (lowered in _TRUE, None) if lowered in _TRUE + _FALSE else (None, "not_boolean")
+    if type_ == "enum":
+        return (text, None) if text in (values or ()) else (None, "not_in_enum")
+    converted = {"mac": mac, "ip": ip, "cidr": cidr}[type_](text)
+    return (converted, None) if converted is not None else (None, f"not_{type_}")
+
+
 def is_canonical(type_: CsvType, value: Any, values: list[str] | None = None) -> bool:
     """Whether `value` is a canonical value of `type_`: what converting a cell would give, and nothing else."""
     if type_ == "integer":
diff --git a/backend/tests/apps/test_csv_input.py b/backend/tests/apps/test_csv_input.py
new file mode 100644
index 0000000..cbd8a89
--- /dev/null
+++ b/backend/tests/apps/test_csv_input.py
@@ -0,0 +1,138 @@
+# SPDX-License-Identifier: Apache-2.0
+"""A CSV file read as data only (engine 2b spec §8.1): UTF-8 with an optional BOM, the delimiter detected among comma,
+semicolon and tab, the caps enforced, the headers unique. Its rows are built through a mapping from declared columns to
+the file's headers, each cell converted to its column's type; a row that breaks a rule is reported as its number, the
+column's declared name and a fixed code, never what the cell holds."""
+
+import string
+
+import pytest
+from hypothesis import given, settings
+from hypothesis import strategies as st
+from jsonschema import Draft202012Validator
+
+from dewpoint.apps.csv_input import (
+    FILE_CODES,
+    CsvFileError,
+    RowError,
+    build_rows,
+    exact_mapping,
+    mapping_problems,
+    read_table,
+)
+from dewpoint.engine.graph.csv import CELL_CODES, trigger_schema
+
+COLUMNS = [
+    {"header": "Site", "name": "site", "type": "string", "required": True},
+    {"header": "VLAN", "name": "vlan", "type": "integer", "default": 1},
+    {"header": "MAC", "name": "mac", "type": "mac"},
+    {"header": "PSK", "name": "psk", "type": "string", "sensitive": True},
+]
+MAPPING = {"site": "Site", "vlan": "VLAN", "mac": "MAC", "psk": "PSK"}
+
+
+@pytest.mark.parametrize("delimiter", [",", ";", "\t"])
+def test_the_delimiter_is_detected_among_comma_semicolon_and_tab(delimiter: str) -> None:
+    data = f"Site{delimiter}VLAN\r\nparis{delimiter}10\r\n".encode()
+    table = read_table(data, max_rows=10, max_bytes=1000)
+    assert (table.headers, table.rows) == (["Site", "VLAN"], [["paris", "10"]])
+
+
+def test_a_bom_quotes_and_blank_lines_are_handled() -> None:
+    data = '﻿Site,Note\n"paris, fr","two\nlines"\n\n"say ""hi""",x\n'.encode()
+    table = read_table(data, max_rows=10, max_bytes=1000)
+    assert table.headers == ["Site", "Note"]
+    assert table.rows == [["paris, fr", "two\nlines"], ['say "hi"', "x"]]
+
+
+def test_a_comma_in_a_quoted_semicolon_header_doesnt_fool_the_detection() -> None:
+    table = read_table(b'"a,b";c\n1;2\n', max_rows=10, max_bytes=1000)
+    assert (table.headers, table.rows) == (["a,b", "c"], [["1", "2"]])
+
+
+@pytest.mark.parametrize(
+    ("data", "code"),
+    [
+        (b"Site\n\xff\xfe\n", "csv_encoding"),
+        (b"", "csv_empty"),
+        (b"\n\n", "csv_empty"),
+        (b"Site,Site\nx,y\n", "csv_duplicate_header"),
+        (b'Site\n"unterminated\n', "csv_malformed"),
+        (b"Site\nx\x00y\n", "csv_malformed"),
+        (b"Site\n1\n2\n3\n", "csv_too_many_rows"),
+        (b"S" * 1001, "csv_too_large"),
+    ],
+)
+def test_a_file_that_cant_be_read_gives_its_code(data: bytes, code: str) -> None:
+    with pytest.raises(CsvFileError) as e:
+        read_table(data, max_rows=2, max_bytes=1000)
+    assert e.value.code == code and code in FILE_CODES
+    assert str(e.value) == code  # never the file's text
+
+
+def test_exact_header_matches_are_mapped() -> None:
+    assert exact_mapping(COLUMNS, ["PSK", "Site", "vlan", "extra"]) == {"psk": "PSK", "site": "Site"}
+
+
+def test_a_mapping_is_checked_against_the_declaration_and_the_file() -> None:
+    headers = ["Site", "VLAN", "PSK"]
+    assert mapping_problems(COLUMNS, {"site": "Site"}, headers) == []
+    assert mapping_problems(COLUMNS, {"vlan": "VLAN"}, headers) == [{"column": "site", "code": "required_unmapped"}]
+    assert mapping_problems(COLUMNS, {"site": "Site", "nope": "VLAN"}, headers) == [
+        {"column": "nope", "code": "unknown_column"}
+    ]
+    assert mapping_problems(COLUMNS, {"site": "Elsewhere"}, headers) == [{"column": "site", "code": "unknown_header"}]
+    assert mapping_problems(COLUMNS, {"site": "Site", "psk": "Site"}, headers) == [
+        {"column": "psk", "code": "header_reused"}
+    ]
+
+
+def test_rows_are_built_typed_with_defaults_filled_and_absent_cells_omitted() -> None:
+    table = read_table(b"Site,VLAN,MAC,PSK,Extra\nparis,,AA-BB-CC-DD-EE-FF,s3cret,ignored\nlyon,20,,,\n",
+                       max_rows=10, max_bytes=1000)  # fmt: skip
+    rows, errors = build_rows(table, COLUMNS, MAPPING)
+    assert errors == []
+    assert rows == [
+        {"site": "paris", "vlan": 1, "mac": "aa:bb:cc:dd:ee:ff", "psk": "s3cret"},
+        {"site": "lyon", "vlan": 20},
+    ]
+
+
+def test_a_row_that_breaks_a_rule_is_its_number_column_and_code() -> None:
+    table = read_table(b"Site,VLAN,MAC\n,x,zz\nok,1\nfine,2,\n", max_rows=10, max_bytes=1000)
+    rows, errors = build_rows(table, COLUMNS, {"site": "Site", "vlan": "VLAN", "mac": "MAC"})
+    assert rows == [{"site": "fine", "vlan": 2}]
+    assert errors == [
+        RowError(1, "site", "required"),
+        RowError(1, "vlan", "not_integer"),
+        RowError(1, "mac", "not_mac"),
+        RowError(2, None, "cell_count"),
+    ]
+
+
+ROW_SCHEMA = trigger_schema({"csv": {"columns": COLUMNS, "max_rows": 10_000}})["properties"]["rows"]["items"]
+CELL = st.text(alphabet=string.printable + "é﻿ ", max_size=12)
+
+
+@settings(max_examples=300, deadline=None)
+@given(st.binary(max_size=400))
+def test_any_bytes_read_as_a_table_or_give_a_file_code(data: bytes) -> None:
+    try:
+        table = read_table(data, max_rows=50, max_bytes=1000)
+    except CsvFileError as e:
+        assert e.code in FILE_CODES
+        return
+    assert len(set(table.headers)) == len(table.headers)
+    assert all(isinstance(cell, str) for row in table.rows for cell in row)
+
+
+@settings(max_examples=300, deadline=None)
+@given(st.lists(st.lists(CELL, min_size=4, max_size=5), max_size=8))
+def test_built_rows_always_match_the_row_schema_and_errors_never_quote_a_cell(cells: list[list[str]]) -> None:
+    from dewpoint.apps.csv_input import Table
+
+    rows, errors = build_rows(Table(["Site", "VLAN", "MAC", "PSK"], cells), COLUMNS, MAPPING)
+    validator = Draft202012Validator(ROW_SCHEMA)
+    assert all(validator.is_valid(row) for row in rows)
+    assert len(rows) + len({e.row for e in errors}) == len(cells)
+    assert all(e.code in CELL_CODES | {"required", "cell_count"} and e.column in (None, *MAPPING) for e in errors)
diff --git a/backend/tests/engine/graph/test_csv_cells.py b/backend/tests/engine/graph/test_csv_cells.py
new file mode 100644
index 0000000..5adfbe7
--- /dev/null
+++ b/backend/tests/engine/graph/test_csv_cells.py
@@ -0,0 +1,67 @@
+# SPDX-License-Identifier: Apache-2.0
+"""A CSV cell converted to its column's canonical value (engine 2b spec §8.1, the owner's ruling 7): `boolean` takes
+true/false, yes/no and 1/0 in any case; `integer` is decimal, within CEL's int; `number` is finite; `mac` is written in
+lowercase colon form; `ip` and `cidr` as Python's `ipaddress` writes them, a `cidr` with host bits set refused; `enum`
+matches exactly. A cell that doesn't convert gives a fixed code, never its text."""
+
+from typing import Any
+
+import pytest
+from hypothesis import given, settings
+from hypothesis import strategies as st
+
+from dewpoint.engine.graph.csv import CELL_CODES, CsvType, convert, is_canonical
+
+
+@pytest.mark.parametrize(
+    ("type_", "text", "value"),
+    [
+        ("string", "  paris ", "  paris "),
+        ("integer", "42", 42), ("integer", "-7", -7), ("integer", "+3", 3), ("integer", "007", 7),
+        ("number", "1.5", 1.5), ("number", "2", 2.0), ("number", "-1e3", -1000.0), ("number", ".5", 0.5),
+        ("boolean", "TRUE", True), ("boolean", "yes", True), ("boolean", "1", True),
+        ("boolean", "False", False), ("boolean", "NO", False), ("boolean", "0", False),
+        ("mac", "AA:BB:CC:DD:EE:FF", "aa:bb:cc:dd:ee:ff"), ("mac", "aa-bb-cc-dd-ee-ff", "aa:bb:cc:dd:ee:ff"),
+        ("mac", "aabb.ccdd.eeff", "aa:bb:cc:dd:ee:ff"), ("mac", "AABBCCDDEEFF", "aa:bb:cc:dd:ee:ff"),
+        ("ip", "10.0.0.1", "10.0.0.1"), ("ip", "2001:DB8:0:0::1", "2001:db8::1"),
+        ("cidr", "10.0.0.0/8", "10.0.0.0/8"), ("cidr", "2001:DB8::/32", "2001:db8::/32"),
+        ("enum", "ap", "ap"),
+    ],
+)  # fmt: skip
+def test_a_cell_converts_to_its_canonical_value(type_: CsvType, text: str, value: Any) -> None:
+    assert convert(type_, text, ["ap", "switch"]) == (value, None)
+    assert is_canonical(type_, value, ["ap", "switch"])
+
+
+@pytest.mark.parametrize(
+    ("type_", "text", "code"),
+    [
+        ("integer", "4.2", "not_integer"), ("integer", "١٢", "not_integer"), ("integer", "1_000", "not_integer"),
+        ("integer", str(2**63), "out_of_range"), ("integer", " 4", "not_integer"),
+        ("number", "nan", "not_number"), ("number", "inf", "not_number"), ("number", "1e400", "not_number"),
+        ("number", "1,5", "not_number"), ("number", "0x10", "not_number"),
+        ("boolean", "y", "not_boolean"), ("boolean", "2", "not_boolean"),
+        ("mac", "aa:bb:cc:dd:ee", "not_mac"), ("mac", "aa:bb-cc:dd:ee:ff", "not_mac"),
+        ("mac", "gg:bb:cc:dd:ee:ff", "not_mac"),
+        ("ip", "10.0.0.256", "not_ip"), ("ip", "010.0.0.1", "not_ip"), ("ip", "host.example", "not_ip"),
+        ("cidr", "10.0.0.1/8", "not_cidr"), ("cidr", "10.0.0.0/33", "not_cidr"),
+        ("enum", "AP", "not_in_enum"), ("enum", "router", "not_in_enum"),
+    ],
+)  # fmt: skip
+def test_a_cell_that_doesnt_convert_gives_its_code(type_: CsvType, text: str, code: str) -> None:
+    assert convert(type_, text, ["ap", "switch"]) == (None, code)
+    assert code in CELL_CODES
+
+
+@settings(max_examples=500, deadline=None)
+@given(
+    st.sampled_from(["string", "integer", "number", "boolean", "mac", "ip", "cidr", "enum"]),
+    st.text(max_size=64),
+)
+def test_any_text_converts_to_a_canonical_value_or_a_fixed_code(type_: CsvType, text: str) -> None:
+    value, code = convert(type_, text, ["ap", "switch"])
+    if code is None:
+        assert is_canonical(type_, value, ["ap", "switch"])
+        assert convert(type_, str(value).lower() if type_ == "boolean" else str(value), ["ap", "switch"])[1] is None
+    else:
+        assert value is None and code in CELL_CODES
```

### Task 6: A CSV upload, staged encrypted for an hour and read as its bytes arrive

**Commit:** `a527753` (prototype `proto/2b3a-v2`); the replay's tree was identical: yes.

**Create:** `backend/migrations/versions/0026_csv_uploads.py`, `backend/src/dewpoint/apps/api/routes/csv_uploads.py`, `backend/src/dewpoint/apps/csv_uploads.py`, `backend/src/dewpoint/core/models/uploads.py`, `backend/tests/apps/api/test_csv_uploads_api.py`, `backend/tests/core/requests/test_csv_uploads_schema.py`

**Modify:** `backend/src/dewpoint/apps/api/main.py`, `backend/src/dewpoint/apps/api/middleware.py`, `backend/src/dewpoint/core/models/__init__.py`, `backend/src/dewpoint/core/requests/digest.py`

**What it does:**

`POST /t/{tid}/workflows/{wid}/csv-uploads` (`run.start`) takes a raw `text/csv` body
(engine 2b spec §8.1; no multipart dependency). The API's middleware buffers a body before
the app runs, so this one route is passed through unread, refused there only past the
platform's 5 MiB as declared: the route authorizes the caller and loads the active
version's declaration first, then reads the body chunk by chunk up to the declaration's own
cap and stops one byte past it with 413, never reading or buffering the rest (the owner's
correction). Every other route keeps the 1 MiB limit.

The file is staged in `csv_uploads` (0026): its headers and cells sealed with the tenant's
key under `csv.upload`, a tenant-keyed digest of the file for its start's audit entry, its
uploader and workflow, expiring after an hour, under forced row-level security. The API may
stage and consume an upload but never delete one: only retention deletes (§10.3). The answer
gives the headers, the exact matches mapped, what keeps that mapping from building rows, a
preview of the first records' mapped cells without the sensitive columns, and each record's
errors as its number, the column's name and a code.

**Later tasks refine this.** Task 9 stages the upload as the file's own sealed bytes, where this task stages its parsed
rows, and lists the first 100 errors with their count.

- [ ] **Step 1: its tests alone, before its code.** Run: `uv run pytest -n 8 tests/apps/api/test_csv_uploads_api.py tests/core/requests/test_csv_uploads_schema.py`. Replay result (exit 1), shortened:

```
FAILED tests/apps/api/test_csv_uploads_api.py::test_a_file_that_cant_be_read_is_refused_with_its_code[\xff\xfe-csv_encoding]
FAILED tests/core/requests/test_csv_uploads_schema.py::test_the_api_consumes_an_upload_but_never_deletes_one
FAILED tests/apps/api/test_csv_uploads_api.py::test_the_declarations_cap_stops_the_read_as_bytes_arrive
FAILED tests/apps/api/test_csv_uploads_api.py::test_an_operator_uploads_a_csv_and_gets_its_mapping_preview_and_errors
FAILED tests/core/requests/test_csv_uploads_schema.py::test_an_upload_is_staged_until_a_start_consumes_it[staged = null]
FAILED tests/apps/api/test_csv_uploads_api.py::test_a_workflow_without_a_csv_takes_no_upload
FAILED tests/core/requests/test_csv_uploads_schema.py::test_an_upload_is_staged_until_a_start_consumes_it[consumed_by = gen_random_uuid(), staged = null]
FAILED tests/apps/api/test_csv_uploads_api.py::test_a_file_that_cant_be_read_is_refused_with_its_code[Site,Site\nx,y\n-csv_duplicate_header]
FAILED tests/apps/api/test_csv_uploads_api.py::test_what_the_route_refuses - ...
FAILED tests/core/requests/test_csv_uploads_schema.py::test_uploads_force_row_level_security
FAILED tests/apps/api/test_csv_uploads_api.py::test_a_file_that_cant_be_read_is_refused_with_its_code[-csv_empty]
FAILED tests/apps/api/test_csv_uploads_api.py::test_a_declared_length_past_the_cap_is_refused_before_reading
FAILED tests/apps/api/test_csv_uploads_api.py::test_the_upload_belongs_to_its_uploader
16 failed, 1 passed in 12.68s
```

- [ ] **Step 2: its code, then the same tests.** Replay result (exit 0), shortened:

```
.................                                                        [100%]
17 passed in 13.44s
```

- [ ] **Step 3: commit.** `git cherry-pick --no-commit a527753 && git commit -C a527753`

The diff:

```diff
diff --git a/backend/migrations/versions/0026_csv_uploads.py b/backend/migrations/versions/0026_csv_uploads.py
new file mode 100644
index 0000000..1e6bc2e
--- /dev/null
+++ b/backend/migrations/versions/0026_csv_uploads.py
@@ -0,0 +1,50 @@
+# SPDX-License-Identifier: Apache-2.0
+"""staged CSV uploads (engine 2b spec §8.1, §14): a file's headers and cells, encrypted, owned by its uploader and
+tenant, for one hour; a start consumes one by clearing its cells, so only retention ever deletes a row (§10.3)"""
+
+import sqlalchemy as sa
+from alembic import op
+from sqlalchemy.dialects import postgresql as pg
+
+revision = "0026"
+down_revision = "0025"
+branch_labels = None
+depends_on = None
+
+
+def upgrade() -> None:
+    op.create_table(
+        "csv_uploads",
+        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
+        sa.Column("tenant_id", pg.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
+        sa.Column("owner_id", pg.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
+        sa.Column("workflow_id", pg.UUID(as_uuid=True), sa.ForeignKey("workflows.id"), nullable=False),
+        # The headers and cells, sealed with the tenant's key under `csv.upload`, the upload's id the context.
+        sa.Column("staged", sa.LargeBinary, nullable=True),
+        # A tenant-keyed HMAC of the file, for its start's audit entry: never an unkeyed hash of its content.
+        sa.Column("file_digest", sa.LargeBinary, nullable=False),
+        sa.Column("digest_key_version", sa.Integer, nullable=False),
+        sa.Column("size_bytes", sa.Integer, nullable=False),
+        sa.Column("row_count", sa.Integer, nullable=False),
+        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
+        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
+        sa.Column("consumed_by", pg.UUID(as_uuid=True), nullable=True),  # the request its start froze
+        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
+        sa.CheckConstraint("(consumed_by IS NULL) = (consumed_at IS NULL)", name="csv_uploads_consumed"),
+        sa.CheckConstraint("(consumed_by IS NULL) = (staged IS NOT NULL)", name="csv_uploads_staged_until_consumed"),
+        sa.CheckConstraint("expires_at > created_at", name="csv_uploads_expiry"),
+    )
+    for statement in (
+        "ALTER TABLE csv_uploads ENABLE ROW LEVEL SECURITY",
+        "ALTER TABLE csv_uploads FORCE ROW LEVEL SECURITY",
+        "CREATE POLICY csv_uploads_scope ON csv_uploads TO dewpoint_api "
+        "USING (tenant_id = app_tenant_id()) WITH CHECK (tenant_id = app_tenant_id())",
+        # The API stages an upload and its start consumes it, in the start's own transaction (admission's).
+        "GRANT SELECT, INSERT ON csv_uploads TO dewpoint_api",
+        "GRANT UPDATE (staged, consumed_by, consumed_at) ON csv_uploads TO dewpoint_api",
+    ):
+        op.execute(statement)
+
+
+def downgrade() -> None:
+    op.drop_table("csv_uploads")
diff --git a/backend/src/dewpoint/apps/api/main.py b/backend/src/dewpoint/apps/api/main.py
index d419786..9729aae 100644
--- a/backend/src/dewpoint/apps/api/main.py
+++ b/backend/src/dewpoint/apps/api/main.py
@@ -12,6 +12,7 @@ from dewpoint.apps.api.routes import (
     audit,
     auth,
     connections,
+    csv_uploads,
     health,
     members,
     mfa,
@@ -27,6 +28,7 @@ from dewpoint.core.crypto.kek import KekSet
 from dewpoint.core.crypto.keyring import Keyring
 from dewpoint.core.crypto.keys import KeyringKeys
 from dewpoint.core.db import make_engine, make_sessionmaker
+from dewpoint.engine.graph.csv import MAX_BYTES as CSV_MAX_BYTES
 
 
 def create_app(settings: Settings | None = None) -> FastAPI:
@@ -49,7 +51,10 @@ def create_app(settings: Settings | None = None) -> FastAPI:
     # Created eagerly (not in the lifespan) so ASGI test transports, which skip lifespan, get it too.
     app.state.http = httpx.AsyncClient(timeout=10, follow_redirects=False)
     app.add_middleware(
-        BodyLimitMiddleware, max_bytes=settings.max_request_body_bytes
+        BodyLimitMiddleware,
+        max_bytes=settings.max_request_body_bytes,
+        streamed=csv_uploads.STREAMED,  # a CSV upload reads its own body, to its declaration's cap
+        streamed_max=CSV_MAX_BYTES,
     )  # innermost: its 413 gets security headers
     app.add_middleware(ClientHeaderMiddleware)
     app.add_middleware(SecurityHeadersMiddleware)
@@ -67,6 +72,7 @@ def create_app(settings: Settings | None = None) -> FastAPI:
         node_types.router,
         workflows.router,
         run_requests.router,
+        csv_uploads.router,
         runs.router,
     ):
         app.include_router(router)
diff --git a/backend/src/dewpoint/apps/api/middleware.py b/backend/src/dewpoint/apps/api/middleware.py
index 4495441..39ac41d 100644
--- a/backend/src/dewpoint/apps/api/middleware.py
+++ b/backend/src/dewpoint/apps/api/middleware.py
@@ -1,4 +1,6 @@
 # SPDX-License-Identifier: Apache-2.0
+import re
+
 from starlette.datastructures import Headers
 from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
 from starlette.requests import Request
@@ -37,17 +39,30 @@ class ClientHeaderMiddleware(BaseHTTPMiddleware):
 class BodyLimitMiddleware:
     """Caps request bodies by the bytes actually received. Content-Length can't be relied on: chunked requests have
     none, and FastAPI parses a body before any route dependency could object. The body is buffered up to the limit
-    before the app runs; one byte more answers 413 without reading the rest."""
+    before the app runs; one byte more answers 413 without reading the rest.
+
+    A `streamed` route (a POST whose path it matches whole) reads its own body as it arrives, to a cap it knows only
+    once it has authorized the caller (a CSV upload's, engine 2b spec §8.1): it's passed through unread, refused here
+    only when it declares more than `streamed_max`, which its own cap never passes."""
 
-    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
+    def __init__(
+        self, app: ASGIApp, max_bytes: int, streamed: re.Pattern[str] | None = None, streamed_max: int = 0
+    ) -> None:
         self.app = app
         self.max_bytes = max_bytes
+        self.streamed, self.streamed_max = streamed, streamed_max
 
     async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
         if scope["type"] != "http":
             await self.app(scope, receive, send)
             return
         declared = Headers(scope=scope).get("content-length", "")
+        if self.streamed is not None and scope["method"] == "POST" and self.streamed.fullmatch(scope["path"]):
+            if declared.isdigit() and int(declared) > self.streamed_max:
+                await JSONResponse({"error": "too_large"}, status_code=413)(scope, receive, send)
+                return
+            await self.app(scope, receive, send)
+            return
         if declared.isdigit() and int(declared) > self.max_bytes:
             await JSONResponse({"error": "too_large"}, status_code=413)(scope, receive, send)
             return
diff --git a/backend/src/dewpoint/apps/api/routes/csv_uploads.py b/backend/src/dewpoint/apps/api/routes/csv_uploads.py
new file mode 100644
index 0000000..88acd5f
--- /dev/null
+++ b/backend/src/dewpoint/apps/api/routes/csv_uploads.py
@@ -0,0 +1,78 @@
+# SPDX-License-Identifier: Apache-2.0
+"""Uploading a CSV for a start (engine 2b spec §8.1): `POST /t/{tid}/workflows/{wid}/csv-uploads`, `run.start`, a raw
+`text/csv` body. The API's middleware buffers a body before the app runs, so this one route is passed through unread
+(`STREAMED`): it authorizes the caller and loads the active version's declaration first, then reads the body as it
+arrives, up to the declaration's cap (never past the platform's 5 MiB), and stops one byte past it with 413, never
+reading or buffering the rest."""
+
+import re
+import uuid
+
+from fastapi import APIRouter, Depends, HTTPException, Request
+from sqlalchemy.ext.asyncio import AsyncSession
+
+from dewpoint.apps import admission
+from dewpoint.apps.api.routes.run_requests import get_keys, key_unusable
+from dewpoint.apps.csv_input import CsvFileError
+from dewpoint.apps.csv_uploads import byte_cap, declaration, stage
+from dewpoint.core.authz.permissions import P
+from dewpoint.core.crypto.keys import KeySource
+from dewpoint.core.http import TenantContext, get_db, require
+from dewpoint.core.models.workflows import Workflow, WorkflowVersion
+
+router = APIRouter(prefix="/api/v1", tags=["runs"])
+STREAMED = re.compile(r"/api/v1/t/[^/]+/workflows/[^/]+/csv-uploads")  # matched whole, for POST
+TOO_LARGE = {"error": "too_large"}
+
+
+class _TooLargeError(Exception):
+    pass
+
+
+async def _read(request: Request, cap: int) -> bytes:
+    """The body as it arrives, stopping at its first byte past `cap`: the rest is never read."""
+    chunks: list[bytes] = []
+    size = 0
+    async for chunk in request.stream():
+        size += len(chunk)
+        if size > cap:
+            raise _TooLargeError
+        chunks.append(chunk)
+    return b"".join(chunks)
+
+
+@router.post("/t/{tenant_id}/workflows/{workflow_id}/csv-uploads", status_code=201)
+async def upload_csv(
+    workflow_id: uuid.UUID,
+    request: Request,
+    ctx: TenantContext = Depends(require(P.RUN_START)),
+    db: AsyncSession = Depends(get_db, scope="function"),
+    keys: KeySource = Depends(get_keys),
+) -> dict[str, object]:
+    """201 with the staged upload's id, its mapping, preview and errors."""
+    if request.headers.get("content-type", "").split(";")[0].strip().lower() != "text/csv":
+        raise HTTPException(415, detail={"error": "unsupported_media_type"})
+    workflow = await db.get(Workflow, workflow_id)  # row-level security: the caller's tenant's only
+    if workflow is None:
+        raise HTTPException(404, detail={"error": "not_found"})
+    version = await db.get(WorkflowVersion, workflow.active_version_id) if workflow.active_version_id else None
+    if version is None:
+        raise HTTPException(409, detail={"error": admission.NOT_ACTIVE})
+    csv = declaration(version)
+    if csv is None:
+        raise HTTPException(409, detail={"error": "csv_not_declared"})
+    cap = byte_cap(csv)
+    declared = request.headers.get("content-length", "")
+    if declared.isdigit() and int(declared) > cap:
+        raise HTTPException(413, detail=TOO_LARGE)
+    try:
+        data = await _read(request, cap)
+    except _TooLargeError:
+        raise HTTPException(413, detail=TOO_LARGE) from None
+    try:
+        return await stage(db, keys, tenant_id=ctx.tenant_id, owner_id=ctx.user.id, workflow_id=workflow_id, csv=csv,
+                           data=data)  # fmt: skip
+    except CsvFileError as e:
+        raise HTTPException(422, detail={"error": e.code}) from None
+    except Exception as e:
+        raise key_unusable(e) from None
diff --git a/backend/src/dewpoint/apps/csv_uploads.py b/backend/src/dewpoint/apps/csv_uploads.py
new file mode 100644
index 0000000..b414244
--- /dev/null
+++ b/backend/src/dewpoint/apps/csv_uploads.py
@@ -0,0 +1,102 @@
+# SPDX-License-Identifier: Apache-2.0
+"""A CSV staged for a start (engine 2b spec §8.1): read as data only (`apps.csv_input`), its headers and cells sealed
+with the tenant's key under `csv.upload` (the upload's id the context), owned by its uploader and tenant for one hour.
+A start consumes it in its own transaction.
+
+What the uploader is told: the file's headers, the declared columns mapped to them (exact matches), what keeps that
+mapping from building rows, a preview of the first records' mapped cells with sensitive columns left out, and each
+record's errors as its number, the column's name and a code. Nothing is logged or audited at upload: the start's audit
+entry keeps the file's tenant-keyed digest and counts."""
+
+import json
+import uuid
+from collections.abc import Mapping, Sequence
+from dataclasses import asdict
+from datetime import timedelta
+from typing import Any
+
+from sqlalchemy import func
+from sqlalchemy.ext.asyncio import AsyncSession
+
+from dewpoint.apps.csv_input import Table, build_rows, exact_mapping, mapping_problems, read_table
+from dewpoint.core.claims.cipher import ClaimCipher
+from dewpoint.core.crypto.keys import KeySource
+from dewpoint.core.models.uploads import CsvUpload
+from dewpoint.core.models.workflows import WorkflowVersion
+from dewpoint.core.requests import digest as digests
+from dewpoint.engine.graph.csv import MAX_BYTES
+
+PURPOSE = "csv.upload"
+TTL = timedelta(hours=1)
+PREVIEW_ROWS = 5
+LISTED_ERRORS = 100  # the response lists this many; its count is every one
+
+
+def declaration(version: WorkflowVersion) -> dict[str, Any] | None:
+    """A version's CSV declaration, as its graph document holds it; None when it declares none."""
+    csv = (version.graph.get("settings") or {}).get("csv")
+    return dict(csv) if csv else None
+
+
+def byte_cap(csv: Mapping[str, Any]) -> int:
+    """The most an upload may send: the declaration's own cap, never past the platform's."""
+    return min(int(csv["max_bytes"]), MAX_BYTES)
+
+
+def described(table: Table, columns: Sequence[Mapping[str, Any]], mapping: Mapping[str, str]) -> dict[str, Any]:
+    """What `mapping` makes of `table`: its problems, the preview and the records' errors."""
+    problems = mapping_problems(columns, mapping, table.headers)
+    errors = [] if problems else build_rows(table, columns, mapping)[1]
+    position = {header: i for i, header in enumerate(table.headers)}
+    shown = [c["name"] for c in columns if not c.get("sensitive") and c["name"] in mapping and not problems]
+    preview = [
+        {"row": number, "cells": {name: _cell(record, position[mapping[name]]) for name in shown}}
+        for number, record in enumerate(table.rows[:PREVIEW_ROWS], start=1)
+    ]
+    return {
+        "mapping": dict(mapping),
+        "problems": problems,
+        "masked_columns": [c["name"] for c in columns if c.get("sensitive")],
+        "preview": preview,
+        "errors": [asdict(e) for e in errors[:LISTED_ERRORS]],
+        "error_count": len(errors),
+    }
+
+
+def _cell(record: list[str], index: int) -> str:
+    return record[index] if index < len(record) else ""
+
+
+async def stage(
+    s: AsyncSession,
+    keys: KeySource,
+    *,
+    tenant_id: uuid.UUID,
+    owner_id: uuid.UUID,
+    workflow_id: uuid.UUID,
+    csv: Mapping[str, Any],
+    data: bytes,
+) -> dict[str, Any]:
+    """The file staged, and what the uploader is told. Raises CsvFileError for a file that can't be read, having
+    staged nothing."""
+    table = read_table(data, max_rows=int(csv["max_rows"]), max_bytes=byte_cap(csv))
+    upload_id = uuid.uuid4()
+    plaintext = json.dumps({"headers": table.headers, "rows": table.rows}, ensure_ascii=False).encode()
+    staged = await ClaimCipher(keys, purpose=PURPOSE).seal(str(tenant_id), str(upload_id), plaintext)
+    key_version, file_digest = await digests.file_digest(keys, str(tenant_id), data)
+    upload = CsvUpload(
+        id=upload_id, tenant_id=tenant_id, owner_id=owner_id, workflow_id=workflow_id, staged=staged,
+        file_digest=file_digest, digest_key_version=key_version, size_bytes=len(data), row_count=len(table.rows),
+        expires_at=func.now() + TTL,
+    )  # fmt: skip
+    s.add(upload)
+    await s.flush()
+    await s.refresh(upload)
+    columns = csv["columns"]
+    return {
+        "upload_id": str(upload_id),
+        "expires_at": upload.expires_at.isoformat(),
+        "headers": table.headers,
+        "row_count": len(table.rows),
+        **described(table, columns, exact_mapping(columns, table.headers)),
+    }
diff --git a/backend/src/dewpoint/core/models/__init__.py b/backend/src/dewpoint/core/models/__init__.py
index 4c0d33a..bc1699c 100644
--- a/backend/src/dewpoint/core/models/__init__.py
+++ b/backend/src/dewpoint/core/models/__init__.py
@@ -9,10 +9,12 @@ from dewpoint.core.models import (
     requests,
     runs,
     tenancy,
+    uploads,
     workflows,
 )
 from dewpoint.core.models.base import Base
 
 __all__ = [
-    "Base", "audit", "claims", "connections", "identity", "keys", "plugins", "requests", "runs", "tenancy", "workflows",
+    "Base", "audit", "claims", "connections", "identity", "keys", "plugins", "requests", "runs", "tenancy", "uploads",
+    "workflows",
 ]  # fmt: skip
diff --git a/backend/src/dewpoint/core/models/uploads.py b/backend/src/dewpoint/core/models/uploads.py
new file mode 100644
index 0000000..53a6085
--- /dev/null
+++ b/backend/src/dewpoint/core/models/uploads.py
@@ -0,0 +1,29 @@
+# SPDX-License-Identifier: Apache-2.0
+"""A CSV staged for a start (engine 2b spec §8.1): its headers and cells encrypted, its uploader, its workflow, and
+when it expires. A start consumes it by clearing its cells; only retention deletes the row (§10.3)."""
+
+import uuid
+from datetime import datetime
+
+from sqlalchemy import DateTime, ForeignKey, Integer, LargeBinary, func
+from sqlalchemy.dialects.postgresql import UUID
+from sqlalchemy.orm import Mapped, mapped_column
+
+from dewpoint.core.models.base import Base
+
+
+class CsvUpload(Base):
+    __tablename__ = "csv_uploads"
+    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
+    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"))
+    owner_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
+    workflow_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("workflows.id"))
+    staged: Mapped[bytes | None] = mapped_column(LargeBinary)
+    file_digest: Mapped[bytes] = mapped_column(LargeBinary)
+    digest_key_version: Mapped[int] = mapped_column(Integer)
+    size_bytes: Mapped[int] = mapped_column(Integer)
+    row_count: Mapped[int] = mapped_column(Integer)
+    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
+    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
+    consumed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
+    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
diff --git a/backend/src/dewpoint/core/requests/digest.py b/backend/src/dewpoint/core/requests/digest.py
index 991c7f7..1935e0c 100644
--- a/backend/src/dewpoint/core/requests/digest.py
+++ b/backend/src/dewpoint/core/requests/digest.py
@@ -43,3 +43,10 @@ async def matches(
     _, fresh = await digest(keys, tenant_id, source=source, workflow_id=workflow_id, mode=mode, input=input,
                             version=version)  # fmt: skip
     return hmac.compare_digest(fresh, stored)
+
+
+async def file_digest(keys: KeySource, tenant_id: str, data: bytes) -> tuple[int, bytes]:
+    """A file's digest with the tenant's active request-digest key (a CSV's, for its start's audit entry, §8.1), and
+    that version. The prefix keeps it apart from any request's: a request's canonical JSON starts with `{`."""
+    version, key = await keys.digest_key(tenant_id, None)
+    return version, hmac.new(key, b"csv-file\x00" + data, hashlib.sha256).digest()
diff --git a/backend/tests/apps/api/test_csv_uploads_api.py b/backend/tests/apps/api/test_csv_uploads_api.py
new file mode 100644
index 0000000..da01dfd
--- /dev/null
+++ b/backend/tests/apps/api/test_csv_uploads_api.py
@@ -0,0 +1,174 @@
+# SPDX-License-Identifier: Apache-2.0
+"""Uploading a CSV for a start (engine 2b spec §8.1): `POST /t/{tid}/workflows/{wid}/csv-uploads` (`run.start`) takes a
+raw `text/csv` body, read as it arrives up to the smaller of the declaration's `max_bytes` and the platform's 5 MiB, and
+stages the file encrypted for one hour, owned by its uploader. It answers with the headers, the exact matches mapped, a
+preview of the first rows with sensitive columns left out, and each row's errors as its number, column and code."""
+
+import uuid
+from collections.abc import AsyncIterator
+from typing import Any
+
+import pytest
+from sqlalchemy import text
+
+from dewpoint.engine.graph.csv import MAX_BYTES
+from tests.apps.api.helpers import member_client
+from tests.apps.api.test_run_requests_api import as_role
+from tests.apps.test_admission import KEYS, published
+from tests.support.graphs import G
+
+pytestmark = pytest.mark.usefixtures("development_deployment")
+CSV = {
+    "columns": [
+        {"header": "Site", "name": "site", "type": "string", "required": True},
+        {"header": "VLAN", "name": "vlan", "type": "integer", "default": 1},
+        {"header": "PSK", "name": "psk", "type": "string", "sensitive": True},
+    ],
+    "max_bytes": 100_000,
+}
+GRAPH = G().node("a", "testkit.echo@1", {"value": 1}).data() | {"settings": {"csv": CSV}}
+FILE = b"Site,VLAN,PSK,Extra\nparis,10,s3cret-psk,x\nlyon,,,y\n,20,k3y-two,z\n"
+CSV_TYPE = {"Content-Type": "text/csv; charset=utf-8"}
+
+
+@pytest.fixture
+def keyed_app(app: Any) -> Any:
+    """The API with fixture keys, which its tenants here have."""
+    app.state.keys = KEYS
+    return app
+
+
+def uploads_url(ctx: Any, wf: uuid.UUID) -> str:
+    return f"/api/v1/t/{ctx.tenant_id}/workflows/{wf}/csv-uploads"
+
+
+@pytest.fixture
+async def csv_workflow(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings) -> Any:
+    return await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings, GRAPH)
+
+
+async def stored(owner: Any, upload_id: str) -> Any:
+    async with owner() as s:
+        found = await s.execute(text("select * from csv_uploads where id = :i"), {"i": upload_id})
+        return found.mappings().one()
+
+
+async def test_an_operator_uploads_a_csv_and_gets_its_mapping_preview_and_errors(
+    keyed_app, csv_workflow, owner_sessionmaker, api_settings
+) -> None:
+    ctx, wf = csv_workflow
+    client = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx)
+    answer = await client.post(uploads_url(ctx, wf), content=FILE, headers=CSV_TYPE)
+    assert answer.status_code == 201, answer.text
+    body = answer.json()
+    assert body["headers"] == ["Site", "VLAN", "PSK", "Extra"]
+    assert body["mapping"] == {"site": "Site", "vlan": "VLAN", "psk": "PSK"}
+    assert (body["row_count"], body["problems"], body["masked_columns"]) == (3, [], ["psk"])
+    assert body["preview"] == [
+        {"row": 1, "cells": {"site": "paris", "vlan": "10"}},
+        {"row": 2, "cells": {"site": "lyon", "vlan": ""}},
+        {"row": 3, "cells": {"site": "", "vlan": "20"}},
+    ]  # the sensitive column and the undeclared one are never shown
+    assert (body["errors"], body["error_count"]) == ([{"row": 3, "column": "site", "code": "required"}], 1)
+    row = await stored(owner_sessionmaker, body["upload_id"])
+    assert (row["workflow_id"], row["size_bytes"], row["row_count"]) == (wf, len(FILE), 3)
+    assert b"s3cret-psk" not in row["staged"] and b"paris" not in row["staged"]  # encrypted
+    assert len(row["file_digest"]) == 32 and row["consumed_by"] is None
+    assert (row["expires_at"] - row["created_at"]).total_seconds() == 3600
+
+
+async def test_the_upload_belongs_to_its_uploader(keyed_app, csv_workflow, owner_sessionmaker, api_settings) -> None:
+    ctx, wf = csv_workflow
+    client, me = await member_client(keyed_app, owner_sessionmaker, api_settings, ctx.tenant_id, "operator")
+    upload = (await client.post(uploads_url(ctx, wf), content=FILE, headers=CSV_TYPE)).json()["upload_id"]
+    assert (await stored(owner_sessionmaker, upload))["owner_id"] == me
+
+
+async def chunks(total: int, size: int, read: list[int]) -> AsyncIterator[bytes]:
+    yield b"Site\n"
+    for _ in range(total // size):
+        read.append(size)
+        yield b"x" * (size - 1) + b"\n"
+
+
+async def test_the_declarations_cap_stops_the_read_as_bytes_arrive(
+    keyed_app, csv_workflow, owner_sessionmaker, api_settings
+) -> None:
+    """A chunked body with no length: the route stops one chunk past the declaration's 100,000 bytes, not after the
+    6 MiB the client would send, and nothing is staged."""
+    ctx, wf = csv_workflow
+    client = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx)
+    read: list[int] = []
+    answer = await client.post(uploads_url(ctx, wf), content=chunks(6 * 1024 * 1024, 16_384, read), headers=CSV_TYPE)
+    assert (answer.status_code, answer.json()) == (413, {"error": "too_large"})
+    assert sum(read) <= 100_000 + 16_384
+    async with owner_sessionmaker() as s:
+        assert (await s.execute(text("select count(*) from csv_uploads"))).scalar_one() == 0
+
+
+async def test_a_declared_length_past_the_cap_is_refused_before_reading(
+    keyed_app, csv_workflow, owner_sessionmaker, api_settings
+) -> None:
+    ctx, wf = csv_workflow
+    client = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx)
+    read: list[int] = []
+    headers = CSV_TYPE | {"Content-Length": str(100_001)}
+    answer = await client.post(uploads_url(ctx, wf), content=chunks(100_001, 16_384, read), headers=headers)
+    assert (answer.status_code, read) == (413, [])
+
+
+async def test_other_routes_keep_the_api_body_limit(keyed_app, csv_workflow, owner_sessionmaker, api_settings) -> None:
+    ctx, wf = csv_workflow
+    client = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx)
+    big = b'{"input": {"x": "' + b"y" * (api_settings.max_request_body_bytes + 1) + b'"}}'
+    answer = await client.post(f"/api/v1/t/{ctx.tenant_id}/workflows/{wf}/runs", content=big,
+                               headers={"Content-Type": "application/json", "Idempotency-Key": "k"})  # fmt: skip
+    assert answer.status_code == 413
+    assert MAX_BYTES > api_settings.max_request_body_bytes
+
+
+@pytest.mark.parametrize(
+    ("body", "code"),
+    [(b"Site,Site\nx,y\n", "csv_duplicate_header"), (b"\xff\xfe", "csv_encoding"), (b"", "csv_empty")],
+)
+async def test_a_file_that_cant_be_read_is_refused_with_its_code(
+    keyed_app, csv_workflow, owner_sessionmaker, api_settings, body: bytes, code: str
+) -> None:
+    ctx, wf = csv_workflow
+    client = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx)
+    answer = await client.post(uploads_url(ctx, wf), content=body, headers=CSV_TYPE)
+    assert (answer.status_code, answer.json()) == (422, {"error": code})
+
+
+async def test_a_required_column_the_file_lacks_is_a_mapping_problem(
+    keyed_app, csv_workflow, owner_sessionmaker, api_settings
+) -> None:
+    ctx, wf = csv_workflow
+    client = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx)
+    body = (await client.post(uploads_url(ctx, wf), content=b"Where,VLAN\nparis,1\n", headers=CSV_TYPE)).json()
+    assert body["mapping"] == {"vlan": "VLAN"}
+    assert (body["problems"], body["errors"]) == ([{"column": "site", "code": "required_unmapped"}], [])
+
+
+async def test_what_the_route_refuses(
+    keyed_app, csv_workflow, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings
+) -> None:
+    ctx, wf = csv_workflow
+    client = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx)
+    assert (await client.post(uploads_url(ctx, wf), content=FILE, headers={"Content-Type": "application/json"})
+            ).status_code == 415  # fmt: skip
+    plain = G().node("a", "testkit.echo@1", {"value": 1}).data()
+    _, other = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings, plain)
+    assert (await client.post(uploads_url(ctx, other), content=FILE, headers=CSV_TYPE)).status_code == 404  # not ours
+    viewer = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "viewer")
+    assert (await viewer.post(uploads_url(ctx, wf), content=FILE, headers=CSV_TYPE)).status_code == 403
+
+
+async def test_a_workflow_without_a_csv_takes_no_upload(
+    keyed_app, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings
+) -> None:
+    plain = G().node("a", "testkit.echo@1", {"value": 1}).data()
+    ctx, wf = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings, plain)
+    client = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx)
+    answer = await client.post(uploads_url(ctx, wf), content=FILE, headers=CSV_TYPE)
+    assert (answer.status_code, answer.json()) == (409, {"error": "csv_not_declared"})
diff --git a/backend/tests/core/requests/test_csv_uploads_schema.py b/backend/tests/core/requests/test_csv_uploads_schema.py
new file mode 100644
index 0000000..8dc4f9d
--- /dev/null
+++ b/backend/tests/core/requests/test_csv_uploads_schema.py
@@ -0,0 +1,80 @@
+# SPDX-License-Identifier: Apache-2.0
+"""Staged CSV uploads (engine 2b spec §8.1, §14): under forced row-level security, the API's only within its tenant;
+staged until a start consumes it, which clears its cells; never deleted by the API, since only retention deletes
+(§10.3)."""
+
+import uuid
+from typing import Any
+
+import pytest
+from sqlalchemy import text
+from sqlalchemy.exc import DBAPIError, IntegrityError
+
+from dewpoint.core.auth.users import create_user
+from dewpoint.core.db import tenant_scope
+from tests.apps.api.helpers import PW
+from tests.support.workflows import seed_workflow
+
+INSERT = text(
+    "insert into csv_uploads (id, tenant_id, owner_id, workflow_id, staged, file_digest, digest_key_version, "
+    "size_bytes, row_count, expires_at) values (:id, :t, :o, :w, :staged, :d, 1, 10, 1, now() + interval '1 hour')"
+)
+
+
+async def upload(api: Any, owner: Any) -> tuple[uuid.UUID, uuid.UUID]:
+    tenant, wf, _ = await seed_workflow(owner)
+    async with owner() as s, s.begin():
+        user = (await create_user(s, email=f"{uuid.uuid4().hex[:8]}@corp.test", password=PW)).id
+    upload_id = uuid.uuid4()
+    async with api() as s, s.begin():
+        await tenant_scope(s, tenant)
+        await s.execute(INSERT, {"id": upload_id, "t": tenant, "o": user, "w": wf, "staged": b"\x01", "d": b"\x02"})
+    return tenant, upload_id
+
+
+async def test_uploads_force_row_level_security(owner_sessionmaker) -> None:
+    async with owner_sessionmaker() as s:
+        flags = (
+            await s.execute(
+                text("select relrowsecurity, relforcerowsecurity from pg_class where relname = 'csv_uploads'")
+            )
+        ).one()
+    assert tuple(flags) == (True, True)
+
+
+async def test_an_upload_is_seen_only_within_its_tenant(api_sessionmaker, owner_sessionmaker) -> None:
+    tenant, upload_id = await upload(api_sessionmaker, owner_sessionmaker)
+    other, _ = await upload(api_sessionmaker, owner_sessionmaker)
+    for scope, seen in ((tenant, 1), (other, 0)):
+        async with api_sessionmaker() as s, s.begin():
+            await tenant_scope(s, scope)
+            found = await s.execute(text("select count(*) from csv_uploads where id = :i"), {"i": upload_id})
+            assert found.scalar_one() == seen
+
+
+async def test_the_api_consumes_an_upload_but_never_deletes_one(api_sessionmaker, owner_sessionmaker) -> None:
+    tenant, upload_id = await upload(api_sessionmaker, owner_sessionmaker)
+    async with api_sessionmaker() as s, s.begin():
+        await tenant_scope(s, tenant)
+        consume = "update csv_uploads set staged = null, consumed_by = :r, consumed_at = now() where id = :i"
+        await s.execute(text(consume), {"i": upload_id, "r": uuid.uuid4()})
+    with pytest.raises(DBAPIError, match="permission denied"):
+        async with api_sessionmaker() as s, s.begin():
+            await tenant_scope(s, tenant)
+            await s.execute(text("delete from csv_uploads where id = :i"), {"i": upload_id})
+
+
+@pytest.mark.parametrize(
+    "change",
+    [
+        "consumed_by = gen_random_uuid(), consumed_at = now()",  # consumed while its cells stay
+        "staged = null",  # cleared without a consumer
+        "consumed_by = gen_random_uuid(), staged = null",  # consumed without a time
+    ],
+)
+async def test_an_upload_is_staged_until_a_start_consumes_it(api_sessionmaker, owner_sessionmaker, change) -> None:
+    tenant, upload_id = await upload(api_sessionmaker, owner_sessionmaker)
+    with pytest.raises(IntegrityError):
+        async with api_sessionmaker() as s, s.begin():
+            await tenant_scope(s, tenant)
+            await s.execute(text(f"update csv_uploads set {change} where id = :i"), {"i": upload_id})
```

### Task 7: A CSV's saved default mapping, marked stale when a later version no longer fits it

**Commit:** `834eae4` (prototype `proto/2b3a-v2`); the replay's tree was identical: yes.

**Create:** `backend/migrations/versions/0027_csv_mappings.py`, `backend/tests/apps/api/test_csv_mappings_api.py`

**Modify:** `backend/src/dewpoint/apps/api/routes/csv_uploads.py`, `backend/src/dewpoint/apps/csv_uploads.py`, `backend/src/dewpoint/core/authz/permissions.py`, `backend/src/dewpoint/core/models/uploads.py`, `backend/tests/core/authz/test_permissions.py`

**What it does:**

`PUT /t/{tid}/workflows/{wid}/csv-mapping` saves a workflow's default mapping, with the new
permission `trigger.manage` (editors and above, engine 2b spec §14), checked against the
active version's declaration (422 `csv_mapping_invalid` with each column's code). It's one
per workflow, in `csv_mappings` (0027), sealed under `csv.mapping`, since a file's header
names are its data, with the version it was saved against.

An upload proposes it when it fits the active version's declaration. One a later version no
longer fits (a column it maps is gone, a required column unmapped) is marked stale on its
row and reported as stale with each column's code, and the exact matches are proposed
instead: it's never applied silently (the owner's ruling 6). Saving a new one clears the
mark. A header the file lacks is the upload's problem, not staleness.

- [ ] **Step 1: its tests alone, before its code.** Run: `uv run pytest -n 8 tests/apps/api/test_csv_mappings_api.py tests/core/authz/test_permissions.py`. Replay result (exit 1), shortened:

```
<replay>/backend/tests/apps/api/test_csv_mappings_api.py:65: KeyError: 'default_mapping'
[gw1] darwin -- Python 3.14.7 <venv>/bin/python
E   AttributeError: type object 'P' has no attribute 'TRIGGER_MANAGE'. Did you mean: 'MEMBER_MANAGE'?
<replay>/backend/tests/core/authz/test_permissions.py:24: AttributeError: type object 'P' has no attribute 'TRIGGER_MANAGE'. Did you mean: 'MEMBER_MANAGE'?
=========================== short test summary info ============================
FAILED tests/apps/api/test_csv_mappings_api.py::test_saving_a_default_needs_trigger_manage
FAILED tests/apps/api/test_csv_mappings_api.py::test_a_mapping_that_doesnt_fit_the_declaration_isnt_saved[mapping0-problems0]
FAILED tests/apps/api/test_csv_mappings_api.py::test_a_header_the_file_lacks_is_the_uploads_problem_not_the_mappings
FAILED tests/apps/api/test_csv_mappings_api.py::test_a_mapping_a_later_version_no_longer_fits_is_stale_and_never_applied
FAILED tests/apps/api/test_csv_mappings_api.py::test_an_editor_saves_a_default_mapping_the_next_upload_proposes
FAILED tests/apps/api/test_csv_mappings_api.py::test_a_mapping_that_doesnt_fit_the_declaration_isnt_saved[mapping1-problems1]
FAILED tests/apps/api/test_csv_mappings_api.py::test_without_a_saved_mapping_the_exact_matches_are_proposed
FAILED tests/core/authz/test_permissions.py::test_managing_triggers_is_an_editors
8 failed, 2 passed in 12.68s
```

- [ ] **Step 2: its code, then the same tests.** Replay result (exit 0), shortened:

```
..........                                                               [100%]
10 passed in 13.26s
```

- [ ] **Step 3: commit.** `git cherry-pick --no-commit 834eae4 && git commit -C 834eae4`

The diff:

```diff
diff --git a/backend/migrations/versions/0027_csv_mappings.py b/backend/migrations/versions/0027_csv_mappings.py
new file mode 100644
index 0000000..81cf207
--- /dev/null
+++ b/backend/migrations/versions/0027_csv_mappings.py
@@ -0,0 +1,39 @@
+# SPDX-License-Identifier: Apache-2.0
+"""a CSV's saved default mapping (engine 2b spec §8.1; the owner's ruling 6): one per workflow, encrypted, with the
+version it was saved against, and when an upload found it no longer fits the active version's declaration"""
+
+import sqlalchemy as sa
+from alembic import op
+from sqlalchemy.dialects import postgresql as pg
+
+revision = "0027"
+down_revision = "0026"
+branch_labels = None
+depends_on = None
+
+
+def upgrade() -> None:
+    op.create_table(
+        "csv_mappings",
+        sa.Column("workflow_id", pg.UUID(as_uuid=True), sa.ForeignKey("workflows.id"), primary_key=True),
+        sa.Column("tenant_id", pg.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
+        # Declared names to the file's headers, sealed under `csv.mapping`, the workflow's id the context: a file's
+        # header names are its data, never plain metadata.
+        sa.Column("mapping", sa.LargeBinary, nullable=False),
+        sa.Column("saved_by", pg.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
+        sa.Column("saved_against", pg.UUID(as_uuid=True), sa.ForeignKey("workflow_versions.id"), nullable=False),
+        sa.Column("saved_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
+        sa.Column("stale_at", sa.DateTime(timezone=True), nullable=True),
+    )
+    for statement in (
+        "ALTER TABLE csv_mappings ENABLE ROW LEVEL SECURITY",
+        "ALTER TABLE csv_mappings FORCE ROW LEVEL SECURITY",
+        "CREATE POLICY csv_mappings_scope ON csv_mappings TO dewpoint_api "
+        "USING (tenant_id = app_tenant_id()) WITH CHECK (tenant_id = app_tenant_id())",
+        "GRANT SELECT, INSERT, UPDATE ON csv_mappings TO dewpoint_api",
+    ):
+        op.execute(statement)
+
+
+def downgrade() -> None:
+    op.drop_table("csv_mappings")
diff --git a/backend/src/dewpoint/apps/api/routes/csv_uploads.py b/backend/src/dewpoint/apps/api/routes/csv_uploads.py
index 88acd5f..c356c0f 100644
--- a/backend/src/dewpoint/apps/api/routes/csv_uploads.py
+++ b/backend/src/dewpoint/apps/api/routes/csv_uploads.py
@@ -7,14 +7,16 @@ reading or buffering the rest."""
 
 import re
 import uuid
+from typing import Annotated, Any
 
 from fastapi import APIRouter, Depends, HTTPException, Request
+from pydantic import BaseModel, ConfigDict, Field
 from sqlalchemy.ext.asyncio import AsyncSession
 
 from dewpoint.apps import admission
 from dewpoint.apps.api.routes.run_requests import get_keys, key_unusable
-from dewpoint.apps.csv_input import CsvFileError
-from dewpoint.apps.csv_uploads import byte_cap, declaration, stage
+from dewpoint.apps.csv_input import CsvFileError, mapping_problems
+from dewpoint.apps.csv_uploads import byte_cap, declaration, save_default, stage
 from dewpoint.core.authz.permissions import P
 from dewpoint.core.crypto.keys import KeySource
 from dewpoint.core.http import TenantContext, get_db, require
@@ -29,6 +31,27 @@ class _TooLargeError(Exception):
     pass
 
 
+class MappingIn(BaseModel):
+    """Declared column names to the file's headers."""
+
+    model_config = ConfigDict(extra="forbid")
+    mapping: dict[Annotated[str, Field(max_length=63)], Annotated[str, Field(max_length=512)]] = Field(max_length=200)
+
+
+async def _active_csv(db: AsyncSession, workflow_id: uuid.UUID) -> tuple[WorkflowVersion, dict[str, Any]]:
+    """The workflow's active version and its CSV declaration: 404, or 409 without either."""
+    workflow = await db.get(Workflow, workflow_id)  # row-level security: the caller's tenant's only
+    if workflow is None:
+        raise HTTPException(404, detail={"error": "not_found"})
+    version = await db.get(WorkflowVersion, workflow.active_version_id) if workflow.active_version_id else None
+    if version is None:
+        raise HTTPException(409, detail={"error": admission.NOT_ACTIVE})
+    csv = declaration(version)
+    if csv is None:
+        raise HTTPException(409, detail={"error": "csv_not_declared"})
+    return version, csv
+
+
 async def _read(request: Request, cap: int) -> bytes:
     """The body as it arrives, stopping at its first byte past `cap`: the rest is never read."""
     chunks: list[bytes] = []
@@ -52,15 +75,7 @@ async def upload_csv(
     """201 with the staged upload's id, its mapping, preview and errors."""
     if request.headers.get("content-type", "").split(";")[0].strip().lower() != "text/csv":
         raise HTTPException(415, detail={"error": "unsupported_media_type"})
-    workflow = await db.get(Workflow, workflow_id)  # row-level security: the caller's tenant's only
-    if workflow is None:
-        raise HTTPException(404, detail={"error": "not_found"})
-    version = await db.get(WorkflowVersion, workflow.active_version_id) if workflow.active_version_id else None
-    if version is None:
-        raise HTTPException(409, detail={"error": admission.NOT_ACTIVE})
-    csv = declaration(version)
-    if csv is None:
-        raise HTTPException(409, detail={"error": "csv_not_declared"})
+    _, csv = await _active_csv(db, workflow_id)
     cap = byte_cap(csv)
     declared = request.headers.get("content-length", "")
     if declared.isdigit() and int(declared) > cap:
@@ -76,3 +91,24 @@ async def upload_csv(
         raise HTTPException(422, detail={"error": e.code}) from None
     except Exception as e:
         raise key_unusable(e) from None
+
+
+@router.put("/t/{tenant_id}/workflows/{workflow_id}/csv-mapping")
+async def save_csv_mapping(
+    workflow_id: uuid.UUID,
+    body: MappingIn,
+    ctx: TenantContext = Depends(require(P.TRIGGER_MANAGE)),
+    db: AsyncSession = Depends(get_db, scope="function"),
+    keys: KeySource = Depends(get_keys),
+) -> dict[str, object]:
+    """The workflow's default mapping, checked against the active version's declaration (the owner's ruling 6)."""
+    version, csv = await _active_csv(db, workflow_id)
+    problems = mapping_problems(csv["columns"], body.mapping, None)
+    if problems:
+        raise HTTPException(422, detail={"error": "csv_mapping_invalid", "problems": problems})
+    try:
+        await save_default(db, keys, tenant_id=ctx.tenant_id, workflow_id=workflow_id, version_id=version.id,
+                           user_id=ctx.user.id, mapping=body.mapping)  # fmt: skip
+    except Exception as e:
+        raise key_unusable(e) from None
+    return {"mapping": body.mapping, "version_id": str(version.id)}
diff --git a/backend/src/dewpoint/apps/csv_uploads.py b/backend/src/dewpoint/apps/csv_uploads.py
index b414244..1eaa523 100644
--- a/backend/src/dewpoint/apps/csv_uploads.py
+++ b/backend/src/dewpoint/apps/csv_uploads.py
@@ -3,10 +3,15 @@
 with the tenant's key under `csv.upload` (the upload's id the context), owned by its uploader and tenant for one hour.
 A start consumes it in its own transaction.
 
-What the uploader is told: the file's headers, the declared columns mapped to them (exact matches), what keeps that
-mapping from building rows, a preview of the first records' mapped cells with sensitive columns left out, and each
-record's errors as its number, the column's name and a code. Nothing is logged or audited at upload: the start's audit
-entry keeps the file's tenant-keyed digest and counts."""
+What the uploader is told: the file's headers, the declared columns mapped to them (the workflow's saved default
+mapping, else the exact matches), what keeps that mapping from building rows, a preview of the first records' mapped
+cells with sensitive columns left out, and each record's errors as its number, the column's name and a code. Nothing
+is logged or audited at upload: the start's audit entry keeps the file's tenant-keyed digest and counts.
+
+A workflow's saved default mapping (the owner's ruling 6) is sealed under `csv.mapping`. An upload proposes it when it
+fits the active version's declaration; one that no longer does is marked stale and reported with each column's code,
+and the exact matches are proposed instead: it's never applied silently, and a start always needs a mapping valid for
+its version."""
 
 import json
 import uuid
@@ -15,18 +20,20 @@ from dataclasses import asdict
 from datetime import timedelta
 from typing import Any
 
-from sqlalchemy import func
+from sqlalchemy import func, update
+from sqlalchemy.dialects.postgresql import insert
 from sqlalchemy.ext.asyncio import AsyncSession
 
 from dewpoint.apps.csv_input import Table, build_rows, exact_mapping, mapping_problems, read_table
 from dewpoint.core.claims.cipher import ClaimCipher
 from dewpoint.core.crypto.keys import KeySource
-from dewpoint.core.models.uploads import CsvUpload
+from dewpoint.core.models.uploads import CsvMapping, CsvUpload
 from dewpoint.core.models.workflows import WorkflowVersion
 from dewpoint.core.requests import digest as digests
 from dewpoint.engine.graph.csv import MAX_BYTES
 
 PURPOSE = "csv.upload"
+MAPPING_PURPOSE = "csv.mapping"
 TTL = timedelta(hours=1)
 PREVIEW_ROWS = 5
 LISTED_ERRORS = 100  # the response lists this many; its count is every one
@@ -93,10 +100,48 @@ async def stage(
     await s.flush()
     await s.refresh(upload)
     columns = csv["columns"]
+    mapping, default = await proposed(s, keys, tenant_id=tenant_id, workflow_id=workflow_id, columns=columns,
+                                      headers=table.headers)  # fmt: skip
     return {
         "upload_id": str(upload_id),
         "expires_at": upload.expires_at.isoformat(),
         "headers": table.headers,
         "row_count": len(table.rows),
-        **described(table, columns, exact_mapping(columns, table.headers)),
+        "default_mapping": default,
+        **described(table, columns, mapping),
     }
+
+
+async def save_default(
+    s: AsyncSession, keys: KeySource, *, tenant_id: uuid.UUID, workflow_id: uuid.UUID, version_id: uuid.UUID,
+    user_id: uuid.UUID, mapping: Mapping[str, str],
+) -> None:  # fmt: skip
+    """`mapping`, checked against the version's declaration by the caller, as the workflow's default; not stale."""
+    plaintext = json.dumps(dict(mapping), sort_keys=True, ensure_ascii=False).encode()
+    sealed = await ClaimCipher(keys, purpose=MAPPING_PURPOSE).seal(str(tenant_id), str(workflow_id), plaintext)
+    values = {"mapping": sealed, "saved_by": user_id, "saved_against": version_id, "saved_at": func.now(),
+              "stale_at": None}  # fmt: skip
+    await s.execute(
+        insert(CsvMapping)
+        .values(workflow_id=workflow_id, tenant_id=tenant_id, **values)
+        .on_conflict_do_update(index_elements=[CsvMapping.workflow_id], set_=values)
+    )
+
+
+async def proposed(
+    s: AsyncSession, keys: KeySource, *, tenant_id: uuid.UUID, workflow_id: uuid.UUID,
+    columns: Sequence[Mapping[str, Any]], headers: Sequence[str],
+) -> tuple[dict[str, str], dict[str, Any]]:  # fmt: skip
+    """The mapping an upload proposes, and what became of the saved default: none, applied, or stale with its
+    problems (marked on its row the first time an upload finds it), the exact matches proposed instead."""
+    saved = await s.get(CsvMapping, workflow_id, populate_existing=True)  # row-level security: the tenant's only
+    if saved is None:
+        return exact_mapping(columns, headers), {"status": "none"}
+    plaintext = await ClaimCipher(keys, purpose=MAPPING_PURPOSE).open(str(tenant_id), str(workflow_id), saved.mapping)
+    mapping: dict[str, str] = json.loads(plaintext)
+    problems = mapping_problems(columns, mapping, None)  # the declaration's: a file's own headers aren't staleness
+    if not problems:
+        return mapping, {"status": "applied"}
+    if saved.stale_at is None:
+        await s.execute(update(CsvMapping).where(CsvMapping.workflow_id == workflow_id).values(stale_at=func.now()))
+    return exact_mapping(columns, headers), {"status": "stale", "problems": problems}
diff --git a/backend/src/dewpoint/core/authz/permissions.py b/backend/src/dewpoint/core/authz/permissions.py
index 49e4242..e7d64e9 100644
--- a/backend/src/dewpoint/core/authz/permissions.py
+++ b/backend/src/dewpoint/core/authz/permissions.py
@@ -18,13 +18,14 @@ class P(StrEnum):
     RUN_START = "run.start"
     RUN_VIEW = "run.view"
     RUN_CANCEL = "run.cancel"  # a queued request at once, a running run through the dispatcher (2b §7.7)
+    TRIGGER_MANAGE = "trigger.manage"  # schedules, a CSV's saved default mapping (2b §8, §14)
     APPROVAL_DECIDE = "approval.decide"
     AGENT_GRANT = "agent.grant"
 
 
 _VIEWER = frozenset({P.TENANT_VIEW, P.WORKFLOW_VIEW, P.RUN_VIEW, P.CONNECTION_VIEW, P.MEMBER_VIEW})
 _OPERATOR = _VIEWER | {P.RUN_START, P.RUN_CANCEL, P.APPROVAL_DECIDE}
-_EDITOR = _OPERATOR | {P.WORKFLOW_EDIT, P.WORKFLOW_PUBLISH, P.CONNECTION_USE}
+_EDITOR = _OPERATOR | {P.WORKFLOW_EDIT, P.WORKFLOW_PUBLISH, P.CONNECTION_USE, P.TRIGGER_MANAGE}
 _ADMIN = _EDITOR | {
     P.TENANT_MANAGE,
     P.MEMBER_MANAGE,
diff --git a/backend/src/dewpoint/core/models/uploads.py b/backend/src/dewpoint/core/models/uploads.py
index 53a6085..94080f8 100644
--- a/backend/src/dewpoint/core/models/uploads.py
+++ b/backend/src/dewpoint/core/models/uploads.py
@@ -27,3 +27,17 @@ class CsvUpload(Base):
     expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
     consumed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
     consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
+
+
+class CsvMapping(Base):
+    """A workflow's saved default mapping (§8.1): sealed, with the version it was saved against; `stale_at` once an
+    upload found it no longer fits the active version's declaration, until a new one is saved."""
+
+    __tablename__ = "csv_mappings"
+    workflow_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("workflows.id"), primary_key=True)
+    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"))
+    mapping: Mapped[bytes] = mapped_column(LargeBinary)
+    saved_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
+    saved_against: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("workflow_versions.id"))
+    saved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
+    stale_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
diff --git a/backend/tests/apps/api/test_csv_mappings_api.py b/backend/tests/apps/api/test_csv_mappings_api.py
new file mode 100644
index 0000000..3da45ce
--- /dev/null
+++ b/backend/tests/apps/api/test_csv_mappings_api.py
@@ -0,0 +1,123 @@
+# SPDX-License-Identifier: Apache-2.0
+"""A CSV's saved default mapping (engine 2b spec §8.1; the owner's ruling 6): one per workflow, encrypted, saved with
+`trigger.manage` against the active version's declaration. An upload proposes it; one a later version no longer fits
+(a column it maps is gone, a required column unmapped) is marked stale and returned as stale with each column's code,
+never applied, until a new one is saved."""
+
+from typing import Any
+
+import pytest
+from sqlalchemy import text
+
+from tests.apps.api.test_csv_uploads_api import CSV, CSV_TYPE, GRAPH, uploads_url
+from tests.apps.api.test_run_requests_api import as_role
+from tests.apps.test_admission import KEYS, published
+from tests.apps.test_workflow_ops import publish, save
+from tests.support.graphs import G
+
+pytestmark = pytest.mark.usefixtures("development_deployment")
+MAPPING = {"site": "Where", "vlan": "Vlan id"}
+FILE = b"Where,Vlan id,PSK\nparis,10,s3cret\n"
+
+
+@pytest.fixture
+def keyed_app(app: Any) -> Any:
+    app.state.keys = KEYS
+    return app
+
+
+def mapping_url(ctx: Any, wf: Any) -> str:
+    return f"/api/v1/t/{ctx.tenant_id}/workflows/{wf}/csv-mapping"
+
+
+@pytest.fixture
+async def csv_workflow(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings) -> Any:
+    return await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings, GRAPH)
+
+
+async def saved(owner: Any) -> Any:
+    async with owner() as s:
+        return (await s.execute(text("select * from csv_mappings"))).mappings().one()
+
+
+async def test_an_editor_saves_a_default_mapping_the_next_upload_proposes(
+    keyed_app, csv_workflow, owner_sessionmaker, api_settings
+) -> None:
+    ctx, wf = csv_workflow
+    editor = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "editor")
+    answer = await editor.put(mapping_url(ctx, wf), json={"mapping": MAPPING})
+    assert answer.status_code == 200, answer.text
+    assert answer.json()["mapping"] == MAPPING
+    row = await saved(owner_sessionmaker)
+    assert b"Where" not in row["mapping"] and row["stale_at"] is None  # encrypted
+    operator = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx)
+    body = (await operator.post(uploads_url(ctx, wf), content=FILE, headers=CSV_TYPE)).json()
+    assert (body["default_mapping"], body["mapping"], body["problems"]) == ({"status": "applied"}, MAPPING, [])
+    assert body["preview"] == [{"row": 1, "cells": {"site": "paris", "vlan": "10"}}]
+
+
+async def test_without_a_saved_mapping_the_exact_matches_are_proposed(
+    keyed_app, csv_workflow, owner_sessionmaker, api_settings
+) -> None:
+    ctx, wf = csv_workflow
+    operator = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx)
+    body = (await operator.post(uploads_url(ctx, wf), content=b"Site,PSK\nx,y\n", headers=CSV_TYPE)).json()
+    assert (body["default_mapping"], body["mapping"]) == ({"status": "none"}, {"site": "Site", "psk": "PSK"})
+
+
+async def test_a_header_the_file_lacks_is_the_uploads_problem_not_the_mappings(
+    keyed_app, csv_workflow, owner_sessionmaker, api_settings
+) -> None:
+    ctx, wf = csv_workflow
+    editor = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "editor")
+    await editor.put(mapping_url(ctx, wf), json={"mapping": MAPPING})
+    body = (await editor.post(uploads_url(ctx, wf), content=b"Where\nparis\n", headers=CSV_TYPE)).json()
+    assert body["default_mapping"] == {"status": "applied"}
+    assert body["problems"] == [{"column": "vlan", "code": "unknown_header"}]
+    assert (await saved(owner_sessionmaker))["stale_at"] is None
+
+
+async def test_a_mapping_a_later_version_no_longer_fits_is_stale_and_never_applied(
+    keyed_app, csv_workflow, owner_sessionmaker, api_sessionmaker, api_settings
+) -> None:
+    ctx, wf = csv_workflow
+    editor = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "editor")
+    await editor.put(mapping_url(ctx, wf), json={"mapping": MAPPING})
+    columns = [CSV["columns"][0], {"header": "Region", "name": "region", "type": "string", "required": True}]
+    v2 = G().node("a", "testkit.echo@1", {"value": 1}).data() | {"settings": {"csv": {"columns": columns}}}
+    await save(api_sessionmaker, ctx, wf, v2)
+    assert (await publish(api_sessionmaker, ctx, wf, api_settings)).version is not None
+    body = (await editor.post(uploads_url(ctx, wf), content=b"Site,Region\nparis,eu\n", headers=CSV_TYPE)).json()
+    assert body["default_mapping"] == {
+        "status": "stale",
+        "problems": [{"column": "vlan", "code": "unknown_column"}, {"column": "region", "code": "required_unmapped"}],
+    }
+    assert body["mapping"] == {"site": "Site", "region": "Region"}  # the exact matches, never the stale mapping
+    assert (await saved(owner_sessionmaker))["stale_at"] is not None
+    assert (await editor.put(mapping_url(ctx, wf), json={"mapping": {"site": "Site", "region": "Region"}})
+            ).status_code == 200  # fmt: skip
+    assert (await saved(owner_sessionmaker))["stale_at"] is None
+
+
+@pytest.mark.parametrize(
+    ("mapping", "problems"),
+    [
+        ({"site": "Where", "nope": "X"}, [{"column": "nope", "code": "unknown_column"}]),
+        ({"vlan": "VLAN"}, [{"column": "site", "code": "required_unmapped"}]),
+    ],
+)
+async def test_a_mapping_that_doesnt_fit_the_declaration_isnt_saved(
+    keyed_app, csv_workflow, owner_sessionmaker, api_settings, mapping: dict[str, str], problems: list[Any]
+) -> None:
+    ctx, wf = csv_workflow
+    editor = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "editor")
+    answer = await editor.put(mapping_url(ctx, wf), json={"mapping": mapping})
+    assert (answer.status_code, answer.json()) == (422, {"error": "csv_mapping_invalid", "problems": problems})
+    async with owner_sessionmaker() as s:
+        assert (await s.execute(text("select count(*) from csv_mappings"))).scalar_one() == 0
+
+
+async def test_saving_a_default_needs_trigger_manage(keyed_app, csv_workflow, owner_sessionmaker, api_settings) -> None:
+    ctx, wf = csv_workflow
+    operator = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx)
+    assert (await operator.put(mapping_url(ctx, wf), json={"mapping": MAPPING})).status_code == 403
diff --git a/backend/tests/core/authz/test_permissions.py b/backend/tests/core/authz/test_permissions.py
index 4deebf5..a787759 100644
--- a/backend/tests/core/authz/test_permissions.py
+++ b/backend/tests/core/authz/test_permissions.py
@@ -17,3 +17,8 @@ def test_key_grants() -> None:
     assert P.AGENT_GRANT in ROLE_PERMISSIONS["admin"]
     assert P.RUN_START in ROLE_PERMISSIONS["operator"] and P.WORKFLOW_EDIT not in ROLE_PERMISSIONS["operator"]
     assert ROLE_PERMISSIONS["viewer"] == {P.TENANT_VIEW, P.WORKFLOW_VIEW, P.RUN_VIEW, P.CONNECTION_VIEW, P.MEMBER_VIEW}
+
+
+def test_managing_triggers_is_an_editors() -> None:
+    """Schedules and a CSV's saved default mapping (engine 2b spec §8, §14): editors and above."""
+    assert P.TRIGGER_MANAGE in ROLE_PERMISSIONS["editor"] and P.TRIGGER_MANAGE not in ROLE_PERMISSIONS["operator"]
```

### Task 8: CSV starts: key first, one consumer, rows frozen and the upload consumed

**Commit:** `eaafdc9` (prototype `proto/2b3a-v2`); the replay's tree was identical: yes.

**Create:** `backend/migrations/versions/0028_csv_records.py`, `backend/tests/apps/api/test_csv_starts_api.py`, `backend/tests/apps/test_admission_csv.py`

**Modify:** `backend/src/dewpoint/apps/admission.py`, `backend/src/dewpoint/apps/api/routes/run_requests.py`, `backend/src/dewpoint/apps/api/routes/runs.py`, `backend/src/dewpoint/core/claims/service.py`, `backend/tests/apps/api/test_run_requests_api.py`, `backend/tests/core/requests/test_csv_uploads_schema.py`

**What it does:**

`POST …/runs` takes `csv: {upload_id, mapping, skip_invalid}`, and a re-run a new upload
(engine 2b spec §8.1; the owner's ruling 5 and the M1 corrections):
- the key first: the digest covers what was asked (the input, the upload, the mapping,
  `skip_invalid`), so an exact retry is recognized without rebuilding the rows, after the
  upload is consumed, and it's returned only to the upload's owner; anyone else gets the
  same 409 as a conflict;
- then the upload, locked FOR UPDATE and checked: its tenant, owner and workflow (else
  `upload_not_found`, whoever's it is), not expired (`upload_expired`, 410), not consumed:
  a start that finds it consumed looks its own key up again, since the consumer has
  committed, so concurrent starts yield one consumer and an exact retry its request;
- the rows are built against the frozen version's declaration (`csv_mapping_invalid`, or
  `input_invalid` naming each row, column and code; `skip_invalid` keeps the valid rows),
  claimed with the rest of the trigger (sensitive cells with taint), and the upload is
  consumed by an UPDATE that clears its cells (§10.3: only retention deletes);
- the mapping, the file's headers and the skipped rows go into a `run_inputs` row of the
  role `csv` (0028): no pointer, one per request, never a claim; the run's details show it
  to `run.view`; the audit entry keeps the file's tenant-keyed digest and counts only.

A re-run's original input brings its rows back from the retained claims, which admission
accepts only as a re-run's own; a re-run's digest gains its CSV only when it has one, so
earlier re-runs' digests are unchanged.

**Later tasks refine this.** Task 9 reads the staged file again under the frozen version's caps, and keeps a bounded CSV
record (every skipped row's number and first code, the first 100 errors, the count).

- [ ] **Step 1: its tests alone, before its code.** Run: `uv run pytest -n 8 tests/apps/api/test_csv_starts_api.py tests/apps/api/test_run_requests_api.py tests/apps/test_admission_csv.py tests/core/requests/test_csv_uploads_schema.py`. Replay result (exit 1), shortened:

```
FAILED tests/apps/test_admission_csv.py::test_an_exact_retry_returns_its_request_after_the_upload_was_consumed
FAILED tests/apps/test_admission_csv.py::test_concurrent_starts_with_one_upload_yield_one_consumer[True]
FAILED tests/apps/test_admission_csv.py::test_an_exact_retry_is_returned_only_to_the_uploads_owner
FAILED tests/apps/test_admission_csv.py::test_a_mapping_the_frozen_version_refuses_is_refused
FAILED tests/apps/test_admission_csv.py::test_another_start_with_a_consumed_upload_is_refused
FAILED tests/apps/test_admission_csv.py::test_concurrent_starts_with_one_upload_yield_one_consumer[False]
FAILED tests/apps/test_admission_csv.py::test_an_expired_upload_is_refused - ...
FAILED tests/apps/test_admission_csv.py::test_an_upload_of_another_user_or_workflow_is_never_found
FAILED tests/apps/test_admission_csv.py::test_a_workflow_without_a_csv_takes_no_csv_start
FAILED tests/apps/test_admission_csv.py::test_a_row_that_breaks_a_rule_refuses_the_start_unless_invalid_rows_are_skipped
FAILED tests/apps/test_admission_csv.py::test_a_csv_start_still_refuses_rows_in_its_input
FAILED tests/apps/test_admission_csv.py::test_a_rerun_takes_the_original_rows_or_a_new_csv
FAILED tests/core/requests/test_csv_uploads_schema.py::test_a_csv_record_is_never_a_claim
18 failed, 34 passed in 16.60s
```

- [ ] **Step 2: its code, then the same tests.** Replay result (exit 0), shortened:

```
....................................................                     [100%]
52 passed in 15.98s
```

- [ ] **Step 3: commit.** `git cherry-pick --no-commit eaafdc9 && git commit -C eaafdc9`

The diff:

```diff
diff --git a/backend/migrations/versions/0028_csv_records.py b/backend/migrations/versions/0028_csv_records.py
new file mode 100644
index 0000000..d6a63f6
--- /dev/null
+++ b/backend/migrations/versions/0028_csv_records.py
@@ -0,0 +1,35 @@
+# SPDX-License-Identifier: Apache-2.0
+"""a CSV start's record (engine 2b spec §8.1, §7.1): the mapping, the file's header names and the skipped rows, kept
+encrypted in `run_inputs` under a third role, `csv`, beside the request's envelope and claims; like the envelope, never
+a claim (no pointer, at most one per request), and kept and deleted with its request"""
+
+import sqlalchemy as sa
+from alembic import op
+
+revision = "0028"
+down_revision = "0027"
+branch_labels = None
+depends_on = None
+
+
+def upgrade() -> None:
+    op.drop_constraint("run_inputs_role", "run_inputs")
+    op.create_check_constraint(
+        "run_inputs_role",
+        "run_inputs",
+        "(role = 'claim' AND pointer IS NOT NULL) OR (role IN ('envelope', 'csv') AND pointer IS NULL)",
+    )
+    op.create_index(
+        "run_inputs_one_csv", "run_inputs", ["owner_run_id"], unique=True, postgresql_where=sa.text("role = 'csv'")
+    )
+
+
+def downgrade() -> None:
+    op.drop_index("run_inputs_one_csv", "run_inputs")
+    op.execute("DELETE FROM run_inputs WHERE role = 'csv'")
+    op.drop_constraint("run_inputs_role", "run_inputs")
+    op.create_check_constraint(
+        "run_inputs_role",
+        "run_inputs",
+        "(role = 'claim' AND pointer IS NOT NULL) OR (role = 'envelope' AND pointer IS NULL)",
+    )
diff --git a/backend/src/dewpoint/apps/admission.py b/backend/src/dewpoint/apps/admission.py
index 751b3cd..0e70fa8 100644
--- a/backend/src/dewpoint/apps/admission.py
+++ b/backend/src/dewpoint/apps/admission.py
@@ -15,17 +15,27 @@ In §7.2's order:
    insert that won the key rolls this call back, claims and envelope included, and the winner is compared instead.
 
 A durable source's refusal is kept as a `refused` request with its reason, never lost; an interactive one's is raised.
-The request's id is its run's, once it starts: its claims and envelope are owned by it from the start."""
+The request's id is its run's, once it starts: its claims and envelope are owned by it from the start.
 
+A CSV start (2b-3a, §8.1) is a manual start or a re-run given a staged upload: its digest covers what was asked, so an
+exact retry is recognized without the rows, and returned only to the upload's owner. A new key locks the upload and
+checks it (its tenant, owner and workflow, not expired, not consumed: a consumed one sends the start back to its key,
+which a concurrent start under it has taken), builds its rows against the frozen version's declaration, claims them
+with the rest of the trigger, keeps the mapping, headers and skipped rows as the request's CSV record, and consumes the
+upload, all in the same savepoint."""
+
+import json
 import uuid
-from dataclasses import dataclass
+from dataclasses import asdict, dataclass
 from datetime import timedelta
 from typing import Any
 
-from sqlalchemy import func, select
+from sqlalchemy import func, select, update
 from sqlalchemy.dialects.postgresql import insert
 from sqlalchemy.ext.asyncio import AsyncSession
 
+from dewpoint.apps import csv_uploads
+from dewpoint.apps.csv_input import RowError, Table, build_rows, mapping_problems
 from dewpoint.apps.inputs import INPUT_INVALID, RESERVED_INPUT, InputRefusedError, claim_input
 from dewpoint.apps.workflow_ops import abi_reasons
 from dewpoint.core.audit import service as audit
@@ -35,6 +45,7 @@ from dewpoint.core.crypto.keys import KeySource
 from dewpoint.core.db import tenant_scope
 from dewpoint.core.models.requests import CurrentBuild, RunRequest
 from dewpoint.core.models.tenancy import Tenant
+from dewpoint.core.models.uploads import CsvUpload
 from dewpoint.core.models.workflows import WorkflowVersion
 from dewpoint.core.platform.service import NOT_RECORDED, PRODUCTION, recorded
 from dewpoint.core.plugins import lifecycle
@@ -58,6 +69,12 @@ NO_CURRENT_BUILD = "no_current_build"
 VERSION_UNUSABLE = "version_unusable"
 NODE_TYPE_RETIRED = "node_type_retired"
 CEL_PROFILE_RETIRED = "cel_profile_retired"
+CSV_NOT_DECLARED = "csv_not_declared"
+CSV_MAPPING_INVALID = "csv_mapping_invalid"
+UPLOAD_NOT_FOUND = "upload_not_found"
+UPLOAD_EXPIRED = "upload_expired"
+UPLOAD_CONSUMED = "upload_consumed"
+_LISTED = 5  # a refusal lists this many of the CSV's problems
 
 GATE_OFF = (
     "Production runs are off in this deployment: no run starts in a production deployment until its gate lifts "
@@ -85,17 +102,34 @@ class WorkflowNotFoundError(LookupError):
     """No such workflow in the caller's tenant."""
 
 
+@dataclass(frozen=True)
+class CsvStart:
+    """A start's CSV: the staged upload, the mapping from declared column names to its headers, and whether rows that
+    break a rule are skipped (recorded) rather than refusing the start."""
+
+    upload_id: uuid.UUID
+    mapping: dict[str, str]
+    skip_invalid: bool = False
+
+    def digested(self) -> dict[str, Any]:
+        return {"upload_id": str(self.upload_id), "mapping": dict(self.mapping), "skip_invalid": self.skip_invalid}
+
+
 @dataclass(frozen=True)
 class Rerun:
-    """A re-run's identity: the request (or, from before 2b-2, the run) it re-runs, and the new input it was given,
-    if any. Its idempotency digest covers this in place of the input it admits, so an exact retry is recognized, and
-    another request under the key refused, without rebuilding the old input, which retention may have removed."""
+    """A re-run's identity: the request (or, from before 2b-2, the run) it re-runs, and the new input (and CSV) it was
+    given, if any. Its idempotency digest covers this in place of the input it admits, so an exact retry is recognized,
+    and another request under the key refused, without rebuilding the old input, which retention may have removed."""
 
     of: uuid.UUID
     input: dict[str, Any] | None = None
+    csv: CsvStart | None = None
 
     def digested(self) -> dict[str, Any]:
-        return {"rerun_of": str(self.of), "input": self.input}
+        digested: dict[str, Any] = {"rerun_of": str(self.of), "input": self.input}
+        if self.csv is not None:  # only then: earlier re-runs' digests stay what they were
+            digested["csv"] = self.csv.digested()
+        return digested
 
 
 @dataclass(frozen=True)
@@ -109,10 +143,25 @@ class _Refused(Exception):
         self.reason, self.messages, self.version_id = reason, messages, version_id
 
 
+class _Consumed(Exception):
+    """The upload was consumed: by a start under this key (an exact retry), or another (`upload_consumed`)."""
+
+
+@dataclass(frozen=True)
+class _Frozen:
+    version_id: uuid.UUID
+    envelope_id: uuid.UUID
+    details: dict[str, object]  # the audit entry's, beyond the request's own
+
+
 async def _before_insert() -> None:
     """Runs between a new request's claims and its insert. A no-op; the race tests commit a competing request here."""
 
 
+async def _after_upload_locked() -> None:
+    """Runs once a CSV start holds its upload's row lock. A no-op; the race tests start a competing start here."""
+
+
 async def admit_request(
     s: AsyncSession,
     keys: KeySource,
@@ -125,23 +174,38 @@ async def admit_request(
     idempotency_key: str,
     input: dict[str, Any],
     rerun: Rerun | None = None,
+    csv: CsvStart | None = None,
 ) -> Admitted:
     """The request under `idempotency_key`: an exact retry's, or a new one, frozen. A re-run's digest covers its
-    `rerun` identity in place of `input`. Raises IdempotencyConflictError, WorkflowNotFoundError, or, for an
-    interactive source, AdmissionRefusedError."""
+    `rerun` identity in place of `input`, and a CSV start's its `csv` beside it. Raises IdempotencyConflictError,
+    WorkflowNotFoundError, or, for an interactive source, AdmissionRefusedError."""
     if source not in INTERACTIVE + DURABLE or mode not in (LIVE, SIMULATE):
         raise ValueError(f"no such source or mode: {source}, {mode}")
+    if csv is not None and source not in ("manual", "rerun"):
+        raise ValueError(f"a {source} start takes no CSV")
     await lifecycle.assert_read_committed(s)
     await tenant_scope(s, tenant_id)
     fields: dict[str, Any] = {"source": source, "workflow_id": workflow_id, "mode": mode, "input": input}
-    digested = {**fields, "input": rerun.digested()} if rerun is not None else fields
+    if rerun is not None:
+        digested = {**fields, "input": rerun.digested()}
+    elif csv is not None:
+        digested = {**fields, "input": {"input": input, "csv": csv.digested()}}
+    else:
+        digested = fields
+    owner = actor_id if csv is not None else None  # a CSV start's exact retry is its upload owner's only
     existing = await _by_key(s, idempotency_key)
     if existing is not None:
-        return await _retry(keys, tenant_id, existing, digested)
+        return await _retry(keys, tenant_id, existing, digested, owner)
     request_id = uuid.uuid4()
     savepoint = await s.begin_nested()
     try:
-        version_id, envelope_id = await _frozen(s, keys, tenant_id, request_id, fields)
+        frozen = await _frozen(s, keys, tenant_id, request_id, fields, actor_id, rerun, csv)
+    except _Consumed:
+        await savepoint.rollback()
+        existing = await _by_key(s, idempotency_key)  # its consumer has committed: under this key, an exact retry
+        if existing is not None:
+            return await _retry(keys, tenant_id, existing, digested, owner)
+        raise AdmissionRefusedError(UPLOAD_CONSUMED, ["This upload has already started a run."]) from None
     except _Refused as refused:
         await savepoint.rollback()
         if source in INTERACTIVE:
@@ -149,28 +213,30 @@ async def admit_request(
         return await _insert(s, keys, tenant_id, request_id, actor_id, idempotency_key, digested, None, None, refused,
                              rerun)  # fmt: skip
     await _before_insert()
-    admitted = await _insert(s, keys, tenant_id, request_id, actor_id, idempotency_key, digested, version_id,
-                             envelope_id, rerun=rerun)  # fmt: skip
+    admitted = await _insert(s, keys, tenant_id, request_id, actor_id, idempotency_key, digested, frozen.version_id,
+                             frozen.envelope_id, rerun=rerun, extra=frozen.details)  # fmt: skip
     if admitted.new:
         await savepoint.commit()
     else:
         await savepoint.rollback()  # another transaction won the key: this call's claims and envelope go with it
-        return await _retry(keys, tenant_id, await _winner(s, idempotency_key), digested)
+        return await _retry(keys, tenant_id, await _winner(s, idempotency_key), digested, owner)
     return admitted
 
 
 async def admitted_under(
     s: AsyncSession, keys: KeySource, *, tenant_id: uuid.UUID, idempotency_key: str, source: str,
-    workflow_id: uuid.UUID, mode: str, rerun: Rerun,
+    workflow_id: uuid.UUID, mode: str, rerun: Rerun, actor_id: uuid.UUID | None = None,
 ) -> RunRequest | None:  # fmt: skip
     """The request an exact retry of this re-run finds under its key, before its input is rebuilt; None when the key
-    is free. Raises IdempotencyConflictError for another request under the key."""
+    is free. Raises IdempotencyConflictError for another request under the key, or, for a re-run with a new CSV, one
+    another user admitted."""
     await tenant_scope(s, tenant_id)
     existing = await _by_key(s, idempotency_key)
     if existing is None:
         return None
     fields = {"source": source, "workflow_id": workflow_id, "mode": mode, "input": rerun.digested()}
-    return (await _retry(keys, tenant_id, existing, fields)).request
+    owner = actor_id if rerun.csv is not None else None
+    return (await _retry(keys, tenant_id, existing, fields, owner)).request
 
 
 async def _by_key(s: AsyncSession, idempotency_key: str) -> RunRequest | None:
@@ -190,16 +256,25 @@ async def _winner(s: AsyncSession, idempotency_key: str) -> RunRequest:
     return winner
 
 
-async def _retry(keys: KeySource, tenant_id: uuid.UUID, existing: RunRequest, fields: dict[str, Any]) -> Admitted:
+async def _retry(
+    keys: KeySource, tenant_id: uuid.UUID, existing: RunRequest, fields: dict[str, Any], owner: uuid.UUID | None = None
+) -> Admitted:
+    """`existing` as an exact retry finds it; IdempotencyConflictError for another request under the key, or for a
+    CSV start another user made (`owner`, the caller, must be its actor, the upload's owner): no different answer
+    tells it apart from any other conflict."""
     if not await digests.matches(keys, str(tenant_id), existing.digest, existing.digest_key_version, **fields):
         raise IdempotencyConflictError("Another request was made under this idempotency key.")
+    if owner is not None and existing.actor_id != owner:
+        raise IdempotencyConflictError("Another request was made under this idempotency key.")
     return Admitted(existing, new=False)
 
 
 async def _frozen(
-    s: AsyncSession, keys: KeySource, tenant_id: uuid.UUID, request_id: uuid.UUID, fields: dict[str, Any]
-) -> tuple[uuid.UUID, uuid.UUID]:
-    """The mutable checks, then the trigger claimed and its envelope stored: the frozen version and the envelope."""
+    s: AsyncSession, keys: KeySource, tenant_id: uuid.UUID, request_id: uuid.UUID, fields: dict[str, Any],
+    actor_id: uuid.UUID | None, rerun: Rerun | None, csv: CsvStart | None,
+) -> _Frozen:  # fmt: skip
+    """The mutable checks, then the trigger claimed and its envelope stored (a CSV start's rows built and its upload
+    consumed first): the frozen version, the envelope and what the audit entry adds."""
     tenant = await s.get(Tenant, tenant_id, populate_existing=True)
     if tenant is None:
         raise WorkflowNotFoundError(str(fields["workflow_id"]))
@@ -237,18 +312,85 @@ async def _frozen(
     if blocked:
         reason = NODE_TYPE_RETIRED if any(e.kind == "node" for e in blocked) else CEL_PROFILE_RETIRED
         raise _Refused(reason, [f"{entry} has been retired." for entry in blocked], version.id)
-    if any(name in fields["input"] for name in RESERVED):  # only a CSV upload supplies them (§8.1)
+    settings = version.graph.get("settings") or {}
+    value: dict[str, Any] = fields["input"]
+    retained = rerun is not None and rerun.input is None and csv is None  # a re-run's own input, rebuilt
+    if not retained and any(name in value for name in RESERVED):  # only a CSV upload supplies them (§8.1)
         raise _Refused(INPUT_INVALID, [RESERVED_INPUT], version.id)
-    schema = trigger_schema(version.graph.get("settings") or {})
+    built: _Built | None = None
+    if csv is not None:
+        if not settings.get("csv"):
+            raise _Refused(CSV_NOT_DECLARED, ["This workflow takes no CSV."], version.id)
+        built = await _rows(s, keys, tenant_id, fields["workflow_id"], actor_id, csv, settings["csv"], version.id)
+        value = {**value, "rows": built.rows, "row_count": len(built.rows)}
     try:
         envelope = await claim_input(
-            s, keys, tenant_id=tenant_id, run_id=request_id, root_run_id=request_id, schema=schema,
-            value=fields["input"],
+            s, keys, tenant_id=tenant_id, run_id=request_id, root_run_id=request_id, schema=trigger_schema(settings),
+            value=value,
         )  # fmt: skip
     except InputRefusedError as e:
         raise _Refused(e.reason, e.reasons, version.id) from None
     envelope_id = await claims.write_envelope(s, ClaimCipher(keys), tenant_id, request_id=request_id, envelope=envelope)
-    return version.id, envelope_id
+    if built is None or csv is None:
+        return _Frozen(version.id, envelope_id, {})
+    record = {"mapping": dict(csv.mapping), "headers": built.headers, "skipped": [asdict(e) for e in built.errors],
+              "row_count": len(built.rows)}  # fmt: skip
+    await claims.write_csv_record(s, ClaimCipher(keys), tenant_id, request_id=request_id, record=record)
+    await s.execute(
+        update(CsvUpload)
+        .where(CsvUpload.id == csv.upload_id)
+        .values(staged=None, consumed_by=request_id, consumed_at=func.now())
+    )
+    skipped = len({e.row for e in built.errors})
+    return _Frozen(version.id, envelope_id, {"csv_digest": built.file_digest.hex(), "csv_rows": len(built.rows),
+                                             "csv_skipped": skipped})  # fmt: skip
+
+
+@dataclass(frozen=True)
+class _Built:
+    headers: list[str]
+    rows: list[dict[str, Any]]
+    errors: list[RowError]  # every rule a skipped row broke
+    file_digest: bytes
+
+
+def _row_message(e: RowError) -> str:
+    return f"The CSV's row {e.row}, column `{e.column}`: {e.code}." if e.column else f"The CSV's row {e.row}: {e.code}."
+
+
+async def _rows(
+    s: AsyncSession, keys: KeySource, tenant_id: uuid.UUID, workflow_id: uuid.UUID, actor_id: uuid.UUID | None,
+    csv: CsvStart, declared: dict[str, Any], version_id: uuid.UUID,
+) -> _Built:  # fmt: skip
+    """The upload's rows, built against the frozen version's declaration, its row locked until the caller commits:
+    its tenant, owner and workflow the caller's (else it's not found, whoever's it is), not consumed, not expired."""
+    query = (
+        select(CsvUpload, CsvUpload.expires_at > func.statement_timestamp())
+        .where(CsvUpload.id == csv.upload_id)
+        .with_for_update()
+        .execution_options(populate_existing=True)
+    )
+    found = (await s.execute(query)).one_or_none()
+    await _after_upload_locked()
+    upload, live = found if found is not None else (None, False)
+    if upload is None or (upload.tenant_id, upload.owner_id, upload.workflow_id) != (tenant_id, actor_id, workflow_id):
+        raise _Refused(UPLOAD_NOT_FOUND, ["There's no such upload of yours for this workflow."], version_id)
+    if upload.consumed_by is not None or upload.staged is None:
+        raise _Consumed
+    if not live:
+        raise _Refused(UPLOAD_EXPIRED, ["This upload has expired: upload the file again."], version_id)
+    plaintext = await ClaimCipher(keys, purpose=csv_uploads.PURPOSE).open(str(tenant_id), str(upload.id), upload.staged)
+    staged = json.loads(plaintext)
+    table = Table(staged["headers"], staged["rows"])
+    columns = declared["columns"]
+    problems = mapping_problems(columns, csv.mapping, table.headers)
+    if problems:
+        messages = [f"The mapping's column `{p['column']}`: {p['code']}." for p in problems[:_LISTED]]
+        raise _Refused(CSV_MAPPING_INVALID, messages, version_id)
+    rows, errors = build_rows(table, columns, csv.mapping)
+    if errors and not csv.skip_invalid:
+        raise _Refused(INPUT_INVALID, [_row_message(e) for e in errors[:_LISTED]], version_id)
+    return _Built(table.headers, rows, errors, upload.file_digest)
 
 
 async def _insert(
@@ -263,6 +405,7 @@ async def _insert(
     envelope_id: uuid.UUID | None,
     refused: _Refused | None = None,
     rerun: Rerun | None = None,
+    extra: dict[str, object] | None = None,
 ) -> Admitted:
     """The request row, queued or refused, and its audit entry; `new` False when another transaction won the key."""
     key_version, digest = await digests.digest(keys, str(tenant_id), **fields)  # the tenant's active key (§7.2)
@@ -301,6 +444,7 @@ async def _insert(
         details["reason"] = refused.reason
     if rerun is not None:
         details["rerun_of"] = str(rerun.of)
+    details.update(extra or {})
     await audit.record(s, tenant_id=tenant_id, actor_id=actor_id, action="run.request", target_type="run_request",
                        target_id=str(request_id), details=details)  # fmt: skip
     request = await s.get(RunRequest, request_id, populate_existing=True)
diff --git a/backend/src/dewpoint/apps/api/routes/run_requests.py b/backend/src/dewpoint/apps/api/routes/run_requests.py
index 3ba5ad3..25acd75 100644
--- a/backend/src/dewpoint/apps/api/routes/run_requests.py
+++ b/backend/src/dewpoint/apps/api/routes/run_requests.py
@@ -7,7 +7,7 @@ workflow's state. A cancel and a re-run name a request: its id is its run's, if
 
 import uuid
 from datetime import datetime
-from typing import Any, Literal
+from typing import Annotated, Any, Literal
 
 from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
 from pydantic import BaseModel, ConfigDict, Field
@@ -30,20 +30,37 @@ from dewpoint.engine.handles import NestingError, StoredClaim, resolve_value
 router = APIRouter(prefix="/api/v1", tags=["runs"])
 KEY_MAX = 255
 UNAVAILABLE = {admission.PRODUCTION_RUNS_DISABLED, admission.ENVIRONMENT_NOT_RECORDED, admission.NO_CURRENT_BUILD}
-INVALID = {INPUT_INVALID, SECRET_INDEX_LIMIT}
+INVALID = {INPUT_INVALID, SECRET_INDEX_LIMIT, admission.CSV_MAPPING_INVALID}
+NOT_FOUND = {admission.UPLOAD_NOT_FOUND}  # whoever's it is: an upload is its owner's only
+GONE = {admission.UPLOAD_EXPIRED}
 INPUT_NOT_RETAINED = "input_not_retained"
 
 
+class CsvIn(BaseModel):
+    """A staged upload (`POST …/csv-uploads`), the mapping from declared column names to its headers, and whether rows
+    that break a rule are skipped (and recorded) rather than refusing the start (engine 2b spec §8.1)."""
+
+    model_config = ConfigDict(extra="forbid")
+    upload_id: uuid.UUID
+    mapping: dict[Annotated[str, Field(max_length=63)], Annotated[str, Field(max_length=512)]] = Field(max_length=200)
+    skip_invalid: bool = False
+
+    def start(self) -> admission.CsvStart:
+        return admission.CsvStart(self.upload_id, dict(self.mapping), self.skip_invalid)
+
+
 class StartIn(BaseModel):
     model_config = ConfigDict(extra="forbid")
     input: dict[str, Any] = Field(default_factory=dict)
     mode: Literal["live", "simulate"] = "live"
+    csv: CsvIn | None = None  # a workflow that declares a CSV starts only with one (§8.1)
 
 
 class RerunIn(BaseModel):
     model_config = ConfigDict(extra="forbid")
     mode: Literal["live", "simulate"] | None = None  # the old request's when not given
     input: dict[str, Any] | None = None  # new input; else the original, rebuilt while it's retained
+    csv: CsvIn | None = None  # a new upload, with `input` (or none) beside it
 
 
 def key_unusable(e: Exception) -> HTTPException:
@@ -92,13 +109,17 @@ async def admit(
         admitted = await admission.admit_request(
             db, keys, tenant_id=ctx.tenant_id, workflow_id=workflow_id, source=source, actor_id=ctx.user.id,
             mode=body.mode, idempotency_key=key, input=body.input, rerun=rerun,
+            csv=body.csv.start() if body.csv is not None else None,
         )  # fmt: skip
     except admission.WorkflowNotFoundError:
         raise HTTPException(404, detail={"error": "not_found"}) from None
     except admission.IdempotencyConflictError:
         raise HTTPException(409, detail={"error": "idempotency_conflict"}) from None
     except admission.AdmissionRefusedError as e:
-        status = 503 if e.reason in UNAVAILABLE else 422 if e.reason in INVALID else 409
+        status = (
+            503 if e.reason in UNAVAILABLE else 422 if e.reason in INVALID else 404 if e.reason in NOT_FOUND
+            else 410 if e.reason in GONE else 409
+        )  # fmt: skip
         raise HTTPException(status, detail={"error": e.reason, "messages": e.messages}) from None
     except Exception as e:
         raise key_unusable(e) from None
@@ -186,11 +207,11 @@ async def rerun(
     if named is None:
         raise HTTPException(404, detail={"error": "not_found"})
     workflow_id, mode = named.workflow_id, given.mode or named.mode
-    again = admission.Rerun(request_id, given.input)
+    again = admission.Rerun(request_id, given.input, given.csv.start() if given.csv is not None else None)
     try:
         existing = await admission.admitted_under(
             db, keys, tenant_id=ctx.tenant_id, idempotency_key=key, source="rerun", workflow_id=workflow_id,
-            mode=mode, rerun=again,
+            mode=mode, rerun=again, actor_id=ctx.user.id,
         )  # fmt: skip
     except admission.IdempotencyConflictError:
         raise HTTPException(409, detail={"error": "idempotency_conflict"}) from None
@@ -198,6 +219,9 @@ async def rerun(
         raise key_unusable(e) from None
     if existing is not None:
         return request_body(existing)
+    if given.csv is not None:
+        start = StartIn(input=given.input or {}, mode=mode, csv=given.csv)
+        return request_body(await admit(db, keys, ctx, workflow_id, "rerun", start, key, rerun=again))
     if given.input is not None:
         value = given.input
     elif old is None:
diff --git a/backend/src/dewpoint/apps/api/routes/runs.py b/backend/src/dewpoint/apps/api/routes/runs.py
index d2aff70..3624e85 100644
--- a/backend/src/dewpoint/apps/api/routes/runs.py
+++ b/backend/src/dewpoint/apps/api/routes/runs.py
@@ -10,7 +10,11 @@ from datetime import datetime
 from fastapi import APIRouter, Depends, HTTPException, Query
 from sqlalchemy.ext.asyncio import AsyncSession
 
+from dewpoint.apps.api.routes.run_requests import get_keys, key_unusable
 from dewpoint.core.authz.permissions import P
+from dewpoint.core.claims import service as claims
+from dewpoint.core.claims.cipher import ClaimCipher
+from dewpoint.core.crypto.keys import KeySource
 from dewpoint.core.http import TenantContext, get_db, require
 from dewpoint.core.models.requests import RunRequest
 from dewpoint.core.models.runs import Run, RunStep
@@ -130,10 +134,19 @@ async def get_run(
     run_id: uuid.UUID,
     ctx: TenantContext = Depends(require(P.RUN_VIEW)),
     db: AsyncSession = Depends(get_db, scope="function"),
+    keys: KeySource = Depends(get_keys),
 ) -> dict[str, object]:
+    """A run with its steps and sub-runs, or a request that hasn't started as itself; with its CSV record (engine 2b
+    spec §8.1), when it took a CSV: the mapping, the file's headers, the row count and the skipped rows."""
     request = await db.get(RunRequest, run_id)  # row-level security: the caller's tenant's only
+    csv = None
+    if request is not None:
+        try:
+            csv = await claims.read_csv_record(db, ClaimCipher(keys), ctx.tenant_id, request_id=request.id)
+        except Exception as e:
+            raise key_unusable(e) from None
     if request is not None and request.status != "started":
-        return {**_unstarted(request), "steps": [], "children": []}
+        return {**_unstarted(request), "steps": [], "children": [], "csv": csv}
     run = await service.get_run(db, run_id)
     if run is None or run.tenant_id != ctx.tenant_id:
         raise HTTPException(404, detail={"error": "not_found"})
@@ -142,4 +155,5 @@ async def get_run(
         "request": _request(request),
         "steps": [_step(r) for r in await service.run_steps(db, run.id)],
         "children": [_child(c) for c in await service.children(db, run.id)],
+        "csv": csv,
     }
diff --git a/backend/src/dewpoint/core/claims/service.py b/backend/src/dewpoint/core/claims/service.py
index d81281e..d6db2b1 100644
--- a/backend/src/dewpoint/core/claims/service.py
+++ b/backend/src/dewpoint/core/claims/service.py
@@ -219,6 +219,39 @@ async def read_envelope(s: AsyncSession, cipher: ClaimCipher, tenant_id: uuid.UU
         raise EnvelopeUnreadableError("A trigger envelope that isn't JSON.") from None
 
 
+async def write_csv_record(
+    s: AsyncSession, cipher: ClaimCipher, tenant_id: uuid.UUID, *, request_id: uuid.UUID, record: dict[str, Any]
+) -> None:
+    """A CSV start's record (§8.1): its mapping, the file's header names and its skipped rows, encrypted as a claim is
+    and owned by the request. Like the envelope it's never a claim: no claim read or grant serves it."""
+    record_id = uuid.uuid4()
+    row = {
+        "id": record_id,
+        "tenant_id": tenant_id,
+        "owner_run_id": request_id,
+        "root_run_id": request_id,
+        "sensitive_pointers": [],
+        "ciphertext": await cipher.seal(str(tenant_id), str(record_id), _plain(record)),
+        "role": "csv",
+        "pointer": None,
+    }
+    await s.execute(insert(InputClaim).values(row))
+
+
+async def read_csv_record(
+    s: AsyncSession, cipher: ClaimCipher, tenant_id: uuid.UUID, *, request_id: uuid.UUID
+) -> dict[str, Any] | None:
+    """A request's CSV record, in the caller's tenant; None for a request that took no CSV, or whose record retention
+    removed."""
+    row = (
+        await s.execute(select(InputClaim).where(InputClaim.owner_run_id == request_id, InputClaim.role == "csv"))
+    ).scalar_one_or_none()
+    if row is None:
+        return None
+    record: dict[str, Any] = json.loads(await cipher.open(str(tenant_id), str(row.id), row.ciphertext))
+    return record
+
+
 async def read_request_claim(
     s: AsyncSession, cipher: ClaimCipher, tenant_id: uuid.UUID, *, request_id: uuid.UUID, claim_id: uuid.UUID
 ) -> Stored:
diff --git a/backend/tests/apps/api/test_csv_starts_api.py b/backend/tests/apps/api/test_csv_starts_api.py
new file mode 100644
index 0000000..5cb303e
--- /dev/null
+++ b/backend/tests/apps/api/test_csv_starts_api.py
@@ -0,0 +1,116 @@
+# SPDX-License-Identifier: Apache-2.0
+"""A CSV start through the API (engine 2b spec §7.7, §8.1): `POST …/runs` with `csv: {upload_id, mapping,
+skip_invalid}`, and a re-run with a new upload. Its refusals answer with their codes: 404 `upload_not_found`, 410
+`upload_expired`, 409 `upload_consumed`, 422 `csv_mapping_invalid`. A run's details show its CSV record to `run.view`:
+the mapping, the file's headers, the row count and the skipped rows' numbers and codes."""
+
+import uuid
+from typing import Any
+
+import pytest
+from sqlalchemy import text
+
+from tests.apps.api.helpers import member_client
+from tests.apps.api.test_csv_uploads_api import CSV_TYPE, uploads_url
+from tests.apps.api.test_run_requests_api import as_role, runs_url
+from tests.apps.test_admission import KEYS, TOKEN, current, published
+from tests.apps.test_admission_csv import GRAPH, MAPPING
+
+pytestmark = pytest.mark.usefixtures("development_deployment")
+FILE = b"Site,VLAN,PSK\nparis,10,s3cret-psk-1\nlyon,x,\n"
+INPUT = {"token": TOKEN, "site": "a"}
+
+
+@pytest.fixture
+def keyed_app(app: Any) -> Any:
+    app.state.keys = KEYS
+    return app
+
+
+@pytest.fixture
+async def csv_ready(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings):
+    ctx, wf = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings, GRAPH)
+    await current(dispatch_sessionmaker)
+    return ctx, wf
+
+
+async def uploaded(client: Any, ctx: Any, wf: uuid.UUID, data: bytes = FILE) -> str:
+    answer = await client.post(uploads_url(ctx, wf), content=data, headers=CSV_TYPE)
+    assert answer.status_code == 201, answer.text
+    return str(answer.json()["upload_id"])
+
+
+def csv_body(upload: str, mapping: dict[str, str] = MAPPING, skip: bool = True) -> dict[str, Any]:
+    return {"input": INPUT, "mode": "live", "csv": {"upload_id": upload, "mapping": mapping, "skip_invalid": skip}}
+
+
+async def test_a_csv_start_is_admitted_and_its_run_shows_its_record(
+    keyed_app, csv_ready, owner_sessionmaker, api_settings
+) -> None:
+    ctx, wf = csv_ready
+    client = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx)
+    upload = await uploaded(client, ctx, wf)
+    answer = await client.post(runs_url(ctx, wf), json=csv_body(upload), headers={"Idempotency-Key": "c1"})
+    assert answer.status_code == 202, answer.text
+    request_id = answer.json()["id"]
+    again = await client.post(runs_url(ctx, wf), json=csv_body(upload), headers={"Idempotency-Key": "c1"})
+    assert (again.status_code, again.json()["id"]) == (202, request_id)
+    viewer = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "viewer")
+    details = (await viewer.get(f"/api/v1/t/{ctx.tenant_id}/runs/{request_id}")).json()
+    assert details["csv"] == {
+        "mapping": MAPPING,
+        "headers": ["Site", "VLAN", "PSK"],
+        "row_count": 1,
+        "skipped": [{"row": 2, "column": "vlan", "code": "not_integer"}],
+    }
+    assert "s3cret" not in str(details)
+
+
+async def test_another_user_replaying_the_start_gets_a_conflict(
+    keyed_app, csv_ready, owner_sessionmaker, api_settings
+) -> None:
+    ctx, wf = csv_ready
+    client = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx)
+    upload = await uploaded(client, ctx, wf)
+    assert (await client.post(runs_url(ctx, wf), json=csv_body(upload), headers={"Idempotency-Key": "c1"})
+            ).status_code == 202  # fmt: skip
+    other, _ = await member_client(keyed_app, owner_sessionmaker, api_settings, ctx.tenant_id, "operator")
+    answer = await other.post(runs_url(ctx, wf), json=csv_body(upload), headers={"Idempotency-Key": "c1"})
+    assert (answer.status_code, answer.json()) == (409, {"error": "idempotency_conflict"})
+
+
+async def test_each_refusal_answers_with_its_code(keyed_app, csv_ready, owner_sessionmaker, api_settings) -> None:
+    ctx, wf = csv_ready
+    client = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx)
+
+    async def started(body: dict[str, Any], key: str) -> tuple[int, str]:
+        answer = await client.post(runs_url(ctx, wf), json=body, headers={"Idempotency-Key": key})
+        return answer.status_code, answer.json().get("error")
+
+    assert await started(csv_body(str(uuid.uuid4())), "u") == (404, "upload_not_found")
+    upload = await uploaded(client, ctx, wf)
+    assert await started(csv_body(upload, {"vlan": "VLAN"}), "m") == (422, "csv_mapping_invalid")
+    assert await started(csv_body(upload, skip=False), "r") == (422, "input_invalid")
+    assert await started(csv_body(upload), "c1") == (202, None)
+    assert await started(csv_body(upload), "c2") == (409, "upload_consumed")
+    late = await uploaded(client, ctx, wf)
+    async with owner_sessionmaker() as s, s.begin():
+        await s.execute(text("update csv_uploads set created_at = now() - interval '2 hours', "
+                             "expires_at = now() - interval '1 hour' where id = :i"), {"i": late})  # fmt: skip
+    assert await started(csv_body(late), "e") == (410, "upload_expired")
+
+
+async def test_a_rerun_takes_a_new_upload(keyed_app, csv_ready, owner_sessionmaker, api_settings) -> None:
+    ctx, wf = csv_ready
+    client = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx)
+    first = await client.post(runs_url(ctx, wf), json=csv_body(await uploaded(client, ctx, wf)),
+                              headers={"Idempotency-Key": "c1"})  # fmt: skip
+    upload = await uploaded(client, ctx, wf, b"Site\nnice\n")
+    body = {"input": INPUT, "csv": {"upload_id": upload, "mapping": {"site": "Site"}}}
+    rerun_url = f"/api/v1/t/{ctx.tenant_id}/runs/{first.json()['id']}/rerun"
+    answer = await client.post(rerun_url, json=body, headers={"Idempotency-Key": "r1"})
+    assert (answer.status_code, answer.json()["source"]) == (202, "rerun"), answer.text
+    details = (await client.get(f"/api/v1/t/{ctx.tenant_id}/runs/{answer.json()['id']}")).json()
+    assert details["csv"]["row_count"] == 1
+    again = await client.post(rerun_url, json=body, headers={"Idempotency-Key": "r1"})
+    assert (again.status_code, again.json()["id"]) == (202, answer.json()["id"])  # found by its key, upload consumed
diff --git a/backend/tests/apps/api/test_run_requests_api.py b/backend/tests/apps/api/test_run_requests_api.py
index 51b3b45..4263d3c 100644
--- a/backend/tests/apps/api/test_run_requests_api.py
+++ b/backend/tests/apps/api/test_run_requests_api.py
@@ -104,11 +104,11 @@ async def test_an_input_that_doesnt_match_its_schema_is_422_with_its_places_neve
 
 
 async def test_a_body_with_unknown_fields_is_refused(keyed_app, ready, owner_sessionmaker, api_settings) -> None:
-    """CSV starts are 2b-3's: a `csv` field isn't accepted yet."""
     ctx, wf = ready
     client = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx)
-    answer = await client.post(runs_url(ctx, wf), json={**BODY, "csv": "u1"}, headers={"Idempotency-Key": "k1"})
-    assert (answer.status_code, answer.json()["error"]) == (422, "invalid")
+    for body in ({**BODY, "rows": []}, {**BODY, "csv": "u1"}, {**BODY, "csv": {"upload_id": "u1", "mapping": {}}}):
+        answer = await client.post(runs_url(ctx, wf), json=body, headers={"Idempotency-Key": "k1"})
+        assert (answer.status_code, answer.json()["error"]) == (422, "invalid")
 
 
 async def test_production_runs_off_answers_503(keyed_app, ready, owner_sessionmaker, api_settings) -> None:
diff --git a/backend/tests/apps/test_admission_csv.py b/backend/tests/apps/test_admission_csv.py
new file mode 100644
index 0000000..676b279
--- /dev/null
+++ b/backend/tests/apps/test_admission_csv.py
@@ -0,0 +1,281 @@
+# SPDX-License-Identifier: Apache-2.0
+"""A CSV start (engine 2b spec §8.1; the owner's rulings 5 and 7–8, and the M1 corrections): admission builds the
+trigger's rows from a staged upload and consumes it in the same transaction.
+
+- The key first: the digest covers what was asked (the input, the upload, the mapping, `skip_invalid`), so an exact
+  retry is recognized without the rows, after the upload is gone, and returned only to the upload's owner.
+- Then the upload, locked and checked (its tenant, its owner, its workflow, not expired, not consumed): concurrent
+  starts yield one consumer, and a start that finds it consumed looks its own key up again.
+- The rows are built against the frozen version's declaration, the sensitive cells claimed with taint, the upload's
+  cells cleared, and the mapping, headers and skipped rows kept in a `run_inputs` row of the role `csv`."""
+
+import asyncio
+import uuid
+from typing import Any
+
+import pytest
+from sqlalchemy import text
+
+from dewpoint.apps import admission, csv_uploads
+from dewpoint.apps.inputs import RESERVED_INPUT
+from dewpoint.core.claims import service as claims
+from dewpoint.core.claims.cipher import ClaimCipher
+from dewpoint.core.db import tenant_scope
+from dewpoint.engine.graph.csv import MAX_BYTES
+from dewpoint.engine.handles import StoredClaim, resolve_value
+from tests.apps.api.helpers import member_client
+from tests.apps.test_admission import KEYS, SCHEMA, TOKEN, admit, count, current, published
+
+pytestmark = pytest.mark.usefixtures("development_deployment")
+CSV = {
+    "columns": [
+        {"header": "Site", "name": "site", "type": "string", "required": True},
+        {"header": "VLAN", "name": "vlan", "type": "integer", "default": 1},
+        {"header": "PSK", "name": "psk", "type": "string", "sensitive": True},
+    ],
+    "max_rows": 10_000,
+    "max_bytes": MAX_BYTES,
+}
+GRAPH = {"graph_format": 1, "nodes": [{"id": str(uuid.uuid4()), "key": "a", "type": "testkit.echo@1",
+         "config": {"value": 1}}], "edges": [], "settings": {"input_schema": SCHEMA, "csv": CSV}}  # fmt: skip
+FILE = b"Site,VLAN,PSK\nparis,10,s3cret-psk-1\nlyon,,\n"
+MAPPING = {"site": "Site", "vlan": "VLAN", "psk": "PSK"}
+ROWS = [{"site": "paris", "vlan": 10, "psk": "s3cret-psk-1"}, {"site": "lyon", "vlan": 1}]
+
+
+@pytest.fixture
+async def csv_ready(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings):
+    ctx, wf = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings, GRAPH)
+    await current(dispatch_sessionmaker)
+    return ctx, wf
+
+
+async def staged(api: Any, ctx: Any, wf: uuid.UUID, data: bytes = FILE, owner: uuid.UUID | None = None) -> uuid.UUID:
+    async with api() as s, s.begin():
+        await tenant_scope(s, ctx.tenant_id)
+        body = await csv_uploads.stage(s, KEYS, tenant_id=ctx.tenant_id, owner_id=owner or ctx.user.id,
+                                       workflow_id=wf, csv=CSV, data=data)  # fmt: skip
+    return uuid.UUID(body["upload_id"])
+
+
+def start(upload: uuid.UUID, mapping: dict[str, str] = MAPPING, skip_invalid: bool = False) -> admission.CsvStart:
+    return admission.CsvStart(upload, mapping, skip_invalid)
+
+
+async def full_input(dispatch: Any, ctx: Any, request_id: uuid.UUID) -> Any:
+    async with dispatch() as s, s.begin():
+        await tenant_scope(s, ctx.tenant_id)
+        cipher = ClaimCipher(KEYS)
+
+        async def fetch(claim_id: str) -> StoredClaim:
+            got = await claims.read_request_claim(s, cipher, ctx.tenant_id, request_id=request_id,
+                                                  claim_id=uuid.UUID(claim_id))  # fmt: skip
+            return StoredClaim(got.value, got.sensitive_pointers)
+
+        envelope = await claims.read_envelope(s, cipher, ctx.tenant_id, request_id=request_id)
+        return (await resolve_value(envelope, fetch)).value
+
+
+async def upload_row(owner: Any, upload: uuid.UUID) -> Any:
+    async with owner() as s:
+        return (await s.execute(text("select * from csv_uploads where id = :i"), {"i": upload})).mappings().one()
+
+
+async def record(api: Any, ctx: Any, request_id: uuid.UUID) -> Any:
+    async with api() as s, s.begin():
+        await tenant_scope(s, ctx.tenant_id)
+        return await claims.read_csv_record(s, ClaimCipher(KEYS), ctx.tenant_id, request_id=request_id)
+
+
+async def test_a_csv_start_freezes_its_rows_and_consumes_its_upload(
+    csv_ready, owner_sessionmaker, api_sessionmaker, dispatch_sessionmaker
+) -> None:
+    ctx, wf = csv_ready
+    upload = await staged(api_sessionmaker, ctx, wf)
+    admitted = await admit(api_sessionmaker, ctx, wf, csv=start(upload))
+    r = admitted.request
+    assert admitted.new and r.status == "queued"
+    trigger = await full_input(dispatch_sessionmaker, ctx, r.id)
+    assert trigger == {"token": TOKEN, "site": "a", "rows": ROWS, "row_count": 2}
+    async with owner_sessionmaker() as s:
+        tainted_claims = text("select count(*) from run_inputs where owner_run_id = :r and role = 'claim' "
+                              "and sensitive_pointers::text = '[\"\"]'")  # fmt: skip
+        tainted = (await s.execute(tainted_claims, {"r": r.id})).scalar_one()
+        audit = (await s.execute(text("select details from audit_log where action = 'run.request'"))).scalar_one()
+    assert tainted == 2  # the token and the one PSK cell, each claimed with taint
+    row = await upload_row(owner_sessionmaker, upload)
+    assert (row["staged"], row["consumed_by"]) == (None, r.id) and row["consumed_at"] is not None
+    assert await record(api_sessionmaker, ctx, r.id) == {
+        "mapping": MAPPING, "headers": ["Site", "VLAN", "PSK"], "skipped": [], "row_count": 2,
+    }  # fmt: skip
+    assert (audit["csv_digest"], audit["csv_rows"], audit["csv_skipped"]) == (row["file_digest"].hex(), 2, 0)
+
+
+async def test_an_exact_retry_returns_its_request_after_the_upload_was_consumed(csv_ready, api_sessionmaker) -> None:
+    ctx, wf = csv_ready
+    upload = await staged(api_sessionmaker, ctx, wf)
+    first = await admit(api_sessionmaker, ctx, wf, csv=start(upload))
+    again = await admit(api_sessionmaker, ctx, wf, csv=start(upload))
+    assert (again.new, again.request.id) == (False, first.request.id)
+    with pytest.raises(admission.IdempotencyConflictError):
+        await admit(api_sessionmaker, ctx, wf, csv=start(upload, skip_invalid=True))  # another request, same key
+
+
+async def test_an_exact_retry_is_returned_only_to_the_uploads_owner(
+    csv_ready, owner_sessionmaker, api_sessionmaker, api_settings, app
+) -> None:
+    """The owner's correction: another user of the tenant who knows the key and the upload's id gets a conflict."""
+    ctx, wf = csv_ready
+    upload = await staged(api_sessionmaker, ctx, wf)
+    await admit(api_sessionmaker, ctx, wf, csv=start(upload))
+    _, other = await member_client(app, owner_sessionmaker, api_settings, ctx.tenant_id, "operator")
+    async with api_sessionmaker() as s, s.begin():
+        with pytest.raises(admission.IdempotencyConflictError):
+            await admission.admit_request(s, KEYS, tenant_id=ctx.tenant_id, workflow_id=wf, source="manual",
+                                          actor_id=other, mode="live", idempotency_key="k1",
+                                          input={"token": TOKEN, "site": "a"}, csv=start(upload))  # fmt: skip
+
+
+async def test_another_start_with_a_consumed_upload_is_refused(csv_ready, api_sessionmaker) -> None:
+    ctx, wf = csv_ready
+    upload = await staged(api_sessionmaker, ctx, wf)
+    await admit(api_sessionmaker, ctx, wf, csv=start(upload))
+    with pytest.raises(admission.AdmissionRefusedError) as refused:
+        await admit(api_sessionmaker, ctx, wf, key="k2", csv=start(upload))
+    assert refused.value.reason == "upload_consumed"
+
+
+async def lock_waiters(owner: Any) -> int:
+    async with owner() as s:
+        return int((await s.execute(text("select count(*) from pg_stat_activity where wait_event_type = 'Lock'"))
+                    ).scalar_one())  # fmt: skip
+
+
+@pytest.mark.parametrize("same_key", [True, False])
+async def test_concurrent_starts_with_one_upload_yield_one_consumer(
+    csv_ready, owner_sessionmaker, api_sessionmaker, monkeypatch, same_key
+) -> None:
+    """The second start looks its key up before the first commits, then waits on the upload's row lock. Once the first
+    commits, it finds the upload consumed and looks its key up again: under the same key, the first's request; under
+    another, `upload_consumed`."""
+    ctx, wf = csv_ready
+    upload = await staged(api_sessionmaker, ctx, wf)
+    second: list[asyncio.Task[Any]] = []
+
+    async def race() -> None:
+        if second:
+            return
+        second.append(asyncio.create_task(admit(api_sessionmaker, ctx, wf, key="k1" if same_key else "k2",
+                                                csv=start(upload))))  # fmt: skip
+        for _ in range(200):  # until it waits on this transaction's row lock
+            if await lock_waiters(owner_sessionmaker):
+                return
+            await asyncio.sleep(0.01)
+        raise AssertionError("the second start never waited on the upload")
+
+    monkeypatch.setattr(admission, "_after_upload_locked", race)
+    first = (await admit(api_sessionmaker, ctx, wf, csv=start(upload))).request
+    if same_key:
+        again = await second[0]
+        assert (again.new, again.request.id) == (False, first.id)
+    else:
+        with pytest.raises(admission.AdmissionRefusedError) as refused:
+            await second[0]
+        assert refused.value.reason == "upload_consumed"
+    assert await count(owner_sessionmaker, "run_requests") == 1
+
+
+async def test_an_upload_of_another_user_or_workflow_is_never_found(
+    csv_ready, owner_sessionmaker, api_sessionmaker, api_settings, app
+) -> None:
+    ctx, wf = csv_ready
+    _, other = await member_client(app, owner_sessionmaker, api_settings, ctx.tenant_id, "operator")
+    theirs = await staged(api_sessionmaker, ctx, wf, owner=other)
+    elsewhere = uuid.uuid4()
+    async with owner_sessionmaker() as s, s.begin():
+        await s.execute(text("insert into workflows (id, tenant_id, name, enabled, draft) values (:w, :t, 'X', true, "
+                             "'{}')"), {"w": elsewhere, "t": ctx.tenant_id})  # fmt: skip
+    for_another = await staged(api_sessionmaker, ctx, elsewhere)
+    for upload in (theirs, for_another, uuid.uuid4()):
+        with pytest.raises(admission.AdmissionRefusedError) as refused:
+            await admit(api_sessionmaker, ctx, wf, key=str(upload), csv=start(upload))
+        assert refused.value.reason == "upload_not_found"
+    assert (await upload_row(owner_sessionmaker, theirs))["consumed_by"] is None
+
+
+async def test_an_expired_upload_is_refused(csv_ready, owner_sessionmaker, api_sessionmaker) -> None:
+    ctx, wf = csv_ready
+    upload = await staged(api_sessionmaker, ctx, wf)
+    async with owner_sessionmaker() as s, s.begin():
+        await s.execute(text("update csv_uploads set created_at = now() - interval '2 hours', "
+                             "expires_at = now() - interval '1 hour' where id = :i"), {"i": upload})  # fmt: skip
+    with pytest.raises(admission.AdmissionRefusedError) as refused:
+        await admit(api_sessionmaker, ctx, wf, csv=start(upload))
+    assert refused.value.reason == "upload_expired"
+
+
+async def test_a_mapping_the_frozen_version_refuses_is_refused(csv_ready, api_sessionmaker) -> None:
+    ctx, wf = csv_ready
+    upload = await staged(api_sessionmaker, ctx, wf)
+    with pytest.raises(admission.AdmissionRefusedError) as refused:
+        await admit(api_sessionmaker, ctx, wf, csv=start(upload, {"vlan": "VLAN"}))
+    assert (refused.value.reason, refused.value.messages) == (
+        "csv_mapping_invalid", ["The mapping's column `site`: required_unmapped."],
+    )  # fmt: skip
+
+
+async def test_a_row_that_breaks_a_rule_refuses_the_start_unless_invalid_rows_are_skipped(
+    csv_ready, owner_sessionmaker, api_sessionmaker, dispatch_sessionmaker
+) -> None:
+    ctx, wf = csv_ready
+    data = b"Site,VLAN,PSK\nparis,ten,k3y-value-1\nlyon,2,\n"
+    upload = await staged(api_sessionmaker, ctx, wf, data)
+    with pytest.raises(admission.AdmissionRefusedError) as refused:
+        await admit(api_sessionmaker, ctx, wf, csv=start(upload))
+    assert (refused.value.reason, refused.value.messages) == (
+        "input_invalid", ["The CSV's row 1, column `vlan`: not_integer."],
+    )  # fmt: skip
+    assert not any("ten" in m or "k3y" in m for m in refused.value.messages)
+    assert (await upload_row(owner_sessionmaker, upload))["consumed_by"] is None  # nothing commits
+    r = (await admit(api_sessionmaker, ctx, wf, key="k2", csv=start(upload, skip_invalid=True))).request
+    assert (await full_input(dispatch_sessionmaker, ctx, r.id))["rows"] == [{"site": "lyon", "vlan": 2}]
+    skipped = (await record(api_sessionmaker, ctx, r.id))["skipped"]
+    assert skipped == [{"row": 1, "column": "vlan", "code": "not_integer"}]
+
+
+async def test_a_csv_start_still_refuses_rows_in_its_input(csv_ready, api_sessionmaker) -> None:
+    ctx, wf = csv_ready
+    upload = await staged(api_sessionmaker, ctx, wf)
+    with pytest.raises(admission.AdmissionRefusedError) as refused:
+        await admit(api_sessionmaker, ctx, wf, input={"token": TOKEN, "rows": []}, csv=start(upload))
+    assert refused.value.messages == [RESERVED_INPUT]
+
+
+async def test_a_workflow_without_a_csv_takes_no_csv_start(ready_plain, api_sessionmaker) -> None:
+    ctx, wf = ready_plain
+    with pytest.raises(admission.AdmissionRefusedError) as refused:
+        await admit(api_sessionmaker, ctx, wf, csv=start(uuid.uuid4()))
+    assert refused.value.reason == "csv_not_declared"
+
+
+@pytest.fixture
+async def ready_plain(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings):
+    ctx, wf = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings)
+    await current(dispatch_sessionmaker)
+    return ctx, wf
+
+
+async def test_a_rerun_takes_the_original_rows_or_a_new_csv(csv_ready, api_sessionmaker, dispatch_sessionmaker) -> None:
+    """The original input's rows come back from the retained claims, which admission accepts as only a re-run's own
+    input; a re-run may take a new upload instead."""
+    ctx, wf = csv_ready
+    first = (await admit(api_sessionmaker, ctx, wf, csv=start(await staged(api_sessionmaker, ctx, wf)))).request
+    original = await full_input(dispatch_sessionmaker, ctx, first.id)
+    again = await admit(api_sessionmaker, ctx, wf, key="r1", source="rerun", input=original,
+                        rerun=admission.Rerun(first.id))  # fmt: skip
+    assert (await full_input(dispatch_sessionmaker, ctx, again.request.id))["rows"] == ROWS
+    upload = await staged(api_sessionmaker, ctx, wf, b"Site\nnice\n")
+    fresh = await admit(api_sessionmaker, ctx, wf, key="r2", source="rerun",
+                        rerun=admission.Rerun(first.id, {"token": TOKEN}, start(upload, {"site": "Site"})),
+                        input={"token": TOKEN}, csv=start(upload, {"site": "Site"}))  # fmt: skip
+    assert (await full_input(dispatch_sessionmaker, ctx, fresh.request.id))["rows"] == [{"site": "nice", "vlan": 1}]
diff --git a/backend/tests/core/requests/test_csv_uploads_schema.py b/backend/tests/core/requests/test_csv_uploads_schema.py
index 8dc4f9d..34759b2 100644
--- a/backend/tests/core/requests/test_csv_uploads_schema.py
+++ b/backend/tests/core/requests/test_csv_uploads_schema.py
@@ -78,3 +78,29 @@ async def test_an_upload_is_staged_until_a_start_consumes_it(api_sessionmaker, o
         async with api_sessionmaker() as s, s.begin():
             await tenant_scope(s, tenant)
             await s.execute(text(f"update csv_uploads set {change} where id = :i"), {"i": upload_id})
+
+
+async def test_a_csv_record_is_never_a_claim(api_sessionmaker, owner_sessionmaker, worker_sessionmaker) -> None:
+    """A CSV start's record (§8.1, §7.1) sits in `run_inputs` under the role `csv`: no pointer, one per request, and
+    neither a claim read nor a grant serves it, as for an envelope."""
+    from dewpoint.core.claims import service as claims
+    from dewpoint.core.claims.cipher import ClaimCipher
+    from tests.core.requests.test_schema import claim
+    from tests.support.keys import FixtureKeys
+
+    tenant, _ = await upload(api_sessionmaker, owner_sessionmaker)
+    request = uuid.uuid4()
+    async with api_sessionmaker() as s, s.begin():
+        await tenant_scope(s, tenant)
+        record = await claim(s, tenant, request, role="csv", pointer=None)
+    async with worker_sessionmaker() as s, s.begin():
+        await tenant_scope(s, tenant)
+        with pytest.raises(claims.ClaimUnavailableError):
+            await claims.fetch(s, ClaimCipher(FixtureKeys()), tenant, run_id=request, claim_id=record)
+        with pytest.raises(claims.ClaimUnavailableError):
+            await claims.grant(s, tenant, granted_by=request, to=uuid.uuid4(), claim_ids=[record], root_run_id=request)
+    for pointer in (None, ""):  # a second record, then one with a pointer
+        with pytest.raises(IntegrityError):
+            async with api_sessionmaker() as s, s.begin():
+                await tenant_scope(s, tenant)
+                await claim(s, tenant, request, role="csv", pointer=pointer)
```

### Task 9: Bounded error detail, the byte cap governs a field's length, the upload staged as its bytes (the owner's milestone-2 review)

**Commit:** `fbc50ff` (prototype `proto/2b3a-v2`); the replay's tree was identical: yes.

**Modify:** `backend/src/dewpoint/apps/admission.py`, `backend/src/dewpoint/apps/csv_input.py`, `backend/src/dewpoint/apps/csv_uploads.py`, `backend/tests/apps/api/test_csv_starts_api.py`, `backend/tests/apps/api/test_csv_uploads_api.py`, `backend/tests/apps/test_admission_csv.py`, `backend/tests/apps/test_csv_input.py`

**What it does:**

From the owner's M2 review, refining tasks 4, 5 and 7:
- 200 required columns and 10,000 records of empty cells fit in a 2 MB file and break 2
  million rules, which the builder held as 2 million errors (a 200 MB peak), the upload's
  answer before listing 100, and a skip_invalid start's record whole. The builder now
  keeps the first 100 errors in detail, each skipped record's number and first code, and
  an exact count (a 1 MB peak at the limits): the answer lists the 100 and the count, and
  the record keeps every skipped row's number and code, the 100 in detail and the count,
  growing with the records, never with records times columns. Regressions at the limits.
- Python's csv module refused a field past 131,072 characters, so a valid one-row file
  with a 140,000-character cell was `csv_malformed` under the 5 MiB cap. Its process-wide
  limit is raised to the platform's byte cap (nothing else in the process reads CSV).
- Found alongside: the upload was staged as parsed JSON, several times the file's size (an
  empty cell is `""`). It's now staged as the file's own sealed bytes, bounded by its cap,
  and a start reads it again under the version it freezes, so a version published since
  with a lower cap refuses a file the earlier one took.

- [ ] **Step 1: its tests alone, before its code.** Run: `uv run pytest -n 8 tests/apps/api/test_csv_starts_api.py tests/apps/api/test_csv_uploads_api.py tests/apps/test_admission_csv.py tests/apps/test_csv_input.py`. Replay result (exit 1), shortened:

```
<replay>/backend/tests/apps/api/test_csv_uploads_api.py:194: assert 8021546 <= (2000890 + 64)
[gw1] darwin -- Python 3.14.7 <venv>/bin/python
E   KeyError: 'error_count'
<replay>/backend/tests/apps/test_admission_csv.py:313: KeyError: 'error_count'
=========================== short test summary info ============================
FAILED tests/apps/api/test_csv_starts_api.py::test_a_csv_start_is_admitted_and_its_run_shows_its_record
FAILED tests/apps/api/test_csv_uploads_api.py::test_a_cell_longer_than_pythons_default_field_limit_uploads
FAILED tests/apps/test_admission_csv.py::test_a_csv_start_freezes_its_rows_and_consumes_its_upload
FAILED tests/apps/test_admission_csv.py::test_a_row_that_breaks_a_rule_refuses_the_start_unless_invalid_rows_are_skipped
FAILED tests/apps/test_admission_csv.py::test_the_frozen_versions_caps_govern_the_start
FAILED tests/apps/api/test_csv_uploads_api.py::test_an_upload_at_the_permitted_limits_lists_100_errors_and_counts_them_all
FAILED tests/apps/test_admission_csv.py::test_a_skip_invalid_start_at_the_permitted_limits_keeps_a_bounded_record
ERROR tests/apps/test_csv_input.py - ImportError while importing test module ...
7 failed, 25 passed, 1 error in 23.14s
```

- [ ] **Step 2: its code, then the same tests.** Replay result (exit 0), shortened:

```
......................................................                   [100%]
54 passed in 14.94s
```

- [ ] **Step 3: commit.** `git cherry-pick --no-commit fbc50ff && git commit -C fbc50ff`

The diff:

```diff
diff --git a/backend/src/dewpoint/apps/admission.py b/backend/src/dewpoint/apps/admission.py
index 0e70fa8..ee822a5 100644
--- a/backend/src/dewpoint/apps/admission.py
+++ b/backend/src/dewpoint/apps/admission.py
@@ -24,7 +24,6 @@ which a concurrent start under it has taken), builds its rows against the frozen
 with the rest of the trigger, keeps the mapping, headers and skipped rows as the request's CSV record, and consumes the
 upload, all in the same savepoint."""
 
-import json
 import uuid
 from dataclasses import asdict, dataclass
 from datetime import timedelta
@@ -35,7 +34,7 @@ from sqlalchemy.dialects.postgresql import insert
 from sqlalchemy.ext.asyncio import AsyncSession
 
 from dewpoint.apps import csv_uploads
-from dewpoint.apps.csv_input import RowError, Table, build_rows, mapping_problems
+from dewpoint.apps.csv_input import CsvFileError, RowError, build_rows, mapping_problems, read_table
 from dewpoint.apps.inputs import INPUT_INVALID, RESERVED_INPUT, InputRefusedError, claim_input
 from dewpoint.apps.workflow_ops import abi_reasons
 from dewpoint.core.audit import service as audit
@@ -333,24 +332,31 @@ async def _frozen(
     envelope_id = await claims.write_envelope(s, ClaimCipher(keys), tenant_id, request_id=request_id, envelope=envelope)
     if built is None or csv is None:
         return _Frozen(version.id, envelope_id, {})
-    record = {"mapping": dict(csv.mapping), "headers": built.headers, "skipped": [asdict(e) for e in built.errors],
-              "row_count": len(built.rows)}  # fmt: skip
+    record = {
+        "mapping": dict(csv.mapping),
+        "headers": built.headers,
+        "row_count": len(built.rows),
+        "skipped": [{"row": row, "code": code} for row, code in built.skipped],  # every one, its first rule
+        "errors": [asdict(e) for e in built.errors],  # the first ones, in detail
+        "error_count": built.error_count,
+    }
     await claims.write_csv_record(s, ClaimCipher(keys), tenant_id, request_id=request_id, record=record)
     await s.execute(
         update(CsvUpload)
         .where(CsvUpload.id == csv.upload_id)
         .values(staged=None, consumed_by=request_id, consumed_at=func.now())
     )
-    skipped = len({e.row for e in built.errors})
     return _Frozen(version.id, envelope_id, {"csv_digest": built.file_digest.hex(), "csv_rows": len(built.rows),
-                                             "csv_skipped": skipped})  # fmt: skip
+                                             "csv_skipped": len(built.skipped)})  # fmt: skip
 
 
 @dataclass(frozen=True)
 class _Built:
     headers: list[str]
     rows: list[dict[str, Any]]
-    errors: list[RowError]  # every rule a skipped row broke
+    skipped: list[tuple[int, str]]  # every skipped record: its number and the first rule it broke
+    errors: list[RowError]  # the first ones, in detail
+    error_count: int
     file_digest: bytes
 
 
@@ -379,18 +385,20 @@ async def _rows(
         raise _Consumed
     if not live:
         raise _Refused(UPLOAD_EXPIRED, ["This upload has expired: upload the file again."], version_id)
-    plaintext = await ClaimCipher(keys, purpose=csv_uploads.PURPOSE).open(str(tenant_id), str(upload.id), upload.staged)
-    staged = json.loads(plaintext)
-    table = Table(staged["headers"], staged["rows"])
+    data = await ClaimCipher(keys, purpose=csv_uploads.PURPOSE).open(str(tenant_id), str(upload.id), upload.staged)
+    try:  # under the frozen version's caps, which may be lower than those it was uploaded under
+        table = read_table(data, max_rows=int(declared["max_rows"]), max_bytes=csv_uploads.byte_cap(declared))
+    except CsvFileError as e:
+        raise _Refused(INPUT_INVALID, [f"The CSV file: {e.code}."], version_id) from None
     columns = declared["columns"]
     problems = mapping_problems(columns, csv.mapping, table.headers)
     if problems:
         messages = [f"The mapping's column `{p['column']}`: {p['code']}." for p in problems[:_LISTED]]
         raise _Refused(CSV_MAPPING_INVALID, messages, version_id)
-    rows, errors = build_rows(table, columns, csv.mapping)
-    if errors and not csv.skip_invalid:
-        raise _Refused(INPUT_INVALID, [_row_message(e) for e in errors[:_LISTED]], version_id)
-    return _Built(table.headers, rows, errors, upload.file_digest)
+    built = build_rows(table, columns, csv.mapping)
+    if built.skipped and not csv.skip_invalid:
+        raise _Refused(INPUT_INVALID, [_row_message(e) for e in built.errors[:_LISTED]], version_id)
+    return _Built(table.headers, built.rows, built.skipped, built.errors, built.error_count, upload.file_digest)
 
 
 async def _insert(
diff --git a/backend/src/dewpoint/apps/csv_input.py b/backend/src/dewpoint/apps/csv_input.py
index 838638b..4113576 100644
--- a/backend/src/dewpoint/apps/csv_input.py
+++ b/backend/src/dewpoint/apps/csv_input.py
@@ -6,7 +6,14 @@ strict quoting; blank lines are skipped. Its caps are enforced: bytes, then data
 A table's rows are built through a mapping from declared column names to the file's headers: each cell converted to its
 column's canonical value (`engine.graph.csv.convert`), an empty cell absent (its column's default, or `required`). What
 breaks a rule is reported as the record's number (1 is the first after the header), the column's declared name and a
-fixed code: never a cell's text nor a header, both of which are the file's data."""
+fixed code: never a cell's text nor a header, both of which are the file's data.
+
+What the builder keeps is bounded by the records, never by records times columns (the owner's M2 review: 200 required
+columns of empty cells in 10,000 records break 2 million rules in a 2 MB file): the first `LISTED_ERRORS` errors in
+detail, each skipped record's number and the first rule it broke, and a count of every error.
+
+A field may be as long as the platform's byte cap: Python's csv module refuses one past 131,072 characters by default,
+so its process-wide limit is raised to that cap here (nothing else in the process reads CSV)."""
 
 import csv
 import io
@@ -14,7 +21,7 @@ from collections.abc import Iterator, Mapping, Sequence
 from dataclasses import dataclass
 from typing import Any
 
-from dewpoint.engine.graph.csv import convert
+from dewpoint.engine.graph.csv import MAX_BYTES, convert
 
 DELIMITERS = (",", ";", "\t")  # tried in this order: a tie goes to the earlier one
 FILE_CODES = frozenset(
@@ -22,6 +29,9 @@ FILE_CODES = frozenset(
 )
 ROW_CODES = frozenset({"required", "cell_count"})  # beside a cell's conversion codes (`CELL_CODES`)
 MAPPING_CODES = frozenset({"required_unmapped", "unknown_column", "unknown_header", "header_reused"})
+LISTED_ERRORS = 100  # errors kept in detail; the count is every one
+
+csv.field_size_limit(max(csv.field_size_limit(), MAX_BYTES))
 
 
 class CsvFileError(Exception):
@@ -45,6 +55,14 @@ class RowError:
     code: str
 
 
+@dataclass(frozen=True)
+class Built:
+    rows: list[dict[str, Any]]  # every record that broke no rule
+    skipped: list[tuple[int, str]]  # every other record: its number and the first rule it broke
+    errors: list[RowError]  # the first `LISTED_ERRORS` errors, in order
+    error_count: int  # every error
+
+
 def _records(text: str, delimiter: str) -> Iterator[list[str]]:
     return csv.reader(io.StringIO(text, newline=""), delimiter=delimiter, strict=True)
 
@@ -125,36 +143,40 @@ def mapping_problems(
     return problems
 
 
-def build_rows(
-    table: Table, columns: Sequence[Mapping[str, Any]], mapping: Mapping[str, str]
-) -> tuple[list[dict[str, Any]], list[RowError]]:
-    """The rows `mapping` builds from `table` (its problems checked first, `mapping_problems`), and the errors of
-    every record that breaks a rule, which builds no row."""
+def build_rows(table: Table, columns: Sequence[Mapping[str, Any]], mapping: Mapping[str, str]) -> Built:
+    """The rows `mapping` builds from `table` (its problems checked first, `mapping_problems`); a record that breaks a
+    rule builds none, and is reported within the builder's bounds."""
     position = {header: i for i, header in enumerate(table.headers)}
     rows: list[dict[str, Any]] = []
+    skipped: list[tuple[int, str]] = []
     errors: list[RowError] = []
+    count = 0
     for number, record in enumerate(table.rows, start=1):
+        broke: list[RowError] = []
         if len(record) != len(table.headers):
-            errors.append(RowError(number, None, "cell_count"))
-            continue
+            broke.append(RowError(number, None, "cell_count"))
         row: dict[str, Any] = {}
-        broken = False
-        for c in columns:
+        for c in columns if not broke else ():
             header = mapping.get(c["name"])
             text = record[position[header]] if header is not None else ""
             if text == "":
                 if "default" in c:
                     row[c["name"]] = c["default"]
                 elif c.get("required"):
-                    errors.append(RowError(number, c["name"], "required"))
-                    broken = True
+                    broke.append(RowError(number, c["name"], "required"))
                 continue
             value, code = convert(c["type"], text, c.get("values"))
             if code is not None:
-                errors.append(RowError(number, c["name"], code))
-                broken = True
+                broke.append(RowError(number, c["name"], code))
             else:
                 row[c["name"]] = value
-        if not broken:
+            if len(broke) > LISTED_ERRORS:  # a record keeps no more detail than the whole file lists
+                broke.pop()
+                count += 1
+        if not broke:
             rows.append(row)
-    return rows, errors
+            continue
+        skipped.append((number, broke[0].code))
+        count += len(broke)
+        errors.extend(broke[: LISTED_ERRORS - len(errors)])
+    return Built(rows, skipped, errors, count)
diff --git a/backend/src/dewpoint/apps/csv_uploads.py b/backend/src/dewpoint/apps/csv_uploads.py
index 1eaa523..09e1c08 100644
--- a/backend/src/dewpoint/apps/csv_uploads.py
+++ b/backend/src/dewpoint/apps/csv_uploads.py
@@ -1,7 +1,8 @@
 # SPDX-License-Identifier: Apache-2.0
-"""A CSV staged for a start (engine 2b spec §8.1): read as data only (`apps.csv_input`), its headers and cells sealed
-with the tenant's key under `csv.upload` (the upload's id the context), owned by its uploader and tenant for one hour.
-A start consumes it in its own transaction.
+"""A CSV staged for a start (engine 2b spec §8.1): read as data only (`apps.csv_input`), then its own bytes sealed with
+the tenant's key under `csv.upload` (the upload's id the context), owned by its uploader and tenant for one hour: what's
+stored is bounded by the file's cap, never a parsed form several times larger. A start reads it again under the version
+it freezes, and consumes it in its own transaction.
 
 What the uploader is told: the file's headers, the declared columns mapped to them (the workflow's saved default
 mapping, else the exact matches), what keeps that mapping from building rows, a preview of the first records' mapped
@@ -36,7 +37,6 @@ PURPOSE = "csv.upload"
 MAPPING_PURPOSE = "csv.mapping"
 TTL = timedelta(hours=1)
 PREVIEW_ROWS = 5
-LISTED_ERRORS = 100  # the response lists this many; its count is every one
 
 
 def declaration(version: WorkflowVersion) -> dict[str, Any] | None:
@@ -53,7 +53,7 @@ def byte_cap(csv: Mapping[str, Any]) -> int:
 def described(table: Table, columns: Sequence[Mapping[str, Any]], mapping: Mapping[str, str]) -> dict[str, Any]:
     """What `mapping` makes of `table`: its problems, the preview and the records' errors."""
     problems = mapping_problems(columns, mapping, table.headers)
-    errors = [] if problems else build_rows(table, columns, mapping)[1]
+    built = None if problems else build_rows(table, columns, mapping)
     position = {header: i for i, header in enumerate(table.headers)}
     shown = [c["name"] for c in columns if not c.get("sensitive") and c["name"] in mapping and not problems]
     preview = [
@@ -65,8 +65,8 @@ def described(table: Table, columns: Sequence[Mapping[str, Any]], mapping: Mappi
         "problems": problems,
         "masked_columns": [c["name"] for c in columns if c.get("sensitive")],
         "preview": preview,
-        "errors": [asdict(e) for e in errors[:LISTED_ERRORS]],
-        "error_count": len(errors),
+        "errors": [asdict(e) for e in built.errors] if built else [],
+        "error_count": built.error_count if built else 0,
     }
 
 
@@ -88,8 +88,7 @@ async def stage(
     staged nothing."""
     table = read_table(data, max_rows=int(csv["max_rows"]), max_bytes=byte_cap(csv))
     upload_id = uuid.uuid4()
-    plaintext = json.dumps({"headers": table.headers, "rows": table.rows}, ensure_ascii=False).encode()
-    staged = await ClaimCipher(keys, purpose=PURPOSE).seal(str(tenant_id), str(upload_id), plaintext)
+    staged = await ClaimCipher(keys, purpose=PURPOSE).seal(str(tenant_id), str(upload_id), data)
     key_version, file_digest = await digests.file_digest(keys, str(tenant_id), data)
     upload = CsvUpload(
         id=upload_id, tenant_id=tenant_id, owner_id=owner_id, workflow_id=workflow_id, staged=staged,
diff --git a/backend/tests/apps/api/test_csv_starts_api.py b/backend/tests/apps/api/test_csv_starts_api.py
index 5cb303e..09b560c 100644
--- a/backend/tests/apps/api/test_csv_starts_api.py
+++ b/backend/tests/apps/api/test_csv_starts_api.py
@@ -61,7 +61,9 @@ async def test_a_csv_start_is_admitted_and_its_run_shows_its_record(
         "mapping": MAPPING,
         "headers": ["Site", "VLAN", "PSK"],
         "row_count": 1,
-        "skipped": [{"row": 2, "column": "vlan", "code": "not_integer"}],
+        "skipped": [{"row": 2, "code": "not_integer"}],
+        "errors": [{"row": 2, "column": "vlan", "code": "not_integer"}],
+        "error_count": 1,
     }
     assert "s3cret" not in str(details)
 
diff --git a/backend/tests/apps/api/test_csv_uploads_api.py b/backend/tests/apps/api/test_csv_uploads_api.py
index da01dfd..4f919c4 100644
--- a/backend/tests/apps/api/test_csv_uploads_api.py
+++ b/backend/tests/apps/api/test_csv_uploads_api.py
@@ -172,3 +172,36 @@ async def test_a_workflow_without_a_csv_takes_no_upload(
     client = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx)
     answer = await client.post(uploads_url(ctx, wf), content=FILE, headers=CSV_TYPE)
     assert (answer.status_code, answer.json()) == (409, {"error": "csv_not_declared"})
+
+
+WIDE = {"columns": [{"header": f"h{i}", "name": f"c{i}", "type": "string", "required": True} for i in range(200)]}
+WIDE_FILE = (",".join(f"h{i}" for i in range(200)) + "\n" + ("," * 199 + "\n") * 10_000).encode()
+
+
+async def test_an_upload_at_the_permitted_limits_lists_100_errors_and_counts_them_all(
+    keyed_app, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings
+) -> None:
+    """The owner's M2 review: 200 required columns and 10,000 records of empty cells, 2 MB, break 2 million rules. The
+    answer lists the first 100 and counts every one, and the file is staged as its own bytes, sealed."""
+    graph = G().node("a", "testkit.echo@1", {"value": 1}).data() | {"settings": {"csv": WIDE}}
+    ctx, wf = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings, graph)
+    client = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx)
+    answer = await client.post(uploads_url(ctx, wf), content=WIDE_FILE, headers=CSV_TYPE)
+    assert answer.status_code == 201, answer.text[:200]
+    body = answer.json()
+    assert (len(body["errors"]), body["error_count"], body["row_count"]) == (100, 2_000_000, 10_000)
+    row = await stored(owner_sessionmaker, body["upload_id"])
+    assert len(row["staged"]) <= len(WIDE_FILE) + 64  # the file's bytes, never a parsed form several times larger
+
+
+async def test_a_cell_longer_than_pythons_default_field_limit_uploads(
+    keyed_app, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings
+) -> None:
+    """The owner's M2 review: the byte cap governs a field's length, not Python's 131,072-character default."""
+    graph = G().node("a", "testkit.echo@1", {"value": 1}).data() | {"settings": {"csv": {"columns": CSV["columns"]}}}
+    ctx, wf = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings, graph)
+    client = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx)
+    long = b"Site\n" + b"x" * 140_000 + b"\n"
+    answer = await client.post(uploads_url(ctx, wf), content=long, headers=CSV_TYPE)
+    assert answer.status_code == 201, answer.text[:200]
+    assert len(answer.json()["preview"][0]["cells"]["site"]) == 140_000
diff --git a/backend/tests/apps/test_admission_csv.py b/backend/tests/apps/test_admission_csv.py
index 676b279..4ddc3f1 100644
--- a/backend/tests/apps/test_admission_csv.py
+++ b/backend/tests/apps/test_admission_csv.py
@@ -10,6 +10,7 @@ trigger's rows from a staged upload and consumes it in the same transaction.
   cells cleared, and the mapping, headers and skipped rows kept in a `run_inputs` row of the role `csv`."""
 
 import asyncio
+import json
 import uuid
 from typing import Any
 
@@ -25,6 +26,7 @@ from dewpoint.engine.graph.csv import MAX_BYTES
 from dewpoint.engine.handles import StoredClaim, resolve_value
 from tests.apps.api.helpers import member_client
 from tests.apps.test_admission import KEYS, SCHEMA, TOKEN, admit, count, current, published
+from tests.apps.test_workflow_ops import publish, save
 
 pytestmark = pytest.mark.usefixtures("development_deployment")
 CSV = {
@@ -106,7 +108,8 @@ async def test_a_csv_start_freezes_its_rows_and_consumes_its_upload(
     row = await upload_row(owner_sessionmaker, upload)
     assert (row["staged"], row["consumed_by"]) == (None, r.id) and row["consumed_at"] is not None
     assert await record(api_sessionmaker, ctx, r.id) == {
-        "mapping": MAPPING, "headers": ["Site", "VLAN", "PSK"], "skipped": [], "row_count": 2,
+        "mapping": MAPPING, "headers": ["Site", "VLAN", "PSK"], "row_count": 2, "skipped": [], "errors": [],
+        "error_count": 0,
     }  # fmt: skip
     assert (audit["csv_digest"], audit["csv_rows"], audit["csv_skipped"]) == (row["file_digest"].hex(), 2, 0)
 
@@ -239,8 +242,9 @@ async def test_a_row_that_breaks_a_rule_refuses_the_start_unless_invalid_rows_ar
     assert (await upload_row(owner_sessionmaker, upload))["consumed_by"] is None  # nothing commits
     r = (await admit(api_sessionmaker, ctx, wf, key="k2", csv=start(upload, skip_invalid=True))).request
     assert (await full_input(dispatch_sessionmaker, ctx, r.id))["rows"] == [{"site": "lyon", "vlan": 2}]
-    skipped = (await record(api_sessionmaker, ctx, r.id))["skipped"]
-    assert skipped == [{"row": 1, "column": "vlan", "code": "not_integer"}]
+    kept = await record(api_sessionmaker, ctx, r.id)
+    assert (kept["skipped"], kept["error_count"]) == ([{"row": 1, "code": "not_integer"}], 1)
+    assert kept["errors"] == [{"row": 1, "column": "vlan", "code": "not_integer"}]
 
 
 async def test_a_csv_start_still_refuses_rows_in_its_input(csv_ready, api_sessionmaker) -> None:
@@ -279,3 +283,51 @@ async def test_a_rerun_takes_the_original_rows_or_a_new_csv(csv_ready, api_sessi
                         rerun=admission.Rerun(first.id, {"token": TOKEN}, start(upload, {"site": "Site"})),
                         input={"token": TOKEN}, csv=start(upload, {"site": "Site"}))  # fmt: skip
     assert (await full_input(dispatch_sessionmaker, ctx, fresh.request.id))["rows"] == [{"site": "nice", "vlan": 1}]
+
+
+WIDE = {"columns": [{"header": f"h{i}", "name": f"c{i}", "type": "string", "required": True} for i in range(200)],
+        "max_rows": 10_000, "max_bytes": MAX_BYTES}  # fmt: skip
+WIDE_FILE = (",".join(f"h{i}" for i in range(200)) + "\n" + ("," * 199 + "\n") * 10_000).encode()
+
+
+async def test_a_skip_invalid_start_at_the_permitted_limits_keeps_a_bounded_record(
+    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings
+) -> None:
+    """The owner's M2 review: 2 million broken rules in a 2 MB file. A refused start names the first five; a start that
+    skips them keeps each skipped record's number and first code, the first 100 errors in detail and an exact count,
+    in a record that grows with the records, never with records times columns."""
+    graph = {**GRAPH, "settings": {"input_schema": SCHEMA, "csv": WIDE}}
+    ctx, wf = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings, graph)
+    await current(dispatch_sessionmaker)
+    async with api_sessionmaker() as s, s.begin():
+        await tenant_scope(s, ctx.tenant_id)
+        body = await csv_uploads.stage(s, KEYS, tenant_id=ctx.tenant_id, owner_id=ctx.user.id, workflow_id=wf,
+                                       csv=WIDE, data=WIDE_FILE)  # fmt: skip
+    upload = uuid.UUID(body["upload_id"])
+    mapping = {f"c{i}": f"h{i}" for i in range(200)}
+    with pytest.raises(admission.AdmissionRefusedError) as refused:
+        await admit(api_sessionmaker, ctx, wf, csv=start(upload, mapping))
+    assert refused.value.messages == [f"The CSV's row 1, column `c{i}`: required." for i in range(5)]
+    r = (await admit(api_sessionmaker, ctx, wf, key="k2", csv=start(upload, mapping, skip_invalid=True))).request
+    kept = await record(api_sessionmaker, ctx, r.id)
+    assert (kept["row_count"], kept["error_count"], len(kept["errors"])) == (0, 2_000_000, 100)
+    assert kept["skipped"] == [{"row": n, "code": "required"} for n in range(1, 10_001)]
+    assert len(json.dumps(kept)) < 400_000
+    async with owner_sessionmaker() as s:
+        audit = (await s.execute(text("select details from audit_log where action = 'run.request'"))).scalar_one()
+    assert (audit["csv_rows"], audit["csv_skipped"]) == (0, 10_000)
+
+
+async def test_the_frozen_versions_caps_govern_the_start(
+    csv_ready, owner_sessionmaker, api_sessionmaker, api_settings
+) -> None:
+    """The upload is staged as its bytes, and read again at the start under the version it freezes: one published
+    since with a lower cap refuses a file the earlier one took."""
+    ctx, wf = csv_ready
+    upload = await staged(api_sessionmaker, ctx, wf)
+    lower = {**GRAPH, "settings": {"input_schema": SCHEMA, "csv": {**CSV, "max_rows": 1}}}
+    await save(api_sessionmaker, ctx, wf, lower)
+    assert (await publish(api_sessionmaker, ctx, wf, api_settings)).version is not None
+    with pytest.raises(admission.AdmissionRefusedError) as refused:
+        await admit(api_sessionmaker, ctx, wf, csv=start(upload))
+    assert (refused.value.reason, refused.value.messages) == ("input_invalid", ["The CSV file: csv_too_many_rows."])
diff --git a/backend/tests/apps/test_csv_input.py b/backend/tests/apps/test_csv_input.py
index cbd8a89..85f2e87 100644
--- a/backend/tests/apps/test_csv_input.py
+++ b/backend/tests/apps/test_csv_input.py
@@ -13,14 +13,16 @@ from jsonschema import Draft202012Validator
 
 from dewpoint.apps.csv_input import (
     FILE_CODES,
+    LISTED_ERRORS,
     CsvFileError,
     RowError,
+    Table,
     build_rows,
     exact_mapping,
     mapping_problems,
     read_table,
 )
-from dewpoint.engine.graph.csv import CELL_CODES, trigger_schema
+from dewpoint.engine.graph.csv import CELL_CODES, MAX_BYTES, MAX_ROWS, trigger_schema
 
 COLUMNS = [
     {"header": "Site", "name": "site", "type": "string", "required": True},
@@ -90,9 +92,9 @@ def test_a_mapping_is_checked_against_the_declaration_and_the_file() -> None:
 def test_rows_are_built_typed_with_defaults_filled_and_absent_cells_omitted() -> None:
     table = read_table(b"Site,VLAN,MAC,PSK,Extra\nparis,,AA-BB-CC-DD-EE-FF,s3cret,ignored\nlyon,20,,,\n",
                        max_rows=10, max_bytes=1000)  # fmt: skip
-    rows, errors = build_rows(table, COLUMNS, MAPPING)
-    assert errors == []
-    assert rows == [
+    built = build_rows(table, COLUMNS, MAPPING)
+    assert (built.errors, built.skipped, built.error_count) == ([], [], 0)
+    assert built.rows == [
         {"site": "paris", "vlan": 1, "mac": "aa:bb:cc:dd:ee:ff", "psk": "s3cret"},
         {"site": "lyon", "vlan": 20},
     ]
@@ -100,14 +102,37 @@ def test_rows_are_built_typed_with_defaults_filled_and_absent_cells_omitted() ->
 
 def test_a_row_that_breaks_a_rule_is_its_number_column_and_code() -> None:
     table = read_table(b"Site,VLAN,MAC\n,x,zz\nok,1\nfine,2,\n", max_rows=10, max_bytes=1000)
-    rows, errors = build_rows(table, COLUMNS, {"site": "Site", "vlan": "VLAN", "mac": "MAC"})
-    assert rows == [{"site": "fine", "vlan": 2}]
-    assert errors == [
+    built = build_rows(table, COLUMNS, {"site": "Site", "vlan": "VLAN", "mac": "MAC"})
+    assert built.rows == [{"site": "fine", "vlan": 2}]
+    assert built.errors == [
         RowError(1, "site", "required"),
         RowError(1, "vlan", "not_integer"),
         RowError(1, "mac", "not_mac"),
         RowError(2, None, "cell_count"),
     ]
+    assert (built.skipped, built.error_count) == ([(1, "required"), (2, "cell_count")], 4)  # each row's first
+
+
+def test_at_the_permitted_limits_the_detail_kept_is_bounded_and_the_count_exact() -> None:
+    """The owner's M2 review: 200 required columns and 10,000 records of empty cells fit in a 2 MB file, and break 2
+    million rules. The builder keeps the first errors in detail, each skipped record's number and first code, and
+    counts every error: what it holds grows with the records, never with records times columns."""
+    columns = [{"header": f"h{i}", "name": f"c{i}", "type": "string", "required": True} for i in range(200)]
+    data = (",".join(c["header"] for c in columns) + "\n" + ("," * 199 + "\n") * MAX_ROWS).encode()
+    assert len(data) <= MAX_BYTES
+    table = read_table(data, max_rows=MAX_ROWS, max_bytes=MAX_BYTES)
+    built = build_rows(table, columns, exact_mapping(columns, table.headers))
+    assert (built.rows, built.error_count) == ([], 200 * MAX_ROWS)
+    assert built.errors == [RowError(1, f"c{i}", "required") for i in range(LISTED_ERRORS)]
+    assert built.skipped == [(n, "required") for n in range(1, MAX_ROWS + 1)]
+
+
+@pytest.mark.parametrize("length", [140_000, MAX_BYTES - 64])
+def test_a_cell_as_long_as_the_byte_cap_allows_is_read(length: int) -> None:
+    """The owner's M2 review: Python's csv module refuses a field past 131,072 characters by default; the byte cap
+    governs instead."""
+    table = read_table(b"Note\n" + b"x" * length + b"\n", max_rows=1, max_bytes=MAX_BYTES)
+    assert len(table.rows[0][0]) == length
 
 
 ROW_SCHEMA = trigger_schema({"csv": {"columns": COLUMNS, "max_rows": 10_000}})["properties"]["rows"]["items"]
@@ -129,10 +154,11 @@ def test_any_bytes_read_as_a_table_or_give_a_file_code(data: bytes) -> None:
 @settings(max_examples=300, deadline=None)
 @given(st.lists(st.lists(CELL, min_size=4, max_size=5), max_size=8))
 def test_built_rows_always_match_the_row_schema_and_errors_never_quote_a_cell(cells: list[list[str]]) -> None:
-    from dewpoint.apps.csv_input import Table
-
-    rows, errors = build_rows(Table(["Site", "VLAN", "MAC", "PSK"], cells), COLUMNS, MAPPING)
+    built = build_rows(Table(["Site", "VLAN", "MAC", "PSK"], cells), COLUMNS, MAPPING)
     validator = Draft202012Validator(ROW_SCHEMA)
-    assert all(validator.is_valid(row) for row in rows)
-    assert len(rows) + len({e.row for e in errors}) == len(cells)
-    assert all(e.code in CELL_CODES | {"required", "cell_count"} and e.column in (None, *MAPPING) for e in errors)
+    assert all(validator.is_valid(row) for row in built.rows)
+    assert len(built.rows) + len(built.skipped) == len(cells)
+    assert built.error_count >= len(built.skipped) and len(built.errors) == min(built.error_count, LISTED_ERRORS)
+    codes = CELL_CODES | {"required", "cell_count"}
+    assert all(e.code in codes and e.column in (None, *MAPPING) for e in built.errors)
+    assert all(code in codes for _, code in built.skipped)
```

**Checkpoint (milestone 2).** Focused: as milestone 1, plus the CSV parser, uploads, mappings, starts and their schema
proofs (960; 967 after Task 9); the migrations 0025 → 0028 → 0025 → 0028 over existing rows (a CSV record deleted on the
way down, its claim kept). The owner held it once (Task 9), approved it as a prototype checkpoint, and deferred the
reader's memory to production sizing (2026-10-04).

## Milestone 3 — Schedules

### Task 10: A stale schedule update sent directly is discarded, not refused

**Commit:** `9971a55` (prototype `proto/2b3a-v2`); the replay's tree was identical: yes.

**Modify:** `backend/tests/apps/worker/test_temporal_contract.py`

**What it does:**

SDK 1.33.0's `ScheduleHandle.update()` sends no conflict token, so 2b-3a's sync sends
`UpdateScheduleRequest` itself with the token of the `DescribeScheduleResponse` it computed
from (the owner's correction). Pinned on the CLI dev server (server 1.32.0; the file fails
on any other SDK or server version): the token counts the schedule's updates, and a firing
doesn't move it; an update with the current token lands and the describe sees it at once;
one with a token a later update made stale is discarded: the call succeeds and nothing
changes (the server logs "Update conflicted with concurrent change"). Temporal never lets
a stale writer overwrite a newer state, but tells the writer only through the describe that
follows. A pause is the update's own `state.paused`, under the same token, and the action
stays sealed under the schedule's tenant. Stable over six runs.

- [ ] **Step 1: its tests alone, before its code.** Run: `uv run pytest -n 8 tests/apps/worker/test_temporal_contract.py`. Replay result (exit 0), shortened:

```
.......                                                                  [100%]
7 passed in 32.19s
```

- [ ] **Step 2: its code, then the same tests.** Replay result (exit 0), shortened:

```
.......                                                                  [100%]
7 passed in 35.52s
```

Evidence beyond the replay: a contract test of Temporal itself, so it passes before any Dewpoint code. The prototype's
probe found the outline's premise wrong: a stale update isn't refused, it's discarded.

- [ ] **Step 3: commit.** `git cherry-pick --no-commit 9971a55 && git commit -C 9971a55`

The diff:

```diff
diff --git a/backend/tests/apps/worker/test_temporal_contract.py b/backend/tests/apps/worker/test_temporal_contract.py
index 46c588f..c87de4b 100644
--- a/backend/tests/apps/worker/test_temporal_contract.py
+++ b/backend/tests/apps/worker/test_temporal_contract.py
@@ -6,6 +6,8 @@ Test-only workflows on the CLI dev server, through the tenant codec with fixture
 - every payload, on every path, is encoded and decoded with a context whose workflow id names its tenant;
 - a schedule's `TemporalScheduledStartTime` is whole seconds and the same under replay, and a backfill over a time
   that already fired starts a second execution with the same time;
+- a schedule update sent directly with a conflict token that a later update made stale is discarded, not refused: the
+  call succeeds and nothing changes, so a writer learns it from the describe that follows (2b-3a's sync);
 - the SDK checks a payload's size after the codec;
 - a workflow task whose completion passes the gRPC message limit gets its workflow terminated."""
 
@@ -22,7 +24,7 @@ import temporalio
 from temporalio import activity, workflow
 from temporalio.api.common.v1 import Payload
 from temporalio.api.enums.v1 import EventType
-from temporalio.api.workflowservice.v1 import GetSystemInfoRequest
+from temporalio.api.workflowservice.v1 import DescribeScheduleRequest, GetSystemInfoRequest, UpdateScheduleRequest
 from temporalio.client import (
     Client,
     Schedule,
@@ -296,6 +298,61 @@ async def test_a_schedules_time_is_whole_seconds_the_same_on_replay_and_a_backfi
     assert stamps(replaying=True) == times
 
 
+async def test_a_stale_schedule_update_is_discarded_and_the_describe_after_it_shows_it(
+    dev_env: WorkflowEnvironment,
+) -> None:
+    """2b-3a's first M3 gate (the owner's correction): SDK 1.33.0's `ScheduleHandle.update()` sends no conflict token,
+    so the sync sends `UpdateScheduleRequest` itself, with the token of the `DescribeScheduleResponse` it computed from.
+    On this server the token counts the schedule's updates (a firing doesn't move it); an update with the current one
+    lands and is seen by the describe at once; one with a token a later update made stale is DISCARDED: the call
+    succeeds and nothing changes. So Temporal never lets a stale writer overwrite a newer state, but tells it only
+    through the describe that follows, which the sync reads before it records anything. A pause is the update's own
+    `state.paused`, under the same token; the action stays sealed under the schedule's tenant."""
+    client = Client(dev_env.client.service_client, namespace=dev_env.client.namespace, data_converter=RECORDING)
+    schedule_id = f"t:{A}:sched:{uuid.uuid4()}"
+    service, namespace = client.workflow_service, client.namespace
+
+    def every(hours: int, *, paused: bool = True) -> Schedule:
+        return Schedule(
+            action=ScheduleActionStartWorkflow(Tick.run, schedule_id, id=schedule_id, task_queue=QUEUE),
+            spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=timedelta(hours=hours))]),
+            policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.ALLOW_ALL),
+            state=ScheduleState(paused=paused),
+        )
+
+    async def described() -> tuple[bytes, int, bool]:
+        answer = await service.describe_schedule(DescribeScheduleRequest(namespace=namespace, schedule_id=schedule_id))
+        return answer.conflict_token, answer.schedule.spec.interval[0].interval.seconds, answer.schedule.state.paused
+
+    async def update(schedule: Schedule, token: bytes) -> None:
+        await service.update_schedule(
+            UpdateScheduleRequest(
+                namespace=namespace, schedule_id=schedule_id, schedule=await schedule._to_proto(client),
+                conflict_token=token, identity="contract", request_id=str(uuid.uuid4()),
+            )
+        )  # fmt: skip
+
+    handle = await client.create_schedule(schedule_id, every(1))
+    first, _, _ = await described()
+    await update(every(2), first)
+    second, interval, _ = await described()  # at once: no wait
+    assert second != first and interval == 7200
+    await update(every(3), first)  # computed from the first describe: stale since the second update
+    assert await described() == (second, 7200, True)  # discarded, and the call didn't fail
+    now = datetime.now(UTC).replace(second=0, microsecond=0)
+    await handle.backfill(ScheduleBackfill(start_at=now - timedelta(minutes=2), end_at=now,
+                                           overlap=ScheduleOverlapPolicy.ALLOW_ALL))  # fmt: skip
+    assert (await described())[0] == second  # a firing isn't an update
+    await update(every(3, paused=False), second)
+    third, interval, paused = await described()
+    assert (third != second, interval, paused) == (True, 10800, False)  # unpaused through the update's state
+    action = (await handle.describe()).schedule.action
+    assert isinstance(action, ScheduleActionStartWorkflow)
+    [arg] = action.args
+    assert isinstance(arg, Payload) and arg.metadata[TENANT] == A.encode() and await opened(arg) == schedule_id
+    await handle.delete()
+
+
 async def replay(workflows: list[type], runs: list[WorkflowHistory]) -> None:
     """Every history, replayed through the recording codec: a nondeterminism, or a path without a tenant, raises."""
```

### Task 11: A schedule's note shows the generation of the update that landed, never a stale writer's

**Commit:** `c4d35a1` (prototype `proto/2b3a-v2`); the replay's tree was identical: yes.

**Modify:** `backend/tests/apps/worker/test_temporal_contract.py`

**What it does:**

The owner's ruling (option b): 2b-3a's sync writes only its generation counter into the
schedule's note, in the same token-bearing update as its spec, action and pause state, and
marks a generation synced only once a fresh describe shows that marker. Pinned on the dev
server: the note carries what the create wrote, then what each landed update wrote, a pause
included; two writers describing the same token, the landed one's marker is what the
read-back shows, and the stale one's never appears.

- [ ] **Step 1: its tests alone, before its code.** Run: `uv run pytest -n 8 tests/apps/worker/test_temporal_contract.py`. Replay result (exit 0), shortened:

```
........                                                                 [100%]
8 passed in 32.20s
```

- [ ] **Step 2: its code, then the same tests.** Replay result (exit 0), shortened:

```
........                                                                 [100%]
8 passed in 31.24s
```

Evidence beyond the replay: a contract test of Temporal itself: in the stale writer's race, the note shows only the
generation of the update that landed.

- [ ] **Step 3: commit.** `git cherry-pick --no-commit c4d35a1 && git commit -C c4d35a1`

The diff:

```diff
diff --git a/backend/tests/apps/worker/test_temporal_contract.py b/backend/tests/apps/worker/test_temporal_contract.py
index c87de4b..fbb3ee8 100644
--- a/backend/tests/apps/worker/test_temporal_contract.py
+++ b/backend/tests/apps/worker/test_temporal_contract.py
@@ -8,6 +8,8 @@ Test-only workflows on the CLI dev server, through the tenant codec with fixture
   that already fired starts a second execution with the same time;
 - a schedule update sent directly with a conflict token that a later update made stale is discarded, not refused: the
   call succeeds and nothing changes, so a writer learns it from the describe that follows (2b-3a's sync);
+- a schedule's note carries what its create or its last landed update wrote, the pause included, so the marker a stale
+  writer wrote is never what the read-back shows;
 - the SDK checks a payload's size after the codec;
 - a workflow task whose completion passes the gRPC message limit gets its workflow terminated."""
 
@@ -353,6 +355,56 @@ async def test_a_stale_schedule_update_is_discarded_and_the_describe_after_it_sh
     await handle.delete()
 
 
+MARK = "dewpoint generation {}"  # the only thing 2b-3a writes in a schedule's note (the owner's ruling: option b)
+
+
+async def test_a_schedules_note_shows_the_generation_of_the_update_that_landed_and_never_a_stale_writers(
+    dev_env: WorkflowEnvironment,
+) -> None:
+    """2b-3a's read-back gate (the owner's ruling): the sync writes its generation into the schedule's note in the same
+    token-bearing update as its spec, action and pause state, and marks the generation synced only once a fresh
+    describe shows that marker. The note carries what the create wrote, then what each landed update wrote, a pause
+    included. Two writers describe the same token; the one whose update lands is the one the read-back shows, and the
+    other's marker never appears: its update was discarded, and its read-back tells it so."""
+    client = Client(dev_env.client.service_client, namespace=dev_env.client.namespace, data_converter=RECORDING)
+    schedule_id = f"t:{A}:sched:{uuid.uuid4()}"
+    service, namespace = client.workflow_service, client.namespace
+
+    def wanted(hours: int, generation: int, *, paused: bool) -> Schedule:
+        return Schedule(
+            action=ScheduleActionStartWorkflow(Tick.run, schedule_id, id=schedule_id, task_queue=QUEUE),
+            spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=timedelta(hours=hours))]),
+            policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.ALLOW_ALL),
+            state=ScheduleState(paused=paused, note=MARK.format(generation)),
+        )
+
+    async def read_back() -> tuple[bytes, str, bool, int]:
+        answer = await service.describe_schedule(DescribeScheduleRequest(namespace=namespace, schedule_id=schedule_id))
+        state = answer.schedule.state
+        return answer.conflict_token, state.notes, state.paused, answer.schedule.spec.interval[0].interval.seconds
+
+    async def update(schedule: Schedule, token: bytes) -> None:
+        await service.update_schedule(
+            UpdateScheduleRequest(
+                namespace=namespace, schedule_id=schedule_id, schedule=await schedule._to_proto(client),
+                conflict_token=token, identity="contract", request_id=str(uuid.uuid4()),
+            )
+        )  # fmt: skip
+
+    handle = await client.create_schedule(schedule_id, wanted(1, 1, paused=False))
+    token, note, paused, _ = await read_back()
+    assert (note, paused) == (MARK.format(1), False)  # on create
+    stale, fresh = token, token  # two writers describe the same token: one read generation 2 before the other read 3
+    await update(wanted(3, 3, paused=False), fresh)
+    await update(wanted(2, 2, paused=False), stale)  # the slower writer's update, computed from the same describe
+    token, note, paused, interval = await read_back()
+    assert (note, paused, interval) == (MARK.format(3), False, 10800)  # the landed update's marker, never the stale one
+    await update(wanted(3, 4, paused=True), token)
+    _, note, paused, _ = await read_back()
+    assert (note, paused) == (MARK.format(4), True)  # a pause carries its generation too
+    await handle.delete()
+
+
 async def replay(workflows: list[type], runs: list[WorkflowHistory]) -> None:
     """Every history, replayed through the recording codec: a nondeterminism, or a path without a tenant, raises."""
```

### Task 12: Cron as Temporal reads it, both day fields and time zone changes included

**Commit:** `15f67d5` (prototype `proto/2b3a-v2`); the replay's tree was identical: yes.

**Modify:** `backend/tests/apps/worker/test_temporal_contract.py`

**What it does:**

The owner's ruling 9: 2b-3a's schedules accept only cron forms whose meaning is Temporal's
own, pinned through ListScheduleMatchingTimes on the dev server: names, both spellings of
Sunday, steps, ranges and lists read as cron does; a day of the month and a day of the week
restricted together must both match (cron's usual reading is either), so Dewpoint refuses
that form; a local time the spring change skips doesn't fire that day, and one the autumn
change repeats fires once, at its second occurrence.

- [ ] **Step 1: its tests alone, before its code.** Run: `uv run pytest -n 8 tests/apps/worker/test_temporal_contract.py`. Replay result (exit 0), shortened:

```
.........                                                                [100%]
9 passed in 31.59s
```

- [ ] **Step 2: its code, then the same tests.** Replay result (exit 0), shortened:

```
.........                                                                [100%]
9 passed in 32.21s
```

Evidence beyond the replay: a contract test of Temporal itself, through `ListScheduleMatchingTimes` on the dev server:
names, both spellings of Sunday, steps, ranges and lists; both day fields restricted together must both match; and a
daylight-saving change in each direction.

- [ ] **Step 3: commit.** `git cherry-pick --no-commit 15f67d5 && git commit -C 15f67d5`

The diff:

```diff
diff --git a/backend/tests/apps/worker/test_temporal_contract.py b/backend/tests/apps/worker/test_temporal_contract.py
index fbb3ee8..1b995c3 100644
--- a/backend/tests/apps/worker/test_temporal_contract.py
+++ b/backend/tests/apps/worker/test_temporal_contract.py
@@ -10,6 +10,9 @@ Test-only workflows on the CLI dev server, through the tenant codec with fixture
   call succeeds and nothing changes, so a writer learns it from the describe that follows (2b-3a's sync);
 - a schedule's note carries what its create or its last landed update wrote, the pause included, so the marker a stale
   writer wrote is never what the read-back shows;
+- how Temporal reads a five-field cron expression: a day of the month and a day of the week restricted together must
+  both match (cron's usual reading is either); a local time the spring change skips doesn't fire that day, and one the
+  autumn change repeats fires once, at its second occurrence;
 - the SDK checks a payload's size after the codec;
 - a workflow task whose completion passes the gRPC message limit gets its workflow terminated."""
 
@@ -23,10 +26,16 @@ from pathlib import Path
 from typing import Any
 
 import temporalio
+from google.protobuf.timestamp_pb2 import Timestamp
 from temporalio import activity, workflow
 from temporalio.api.common.v1 import Payload
 from temporalio.api.enums.v1 import EventType
-from temporalio.api.workflowservice.v1 import DescribeScheduleRequest, GetSystemInfoRequest, UpdateScheduleRequest
+from temporalio.api.workflowservice.v1 import (
+    DescribeScheduleRequest,
+    GetSystemInfoRequest,
+    ListScheduleMatchingTimesRequest,
+    UpdateScheduleRequest,
+)
 from temporalio.client import (
     Client,
     Schedule,
@@ -405,6 +414,62 @@ async def test_a_schedules_note_shows_the_generation_of_the_update_that_landed_a
     await handle.delete()
 
 
+# An expression, its time zone, a window, and every time Temporal fires in it, in UTC (the window's start excluded).
+CRON = [
+    ("0 9 * * 1-5", "UTC", "2026-06-01", "2026-06-09",
+     ["06-01 09:00", "06-02 09:00", "06-03 09:00", "06-04 09:00", "06-05 09:00", "06-08 09:00"]),
+    ("0 9 13 * 5", "UTC", "2026-01-01", "2026-12-31",
+     ["02-13 09:00", "03-13 09:00", "11-13 09:00"]),  # both days restricted: Fridays the 13th only, not either
+    ("*/20 * * * *", "UTC", "2026-06-01T00:00", "2026-06-01T01:30",
+     ["06-01 00:20", "06-01 00:40", "06-01 01:00", "06-01 01:20"]),
+    ("0 0 1 JAN,JUL *", "UTC", "2026-01-01", "2027-01-02", ["07-01 00:00", "01-01 00:00"]),
+    ("0 12 * * SUN", "UTC", "2026-06-01", "2026-06-20", ["06-07 12:00", "06-14 12:00"]),
+    ("0 12 * * 0", "UTC", "2026-06-01", "2026-06-20", ["06-07 12:00", "06-14 12:00"]),
+    ("0 12 * * 7", "UTC", "2026-06-01", "2026-06-20", ["06-07 12:00", "06-14 12:00"]),
+    ("0 9-17/4 * * *", "UTC", "2026-06-01", "2026-06-02", ["06-01 09:00", "06-01 13:00", "06-01 17:00"]),
+    ("5 4 31 * *", "UTC", "2026-01-01", "2026-12-31",
+     ["01-31 04:05", "03-31 04:05", "05-31 04:05", "07-31 04:05", "08-31 04:05", "10-31 04:05"]),
+    ("0 9 * * *", "Europe/Paris", "2026-03-27", "2026-03-31",
+     ["03-27 08:00", "03-28 08:00", "03-29 07:00", "03-30 07:00"]),  # local 09:00 across the spring change
+    ("30 2 * * *", "Europe/Paris", "2026-03-27", "2026-03-31",
+     ["03-27 01:30", "03-28 01:30", "03-30 00:30"]),  # 02:30 doesn't exist on 03-29: it doesn't fire
+    ("30 2 * * *", "Europe/Paris", "2026-10-23", "2026-10-27",
+     ["10-23 00:30", "10-24 00:30", "10-25 01:30", "10-26 01:30"]),  # 02:30 twice on 10-25: once, the second
+]  # fmt: skip
+
+
+async def test_cron_as_temporal_reads_it(dev_env: WorkflowEnvironment) -> None:
+    """2b-3a's schedules accept only the cron forms whose meaning this pins (the owner's ruling 9): Temporal's own
+    reading, through `ListScheduleMatchingTimes`, never one of Dewpoint's. Names, both spellings of Sunday, steps,
+    ranges and lists read as cron does; a day of the month and a day of the week together must both match, which
+    differs from cron's usual reading, so Dewpoint refuses that form; and a time zone's changes skip a local time that
+    doesn't exist and fire a repeated one once."""
+    client = Client(dev_env.client.service_client, namespace=dev_env.client.namespace, data_converter=RECORDING)
+
+    def at(text: str) -> Timestamp:
+        stamp = Timestamp()
+        stamp.FromDatetime(datetime.fromisoformat(text).replace(tzinfo=UTC))
+        return stamp
+
+    for cron, zone, start, end, expected in CRON:
+        schedule_id = f"t:{A}:sched:{uuid.uuid4()}"
+        handle = await client.create_schedule(
+            schedule_id,
+            Schedule(
+                action=ScheduleActionStartWorkflow(Tick.run, schedule_id, id=schedule_id, task_queue=QUEUE),
+                spec=ScheduleSpec(cron_expressions=[cron], time_zone_name=zone),
+                state=ScheduleState(paused=True),
+            ),
+        )
+        answer = await client.workflow_service.list_schedule_matching_times(
+            ListScheduleMatchingTimesRequest(
+                namespace=client.namespace, schedule_id=schedule_id, start_time=at(start), end_time=at(end)
+            )
+        )
+        assert [t.ToDatetime().strftime("%m-%d %H:%M") for t in answer.start_time] == expected, (cron, zone)
+        await handle.delete()
+
+
 async def replay(workflows: list[type], runs: list[WorkflowHistory]) -> None:
     """Every history, replayed through the recording codec: a nondeterminism, or a path without a tenant, raises."""
```

### Task 13: The schedules table and API, cron as Temporal reads it

**Commit:** `1f3c20f` (prototype `proto/2b3a-v2`); the replay's tree was identical: yes.

**Create:** `backend/migrations/versions/0029_schedules.py`, `backend/src/dewpoint/apps/api/routes/schedules.py`, `backend/src/dewpoint/apps/schedules.py`, `backend/src/dewpoint/core/models/schedules.py`, `backend/tests/apps/api/test_schedules_api.py`, `backend/tests/apps/test_schedules.py`, `backend/tests/core/requests/test_schedules_schema.py`

**Modify:** `backend/src/dewpoint/apps/api/main.py`, `backend/src/dewpoint/core/models/__init__.py`, `backend/tests/apps/worker/test_temporal_contract.py`

**What it does:**

`schedules` (0029) is the source of truth the dispatcher will keep Temporal in step with
(engine 2b spec §8.2): a cron or an interval, a time zone, a catch-up window, a mode, the
fixed input sealed under `schedule.input` with the schedule's id as context, a generation
every API change raises, the one the sync last completed, and a tombstone a deletion leaves
(its input cleared, its tenant, id, workflow and mode kept for a late tick). Under forced
row-level security; the API writes the wanted state, the dispatcher only what its sync
completed and what Temporal counts, and no role deletes a row.

The API: `trigger.manage` writes (create, update, delete), `workflow.view` reads, never with
the input. The timing is checked against Temporal's own reading of cron (the owner's ruling
9): five fields in exactly the forms the contract test pins, names in any case, Sunday as 0
or 7, and a day of the month with a day of the week refused, since Temporal requires both
where cron takes either; an interval of at least 60 s, an IANA time zone, a catch-up window
of 1 minute to 24 hours. The fixed input is checked against the active version when written
(the reserved names, the schema, a forged handle), and a workflow declaring a CSV can't be
scheduled (409 `csv_required`). Each write is audited, without the input.

**Later tasks refine this.** Task 16 refuses a PATCH's null except for `cron` and `every_s`.

- [ ] **Step 1: its tests alone, before its code.** Run: `uv run pytest -n 8 tests/apps/api/test_schedules_api.py tests/apps/test_schedules.py tests/apps/worker/test_temporal_contract.py tests/core/requests/test_schedules_schema.py`. Replay result (exit 1), shortened:

```
FAILED tests/apps/api/test_schedules_api.py::test_writing_a_schedule_needs_trigger_manage
FAILED tests/core/requests/test_schedules_schema.py::test_schedules_force_row_level_security
FAILED tests/core/requests/test_schedules_schema.py::test_a_schedule_is_seen_only_within_its_tenant
FAILED tests/apps/api/test_schedules_api.py::test_every_change_raises_the_generation
FAILED tests/core/requests/test_schedules_schema.py::test_the_database_keeps_a_schedules_shape[update schedules set catchup_window_s = 30 where id = :i]
FAILED tests/core/requests/test_schedules_schema.py::test_the_database_keeps_a_schedules_shape[update schedules set cron = null, every_s = 59 where id = :i]
FAILED tests/core/requests/test_schedules_schema.py::test_the_database_keeps_a_schedules_shape[update schedules set deleted_at = now() where id = :i]
FAILED tests/core/requests/test_schedules_schema.py::test_the_database_keeps_a_schedules_shape[update schedules set generation = 0 where id = :i]
FAILED tests/core/requests/test_schedules_schema.py::test_each_role_writes_only_its_part_and_none_deletes
FAILED tests/core/requests/test_schedules_schema.py::test_the_database_keeps_a_schedules_shape[update schedules set every_s = 3600 where id = :i]
FAILED tests/core/requests/test_schedules_schema.py::test_the_database_keeps_a_schedules_shape[update schedules set cron = null where id = :i]
FAILED tests/core/requests/test_schedules_schema.py::test_the_database_keeps_a_schedules_shape[update schedules set input = null where id = :i]
ERROR tests/apps/test_schedules.py - ImportError while importing test module ...
21 failed, 9 passed, 1 error in 32.35s
```

- [ ] **Step 2: its code, then the same tests.** Replay result (exit 0), shortened:

```
..................................................................       [100%]
66 passed in 36.38s
```

- [ ] **Step 3: commit.** `git cherry-pick --no-commit 1f3c20f && git commit -C 1f3c20f`

The diff:

```diff
diff --git a/backend/migrations/versions/0029_schedules.py b/backend/migrations/versions/0029_schedules.py
new file mode 100644
index 0000000..8f2c939
--- /dev/null
+++ b/backend/migrations/versions/0029_schedules.py
@@ -0,0 +1,68 @@
+# SPDX-License-Identifier: Apache-2.0
+"""schedules, the source of truth the dispatcher keeps Temporal in step with (engine 2b spec §8.2, §14): a cron or an
+interval, a time zone, a catch-up window, a mode and the fixed input sealed under `schedule.input`; a generation every
+API change raises and the one the sync last completed (by a read-back of its marker); a tombstone a deletion leaves, so
+a late tick still finds what it belonged to"""
+
+import sqlalchemy as sa
+from alembic import op
+from sqlalchemy.dialects import postgresql as pg
+
+revision = "0029"
+down_revision = "0028"
+branch_labels = None
+depends_on = None
+
+
+def upgrade() -> None:
+    op.create_table(
+        "schedules",
+        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
+        sa.Column("tenant_id", pg.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
+        sa.Column("workflow_id", pg.UUID(as_uuid=True), sa.ForeignKey("workflows.id"), nullable=False),
+        sa.Column("cron", sa.Text, nullable=True),
+        sa.Column("every_s", sa.Integer, nullable=True),
+        sa.Column("offset_s", sa.Integer, nullable=False, server_default="0"),
+        sa.Column("time_zone", sa.Text, nullable=False, server_default="UTC"),
+        sa.Column("catchup_window_s", sa.Integer, nullable=False, server_default="600"),
+        sa.Column("mode", sa.String(16), nullable=False),
+        sa.Column("input", sa.LargeBinary, nullable=True),  # cleared by a deletion
+        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.true()),
+        sa.Column("generation", sa.BigInteger, nullable=False, server_default="1"),
+        sa.Column("synced_generation", sa.BigInteger, nullable=False, server_default="0"),
+        sa.Column("misses", sa.BigInteger, nullable=False, server_default="0"),
+        sa.Column("misses_checked_at", sa.DateTime(timezone=True), nullable=True),
+        sa.Column("sync_error", sa.String(64), nullable=True),
+        sa.Column("sync_error_at", sa.DateTime(timezone=True), nullable=True),
+        sa.Column("created_by", pg.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
+        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
+        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
+        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
+        sa.CheckConstraint("(cron IS NULL) <> (every_s IS NULL)", name="schedules_timing"),
+        sa.CheckConstraint("every_s IS NULL OR every_s >= 60", name="schedules_interval"),
+        sa.CheckConstraint("offset_s >= 0 AND (every_s IS NULL OR offset_s < every_s)", name="schedules_offset"),
+        sa.CheckConstraint("catchup_window_s BETWEEN 60 AND 86400", name="schedules_catchup"),
+        sa.CheckConstraint("mode IN ('live', 'simulate')", name="schedules_mode"),
+        sa.CheckConstraint("(deleted_at IS NULL) = (input IS NOT NULL)", name="schedules_tombstone"),
+        sa.CheckConstraint("synced_generation <= generation", name="schedules_synced"),
+    )
+    op.create_index("schedules_workflow", "schedules", ["tenant_id", "workflow_id"])
+    for statement in (
+        "ALTER TABLE schedules ENABLE ROW LEVEL SECURITY",
+        "ALTER TABLE schedules FORCE ROW LEVEL SECURITY",
+        "CREATE POLICY schedules_scope ON schedules TO dewpoint_api, dewpoint_dispatch "
+        "USING (tenant_id = app_tenant_id()) WITH CHECK (tenant_id = app_tenant_id())",
+        # The API writes a schedule's wanted state; the dispatcher reads it, records what its sync completed and the
+        # misses Temporal counts, and its tick reads it. No role deletes one: a deletion is a tombstone.
+        "GRANT SELECT, INSERT ON schedules TO dewpoint_api",
+        "GRANT UPDATE (cron, every_s, offset_s, time_zone, catchup_window_s, mode, input, enabled, generation, "
+        "updated_at, deleted_at) ON schedules TO dewpoint_api",
+        "GRANT SELECT ON schedules TO dewpoint_dispatch",
+        "GRANT UPDATE (synced_generation, misses, misses_checked_at, sync_error, sync_error_at) ON schedules "
+        "TO dewpoint_dispatch",
+    ):
+        op.execute(statement)
+
+
+def downgrade() -> None:
+    op.drop_table("schedules")
diff --git a/backend/src/dewpoint/apps/api/main.py b/backend/src/dewpoint/apps/api/main.py
index 9729aae..18f9cc4 100644
--- a/backend/src/dewpoint/apps/api/main.py
+++ b/backend/src/dewpoint/apps/api/main.py
@@ -20,6 +20,7 @@ from dewpoint.apps.api.routes import (
     passkeys,
     run_requests,
     runs,
+    schedules,
     tenants,
     workflows,
 )
@@ -74,6 +75,7 @@ def create_app(settings: Settings | None = None) -> FastAPI:
         run_requests.router,
         csv_uploads.router,
         runs.router,
+        schedules.router,
     ):
         app.include_router(router)
     return app
diff --git a/backend/src/dewpoint/apps/api/routes/schedules.py b/backend/src/dewpoint/apps/api/routes/schedules.py
new file mode 100644
index 0000000..f6764b2
--- /dev/null
+++ b/backend/src/dewpoint/apps/api/routes/schedules.py
@@ -0,0 +1,130 @@
+# SPDX-License-Identifier: Apache-2.0
+"""Schedules (engine 2b spec §8.2): written with `trigger.manage`, read with `workflow.view`, never with their input.
+The API writes a schedule's wanted state and raises its generation; the dispatcher's sync keeps Temporal in step with
+it, so the API needs no Temporal client."""
+
+import uuid
+from typing import Any, Literal
+
+from fastapi import APIRouter, Depends, HTTPException, Response
+from pydantic import BaseModel, ConfigDict, Field
+from sqlalchemy import select
+from sqlalchemy.ext.asyncio import AsyncSession
+
+from dewpoint.apps import schedules
+from dewpoint.apps.api.routes.run_requests import get_keys, key_unusable
+from dewpoint.core.authz.permissions import P
+from dewpoint.core.crypto.keys import KeySource
+from dewpoint.core.http import TenantContext, get_db, require
+from dewpoint.core.models.schedules import Schedule
+
+router = APIRouter(prefix="/api/v1", tags=["schedules"])
+
+
+class ScheduleIn(BaseModel):
+    model_config = ConfigDict(extra="forbid")
+    cron: str | None = Field(default=None, max_length=120)
+    every_s: int | None = None
+    offset_s: int = 0
+    time_zone: str = Field(default="UTC", max_length=64)
+    catchup_window_s: int = schedules.CATCHUP_DEFAULT
+    mode: Literal["live", "simulate"] = "live"
+    input: dict[str, Any] = Field(default_factory=dict)
+    enabled: bool = True
+
+
+class SchedulePatch(BaseModel):
+    """Only the fields given change; `cron` or `every_s` given as null switches the timing's kind."""
+
+    model_config = ConfigDict(extra="forbid")
+    cron: str | None = Field(default=None, max_length=120)
+    every_s: int | None = None
+    offset_s: int | None = None
+    time_zone: str | None = Field(default=None, max_length=64)
+    catchup_window_s: int | None = None
+    mode: Literal["live", "simulate"] | None = None
+    input: dict[str, Any] | None = None
+    enabled: bool | None = None
+
+
+def _refused(e: schedules.ScheduleRefusedError) -> HTTPException:
+    return HTTPException(e.status, detail=e.detail)
+
+
+@router.post("/t/{tenant_id}/workflows/{workflow_id}/schedules", status_code=201)
+async def create_schedule(
+    workflow_id: uuid.UUID,
+    given: ScheduleIn,
+    ctx: TenantContext = Depends(require(P.TRIGGER_MANAGE)),
+    db: AsyncSession = Depends(get_db, scope="function"),
+    keys: KeySource = Depends(get_keys),
+) -> dict[str, object]:
+    try:
+        created = await schedules.create(
+            db, keys, tenant_id=ctx.tenant_id, actor_id=ctx.user.id, workflow_id=workflow_id,
+            timing={k: getattr(given, k) for k in schedules.TIMING}, mode=given.mode, input=given.input,
+            enabled=given.enabled,
+        )  # fmt: skip
+    except schedules.ScheduleRefusedError as e:
+        raise _refused(e) from None
+    except Exception as e:
+        raise key_unusable(e) from None
+    return schedules.body(created)
+
+
+@router.get("/t/{tenant_id}/workflows/{workflow_id}/schedules")
+async def list_schedules(
+    workflow_id: uuid.UUID,
+    ctx: TenantContext = Depends(require(P.WORKFLOW_VIEW)),
+    db: AsyncSession = Depends(get_db, scope="function"),
+) -> dict[str, object]:
+    found = await db.execute(
+        select(Schedule)
+        .where(Schedule.workflow_id == workflow_id, Schedule.deleted_at.is_(None))
+        .order_by(Schedule.created_at, Schedule.id)
+    )
+    return {"schedules": [schedules.body(s) for s in found.scalars()]}
+
+
+@router.get("/t/{tenant_id}/schedules/{schedule_id}")
+async def get_schedule(
+    schedule_id: uuid.UUID,
+    ctx: TenantContext = Depends(require(P.WORKFLOW_VIEW)),
+    db: AsyncSession = Depends(get_db, scope="function"),
+) -> dict[str, object]:
+    schedule = await db.get(Schedule, schedule_id)  # row-level security: the caller's tenant's only
+    if schedule is None or schedule.deleted_at is not None:
+        raise HTTPException(404, detail={"error": "not_found"})
+    return schedules.body(schedule)
+
+
+@router.patch("/t/{tenant_id}/schedules/{schedule_id}")
+async def update_schedule(
+    schedule_id: uuid.UUID,
+    given: SchedulePatch,
+    ctx: TenantContext = Depends(require(P.TRIGGER_MANAGE)),
+    db: AsyncSession = Depends(get_db, scope="function"),
+    keys: KeySource = Depends(get_keys),
+) -> dict[str, object]:
+    changes = {k: getattr(given, k) for k in given.model_fields_set}
+    try:
+        schedule = await schedules.found(db, schedule_id)
+        updated = await schedules.update(db, keys, actor_id=ctx.user.id, schedule=schedule, changes=changes)
+    except schedules.ScheduleRefusedError as e:
+        raise _refused(e) from None
+    except Exception as e:
+        raise key_unusable(e) from None
+    return schedules.body(updated)
+
+
+@router.delete("/t/{tenant_id}/schedules/{schedule_id}", status_code=204)
+async def delete_schedule(
+    schedule_id: uuid.UUID,
+    ctx: TenantContext = Depends(require(P.TRIGGER_MANAGE)),
+    db: AsyncSession = Depends(get_db, scope="function"),
+) -> Response:
+    try:
+        await schedules.delete(db, actor_id=ctx.user.id, schedule=await schedules.found(db, schedule_id))
+    except schedules.ScheduleRefusedError as e:
+        raise _refused(e) from None
+    return Response(status_code=204)
diff --git a/backend/src/dewpoint/apps/schedules.py b/backend/src/dewpoint/apps/schedules.py
new file mode 100644
index 0000000..680835b
--- /dev/null
+++ b/backend/src/dewpoint/apps/schedules.py
@@ -0,0 +1,265 @@
+# SPDX-License-Identifier: Apache-2.0
+"""Schedules (engine 2b spec §8.2): their timing, checked against Temporal's own reading.
+
+A cron expression is accepted only in the forms whose meaning `test_temporal_contract.py` pins on the dev server (the
+owner's ruling 9): five fields (minute, hour, day of the month, month, day of the week), each `*`, a number, a range,
+`*/step` or `a-b/step`, or a list of those; months and days of the week also by name, in any case, and Sunday as 0 or
+7. A day of the month and a day of the week restricted together is refused: Temporal requires both to match, where
+cron usually takes either, and Dewpoint never accepts an expression under a meaning of its own. A time zone's changes
+skip a local time that doesn't exist and fire a repeated one once, at its second occurrence (pinned too). An interval
+is at least 60 s, so with cron's minutes every tick's nominal time is its own (§8.2's tick key)."""
+
+import functools
+import json
+import re
+import uuid
+import zoneinfo
+from collections.abc import Mapping
+from typing import Any
+
+from sqlalchemy import func, select
+from sqlalchemy.ext.asyncio import AsyncSession
+
+from dewpoint.apps.inputs import FORGED, RESERVED_INPUT, reasons
+from dewpoint.core.audit import service as audit
+from dewpoint.core.claims.cipher import ClaimCipher
+from dewpoint.core.crypto.keys import KeySource
+from dewpoint.core.models.schedules import Schedule
+from dewpoint.core.models.workflows import Workflow, WorkflowVersion
+from dewpoint.engine.graph.csv import RESERVED, trigger_schema
+from dewpoint.engine.handles import contains_marker
+
+INPUT_PURPOSE = "schedule.input"  # the fixed input, sealed with the schedule's id as context
+TIMING = ("cron", "every_s", "offset_s", "time_zone", "catchup_window_s")
+MIN_INTERVAL = 60
+MAX_INTERVAL = 366 * 24 * 3600
+CATCHUP_MIN, CATCHUP_MAX, CATCHUP_DEFAULT = 60, 24 * 3600, 600  # §15: provisional
+TIMING_CODES = frozenset(
+    {"cron_fields", "cron_syntax", "cron_range", "cron_day_fields", "timing_missing", "timing_both",
+     "interval_too_short", "interval_too_long", "interval_offset", "time_zone_unknown", "catchup_window"}
+)  # fmt: skip
+
+_MONTHS = {m: i for i, m in enumerate(("JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC").split(), start=1)}
+_DAYS = {d: i for i, d in enumerate(("SUN MON TUE WED THU FRI SAT").split())}
+_NONE: dict[str, int] = {}
+_FIELDS: tuple[tuple[int, int, dict[str, int]], ...] = (
+    (0, 59, _NONE), (0, 23, _NONE), (1, 31, _NONE), (1, 12, _MONTHS), (0, 7, _DAYS)
+)  # min, max, names  # fmt: skip
+_ATOM = r"(?:[0-9]{1,2}|[A-Za-z]{3})"
+_PART = re.compile(
+    rf"(?:\*(?:/(?P<every>[0-9]{{1,2}}))?|(?P<a>{_ATOM})(?:-(?P<b>{_ATOM})(?:/(?P<step>[0-9]{{1,2}}))?)?)"
+)
+
+
+class _Bad(Exception):
+    def __init__(self, code: str) -> None:
+        self.code = code
+
+
+def _value(atom: str, low: int, high: int, names: dict[str, int]) -> int:
+    if atom.isdigit():
+        value = int(atom)
+    elif atom.upper() in names:
+        value = names[atom.upper()]
+    else:
+        raise _Bad("cron_syntax")
+    if not low <= value <= high:
+        raise _Bad("cron_range")
+    return value
+
+
+def _field(text: str, low: int, high: int, names: dict[str, int]) -> None:
+    for part in text.split(","):
+        found = _PART.fullmatch(part)
+        if found is None:
+            raise _Bad("cron_syntax")
+        step = found["every"] or found["step"]
+        if step is not None and int(step) == 0:
+            raise _Bad("cron_range")
+        if found["a"] is None:
+            continue  # `*`, `*/step`
+        a = _value(found["a"], low, high, names)
+        if found["b"] is not None and _value(found["b"], low, high, names) < a:
+            raise _Bad("cron_range")
+
+
+def cron_problems(cron: str) -> list[str]:
+    """Why `cron` isn't one of the forms Dewpoint accepts, as one code; empty when it is."""
+    fields = cron.split()
+    if len(fields) != 5:
+        return ["cron_fields"]
+    try:
+        for text, (low, high, names) in zip(fields, _FIELDS, strict=True):
+            _field(text, low, high, names)
+    except _Bad as bad:
+        return [bad.code]
+    if fields[2] != "*" and fields[4] != "*":
+        return ["cron_day_fields"]
+    return []
+
+
+@functools.cache
+def _zones() -> frozenset[str]:
+    return frozenset(zoneinfo.available_timezones() | {"UTC"})
+
+
+def timing_problems(
+    *, cron: str | None, every_s: int | None, offset_s: int, time_zone: str, catchup_s: int
+) -> list[dict[str, Any]]:
+    """What's wrong with a schedule's timing, each as its field and a code (`TIMING_CODES`)."""
+    problems: list[dict[str, Any]] = []
+    if cron is None and every_s is None:
+        problems.append({"field": "cron", "code": "timing_missing"})
+    elif cron is not None and every_s is not None:
+        problems.append({"field": "every_s", "code": "timing_both"})
+    elif cron is not None:
+        problems += [{"field": "cron", "code": code} for code in cron_problems(cron)]
+    elif every_s is not None:
+        if every_s < MIN_INTERVAL:
+            problems.append({"field": "every_s", "code": "interval_too_short"})
+        elif every_s > MAX_INTERVAL:
+            problems.append({"field": "every_s", "code": "interval_too_long"})
+        elif not 0 <= offset_s < every_s:
+            problems.append({"field": "offset_s", "code": "interval_offset"})
+    if time_zone not in _zones():
+        problems.append({"field": "time_zone", "code": "time_zone_unknown"})
+    if not CATCHUP_MIN <= catchup_s <= CATCHUP_MAX:
+        problems.append({"field": "catchup_window_s", "code": "catchup_window"})
+    return problems
+
+
+class ScheduleRefusedError(Exception):
+    """A schedule the API refuses to write: the HTTP status and the fixed detail to answer with."""
+
+    def __init__(self, status: int, detail: dict[str, Any]) -> None:
+        super().__init__(detail["error"])
+        self.status, self.detail = status, detail
+
+
+async def _active_version(s: AsyncSession, workflow_id: uuid.UUID) -> WorkflowVersion:
+    workflow = await s.get(Workflow, workflow_id)  # row-level security: the caller's tenant's only
+    if workflow is None:
+        raise ScheduleRefusedError(404, {"error": "not_found"})
+    version = await s.get(WorkflowVersion, workflow.active_version_id) if workflow.active_version_id else None
+    if version is None:
+        raise ScheduleRefusedError(409, {"error": "not_active"})
+    if (version.graph.get("settings") or {}).get("csv"):
+        raise ScheduleRefusedError(409, {"error": "csv_required"})  # its rows come from an upload only (§8.1)
+    return version
+
+
+def _checked_input(version: WorkflowVersion, value: Mapping[str, Any]) -> None:
+    """The fixed input against the active version, as admission checks a trigger: a tick checks it again."""
+    if any(name in value for name in RESERVED):
+        raise ScheduleRefusedError(422, {"error": "input_invalid", "messages": [RESERVED_INPUT]})
+    refused = reasons(trigger_schema(version.graph.get("settings") or {}), value)
+    if refused:
+        raise ScheduleRefusedError(422, {"error": "input_invalid", "messages": refused})
+    if contains_marker(value):
+        raise ScheduleRefusedError(422, {"error": "input_invalid", "messages": [FORGED]})
+
+
+def _checked_timing(timing: Mapping[str, Any]) -> None:
+    problems = timing_problems(cron=timing["cron"], every_s=timing["every_s"], offset_s=timing["offset_s"],
+                               time_zone=timing["time_zone"], catchup_s=timing["catchup_window_s"])  # fmt: skip
+    if problems:
+        raise ScheduleRefusedError(422, {"error": "schedule_invalid", "problems": problems})
+
+
+async def _sealed(keys: KeySource, tenant_id: uuid.UUID, schedule_id: uuid.UUID, value: Mapping[str, Any]) -> bytes:
+    plaintext = json.dumps(dict(value), sort_keys=True, ensure_ascii=False, allow_nan=False).encode()
+    return await ClaimCipher(keys, purpose=INPUT_PURPOSE).seal(str(tenant_id), str(schedule_id), plaintext)
+
+
+async def _audited(s: AsyncSession, action: str, actor_id: uuid.UUID, schedule: Schedule) -> None:
+    details = {"schedule_id": str(schedule.id), "workflow_id": str(schedule.workflow_id),
+               "generation": schedule.generation}  # fmt: skip
+    await audit.record(s, tenant_id=schedule.tenant_id, actor_id=actor_id, action=action, target_type="schedule",
+                       target_id=str(schedule.id), details=details)  # fmt: skip
+
+
+async def create(
+    s: AsyncSession, keys: KeySource, *, tenant_id: uuid.UUID, actor_id: uuid.UUID, workflow_id: uuid.UUID,
+    timing: Mapping[str, Any], mode: str, input: Mapping[str, Any], enabled: bool,
+) -> Schedule:  # fmt: skip
+    """A schedule of the workflow's active version, its timing and its fixed input checked, the input sealed."""
+    version = await _active_version(s, workflow_id)
+    _checked_timing(timing)
+    _checked_input(version, input)
+    schedule_id = uuid.uuid4()
+    schedule = Schedule(
+        id=schedule_id, tenant_id=tenant_id, workflow_id=workflow_id, mode=mode, enabled=enabled, generation=1,
+        synced_generation=0, input=await _sealed(keys, tenant_id, schedule_id, input), created_by=actor_id,
+        **{k: timing[k] for k in TIMING},
+    )  # fmt: skip
+    s.add(schedule)
+    await s.flush()
+    await _audited(s, "schedule.create", actor_id, schedule)
+    await s.refresh(schedule)
+    return schedule
+
+
+async def found(s: AsyncSession, schedule_id: uuid.UUID) -> Schedule:
+    """A schedule of the caller's tenant that isn't a tombstone, locked for the change the caller makes."""
+    schedule = (
+        await s.execute(
+            select(Schedule)
+            .where(Schedule.id == schedule_id, Schedule.deleted_at.is_(None))
+            .with_for_update()
+            .execution_options(populate_existing=True)
+        )
+    ).scalar_one_or_none()
+    if schedule is None:
+        raise ScheduleRefusedError(404, {"error": "not_found"})
+    return schedule
+
+
+async def update(
+    s: AsyncSession, keys: KeySource, *, actor_id: uuid.UUID, schedule: Schedule, changes: Mapping[str, Any]
+) -> Schedule:
+    """`changes` applied (the timing as a whole checked again, a new input against the active version), and the
+    generation raised, which the sync follows."""
+    timing = {k: changes.get(k, getattr(schedule, k)) for k in TIMING}
+    _checked_timing(timing)
+    if "input" in changes:
+        _checked_input(await _active_version(s, schedule.workflow_id), changes["input"])
+        schedule.input = await _sealed(keys, schedule.tenant_id, schedule.id, changes["input"])
+    for key in TIMING:
+        setattr(schedule, key, timing[key])
+    for key in ("mode", "enabled"):
+        if key in changes:
+            setattr(schedule, key, changes[key])
+    schedule.generation += 1
+    schedule.updated_at = func.now()
+    await s.flush()
+    await _audited(s, "schedule.update", actor_id, schedule)
+    await s.refresh(schedule)
+    return schedule
+
+
+async def delete(s: AsyncSession, *, actor_id: uuid.UUID, schedule: Schedule) -> None:
+    """A tombstone: its fixed input cleared, its generation raised for the sync to delete it from Temporal; its
+    tenant, id, workflow and mode kept, so a late tick still records `schedule_deleted`."""
+    schedule.input = None
+    schedule.deleted_at = func.now()
+    schedule.generation += 1
+    schedule.updated_at = func.now()
+    await s.flush()
+    await _audited(s, "schedule.delete", actor_id, schedule)
+
+
+def body(schedule: Schedule) -> dict[str, object]:
+    """A schedule as the API shows it: never its input."""
+    return {
+        "id": str(schedule.id),
+        "workflow_id": str(schedule.workflow_id),
+        **{k: getattr(schedule, k) for k in TIMING},
+        "mode": schedule.mode,
+        "enabled": schedule.enabled,
+        "generation": schedule.generation,
+        "synced_generation": schedule.synced_generation,
+        "misses": schedule.misses,
+        "sync_error": schedule.sync_error,
+        "created_at": schedule.created_at.isoformat(),
+        "updated_at": schedule.updated_at.isoformat(),
+    }
diff --git a/backend/src/dewpoint/core/models/__init__.py b/backend/src/dewpoint/core/models/__init__.py
index bc1699c..c7dd63c 100644
--- a/backend/src/dewpoint/core/models/__init__.py
+++ b/backend/src/dewpoint/core/models/__init__.py
@@ -8,6 +8,7 @@ from dewpoint.core.models import (
     plugins,
     requests,
     runs,
+    schedules,
     tenancy,
     uploads,
     workflows,
@@ -15,6 +16,6 @@ from dewpoint.core.models import (
 from dewpoint.core.models.base import Base
 
 __all__ = [
-    "Base", "audit", "claims", "connections", "identity", "keys", "plugins", "requests", "runs", "tenancy", "uploads",
-    "workflows",
+    "Base", "audit", "claims", "connections", "identity", "keys", "plugins", "requests", "runs", "schedules",
+    "tenancy", "uploads", "workflows",
 ]  # fmt: skip
diff --git a/backend/src/dewpoint/core/models/schedules.py b/backend/src/dewpoint/core/models/schedules.py
new file mode 100644
index 0000000..edc6079
--- /dev/null
+++ b/backend/src/dewpoint/core/models/schedules.py
@@ -0,0 +1,37 @@
+# SPDX-License-Identifier: Apache-2.0
+"""A schedule (engine 2b spec §8.2): the wanted state the API writes, the generation it raises with every change, the
+one the dispatcher's sync last completed, and the tombstone a deletion leaves."""
+
+import uuid
+from datetime import datetime
+
+from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, LargeBinary, String, Text, func
+from sqlalchemy.dialects.postgresql import UUID
+from sqlalchemy.orm import Mapped, mapped_column
+
+from dewpoint.core.models.base import Base
+
+
+class Schedule(Base):
+    __tablename__ = "schedules"
+    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
+    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"))
+    workflow_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("workflows.id"))
+    cron: Mapped[str | None] = mapped_column(Text)
+    every_s: Mapped[int | None] = mapped_column(Integer)
+    offset_s: Mapped[int] = mapped_column(Integer, default=0)
+    time_zone: Mapped[str] = mapped_column(Text, default="UTC")
+    catchup_window_s: Mapped[int] = mapped_column(Integer, default=600)
+    mode: Mapped[str] = mapped_column(String(16))
+    input: Mapped[bytes | None] = mapped_column(LargeBinary)
+    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
+    generation: Mapped[int] = mapped_column(BigInteger, default=1)
+    synced_generation: Mapped[int] = mapped_column(BigInteger, default=0)
+    misses: Mapped[int] = mapped_column(BigInteger, default=0)
+    misses_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
+    sync_error: Mapped[str | None] = mapped_column(String(64))
+    sync_error_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
+    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
+    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
+    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
+    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
diff --git a/backend/tests/apps/api/test_schedules_api.py b/backend/tests/apps/api/test_schedules_api.py
new file mode 100644
index 0000000..1a740fd
--- /dev/null
+++ b/backend/tests/apps/api/test_schedules_api.py
@@ -0,0 +1,163 @@
+# SPDX-License-Identifier: Apache-2.0
+"""Schedules through the API (engine 2b spec §8.2; the owner's ruling 9): `trigger.manage` (editors and above) writes
+them, `workflow.view` reads them. A schedule's timing is checked against Temporal's own reading of cron, its fixed input
+against the active version when written (a tick checks it again), and the input is sealed under `schedule.input`, with
+the schedule's id as context, and never shown. A workflow that declares a CSV can't be scheduled. Every change raises
+the schedule's generation, which the dispatcher's sync follows; deleting leaves a tombstone, so a late tick still finds
+what it belonged to."""
+
+import uuid
+from typing import Any
+
+import pytest
+from sqlalchemy import text
+
+from dewpoint.apps.inputs import RESERVED_INPUT
+from tests.apps.api.test_run_requests_api import as_role
+from tests.apps.test_admission import KEYS, TOKEN, published
+from tests.apps.test_admission_csv import GRAPH as CSV_GRAPH
+
+pytestmark = pytest.mark.usefixtures("development_deployment")
+BODY = {"cron": "0 9 * * 1-5", "time_zone": "Europe/Paris", "input": {"token": TOKEN, "site": "a"}}
+
+
+@pytest.fixture
+def keyed_app(app: Any) -> Any:
+    app.state.keys = KEYS
+    return app
+
+
+@pytest.fixture
+async def workflow(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings) -> Any:
+    return await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings)
+
+
+def schedules_url(ctx: Any, wf: uuid.UUID) -> str:
+    return f"/api/v1/t/{ctx.tenant_id}/workflows/{wf}/schedules"
+
+
+def schedule_url(ctx: Any, schedule_id: str) -> str:
+    return f"/api/v1/t/{ctx.tenant_id}/schedules/{schedule_id}"
+
+
+async def row(owner: Any, schedule_id: str) -> Any:
+    async with owner() as s:
+        return (await s.execute(text("select * from schedules where id = :i"), {"i": schedule_id})).mappings().one()
+
+
+async def audited(owner: Any, action: str) -> list[Any]:
+    async with owner() as s:
+        found = await s.execute(text("select details from audit_log where action = :a"), {"a": action})
+        return list(found.scalars())
+
+
+async def test_an_editor_schedules_a_workflow_its_input_sealed_and_never_shown(
+    keyed_app, workflow, owner_sessionmaker, api_settings
+) -> None:
+    ctx, wf = workflow
+    editor = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "editor")
+    answer = await editor.post(schedules_url(ctx, wf), json=BODY)
+    assert answer.status_code == 201, answer.text
+    body = answer.json()
+    assert {k: body[k] for k in ("cron", "every_s", "time_zone", "catchup_window_s", "mode", "enabled", "generation",
+                                 "synced_generation")} == {
+        "cron": "0 9 * * 1-5", "every_s": None, "time_zone": "Europe/Paris", "catchup_window_s": 600, "mode": "live",
+        "enabled": True, "generation": 1, "synced_generation": 0,
+    }  # fmt: skip
+    assert "input" not in body and TOKEN not in answer.text
+    stored = await row(owner_sessionmaker, body["id"])
+    assert TOKEN.encode() not in stored["input"] and stored["deleted_at"] is None
+    assert [d["schedule_id"] for d in await audited(owner_sessionmaker, "schedule.create")] == [body["id"]]
+    viewer = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "viewer")
+    listed = (await viewer.get(schedules_url(ctx, wf))).json()
+    assert [s["id"] for s in listed["schedules"]] == [body["id"]] and TOKEN not in str(listed)
+    assert (await viewer.get(schedule_url(ctx, body["id"]))).json()["id"] == body["id"]
+
+
+async def test_writing_a_schedule_needs_trigger_manage(keyed_app, workflow, owner_sessionmaker, api_settings) -> None:
+    ctx, wf = workflow
+    for role in ("operator", "viewer"):
+        client = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, role)
+        assert (await client.post(schedules_url(ctx, wf), json=BODY)).status_code == 403
+
+
+@pytest.mark.parametrize(
+    ("change", "problems"),
+    [
+        ({"cron": "0 9 13 * 5"}, [{"field": "cron", "code": "cron_day_fields"}]),
+        ({"cron": None, "every_s": 30}, [{"field": "every_s", "code": "interval_too_short"}]),
+        ({"time_zone": "Mars/Olympus"}, [{"field": "time_zone", "code": "time_zone_unknown"}]),
+        ({"catchup_window_s": 10}, [{"field": "catchup_window_s", "code": "catchup_window"}]),
+    ],
+)
+async def test_a_timing_temporal_wouldnt_read_as_written_is_refused(
+    keyed_app, workflow, owner_sessionmaker, api_settings, change: dict[str, Any], problems: list[Any]
+) -> None:
+    ctx, wf = workflow
+    editor = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "editor")
+    answer = await editor.post(schedules_url(ctx, wf), json=BODY | change)
+    assert (answer.status_code, answer.json()) == (422, {"error": "schedule_invalid", "problems": problems})
+
+
+@pytest.mark.parametrize(
+    ("given", "message"),
+    [
+        ({"token": 7}, None),
+        ({"token": TOKEN, "rows": []}, RESERVED_INPUT),
+    ],
+)
+async def test_an_input_the_active_version_refuses_is_refused(
+    keyed_app, workflow, owner_sessionmaker, api_settings, given: dict[str, Any], message: str | None
+) -> None:
+    ctx, wf = workflow
+    editor = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "editor")
+    answer = await editor.post(schedules_url(ctx, wf), json=BODY | {"input": given})
+    assert (answer.status_code, answer.json()["error"]) == (422, "input_invalid")
+    assert message is None or answer.json()["messages"] == [message]
+    assert "7" not in answer.json()["messages"][0].split("at ")[-1]
+
+
+async def test_what_cant_be_scheduled(
+    keyed_app, workflow, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings
+) -> None:
+    ctx, _ = workflow
+    editor = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "editor")
+    _, other = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings)
+    assert (await editor.post(schedules_url(ctx, other), json=BODY)).status_code == 404  # another tenant's
+    csv_ctx, csv_wf = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings, CSV_GRAPH)
+    csv_editor = await as_role(keyed_app, owner_sessionmaker, api_settings, csv_ctx, "editor")
+    answer = await csv_editor.post(schedules_url(csv_ctx, csv_wf), json=BODY)
+    assert (answer.status_code, answer.json()) == (409, {"error": "csv_required"})
+
+
+async def test_every_change_raises_the_generation(keyed_app, workflow, owner_sessionmaker, api_settings) -> None:
+    ctx, wf = workflow
+    editor = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "editor")
+    created = (await editor.post(schedules_url(ctx, wf), json=BODY)).json()
+    url = schedule_url(ctx, created["id"])
+    changed = await editor.patch(url, json={"cron": None, "every_s": 3600, "offset_s": 60})
+    assert changed.status_code == 200, changed.text
+    assert (changed.json()["cron"], changed.json()["every_s"], changed.json()["generation"]) == (None, 3600, 2)
+    disabled = (await editor.patch(url, json={"enabled": False})).json()
+    assert (disabled["enabled"], disabled["generation"]) == (False, 3)
+    before = (await row(owner_sessionmaker, created["id"]))["input"]
+    replaced = (await editor.patch(url, json={"input": {"token": "an0ther-t0ken", "site": "b"}})).json()
+    assert replaced["generation"] == 4 and (await row(owner_sessionmaker, created["id"]))["input"] != before
+    refused = await editor.patch(url, json={"cron": "@hourly", "every_s": None})
+    assert refused.status_code == 422 and (await row(owner_sessionmaker, created["id"]))["generation"] == 4
+
+
+async def test_deleting_leaves_a_tombstone(keyed_app, workflow, owner_sessionmaker, api_settings) -> None:
+    ctx, wf = workflow
+    editor = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "editor")
+    created = (await editor.post(schedules_url(ctx, wf), json=BODY)).json()
+    url = schedule_url(ctx, created["id"])
+    assert (await editor.delete(url)).status_code == 204
+    stone = await row(owner_sessionmaker, created["id"])
+    assert stone["deleted_at"] is not None and stone["input"] is None and stone["generation"] == 2
+    assert (stone["workflow_id"], stone["mode"]) == (wf, "live")  # what a late tick needs to record its outcome
+    assert (await editor.get(url)).status_code == 404
+    assert (await editor.patch(url, json={"enabled": True})).status_code == 404
+    assert (await editor.delete(url)).status_code == 404
+    assert (await editor.get(schedules_url(ctx, wf))).json()["schedules"] == []
+    assert [d["schedule_id"] for d in await audited(owner_sessionmaker, "schedule.delete")] == [created["id"]]
diff --git a/backend/tests/apps/test_schedules.py b/backend/tests/apps/test_schedules.py
new file mode 100644
index 0000000..cb1f343
--- /dev/null
+++ b/backend/tests/apps/test_schedules.py
@@ -0,0 +1,62 @@
+# SPDX-License-Identifier: Apache-2.0
+"""A schedule's timing (engine 2b spec §8.2; the owner's ruling 9): five-field cron in exactly the forms whose meaning
+`test_temporal_contract.py` pins as Temporal's own, an interval of at least 60 s, an IANA time zone and a catch-up
+window of 1 minute to 24 hours. A form Temporal reads otherwise than cron usually does, a day of the month and a day of
+the week restricted together, is refused rather than accepted under a meaning of Dewpoint's."""
+
+import pytest
+
+from dewpoint.apps.schedules import TIMING_CODES, cron_problems, timing_problems
+from tests.apps.worker.test_temporal_contract import CRON
+
+
+@pytest.mark.parametrize("cron", sorted({c for c, *_ in CRON} - {"0 9 13 * 5"}))
+def test_every_pinned_form_but_both_day_fields_is_accepted(cron: str) -> None:
+    assert cron_problems(cron) == []
+
+
+@pytest.mark.parametrize(
+    ("cron", "code"),
+    [
+        ("0 9 13 * 5", "cron_day_fields"),  # Temporal: both must match; cron: either
+        ("0 9 */2 * MON", "cron_day_fields"),
+        ("0 9 * *", "cron_fields"), ("0 0 9 * * *", "cron_fields"), ("@daily", "cron_fields"), ("", "cron_fields"),
+        ("0 9 L * *", "cron_syntax"), ("0 9 ? * *", "cron_syntax"), ("0 9 * * 5#2", "cron_syntax"),
+        ("0 9 15W * *", "cron_syntax"), ("H 9 * * *", "cron_syntax"), ("0 9 * JAN-MON *", "cron_syntax"),
+        ("0 0 JAN * *", "cron_syntax"), ("5/15 * * * *", "cron_syntax"), ("0,,5 * * * *", "cron_syntax"),
+        ("60 * * * *", "cron_range"), ("0 24 * * *", "cron_range"), ("0 0 0 * *", "cron_range"),
+        ("0 0 * 13 *", "cron_range"), ("0 0 * * 8", "cron_range"), ("*/0 * * * *", "cron_range"),
+        ("5-1 * * * *", "cron_range"), ("0 9-17/0 * * *", "cron_range"),
+    ],
+)  # fmt: skip
+def test_any_other_form_is_refused_with_its_code(cron: str, code: str) -> None:
+    assert cron_problems(cron) == [code]
+    assert code in TIMING_CODES
+
+
+def test_a_timing_is_a_cron_or_an_interval_in_a_known_zone_with_a_bounded_catch_up() -> None:
+    assert timing_problems(cron="0 9 * * 1-5", every_s=None, offset_s=0, time_zone="Europe/Paris", catchup_s=600) == []
+    assert timing_problems(cron=None, every_s=60, offset_s=59, time_zone="UTC", catchup_s=60) == []
+    assert timing_problems(cron=None, every_s=None, offset_s=0, time_zone="UTC", catchup_s=600) == [
+        {"field": "cron", "code": "timing_missing"}
+    ]
+    assert timing_problems(cron="* * * * *", every_s=60, offset_s=0, time_zone="UTC", catchup_s=600) == [
+        {"field": "every_s", "code": "timing_both"}
+    ]
+    assert timing_problems(cron=None, every_s=59, offset_s=0, time_zone="UTC", catchup_s=600) == [
+        {"field": "every_s", "code": "interval_too_short"}
+    ]
+    assert timing_problems(cron=None, every_s=60, offset_s=60, time_zone="UTC", catchup_s=600) == [
+        {"field": "offset_s", "code": "interval_offset"}
+    ]
+    for zone in ("Mars/Olympus", "../etc/passwd", "europe/paris", ""):
+        assert timing_problems(cron="0 9 * * *", every_s=None, offset_s=0, time_zone=zone, catchup_s=600) == [
+            {"field": "time_zone", "code": "time_zone_unknown"}
+        ]
+    for catchup in (59, 86_401):
+        assert timing_problems(cron="0 9 * * *", every_s=None, offset_s=0, time_zone="UTC", catchup_s=catchup) == [
+            {"field": "catchup_window_s", "code": "catchup_window"}
+        ]
+    assert timing_problems(cron="0 9 13 * 5", every_s=None, offset_s=0, time_zone="UTC", catchup_s=600) == [
+        {"field": "cron", "code": "cron_day_fields"}
+    ]
diff --git a/backend/tests/apps/worker/test_temporal_contract.py b/backend/tests/apps/worker/test_temporal_contract.py
index 1b995c3..1ecf58b 100644
--- a/backend/tests/apps/worker/test_temporal_contract.py
+++ b/backend/tests/apps/worker/test_temporal_contract.py
@@ -426,6 +426,8 @@ CRON = [
     ("0 12 * * SUN", "UTC", "2026-06-01", "2026-06-20", ["06-07 12:00", "06-14 12:00"]),
     ("0 12 * * 0", "UTC", "2026-06-01", "2026-06-20", ["06-07 12:00", "06-14 12:00"]),
     ("0 12 * * 7", "UTC", "2026-06-01", "2026-06-20", ["06-07 12:00", "06-14 12:00"]),
+    ("0 12 * * sun", "UTC", "2026-06-01", "2026-06-20", ["06-07 12:00", "06-14 12:00"]),  # names in any case
+    ("0 9 * * MON-FRI", "UTC", "2026-06-05", "2026-06-10", ["06-05 09:00", "06-08 09:00", "06-09 09:00"]),
     ("0 9-17/4 * * *", "UTC", "2026-06-01", "2026-06-02", ["06-01 09:00", "06-01 13:00", "06-01 17:00"]),
     ("5 4 31 * *", "UTC", "2026-01-01", "2026-12-31",
      ["01-31 04:05", "03-31 04:05", "05-31 04:05", "07-31 04:05", "08-31 04:05", "10-31 04:05"]),
diff --git a/backend/tests/core/requests/test_schedules_schema.py b/backend/tests/core/requests/test_schedules_schema.py
new file mode 100644
index 0000000..7fb09bf
--- /dev/null
+++ b/backend/tests/core/requests/test_schedules_schema.py
@@ -0,0 +1,98 @@
+# SPDX-License-Identifier: Apache-2.0
+"""Schedules' table (engine 2b spec §8.2, §14): under forced row-level security, the API's and the dispatcher's within
+their tenant. The API writes the wanted state and never deletes (a deletion is a tombstone); the dispatcher writes only
+what its sync completed and what Temporal counts. The database keeps a schedule's shape: a cron or an interval, at least
+60 s, a bounded catch-up, an input until it's a tombstone, and a synced generation never past its generation."""
+
+import uuid
+from typing import Any
+
+import pytest
+from sqlalchemy import text
+from sqlalchemy.exc import DBAPIError, IntegrityError
+
+from dewpoint.core.auth.users import create_user
+from dewpoint.core.db import tenant_scope
+from tests.apps.api.helpers import PW
+from tests.support.workflows import seed_workflow
+
+INSERT = text(
+    "insert into schedules (id, tenant_id, workflow_id, cron, mode, input, created_by) "
+    "values (:id, :t, :w, '0 9 * * *', 'live', '\\x01', :u)"
+)
+
+
+async def schedule(api: Any, owner: Any) -> tuple[uuid.UUID, uuid.UUID]:
+    tenant, wf, _ = await seed_workflow(owner)
+    async with owner() as s, s.begin():
+        user = (await create_user(s, email=f"{uuid.uuid4().hex[:8]}@corp.test", password=PW)).id
+    schedule_id = uuid.uuid4()
+    async with api() as s, s.begin():
+        await tenant_scope(s, tenant)
+        await s.execute(INSERT, {"id": schedule_id, "t": tenant, "w": wf, "u": user})
+    return tenant, schedule_id
+
+
+async def change(maker: Any, tenant: uuid.UUID, statement: str, schedule_id: uuid.UUID) -> None:
+    async with maker() as s, s.begin():
+        await tenant_scope(s, tenant)
+        await s.execute(text(statement), {"i": schedule_id})
+
+
+async def test_schedules_force_row_level_security(owner_sessionmaker) -> None:
+    async with owner_sessionmaker() as s:
+        query = text("select relrowsecurity, relforcerowsecurity from pg_class where relname = 'schedules'")
+        assert tuple((await s.execute(query)).one()) == (True, True)
+
+
+async def test_a_schedule_is_seen_only_within_its_tenant(
+    api_sessionmaker, dispatch_sessionmaker, owner_sessionmaker
+) -> None:
+    tenant, schedule_id = await schedule(api_sessionmaker, owner_sessionmaker)
+    other, _ = await schedule(api_sessionmaker, owner_sessionmaker)
+    for maker in (api_sessionmaker, dispatch_sessionmaker):
+        for scope, seen in ((tenant, 1), (other, 0)):
+            async with maker() as s, s.begin():
+                await tenant_scope(s, scope)
+                found = await s.execute(text("select count(*) from schedules where id = :i"), {"i": schedule_id})
+                assert found.scalar_one() == seen
+
+
+async def test_each_role_writes_only_its_part_and_none_deletes(
+    api_sessionmaker, dispatch_sessionmaker, owner_sessionmaker
+) -> None:
+    tenant, schedule_id = await schedule(api_sessionmaker, owner_sessionmaker)
+    await change(api_sessionmaker, tenant, "update schedules set enabled = false, generation = 2 where id = :i",
+                 schedule_id)  # fmt: skip
+    await change(dispatch_sessionmaker, tenant, "update schedules set synced_generation = 2, misses = 1 where id = :i",
+                 schedule_id)  # fmt: skip
+    for maker, statement in (
+        (dispatch_sessionmaker, "update schedules set cron = '* * * * *' where id = :i"),
+        (dispatch_sessionmaker, "update schedules set input = null where id = :i"),
+        (api_sessionmaker, "update schedules set synced_generation = 1 where id = :i"),
+        (api_sessionmaker, "delete from schedules where id = :i"),
+        (dispatch_sessionmaker, "delete from schedules where id = :i"),
+    ):
+        with pytest.raises(DBAPIError, match="permission denied"):
+            await change(maker, tenant, statement, schedule_id)
+
+
+@pytest.mark.parametrize(
+    "statement",
+    [
+        "update schedules set every_s = 3600 where id = :i",  # a cron and an interval
+        "update schedules set cron = null where id = :i",  # neither
+        "update schedules set cron = null, every_s = 59 where id = :i",
+        "update schedules set catchup_window_s = 30 where id = :i",
+        "update schedules set input = null where id = :i",  # cleared without a tombstone
+        "update schedules set deleted_at = now() where id = :i",  # a tombstone keeping its input
+        "update schedules set generation = 0 where id = :i",  # its synced generation (1, set first) past it
+    ],
+)
+async def test_the_database_keeps_a_schedules_shape(api_sessionmaker, owner_sessionmaker, statement) -> None:
+    tenant, schedule_id = await schedule(api_sessionmaker, owner_sessionmaker)
+    if "generation = 0" in statement:
+        await change(owner_sessionmaker, tenant, "update schedules set synced_generation = 1 where id = :i",
+                     schedule_id)  # fmt: skip
+    with pytest.raises(IntegrityError):
+        await change(api_sessionmaker, tenant, statement, schedule_id)
```

### Task 14: ScheduleTick and its activity, in the dispatcher's own admission worker

**Commit:** `83b90ed` (prototype `proto/2b3a-v2`); the replay's tree was identical: yes.

**Create:** `backend/src/dewpoint/apps/dispatcher/tick.py`, `backend/src/dewpoint/apps/dispatcher/tick_workflow.py`, `backend/tests/apps/dispatcher/histories/__init__.py`, `backend/tests/apps/dispatcher/histories/record.py`, `backend/tests/apps/dispatcher/histories/schedule_tick.json`, `backend/tests/apps/dispatcher/test_schedule_tick.py`, `backend/tests/apps/dispatcher/test_schedule_tick_replay.py`, `backend/tests/apps/dispatcher/test_schedule_tick_server.py`

**Modify:** `backend/src/dewpoint/apps/admission.py`, `backend/src/dewpoint/apps/dispatcher/main.py`, `backend/src/dewpoint/engine/runtime/ids.py`, `backend/tests/engine/runtime/test_ids.py`

**What it does:**

`ScheduleTick` (engine 2b spec §8.2) is the one-activity workflow a Temporal Schedule's
action starts with the schedule's id: it reads `TemporalScheduledStartTime` once, builds the
tick key `sched:<schedule_id>:<nominal time>` (UTC, whole seconds) and passes it to its
activity, retried without limit (a platform-wide failure waits, §2.5). It runs in the
dispatcher process on `dewpoint-admission`, an unversioned worker outside the engine's
Worker Deployment; a replay test pins its contract against a recorded history, whatever
`ENGINE_ABI` is.

The activity takes its authority from its workflow's own id only (the owner's ruling 10):
the tenant and the schedule parsed with the codec's grammar, an argument naming another
schedule refused, the row read by both in that tenant's scope (another tenant's schedule
isn't there). In one transaction under the tick key, so every retry finds what the first
recorded: an enabled schedule's tick is admitted as a durable source; a schedule disabled
before its pause reached Temporal, or deleted (its tombstone), gives a `refused` request
(`schedule_paused`, `schedule_deleted`, through `admission.record_refused`); an `erasing`
tenant's tick is an audited skip. A tick still unadmitted 10 minutes after its time alerts.

**Later tasks refine this.** Task 16 makes a tick take its workflow's admission lock, shared, then its schedule's row,
exclusively, until it commits, and names the schedule in its request's audit entry.

- [ ] **Step 1: its tests alone, before its code.** Run: `uv run pytest -n 8 tests/apps/dispatcher/test_schedule_tick.py tests/apps/dispatcher/test_schedule_tick_replay.py tests/apps/dispatcher/test_schedule_tick_server.py tests/engine/runtime/test_ids.py`. Replay result (exit 1), shortened:

```
Hint: make sure your test modules/packages have valid Python names.
Traceback:
<python>/lib/python3.14/importlib/__init__.py:88: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
tests/engine/runtime/test_ids.py:8: in <module>
    from dewpoint.engine.runtime.ids import (
E   ImportError: cannot import name 'schedule_of' from 'dewpoint.engine.runtime.ids' (<replay>/backend/src/dewpoint/engine/runtime/ids.py)
=========================== short test summary info ============================
ERROR tests/apps/dispatcher/test_schedule_tick.py - ImportError while importi...
ERROR tests/apps/dispatcher/test_schedule_tick_replay.py - ImportError while ...
ERROR tests/apps/dispatcher/test_schedule_tick_server.py - ImportError while ...
ERROR tests/engine/runtime/test_ids.py - ImportError while importing test mod...
4 errors in 4.78s
```

- [ ] **Step 2: its code, then the same tests.** Replay result (exit 0), shortened:

```
................................................                         [100%]
48 passed in 13.72s
```

- [ ] **Step 3: commit.** `git cherry-pick --no-commit 83b90ed && git commit -C 83b90ed`

The diff:

```diff
diff --git a/backend/src/dewpoint/apps/admission.py b/backend/src/dewpoint/apps/admission.py
index ee822a5..ca45455 100644
--- a/backend/src/dewpoint/apps/admission.py
+++ b/backend/src/dewpoint/apps/admission.py
@@ -222,6 +222,24 @@ async def admit_request(
     return admitted
 
 
+async def record_refused(
+    s: AsyncSession, keys: KeySource, *, tenant_id: uuid.UUID, workflow_id: uuid.UUID, source: str, mode: str,
+    idempotency_key: str, reason: str, messages: list[str],
+) -> RunRequest:  # fmt: skip
+    """A durable source's refusal decided before admission, a paused or deleted schedule's tick (§8.2): a `refused`
+    request under its key, frozen like any, never lost; an exact retry finds it. Raises IdempotencyConflictError when
+    the key holds another request."""
+    if source not in DURABLE:
+        raise ValueError(f"only a durable source's refusal is recorded: {source}")
+    await tenant_scope(s, tenant_id)
+    fields: dict[str, Any] = {"source": source, "workflow_id": workflow_id, "mode": mode, "input": {}}
+    existing = await _by_key(s, idempotency_key)
+    if existing is not None:
+        return (await _retry(keys, tenant_id, existing, fields)).request
+    refused = _Refused(reason, messages)
+    return (await _insert(s, keys, tenant_id, uuid.uuid4(), None, idempotency_key, fields, None, None, refused)).request
+
+
 async def admitted_under(
     s: AsyncSession, keys: KeySource, *, tenant_id: uuid.UUID, idempotency_key: str, source: str,
     workflow_id: uuid.UUID, mode: str, rerun: Rerun, actor_id: uuid.UUID | None = None,
diff --git a/backend/src/dewpoint/apps/dispatcher/main.py b/backend/src/dewpoint/apps/dispatcher/main.py
index 639e3cb..1b15d69 100644
--- a/backend/src/dewpoint/apps/dispatcher/main.py
+++ b/backend/src/dewpoint/apps/dispatcher/main.py
@@ -12,12 +12,15 @@ import structlog
 from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
 from temporalio.client import Client
 from temporalio.service import RPCError, RPCStatusCode
+from temporalio.worker import Worker
 
 from dewpoint.apps.codec import KeyringKeys, data_converter
 from dewpoint.apps.dispatcher.cancels import send_cancels
 from dewpoint.apps.dispatcher.dispatch import Rotation, dispatch_once
 from dewpoint.apps.dispatcher.observe import observe, report
 from dewpoint.apps.dispatcher.reconcile import Leader, reconcile_once
+from dewpoint.apps.dispatcher.tick import ADMISSION_QUEUE, Ticker
+from dewpoint.apps.dispatcher.tick_workflow import ScheduleTick
 from dewpoint.apps.environment import verify_environment
 from dewpoint.apps.worker.deployment import describe, this_build
 from dewpoint.core.config import Settings
@@ -74,6 +77,14 @@ async def serve(one: Callable[[], Awaitable[None]], *, cycles: int | None = None
         await asyncio.sleep(CYCLE_S)
 
 
+def admission_worker(client: Client, sessionmaker: async_sessionmaker[AsyncSession], keys: KeySource) -> Worker:
+    """The dispatcher's own worker for `ScheduleTick` (engine 2b spec §8.2): `dewpoint-admission`, unversioned, outside
+    the engine's Worker Deployment, admitting each tick as the dispatch role."""
+    return Worker(
+        client, task_queue=ADMISSION_QUEUE, workflows=[ScheduleTick], activities=[Ticker(sessionmaker, keys).tick]
+    )
+
+
 async def run(settings: Settings) -> None:
     """Raises EnvironmentNotRecordedError or EnvironmentMismatchError before connecting to Temporal."""
     engine = make_engine(settings.database_url)
@@ -94,7 +105,10 @@ async def run(settings: Settings) -> None:
                         rotation=rotation)  # fmt: skip
 
         try:
-            await serve(one)
+            async with admission_worker(
+                client, sessionmaker, keys
+            ):  # ends the process if it fails: Compose restarts it
+                await serve(one)
         finally:
             await leader.close()
     finally:
diff --git a/backend/src/dewpoint/apps/dispatcher/tick.py b/backend/src/dewpoint/apps/dispatcher/tick.py
new file mode 100644
index 0000000..f5d0b11
--- /dev/null
+++ b/backend/src/dewpoint/apps/dispatcher/tick.py
@@ -0,0 +1,129 @@
+# SPDX-License-Identifier: Apache-2.0
+"""A schedule's tick, admitted (engine 2b spec §8.2): the activity of `ScheduleTick`, in the dispatcher process, as the
+dispatch role. Its authority comes from its own workflow id only (the owner's ruling 10): the tenant and the schedule
+are parsed from it with the codec's grammar, the argument must name the same schedule, and the row is read by both, in
+that tenant's scope.
+
+In one transaction, under the tick key `sched:<schedule_id>:<nominal time>`, so every retry finds what the first
+recorded: an enabled schedule's tick is admitted as any durable source is (queued, or a `refused` request with
+admission's reason); one whose schedule was disabled before its pause reached Temporal, or deleted (its tombstone), is a
+`refused` request (`schedule_paused`, `schedule_deleted`); an `erasing` tenant's is an audited skip, never a request.
+A platform-wide failure (the database, a key) raises, and the workflow retries it without limit (§2.5): a tick still
+unadmitted 10 minutes after its time alerts."""
+
+import json
+import uuid
+from dataclasses import dataclass
+from datetime import UTC, datetime, timedelta
+
+import structlog
+from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
+from temporalio import activity
+from temporalio.exceptions import ApplicationError
+
+from dewpoint.apps import admission, schedules
+from dewpoint.core.audit import service as audit
+from dewpoint.core.claims.cipher import ClaimCipher
+from dewpoint.core.crypto.keys import KeySource
+from dewpoint.core.db import tenant_scope
+from dewpoint.core.models.requests import RunRequest
+from dewpoint.core.models.schedules import Schedule
+from dewpoint.core.models.tenancy import Tenant
+from dewpoint.engine.runtime.ids import schedule_of
+
+log = structlog.get_logger("dewpoint.dispatcher.tick")
+ADMISSION_QUEUE = "dewpoint-admission"  # unversioned, outside the engine's Worker Deployment (engine-core §11.11)
+TICK = "schedule.tick"
+SCHEDULE_PAUSED = "schedule_paused"
+SCHEDULE_DELETED = "schedule_deleted"
+LATE = timedelta(minutes=10)  # §15: provisional
+TICK_IDENTITY = "tick_identity"
+SCHEDULE_UNKNOWN = "schedule_unknown"
+
+
+@dataclass(frozen=True)
+class TickInput:
+    schedule_id: str  # the action's argument, which must name the schedule the workflow id does
+    key: str  # `sched:<schedule_id>:<nominal time>`
+    nominal: str  # the nominal time, UTC, whole seconds: `2026-10-04T09:00:00Z`
+
+
+class ScheduleUnknownError(Exception):
+    """A tick's workflow id names no schedule of its tenant, not even a tombstone: nothing to record it against."""
+
+
+def tick_key(schedule_id: str, nominal: datetime) -> tuple[str, str]:
+    """The tick's key and its nominal time, normalized to UTC at Temporal's precision (whole seconds, §11.1)."""
+    stamp = nominal.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
+    return f"sched:{schedule_id}:{stamp}", stamp
+
+
+def _outcome(request: RunRequest) -> str:
+    return f"refused:{request.reason}" if request.status == "refused" else request.status
+
+
+async def admit_tick(
+    s: AsyncSession, keys: KeySource, *, tenant_id: uuid.UUID, schedule_id: uuid.UUID, key: str
+) -> str:
+    """The tick's outcome, recorded in the caller's transaction: `queued`, `refused:<reason>`, `skipped:<reason>`, or
+    `recorded` when its key already holds another outcome of this tick (it was paused then, enabled since)."""
+    await tenant_scope(s, tenant_id)
+    schedule = await s.get(Schedule, schedule_id, populate_existing=True)  # row-level security: that tenant's only
+    if schedule is None:
+        raise ScheduleUnknownError(str(schedule_id))
+    tenant = await s.get(Tenant, tenant_id, populate_existing=True)
+    if tenant is None or tenant.status == "erasing":
+        details: dict[str, object] = {"schedule_id": str(schedule_id), "tick": key, "reason": admission.TENANT_ERASING}
+        await audit.record(s, tenant_id=tenant_id, actor_id=None, action="schedule.tick_skipped",
+                           target_type="schedule", target_id=str(schedule_id), details=details)  # fmt: skip
+        return f"skipped:{admission.TENANT_ERASING}"
+    try:
+        if schedule.deleted_at is not None or not schedule.enabled or schedule.input is None:
+            reason, said = (
+                (SCHEDULE_DELETED, "The schedule was deleted.") if schedule.deleted_at is not None
+                else (SCHEDULE_PAUSED, "The schedule is disabled.")
+            )  # fmt: skip
+            refused = await admission.record_refused(
+                s, keys, tenant_id=tenant_id, workflow_id=schedule.workflow_id, source="schedule", mode=schedule.mode,
+                idempotency_key=key, reason=reason, messages=[said],
+            )  # fmt: skip
+            return _outcome(refused)
+        cipher = ClaimCipher(keys, purpose=schedules.INPUT_PURPOSE)
+        given = json.loads(await cipher.open(str(tenant_id), str(schedule_id), schedule.input))
+        admitted = await admission.admit_request(
+            s, keys, tenant_id=tenant_id, workflow_id=schedule.workflow_id, source="schedule", actor_id=None,
+            mode=schedule.mode, idempotency_key=key, input=given,
+        )  # fmt: skip
+    except admission.IdempotencyConflictError:
+        return "recorded"
+    return _outcome(admitted.request)
+
+
+class Ticker:
+    """`schedule.tick`, bound to the dispatcher's database and keys."""
+
+    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession], keys: KeySource) -> None:
+        self.sessionmaker, self.keys = sessionmaker, keys
+
+    @activity.defn(name=TICK)
+    async def tick(self, given: TickInput) -> str:
+        named = schedule_of(activity.info().workflow_id or "")
+        if named is None or named[1] != given.schedule_id or tick_key(named[1], _parsed(given.nominal))[0] != given.key:
+            raise ApplicationError("A tick whose workflow id names another schedule.", type=TICK_IDENTITY,
+                                   non_retryable=True)  # fmt: skip
+        tenant_id, schedule_id = (uuid.UUID(part) for part in named)
+        try:
+            async with self.sessionmaker() as s, s.begin():
+                return await admit_tick(s, self.keys, tenant_id=tenant_id, schedule_id=schedule_id, key=given.key)
+        except ScheduleUnknownError:
+            raise ApplicationError("A tick of no schedule of its tenant.", type=SCHEDULE_UNKNOWN,
+                                   non_retryable=True) from None  # fmt: skip
+        except Exception as e:
+            if datetime.now(UTC) - _parsed(given.nominal) > LATE:
+                log.error("schedule_tick_late", schedule_id=str(schedule_id), attempt=activity.info().attempt,
+                          error=type(e).__name__)  # fmt: skip
+            raise
+
+
+def _parsed(stamp: str) -> datetime:
+    return datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
diff --git a/backend/src/dewpoint/apps/dispatcher/tick_workflow.py b/backend/src/dewpoint/apps/dispatcher/tick_workflow.py
new file mode 100644
index 0000000..67e2b2a
--- /dev/null
+++ b/backend/src/dewpoint/apps/dispatcher/tick_workflow.py
@@ -0,0 +1,38 @@
+# SPDX-License-Identifier: Apache-2.0
+"""`ScheduleTick` (engine 2b spec §8.2): the workflow a Temporal Schedule's action starts, with the schedule's id as its
+only argument. It reads its nominal time (`TemporalScheduledStartTime`, set by Temporal, deterministic under replay and
+catch-up, whole seconds) once, builds the tick key from it and passes both to its one activity, which it retries without
+limit: a platform-wide failure waits (§2.5), and only the activity's own non-retryable codes end a tick unadmitted.
+
+Unversioned and outside the engine's Worker Deployment: it holds no engine logic, and its replay test pins its short
+contract, whatever `ENGINE_ABI` is."""
+
+from datetime import timedelta
+
+from temporalio import workflow
+from temporalio.common import RetryPolicy, SearchAttributeKey
+from temporalio.exceptions import ApplicationError
+
+with workflow.unsafe.imports_passed_through():
+    from dewpoint.apps.dispatcher.tick import TICK, TickInput, tick_key
+
+SCHEDULED = SearchAttributeKey.for_datetime("TemporalScheduledStartTime")
+NO_NOMINAL_TIME = "tick_no_nominal_time"
+RETRY = RetryPolicy(
+    initial_interval=timedelta(seconds=1), backoff_coefficient=2.0, maximum_interval=timedelta(minutes=1)
+)
+
+
+@workflow.defn(name="ScheduleTick")
+class ScheduleTick:
+    @workflow.run
+    async def run(self, schedule_id: str) -> str:
+        nominal = workflow.info().typed_search_attributes.get(SCHEDULED)
+        if nominal is None:  # not started by a schedule: there's no tick to key
+            raise ApplicationError("A tick without its nominal time.", type=NO_NOMINAL_TIME, non_retryable=True)
+        key, stamp = tick_key(schedule_id, nominal)
+        outcome: str = await workflow.execute_activity(
+            TICK, TickInput(schedule_id, key, stamp), result_type=str, start_to_close_timeout=timedelta(seconds=30),
+            retry_policy=RETRY,
+        )  # fmt: skip
+        return outcome
diff --git a/backend/src/dewpoint/engine/runtime/ids.py b/backend/src/dewpoint/engine/runtime/ids.py
index 64e3f34..f1c836b 100644
--- a/backend/src/dewpoint/engine/runtime/ids.py
+++ b/backend/src/dewpoint/engine/runtime/ids.py
@@ -38,6 +38,17 @@ def batch_workflow_id(tenant_id: str, run_id: str, step_id: str, iteration_key:
     return f"{run_workflow_id(tenant_id, run_id)}/{step_id}/{iteration_key}/batch:{start}"
 
 
+def schedule_workflow_id(tenant_id: str, schedule_id: str) -> str:
+    """A schedule's Temporal Schedule id, and its action's workflow id: Temporal appends each firing's time to it."""
+    return f"t:{tenant_id}:sched:{schedule_id}"
+
+
+def schedule_of(workflow_id: str) -> tuple[str, str] | None:
+    """The tenant and the schedule a schedule's id, or one of its firings', names; None for any other string."""
+    m = _SCHEDULE.fullmatch(workflow_id)
+    return (m.group(1), m.group(2)) if m else None
+
+
 def tenant_of(workflow_id: str) -> str | None:
     """The tenant a server-built workflow id names, or None for any other string: nothing is inferred from it."""
     m = _RUN.fullmatch(workflow_id) or _SCHEDULE.fullmatch(workflow_id)
diff --git a/backend/tests/apps/dispatcher/histories/__init__.py b/backend/tests/apps/dispatcher/histories/__init__.py
new file mode 100644
index 0000000..e69de29
diff --git a/backend/tests/apps/dispatcher/histories/record.py b/backend/tests/apps/dispatcher/histories/record.py
new file mode 100644
index 0000000..916580a
--- /dev/null
+++ b/backend/tests/apps/dispatcher/histories/record.py
@@ -0,0 +1,71 @@
+# SPDX-License-Identifier: Apache-2.0
+"""Records `ScheduleTick`'s golden history (engine 2b spec §8.2): one backfilled firing on the CLI dev server, the
+activity a stub (replay never runs it), fixed ids, fixture keys. Recording again is a contract change: run it from
+`backend/` as `python -m tests.apps.dispatcher.histories.record` only with a new workflow type."""
+
+import asyncio
+import json
+from datetime import UTC, datetime, timedelta
+from pathlib import Path
+
+from temporalio import activity
+from temporalio.client import (
+    Schedule,
+    ScheduleActionStartWorkflow,
+    ScheduleBackfill,
+    ScheduleIntervalSpec,
+    ScheduleOverlapPolicy,
+    ScheduleSpec,
+    ScheduleState,
+)
+from temporalio.testing import WorkflowEnvironment
+from temporalio.worker import Worker
+
+from dewpoint.apps.dispatcher.tick import ADMISSION_QUEUE, TICK, TickInput
+from dewpoint.apps.dispatcher.tick_workflow import ScheduleTick
+from dewpoint.engine.runtime.ids import schedule_workflow_id
+from tests.support.keys import FIXTURE_CONVERTER
+
+TENANT, SCHEDULE = "00000000-0000-4000-8000-0000000000a1", "00000000-0000-4000-8000-0000000000b2"
+
+
+@activity.defn(name=TICK)
+async def stub(given: TickInput) -> str:
+    return "queued"
+
+
+async def main() -> dict[str, object]:
+    async with await WorkflowEnvironment.start_local(data_converter=FIXTURE_CONVERTER) as env:
+        client = env.client
+        schedule_id = schedule_workflow_id(TENANT, SCHEDULE)
+        handle = await client.create_schedule(
+            schedule_id,
+            Schedule(
+                action=ScheduleActionStartWorkflow(
+                    "ScheduleTick", SCHEDULE, id=schedule_id, task_queue=ADMISSION_QUEUE
+                ),
+                spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=timedelta(minutes=1))]),
+                state=ScheduleState(paused=True),
+            ),
+        )
+        at = datetime(2026, 10, 4, 9, 0, tzinfo=UTC)
+        async with Worker(client, task_queue=ADMISSION_QUEUE, workflows=[ScheduleTick], activities=[stub]):
+            await handle.backfill(
+                ScheduleBackfill(
+                    start_at=at - timedelta(seconds=30), end_at=at, overlap=ScheduleOverlapPolicy.ALLOW_ALL
+                )
+            )
+            for _ in range(100):
+                found = [w async for w in client.list_workflows("WorkflowType='ScheduleTick'")]
+                if found and found[0].status.name == "COMPLETED":
+                    break
+                await asyncio.sleep(0.2)
+            [w] = found
+            history = await client.get_workflow_handle(w.id, run_id=w.run_id).fetch_history()
+        return {"workflow_id": history.workflow_id, "history": json.loads(history.to_json())}
+
+
+if __name__ == "__main__":
+    out = Path("tests/apps/dispatcher/histories/schedule_tick.json")
+    out.write_text(json.dumps(asyncio.run(main()), indent=1))
+    print("recorded ->", out)
diff --git a/backend/tests/apps/dispatcher/histories/schedule_tick.json b/backend/tests/apps/dispatcher/histories/schedule_tick.json
new file mode 100644
index 0000000..cace88d
--- /dev/null
+++ b/backend/tests/apps/dispatcher/histories/schedule_tick.json
@@ -0,0 +1,259 @@
+{
+ "workflow_id": "t:00000000-0000-4000-8000-0000000000a1:sched:00000000-0000-4000-8000-0000000000b2-2026-10-04T09:00:00Z",
+ "history": {
+  "events": [
+   {
+    "eventId": "1",
+    "eventTime": "2026-10-04T06:42:39.505868Z",
+    "eventType": "EVENT_TYPE_WORKFLOW_EXECUTION_STARTED",
+    "taskId": "1048614",
+    "workflowExecutionStartedEventAttributes": {
+     "workflowType": {
+      "name": "ScheduleTick"
+     },
+     "taskQueue": {
+      "name": "dewpoint-admission",
+      "kind": "TASK_QUEUE_KIND_NORMAL"
+     },
+     "input": {
+      "payloads": [
+       {
+        "metadata": {
+         "dewpoint-key-version": "MQ==",
+         "dewpoint-tenant": "MDAwMDAwMDAtMDAwMC00MDAwLTgwMDAtMDAwMDAwMDAwMGEx",
+         "encoding": "YmluYXJ5L2Rld3BvaW50LXRlbmFudC12MQ=="
+        },
+        "data": "KLt8g8nMpCQijIA3VtAZKa0aqdEvPkqRbQn/HWFZbjKzeirdQy2a5Cds5s7LfmYauzfYlwaiweDLAEB13GGETF1Zc/r4VVPYpfnMu6BKgAT8D0Bi7+ptFwN75Xw="
+       }
+      ]
+     },
+     "workflowTaskTimeout": "10s",
+     "originalExecutionRunId": "01a105a6-7d11-7d3a-b6f6-95f3088c8375",
+     "identity": "temporal-scheduler-default-t:00000000-0000-4000-8000-0000000000a1:sched:00000000-0000-4000-8000-0000000000b2",
+     "firstExecutionRunId": "01a105a6-7d11-7d3a-b6f6-95f3088c8375",
+     "attempt": 1,
+     "firstWorkflowTaskBackoff": "0s",
+     "searchAttributes": {
+      "indexedFields": {
+       "TemporalScheduledStartTime": {
+        "metadata": {
+         "type": "RGF0ZXRpbWU=",
+         "encoding": "anNvbi9wbGFpbg=="
+        },
+        "data": "IjIwMjYtMTAtMDRUMDk6MDA6MDBaIg=="
+       },
+       "TemporalScheduledById": {
+        "metadata": {
+         "type": "S2V5d29yZA==",
+         "encoding": "anNvbi9wbGFpbg=="
+        },
+        "data": "InQ6MDAwMDAwMDAtMDAwMC00MDAwLTgwMDAtMDAwMDAwMDAwMGExOnNjaGVkOjAwMDAwMDAwLTAwMDAtNDAwMC04MDAwLTAwMDAwMDAwMDBiMiI="
+       }
+      }
+     },
+     "workflowId": "t:00000000-0000-4000-8000-0000000000a1:sched:00000000-0000-4000-8000-0000000000b2-2026-10-04T09:00:00Z",
+     "priority": {}
+    }
+   },
+   {
+    "eventId": "2",
+    "eventTime": "2026-10-04T06:42:39.505904Z",
+    "eventType": "EVENT_TYPE_WORKFLOW_TASK_SCHEDULED",
+    "taskId": "1048615",
+    "workflowTaskScheduledEventAttributes": {
+     "taskQueue": {
+      "name": "dewpoint-admission",
+      "kind": "TASK_QUEUE_KIND_NORMAL"
+     },
+     "startToCloseTimeout": "10s",
+     "attempt": 1
+    }
+   },
+   {
+    "eventId": "3",
+    "eventTime": "2026-10-04T06:42:39.506973Z",
+    "eventType": "EVENT_TYPE_WORKFLOW_TASK_STARTED",
+    "taskId": "1048620",
+    "workflowTaskStartedEventAttributes": {
+     "scheduledEventId": "2",
+     "identity": "20374@JNPR-MAC-P4K4HW",
+     "requestId": "4476938f-e792-4ad0-8de7-671cea558b5f",
+     "historySizeBytes": "873",
+     "workerVersion": {
+      "buildId": "0dc0b137dd34767821920cc66c1f547c"
+     }
+    }
+   },
+   {
+    "eventId": "4",
+    "eventTime": "2026-10-04T06:42:39.516035Z",
+    "eventType": "EVENT_TYPE_WORKFLOW_TASK_COMPLETED",
+    "taskId": "1048633",
+    "workflowTaskCompletedEventAttributes": {
+     "scheduledEventId": "2",
+     "startedEventId": "3",
+     "identity": "20374@JNPR-MAC-P4K4HW",
+     "workerVersion": {
+      "buildId": "0dc0b137dd34767821920cc66c1f547c"
+     },
+     "sdkMetadata": {
+      "coreUsedFlags": [
+       1,
+       3,
+       2
+      ],
+      "sdkName": "temporal-python",
+      "sdkVersion": "1.33.0"
+     },
+     "meteringMetadata": {}
+    }
+   },
+   {
+    "eventId": "5",
+    "eventTime": "2026-10-04T06:42:39.516096Z",
+    "eventType": "EVENT_TYPE_ACTIVITY_TASK_SCHEDULED",
+    "taskId": "1048634",
+    "activityTaskScheduledEventAttributes": {
+     "activityId": "1",
+     "activityType": {
+      "name": "schedule.tick"
+     },
+     "taskQueue": {
+      "name": "dewpoint-admission",
+      "kind": "TASK_QUEUE_KIND_NORMAL"
+     },
+     "header": {},
+     "input": {
+      "payloads": [
+       {
+        "metadata": {
+         "dewpoint-key-version": "MQ==",
+         "dewpoint-tenant": "MDAwMDAwMDAtMDAwMC00MDAwLTgwMDAtMDAwMDAwMDAwMGEx",
+         "encoding": "YmluYXJ5L2Rld3BvaW50LXRlbmFudC12MQ=="
+        },
+        "data": "gTpjTMTBggZ/g/PrQvEjLJeL7YQhq4XggkXfrhlM85xwTH6h8qrdTTX1iaSUQ8X1fxShVTHK0Uy9Z9zbPwNQZ1aBeEhhmJFW45oa1PB7BIuHLiPUFxsTPC6BMTCzz+Cjn2tTYBlOhgGqDSbceR2AYbLboRPHlA4zkf/qpjBgxBxQHeJVJdU3JOdi126Y8D0DNFwEEqGwOUmhU9OybvE3MOqUkhygM5T5lYgPaAnxSOSaBkjgOvyYgaL07BnLkp82P/pq89KJmWeyHI0N9ZeRrSKOiMma8Q=="
+       }
+      ]
+     },
+     "scheduleToCloseTimeout": "0s",
+     "scheduleToStartTimeout": "0s",
+     "startToCloseTimeout": "30s",
+     "heartbeatTimeout": "0s",
+     "workflowTaskCompletedEventId": "4",
+     "retryPolicy": {
+      "initialInterval": "1s",
+      "backoffCoefficient": 2.0,
+      "maximumInterval": "60s"
+     },
+     "useWorkflowBuildId": true,
+     "priority": {}
+    }
+   },
+   {
+    "eventId": "6",
+    "eventTime": "2026-10-04T06:42:39.516556Z",
+    "eventType": "EVENT_TYPE_ACTIVITY_TASK_STARTED",
+    "taskId": "1048638",
+    "activityTaskStartedEventAttributes": {
+     "scheduledEventId": "5",
+     "identity": "20374@JNPR-MAC-P4K4HW",
+     "requestId": "b988bbfa-aa57-41e7-bf76-3a8f9ebe925b",
+     "attempt": 1,
+     "workerVersion": {
+      "buildId": "0dc0b137dd34767821920cc66c1f547c"
+     }
+    }
+   },
+   {
+    "eventId": "7",
+    "eventTime": "2026-10-04T06:42:39.520797Z",
+    "eventType": "EVENT_TYPE_ACTIVITY_TASK_COMPLETED",
+    "taskId": "1048639",
+    "activityTaskCompletedEventAttributes": {
+     "result": {
+      "payloads": [
+       {
+        "metadata": {
+         "dewpoint-key-version": "MQ==",
+         "dewpoint-tenant": "MDAwMDAwMDAtMDAwMC00MDAwLTgwMDAtMDAwMDAwMDAwMGEx",
+         "encoding": "YmluYXJ5L2Rld3BvaW50LXRlbmFudC12MQ=="
+        },
+        "data": "wHjCOxTcxoyHpGkRv5ex6bSNa6pksSaBe/EfYu7H2N5I7zMMR2WKO4zcoVoTu+2gKt7EpEAxyINUyl+IdKQ="
+       }
+      ]
+     },
+     "scheduledEventId": "5",
+     "startedEventId": "6",
+     "identity": "20374@JNPR-MAC-P4K4HW"
+    }
+   },
+   {
+    "eventId": "8",
+    "eventTime": "2026-10-04T06:42:39.520833Z",
+    "eventType": "EVENT_TYPE_WORKFLOW_TASK_SCHEDULED",
+    "taskId": "1048640",
+    "workflowTaskScheduledEventAttributes": {
+     "taskQueue": {
+      "name": "20374@JNPR-MAC-P4K4HW-3dfecb0d3431480db077035652f5d673",
+      "kind": "TASK_QUEUE_KIND_STICKY",
+      "normalName": "dewpoint-admission"
+     },
+     "startToCloseTimeout": "10s",
+     "attempt": 1
+    }
+   },
+   {
+    "eventId": "9",
+    "eventTime": "2026-10-04T06:42:39.521725Z",
+    "eventType": "EVENT_TYPE_WORKFLOW_TASK_STARTED",
+    "taskId": "1048644",
+    "workflowTaskStartedEventAttributes": {
+     "scheduledEventId": "8",
+     "identity": "20374@JNPR-MAC-P4K4HW",
+     "requestId": "394c0388-980b-4319-9883-fe914793c223",
+     "historySizeBytes": "2068",
+     "workerVersion": {
+      "buildId": "0dc0b137dd34767821920cc66c1f547c"
+     }
+    }
+   },
+   {
+    "eventId": "10",
+    "eventTime": "2026-10-04T06:42:39.524079Z",
+    "eventType": "EVENT_TYPE_WORKFLOW_TASK_COMPLETED",
+    "taskId": "1048648",
+    "workflowTaskCompletedEventAttributes": {
+     "scheduledEventId": "8",
+     "startedEventId": "9",
+     "identity": "20374@JNPR-MAC-P4K4HW",
+     "workerVersion": {
+      "buildId": "0dc0b137dd34767821920cc66c1f547c"
+     },
+     "sdkMetadata": {},
+     "meteringMetadata": {}
+    }
+   },
+   {
+    "eventId": "11",
+    "eventTime": "2026-10-04T06:42:39.524112Z",
+    "eventType": "EVENT_TYPE_WORKFLOW_EXECUTION_COMPLETED",
+    "taskId": "1048649",
+    "workflowExecutionCompletedEventAttributes": {
+     "result": {
+      "payloads": [
+       {
+        "metadata": {
+         "dewpoint-key-version": "MQ==",
+         "dewpoint-tenant": "MDAwMDAwMDAtMDAwMC00MDAwLTgwMDAtMDAwMDAwMDAwMGEx",
+         "encoding": "YmluYXJ5L2Rld3BvaW50LXRlbmFudC12MQ=="
+        },
+        "data": "f+elR2Hy5xfE4KORGWJG/SBEq6ZFWiTePOOXaW9MCqo3rpKRUIPXRGAWadyyF6p/bf+g0r/RN51gyNO8gCI="
+       }
+      ]
+     },
+     "workflowTaskCompletedEventId": "10"
+    }
+   }
+  ]
+ }
+}
\ No newline at end of file
diff --git a/backend/tests/apps/dispatcher/test_schedule_tick.py b/backend/tests/apps/dispatcher/test_schedule_tick.py
new file mode 100644
index 0000000..b8cd847
--- /dev/null
+++ b/backend/tests/apps/dispatcher/test_schedule_tick.py
@@ -0,0 +1,119 @@
+# SPDX-License-Identifier: Apache-2.0
+"""A schedule's tick admitted (engine 2b spec §8.2; the owner's rulings 9 and 10): in one transaction, as the dispatch
+role, under the tick key `sched:<schedule_id>:<nominal time>`, so every retry of a tick finds what the first recorded.
+No tick is silently dropped: an enabled schedule's is a request (queued, or refused as admission refuses a durable
+source); a schedule disabled before its pause reached Temporal gives a `refused` request (`schedule_paused`), a deleted
+one's tombstone one (`schedule_deleted`); an `erasing` tenant's is an audited skip, never a request."""
+
+import uuid
+from typing import Any
+
+import pytest
+from sqlalchemy import text
+
+from dewpoint.apps import schedules
+from dewpoint.apps.dispatcher import tick
+from dewpoint.core.db import tenant_scope
+from tests.apps.test_admission import KEYS, SCHEMA, TOKEN, count, current, published
+from tests.apps.test_admission_csv import full_input
+from tests.apps.test_workflow_ops import publish, save, update
+from tests.support.graphs import G
+
+pytestmark = pytest.mark.usefixtures("development_deployment")
+KEY = "sched:{}:2026-10-04T09:00:00Z"
+
+
+@pytest.fixture
+async def ready(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings) -> Any:
+    ctx, wf = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings)
+    await current(dispatch_sessionmaker)
+    async with api_sessionmaker() as s, s.begin():
+        await tenant_scope(s, ctx.tenant_id)
+        created = await schedules.create(
+            s, KEYS, tenant_id=ctx.tenant_id, actor_id=ctx.user.id, workflow_id=wf,
+            timing={"cron": "0 9 * * *", "every_s": None, "offset_s": 0, "time_zone": "UTC", "catchup_window_s": 600},
+            mode="simulate", input={"token": TOKEN, "site": "a"}, enabled=True,
+        )  # fmt: skip
+    return ctx, wf, created.id
+
+
+async def ticked(dispatch: Any, ctx: Any, schedule_id: uuid.UUID) -> str:
+    async with dispatch() as s, s.begin():
+        return await tick.admit_tick(s, KEYS, tenant_id=ctx.tenant_id, schedule_id=schedule_id,
+                                     key=KEY.format(schedule_id))  # fmt: skip
+
+
+async def requests(owner: Any) -> list[Any]:
+    async with owner() as s:
+        found = await s.execute(text("select * from run_requests order by queued_at"))
+        return list(found.mappings())
+
+
+async def changed(owner: Any, schedule_id: uuid.UUID, statement: str) -> None:
+    async with owner() as s, s.begin():
+        await s.execute(text(statement), {"i": schedule_id})
+
+
+async def test_an_enabled_schedules_tick_is_a_request_under_its_key(
+    ready, owner_sessionmaker, dispatch_sessionmaker
+) -> None:
+    ctx, wf, schedule_id = ready
+    assert await ticked(dispatch_sessionmaker, ctx, schedule_id) == "queued"
+    [r] = await requests(owner_sessionmaker)
+    assert (r["source"], r["actor_id"], r["mode"], r["workflow_id"], r["idempotency_key"]) == (
+        "schedule", None, "simulate", wf, KEY.format(schedule_id),
+    )  # fmt: skip
+    assert await full_input(dispatch_sessionmaker, ctx, r["id"]) == {"token": TOKEN, "site": "a"}
+    assert await ticked(dispatch_sessionmaker, ctx, schedule_id) == "queued"  # a retry: the same request
+    assert await count(owner_sessionmaker, "run_requests") == 1
+
+
+@pytest.mark.parametrize(
+    ("statement", "reason"),
+    [
+        ("update schedules set enabled = false where id = :i", "schedule_paused"),
+        ("update schedules set input = null, deleted_at = now() where id = :i", "schedule_deleted"),
+    ],
+)
+async def test_a_paused_or_deleted_schedules_tick_is_a_refused_request(
+    ready, owner_sessionmaker, dispatch_sessionmaker, statement, reason
+) -> None:
+    ctx, wf, schedule_id = ready
+    await changed(owner_sessionmaker, schedule_id, statement)
+    assert await ticked(dispatch_sessionmaker, ctx, schedule_id) == f"refused:{reason}"
+    [r] = await requests(owner_sessionmaker)
+    assert (r["status"], r["reason"], r["workflow_id"], r["envelope_id"]) == ("refused", reason, wf, None)
+    assert await ticked(dispatch_sessionmaker, ctx, schedule_id) == f"refused:{reason}"
+    assert await count(owner_sessionmaker, "run_requests") == 1
+
+
+async def test_a_disabled_workflows_tick_is_refused_as_admission_refuses_it(
+    ready, owner_sessionmaker, api_sessionmaker, dispatch_sessionmaker
+) -> None:
+    ctx, wf, schedule_id = ready
+    await update(api_sessionmaker, ctx, wf, enabled=False)
+    assert await ticked(dispatch_sessionmaker, ctx, schedule_id) == "refused:workflow_disabled"
+
+
+async def test_an_input_the_active_version_no_longer_takes_is_a_refused_request(
+    ready, owner_sessionmaker, api_sessionmaker, dispatch_sessionmaker, api_settings
+) -> None:
+    ctx, wf, schedule_id = ready
+    stricter = {**SCHEMA, "required": ["token", "region"],
+                "properties": {**SCHEMA["properties"], "region": {"type": "string"}}}  # fmt: skip
+    await save(api_sessionmaker, ctx, wf, G().node("a", "testkit.echo@1", {"value": 1}).data()
+               | {"settings": {"input_schema": stricter}})  # fmt: skip
+    assert (await publish(api_sessionmaker, ctx, wf, api_settings)).version is not None
+    assert await ticked(dispatch_sessionmaker, ctx, schedule_id) == "refused:input_invalid"
+
+
+async def test_an_erasing_tenants_tick_is_an_audited_skip(ready, owner_sessionmaker, dispatch_sessionmaker) -> None:
+    ctx, _, schedule_id = ready
+    async with owner_sessionmaker() as s, s.begin():
+        await s.execute(text("update tenants set status = 'erasing' where id = :t"), {"t": ctx.tenant_id})
+    assert await ticked(dispatch_sessionmaker, ctx, schedule_id) == "skipped:tenant_erasing"
+    assert await count(owner_sessionmaker, "run_requests") == 0
+    async with owner_sessionmaker() as s:
+        details = (await s.execute(text("select details from audit_log where action = 'schedule.tick_skipped'"))
+                   ).scalar_one()  # fmt: skip
+    assert details == {"schedule_id": str(schedule_id), "tick": KEY.format(schedule_id), "reason": "tenant_erasing"}
diff --git a/backend/tests/apps/dispatcher/test_schedule_tick_replay.py b/backend/tests/apps/dispatcher/test_schedule_tick_replay.py
new file mode 100644
index 0000000..c04f7cf
--- /dev/null
+++ b/backend/tests/apps/dispatcher/test_schedule_tick_replay.py
@@ -0,0 +1,40 @@
+# SPDX-License-Identifier: Apache-2.0
+"""`ScheduleTick`'s replay test (engine 2b spec §8.2, §12): the workflow is unversioned, so a change to what it does
+would break every tick in flight when a new build takes over. One firing's history, recorded on the CLI dev server
+with fixture keys (`histories/record.py`), replays against today's code, whatever
+`ENGINE_ABI` is. A change that fails here is a contract change, made with a new workflow type."""
+
+import json
+from pathlib import Path
+
+from temporalio.client import WorkflowHistory
+from temporalio.worker import Replayer
+
+from dewpoint.apps.dispatcher.tick_workflow import ScheduleTick
+from tests.support.keys import FIXTURE_CONVERTER, opened
+
+RECORDED = Path(__file__).parent / "histories" / "schedule_tick.json"
+
+
+async def test_schedule_tick_replays_its_recorded_history() -> None:
+    recorded = json.loads(RECORDED.read_text())
+    history = WorkflowHistory.from_json(recorded["workflow_id"], recorded["history"])
+    replayer = Replayer(workflows=[ScheduleTick], data_converter=FIXTURE_CONVERTER)
+    result = await replayer.replay_workflow(history)
+    assert result.replay_failure is None
+
+
+async def test_the_recorded_tick_keyed_its_request_on_its_nominal_time() -> None:
+    """What the history holds: the schedule's id as the only argument, and the activity's input carrying the key built
+    from `TemporalScheduledStartTime`, sealed under the schedule's tenant like every payload."""
+    recorded = json.loads(RECORDED.read_text())
+    history = WorkflowHistory.from_json(recorded["workflow_id"], recorded["history"])
+    started = history.events[0].workflow_execution_started_event_attributes
+    scheduled = next(e for e in history.events if e.HasField("activity_task_scheduled_event_attributes"))
+    activity = scheduled.activity_task_scheduled_event_attributes
+    assert activity.activity_type.name == "schedule.tick" and activity.task_queue.name == "dewpoint-admission"
+    schedule = "00000000-0000-4000-8000-0000000000b2"
+    assert await opened(started.input.payloads[0]) == schedule
+    assert await opened(activity.input.payloads[0]) == {
+        "schedule_id": schedule, "key": f"sched:{schedule}:2026-10-04T09:00:00Z", "nominal": "2026-10-04T09:00:00Z",
+    }  # fmt: skip
diff --git a/backend/tests/apps/dispatcher/test_schedule_tick_server.py b/backend/tests/apps/dispatcher/test_schedule_tick_server.py
new file mode 100644
index 0000000..196a110
--- /dev/null
+++ b/backend/tests/apps/dispatcher/test_schedule_tick_server.py
@@ -0,0 +1,184 @@
+# SPDX-License-Identifier: Apache-2.0
+"""`ScheduleTick` (engine 2b spec §8.2; the owner's ruling 10): a one-activity workflow on `dewpoint-admission`, run by
+the dispatcher's own unversioned worker. It reads `TemporalScheduledStartTime` once and passes its tick key to its
+activity, which takes its authority from the workflow's own id only: an argument naming another schedule, or an id
+naming a schedule its tenant doesn't have, records nothing. A firing becomes a request under its key, and a backfill
+over a time that already fired admits nothing new. A failing tick is retried without limit, and one still unadmitted
+10 minutes after its time alerts.
+
+The Temporal Schedules here are created directly: the sync that keeps them in step with `schedules` is task 10's."""
+
+import asyncio
+import dataclasses
+import uuid
+from collections.abc import AsyncIterator
+from datetime import UTC, datetime, timedelta
+from typing import Any
+
+import pytest
+import structlog
+from sqlalchemy import text
+from temporalio.client import (
+    Client,
+    Schedule,
+    ScheduleActionStartWorkflow,
+    ScheduleBackfill,
+    ScheduleIntervalSpec,
+    ScheduleOverlapPolicy,
+    ScheduleSpec,
+    ScheduleState,
+    WorkflowFailureError,
+)
+from temporalio.exceptions import ApplicationError
+from temporalio.testing import ActivityEnvironment, WorkflowEnvironment
+
+from dewpoint.apps import schedules
+from dewpoint.apps.dispatcher import main, tick
+from dewpoint.core.db import tenant_scope
+from dewpoint.engine.runtime.ids import schedule_workflow_id
+from tests.apps.test_admission import KEYS, TOKEN, count, current, published
+from tests.support.keys import FIXTURE_CONVERTER
+
+pytestmark = pytest.mark.usefixtures("development_deployment")
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
+    ctx, wf = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings)
+    await current(dispatch_sessionmaker)
+    async with api_sessionmaker() as s, s.begin():
+        await tenant_scope(s, ctx.tenant_id)
+        created = await schedules.create(
+            s, KEYS, tenant_id=ctx.tenant_id, actor_id=ctx.user.id, workflow_id=wf,
+            timing={"cron": None, "every_s": 3600, "offset_s": 0, "time_zone": "UTC", "catchup_window_s": 600},
+            mode="live", input={"token": TOKEN, "site": "a"}, enabled=True,
+        )  # fmt: skip
+    return ctx, created.id
+
+
+async def temporal_schedule(client: Client, schedule_id: str, *, argument: str) -> Any:
+    """A Temporal Schedule as the sync will create it, paused so that only backfills fire."""
+    return await client.create_schedule(
+        schedule_id,
+        Schedule(
+            action=ScheduleActionStartWorkflow(
+                "ScheduleTick", argument, id=schedule_id, task_queue=tick.ADMISSION_QUEUE
+            ),  # fmt: skip
+            spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=timedelta(minutes=1))]),
+            state=ScheduleState(paused=True),
+        ),
+    )
+
+
+async def fired(client: Client, handle: Any, at: datetime) -> list[Any]:
+    """The ticks a backfill of the half minute ending at `at` starts (only `at` fires in it), each to its end."""
+    before = {
+        w.id
+        async for w in client.list_workflows(f"WorkflowType='ScheduleTick' AND WorkflowId STARTS_WITH '{handle.id}'")
+    }
+    await handle.backfill(ScheduleBackfill(start_at=at - timedelta(seconds=30), end_at=at,
+                                           overlap=ScheduleOverlapPolicy.ALLOW_ALL))  # fmt: skip
+    for _ in range(100):
+        listed = [
+            w
+            async for w in client.list_workflows(
+                f"WorkflowType='ScheduleTick' AND WorkflowId STARTS_WITH '{handle.id}'"
+            )
+        ]
+        if len(listed) > len(before) and all(w.status is not None and w.status.name != "RUNNING" for w in listed):
+            return [client.get_workflow_handle(w.id, run_id=w.run_id) for w in listed]
+        await asyncio.sleep(0.2)
+    raise AssertionError("no tick ended")
+
+
+async def test_a_firing_is_a_request_under_its_tick_key_and_a_repeat_admits_nothing_new(
+    server, ready, owner_sessionmaker, dispatch_sessionmaker
+) -> None:
+    ctx, schedule_id = ready
+    client = server.client
+    temporal_id = schedule_workflow_id(str(ctx.tenant_id), str(schedule_id))
+    handle = await temporal_schedule(client, temporal_id, argument=str(schedule_id))
+    at = datetime.now(UTC).replace(second=0, microsecond=0)
+    async with main.admission_worker(client, dispatch_sessionmaker, KEYS):
+        [first] = await fired(client, handle, at)
+        assert await first.result() == "queued"
+        ticks = await fired(client, handle, at)  # the same nominal time again
+        assert [await t.result() for t in ticks] == ["queued", "queued"]
+    async with owner_sessionmaker() as s:
+        keys = (await s.execute(text("select idempotency_key from run_requests"))).scalars().all()
+    assert keys == [f"sched:{schedule_id}:{(at).strftime('%Y-%m-%dT%H:%M:%SZ')}"]
+    await handle.delete()
+
+
+async def test_an_id_naming_a_schedule_its_tenant_doesnt_have_records_nothing(
+    server, ready, owner_sessionmaker, dispatch_sessionmaker
+) -> None:
+    """The row is read in the tenant the workflow id names: another tenant's schedule isn't there."""
+    _, schedule_id = ready
+    client = server.client
+    elsewhere = schedule_workflow_id(str(uuid.uuid4()), str(schedule_id))
+    handle = await temporal_schedule(client, elsewhere, argument=str(schedule_id))
+    async with main.admission_worker(client, dispatch_sessionmaker, KEYS):
+        [failed] = await fired(client, handle, datetime.now(UTC).replace(second=0, microsecond=0))
+        with pytest.raises(WorkflowFailureError) as e:
+            await failed.result()
+    assert isinstance(e.value.cause.cause, ApplicationError) and e.value.cause.cause.type == tick.SCHEDULE_UNKNOWN
+    assert await count(owner_sessionmaker, "run_requests") == 0
+    await handle.delete()
+
+
+async def test_a_tick_without_its_nominal_time_fails_before_its_activity(server, ready, dispatch_sessionmaker) -> None:
+    ctx, schedule_id = ready
+    client = server.client
+    workflow_id = schedule_workflow_id(str(ctx.tenant_id), str(schedule_id)) + "-by-hand"
+    async with main.admission_worker(client, dispatch_sessionmaker, KEYS):
+        handle = await client.start_workflow("ScheduleTick", str(schedule_id), id=workflow_id,
+                                             task_queue=tick.ADMISSION_QUEUE)  # fmt: skip
+        with pytest.raises(WorkflowFailureError) as e:
+            await handle.result()
+    assert isinstance(e.value.cause, ApplicationError) and e.value.cause.type == "tick_no_nominal_time"
+
+
+def environment(workflow_id: str) -> ActivityEnvironment:
+    env = ActivityEnvironment()
+    env.info = dataclasses.replace(env.info, workflow_id=workflow_id)
+    return env
+
+
+async def test_an_argument_naming_another_schedule_is_refused_whatever_the_database_holds() -> None:
+    tenant, schedule_id, other = (str(uuid.uuid4()) for _ in range(3))
+    nominal = datetime(2026, 10, 4, 9, tzinfo=UTC)
+    ticker = tick.Ticker(None, KEYS)  # type: ignore[arg-type]  # never reached
+    for workflow_id, argument in (
+        (schedule_workflow_id(tenant, schedule_id) + "-2026-10-04T09:00:00Z", other),
+        (f"t:{tenant}:run:{schedule_id}", schedule_id),  # not a schedule's id at all
+    ):
+        key, stamp = tick.tick_key(argument, nominal)
+        with pytest.raises(ApplicationError) as e:
+            await environment(workflow_id).run(ticker.tick, tick.TickInput(argument, key, stamp))
+        assert (e.value.type, e.value.non_retryable) == (tick.TICK_IDENTITY, True)
+
+
+class Down:
+    """A database that doesn't answer."""
+
+    def __call__(self) -> Any:
+        raise OSError("connection refused")
+
+
+async def test_a_tick_still_failing_ten_minutes_after_its_time_alerts() -> None:
+    tenant, schedule_id = str(uuid.uuid4()), str(uuid.uuid4())
+    ticker = tick.Ticker(Down(), KEYS)  # type: ignore[arg-type]
+    for minutes, alerts in ((5, []), (11, ["schedule_tick_late"])):
+        key, stamp = tick.tick_key(schedule_id, datetime.now(UTC) - timedelta(minutes=minutes))
+        with structlog.testing.capture_logs() as logs, pytest.raises(OSError):
+            await environment(schedule_workflow_id(tenant, schedule_id)).run(
+                ticker.tick, tick.TickInput(schedule_id, key, stamp)
+            )
+        assert [entry["event"] for entry in logs if entry["log_level"] == "error"] == alerts
diff --git a/backend/tests/engine/runtime/test_ids.py b/backend/tests/engine/runtime/test_ids.py
index 213a90b..e538439 100644
--- a/backend/tests/engine/runtime/test_ids.py
+++ b/backend/tests/engine/runtime/test_ids.py
@@ -5,7 +5,15 @@ import uuid
 
 import pytest
 
-from dewpoint.engine.runtime.ids import ID_MAX, batch_workflow_id, run_of, run_workflow_id, tenant_of
+from dewpoint.engine.runtime.ids import (
+    ID_MAX,
+    batch_workflow_id,
+    run_of,
+    run_workflow_id,
+    schedule_of,
+    schedule_workflow_id,
+    tenant_of,
+)
 
 TENANT = "8f14e45f-ceea-467a-9575-8f6a1b2c3d4e"  # letters too: the server writes uuids in lower case
 RUN = str(uuid.UUID(int=2))
@@ -69,6 +77,17 @@ def test_a_schedules_firing_names_its_tenant_and_no_run() -> None:
     assert (tenant_of(firing), run_of(firing)) == (TENANT, None)
 
 
+def test_a_schedules_id_and_its_firings_name_its_tenant_and_the_schedule() -> None:
+    """A tick's activity takes its authority from its workflow id (the owner's ruling 10): both ids, never the
+    argument's."""
+    schedule = str(uuid.UUID(int=4))
+    assert schedule_workflow_id(TENANT, schedule) == f"t:{TENANT}:sched:{schedule}"
+    for workflow_id in (schedule_workflow_id(TENANT, schedule), f"t:{TENANT}:sched:{schedule}-2026-09-29T10:00:00Z"):
+        assert schedule_of(workflow_id) == (TENANT, schedule)
+    for workflow_id in (f"t:{TENANT}:run:{RUN}", f"t:{TENANT}:sched:{schedule}/batch:0", f"t:{TENANT}:sched:x", ""):
+        assert schedule_of(workflow_id) is None
+
+
 @pytest.mark.parametrize(
     "workflow_id",
     [
```

### Task 15: The schedule sync: token-bearing updates, completed only by a read-back of their marker

**Commit:** `9aa31e4` (prototype `proto/2b3a-v2`); the replay's tree was identical: yes.

**Create:** `backend/migrations/versions/0030_schedule_sync.py`, `backend/src/dewpoint/apps/dispatcher/schedule_sync.py`, `backend/tests/apps/dispatcher/test_schedule_sync.py`

**Modify:** `backend/src/dewpoint/apps/dispatcher/main.py`, `backend/src/dewpoint/apps/dispatcher/tick.py`, `backend/src/dewpoint/apps/workflow_ops.py`

**What it does:**

The reconciler's leader keeps each Temporal Schedule in step with its row (engine 2b spec
§8.2; the owner's rulings on the milestone-3 gate), reading across tenants only through
`schedule_candidates()` (0030, ids only). The pinned SDK sends no conflict token, so it
calls the service itself: describe (the token) → read the row → one update with that token
holding the spec, the action (sealed under the tenant by the SDK's own conversion), the pause
state and the note `dewpoint generation <n>`. Temporal discards a stale update and still
answers OK, so a generation is marked synced only once a fresh describe shows its marker and
a transaction confirms the row still has that generation and the writer still leads; else
it stays queued. Tested on the dev server: a create, changes and a workflow's disable
reaching Temporal by generation (disabling or enabling a workflow raises its schedules'
generation); a row changed during the sync left queued; another writer's update landing
between a describe and an update (this one discarded, nothing recorded); a writer that lost
the leadership recording nothing.

A create follows a describe that found nothing; a tombstone's delete is recorded only once a
describe made a call deadline after the deletion finds nothing, and a tick that finds a
tombstone queues it again. A failure is recorded with a fixed code (`temporal_refused`,
`sync_failed`), alerted on, and retried after a minute. Missed firings past the catch-up
window are Temporal's own count, read every five minutes (`schedule_miss_candidates()`),
recorded, audited and alerted on: tested across a dev server outage longer than the window.

**Later tasks refine this.** Task 16's exclusive row lock covers a tick of a tombstone, which writes the row to queue it
again.

- [ ] **Step 1: its tests alone, before its code.** Run: `uv run pytest -n 8 tests/apps/dispatcher/test_schedule_sync.py`. Replay result (exit 1), shortened:

```
==================================== ERRORS ====================================
_________ ERROR collecting tests/apps/dispatcher/test_schedule_sync.py _________
ImportError while importing test module '<replay>/backend/tests/apps/dispatcher/test_schedule_sync.py'.
Hint: make sure your test modules/packages have valid Python names.
Traceback:
<python>/lib/python3.14/importlib/__init__.py:88: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
tests/apps/dispatcher/test_schedule_sync.py:23: in <module>
    from dewpoint.apps.dispatcher import schedule_sync, tick
E   ImportError: cannot import name 'schedule_sync' from 'dewpoint.apps.dispatcher' (<replay>/backend/src/dewpoint/apps/dispatcher/__init__.py)
=========================== short test summary info ============================
ERROR tests/apps/dispatcher/test_schedule_sync.py - ImportError while importi...
1 error in 4.84s
```

- [ ] **Step 2: its code, then the same tests.** Replay result (exit 0), shortened:

```
.........                                                                [100%]
9 passed in 38.40s
```

- [ ] **Step 3: commit.** `git cherry-pick --no-commit 9aa31e4 && git commit -C 9aa31e4`

The diff:

```diff
diff --git a/backend/migrations/versions/0030_schedule_sync.py b/backend/migrations/versions/0030_schedule_sync.py
new file mode 100644
index 0000000..86e3490
--- /dev/null
+++ b/backend/migrations/versions/0030_schedule_sync.py
@@ -0,0 +1,54 @@
+# SPDX-License-Identifier: Apache-2.0
+"""the schedule sync's views across tenants (engine 2b spec §8.2): ids only, as the dispatcher's others are. The
+schedules whose generation passes the one its sync last completed (a failed one retried after a minute), and the
+enabled ones whose missed firings it hasn't read from Temporal for five minutes"""
+
+from alembic import op
+
+revision = "0030"
+down_revision = "0029"
+branch_labels = None
+depends_on = None
+
+STATEMENTS = [
+    "CREATE INDEX schedules_unsynced ON schedules (updated_at, id) WHERE generation > synced_generation",
+    """
+CREATE FUNCTION schedule_candidates(max_schedules integer)
+RETURNS TABLE (tenant_id uuid, schedule_id uuid)
+LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
+    SELECT s.tenant_id, s.id FROM schedules s
+    WHERE s.generation > s.synced_generation
+      AND (s.sync_error_at IS NULL OR s.sync_error_at < statement_timestamp() - interval '60 seconds')
+    ORDER BY s.updated_at, s.id
+    LIMIT max_schedules
+$$""",
+    """
+CREATE FUNCTION schedule_miss_candidates(max_schedules integer)
+RETURNS TABLE (tenant_id uuid, schedule_id uuid)
+LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
+    SELECT s.tenant_id, s.id FROM schedules s
+    WHERE s.deleted_at IS NULL AND s.synced_generation > 0
+      AND (s.misses_checked_at IS NULL OR s.misses_checked_at < statement_timestamp() - interval '5 minutes')
+    ORDER BY s.misses_checked_at NULLS FIRST, s.id
+    LIMIT max_schedules
+$$""",
+    *(
+        statement
+        for name in ("schedule_candidates", "schedule_miss_candidates")
+        for statement in (
+            f"REVOKE ALL ON FUNCTION {name}(integer) FROM PUBLIC",
+            f"GRANT EXECUTE ON FUNCTION {name}(integer) TO dewpoint_dispatch",
+        )
+    ),
+]
+
+
+def upgrade() -> None:
+    for statement in STATEMENTS:
+        op.execute(statement)
+
+
+def downgrade() -> None:
+    op.execute("DROP FUNCTION schedule_miss_candidates(integer)")
+    op.execute("DROP FUNCTION schedule_candidates(integer)")
+    op.execute("DROP INDEX schedules_unsynced")
diff --git a/backend/src/dewpoint/apps/dispatcher/main.py b/backend/src/dewpoint/apps/dispatcher/main.py
index 1b15d69..e16aca9 100644
--- a/backend/src/dewpoint/apps/dispatcher/main.py
+++ b/backend/src/dewpoint/apps/dispatcher/main.py
@@ -19,6 +19,7 @@ from dewpoint.apps.dispatcher.cancels import send_cancels
 from dewpoint.apps.dispatcher.dispatch import Rotation, dispatch_once
 from dewpoint.apps.dispatcher.observe import observe, report
 from dewpoint.apps.dispatcher.reconcile import Leader, reconcile_once
+from dewpoint.apps.dispatcher.schedule_sync import check_misses, sync_schedules
 from dewpoint.apps.dispatcher.tick import ADMISSION_QUEUE, Ticker
 from dewpoint.apps.dispatcher.tick_workflow import ScheduleTick
 from dewpoint.apps.environment import verify_environment
@@ -47,9 +48,10 @@ async def cycle(
     sessionmaker: async_sessionmaker[AsyncSession], client: Client, keys: KeySource, settings: Settings, *,
     instance: uuid.UUID, reconciler: uuid.UUID, leader: Leader, rotation: Rotation,
 ) -> None:  # fmt: skip
-    """One cycle: observe the current build, dispatch what's due, report; the leader also reconciles and sends
-    cancels. An observation that fails (Temporal, or the database, briefly unavailable) dispatches nothing this cycle,
-    and the next one asks again; the record it didn't refresh ages out for admission (§7.2)."""
+    """One cycle: observe the current build, dispatch what's due, report; the leader also reconciles, sends cancels,
+    keeps the Temporal Schedules in step with their rows and reads their missed firings. An observation that fails
+    (Temporal, or the database, briefly unavailable) dispatches nothing this cycle, and the next one asks again; the
+    record it didn't refresh ages out for admission (§7.2)."""
     try:
         build = await observe(sessionmaker, await current_build(client))
     except Exception as e:
@@ -61,6 +63,8 @@ async def cycle(
     if await leader.leading():
         settled = await reconcile_once(sessionmaker, client, keys, settings)
         settled.update({f"cancel_{k}": v for k, v in (await send_cancels(sessionmaker, client)).items()})
+        settled.update({f"schedule_{k}": v for k, v in (await sync_schedules(sessionmaker, client, leader)).items()})
+        settled.update({f"misses_{k}": v for k, v in (await check_misses(sessionmaker, client)).items()})
         await report(sessionmaker, reconciler, build_id, {**settled}, kind="reconciler")
 
 
diff --git a/backend/src/dewpoint/apps/dispatcher/schedule_sync.py b/backend/src/dewpoint/apps/dispatcher/schedule_sync.py
new file mode 100644
index 0000000..d7e2d7a
--- /dev/null
+++ b/backend/src/dewpoint/apps/dispatcher/schedule_sync.py
@@ -0,0 +1,270 @@
+# SPDX-License-Identifier: Apache-2.0
+"""The schedule sync (engine 2b spec §8.2; the owner's rulings on the milestone-3 gate): the reconciler's leader keeps
+each Temporal Schedule in step with its row, reading across tenants only through `schedule_candidates()`.
+
+The pinned SDK sends no conflict token (`ScheduleHandle.update()` builds its request without one), so this module
+calls the service directly. Each change is: describe the schedule (its conflict token) → read the row's generation and
+wanted state → one update with that token, holding the spec, the action (built by the SDK's own conversion, so the codec
+seals it under the tenant), the pause state and the note `dewpoint generation <n>` together. Temporal discards an
+update whose token a later update made stale, and still answers OK (`test_temporal_contract.py`), so an OK answer is no
+evidence: a generation is marked synced only once a fresh describe shows its marker and a transaction confirms that the
+row still has that generation and the writer still holds the leadership. A marker absent or different leaves the row
+queued, and the next pass starts again.
+
+A create (no token) follows a describe that found nothing; one that finds the schedule already there leaves the row
+queued for an update. A deletion's tombstone stays queued until a describe made a call deadline after the deletion
+finds nothing, so a stale writer's create, started before the tombstone, can't bring the schedule back unseen; a tick
+that finds a tombstone queues it again. The marker is evidence of a Dewpoint update, not of the whole state: editing a
+schedule directly in Temporal isn't supported. Missed firings past the catch-up window are Temporal's own count, read
+every five minutes, recorded, audited and alerted on."""
+
+import uuid
+from dataclasses import dataclass
+from datetime import timedelta
+from typing import Any, Protocol
+
+import structlog
+from sqlalchemy import func, select, text, update
+from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
+from temporalio.api.workflowservice.v1 import DeleteScheduleRequest, DescribeScheduleRequest, UpdateScheduleRequest
+from temporalio.client import (
+    Client,
+    Schedule,
+    ScheduleActionStartWorkflow,
+    ScheduleAlreadyRunningError,
+    ScheduleIntervalSpec,
+    ScheduleOverlapPolicy,
+    SchedulePolicy,
+    ScheduleSpec,
+    ScheduleState,
+)
+from temporalio.service import RPCError, RPCStatusCode
+
+from dewpoint.apps.dispatcher.tick import ADMISSION_QUEUE
+from dewpoint.core.audit import service as audit
+from dewpoint.core.db import tenant_scope
+from dewpoint.core.models.schedules import Schedule as Row
+from dewpoint.core.models.tenancy import Tenant
+from dewpoint.core.models.workflows import Workflow
+from dewpoint.engine.runtime.ids import schedule_workflow_id
+
+log = structlog.get_logger("dewpoint.dispatcher.schedules")
+MARK = "dewpoint generation {}"  # the only thing the sync writes into a schedule's note (the owner's ruling)
+BATCH = 50  # schedules a pass
+CALL_DEADLINE = timedelta(seconds=10)  # every call to Temporal here is bounded by it
+TEMPORAL_REFUSED = "temporal_refused"
+SYNC_FAILED = "sync_failed"
+
+
+class _Leader(Protocol):
+    async def leading(self) -> bool: ...
+
+
+@dataclass(frozen=True)
+class Described:
+    token: bytes
+    note: str
+    missed: int  # firings Temporal skipped past the catch-up window, ever
+
+
+@dataclass(frozen=True)
+class _Wanted:
+    generation: int
+    schedule: Schedule | None  # None for a tombstone
+    settled: bool = False  # a tombstone deleted at least a call deadline ago, by the database's clock
+
+
+async def _after_read() -> None:
+    """Runs between the row's read and the update. A no-op; the race tests change things here."""
+
+
+async def described(client: Client, schedule_id: str) -> Described | None:
+    try:
+        answer = await client.workflow_service.describe_schedule(
+            DescribeScheduleRequest(namespace=client.namespace, schedule_id=schedule_id), timeout=CALL_DEADLINE
+        )
+    except RPCError as e:
+        if e.status == RPCStatusCode.NOT_FOUND:
+            return None
+        raise
+    return Described(answer.conflict_token, answer.schedule.state.notes, answer.info.missed_catchup_window)
+
+
+async def _create(client: Client, schedule_id: str, schedule: Schedule) -> bool:
+    """False when a schedule is already there: an update, with a token, is the next pass's."""
+    try:
+        await client.create_schedule(schedule_id, schedule, rpc_timeout=CALL_DEADLINE)
+    except ScheduleAlreadyRunningError:
+        return False
+    return True
+
+
+async def _update(client: Client, schedule_id: str, schedule: Schedule, token: bytes) -> None:
+    await client.workflow_service.update_schedule(
+        UpdateScheduleRequest(
+            namespace=client.namespace, schedule_id=schedule_id, schedule=await schedule._to_proto(client),
+            conflict_token=token, identity=client.identity, request_id=str(uuid.uuid4()),
+        ),
+        timeout=CALL_DEADLINE,
+    )  # fmt: skip
+
+
+async def _delete(client: Client, schedule_id: str) -> None:
+    try:
+        await client.workflow_service.delete_schedule(
+            DeleteScheduleRequest(namespace=client.namespace, schedule_id=schedule_id, identity=client.identity),
+            timeout=CALL_DEADLINE,
+        )
+    except RPCError as e:
+        if e.status != RPCStatusCode.NOT_FOUND:
+            raise
+
+
+def temporal(row: Row, *, paused: bool) -> Schedule:
+    """The Temporal Schedule a row wants, its generation in the note."""
+    if row.cron is not None:
+        spec = ScheduleSpec(cron_expressions=[row.cron], time_zone_name=row.time_zone)
+    else:
+        every = timedelta(seconds=row.every_s or 0)
+        spec = ScheduleSpec(intervals=[ScheduleIntervalSpec(every=every, offset=timedelta(seconds=row.offset_s))])
+    return Schedule(
+        action=ScheduleActionStartWorkflow(
+            "ScheduleTick", str(row.id), id=schedule_workflow_id(str(row.tenant_id), str(row.id)),
+            task_queue=ADMISSION_QUEUE,
+        ),
+        spec=spec,
+        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.ALLOW_ALL,
+                              catchup_window=timedelta(seconds=row.catchup_window_s)),
+        state=ScheduleState(paused=paused, note=MARK.format(row.generation)),
+    )  # fmt: skip
+
+
+async def _wanted(s: AsyncSession, tenant_id: uuid.UUID, schedule_id: uuid.UUID) -> _Wanted | None:
+    await tenant_scope(s, tenant_id)
+    row = await s.get(Row, schedule_id, populate_existing=True)
+    if row is None:
+        return None
+    if row.deleted_at is not None:
+        settled = await s.scalar(select(Row.deleted_at < func.statement_timestamp() - CALL_DEADLINE)
+                                 .where(Row.id == schedule_id))  # fmt: skip
+        return _Wanted(row.generation, None, bool(settled))
+    workflow = await s.get(Workflow, row.workflow_id, populate_existing=True)
+    tenant = await s.get(Tenant, tenant_id, populate_existing=True)
+    paused = not row.enabled or workflow is None or not workflow.enabled or tenant is None or tenant.status != "active"
+    return _Wanted(row.generation, temporal(row, paused=paused))
+
+
+async def _record(
+    sessionmaker: async_sessionmaker[AsyncSession], leader: _Leader, tenant_id: uuid.UUID, schedule_id: uuid.UUID,
+    generation: int,
+) -> str:  # fmt: skip
+    """The generation marked synced, if the row still has it and this writer still leads."""
+    async with sessionmaker() as s, s.begin():
+        await tenant_scope(s, tenant_id)
+        if not await leader.leading():
+            return "not_leading"
+        done = await s.execute(
+            update(Row)
+            .where(Row.id == schedule_id, Row.generation == generation)
+            .values(synced_generation=generation, sync_error=None, sync_error_at=None)
+        )
+    return "synced" if done.rowcount else "pending"  # type: ignore[attr-defined]
+
+
+async def sync_one(
+    sessionmaker: async_sessionmaker[AsyncSession], client: Client, leader: _Leader, tenant_id: uuid.UUID,
+    schedule_id: uuid.UUID,
+) -> str:  # fmt: skip
+    """One schedule brought toward its row: `synced`, `pending` (left queued), `deleting`, `not_leading`, `gone`."""
+    temporal_id = schedule_workflow_id(str(tenant_id), str(schedule_id))
+    before = await described(client, temporal_id)
+    async with sessionmaker() as s, s.begin():
+        wanted = await _wanted(s, tenant_id, schedule_id)
+    if wanted is None:
+        return "gone"
+    await _after_read()
+    if wanted.schedule is None:  # a tombstone
+        if before is not None:
+            await _delete(client, temporal_id)
+            return "deleting"
+        if not wanted.settled:
+            return "deleting"  # absent, but a create started before the tombstone could still land
+        return await _record(sessionmaker, leader, tenant_id, schedule_id, wanted.generation)
+    mark = MARK.format(wanted.generation)
+    if before is None:
+        if not await _create(client, temporal_id, wanted.schedule):
+            return "pending"
+    elif before.note != mark:
+        await _update(client, temporal_id, wanted.schedule, before.token)
+    after = await described(client, temporal_id)  # the read-back: an OK answer proves nothing
+    if after is None or after.note != mark:
+        return "pending"
+    return await _record(sessionmaker, leader, tenant_id, schedule_id, wanted.generation)
+
+
+async def _failed(
+    sessionmaker: async_sessionmaker[AsyncSession], tenant_id: uuid.UUID, schedule_id: uuid.UUID, code: str
+) -> None:
+    async with sessionmaker() as s, s.begin():
+        await tenant_scope(s, tenant_id)
+        await s.execute(update(Row).where(Row.id == schedule_id).values(sync_error=code, sync_error_at=func.now()))
+
+
+async def sync_schedules(
+    sessionmaker: async_sessionmaker[AsyncSession], client: Client, leader: _Leader, *, batch: int = BATCH
+) -> dict[str, int]:
+    """One pass over the queued schedules, each isolated: a failure is recorded with a fixed code, alerted on, and
+    retried after a while."""
+    async with sessionmaker() as s:
+        picked = (
+            await s.execute(text("select tenant_id, schedule_id from schedule_candidates(:n)"), {"n": batch})
+        ).all()
+    counts: dict[str, int] = {}
+    for tenant_id, schedule_id in picked:
+        try:
+            outcome = await sync_one(sessionmaker, client, leader, tenant_id, schedule_id)
+        except Exception as e:
+            refused = isinstance(e, RPCError) and e.status in (RPCStatusCode.INVALID_ARGUMENT,
+                                                                RPCStatusCode.FAILED_PRECONDITION)  # fmt: skip
+            code = TEMPORAL_REFUSED if refused else SYNC_FAILED
+            log.error("schedule_sync_failed", schedule_id=str(schedule_id), code=code, error=type(e).__name__)
+            try:
+                await _failed(sessionmaker, tenant_id, schedule_id, code)
+            except Exception as again:
+                log.error("schedule_sync_unrecorded", schedule_id=str(schedule_id), error=type(again).__name__)
+            outcome = "failed"
+        counts[outcome] = counts.get(outcome, 0) + 1
+    return counts
+
+
+async def check_misses(
+    sessionmaker: async_sessionmaker[AsyncSession], client: Client, *, batch: int = BATCH
+) -> dict[str, int]:
+    """Temporal's count of firings missed past each schedule's catch-up window (an outage longer than it), read every
+    five minutes: an increase is recorded on the schedule, audited and alerted on, and the API shows it."""
+    async with sessionmaker() as s:
+        query = text("select tenant_id, schedule_id from schedule_miss_candidates(:n)")
+        picked = (await s.execute(query, {"n": batch})).all()
+    counts = {"checked": 0, "missed": 0}
+    for tenant_id, schedule_id in picked:
+        try:
+            found = await described(client, schedule_workflow_id(str(tenant_id), str(schedule_id)))
+            async with sessionmaker() as s, s.begin():
+                await tenant_scope(s, tenant_id)
+                row = await s.get(Row, schedule_id, populate_existing=True)
+                if row is None:
+                    continue
+                values: dict[str, Any] = {"misses_checked_at": func.now()}
+                if found is not None and found.missed > row.misses:
+                    missed = found.missed - row.misses
+                    values["misses"] = found.missed
+                    log.error("schedule_firings_missed", schedule_id=str(schedule_id), missed=missed)
+                    await audit.record(s, tenant_id=tenant_id, actor_id=None, action="schedule.missed",
+                                       target_type="schedule", target_id=str(schedule_id),
+                                       details={"schedule_id": str(schedule_id), "missed": missed})  # fmt: skip
+                    counts["missed"] += missed
+                await s.execute(update(Row).where(Row.id == schedule_id).values(**values))
+            counts["checked"] += 1
+        except Exception as e:
+            log.error("schedule_misses_unread", schedule_id=str(schedule_id), error=type(e).__name__)
+    return counts
diff --git a/backend/src/dewpoint/apps/dispatcher/tick.py b/backend/src/dewpoint/apps/dispatcher/tick.py
index f5d0b11..896ff50 100644
--- a/backend/src/dewpoint/apps/dispatcher/tick.py
+++ b/backend/src/dewpoint/apps/dispatcher/tick.py
@@ -17,6 +17,7 @@ from dataclasses import dataclass
 from datetime import UTC, datetime, timedelta
 
 import structlog
+from sqlalchemy import update
 from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
 from temporalio import activity
 from temporalio.exceptions import ApplicationError
@@ -78,6 +79,12 @@ async def admit_tick(
                            target_type="schedule", target_id=str(schedule_id), details=details)  # fmt: skip
         return f"skipped:{admission.TENANT_ERASING}"
     try:
+        if schedule.deleted_at is not None:  # a stale create may have brought it back in Temporal: delete it again
+            await s.execute(
+                update(Schedule)
+                .where(Schedule.id == schedule_id, Schedule.synced_generation == Schedule.generation)
+                .values(synced_generation=Schedule.generation - 1)
+            )
         if schedule.deleted_at is not None or not schedule.enabled or schedule.input is None:
             reason, said = (
                 (SCHEDULE_DELETED, "The schedule was deleted.") if schedule.deleted_at is not None
diff --git a/backend/src/dewpoint/apps/workflow_ops.py b/backend/src/dewpoint/apps/workflow_ops.py
index 5ca1a94..c4f9cc6 100644
--- a/backend/src/dewpoint/apps/workflow_ops.py
+++ b/backend/src/dewpoint/apps/workflow_ops.py
@@ -8,6 +8,7 @@ from dataclasses import dataclass
 from datetime import timedelta
 from typing import Any
 
+from sqlalchemy import text
 from sqlalchemy.ext.asyncio import AsyncSession
 
 from dewpoint.core.authz.permissions import ROLE_PERMISSIONS, P
@@ -305,5 +306,10 @@ async def update(
         version = await service.get_version(s, wf.id, wf.active_version_id)
         if version is not None:
             warnings = await _check_runnable(s, version)
+    if enabled is not None and enabled != wf.enabled:  # its schedules pause or resume: the sync follows the generation
+        await s.execute(
+            text("update schedules set generation = generation + 1, updated_at = now() "
+                 "where workflow_id = :w and deleted_at is null"), {"w": wf.id},
+        )  # fmt: skip
     await service.update_workflow(s, ctx, wf, name=name, enabled=enabled)
     return warnings
diff --git a/backend/tests/apps/dispatcher/test_schedule_sync.py b/backend/tests/apps/dispatcher/test_schedule_sync.py
new file mode 100644
index 0000000..dde6868
--- /dev/null
+++ b/backend/tests/apps/dispatcher/test_schedule_sync.py
@@ -0,0 +1,296 @@
+# SPDX-License-Identifier: Apache-2.0
+"""The schedule sync (engine 2b spec §8.2; the owner's rulings on the milestone-3 gate): the reconciler's leader keeps
+each Temporal Schedule in step with its row. Each change is a describe (its conflict token), the row read, then one
+token-bearing update holding the spec, the action, the pause state and the note `dewpoint generation <n>`. Temporal
+discards a stale update without an error, so an OK answer proves nothing: a generation is marked synced only once a
+fresh describe shows its marker and a transaction confirms that the row still has that generation and the writer still
+holds the leadership; a marker absent or different leaves it queued. A deletion is recorded only once the schedule's
+absence is seen a call deadline after it, and a tick that finds a tombstone queues it again."""
+
+import uuid
+from collections.abc import AsyncIterator
+from datetime import timedelta
+from typing import Any
+
+import pytest
+from sqlalchemy import text
+from temporalio.api.workflowservice.v1 import DescribeScheduleRequest, UpdateScheduleRequest
+from temporalio.client import ScheduleActionStartWorkflow
+from temporalio.service import RPCStatusCode
+from temporalio.testing import WorkflowEnvironment
+
+from dewpoint.apps import schedules
+from dewpoint.apps.dispatcher import schedule_sync, tick
+from dewpoint.core.db import tenant_scope
+from dewpoint.engine.runtime.ids import schedule_workflow_id
+from tests.apps.test_admission import KEYS, TOKEN, current, published
+from tests.apps.test_runs import rpc
+from tests.apps.test_workflow_ops import update as update_workflow
+from tests.support.keys import FIXTURE_CONVERTER, opened
+
+pytestmark = pytest.mark.usefixtures("development_deployment")
+TIMING = {"cron": "0 9 * * 1-5", "every_s": None, "offset_s": 0, "time_zone": "Europe/Paris", "catchup_window_s": 600}
+
+
+@pytest.fixture(scope="module")
+async def server() -> AsyncIterator[WorkflowEnvironment]:
+    async with await WorkflowEnvironment.start_local(data_converter=FIXTURE_CONVERTER) as environment:
+        yield environment
+
+
+class Leading:
+    def __init__(self, value: bool = True) -> None:
+        self.value = value
+
+    async def leading(self) -> bool:
+        return self.value
+
+
+@pytest.fixture
+async def ready(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings) -> Any:
+    ctx, wf = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings)
+    await current(dispatch_sessionmaker)
+    async with api_sessionmaker() as s, s.begin():
+        await tenant_scope(s, ctx.tenant_id)
+        created = await schedules.create(s, KEYS, tenant_id=ctx.tenant_id, actor_id=ctx.user.id, workflow_id=wf,
+                                         timing=TIMING, mode="live", input={"token": TOKEN}, enabled=True)  # fmt: skip
+    return ctx, wf, created.id
+
+
+async def sync(server: Any, dispatch: Any, ctx: Any, schedule_id: uuid.UUID, leader: Any = None) -> str:
+    return await schedule_sync.sync_one(dispatch, server.client, leader or Leading(), ctx.tenant_id, schedule_id)
+
+
+async def stored(owner: Any, schedule_id: uuid.UUID) -> Any:
+    async with owner() as s:
+        return (await s.execute(text("select * from schedules where id = :i"), {"i": schedule_id})).mappings().one()
+
+
+async def changed(api: Any, ctx: Any, schedule_id: uuid.UUID, **changes: Any) -> None:
+    async with api() as s, s.begin():
+        await tenant_scope(s, ctx.tenant_id)
+        await schedules.update(s, KEYS, actor_id=ctx.user.id, schedule=await schedules.found(s, schedule_id),
+                               changes=changes)  # fmt: skip
+
+
+async def in_temporal(server: Any, ctx: Any, schedule_id: uuid.UUID) -> Any:
+    answer = await server.client.workflow_service.describe_schedule(
+        DescribeScheduleRequest(namespace=server.client.namespace,
+                                schedule_id=schedule_workflow_id(str(ctx.tenant_id), str(schedule_id)))
+    )  # fmt: skip
+    return answer
+
+
+def fires(found: Any) -> tuple[int, int, tuple[int, int] | None]:
+    """The minute, the hour and the days of the week of a cron schedule, as Temporal holds it: a calendar."""
+    [calendar] = found.schedule.spec.structured_calendar
+    days = [(r.start, r.end) for r in calendar.day_of_week]
+    return calendar.minute[0].start, calendar.hour[0].start, days[0] if days and days[0] != (0, 6) else None
+
+
+async def test_a_new_schedule_is_created_and_recorded_only_after_its_read_back(
+    server, ready, owner_sessionmaker, dispatch_sessionmaker
+) -> None:
+    ctx, _, schedule_id = ready
+    assert await sync(server, dispatch_sessionmaker, ctx, schedule_id) == "synced"
+    found = await in_temporal(server, ctx, schedule_id)
+    assert (found.schedule.state.notes, found.schedule.state.paused) == ("dewpoint generation 1", False)
+    assert (fires(found), found.schedule.spec.timezone_name) == ((0, 9, (1, 5)), "Europe/Paris")
+    assert found.schedule.policies.catchup_window.seconds == 600
+    handle = server.client.get_schedule_handle(schedule_workflow_id(str(ctx.tenant_id), str(schedule_id)))
+    action = (await handle.describe()).schedule.action
+    assert isinstance(action, ScheduleActionStartWorkflow) and action.task_queue == tick.ADMISSION_QUEUE
+    assert action.workflow == "ScheduleTick" and await opened(action.args[0]) == str(schedule_id)  # sealed
+    assert (await stored(owner_sessionmaker, schedule_id))["synced_generation"] == 1
+    async with dispatch_sessionmaker() as s:
+        candidates = (await s.execute(text("select schedule_id from schedule_candidates(50)"))).scalars().all()
+    assert schedule_id not in candidates
+
+
+async def test_each_change_and_a_workflows_disable_reach_temporal_by_generation(
+    server, ready, owner_sessionmaker, api_sessionmaker, dispatch_sessionmaker
+) -> None:
+    ctx, wf, schedule_id = ready
+    await sync(server, dispatch_sessionmaker, ctx, schedule_id)
+    await changed(api_sessionmaker, ctx, schedule_id, cron="30 8 * * *")
+    assert await sync(server, dispatch_sessionmaker, ctx, schedule_id) == "synced"
+    found = await in_temporal(server, ctx, schedule_id)
+    assert (found.schedule.state.notes, fires(found)) == ("dewpoint generation 2", (30, 8, None))
+    await update_workflow(api_sessionmaker, ctx, wf, enabled=False)  # raises the generation of its schedules
+    assert (await stored(owner_sessionmaker, schedule_id))["generation"] == 3
+    assert await sync(server, dispatch_sessionmaker, ctx, schedule_id) == "synced"
+    found = await in_temporal(server, ctx, schedule_id)
+    assert (found.schedule.state.notes, found.schedule.state.paused) == ("dewpoint generation 3", True)
+
+
+async def test_a_row_changed_while_the_sync_works_stays_queued(
+    server, ready, owner_sessionmaker, api_sessionmaker, dispatch_sessionmaker, monkeypatch
+) -> None:
+    ctx, _, schedule_id = ready
+
+    async def meanwhile() -> None:
+        monkeypatch.setattr(schedule_sync, "_after_read", _noop)
+        await changed(api_sessionmaker, ctx, schedule_id, enabled=False)  # generation 2, after the sync read 1
+
+    monkeypatch.setattr(schedule_sync, "_after_read", meanwhile)
+    assert (
+        await sync(server, dispatch_sessionmaker, ctx, schedule_id) == "pending"
+    )  # its marker 1 landed, but the row moved
+    assert (await stored(owner_sessionmaker, schedule_id))["synced_generation"] == 0
+    assert await sync(server, dispatch_sessionmaker, ctx, schedule_id) == "synced"
+    found = await in_temporal(server, ctx, schedule_id)
+    assert (found.schedule.state.notes, found.schedule.state.paused) == ("dewpoint generation 2", True)
+
+
+async def _noop() -> None:
+    return None
+
+
+async def test_a_stale_writers_update_is_discarded_and_it_records_nothing(
+    server, ready, owner_sessionmaker, dispatch_sessionmaker, monkeypatch
+) -> None:
+    """Another writer's update lands between this one's describe and its update: Temporal discards this one without
+    an error, its read-back shows the other's marker, and it records nothing."""
+    ctx, _, schedule_id = ready
+    await sync(server, dispatch_sessionmaker, ctx, schedule_id)
+    await changed_db(owner_sessionmaker, schedule_id)  # generation 2, for this writer to sync
+    temporal_id = schedule_workflow_id(str(ctx.tenant_id), str(schedule_id))
+    service, namespace = server.client.workflow_service, server.client.namespace
+
+    async def other_writer() -> None:
+        monkeypatch.setattr(schedule_sync, "_after_read", _noop)
+        current = await service.describe_schedule(DescribeScheduleRequest(namespace=namespace, schedule_id=temporal_id))
+        current.schedule.state.notes = "dewpoint generation 9"
+        await service.update_schedule(UpdateScheduleRequest(
+            namespace=namespace, schedule_id=temporal_id, schedule=current.schedule,
+            conflict_token=current.conflict_token, identity="another", request_id=str(uuid.uuid4()),
+        ))  # fmt: skip
+
+    monkeypatch.setattr(schedule_sync, "_after_read", other_writer)
+    assert await sync(server, dispatch_sessionmaker, ctx, schedule_id) == "pending"
+    assert (await in_temporal(server, ctx, schedule_id)).schedule.state.notes == "dewpoint generation 9"
+    assert (await stored(owner_sessionmaker, schedule_id))["synced_generation"] == 1
+
+
+async def changed_db(owner: Any, schedule_id: uuid.UUID) -> None:
+    async with owner() as s, s.begin():
+        await s.execute(text("update schedules set generation = generation + 1 where id = :i"), {"i": schedule_id})
+
+
+async def test_a_writer_that_lost_the_leadership_records_nothing(
+    server, ready, owner_sessionmaker, dispatch_sessionmaker
+) -> None:
+    ctx, _, schedule_id = ready
+    assert await sync(server, dispatch_sessionmaker, ctx, schedule_id, Leading(False)) == "not_leading"
+    assert (await in_temporal(server, ctx, schedule_id)).schedule.state.notes == "dewpoint generation 1"
+    assert (await stored(owner_sessionmaker, schedule_id))["synced_generation"] == 0
+
+
+async def test_a_deletion_is_recorded_once_its_absence_is_seen_after_the_call_deadline(
+    server, ready, owner_sessionmaker, api_sessionmaker, dispatch_sessionmaker, monkeypatch
+) -> None:
+    ctx, _, schedule_id = ready
+    await sync(server, dispatch_sessionmaker, ctx, schedule_id)
+    async with api_sessionmaker() as s, s.begin():
+        await tenant_scope(s, ctx.tenant_id)
+        await schedules.delete(s, actor_id=ctx.user.id, schedule=await schedules.found(s, schedule_id))
+    assert await sync(server, dispatch_sessionmaker, ctx, schedule_id) == "deleting"  # the delete sent
+    assert await sync(server, dispatch_sessionmaker, ctx, schedule_id) == "deleting"  # absent, but within the deadline
+    monkeypatch.setattr(schedule_sync, "CALL_DEADLINE", timedelta(0))
+    assert await sync(server, dispatch_sessionmaker, ctx, schedule_id) == "synced"
+    stone = await stored(owner_sessionmaker, schedule_id)
+    assert stone["synced_generation"] == stone["generation"] == 2
+    with pytest.raises(Exception, match="not found|NotFound|NOT_FOUND"):
+        await in_temporal(server, ctx, schedule_id)
+
+
+async def test_a_tick_that_finds_a_tombstone_queues_it_again(
+    ready, owner_sessionmaker, api_sessionmaker, dispatch_sessionmaker
+) -> None:
+    """A stale create can bring a deleted schedule back in Temporal: its tick records `schedule_deleted`, and the sync
+    deletes it again."""
+    ctx, _, schedule_id = ready
+    async with owner_sessionmaker() as s, s.begin():
+        await s.execute(text("update schedules set input = null, deleted_at = now(), generation = 2, "
+                             "synced_generation = 2 where id = :i"), {"i": schedule_id})  # fmt: skip
+    async with dispatch_sessionmaker() as s, s.begin():
+        outcome = await tick.admit_tick(s, KEYS, tenant_id=ctx.tenant_id, schedule_id=schedule_id,
+                                        key=f"sched:{schedule_id}:2026-10-04T09:00:00Z")  # fmt: skip
+    assert outcome == "refused:schedule_deleted"
+    assert (await stored(owner_sessionmaker, schedule_id))["synced_generation"] == 1
+    async with dispatch_sessionmaker() as s:
+        candidates = (await s.execute(text("select schedule_id from schedule_candidates(50)"))).scalars().all()
+    assert schedule_id in candidates
+
+
+async def test_an_update_temporal_refuses_is_recorded_and_retried_later(
+    server, ready, owner_sessionmaker, dispatch_sessionmaker, monkeypatch
+) -> None:
+    ctx, _, schedule_id = ready
+
+    async def refused(*_: Any, **__: Any) -> bool:
+        raise rpc(RPCStatusCode.INVALID_ARGUMENT)
+
+    monkeypatch.setattr(schedule_sync, "_create", refused)
+    counts = await schedule_sync.sync_schedules(dispatch_sessionmaker, server.client, Leading())
+    assert counts.get("failed") == 1
+    row = await stored(owner_sessionmaker, schedule_id)
+    assert (row["sync_error"], row["synced_generation"]) == (schedule_sync.TEMPORAL_REFUSED, 0)
+    async with dispatch_sessionmaker() as s:
+        candidates = (await s.execute(text("select schedule_id from schedule_candidates(50)"))).scalars().all()
+    assert schedule_id not in candidates  # retried after a while, not every cycle
+    async with owner_sessionmaker() as s, s.begin():
+        await s.execute(text("update schedules set sync_error_at = now() - interval '2 minutes' where id = :i"),
+                        {"i": schedule_id})  # fmt: skip
+    monkeypatch.undo()
+    assert (await schedule_sync.sync_schedules(dispatch_sessionmaker, server.client, Leading())).get("synced") == 1
+    assert (await stored(owner_sessionmaker, schedule_id))["sync_error"] is None
+
+
+async def test_firings_missed_past_the_catch_up_window_are_recorded_audited_and_alerted(
+    ready, owner_sessionmaker, dispatch_sessionmaker, tmp_path
+) -> None:
+    """ "No tick is silently dropped" holds within the catch-up window: a Temporal outage longer than it skips the
+    firings it missed. Temporal counts them, and the leader reads that count every five minutes, records an increase
+    on the schedule, audits and alerts on it. The Temporal Schedule here fires every 2 s with a 10 s window (the
+    product's floors are 60 s and 1 minute), so the outage stays short."""
+    import asyncio
+
+    import structlog
+    from temporalio.client import Schedule, ScheduleIntervalSpec, ScheduleOverlapPolicy, SchedulePolicy, ScheduleSpec
+
+    ctx, _, schedule_id = ready
+    async with owner_sessionmaker() as s, s.begin():
+        await s.execute(text("update schedules set synced_generation = generation where id = :i"), {"i": schedule_id})
+    args = ["--db-filename", str(tmp_path / "temporal.db")]
+    temporal_id = schedule_workflow_id(str(ctx.tenant_id), str(schedule_id))
+    async with await WorkflowEnvironment.start_local(
+        data_converter=FIXTURE_CONVERTER, dev_server_extra_args=args
+    ) as env:
+        await env.client.create_schedule(temporal_id, Schedule(
+            action=ScheduleActionStartWorkflow("ScheduleTick", str(schedule_id), id=temporal_id,
+                                               task_queue=tick.ADMISSION_QUEUE),
+            spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=timedelta(seconds=2))]),
+            policy=SchedulePolicy(catchup_window=timedelta(seconds=10), overlap=ScheduleOverlapPolicy.ALLOW_ALL),
+        ))  # fmt: skip
+        assert (await schedule_sync.check_misses(dispatch_sessionmaker, env.client))["missed"] == 0
+    await asyncio.sleep(25)  # past the window: the firings before its last 10 s are skipped
+    async with owner_sessionmaker() as s, s.begin():
+        await s.execute(text("update schedules set misses_checked_at = null where id = :i"), {"i": schedule_id})
+    async with await WorkflowEnvironment.start_local(
+        data_converter=FIXTURE_CONVERTER, dev_server_extra_args=args
+    ) as env:
+        for _ in range(50):
+            found = await schedule_sync.described(env.client, temporal_id)
+            if found is not None and found.missed:
+                break
+            await asyncio.sleep(0.2)
+        with structlog.testing.capture_logs() as logs:
+            counts = await schedule_sync.check_misses(dispatch_sessionmaker, env.client)
+        await env.client.get_schedule_handle(temporal_id).delete()
+    row = await stored(owner_sessionmaker, schedule_id)
+    assert counts["missed"] == row["misses"] > 0 and row["misses_checked_at"] is not None
+    assert [e["event"] for e in logs if e["log_level"] == "error"] == ["schedule_firings_missed"]
+    async with owner_sessionmaker() as s:
+        audit = (await s.execute(text("select details from audit_log where action = 'schedule.missed'"))).scalar_one()
+    assert audit == {"schedule_id": str(schedule_id), "missed": row["misses"]}
```

### Task 16: A tick decides under its schedule's row, held exclusively; nulls refused; its audit names the schedule (the owner's milestone-3 reviews)

**Commit:** `671b6fb` (prototype `proto/2b3a-v2`); the replay's tree was identical: yes.

**Modify:** `backend/src/dewpoint/apps/admission.py`, `backend/src/dewpoint/apps/api/routes/schedules.py`, `backend/src/dewpoint/apps/dispatcher/tick.py`, `backend/tests/apps/api/test_schedules_api.py`, `backend/tests/apps/dispatcher/test_schedule_tick.py`

**What it does:**

From the owner's two M3 reviews, refining tasks 8, 9 and 10:
- A tick read its schedule without a lock, so a disable or a delete could commit between
  its read and its commit, and a request was admitted under a state already replaced. It
  now takes the workflow's admission lock, shared (as admission does: a workflow's change
  takes it exclusively before it writes its schedules' generations, so the two are taken in
  one order), then the schedule's row, exclusively (`FOR UPDATE`), held until it commits: a
  change holding the row first decides the tick, and one arriving later waits for the
  tick's request. Both races tested, for a disable and a delete. The row is never taken
  shared: a tick of a deleted schedule writes it to queue the tombstone again, so two late
  ticks each holding it shared would deadlock on that write (the second review's
  regression: two late ticks of a tombstone both record `schedule_deleted`).
- A PATCH with a null `input`, `enabled`, `mode`, `offset_s`, `time_zone` or
  `catchup_window_s` raised a server error; only `cron` and `every_s` take a null (it
  switches the timing's kind), and any other is a 422 that changes nothing.
- A tick's request, queued or refused, now names its schedule in its `run.request` audit
  entry (admission's `details`).

- [ ] **Step 1: its tests alone, before its code.** Run: `uv run pytest -n 8 tests/apps/api/test_schedules_api.py tests/apps/dispatcher/test_schedule_tick.py`. Replay result (exit 1), shortened:

```
=========================== short test summary info ============================
FAILED tests/apps/dispatcher/test_schedule_tick.py::test_a_change_holding_the_schedule_first_decides_the_tick[disable]
FAILED tests/apps/dispatcher/test_schedule_tick.py::test_a_tick_holding_the_schedule_first_commits_before_the_change[disable]
FAILED tests/apps/dispatcher/test_schedule_tick.py::test_a_change_holding_the_schedule_first_decides_the_tick[delete]
FAILED tests/apps/dispatcher/test_schedule_tick.py::test_a_tick_holding_the_schedule_first_commits_before_the_change[delete]
FAILED tests/apps/dispatcher/test_schedule_tick.py::test_a_ticks_request_names_its_schedule_in_its_audit_entry
FAILED tests/apps/dispatcher/test_schedule_tick.py::test_two_late_ticks_of_a_tombstone_both_record_their_outcome
FAILED tests/apps/api/test_schedules_api.py::test_only_the_timings_kind_may_be_patched_to_null[enabled]
FAILED tests/apps/api/test_schedules_api.py::test_only_the_timings_kind_may_be_patched_to_null[offset_s]
FAILED tests/apps/api/test_schedules_api.py::test_only_the_timings_kind_may_be_patched_to_null[time_zone]
FAILED tests/apps/api/test_schedules_api.py::test_only_the_timings_kind_may_be_patched_to_null[input]
FAILED tests/apps/api/test_schedules_api.py::test_only_the_timings_kind_may_be_patched_to_null[catchup_window_s]
FAILED tests/apps/api/test_schedules_api.py::test_only_the_timings_kind_may_be_patched_to_null[mode]
12 failed, 17 passed in 17.99s
```

- [ ] **Step 2: its code, then the same tests.** Replay result (exit 0), shortened:

```
.............................                                            [100%]
29 passed in 13.31s
```

- [ ] **Step 3: commit.** `git cherry-pick --no-commit 671b6fb && git commit -C 671b6fb`

The diff:

```diff
diff --git a/backend/src/dewpoint/apps/admission.py b/backend/src/dewpoint/apps/admission.py
index ca45455..e89b4fc 100644
--- a/backend/src/dewpoint/apps/admission.py
+++ b/backend/src/dewpoint/apps/admission.py
@@ -174,6 +174,7 @@ async def admit_request(
     input: dict[str, Any],
     rerun: Rerun | None = None,
     csv: CsvStart | None = None,
+    details: dict[str, object] | None = None,
 ) -> Admitted:
     """The request under `idempotency_key`: an exact retry's, or a new one, frozen. A re-run's digest covers its
     `rerun` identity in place of `input`, and a CSV start's its `csv` beside it. Raises IdempotencyConflictError,
@@ -210,10 +211,10 @@ async def admit_request(
         if source in INTERACTIVE:
             raise AdmissionRefusedError(refused.reason, refused.messages) from None
         return await _insert(s, keys, tenant_id, request_id, actor_id, idempotency_key, digested, None, None, refused,
-                             rerun)  # fmt: skip
+                             rerun, extra=details)  # fmt: skip
     await _before_insert()
     admitted = await _insert(s, keys, tenant_id, request_id, actor_id, idempotency_key, digested, frozen.version_id,
-                             frozen.envelope_id, rerun=rerun, extra=frozen.details)  # fmt: skip
+                             frozen.envelope_id, rerun=rerun, extra={**frozen.details, **(details or {})})  # fmt: skip
     if admitted.new:
         await savepoint.commit()
     else:
@@ -224,7 +225,7 @@ async def admit_request(
 
 async def record_refused(
     s: AsyncSession, keys: KeySource, *, tenant_id: uuid.UUID, workflow_id: uuid.UUID, source: str, mode: str,
-    idempotency_key: str, reason: str, messages: list[str],
+    idempotency_key: str, reason: str, messages: list[str], details: dict[str, object] | None = None,
 ) -> RunRequest:  # fmt: skip
     """A durable source's refusal decided before admission, a paused or deleted schedule's tick (§8.2): a `refused`
     request under its key, frozen like any, never lost; an exact retry finds it. Raises IdempotencyConflictError when
@@ -237,7 +238,9 @@ async def record_refused(
     if existing is not None:
         return (await _retry(keys, tenant_id, existing, fields)).request
     refused = _Refused(reason, messages)
-    return (await _insert(s, keys, tenant_id, uuid.uuid4(), None, idempotency_key, fields, None, None, refused)).request
+    inserted = await _insert(s, keys, tenant_id, uuid.uuid4(), None, idempotency_key, fields, None, None, refused,
+                             extra=details)  # fmt: skip
+    return inserted.request
 
 
 async def admitted_under(
diff --git a/backend/src/dewpoint/apps/api/routes/schedules.py b/backend/src/dewpoint/apps/api/routes/schedules.py
index f6764b2..4fd4f31 100644
--- a/backend/src/dewpoint/apps/api/routes/schedules.py
+++ b/backend/src/dewpoint/apps/api/routes/schedules.py
@@ -7,7 +7,7 @@ import uuid
 from typing import Any, Literal
 
 from fastapi import APIRouter, Depends, HTTPException, Response
-from pydantic import BaseModel, ConfigDict, Field
+from pydantic import BaseModel, ConfigDict, Field, model_validator
 from sqlalchemy import select
 from sqlalchemy.ext.asyncio import AsyncSession
 
@@ -19,6 +19,7 @@ from dewpoint.core.http import TenantContext, get_db, require
 from dewpoint.core.models.schedules import Schedule
 
 router = APIRouter(prefix="/api/v1", tags=["schedules"])
+NULLABLE = frozenset({"cron", "every_s"})  # a null switches the timing's kind
 
 
 class ScheduleIn(BaseModel):
@@ -34,9 +35,18 @@ class ScheduleIn(BaseModel):
 
 
 class SchedulePatch(BaseModel):
-    """Only the fields given change; `cron` or `every_s` given as null switches the timing's kind."""
+    """Only the fields given change; `cron` or `every_s` given as null switches the timing's kind. Any other field
+    given as null is refused (422): it has no null to become (the owner's M3 review)."""
 
     model_config = ConfigDict(extra="forbid")
+
+    @model_validator(mode="after")
+    def _nulls(self) -> "SchedulePatch":
+        nulled = sorted(k for k in self.model_fields_set - NULLABLE if getattr(self, k) is None)
+        if nulled:
+            raise ValueError(f"{', '.join(nulled)} can't be null")
+        return self
+
     cron: str | None = Field(default=None, max_length=120)
     every_s: int | None = None
     offset_s: int | None = None
diff --git a/backend/src/dewpoint/apps/dispatcher/tick.py b/backend/src/dewpoint/apps/dispatcher/tick.py
index 896ff50..090b89a 100644
--- a/backend/src/dewpoint/apps/dispatcher/tick.py
+++ b/backend/src/dewpoint/apps/dispatcher/tick.py
@@ -5,9 +5,17 @@ are parsed from it with the codec's grammar, the argument must name the same sch
 that tenant's scope.
 
 In one transaction, under the tick key `sched:<schedule_id>:<nominal time>`, so every retry finds what the first
-recorded: an enabled schedule's tick is admitted as any durable source is (queued, or a `refused` request with
-admission's reason); one whose schedule was disabled before its pause reached Temporal, or deleted (its tombstone), is a
-`refused` request (`schedule_paused`, `schedule_deleted`); an `erasing` tenant's is an audited skip, never a request.
+recorded, and decided under the schedule's row lock (the owner's M3 reviews), which a change holds until it commits: a
+disable or a delete either commits first and decides the tick, or waits until the tick's request is in. The tick takes
+it exclusively: a tick of a deleted schedule writes the row (it queues the tombstone again), and two ticks holding it
+shared would each wait to write, a deadlock. The workflow's
+admission lock is taken first, shared, as admission takes it: a workflow's change takes it exclusively before it
+writes its schedules' generations, so both take the two in the same order.
+
+An enabled schedule's tick is admitted as any durable source is (queued, or a `refused` request with admission's
+reason); one whose schedule was disabled before its pause reached Temporal, or deleted (its tombstone), is a `refused`
+request (`schedule_paused`, `schedule_deleted`); either way its `run.request` audit entry names the schedule. An
+`erasing` tenant's tick is an audited skip, never a request.
 A platform-wide failure (the database, a key) raises, and the workflow retries it without limit (§2.5): a tick still
 unadmitted 10 minutes after its time alerts."""
 
@@ -17,7 +25,7 @@ from dataclasses import dataclass
 from datetime import UTC, datetime, timedelta
 
 import structlog
-from sqlalchemy import update
+from sqlalchemy import select, update
 from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
 from temporalio import activity
 from temporalio.exceptions import ApplicationError
@@ -30,6 +38,7 @@ from dewpoint.core.db import tenant_scope
 from dewpoint.core.models.requests import RunRequest
 from dewpoint.core.models.schedules import Schedule
 from dewpoint.core.models.tenancy import Tenant
+from dewpoint.core.workflows.service import lock_for_admission
 from dewpoint.engine.runtime.ids import schedule_of
 
 log = structlog.get_logger("dewpoint.dispatcher.tick")
@@ -49,6 +58,10 @@ class TickInput:
     nominal: str  # the nominal time, UTC, whole seconds: `2026-10-04T09:00:00Z`
 
 
+async def _after_schedule_locked() -> None:
+    """Runs once a tick holds its schedule's row. A no-op; the race tests start a competing change here."""
+
+
 class ScheduleUnknownError(Exception):
     """A tick's workflow id names no schedule of its tenant, not even a tombstone: nothing to record it against."""
 
@@ -69,15 +82,24 @@ async def admit_tick(
     """The tick's outcome, recorded in the caller's transaction: `queued`, `refused:<reason>`, `skipped:<reason>`, or
     `recorded` when its key already holds another outcome of this tick (it was paused then, enabled since)."""
     await tenant_scope(s, tenant_id)
-    schedule = await s.get(Schedule, schedule_id, populate_existing=True)  # row-level security: that tenant's only
-    if schedule is None:
+    found = await s.get(Schedule, schedule_id, populate_existing=True)  # row-level security: that tenant's only
+    if found is None:
         raise ScheduleUnknownError(str(schedule_id))
+    await lock_for_admission(s, tenant_id, found.workflow_id)  # a schedule's workflow never changes
+    schedule = (
+        await s.execute(
+            select(Schedule).where(Schedule.id == schedule_id).with_for_update()
+            .execution_options(populate_existing=True)
+        )
+    ).scalar_one()  # exclusive, held until the caller commits: never a shared lock it would upgrade  # fmt: skip
+    await _after_schedule_locked()
     tenant = await s.get(Tenant, tenant_id, populate_existing=True)
     if tenant is None or tenant.status == "erasing":
         details: dict[str, object] = {"schedule_id": str(schedule_id), "tick": key, "reason": admission.TENANT_ERASING}
         await audit.record(s, tenant_id=tenant_id, actor_id=None, action="schedule.tick_skipped",
                            target_type="schedule", target_id=str(schedule_id), details=details)  # fmt: skip
         return f"skipped:{admission.TENANT_ERASING}"
+    named: dict[str, object] = {"schedule_id": str(schedule_id)}  # its request's audit entry names the schedule
     try:
         if schedule.deleted_at is not None:  # a stale create may have brought it back in Temporal: delete it again
             await s.execute(
@@ -92,14 +114,14 @@ async def admit_tick(
             )  # fmt: skip
             refused = await admission.record_refused(
                 s, keys, tenant_id=tenant_id, workflow_id=schedule.workflow_id, source="schedule", mode=schedule.mode,
-                idempotency_key=key, reason=reason, messages=[said],
+                idempotency_key=key, reason=reason, messages=[said], details=named,
             )  # fmt: skip
             return _outcome(refused)
         cipher = ClaimCipher(keys, purpose=schedules.INPUT_PURPOSE)
         given = json.loads(await cipher.open(str(tenant_id), str(schedule_id), schedule.input))
         admitted = await admission.admit_request(
             s, keys, tenant_id=tenant_id, workflow_id=schedule.workflow_id, source="schedule", actor_id=None,
-            mode=schedule.mode, idempotency_key=key, input=given,
+            mode=schedule.mode, idempotency_key=key, input=given, details=named,
         )  # fmt: skip
     except admission.IdempotencyConflictError:
         return "recorded"
diff --git a/backend/tests/apps/api/test_schedules_api.py b/backend/tests/apps/api/test_schedules_api.py
index 1a740fd..91094eb 100644
--- a/backend/tests/apps/api/test_schedules_api.py
+++ b/backend/tests/apps/api/test_schedules_api.py
@@ -161,3 +161,17 @@ async def test_deleting_leaves_a_tombstone(keyed_app, workflow, owner_sessionmak
     assert (await editor.delete(url)).status_code == 404
     assert (await editor.get(schedules_url(ctx, wf))).json()["schedules"] == []
     assert [d["schedule_id"] for d in await audited(owner_sessionmaker, "schedule.delete")] == [created["id"]]
+
+
+@pytest.mark.parametrize("field", ["input", "enabled", "mode", "offset_s", "time_zone", "catchup_window_s"])
+async def test_only_the_timings_kind_may_be_patched_to_null(
+    keyed_app, workflow, owner_sessionmaker, api_settings, field: str
+) -> None:
+    """The owner's M3 review: a null for any field but `cron` or `every_s` (which switch the timing's kind) is a 422,
+    never a server error, and changes nothing."""
+    ctx, wf = workflow
+    editor = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "editor")
+    created = (await editor.post(schedules_url(ctx, wf), json=BODY)).json()
+    answer = await editor.patch(schedule_url(ctx, created["id"]), json={field: None})
+    assert (answer.status_code, answer.json()["error"]) == (422, "invalid")
+    assert (await row(owner_sessionmaker, created["id"]))["generation"] == 1
diff --git a/backend/tests/apps/dispatcher/test_schedule_tick.py b/backend/tests/apps/dispatcher/test_schedule_tick.py
index b8cd847..12d85bc 100644
--- a/backend/tests/apps/dispatcher/test_schedule_tick.py
+++ b/backend/tests/apps/dispatcher/test_schedule_tick.py
@@ -5,6 +5,7 @@ No tick is silently dropped: an enabled schedule's is a request (queued, or refu
 source); a schedule disabled before its pause reached Temporal gives a `refused` request (`schedule_paused`), a deleted
 one's tombstone one (`schedule_deleted`); an `erasing` tenant's is an audited skip, never a request."""
 
+import asyncio
 import uuid
 from typing import Any
 
@@ -117,3 +118,132 @@ async def test_an_erasing_tenants_tick_is_an_audited_skip(ready, owner_sessionma
         details = (await s.execute(text("select details from audit_log where action = 'schedule.tick_skipped'"))
                    ).scalar_one()  # fmt: skip
     assert details == {"schedule_id": str(schedule_id), "tick": KEY.format(schedule_id), "reason": "tenant_erasing"}
+
+
+async def lock_waiters(owner: Any) -> int:
+    async with owner() as s:
+        query = text("select count(*) from pg_stat_activity where wait_event_type = 'Lock'")
+        return int((await s.execute(query)).scalar_one())
+
+
+async def until_waiting(owner: Any) -> None:
+    for _ in range(300):
+        if await lock_waiters(owner):
+            return
+        await asyncio.sleep(0.01)
+    raise AssertionError("nothing waited on the schedule")
+
+
+CHANGES = {
+    "disable": ("schedule_paused", lambda s, ctx, schedule: schedules.update(
+        s, KEYS, actor_id=ctx.user.id, schedule=schedule, changes={"enabled": False})),
+    "delete": ("schedule_deleted", lambda s, ctx, schedule: schedules.delete(
+        s, actor_id=ctx.user.id, schedule=schedule)),
+}  # fmt: skip
+
+
+@pytest.mark.parametrize("change", list(CHANGES))
+async def test_a_change_holding_the_schedule_first_decides_the_tick(
+    ready, owner_sessionmaker, api_sessionmaker, dispatch_sessionmaker, change
+) -> None:
+    """The owner's M3 review: a tick decides under the schedule's row lock, which a change holds until it commits. A
+    disable or a delete that holds it first makes the tick wait, then record what it committed."""
+    ctx, _, schedule_id = ready
+    reason, apply = CHANGES[change]
+    async with api_sessionmaker() as s, s.begin():
+        await tenant_scope(s, ctx.tenant_id)
+        await apply(s, ctx, await schedules.found(s, schedule_id))
+        pending = asyncio.create_task(ticked(dispatch_sessionmaker, ctx, schedule_id))
+        await until_waiting(owner_sessionmaker)
+    assert await pending == f"refused:{reason}"
+    assert [(r["status"], r["reason"]) for r in await requests(owner_sessionmaker)] == [("refused", reason)]
+
+
+@pytest.mark.parametrize("change", list(CHANGES))
+async def test_a_tick_holding_the_schedule_first_commits_before_the_change(
+    ready, owner_sessionmaker, api_sessionmaker, dispatch_sessionmaker, monkeypatch, change
+) -> None:
+    """A tick that holds the row first admits its request; the disable or the delete waits for it, so no request is
+    ever admitted under a schedule state that a committed change had already replaced."""
+    ctx, _, schedule_id = ready
+    _, apply = CHANGES[change]
+    started: list[asyncio.Task[Any]] = []
+
+    async def changing() -> None:
+        async with api_sessionmaker() as s, s.begin():
+            await tenant_scope(s, ctx.tenant_id)
+            await apply(s, ctx, await schedules.found(s, schedule_id))
+
+    async def meanwhile() -> None:
+        started.append(asyncio.create_task(changing()))
+        await until_waiting(owner_sessionmaker)
+
+    monkeypatch.setattr(tick, "_after_schedule_locked", meanwhile)
+    assert await ticked(dispatch_sessionmaker, ctx, schedule_id) == "queued"
+    await started[0]
+    [r] = await requests(owner_sessionmaker)
+    assert r["status"] == "queued"
+    async with owner_sessionmaker() as s:
+        changed_at = (await s.execute(text("select updated_at from schedules where id = :i"), {"i": schedule_id})
+                      ).scalar_one()  # fmt: skip
+    assert changed_at > r["queued_at"]  # the change committed after the tick's request
+
+
+async def test_a_ticks_request_names_its_schedule_in_its_audit_entry(
+    ready, owner_sessionmaker, api_sessionmaker, dispatch_sessionmaker
+) -> None:
+    """The owner's M3 review: the `run.request` entry of a tick's request, queued or refused, names the schedule."""
+    ctx, wf, schedule_id = ready
+    await ticked(dispatch_sessionmaker, ctx, schedule_id)
+    await changed(owner_sessionmaker, schedule_id, "update schedules set enabled = false where id = :i")
+    async with dispatch_sessionmaker() as s, s.begin():
+        await tick.admit_tick(s, KEYS, tenant_id=ctx.tenant_id, schedule_id=schedule_id,
+                              key=f"sched:{schedule_id}:2026-10-04T10:00:00Z")  # fmt: skip
+    await changed(owner_sessionmaker, schedule_id, "update schedules set enabled = true where id = :i")
+    await update(api_sessionmaker, ctx, wf, enabled=False)
+    async with dispatch_sessionmaker() as s, s.begin():
+        await tick.admit_tick(s, KEYS, tenant_id=ctx.tenant_id, schedule_id=schedule_id,
+                              key=f"sched:{schedule_id}:2026-10-04T11:00:00Z")  # fmt: skip
+    async with owner_sessionmaker() as s:
+        entries = (await s.execute(text("select details from audit_log where action = 'run.request' "
+                                        "order by seq"))).scalars().all()  # fmt: skip
+    assert [(e["status"], e.get("reason"), e["schedule_id"]) for e in entries] == [
+        ("queued", None, str(schedule_id)),
+        ("refused", "schedule_paused", str(schedule_id)),
+        ("refused", "workflow_disabled", str(schedule_id)),
+    ]
+
+
+async def test_two_late_ticks_of_a_tombstone_both_record_their_outcome(
+    ready, owner_sessionmaker, dispatch_sessionmaker, monkeypatch
+) -> None:
+    """The owner's M3 review: a tick of a deleted schedule writes its row (it queues the tombstone again), so a tick
+    takes the row exclusively before it decides. Under a shared lock, two late ticks of other nominal times would each
+    hold it and wait to write: a deadlock that aborts one. Here the first holds the row while the second arrives."""
+    ctx, _, schedule_id = ready
+    await changed(owner_sessionmaker, schedule_id, "update schedules set input = null, deleted_at = now(), "
+                                                   "generation = 2, synced_generation = 2 where id = :i")  # fmt: skip
+    second: list[asyncio.Task[Any]] = []
+    holding = asyncio.Event()
+
+    async def at(hour: int) -> str:
+        async with dispatch_sessionmaker() as s, s.begin():
+            return await tick.admit_tick(s, KEYS, tenant_id=ctx.tenant_id, schedule_id=schedule_id,
+                                         key=f"sched:{schedule_id}:2026-10-04T{hour:02d}:00:00Z")  # fmt: skip
+
+    async def meanwhile() -> None:
+        if second:  # the second tick holds the row too: give the first time to try its write
+            holding.set()
+            await asyncio.sleep(0.3)
+            return
+        second.append(asyncio.create_task(at(10)))
+        for _ in range(300):  # until the second holds the row too, or waits on it
+            if holding.is_set() or await lock_waiters(owner_sessionmaker):
+                return
+            await asyncio.sleep(0.01)
+        raise AssertionError("the second tick neither held nor waited on the schedule")
+
+    monkeypatch.setattr(tick, "_after_schedule_locked", meanwhile)
+    assert await at(9) == "refused:schedule_deleted"
+    assert await second[0] == "refused:schedule_deleted"
+    assert [r["reason"] for r in await requests(owner_sessionmaker)] == ["schedule_deleted"] * 2
```

**Checkpoint (milestone 3).** Focused: as milestone 2, plus the whole contract file, schedules, the tick (its database,
server and replay tests) and the sync (956; 968 after Task 16); the migrations 0028 → 0030 → 0028 → 0030. The owner
ruled on the gate (Tasks 10, 11 and 15), held the milestone twice — a tick's unlocked read, a PATCH's nulls and the
audit's schedule, then the shared row lock's deadlock (both in Task 16) — recorded the erasure transition and the sync's
latency for §7.9, and approved it (2026-10-04).

## Milestone 4 — Proofs, Compose and docs

### Task 17: CSV starts and schedule ticks end to end, real keys, no canary anywhere; catch-up; the gate

**Commit:** `805aa11` (prototype `proto/2b3a-v2`); the replay's tree was identical: yes.

**Create:** `backend/tests/apps/dispatcher/test_schedule_tick_gate.py`, `backend/tests/apps/dispatcher/test_triggers_end_to_end.py`

**What it does:**

On the CLI dev server (engine 2b spec §8.1, §8.2, §12):
- a CSV start and a schedule's tick, each a run end to end through the API, the sync, the
  dispatcher's own admission worker, the dispatcher and a versioned engine worker, with the
  keyring's real keys everywhere. Canaries in a sensitive CSV cell, in a file header (so in
  the mapping too) and in a schedule's fixed input appear in no execution's whole raw
  history, no projection or stored row in plain, and no log line; each request's input,
  decrypted with the real keys, holds its canary, and every history scanned names the
  tenant, so the scan reads real data whole;
- an outage shorter than a schedule's catch-up window: every missed time fires when the
  server is back, and each is admitted once, under its own key, with no gap.
And in a production deployment with its gate off, a tick is queued, the dispatcher starts
nothing, and it starts once the gate is on.

- [ ] **Step 1: its tests alone, before its code.** Run: `uv run pytest -n 8 tests/apps/dispatcher/test_schedule_tick_gate.py tests/apps/dispatcher/test_triggers_end_to_end.py`. Replay result (exit 0), shortened:

```
...                                                                      [100%]
3 passed in 23.23s
```

- [ ] **Step 2: its code, then the same tests.** Replay result (exit 0), shortened:

```
...                                                                      [100%]
3 passed in 20.80s
```

Evidence beyond the replay: each request's input, decrypted with the real keys, holds its canary, and every history
scanned names the tenant, so the scan reads real data, whole; the canary is in none.

- [ ] **Step 3: commit.** `git cherry-pick --no-commit 805aa11 && git commit -C 805aa11`

The diff:

```diff
diff --git a/backend/tests/apps/dispatcher/test_schedule_tick_gate.py b/backend/tests/apps/dispatcher/test_schedule_tick_gate.py
new file mode 100644
index 0000000..5f3e935
--- /dev/null
+++ b/backend/tests/apps/dispatcher/test_schedule_tick_gate.py
@@ -0,0 +1,44 @@
+# SPDX-License-Identifier: Apache-2.0
+"""A schedule's ticks while a production deployment's gate is off (engine 2b spec §2.5, §8.2): a tick is a durable
+source, so admission records its request, queued; the dispatcher starts nothing while the gate is off, and starts it
+once the gate is on. Waiting isn't failing."""
+
+from sqlalchemy import text
+
+from dewpoint.apps import schedules
+from dewpoint.apps.dispatcher import dispatch, tick
+from dewpoint.core.db import tenant_scope
+from dewpoint.core.platform.service import PRODUCTION, record_environment
+from tests.apps.dispatcher.support import BUILD, workers
+from tests.apps.test_admission import KEYS, TOKEN, current, published
+from tests.apps.test_runs import FakeClient
+
+
+async def test_a_tick_while_the_gate_is_off_is_queued_and_starts_once_it_is_on(
+    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings
+) -> None:
+    async with owner_sessionmaker() as s, s.begin():
+        await record_environment(s, environment=PRODUCTION, namespace="default")
+    ctx, wf = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings)
+    await current(dispatch_sessionmaker)
+    await workers(owner_sessionmaker)
+    async with api_sessionmaker() as s, s.begin():
+        await tenant_scope(s, ctx.tenant_id)
+        created = await schedules.create(
+            s, KEYS, tenant_id=ctx.tenant_id, actor_id=ctx.user.id, workflow_id=wf,
+            timing={"cron": "0 9 * * *", "every_s": None, "offset_s": 0, "time_zone": "UTC", "catchup_window_s": 600},
+            mode="live", input={"token": TOKEN}, enabled=True,
+        )  # fmt: skip
+    async with dispatch_sessionmaker() as s, s.begin():
+        outcome = await tick.admit_tick(s, KEYS, tenant_id=ctx.tenant_id, schedule_id=created.id,
+                                        key=f"sched:{created.id}:2026-10-04T09:00:00Z")  # fmt: skip
+    assert outcome == "queued"
+    client = FakeClient()
+    await dispatch.dispatch_once(dispatch_sessionmaker, client, KEYS, api_settings, BUILD)
+    assert client.started == []  # the gate is off: it waits, queued
+    async with owner_sessionmaker() as s, s.begin():
+        await s.execute(text("update platform_settings set production_runs = true"))
+    assert await dispatch.dispatch_once(dispatch_sessionmaker, client, KEYS, api_settings, BUILD) == {"started": 1}
+    async with owner_sessionmaker() as s:
+        status = (await s.execute(text("select status from run_requests"))).scalar_one()
+    assert status == "started"
diff --git a/backend/tests/apps/dispatcher/test_triggers_end_to_end.py b/backend/tests/apps/dispatcher/test_triggers_end_to_end.py
new file mode 100644
index 0000000..c399899
--- /dev/null
+++ b/backend/tests/apps/dispatcher/test_triggers_end_to_end.py
@@ -0,0 +1,256 @@
+# SPDX-License-Identifier: Apache-2.0
+"""2b-3a's proofs on Temporal's CLI dev server (engine 2b spec §8.1, §8.2, §12):
+
+- a CSV start and a schedule's tick, each a run end to end through the API, the sync, the dispatcher's own admission
+  worker, the dispatcher and a versioned engine worker, with the keyring's real keys everywhere; canaries in a
+  sensitive CSV cell, in a file header (so in the mapping too) and in a schedule's fixed input appear in no execution's
+  whole raw history, no projection, no stored row in plain and no log line;
+- a server outage shorter than a schedule's catch-up window: each missed time fires when it's back, and each is
+  admitted once, under its own key."""
+
+import asyncio
+import uuid
+from collections.abc import AsyncIterator
+from datetime import UTC, datetime, timedelta
+from pathlib import Path
+from typing import Any
+
+import pytest
+import structlog
+from sqlalchemy import text
+from temporalio.client import (
+    Client,
+    Schedule,
+    ScheduleActionStartWorkflow,
+    ScheduleBackfill,
+    ScheduleIntervalSpec,
+    ScheduleOverlapPolicy,
+    SchedulePolicy,
+    ScheduleSpec,
+)
+from temporalio.testing import WorkflowEnvironment
+
+from dewpoint.apps import schedules
+from dewpoint.apps.codec import data_converter
+from dewpoint.apps.dispatcher import dispatch, main, schedule_sync, tick
+from dewpoint.apps.worker.store import DbRunStore
+from dewpoint.core.claims import service as claims
+from dewpoint.core.claims.cipher import ClaimCipher
+from dewpoint.core.crypto.kek import KekSet
+from dewpoint.core.crypto.keyring import Keyring
+from dewpoint.core.crypto.keys import KeyringKeys
+from dewpoint.core.db import tenant_scope
+from dewpoint.core.tenancy.service import ensure_tenant_keys
+from dewpoint.engine.handles import StoredClaim, resolve_value
+from dewpoint.engine.runtime.ids import schedule_workflow_id
+from tests.apps.api.helpers import member_client
+from tests.apps.dispatcher.support import BUILD, workers
+from tests.apps.dispatcher.test_dev_server import until_ended
+from tests.apps.test_admission import KEYS, SCHEMA, current, published
+from tests.apps.test_workflow_ops import create, publish
+from tests.apps.worker.test_real_server import serving
+from tests.support.graphs import G, ref
+from tests.support.keys import FIXTURE_CONVERTER
+
+pytestmark = pytest.mark.usefixtures("development_deployment")
+CELL, HEADER, FIXED = "CSVcell-c4n4ry-7Q2", "Hdr-c4n4ry-K9", "Sched-c4n4ry-3Z"
+CANARIES = (CELL, HEADER, FIXED)
+PSK = {"header": "PSK", "name": "psk", "type": "string", "required": True, "sensitive": True}
+CSV = {"columns": [{"header": "Site", "name": "site", "type": "string", "required": True}, PSK]}
+CSV_GRAPH = (
+    G().node("l", "flow.loop@1", {"items": ref("trigger.rows")})
+    .node("s", "testkit.echo@1", {"value": ref("item.site")}).edge("l", "s", "body")
+    .node("p", "testkit.echo@1", {"value": ref("item.psk")}).edge("l", "p", "body")
+).data() | {"settings": {"input_schema": {"type": "object", "properties": {}}, "csv": CSV}}  # fmt: skip
+SCHEDULED_GRAPH = G().node("a", "testkit.echo@1", {"value": ref("trigger.token")}).data() | {
+    "settings": {"input_schema": SCHEMA}
+}
+
+
+class Leading:
+    async def leading(self) -> bool:
+        return True
+
+
+@pytest.fixture(scope="module")
+async def server() -> AsyncIterator[WorkflowEnvironment]:
+    async with await WorkflowEnvironment.start_local(data_converter=FIXTURE_CONVERTER) as environment:
+        yield environment
+
+
+async def raw_histories(client: Client) -> list[bytes]:
+    """Every execution the namespace holds, each history whole, every event as the server stores it."""
+    out: list[bytes] = []
+    async for listed in client.list_workflows():
+        history = await client.get_workflow_handle(listed.id, run_id=listed.run_id).fetch_history()
+        out.append(b"".join(event.SerializeToString() for event in history.events))
+    return out
+
+
+async def plain_rows(owner: Any) -> str:
+    """The projection and every row 2b-3a writes, as text: run requests, runs and steps, the audit log, schedules,
+    uploads and run inputs (their ciphertexts included, which must not hold a canary in plain)."""
+    async with owner() as s:
+        tables = ("run_requests", "runs", "run_steps", "audit_log", "schedules", "csv_uploads", "csv_mappings",
+                  "run_inputs", "step_outputs", "run_secret_index")  # fmt: skip
+        dumped = [str((await s.execute(text(f"select * from {t}"))).all()) for t in tables]  # noqa: S608
+    return "\n".join(dumped)
+
+
+async def test_a_csv_start_and_a_schedules_tick_end_to_end_with_the_keyrings_real_keys_leak_no_canary(
+    server, app, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, worker_sessionmaker,
+    api_settings,
+) -> None:  # fmt: skip
+    ctx, csv_wf = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings, CSV_GRAPH)
+    scheduled_wf = await create(api_sessionmaker, ctx, SCHEDULED_GRAPH, name="scheduled")
+    assert (await publish(api_sessionmaker, ctx, scheduled_wf, api_settings)).version is not None
+    await current(dispatch_sessionmaker)
+    await workers(owner_sessionmaker)
+    keyring = Keyring(KekSet.from_settings(api_settings))
+    async with admin_sessionmaker() as s, s.begin():
+        assert ctx.tenant_id in await ensure_tenant_keys(s, keyring)  # a real data key, wrapped by the KEK
+    dispatch_keys, worker_keys = KeyringKeys(dispatch_sessionmaker, keyring), KeyringKeys(worker_sessionmaker, keyring)
+    target, namespace = server.client.service_client.config.target_host, server.client.namespace
+    dispatcher = await Client.connect(target, namespace=namespace, data_converter=data_converter(dispatch_keys))
+    worker = await Client.connect(target, namespace=namespace, data_converter=data_converter(worker_keys))
+    editor, _ = await member_client(app, owner_sessionmaker, api_settings, ctx.tenant_id, "editor")
+    base = f"/api/v1/t/{ctx.tenant_id}"
+    with structlog.testing.capture_logs() as logs:
+        upload = await editor.post(f"{base}/workflows/{csv_wf}/csv-uploads", content=f"Site,{HEADER}\nparis,{CELL}\n",
+                                   headers={"Content-Type": "text/csv"})  # fmt: skip
+        assert upload.status_code == 201, upload.text
+        started = await editor.post(f"{base}/workflows/{csv_wf}/runs", headers={"Idempotency-Key": "csv-1"}, json={
+            "csv": {"upload_id": upload.json()["upload_id"], "mapping": {"site": "Site", "psk": HEADER}},
+        })  # fmt: skip
+        assert started.status_code == 202, started.text
+        scheduled = await editor.post(f"{base}/workflows/{scheduled_wf}/schedules", json={
+            "every_s": 3600, "input": {"token": FIXED, "site": "lyon"},
+        })  # fmt: skip
+        assert scheduled.status_code == 201, scheduled.text
+        schedule_id = uuid.UUID(scheduled.json()["id"])
+        assert await schedule_sync.sync_one(dispatch_sessionmaker, dispatcher, Leading(), ctx.tenant_id,
+                                            schedule_id) == "synced"  # fmt: skip
+        hour = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
+        handle = dispatcher.get_schedule_handle(schedule_workflow_id(str(ctx.tenant_id), str(schedule_id)))
+        async with (
+            main.admission_worker(dispatcher, dispatch_sessionmaker, dispatch_keys),
+            serving(
+                worker,
+                DbRunStore(worker_sessionmaker, worker_keys),  # type: ignore[arg-type]
+            ),
+        ):
+            await handle.backfill(ScheduleBackfill(start_at=hour - timedelta(seconds=30), end_at=hour,
+                                                   overlap=ScheduleOverlapPolicy.ALLOW_ALL))  # fmt: skip
+            tick_request = await until_requested(owner_sessionmaker, f"sched:{schedule_id}:")
+            for _ in range(20):
+                done = await dispatch.dispatch_once(dispatch_sessionmaker, dispatcher, dispatch_keys, api_settings,
+                                                    BUILD)  # fmt: skip
+                if not done:
+                    break
+            csv_run = await until_ended(editor, f"{base}/runs/{started.json()['id']}")
+            tick_run = await until_ended(editor, f"{base}/runs/{tick_request}")
+        await handle.delete()
+    assert (csv_run["status"], tick_run["status"], tick_run["request"]["source"]) == ("succeeded", "succeeded",
+                                                                                       "schedule")  # fmt: skip
+    # the canaries were in the data: each request's input, decrypted with the real keys, holds its canary
+    csv_input = await decrypted_input(dispatch_sessionmaker, dispatch_keys, ctx.tenant_id, started.json()["id"])
+    tick_input = await decrypted_input(dispatch_sessionmaker, dispatch_keys, ctx.tenant_id, tick_request)
+    assert (csv_input["rows"], tick_input["token"]) == ([{"site": "paris", "psk": CELL}], FIXED)
+    raws = await raw_histories(server.client)
+    assert len(raws) >= 3  # the CSV run, the tick, the scheduled run
+    assert all(str(ctx.tenant_id).encode() in raw for raw in raws)  # this tenant's real histories, read whole
+    assert not [c for c in CANARIES for raw in raws if c.encode() in raw]
+    rows = await plain_rows(owner_sessionmaker)
+    assert not [c for c in CANARIES if c in rows]
+    assert not [c for c in CANARIES for entry in logs if c in str(entry)]
+    for run in (csv_run, tick_run):
+        steps = (await editor.get(f"{base}/runs/{run['id']}")).json()["steps"]
+        assert steps and not [c for c in (CELL, FIXED) if c in str(steps)]
+
+
+async def decrypted_input(dispatch: Any, keys: Any, tenant_id: uuid.UUID, request_id: str) -> Any:
+    """A request's whole input, its envelope read and its claims resolved with `keys`, in memory only."""
+    cipher = ClaimCipher(keys)
+    async with dispatch() as s, s.begin():
+        await tenant_scope(s, tenant_id)
+
+        async def fetch(claim_id: str) -> StoredClaim:
+            got = await claims.read_request_claim(s, cipher, tenant_id, request_id=uuid.UUID(request_id),
+                                                  claim_id=uuid.UUID(claim_id))  # fmt: skip
+            return StoredClaim(got.value, got.sensitive_pointers)
+
+        envelope = await claims.read_envelope(s, cipher, tenant_id, request_id=uuid.UUID(request_id))
+        return (await resolve_value(envelope, fetch)).value
+
+
+async def until_requested(owner: Any, prefix: str) -> str:
+    for _ in range(150):
+        async with owner() as s:
+            found = (await s.execute(text("select id from run_requests where idempotency_key like :p"),
+                                     {"p": f"{prefix}%"})).scalar_one_or_none()  # fmt: skip
+        if found is not None:
+            return str(found)
+        await asyncio.sleep(0.2)
+    raise AssertionError("the tick admitted nothing")
+
+
+async def test_a_short_outage_fires_each_missed_time_and_admits_each_once(
+    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings, tmp_path: Path
+) -> None:
+    """Within the catch-up window, no tick is dropped: the times missed while the server was down fire when it's back,
+    each with its own nominal time, and each is admitted once, under its own key. (The Temporal Schedule fires every
+    2 s here, past the product's 60 s floor, to keep the outage short.)"""
+    ctx, wf = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings)
+    await current(dispatch_sessionmaker)
+    async with api_sessionmaker() as s, s.begin():
+        await tenant_scope(s, ctx.tenant_id)
+        created = await schedules.create(
+            s, KEYS, tenant_id=ctx.tenant_id, actor_id=ctx.user.id, workflow_id=wf,
+            timing={"cron": None, "every_s": 60, "offset_s": 0, "time_zone": "UTC", "catchup_window_s": 600},
+            mode="live", input={"token": "t0ken-value-1", "site": "a"}, enabled=True,
+        )  # fmt: skip
+    temporal_id = schedule_workflow_id(str(ctx.tenant_id), str(created.id))
+    args = ["--db-filename", str(tmp_path / "temporal.db")]
+    async with await WorkflowEnvironment.start_local(
+        data_converter=FIXTURE_CONVERTER, dev_server_extra_args=args
+    ) as env:
+        async with main.admission_worker(env.client, dispatch_sessionmaker, KEYS):
+            await env.client.create_schedule(temporal_id, Schedule(
+                action=ScheduleActionStartWorkflow("ScheduleTick", str(created.id), id=temporal_id,
+                                                   task_queue=tick.ADMISSION_QUEUE),
+                spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=timedelta(seconds=2))]),
+                policy=SchedulePolicy(catchup_window=timedelta(minutes=1), overlap=ScheduleOverlapPolicy.ALLOW_ALL),
+            ))  # fmt: skip
+            await admitted(owner_sessionmaker, 2)
+    down = datetime.now(UTC)
+    await asyncio.sleep(7)  # about three firings missed, well within the window
+    async with await WorkflowEnvironment.start_local(
+        data_converter=FIXTURE_CONVERTER, dev_server_extra_args=args
+    ) as env:
+        async with main.admission_worker(env.client, dispatch_sessionmaker, KEYS):
+            times = await admitted(owner_sessionmaker, 0, after=down, at_least=3)
+            await env.client.get_schedule_handle(temporal_id).delete()
+    stamps = await nominal_times(owner_sessionmaker)
+    assert len(stamps) == len(set(stamps))  # each time admitted once
+    gaps = {(b - a).total_seconds() for a, b in zip(stamps, stamps[1:], strict=False)}
+    assert gaps == {2.0}, stamps  # every time fired, the missed ones included: no gap
+    assert len([t for t in times if t > down]) >= 3
+
+
+async def nominal_times(owner: Any) -> list[datetime]:
+    async with owner() as s:
+        keys = (await s.execute(text("select idempotency_key from run_requests"))).scalars().all()
+    stamps = [key.split(":", 2)[2] for key in keys]  # `sched:<schedule id>:<nominal time>`
+    return sorted(datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC) for stamp in stamps)
+
+
+async def admitted(owner: Any, n: int, *, after: datetime | None = None, at_least: int = 0) -> list[datetime]:
+    """Until `n` requests exist, or `at_least` of them have nominal times after `after`."""
+    for _ in range(150):
+        times = await nominal_times(owner)
+        if (after is None and len(times) >= n) or (
+            after is not None and len([t for t in times if t > after]) >= at_least
+        ):
+            return times
+        await asyncio.sleep(0.2)
+    raise AssertionError(f"admitted only {await nominal_times(owner)}")
```

### Task 18: What a CSV's claimed rows cost a run, counted; sensitive cells past the secret index refuse the start

**Commit:** `7d4dd0b` (prototype `proto/2b3a-v2`); the replay's tree was identical: yes.

**Create:** `backend/tests/apps/dispatcher/test_csv_rows_cost.py`

**Modify:** `backend/tests/apps/test_admission_csv.py`

**What it does:**

The owner's ruling 3, with the 10,000-row figures estimated from measured 1,000 and 2,500-row points (owner,
2026-10-04): CEL over a plain cell of claimed rows is one cel.evaluate per row, plus the loop's count, against the count
alone without it; and a file whose sensitive cells pass the index's bound is refused with secret_index_limit, keeping
no claim and leaving its upload unconsumed.

- [ ] **Step 1: its tests alone, before its code.** Run: `uv run pytest -n 8 tests/apps/dispatcher/test_csv_rows_cost.py tests/apps/test_admission_csv.py`. Replay result (exit 0), shortened:

```
..................                                                       [100%]
18 passed in 31.19s
```

- [ ] **Step 2: its code, then the same tests.** Replay result (exit 0), shortened:

```
..................                                                       [100%]
18 passed in 31.02s
```

Evidence beyond the replay: with the expected counts set to the rows and 0, both cost cases failed (`assert 1 == 0`);
with the index's bound at 3, the refusal test failed (the start was admitted).

- [ ] **Step 3: commit.** `git cherry-pick --no-commit 7d4dd0b && git commit -C 7d4dd0b`

The diff:

```diff
diff --git a/backend/tests/apps/dispatcher/test_csv_rows_cost.py b/backend/tests/apps/dispatcher/test_csv_rows_cost.py
new file mode 100644
index 0000000..23287d4
--- /dev/null
+++ b/backend/tests/apps/dispatcher/test_csv_rows_cost.py
@@ -0,0 +1,81 @@
+# SPDX-License-Identifier: Apache-2.0
+"""What a CSV's rows cost a run once they pass 64 KiB (engine 2b spec §8.1, revision 8; the owner's ruling 3): the rows
+are one claim, iterated by handle, and the page activity is deferred, so CEL over a plain cell runs in `cel.evaluate`
+once per row. This counts that work, which the plan's 10,000-row measurement timed: one evaluation per row with a
+per-row condition, plus the loop's count, against the count alone without it."""
+
+from collections import Counter
+from collections.abc import AsyncIterator
+from typing import Any
+
+import pytest
+from sqlalchemy import text
+from temporalio.testing import WorkflowEnvironment
+
+from dewpoint.apps.dispatcher import dispatch
+from dewpoint.apps.worker.store import DbRunStore
+from tests.apps.api.helpers import member_client
+from tests.apps.dispatcher.support import BUILD, workers
+from tests.apps.dispatcher.test_dev_server import until_ended
+from tests.apps.test_admission import KEYS, current, published
+from tests.apps.worker.test_real_server import serving
+from tests.support.graphs import G, cel, ref
+from tests.support.keys import FIXTURE_CONVERTER
+
+pytestmark = pytest.mark.usefixtures("development_deployment")
+ROWS = 90  # with an 800-character note each, their list passes 64 KiB: one claim
+COLUMNS = [{"header": "Site", "name": "site", "type": "string", "required": True},
+           {"header": "Status", "name": "status", "type": "string", "required": True},
+           {"header": "Note", "name": "note", "type": "string", "required": True}]  # fmt: skip
+
+
+@pytest.fixture(scope="module")
+async def server() -> AsyncIterator[WorkflowEnvironment]:
+    async with await WorkflowEnvironment.start_local(data_converter=FIXTURE_CONVERTER) as environment:
+        yield environment
+
+
+def graph(condition: bool) -> dict[str, Any]:
+    g = G().node("l", "flow.loop@1", {"items": ref("trigger.rows")})
+    if condition:
+        g.node("c", "flow.if@1", {"condition": cel("item.status == 'active'")}).edge("l", "c", "body")
+        g.node("e", "testkit.echo@1", {"value": ref("item.site")}).edge("c", "e", "true")
+    else:
+        g.node("e", "testkit.echo@1", {"value": ref("item.site")}).edge("l", "e", "body")
+    return g.data() | {"settings": {"input_schema": {"type": "object", "properties": {}}, "csv": {"columns": COLUMNS}}}
+
+
+@pytest.mark.parametrize(("condition", "evaluations"), [(True, ROWS + 1), (False, 1)])
+async def test_cel_over_a_plain_cell_of_claimed_rows_is_one_evaluation_per_row(
+    server, app, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, worker_sessionmaker,
+    api_settings, condition: bool, evaluations: int,
+) -> None:  # fmt: skip
+    app.state.keys = KEYS
+    ctx, wf = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings, graph(condition))
+    await current(dispatch_sessionmaker)
+    await workers(owner_sessionmaker)
+    client, _ = await member_client(app, owner_sessionmaker, api_settings, ctx.tenant_id, "operator")
+    rows = [f"site-{i},{'active' if i % 2 else 'idle'},{'n' * 800}" for i in range(ROWS)]
+    data = ("Site,Status,Note\n" + "\n".join(rows) + "\n").encode()
+    base = f"/api/v1/t/{ctx.tenant_id}"
+    upload = await client.post(f"{base}/workflows/{wf}/csv-uploads", content=data, headers={"Content-Type": "text/csv"})
+    csv = {"upload_id": upload.json()["upload_id"], "mapping": {c["name"]: c["header"] for c in COLUMNS}}
+    started = await client.post(f"{base}/workflows/{wf}/runs", headers={"Idempotency-Key": "cost"}, json={"csv": csv})
+    assert started.status_code == 202, started.text
+    async with owner_sessionmaker() as s:
+        largest = (await s.execute(text("select max(length(ciphertext)) from run_inputs where owner_run_id = :r"),
+                                   {"r": started.json()["id"]})).scalar_one()  # fmt: skip
+    assert largest > 64 * 1024  # the rows are one claim
+    async with serving(server.client, DbRunStore(worker_sessionmaker, KEYS)):  # type: ignore[arg-type]
+        assert await dispatch.dispatch_once(dispatch_sessionmaker, server.client, KEYS, api_settings, BUILD) == {
+            "started": 1
+        }
+        run = await until_ended(client, f"{base}/runs/{started.json()['id']}")
+    assert run["status"] == "succeeded"
+    counted: Counter[str] = Counter()
+    async for w in server.client.list_workflows(f"WorkflowId STARTS_WITH 't:{ctx.tenant_id}:run:'"):
+        for event in (await server.client.get_workflow_handle(w.id, run_id=w.run_id).fetch_history()).events:
+            if event.HasField("activity_task_scheduled_event_attributes"):
+                counted[event.activity_task_scheduled_event_attributes.activity_type.name] += 1
+    assert counted["cel.evaluate"] == evaluations
+    assert counted["testkit.echo.v1"] == (ROWS // 2 if condition else ROWS)
diff --git a/backend/tests/apps/test_admission_csv.py b/backend/tests/apps/test_admission_csv.py
index 4ddc3f1..698d82f 100644
--- a/backend/tests/apps/test_admission_csv.py
+++ b/backend/tests/apps/test_admission_csv.py
@@ -19,6 +19,7 @@ from sqlalchemy import text
 
 from dewpoint.apps import admission, csv_uploads
 from dewpoint.apps.inputs import RESERVED_INPUT
+from dewpoint.core.claims import secret_index
 from dewpoint.core.claims import service as claims
 from dewpoint.core.claims.cipher import ClaimCipher
 from dewpoint.core.db import tenant_scope
@@ -247,6 +248,21 @@ async def test_a_row_that_breaks_a_rule_refuses_the_start_unless_invalid_rows_ar
     assert kept["errors"] == [{"row": 1, "column": "vlan", "code": "not_integer"}]
 
 
+async def test_sensitive_cells_past_the_secret_index_bound_refuse_the_start_and_keep_nothing(
+    csv_ready, owner_sessionmaker, api_sessionmaker, monkeypatch
+) -> None:
+    """Each sensitive cell joins the run tree's index (2b-3a task 12): a file whose cells pass its bound is refused with
+    `secret_index_limit`, its claims discarded and its upload left for another start."""
+    ctx, wf = csv_ready
+    upload = await staged(api_sessionmaker, ctx, wf, b"Site,VLAN,PSK\nparis,10,psk-one-1\nlyon,2,psk-two-2\n")
+    monkeypatch.setattr(secret_index, "MAX_STRINGS", 2)  # the input's token and one cell fit; the second cell doesn't
+    with pytest.raises(admission.AdmissionRefusedError) as refused:
+        await admit(api_sessionmaker, ctx, wf, csv=start(upload))
+    assert refused.value.reason == "secret_index_limit"
+    assert await count(owner_sessionmaker, "run_inputs") == 0
+    assert (await upload_row(owner_sessionmaker, upload))["consumed_by"] is None
+
+
 async def test_a_csv_start_still_refuses_rows_in_its_input(csv_ready, api_sessionmaker) -> None:
     ctx, wf = csv_ready
     upload = await staged(api_sessionmaker, ctx, wf)
```

### Task 19: A schedule through the Compose dispatcher; CSV starts, schedules and their limits in the operations docs

**Commit:** `5d1a21d` (prototype `proto/2b3a-v2`); the replay's tree was identical: yes.

**Create:** `backend/tests/deploy/test_compose_schedule_proof.py`, `deploy/compose/ci/schedule-proof.py`

**Modify:** `.github/workflows/ci.yml`, `docs/operations/deployment.md`, `docs/operations/runs.md`

**What it does:**

One bounded e2e step (timeout 5 minutes): a schedule every 60 s in Europe/Paris, made as the API's login, so the
API's image must hold the IANA time zone data; its first run waited for at most 150 s (about 1 to 2.5 more minutes of
the hosted runner per e2e run). runs.md: starting a run from a CSV, schedules, and the limits (the measured and
estimated cost of claimed rows, sensitive cells' admission, the leader's serial schedule calls). deployment.md: the
dispatcher's tick worker, unversioned on dewpoint-admission.

- [ ] **Step 1: its tests alone, before its code.** Run: `uv run pytest -n 8 tests/deploy/test_compose_schedule_proof.py`. Replay result (exit 1), shortened:

```
version it was saved against, and when an upload found it no longer fits the active version's declaration
encrypted in `run_inputs` under a third role, `csv`, beside the request's envelope and claims; like the envelope, never
a claim (no pointer, at most one per request), and kept and deleted with its request
interval, a time zone, a catch-up window, a mode and the fixed input sealed under `schedule.input`; a generation every
API change raises and the one the sync last completed (by a read-back of its marker); a tombstone a deletion leaves, so
a late tick still finds what it belonged to
schedules whose generation passes the one its sync last completed (a failed one retried after a minute), and the
enabled ones whose missed firings it hasn't read from Temporal for five minutes
<frozen importlib._bootstrap_external>:950: FileNotFoundError: [Errno 2] No such file or directory: '<replay>/deploy/compose/ci/schedule-proof.py'
=========================== short test summary info ============================
FAILED tests/deploy/test_compose_schedule_proof.py::test_ci_proves_a_schedule_through_the_compose_dispatcher
FAILED tests/deploy/test_compose_schedule_proof.py::test_a_zone_the_image_lacks_is_refused_before_anything_is_scheduled
FAILED tests/deploy/test_compose_schedule_proof.py::test_the_schedule_proof_waits_for_the_first_scheduled_run_to_succeed
3 failed in 9.03s
```

- [ ] **Step 2: its code, then the same tests.** Replay result (exit 0), shortened:

```
...                                                                      [100%]
3 passed in 11.76s
```

- [ ] **Step 3: commit.** `git cherry-pick --no-commit 5d1a21d && git commit -C 5d1a21d`

The diff:

```diff
diff --git a/.github/workflows/ci.yml b/.github/workflows/ci.yml
index 496d6cd..5ee444f 100644
--- a/.github/workflows/ci.yml
+++ b/.github/workflows/ci.yml
@@ -118,6 +118,17 @@ jobs:
           # Admitted as the dispatcher's login, started by the Compose dispatcher, run by the worker: exit 0 only when
           # the run the database records succeeded.
           docker compose exec -T dispatcher dewpoint dev run "$workflow" --tenant "$tenant" --wait 120
+      - name: A schedule through the Compose dispatcher (engine 2b spec §8.2, §12)
+        working-directory: deploy/compose
+        timeout-minutes: 5
+        run: |
+          set -a; . ./.env; set +a
+          read -r tenant workflow < <(docker compose run --rm -T api python - < ci/seed-workflow.py | tail -n 1)
+          # Every 60 s in Europe/Paris, as the API's login: the API's image must hold the time zone data to accept it.
+          # The dispatcher's sync creates its Temporal Schedule and its admission worker admits each firing: exit 0
+          # only once the first scheduled run succeeded, within 150 s.
+          schedule=$(docker compose run --rm -T api python - create "$tenant" "$workflow" < ci/schedule-proof.py | tail -n 1)
+          docker compose run --rm -T api python - wait "$tenant" "$schedule" 150 < ci/schedule-proof.py
       - uses: pnpm/action-setup@b906affcce14559ad1aafd4ab0e942779e9f58b1 # v4  (version comes from package.json "packageManager")
         with: { package_json_file: frontend/package.json }
       - uses: actions/setup-node@v4
diff --git a/backend/tests/deploy/test_compose_schedule_proof.py b/backend/tests/deploy/test_compose_schedule_proof.py
new file mode 100644
index 0000000..056b9a8
--- /dev/null
+++ b/backend/tests/deploy/test_compose_schedule_proof.py
@@ -0,0 +1,84 @@
+# SPDX-License-Identifier: Apache-2.0
+"""CI's schedule proof (engine 2b spec §8.2, §12; 2b-3a task 14): `deploy/compose/ci/schedule-proof.py` makes a
+schedule of the seeded workflow, every 60 s in a non-UTC time zone (the API's image must hold the time zone data), as
+the API's login, then waits for its first run to succeed through the Compose dispatcher's sync, its admission worker,
+the dispatcher and the worker. Here the script runs against the test database, a tick through admission, the dispatcher
+and a worker; CI runs the same against the Compose stack."""
+
+import importlib.util
+from typing import Any
+
+import pytest
+import yaml
+
+from dewpoint.apps.dispatcher import tick
+from dewpoint.apps.dispatcher.dispatch import dispatch_once
+from dewpoint.apps.worker.store import DbRunStore
+from dewpoint.core.crypto.kek import KekSet
+from dewpoint.core.crypto.keyring import Keyring
+from dewpoint.core.crypto.keys import KeyringKeys
+from tests.apps.dispatcher.support import BUILD, workers
+from tests.apps.test_admission import current
+from tests.apps.worker.harness import workers as engine_workers
+from tests.deploy.test_compose_seed import CI, ROOT, seeding
+from tests.support.registry import sync_test_plugins
+
+PROOF = ROOT / "deploy" / "compose" / "ci" / "schedule-proof.py"
+
+
+def proving() -> Any:
+    spec = importlib.util.spec_from_file_location("schedule_proof", PROOF)
+    assert spec is not None and spec.loader is not None
+    module = importlib.util.module_from_spec(spec)
+    spec.loader.exec_module(module)
+    return module
+
+
+@pytest.mark.usefixtures("development_deployment")
+async def test_the_schedule_proof_waits_for_the_first_scheduled_run_to_succeed(
+    env, owner_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, worker_sessionmaker, api_settings
+) -> None:
+    await sync_test_plugins(admin_sessionmaker)
+    tenant_id, workflow_id = await seeding().seed(api_settings)
+    proof = proving()
+    schedule_id = await proof.create(api_settings, tenant_id, workflow_id)
+    assert await proof.state(api_settings, tenant_id, schedule_id) == (None, None)
+    await current(dispatch_sessionmaker)
+    await workers(owner_sessionmaker)
+    keyring = Keyring(KekSet.from_settings(api_settings))
+    dispatch_keys, worker_keys = KeyringKeys(dispatch_sessionmaker, keyring), KeyringKeys(worker_sessionmaker, keyring)
+    async with dispatch_sessionmaker() as s, s.begin():  # the Compose dispatcher's admission worker, a firing's tick
+        assert await tick.admit_tick(s, dispatch_keys, tenant_id=tenant_id, schedule_id=schedule_id,
+                                     key=f"sched:{schedule_id}:2026-10-04T09:00:00Z") == "queued"  # fmt: skip
+    assert (await proof.state(api_settings, tenant_id, schedule_id))[0] == "queued"
+    async with engine_workers(env.client, DbRunStore(worker_sessionmaker, worker_keys)):
+        assert await dispatch_once(dispatch_sessionmaker, env.client, dispatch_keys, api_settings, BUILD) == {
+            "started": 1
+        }
+        assert await proof.wait(api_settings, tenant_id, schedule_id, 30)
+
+
+async def test_a_zone_the_image_lacks_is_refused_before_anything_is_scheduled(
+    owner_sessionmaker, admin_sessionmaker, api_settings, monkeypatch
+) -> None:
+    """An image without the IANA data would refuse `Europe/Paris` at once, so the CI step fails at its first line."""
+    from dewpoint.apps import schedules
+
+    await sync_test_plugins(admin_sessionmaker)
+    tenant_id, workflow_id = await seeding().seed(api_settings)
+    monkeypatch.setattr(schedules, "_zones", lambda: frozenset({"UTC"}))
+    with pytest.raises(schedules.ScheduleRefusedError) as refused:
+        await proving().create(api_settings, tenant_id, workflow_id)
+    assert refused.value.detail["problems"] == [{"field": "time_zone", "code": "time_zone_unknown"}]
+
+
+def test_ci_proves_a_schedule_through_the_compose_dispatcher() -> None:
+    steps = yaml.safe_load(CI.read_text())["jobs"]["e2e"]["steps"]
+    [proof] = [s for s in steps if s.get("name", "").startswith("A schedule through the Compose dispatcher")]
+    assert proof["timeout-minutes"] <= 5  # bounded
+    script = proof["run"]
+    assert "python - < ci/seed-workflow.py" in script
+    assert "python - create" in script and "< ci/schedule-proof.py" in script
+    assert "python - wait" in script and " 150 " in script
+    names = [s.get("name", "") for s in steps]
+    assert names.index(proof["name"]) > names.index("A run through the Compose dispatcher (engine 2b spec §12)")
diff --git a/deploy/compose/ci/schedule-proof.py b/deploy/compose/ci/schedule-proof.py
new file mode 100644
index 0000000..b512f8b
--- /dev/null
+++ b/deploy/compose/ci/schedule-proof.py
@@ -0,0 +1,87 @@
+# SPDX-License-Identifier: Apache-2.0
+"""CI's schedule proof (engine 2b spec §8.2, §12; 2b-3a): a schedule of the synthetic workflow `seed-workflow.py` made,
+every 60 s in a non-UTC time zone, so the API's image must hold the IANA time zone data to accept it; the Compose
+dispatcher's sync creates its Temporal Schedule and its admission worker admits each firing. Run in the API's image,
+as the API's database login:
+
+    docker compose run --rm -T api python - create <tenant> <workflow> < ci/schedule-proof.py   # prints its id
+    docker compose run --rm -T api python - wait <tenant> <schedule> <seconds> < ci/schedule-proof.py
+
+`wait` exits 0 once the schedule's first run succeeded, and 1 when the time is up, printing only states and fixed
+codes. Nothing here is real data."""
+
+import asyncio
+import sys
+import uuid
+
+from sqlalchemy import text
+
+from dewpoint.apps import schedules
+from dewpoint.core.config import Settings, get_settings
+from dewpoint.core.crypto.kek import KekSet
+from dewpoint.core.crypto.keyring import Keyring
+from dewpoint.core.crypto.keys import KeyringKeys
+from dewpoint.core.db import make_engine, make_sessionmaker, tenant_scope
+
+ZONE = "Europe/Paris"  # not UTC: accepted only when the image holds the time zone data
+
+
+async def create(settings: Settings, tenant_id: uuid.UUID, workflow_id: uuid.UUID) -> uuid.UUID:
+    """The schedule's id: every 60 s, in `ZONE`, made by the tenant's owner."""
+    engine = make_engine(settings.database_url)
+    try:
+        sessionmaker = make_sessionmaker(engine)
+        keys = KeyringKeys(sessionmaker, Keyring(KekSet.from_settings(settings)))
+        async with sessionmaker() as s, s.begin():
+            await tenant_scope(s, tenant_id)
+            owner = (
+                await s.execute(text("select user_id from memberships where tenant_id = :t and role = 'owner'"),
+                                {"t": tenant_id})
+            ).scalar_one()  # fmt: skip
+            timing = {"cron": None, "every_s": 60, "offset_s": 0, "time_zone": ZONE, "catchup_window_s": 600}
+            created = await schedules.create(s, keys, tenant_id=tenant_id, actor_id=owner, workflow_id=workflow_id,
+                                             timing=timing, mode="live", input={}, enabled=True)  # fmt: skip
+        return created.id
+    finally:
+        await engine.dispose()
+
+
+async def state(settings: Settings, tenant_id: uuid.UUID, schedule_id: uuid.UUID) -> tuple[str | None, str | None]:
+    """The first scheduled run's state (its run's status once it started, else its request's), and the schedule's
+    sync code, if its last sync failed."""
+    engine = make_engine(settings.database_url)
+    try:
+        async with make_sessionmaker(engine)() as s:
+            await tenant_scope(s, tenant_id)
+            found = (
+                await s.execute(
+                    text("select coalesce(r.status, q.status) from run_requests q left join runs r on r.id = q.id "
+                         "and q.status = 'started' where q.idempotency_key like :key order by q.queued_at limit 1"),
+                    {"key": f"sched:{schedule_id}:%"},
+                )
+            ).scalar_one_or_none()  # fmt: skip
+            code = (
+                await s.execute(text("select sync_error from schedules where id = :i"), {"i": schedule_id})
+            ).scalar_one_or_none()
+        return found, code
+    finally:
+        await engine.dispose()
+
+
+async def wait(settings: Settings, tenant_id: uuid.UUID, schedule_id: uuid.UUID, seconds: int) -> bool:
+    found, code = None, None
+    for _ in range(seconds):
+        found, code = await state(settings, tenant_id, schedule_id)
+        if found in ("succeeded", "failed", "cancelled", "refused", "dead"):
+            break
+        await asyncio.sleep(1)
+    print(f"first scheduled run: {found}; last sync: {code or 'ok'}")
+    return found == "succeeded"
+
+
+if __name__ == "__main__":
+    command, tenant, *rest = sys.argv[1:]
+    if command == "create":
+        print(asyncio.run(create(get_settings(), uuid.UUID(tenant), uuid.UUID(rest[0]))))
+    else:
+        sys.exit(0 if asyncio.run(wait(get_settings(), uuid.UUID(tenant), uuid.UUID(rest[0]), int(rest[1]))) else 1)
diff --git a/docs/operations/deployment.md b/docs/operations/deployment.md
index 9fe7ea7..cd86635 100644
--- a/docs/operations/deployment.md
+++ b/docs/operations/deployment.md
@@ -221,10 +221,17 @@ Compose runs Temporal's dev server (the `temporal` service: its state in SQLite
 UI at <http://127.0.0.1:8233>), one `worker` and one `dispatcher`, which Compose restarts unless it's stopped.
 Production uses a Temporal cluster instead.
 
-Its `migrate` service upgrades the schema, records the environment (`DEWPOINT_ENVIRONMENT`, `production` unless set)
-with the Temporal namespace (`DEWPOINT_TEMPORAL_NAMESPACE`, `default` unless set), and gives every tenant a data key as
-`dewpoint_admin_login`. Set the namespace in `.env`: every service takes it from there, and the worker exits 2 unless
-its own matches the record. Ordinary Compose is `production`, so no run starts; CI and local development use the
+The dispatcher also runs schedules' ticks: its own Temporal worker, on the task queue `dewpoint-admission`, outside the
+engine's Worker Deployment and unversioned, admits each firing as the dispatch login; its leader keeps the Temporal
+Schedules in step with the `schedules` table. A schedule's time zone is checked against the image's IANA time zone
+data, which the shipped image holds (CI schedules a run in `Europe/Paris` through Compose to prove it). Don't edit a
+Dewpoint schedule in Temporal's UI: the dispatcher only tells its own updates apart, by the `dewpoint generation <n>`
+note it writes.
+
+Compose's `migrate` service upgrades the schema, records the environment (`DEWPOINT_ENVIRONMENT`, `production` unless
+set) with the Temporal namespace (`DEWPOINT_TEMPORAL_NAMESPACE`, `default` unless set), and gives every tenant a data
+key as `dewpoint_admin_login`. Set the namespace in `.env`: every service takes it from there, and the worker exits 2
+unless its own matches the record. Ordinary Compose is `production`, so no run starts; CI and local development use the
 development override, on a database of their own (a project's own volume), with synthetic data only:
 
 ```bash
diff --git a/docs/operations/runs.md b/docs/operations/runs.md
index e4140bd..8e60f31 100644
--- a/docs/operations/runs.md
+++ b/docs/operations/runs.md
@@ -9,8 +9,9 @@ Every step's progress is copied into the database (`run_steps`), which is what t
 never shown.
 
 A run starts as a **request**: the run API and `dewpoint dev run` admit it, in their own transaction, and
-`dewpoint dispatcher` starts it on Temporal within its tenant's slots. Nothing else starts a run. Schedules, webhooks
-and CSV starts arrive with sub-project 2b-3.
+`dewpoint dispatcher` starts it on Temporal within its tenant's slots. Nothing else starts a run: a CSV start and a
+schedule's tick are admitted the same way ([below](#starting-a-run-from-a-csv), [schedules](#schedules)); webhooks
+arrive with sub-project 2b-3b.
 
 ## Starting a run
 
@@ -38,6 +39,73 @@ form: its typed top-level fields, each with its `type`, whether it's `required`,
 and `default`, and `x-dewpoint-picker` as `picker`. A sensitive field never shows a value its schema holds:
 `default_masked` and `enum_masked` say there is one. 409 `not_active` without an active version.
 
+## Starting a run from a CSV
+
+A workflow that takes a file declares it in `graph.settings.csv`: its columns (the header, a variable name, a type
+among `string`, `integer`, `number`, `boolean`, `mac`, `ip`, `cidr` and `enum`, whether it's required, a default, and
+whether it's sensitive) and its caps, `max_rows` and `max_bytes`, at most the platform's 10,000 rows and 5 MiB. The run
+sees `trigger.rows` (one object per row, each column by its name) and `trigger.row_count`.
+
+- **Publish checks the declaration:** unique headers and identifier names; an enum's values, and only an enum's; a
+  default that's its type's canonical value (`mac` in lowercase colon form, `ip` and `cidr` as Python's `ipaddress`
+  writes them), never beside `required`. A sensitive column takes neither a default nor `values`: both would be
+  written into the workflow in plain text. `rows` and `row_count` are reserved: no input schema may declare them, and
+  no caller may send them. A CSV workflow's input schema stays plain at its root (`type`, `properties`, `required`,
+  `additionalProperties`, `$defs` and annotations), since any other root keyword could refuse the rows. Such a workflow
+  is started only with its file: it can't be a sub-flow, a failure handler or scheduled.
+- **Uploading:** `POST /api/v1/t/{tenant}/workflows/{workflow}/csv-uploads` (`run.start`) with the file as a raw
+  `text/csv` body, read as it arrives and refused one byte past the declaration's `max_bytes` (413 `too_large`). It's
+  read as data only: UTF-8 with an optional BOM, the delimiter detected among comma, semicolon and tab, strict quoting,
+  unique headers, a field as long as the file allows. A file that can't be read is 422 with its code (`csv_encoding`,
+  `csv_empty`, `csv_duplicate_header`, `csv_malformed`, `csv_too_many_rows`, `csv_too_large`). The file is staged,
+  encrypted, for one hour, for its uploader only. The answer gives the headers, the proposed mapping (declared names to
+  headers), what keeps it from building rows, a preview of the first rows without the sensitive columns, and the
+  first 100 errors with their count, each a row number, a column and a code, never a cell.
+- **The saved default mapping:** `PUT …/workflows/{workflow}/csv-mapping` (`trigger.manage`) saves one per workflow,
+  encrypted. An upload proposes it while it fits the active version's declaration; one a later version no longer fits
+  is reported `stale`, with each column's code, and never applied, until a new one is saved.
+- **Starting:** the run API's body takes `"csv": {"upload_id", "mapping", "skip_invalid"}` beside `input`. The rows are
+  built against the version the request freezes: each cell converted to its type (an empty one is its default, or
+  `required`); with `skip_invalid`, a row that breaks a rule is skipped and recorded, else the start is refused
+  (`input_invalid`, naming the first rows, columns and codes). Sensitive cells are claimed as any sensitive value is.
+  The upload is used once: its retry under the same key returns its request, to its uploader only; any other start of
+  it is 409 `upload_consumed`. 404 `upload_not_found` for an upload that isn't yours or this workflow's, 410
+  `upload_expired`, 422 `csv_mapping_invalid`. A re-run takes the original rows while they're retained, or a new file.
+- **What the run keeps:** the mapping, the file's headers and the skipped rows (each one's number and first code, the
+  first 100 errors in detail, and their count), encrypted beside its input; its details show them (`run.view`). The
+  audit entry keeps a tenant-keyed digest of the file and counts.
+- **A loop over the rows** needs no `declassify` entry: their count is `trigger.row_count`, already public. Rows that
+  together pass 64 KiB are one claim, and the loop gives each iteration a handle to its row: a step's reference to a
+  cell is read in its own activity, but CEL over a cell (a condition on `item.status`) runs in `cel.evaluate`, one
+  activity per row ([measured](#limits-in-this-build)).
+
+## Schedules
+
+`POST /api/v1/t/{tenant}/workflows/{workflow}/schedules` (`trigger.manage`, editors and up) schedules the workflow's
+active version: `cron` or `every_s`, `time_zone` (an IANA name), `catchup_window_s` (1 minute to 24 hours, 10 minutes
+by default), `mode`, a fixed `input` checked against the active version, and `enabled`. `GET` lists and reads them
+(`workflow.view`), never with their input; `PATCH` changes any field (only `cron` and `every_s` take a null, which
+switches the timing's kind); `DELETE` removes one.
+
+- **Cron, as Temporal reads it:** five fields (minute, hour, day of the month, month, day of the week), each `*`, a
+  number, a range, `*/step` or `a-b/step`, or a list; months and days by name in any case; Sunday is 0 or 7. A day of
+  the month and a day of the week together are refused: Temporal requires both to match, where cron usually takes
+  either. A local time a daylight-saving change skips doesn't fire that day; one it repeats fires once, at its second
+  occurrence. An interval is at least 60 seconds.
+- **The dispatcher keeps Temporal in step.** Every change raises the schedule's `generation`, and so does disabling or
+  enabling its workflow; the dispatcher's leader applies it to the Temporal Schedule (paused when the schedule or its
+  workflow is disabled) and marks it synced (`synced_generation`) only once Temporal shows its `dewpoint generation
+  <n>` note. Editing a schedule directly in Temporal isn't supported. A sync Temporal refuses is shown as
+  `sync_error` and retried after a minute. There's no "run now": start the workflow instead.
+- **Each firing is a tick.** It's admitted as any request, under the key `sched:<schedule>:<nominal time>`, so a retry
+  or a backfill over a time that already fired admits nothing new. A tick of a schedule disabled or deleted before
+  Temporal heard of it is a `refused` request (`schedule_paused`, `schedule_deleted`); one of a disabled workflow is
+  refused as admission refuses it; a tenant being erased skips it, audited. A tick that can't be admitted (the database,
+  a key) is retried without limit, and alerts after 10 minutes. Its request's audit entry names the schedule.
+- **Missed firings.** Within the catch-up window, firings missed while Temporal was down fire when it's back, each
+  with its own time. Past it they're skipped: Temporal counts them, and the schedule's `misses` shows the count, read
+  every five minutes, audited and alerted on.
+
 ## The dispatcher
 
 `dewpoint dispatcher` starts admitted requests. Run one or more. It needs `DEWPOINT_DATABASE_URL` with a login in the
@@ -407,6 +475,20 @@ retry settings (`max_attempts` and `timeout_s` can be overridden per step), and
   wait for the next task.
 - `flow.delay` waits 0 to 30 days, and `wait_until` takes instants from year 1 to 9999 in UTC. A value outside that,
   resolved at run time, fails the step with `type_mismatch`.
+- A CSV holds at most 10,000 rows and 5 MiB (its declaration may lower both), and an upload is kept for one hour. The
+  API reads a file whole: one at the cap can take up to about 72 MB of memory while it's read.
+- A loop over a CSV's rows, once they pass 64 KiB, runs each step's activity per row as any loop does, and CEL over a
+  cell adds one `cel.evaluate` per row. On a development machine (Temporal's dev server, one worker), 1,000 rows took
+  2 minutes 15 seconds with a condition on a cell and 55 seconds without; 2,500 rows, 5 minutes 40 seconds and
+  2 minutes 25 seconds. The time grows with the rows, slightly faster than they do: 10,000 rows would take about 23 to
+  25 minutes with the condition and 10 to 12 without (estimated from those two, not measured).
+- Each sensitive cell is its own claim and joins the run tree's secret index, while the start request waits: 2,500
+  rows with five sensitive columns took 7 seconds to admit (12,501 claims), so 10,000 would take about 30 seconds. Ten
+  sensitive columns of distinct values in 10,000 rows reach the index's 100,000 strings (`secret_index_limit`).
+- A schedule fires at most once a minute, and its catch-up window is 1 minute to 24 hours. Each cycle, the
+  dispatcher's leader syncs at most 50 changed schedules (up to three Temporal calls each) and reads at most 50
+  schedules' misses, one call after another, each bounded at 10 seconds: a Temporal that answers slowly delays
+  dispatch as well.
 
 ## If the database is unavailable
```

**Checkpoint (milestone 4).** Focused: the end-to-end and gate proofs, the cost test, the CSV admission tests (21) and
`tests/deploy` (12); ruff. The owner waived the 10,000-row run, kept the cap for v1, and approved it as a prototype
checkpoint (2026-10-04), which doesn't claim the Compose proof has passed CI: this branch's pull request runs it. Then
the whole suite and the static checks once, and a fresh whole-branch review.
