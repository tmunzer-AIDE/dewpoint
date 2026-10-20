# Editor UI 4e-2a: the run form's backend — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The API the run form calls (the run form design §4): a start and a re-run that name the version they
confirmed (B14), a start form that names its version, a staged CSV checked again under other columns (B11), every CSV
error counted by column and problem, and a same-rows re-run that keeps its rows' record.

**Architecture:**
- **The confirmed version (B14).** `StartIn` and `RerunIn` take `expected_version_id`. Admission refuses it once
  another version is active (`version_changed`, with the active one), after the workflow's own checks and before the
  build's. The request digest covers it only when it's given, so every other request keeps its exact bytes.
- **The start form** names its version: `version_number`, `published_at`, and `published_by`, the publisher's email.
- **A CSV checked again (B11).** `POST …/csv-uploads/{upload}/preview` opens the caller's staged file and describes it
  under a new mapping, as the upload does, against the active version's declaration, in a CSV slot.
- **Every error counted.** `build_rows` counts each error by its column and code as it finds it (`ErrorGroup`); the
  upload's and the preview's answers add `error_groups` and `rows_with_errors`, and both name the `version_id` they
  checked.
- **A same-rows re-run** copies its original's CSV record in admission, so its page shows its rows.
- **Typed answers.** A start's and a re-run's answer is `RequestOut`; the upload's, the preview's and the saved
  mapping's have models of their own. The web client is regenerated.

**Tech Stack:** FastAPI with pydantic response models (`extra="forbid"`), SQLAlchemy 2 (async) over PostgreSQL 16 with
row-level security, pytest with testcontainers and pytest-xdist, and openapi-typescript for the web client's types.

**Spec:** `docs/superpowers/specs/2026-10-19-editor-4e2-run-form-design.md`: §4 (the backend), with §2 (the plans), §3
(the owner's answers), §6 (4e-2a's tests) and §8 (the calls). The UI is 4e-2b's plan, after this one merges.

## How this plan was checked

The plan's code was checked before review on a scratch checkout of main at 00cbbad9, never on a branch. Each
task's diffs were applied as written, in order:
- the test diff alone, then the task's tests: they failed as its "Run them" step says;
- then the implementation diff and the same tests: they passed;
- after every task, ruff, `ruff format --check` and mypy: silent;
- after Task 7's docs, `dewpoint api openapi` and openapi-typescript regenerated the client; `check:api` passed, and
  the tree matched the prototype the diffs were cut from, every file, byte for byte;
- the 12 diff blocks, taken from this file's own text, are the diffs applied, byte for byte, in order.

On the final tree:
- the API, admission, CSV and request digest tests: 739 passed;
- `lint-imports`: 11 contracts kept;
- the frontend's type check: silent; its suite: 1288 passed (99 files), unchanged;
- CodeQL (python, CLI 2.27.2, python-queries 1.8.12, CI's filter): no finding.

The whole backend suite wasn't run: Task 7 asks the owner first. The executor still runs every step: the check is
evidence, not a substitute.

## Global Constraints

- **The backend and its generated client only.** No screen changes (4e-2b's). The frontend keeps passing as it is.
- **No migration, no ABI change:** `ENGINE_ABI` stays 11. No new dependency.
- **Every new answer is typed**, and models forbid extra keys. `openapi.json` and `schema.d.ts` are regenerated, never
  edited by hand.
- **A request without `expected_version_id` keeps its exact digest** (the design §4.1): a retry from before the deploy
  still finds its request.
- **Nothing secret leaves:** a preview never shows a sensitive column; an error names a row, a column and a code, never
  a cell; a preview is neither logged nor audited. Logs name an exception's type, never a value.
- **Tests run as CI runs them:** `cd backend && UV_FROZEN=1 UV_NO_SYNC=1 uv run pytest -q -n 6 <files>` (the fixture's
  own `uv run alembic` would sync otherwise).
- **Commits** end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Nothing is pushed; the owner merges.

## Review Focus

The inputs and failure modes the design implies that a person would meet first. Each is pinned by a test in the task
that owns the code:

1. **A start retried after a lost answer, with a publish in between,** returns its request, never `version_changed`.
   Task 2: `test_an_exact_retry_after_a_publish_is_its_request_and_another_version_under_its_key_a_conflict`; Task 3:
   `test_a_start_on_the_confirmed_version_is_admitted_and_on_another_answers_409_with_the_active_one`.
2. **A request that names no version** keeps the digest it had before this plan, byte for byte. Task 2:
   `test_a_start_on_a_confirmed_version_digests_it_and_any_other_request_keeps_its_bytes`.
3. **Another user's staged file, or one expired or consumed,** is refused as a start refuses it, never described.
   Task 5: `test_a_preview_is_of_the_callers_own_upload_while_its_staged`.
4. **A file at the caps where every cell fails** (10,000 rows, 200 required columns): 200 groups, each counting every
   error, past the 100 a record lists. Task 4:
  `test_at_the_permitted_limits_the_detail_kept_is_bounded_and_the_count_exact`
   and `test_an_upload_at_the_permitted_limits_lists_100_errors_and_counts_them_all`.
5. **A re-run of a re-run of a CSV start** still shows its rows. Task 6:
   `test_a_same_rows_rerun_keeps_its_originals_csv_record_and_a_rerun_of_it_finds_it`.

## Rulings (proposed; they join the ledger as 260 onward when the owner accepts the plan)

Each says what was decided, why, and what it costs if wrong. Found while building the prototype the diffs come from.

1. **One plan with milestone pauses:** after Task 3 (the version check, end to end), after Task 6 (the CSV), and after
   Task 7 (the client, the docs, every check), then a fresh reviewer, as 4e-1a. Cost: none.
2. **The version check comes after `workflow_disabled` and `not_active`, before the build's checks.** A disabled or
   unpublished workflow says so first; the active version is read once, for the check and for the rest. Cost if wrong:
   which refusal a doubly refused start names.
3. **`version_changed` keeps a refusal's shape and adds the active version:** `{"error", "messages",
   "active_version_id", "active_version_number"}`. `AdmissionRefusedError` and `_Refused` gain `extra`, which the
   route merges into the answer. The message is fixed: "Version N is the active version now: confirm the start on it."
   Cost: none.
4. **The digest names the confirmed version as its id's text, a key only when given**
   (`canonical(..., expected_version_id=None)`), as a draft simulation's `draft` already is. A re-run's exact-retry
   lookup (`admitted_under`) digests it the same way. Cost: none.
5. **The run form's answers are typed:** a start's and a re-run's answer is `RequestOut`, as a cancel's already is
   (4e-1a's ruling 15 left them to 4e-2); the upload's is `CsvUploadOut`, the preview's `CsvPreviewOut` (the upload's
   without its id, hour, headers, row count and default), the saved mapping's `CsvMappingOut`. The upload's
   `default_mapping` keeps `problems` out unless it's stale (`response_model_exclude_unset`). Cost: none; the answers'
   keys don't change.
6. **The upload's `version_id` is added by its route,** from the version `_active_csv` read. `stage()` stays as it is:
   the tests' helpers call it. Cost: none.
7. **The upload codes live in `csv_uploads`; admission names them from there.** A preview raises
   `UploadUnavailableError(code)`, which its route answers as a start does (404, 409, 410), checked in admission's
   order: not found, consumed, expired. Cost: none.
8. **A preview reads the file under the active version's caps,** as a start does: a file past caps lowered since its
   upload answers 422 with its code. Cost: none.
9. **The error groups:** ordered by count, the most first, then by column (a record's own `cell_count`, its column
   null, first), then by code; each keeps its first 5 records. Each error is counted as it's found, so a record's
   errors past the 100 it lists in detail count too. What's kept is at most a group per column and code. Cost: none.
10. **A same-rows re-run's audit entry counts its rows (`csv_rows`, `csv_skipped`) without a file digest:** the record
    keeps none; the original's entry has it. Cost: an auditor follows `rerun_of` to the file's digest.
11. **The start form names its publisher by email,** in one read beside the version, null once the user is gone.
    Versions are immutable, so the test publishes a second version as a user it then deletes. Cost: none.
12. **The client is regenerated; nothing else in the frontend changes.** `StartFormOut` gains three required fields
    that no frontend code or fake builds: the type check passes as it is. Cost: none.
13. **The checks:** each task's tests red, then green; on the final tree, the broad backend suites, the frontend suite
    unchanged and CodeQL; the whole backend suite on the owner's word, else on CI. Cost: none.

Mid-slice rulings start at M110.

## File structure

| File | Responsibility |
|---|---|
| `backend/src/dewpoint/core/requests/digest.py` | the digest's optional `expected_version_id` (Task 2) |
| `backend/src/dewpoint/apps/admission.py` | the version check, a refusal's `extra` (Task 2); the upload codes (Task 5); a same-rows re-run's record (Task 6) |
| `backend/src/dewpoint/apps/api/routes/run_requests.py` | `expected_version_id`, typed answers, the start form's version (Task 3) |
| `backend/src/dewpoint/apps/csv_input.py` | `ErrorGroup`, `Built.groups` (Task 4) |
| `backend/src/dewpoint/apps/csv_uploads.py` | the groups in `described` (Task 4); the upload codes, `previewed` (Task 5) |
| `backend/src/dewpoint/apps/api/routes/csv_uploads.py` | the upload's `version_id`, the preview route, typed answers (Task 5) |
| `backend/src/dewpoint/apps/api/responses.py` | `StartFormOut`'s version (Task 3); the CSV answers (Task 5) |
| `frontend/src/api/openapi.json`, `schema.d.ts` | regenerated (Task 7) |
| `docs/operations/runs.md` | starting on a version, checking a file again, a same-rows re-run (Task 7) |

## Milestones

1. **Tasks 1–3:** the ledger, the confirmed version and the start form, end to end. Pause for the owner's review.
2. **Tasks 4–6:** every error counted, a file checked again, a same-rows re-run's record. Pause for the owner's review.
3. **Task 7:** the client, the docs, every check, the final checkpoint. Then the final review.

---

# Milestone 1 — The confirmed version, end to end

### Task 1: The ledger: the 4e-2 design and this plan accepted

**Files:**
- Modify: `docs/superpowers/plans/2026-10-05-editor-ui-4-ledger.md` (append at the end)

**Interfaces:**
- Consumes: nothing.
- Produces: the ledger section later tasks append to (`### 4e-2a, milestone N`).

- [ ] **Step 1: Append the design's and the plan's status**

Run this task only once the owner has accepted the plan. Apply:

```diff
diff --git a/docs/superpowers/plans/2026-10-05-editor-ui-4-ledger.md b/docs/superpowers/plans/2026-10-05-editor-ui-4-ledger.md
index 5dda4051..1a6457e6 100644
--- a/docs/superpowers/plans/2026-10-05-editor-ui-4-ledger.md
+++ b/docs/superpowers/plans/2026-10-05-editor-ui-4-ledger.md
@@ -3384,3 +3384,42 @@ M109. **The cancel spec's delay follows a step** (CI's e2e job on #118, its thir
       loop. The fixture now runs a transform first; the spec waits 15 s for "running" (the steps are read every 5 s)
       and checks the delay ends "cancelled". A run that starts with a delay still shows it "not reached yet" while it
       sleeps: an engine gap, outside 4e-1b, for the owner to schedule. Cost if wrong: another e2e round.
+
+### 4e-2: the design accepted; the 4e-2a plan accepted (2026-10-20)
+
+The owner merged 4e-1b as #118 (squash 729f94a7); its nine deferred minors are issue #126, and #127 corrected M109's
+comment once the engine recorded a waiting delay at once (#119). The owner started 4e-2 ("let's start 4e-2"). Their
+answers, in chat:
+- both start runs: the builder, from the editor, and an operator, from the Workflows list or the Runs page;
+- a CSV row is one turn of the workflow's main loop, a few rows to thousands; the form gives a quick view of the CSV's
+  validation errors; a CSV start goes ahead only when every row passes (the outline's "skip invalid" is dropped);
+- in the editor, Start warns when the draft differs from the published version;
+- re-run: the same input or a changed one, the original prefilled; a changed input asks for its sensitive values
+  again, and a same-rows CSV re-run keeps its other fields read-only, both with no backend work;
+- after Start, the new run's page.
+
+D8 was signed off ("signed off, write the spec") at the Design canvas "4e-2 Run Form Mockups", version 6; versions 7
+to 10 bring its words in line with what the backend allows.
+`docs/superpowers/specs/2026-10-19-editor-4e2-run-form-design.md` (7c737523) was committed on the owner's word ("yes,
+commit"), its §8 calls listed for them to check.
+
+`docs/superpowers/plans/2026-10-20-editor-ui-4e2a-run-form-backend.md`, revision 1: the backend of the design §4, one
+plan with milestone pauses. The owner accepted it: its rulings 1–13 join this ledger as 260–272. No migration, no ABI
+change. Mid-slice rulings start at M110.
+
+260. **Accepted. One plan with milestone pauses** (plan ruling 1).
+261. **Accepted. The version check comes after `workflow_disabled` and `not_active`, before the build's checks**
+     (plan ruling 2).
+262. **Accepted. `version_changed` keeps a refusal's shape and adds the active version** (plan ruling 3).
+263. **Accepted. The digest names the confirmed version as its id's text, a key only when given** (plan ruling 4).
+264. **Accepted. The run form's answers are typed** (plan ruling 5).
+265. **Accepted. The upload's `version_id` is added by its route** (plan ruling 6).
+266. **Accepted. The upload codes live in `csv_uploads`; a preview refuses as a start does, in its order**
+     (plan ruling 7).
+267. **Accepted. A preview reads the file under the active version's caps** (plan ruling 8).
+268. **Accepted. The error groups: their order, their first rows, every error counted** (plan ruling 9).
+269. **Accepted. A same-rows re-run's audit entry counts its rows, without a file digest** (plan ruling 10).
+270. **Accepted. The start form names its publisher by email, null once they're gone** (plan ruling 11).
+271. **Accepted. The client is regenerated; nothing else in the frontend changes** (plan ruling 12).
+272. **Accepted. The checks: each task's suites, the final tree's broad suites, and the whole backend suite on CI**
+     (plan ruling 13).
```

- [ ] **Step 2: Commit**

```bash
git add docs/superpowers/plans/2026-10-05-editor-ui-4-ledger.md
git commit -m "docs(editor-4): the 4e-2 design accepted, the 4e-2a plan accepted (rulings 260-272)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: A start names the version it confirmed (B14, admission)

**Spec:** §4.1.

**Files:**
- Modify: `backend/src/dewpoint/core/requests/digest.py` (`canonical`, `digest`, `matches`),
  `backend/src/dewpoint/apps/admission.py` (`VERSION_CHANGED`, `AdmissionRefusedError`, `_Refused`, `admit_request`,
  `admitted_under`, `_frozen`)
- Test: modify `backend/tests/core/requests/test_digest.py`, `backend/tests/apps/test_admission.py`

**Interfaces:**
- Consumes: nothing new.
- Produces:
  - `digest.canonical(..., expected_version_id: str | None = None)`, and the same keyword on `digest` and `matches`;
  - `admission.VERSION_CHANGED = "version_changed"`;
  - `admission.AdmissionRefusedError(reason, messages, extra: dict[str, Any] | None = None)`, its `extra` a dict
    (`{}` when none);
  - `admission.admit_request(..., expected_version_id: uuid.UUID | None = None)` and
    `admission.admitted_under(..., expected_version_id: uuid.UUID | None = None)`;
  - in `tests/apps/test_admission.py`: `active(owner, wf) -> uuid.UUID` and
    `published_again(api, ctx, wf, settings) -> uuid.UUID`, a second version's id (Task 3 uses it).

- [ ] **Step 1: Write the failing tests**

Apply:

```diff
diff --git a/backend/tests/apps/test_admission.py b/backend/tests/apps/test_admission.py
index 84ff0055..84c6ddf6 100644
--- a/backend/tests/apps/test_admission.py
+++ b/backend/tests/apps/test_admission.py
@@ -20,7 +20,7 @@ from dewpoint.core.claims.cipher import ClaimCipher
 from dewpoint.core.db import tenant_scope
 from dewpoint.core.plugins import lifecycle
 from dewpoint.engine import ENGINE_ABI
-from tests.apps.test_workflow_ops import ECHO_GRAPH, actor, create, publish, update
+from tests.apps.test_workflow_ops import ECHO_GRAPH, actor, create, publish, save, update
 from tests.support.graphs import G
 from tests.support.keys import FixtureKeys
 from tests.support.registry import sync_test_plugins
@@ -327,3 +327,75 @@ async def test_an_input_past_the_limit_is_refused_before_its_key_is_read(ready,
                                            workflow_id=wf, mode="live",
                                            rerun=admission.Rerun(uuid.uuid4(), deep))  # fmt: skip
     assert (raised.value.reason, raised.value.messages) == ("input_invalid", [TOO_DEEP])
+
+
+# --- a start on the version it confirmed (B14; the run form design §4.1) ----------------------------------------------
+
+
+async def active(owner: Any, wf: uuid.UUID) -> uuid.UUID:
+    async with owner() as s:
+        found = await s.execute(text("select active_version_id from workflows where id = :w"), {"w": wf})
+        return uuid.UUID(str(found.scalar_one()))
+
+
+async def published_again(api: Any, ctx: Any, wf: uuid.UUID, settings: Any) -> uuid.UUID:
+    """A second version of the workflow, its draft changed first: the new active version's id."""
+    changed = G().node("a", "testkit.echo@1", {"value": 2}).data() | {"settings": TOKEN_GRAPH["settings"]}
+    await save(api, ctx, wf, changed)
+    version = (await publish(api, ctx, wf, settings)).version
+    assert version is not None
+    return version.id
+
+
+async def test_a_start_on_the_version_it_confirmed_is_frozen_on_it(ready, owner_sessionmaker, api_sessionmaker) -> None:
+    ctx, wf = ready
+    first = await active(owner_sessionmaker, wf)
+    admitted = await admit(api_sessionmaker, ctx, wf, expected_version_id=first)
+    assert admitted.new and admitted.request.workflow_version_id == first
+
+
+async def test_a_start_on_a_version_no_longer_active_is_refused_and_admits_nothing(
+    ready, owner_sessionmaker, api_sessionmaker, api_settings
+) -> None:
+    ctx, wf = ready
+    first = await active(owner_sessionmaker, wf)
+    second = await published_again(api_sessionmaker, ctx, wf, api_settings)
+    with pytest.raises(admission.AdmissionRefusedError) as refused:
+        await admit(api_sessionmaker, ctx, wf, expected_version_id=first)
+    assert refused.value.reason == "version_changed" and refused.value.messages
+    assert refused.value.extra == {"active_version_id": str(second), "active_version_number": 2}
+    assert (await count(owner_sessionmaker, "run_requests"), await count(owner_sessionmaker, "run_inputs")) == (0, 0)
+
+
+async def test_an_exact_retry_after_a_publish_is_its_request_and_another_version_under_its_key_a_conflict(
+    ready, owner_sessionmaker, api_sessionmaker, api_settings
+) -> None:
+    """An exact retry is resolved by its key before the version is checked; the version it confirmed is part of its
+    digest, so the same key naming another version, or none, is another request."""
+    ctx, wf = ready
+    first = await active(owner_sessionmaker, wf)
+    admitted = (await admit(api_sessionmaker, ctx, wf, expected_version_id=first)).request
+    second = await published_again(api_sessionmaker, ctx, wf, api_settings)
+    again = await admit(api_sessionmaker, ctx, wf, expected_version_id=first)
+    assert (again.new, again.request.id, again.request.workflow_version_id) == (False, admitted.id, first)
+    for other in ({"expected_version_id": second}, {}):
+        with pytest.raises(admission.IdempotencyConflictError):
+            await admit(api_sessionmaker, ctx, wf, **other)
+
+
+async def test_a_reruns_retry_is_found_under_its_key_only_with_the_version_it_confirmed(
+    ready, owner_sessionmaker, api_sessionmaker
+) -> None:
+    ctx, wf = ready
+    first = await active(owner_sessionmaker, wf)
+    original = (await admit(api_sessionmaker, ctx, wf)).request
+    rerun = admission.Rerun(original.id)
+    made = (await admit(api_sessionmaker, ctx, wf, key="r1", source="rerun", rerun=rerun,
+                        expected_version_id=first)).request  # fmt: skip
+    async with api_sessionmaker() as s, s.begin():
+        under = {"tenant_id": ctx.tenant_id, "idempotency_key": "r1", "source": "rerun", "workflow_id": wf}
+        under |= {"mode": "live"}
+        found = await admission.admitted_under(s, KEYS, **under, rerun=rerun, expected_version_id=first)
+        assert found is not None and found.id == made.id
+        with pytest.raises(admission.IdempotencyConflictError):
+            await admission.admitted_under(s, KEYS, **under, rerun=rerun)
diff --git a/backend/tests/core/requests/test_digest.py b/backend/tests/core/requests/test_digest.py
index 18dc8631..84d82985 100644
--- a/backend/tests/core/requests/test_digest.py
+++ b/backend/tests/core/requests/test_digest.py
@@ -55,3 +55,18 @@ async def test_a_draft_simulation_digests_its_draft_and_any_other_request_keeps_
     assert len({plain, drafted, later}) == 3
     assert await d.matches(keys, TENANT, drafted, 1, **REQUEST, draft={"draft_revision": 2})
     assert not await d.matches(keys, TENANT, drafted, 1, **REQUEST)
+
+
+async def test_a_start_on_a_confirmed_version_digests_it_and_any_other_request_keeps_its_bytes() -> None:
+    """B14 (the run form design §4.1): a start that names the version it confirmed digests it as a fifth key; one that
+    names none is digested as before, byte for byte."""
+    keys = FixtureKeys()
+    seven, eight = str(uuid.UUID(int=7)), str(uuid.UUID(int=8))
+    assert d.canonical(**REQUEST, expected_version_id=None) == d.canonical(**REQUEST)
+    _, plain = await d.digest(keys, TENANT, **REQUEST)
+    _, on_seven = await d.digest(keys, TENANT, **REQUEST, expected_version_id=seven)
+    _, on_eight = await d.digest(keys, TENANT, **REQUEST, expected_version_id=eight)
+    assert len({plain, on_seven, on_eight}) == 3
+    assert await d.matches(keys, TENANT, on_seven, 1, **REQUEST, expected_version_id=seven)
+    assert not await d.matches(keys, TENANT, on_seven, 1, **REQUEST)
+    assert not await d.matches(keys, TENANT, plain, 1, **REQUEST, expected_version_id=seven)
```

- [ ] **Step 2: Run them**

Run:

```bash
cd backend && UV_FROZEN=1 UV_NO_SYNC=1 uv run pytest -q -n 6 \
  tests/core/requests/test_digest.py \
  tests/apps/test_admission.py
```

Expected: FAIL, 5 failed and 29 passed: `canonical()` takes no `expected_version_id` (`TypeError`), nor does
`admit_request()` (`TypeError`, the four admission tests).

- [ ] **Step 3: Write the implementation**

Apply:

```diff
diff --git a/backend/src/dewpoint/apps/admission.py b/backend/src/dewpoint/apps/admission.py
index 78d6b4ff..6411a029 100644
--- a/backend/src/dewpoint/apps/admission.py
+++ b/backend/src/dewpoint/apps/admission.py
@@ -81,6 +81,7 @@ PRODUCTION_RUNS_DISABLED = "production_runs_disabled"
 ENVIRONMENT_NOT_RECORDED = "environment_not_recorded"
 WORKFLOW_DISABLED = "workflow_disabled"
 NOT_ACTIVE = "not_active"
+VERSION_CHANGED = "version_changed"  # B14: the start confirmed a version no longer active
 NO_CURRENT_BUILD = "no_current_build"
 VERSION_UNUSABLE = "version_unusable"
 NODE_TYPE_RETIRED = "node_type_retired"
@@ -110,11 +111,12 @@ NO_BUILD = (
 
 
 class AdmissionRefusedError(Exception):
-    """An interactive request admission refused: its `reason` code (§9) and what to tell the caller."""
+    """An interactive request admission refused: its `reason` code (§9), what to tell the caller, and the facts its
+    answer adds (`version_changed`'s active version)."""
 
-    def __init__(self, reason: str, messages: list[str]) -> None:
+    def __init__(self, reason: str, messages: list[str], extra: dict[str, Any] | None = None) -> None:
         super().__init__("; ".join(messages))
-        self.reason, self.messages = reason, messages
+        self.reason, self.messages, self.extra = reason, messages, extra or {}
 
 
 class IdempotencyConflictError(Exception):
@@ -199,8 +201,10 @@ class Admitted:
 
 
 class _Refused(Exception):
-    def __init__(self, reason: str, messages: list[str], version_id: uuid.UUID | None = None) -> None:
-        self.reason, self.messages, self.version_id = reason, messages, version_id
+    def __init__(
+        self, reason: str, messages: list[str], version_id: uuid.UUID | None = None, extra: dict[str, Any] | None = None
+    ) -> None:
+        self.reason, self.messages, self.version_id, self.extra = reason, messages, version_id, extra
 
 
 class _Consumed(Exception):
@@ -247,11 +251,13 @@ async def admit_request(
     csv: CsvStart | None = None,
     details: dict[str, object] | None = None,
     trigger_id: uuid.UUID | None = None,
+    expected_version_id: uuid.UUID | None = None,
 ) -> Admitted:
     """The request under `idempotency_key`: an exact retry's, or a new one, frozen. A re-run's digest covers its
-    `rerun` identity in place of `input`, and a CSV start's its `csv` beside it. `trigger_id` is the schedule or webhook
-    endpoint a durable source's request came from. Raises IdempotencyConflictError, WorkflowNotFoundError, or, for an
-    interactive source, AdmissionRefusedError."""
+    `rerun` identity in place of `input`, and a CSV start's its `csv` beside it; a start that confirmed a version
+    (`expected_version_id`, B14) is refused once another is active, and its digest covers it. `trigger_id` is the
+    schedule or webhook endpoint a durable source's request came from. Raises IdempotencyConflictError,
+    WorkflowNotFoundError, or, for an interactive source, AdmissionRefusedError."""
     if source not in INTERACTIVE + DURABLE or mode not in (LIVE, SIMULATE):
         raise ValueError(f"no such source or mode: {source}, {mode}")
     if csv is not None and source not in ("manual", "rerun"):
@@ -269,6 +275,8 @@ async def admit_request(
         digested = {**fields, "input": {"input": input, "csv": csv.digested()}}
     else:
         digested = fields
+    if expected_version_id is not None:  # only then: every other request's digest keeps its bytes
+        digested = {**digested, "expected_version_id": str(expected_version_id)}
     owner = actor_id if csv is not None else None  # a CSV start's exact retry is its upload owner's only
     existing = await _by_key(s, idempotency_key)
     if existing is not None:
@@ -276,7 +284,7 @@ async def admit_request(
     request_id = uuid.uuid4()
     savepoint = await s.begin_nested()
     try:
-        frozen = await _frozen(s, keys, tenant_id, request_id, fields, actor_id, rerun, csv)
+        frozen = await _frozen(s, keys, tenant_id, request_id, fields, actor_id, rerun, csv, expected_version_id)
     except _Consumed:
         await savepoint.rollback()
         existing = await _by_key(s, idempotency_key)  # its consumer has committed: under this key, an exact retry
@@ -286,7 +294,7 @@ async def admit_request(
     except _Refused as refused:
         await savepoint.rollback()
         if source in INTERACTIVE:
-            raise AdmissionRefusedError(refused.reason, refused.messages) from None
+            raise AdmissionRefusedError(refused.reason, refused.messages, refused.extra) from None
         return await _insert(s, keys, tenant_id, request_id, actor_id, idempotency_key, digested, None, None, refused,
                              rerun, extra=details, trigger_id=trigger_id)  # fmt: skip
     await _before_insert()
@@ -369,6 +377,7 @@ async def record_refused(
 async def admitted_under(
     s: AsyncSession, keys: KeySource, *, tenant_id: uuid.UUID, idempotency_key: str, source: str,
     workflow_id: uuid.UUID, mode: str, rerun: Rerun, actor_id: uuid.UUID | None = None,
+    expected_version_id: uuid.UUID | None = None,
 ) -> RunRequest | None:  # fmt: skip
     """The request an exact retry of this re-run finds under its key, before its input is rebuilt; None when the key
     is free. Raises IdempotencyConflictError for another request under the key, or, for a re-run with a new CSV, one
@@ -383,6 +392,8 @@ async def admitted_under(
     if existing is None:
         return None
     fields = {"source": source, "workflow_id": workflow_id, "mode": mode, "input": rerun.digested()}
+    if expected_version_id is not None:
+        fields["expected_version_id"] = str(expected_version_id)
     owner = actor_id if rerun.csv is not None else None
     return (await _retry(keys, tenant_id, existing, fields, owner)).request
 
@@ -419,7 +430,7 @@ async def _retry(
 
 async def _frozen(
     s: AsyncSession, keys: KeySource, tenant_id: uuid.UUID, request_id: uuid.UUID, fields: dict[str, Any],
-    actor_id: uuid.UUID | None, rerun: Rerun | None, csv: CsvStart | None,
+    actor_id: uuid.UUID | None, rerun: Rerun | None, csv: CsvStart | None, expected_version_id: uuid.UUID | None = None,
 ) -> _Frozen:  # fmt: skip
     """The mutable checks, then the trigger claimed and its envelope stored (a CSV start's rows built and its upload
     consumed first): the frozen version, the envelope and what the audit entry adds."""
@@ -434,6 +445,10 @@ async def _frozen(
     version = await s.get(WorkflowVersion, workflow.active_version_id)
     if version is None:
         raise RuntimeError("A workflow's active version that isn't there.")
+    if expected_version_id is not None and version.id != expected_version_id:  # B14: confirmed on another version
+        message = f"Version {version.number} is the active version now: confirm the start on it."
+        active = {"active_version_id": str(version.id), "active_version_number": version.number}
+        raise _Refused(VERSION_CHANGED, [message], version.id, active)
     build = await _current_build(s)
     if build is None:
         raise _Refused(NO_CURRENT_BUILD, [NO_BUILD], version.id)
diff --git a/backend/src/dewpoint/core/requests/digest.py b/backend/src/dewpoint/core/requests/digest.py
index 7e9a7be9..ba890d68 100644
--- a/backend/src/dewpoint/core/requests/digest.py
+++ b/backend/src/dewpoint/core/requests/digest.py
@@ -13,12 +13,18 @@ from typing import Any
 from dewpoint.core.crypto.keys import KeySource
 
 
-def canonical(*, source: str, workflow_id: uuid.UUID, mode: str, input: Any, draft: Any = None) -> bytes:
+def canonical(
+    *, source: str, workflow_id: uuid.UUID, mode: str, input: Any, draft: Any = None,
+    expected_version_id: str | None = None,
+) -> bytes:  # fmt: skip
     """Sorted keys, no whitespace, UTF-8, no NaN: equal requests always give equal bytes. A draft simulation's `draft`
-    (B8) is there only when given, so every other request's bytes stay what they were."""
+    (B8), and the version a start confirmed (B14), are there only when given, so every other request's bytes stay what
+    they were."""
     value = {"source": source, "workflow_id": str(workflow_id), "mode": mode, "input": input}
     if draft is not None:
         value["draft"] = draft
+    if expected_version_id is not None:
+        value["expected_version_id"] = expected_version_id
     return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
 
 
@@ -31,21 +37,23 @@ async def digest(
     mode: str,
     input: Any,
     draft: Any = None,
+    expected_version_id: str | None = None,
     version: int | None = None,
 ) -> tuple[int, bytes]:
     """The request's digest with the tenant's key of `version` (its active one when None), and that version."""
     found, key = await keys.digest_key(tenant_id, version)
-    message = canonical(source=source, workflow_id=workflow_id, mode=mode, input=input, draft=draft)
+    message = canonical(source=source, workflow_id=workflow_id, mode=mode, input=input, draft=draft,
+                        expected_version_id=expected_version_id)  # fmt: skip
     return found, hmac.new(key, message, hashlib.sha256).digest()
 
 
 async def matches(
     keys: KeySource, tenant_id: str, stored: bytes, version: int, *, source: str, workflow_id: uuid.UUID, mode: str,
-    input: Any, draft: Any = None,
+    input: Any, draft: Any = None, expected_version_id: str | None = None,
 ) -> bool:  # fmt: skip
     """Whether a request is the one `stored` was computed for, with the key version it was computed with."""
     _, fresh = await digest(keys, tenant_id, source=source, workflow_id=workflow_id, mode=mode, input=input,
-                            draft=draft, version=version)  # fmt: skip
+                            draft=draft, expected_version_id=expected_version_id, version=version)  # fmt: skip
     return hmac.compare_digest(fresh, stored)
 
 
```

- [ ] **Step 4: Run them again**

Run: the same command.

Expected: PASS, 34 passed.

- [ ] **Step 5: Run the static checks**

Run:

```bash
cd backend \
  && uv run ruff check src tests migrations \
  && uv run ruff format --check src tests migrations \
  && uv run mypy src
```

Expected: silent ("All checks passed!", every file already formatted, "Success: no issues found").

- [ ] **Step 6: Commit**

```bash
git add backend/src/dewpoint/core/requests/digest.py backend/src/dewpoint/apps/admission.py \
  backend/tests/core/requests/test_digest.py backend/tests/apps/test_admission.py
git commit -m "feat(runs): a start names the version it confirmed, refused once another is active (B14, 4e-2a)

Admission refuses a start or a re-run whose expected version is no longer the active one (version_changed, naming the
active version), and its digest covers that version only when it's given (the run form design §4.1).

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: The confirmed version and the start form, through the API

**Spec:** §4.1, §4.2.

**Files:**
- Modify: `backend/src/dewpoint/apps/api/routes/run_requests.py` (`StartIn`, `RerunIn`, `admit`, `start_run`,
  `start_form`, `rerun`), `backend/src/dewpoint/apps/api/responses.py` (`StartFormOut`)
- Test: modify `backend/tests/apps/api/test_run_requests_api.py`, `backend/tests/apps/api/test_openapi.py`

**Interfaces:**
- Consumes: Task 2's `admit_request(..., expected_version_id=...)`, `admitted_under(..., expected_version_id=...)`,
  `AdmissionRefusedError.extra`; `tests.apps.test_admission.published_again`.
- Produces:
  - `StartIn.expected_version_id` and `RerunIn.expected_version_id`, `uuid.UUID | None`;
  - a refusal's answer: `{"error", "messages", **extra}`, so `version_changed` is
    `{"error", "messages", "active_version_id", "active_version_number"}`;
  - `StartFormOut.version_number: int`, `published_at: str`, `published_by: str | None`;
  - the start's and the re-run's `response_model=RequestOut`;
  - `tests/apps/api/test_openapi.py`'s `SLICE_4E2` list (Task 5 extends it).

- [ ] **Step 1: Write the failing tests**

Apply:

```diff
diff --git a/backend/tests/apps/api/test_openapi.py b/backend/tests/apps/api/test_openapi.py
index 1b0f0aef..2acad3d1 100644
--- a/backend/tests/apps/api/test_openapi.py
+++ b/backend/tests/apps/api/test_openapi.py
@@ -211,6 +211,20 @@ def test_slice_4d1_routes_name_their_answer(method: str, path: str) -> None:
     assert "$ref" in body or "$ref" in body.get("items", {}), body
 
 
+SLICE_4E2 = [  # the run form's answers (the run form design §4)
+    ("post", "/api/v1/t/{tenant_id}/workflows/{workflow_id}/runs"),
+    ("post", "/api/v1/t/{tenant_id}/runs/{request_id}/rerun"),
+]
+
+
+@pytest.mark.parametrize("method,path", SLICE_4E2)
+def test_slice_4e2_routes_name_their_answer(method: str, path: str) -> None:
+    responses = schema()["paths"][path][method]["responses"]
+    ok = next(code for code in responses if code.startswith("2"))
+    body = responses[ok]["content"]["application/json"]["schema"]
+    assert "$ref" in body or "$ref" in body.get("items", {}), body
+
+
 def test_a_schedules_uncounted_span_keeps_its_wire_names() -> None:
     """`from` and `class` are Python keywords: the model aliases them, and the schema says the names on the wire."""
     span = schema()["components"]["schemas"]["UncountedOut"]
diff --git a/backend/tests/apps/api/test_run_requests_api.py b/backend/tests/apps/api/test_run_requests_api.py
index ac010092..2e96bbf7 100644
--- a/backend/tests/apps/api/test_run_requests_api.py
+++ b/backend/tests/apps/api/test_run_requests_api.py
@@ -7,19 +7,22 @@ version's input, masking what's sensitive."""
 
 import json
 import uuid
+from datetime import datetime
 from typing import Any
 
 import pytest
 from sqlalchemy import text
 
 from dewpoint.apps.inputs import NOT_FINITE, TOO_DEEP
+from dewpoint.core.auth.users import create_user
 from dewpoint.core.claims import service as claims
 from dewpoint.core.claims.cipher import ClaimCipher
 from dewpoint.core.db import tenant_scope
+from dewpoint.core.http import TenantContext
 from dewpoint.core.runs import service as runs
 from dewpoint.engine.handles import ClaimRef, StoredClaim, resolve_value
-from tests.apps.api.helpers import member_client
-from tests.apps.test_admission import KEYS, OPEN_GRAPH, TOKEN, admit, count, current, published
+from tests.apps.api.helpers import PW, member_client
+from tests.apps.test_admission import KEYS, OPEN_GRAPH, TOKEN, admit, count, current, published, published_again
 from tests.apps.test_inputs import objects
 from tests.apps.test_workflow_ops import update
 from tests.support.graphs import G
@@ -585,3 +588,63 @@ async def test_an_input_holding_nan_or_an_infinity_is_422_with_the_fixed_reason(
         answer = await client.post(rerun_url(ctx, old["id"]), content=body, headers=raw(key))
         assert (answer.status_code, answer.json()) == refused, key
     assert await count(owner_sessionmaker, "run_requests") == 1
+
+
+# --- starting on the confirmed version (B14; the run form design §4.1, §4.2) -----------------------------------------
+
+
+def form_url(ctx: Any, wf: uuid.UUID) -> str:
+    return f"/api/v1/t/{ctx.tenant_id}/workflows/{wf}/start-form"
+
+
+async def test_the_start_form_names_its_version_and_who_published_it(
+    keyed_app, ready, owner_sessionmaker, api_sessionmaker, api_settings
+) -> None:
+    ctx, wf = ready
+    client = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx)
+    form = (await client.get(form_url(ctx, wf))).json()
+    assert (form["version_number"], form["published_by"]) == (1, ctx.user.email)
+    assert datetime.fromisoformat(form["published_at"]).tzinfo is not None
+    async with owner_sessionmaker() as s, s.begin():
+        leaver = await create_user(s, email=f"{uuid.uuid4().hex[:8]}@corp.test", password=PW)
+    by = TenantContext(tenant_id=ctx.tenant_id, user=leaver, role="editor", session=None)  # type: ignore[arg-type]
+    await published_again(api_sessionmaker, by, wf, api_settings)
+    async with owner_sessionmaker() as s, s.begin():
+        await s.execute(text("delete from users where id = :u"), {"u": leaver.id})
+    form = (await client.get(form_url(ctx, wf))).json()
+    assert (form["version_number"], form["published_by"]) == (2, None)  # a publisher who's gone
+
+
+async def test_a_start_on_the_confirmed_version_is_admitted_and_on_another_answers_409_with_the_active_one(
+    keyed_app, ready, owner_sessionmaker, api_sessionmaker, api_settings
+) -> None:
+    ctx, wf = ready
+    client = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx)
+    confirmed = {**BODY, "expected_version_id": (await client.get(form_url(ctx, wf))).json()["version_id"]}
+    answer = await client.post(runs_url(ctx, wf), json=confirmed, headers={"Idempotency-Key": "k1"})
+    assert (answer.status_code, answer.json()["version_id"]) == (202, confirmed["expected_version_id"])
+    second = await published_again(api_sessionmaker, ctx, wf, api_settings)
+    refused = await client.post(runs_url(ctx, wf), json=confirmed, headers={"Idempotency-Key": "k2"})
+    assert refused.status_code == 409, refused.text
+    body = refused.json()
+    assert (body["error"], body["active_version_id"], body["active_version_number"]) == (
+        "version_changed", str(second), 2,
+    )  # fmt: skip
+    assert body["messages"] == ["Version 2 is the active version now: confirm the start on it."]
+    again = await client.post(runs_url(ctx, wf), json=confirmed, headers={"Idempotency-Key": "k1"})
+    assert (again.status_code, again.json()["id"]) == (202, answer.json()["id"])  # an exact retry, whatever's active
+
+
+async def test_a_rerun_on_the_confirmed_version_is_admitted_and_on_another_answers_409(
+    keyed_app, ready, owner_sessionmaker, api_sessionmaker, api_settings
+) -> None:
+    ctx, wf = ready
+    client = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx)
+    old = await started_request(client, ctx, wf)
+    second = await published_again(api_sessionmaker, ctx, wf, api_settings)
+    stale = await client.post(rerun_url(ctx, old["id"]), json={"expected_version_id": old["version_id"]},
+                              headers={"Idempotency-Key": "r1"})  # fmt: skip
+    assert (stale.status_code, stale.json()["error"]) == (409, "version_changed")
+    fresh = await client.post(rerun_url(ctx, old["id"]), json={"expected_version_id": str(second)},
+                              headers={"Idempotency-Key": "r2"})  # fmt: skip
+    assert (fresh.status_code, fresh.json()["version_id"], fresh.json()["source"]) == (202, str(second), "rerun")
```

- [ ] **Step 2: Run them**

Run:

```bash
cd backend && UV_FROZEN=1 UV_NO_SYNC=1 uv run pytest -q -n 6 \
  tests/apps/api/test_run_requests_api.py \
  tests/apps/api/test_openapi.py
```

Expected: FAIL, 5 failed and 115 passed: the start form has no `version_number` (`KeyError`); `StartIn` and `RerunIn`
forbid an unknown `expected_version_id`, so the start answers 422 `invalid` (`KeyError: 'version_id'`) and the re-run
too ("(422, 'invalid') == (409, 'version_changed')"); the start's and the re-run's answers are untyped objects, with no
`$ref`.

- [ ] **Step 3: Write the implementation**

Apply:

```diff
diff --git a/backend/src/dewpoint/apps/api/responses.py b/backend/src/dewpoint/apps/api/responses.py
index 8413cb12..0b337b39 100644
--- a/backend/src/dewpoint/apps/api/responses.py
+++ b/backend/src/dewpoint/apps/api/responses.py
@@ -602,10 +602,14 @@ class CsvFormOut(_Answer):
 
 
 class StartFormOut(_Answer):
-    """The active version's input, as a form: what a schedule's input is entered on (4c-3a ruling 5)."""
+    """The active version's input, as a form: what a schedule's input is entered on (4c-3a ruling 5), and the run
+    form's (the run form design §4.2): the version it names, and who published it, null once they're gone."""
 
     workflow_id: str
     version_id: str
+    version_number: int
+    published_at: str
+    published_by: str | None
     fields: list[StartFieldOut]
     csv: CsvFormOut | None
 
diff --git a/backend/src/dewpoint/apps/api/routes/run_requests.py b/backend/src/dewpoint/apps/api/routes/run_requests.py
index c1d9e1a7..75ada548 100644
--- a/backend/src/dewpoint/apps/api/routes/run_requests.py
+++ b/backend/src/dewpoint/apps/api/routes/run_requests.py
@@ -12,10 +12,11 @@ from typing import Annotated, Any, Literal
 
 from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
 from pydantic import BaseModel, ConfigDict, Field
+from sqlalchemy import select
 from sqlalchemy.ext.asyncio import AsyncSession
 
 from dewpoint.apps import admission, cancels
-from dewpoint.apps.api.responses import CancelOut, StartFormOut
+from dewpoint.apps.api.responses import CancelOut, RequestOut, StartFormOut
 from dewpoint.apps.csv_slots import CsvBusyError, Slot
 from dewpoint.apps.forms import csv_form, form_fields
 from dewpoint.apps.inputs import INPUT_INVALID, TOO_DEEP
@@ -25,6 +26,7 @@ from dewpoint.core.claims.cipher import ClaimCipher
 from dewpoint.core.claims.secret_index import SECRET_INDEX_LIMIT
 from dewpoint.core.crypto.keys import KeySource, key_unreadable
 from dewpoint.core.http import TenantContext, get_db, require
+from dewpoint.core.models.identity import User
 from dewpoint.core.models.requests import RunRequest
 from dewpoint.core.models.runs import Run
 from dewpoint.core.models.workflows import Workflow, WorkflowVersion
@@ -63,6 +65,7 @@ class StartIn(BaseModel):
     input: dict[str, Any] = Field(default_factory=dict)
     mode: Literal["live", "simulate"] = "live"
     csv: CsvIn | None = None  # a workflow that declares a CSV starts only with one (§8.1)
+    expected_version_id: uuid.UUID | None = None  # the version confirmed: 409 `version_changed` once another is (B14)
 
 
 class RerunIn(BaseModel):
@@ -70,6 +73,7 @@ class RerunIn(BaseModel):
     mode: Literal["live", "simulate"] | None = None  # the old request's when not given
     input: dict[str, Any] | None = None  # new input; else the original, rebuilt while it's retained
     csv: CsvIn | None = None  # a new upload, with `input` (or none) beside it
+    expected_version_id: uuid.UUID | None = None  # as a start's (B14)
 
 
 def key_unusable(e: Exception) -> HTTPException:
@@ -135,7 +139,7 @@ async def admit(
         admitted = await admission.admit_request(
             db, keys, tenant_id=ctx.tenant_id, workflow_id=workflow_id, source=source, actor_id=ctx.user.id,
             mode=body.mode, idempotency_key=key, input=body.input, rerun=rerun,
-            csv=body.csv.start() if body.csv is not None else None,
+            csv=body.csv.start() if body.csv is not None else None, expected_version_id=body.expected_version_id,
         )  # fmt: skip
     except admission.WorkflowNotFoundError:
         raise HTTPException(404, detail={"error": "not_found"}) from None
@@ -146,7 +150,7 @@ async def admit(
             503 if e.reason in UNAVAILABLE else 422 if e.reason in INVALID else 404 if e.reason in NOT_FOUND
             else 410 if e.reason in GONE else 409
         )  # fmt: skip
-        raise HTTPException(status, detail={"error": e.reason, "messages": e.messages}) from None
+        raise HTTPException(status, detail={"error": e.reason, "messages": e.messages, **e.extra}) from None
     except Exception as e:
         raise key_unusable(e) from None
     if not admitted.new:
@@ -170,7 +174,7 @@ async def not_past_cutoff(db: AsyncSession, ctx: TenantContext, request: RunRequ
         raise HTTPException(410, detail={"error": REQUEST_NOT_RETAINED})
 
 
-@router.post("/t/{tenant_id}/workflows/{workflow_id}/runs", status_code=202)
+@router.post("/t/{tenant_id}/workflows/{workflow_id}/runs", status_code=202, response_model=RequestOut)
 async def start_run(
     workflow_id: uuid.UUID,
     body: StartIn,
@@ -202,9 +206,13 @@ async def start_form(
     version = await db.get(WorkflowVersion, workflow.active_version_id)
     if version is None:
         raise HTTPException(409, detail={"error": admission.NOT_ACTIVE})
+    published_by = (await db.execute(select(User.email).where(User.id == version.published_by))).scalar()
     return {
         "workflow_id": str(workflow.id),
         "version_id": str(version.id),
+        "version_number": version.number,
+        "published_at": version.published_at.isoformat(),
+        "published_by": published_by,  # null once the user who published it is gone
         "fields": form_fields(version.input_schema or {}),
         "csv": csv_form((version.graph.get("settings") or {}).get("csv")),
     }
@@ -238,7 +246,7 @@ async def cancel_run(
     return {"cancel": happened, "request": request_body(request)}
 
 
-@router.post("/t/{tenant_id}/runs/{request_id}/rerun", status_code=202)
+@router.post("/t/{tenant_id}/runs/{request_id}/rerun", status_code=202, response_model=RequestOut)
 async def rerun(
     request_id: uuid.UUID,
     body: RerunIn | None = None,
@@ -268,7 +276,7 @@ async def rerun(
     try:
         existing = await admission.admitted_under(
             db, keys, tenant_id=ctx.tenant_id, idempotency_key=key, source="rerun", workflow_id=workflow_id,
-            mode=mode, rerun=again, actor_id=ctx.user.id,
+            mode=mode, rerun=again, actor_id=ctx.user.id, expected_version_id=given.expected_version_id,
         )  # fmt: skip
     except admission.IdempotencyConflictError:
         raise HTTPException(409, detail={"error": "idempotency_conflict"}) from None
@@ -279,16 +287,17 @@ async def rerun(
     if existing is not None:
         await not_past_cutoff(db, ctx, existing)
         return request_body(existing)
+    expected = given.expected_version_id
     if given.csv is not None:
-        start = StartIn(input=given.input or {}, mode=mode, csv=given.csv)
+        start = StartIn(input=given.input or {}, mode=mode, csv=given.csv, expected_version_id=expected)
         return request_body(await admit(db, keys, ctx, workflow_id, "rerun", start, key, rerun=again, slot=slot))
     if given.input is not None:
-        start = StartIn(input=given.input, mode=mode)
+        start = StartIn(input=given.input, mode=mode, expected_version_id=expected)
         return request_body(await admit(db, keys, ctx, workflow_id, "rerun", start, key, rerun=again))
     if old is None or not await retention.request_kept(db, await retention.cutoff(db, ctx.tenant_id), old):
         raise HTTPException(410, detail={"error": INPUT_NOT_RETAINED})
     taken(slot)  # its original's input, a CSV's rows perhaps, read only in a slot (the fresh M3 review's I5)
-    start = StartIn(input=await original_input(db, keys, ctx.tenant_id, old), mode=mode)
+    start = StartIn(input=await original_input(db, keys, ctx.tenant_id, old), mode=mode, expected_version_id=expected)
     return request_body(await admit(db, keys, ctx, workflow_id, "rerun", start, key, rerun=again))
 
 
```

- [ ] **Step 4: Run them again**

Run: the same command.

Expected: PASS, 120 passed.

- [ ] **Step 5: Run the static checks**

Run: Task 2's static checks.

Expected: silent.

- [ ] **Step 6: Commit**

```bash
git add backend/src/dewpoint/apps/api/routes/run_requests.py backend/src/dewpoint/apps/api/responses.py \
  backend/tests/apps/api/test_run_requests_api.py backend/tests/apps/api/test_openapi.py
git commit -m "feat(api): starts and re-runs confirm their version; the start form names it (B14, 4e-2a)

expected_version_id on StartIn and RerunIn, 409 version_changed naming the active version; the start form's
version number, publish time and publisher; a start's and a re-run's answers typed as RequestOut (the run form
design §4.1, §4.2).

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

**Milestone 1 ends here.** Append `### 4e-2a, milestone 1 (<date>)` to the ledger: each task's commit, its red and
green results, any mid-slice ruling. Commit it as `docs(editor-4): 4e-2a milestone 1`, with the trailer, and pause for
the owner's review.

---

# Milestone 2 — The CSV: every error counted, a file checked again, a re-run's record

### Task 4: Every error counted by column and problem

**Spec:** §4.4.

**Files:**
- Modify: `backend/src/dewpoint/apps/csv_input.py` (`GROUP_ROWS`, `ErrorGroup`, `Built.groups`, `build_rows`),
  `backend/src/dewpoint/apps/csv_uploads.py` (`described`)
- Test: modify `backend/tests/apps/test_csv_input.py`, `backend/tests/apps/api/test_csv_uploads_api.py`

**Interfaces:**
- Consumes: nothing new.
- Produces:
  - `csv_input.GROUP_ROWS = 5`;
  - `csv_input.ErrorGroup(column: str | None, code: str, count: int, rows: list[int])`, frozen;
  - `Built.groups: list[ErrorGroup]`, its fifth field, ordered by ruling 9;
  - `described(...)` adds `"error_groups"` (each group as a dict) and `"rows_with_errors"` (`len(built.skipped)`),
    `[]` and `0` while the mapping has problems.

- [ ] **Step 1: Write the failing tests**

Apply:

```diff
diff --git a/backend/tests/apps/api/test_csv_uploads_api.py b/backend/tests/apps/api/test_csv_uploads_api.py
index 4ffdc754..112ece29 100644
--- a/backend/tests/apps/api/test_csv_uploads_api.py
+++ b/backend/tests/apps/api/test_csv_uploads_api.py
@@ -70,6 +70,8 @@ async def test_an_operator_uploads_a_csv_and_gets_its_mapping_preview_and_errors
         {"row": 3, "cells": {"site": "", "vlan": "20"}},
     ]  # the sensitive column and the undeclared one are never shown
     assert (body["errors"], body["error_count"]) == ([{"row": 3, "column": "site", "code": "required"}], 1)
+    assert body["error_groups"] == [{"column": "site", "code": "required", "count": 1, "rows": [3]}]
+    assert body["rows_with_errors"] == 1
     row = await stored(owner_sessionmaker, body["upload_id"])
     assert (row["workflow_id"], row["size_bytes"], row["row_count"]) == (wf, len(FILE), 3)
     assert b"s3cret-psk" not in row["staged"] and b"paris" not in row["staged"]  # encrypted
@@ -190,6 +192,8 @@ async def test_an_upload_at_the_permitted_limits_lists_100_errors_and_counts_the
     assert answer.status_code == 201, answer.text[:200]
     body = answer.json()
     assert (len(body["errors"]), body["error_count"], body["row_count"]) == (100, 2_000_000, 10_000)
+    assert (len(body["error_groups"]), body["rows_with_errors"]) == (200, 10_000)
+    assert {g["count"] for g in body["error_groups"]} == {10_000}
     row = await stored(owner_sessionmaker, body["upload_id"])
     assert len(row["staged"]) <= len(WIDE_FILE) + 64  # the file's bytes, never a parsed form several times larger
 
diff --git a/backend/tests/apps/test_csv_input.py b/backend/tests/apps/test_csv_input.py
index 85f2e87a..d6336d4c 100644
--- a/backend/tests/apps/test_csv_input.py
+++ b/backend/tests/apps/test_csv_input.py
@@ -5,6 +5,7 @@ the file's headers, each cell converted to its column's type; a row that breaks
 column's declared name and a fixed code, never what the cell holds."""
 
 import string
+from dataclasses import asdict
 
 import pytest
 from hypothesis import given, settings
@@ -113,6 +114,21 @@ def test_a_row_that_breaks_a_rule_is_its_number_column_and_code() -> None:
     assert (built.skipped, built.error_count) == ([(1, "required"), (2, "cell_count")], 4)  # each row's first
 
 
+def test_every_error_is_counted_by_column_and_code_with_its_first_rows() -> None:
+    """The run form design §4.4: every error, not only those listed, counted by its column and its code, each with the
+    first rows that broke it: the most frequent first, then by column (a record's own error first), then by code."""
+    rows = [",x,zz", "ok,1", ",2,aa:bb:cc:dd:ee:ff", "a,y,zz", ",z,", ",3,", ",4,", ",5,", ",6,", "b,1,zz"]
+    table = read_table(("Site,VLAN,MAC\n" + "\n".join(rows) + "\n").encode(), max_rows=20, max_bytes=1000)
+    built = build_rows(table, COLUMNS, {"site": "Site", "vlan": "VLAN", "mac": "MAC"})
+    assert [asdict(g) for g in built.groups] == [
+        {"column": "site", "code": "required", "count": 7, "rows": [1, 3, 5, 6, 7]},
+        {"column": "mac", "code": "not_mac", "count": 3, "rows": [1, 4, 10]},
+        {"column": "vlan", "code": "not_integer", "count": 3, "rows": [1, 4, 5]},
+        {"column": None, "code": "cell_count", "count": 1, "rows": [2]},
+    ]
+    assert built.error_count == sum(g.count for g in built.groups) == 14
+
+
 def test_at_the_permitted_limits_the_detail_kept_is_bounded_and_the_count_exact() -> None:
     """The owner's M2 review: 200 required columns and 10,000 records of empty cells fit in a 2 MB file, and break 2
     million rules. The builder keeps the first errors in detail, each skipped record's number and first code, and
@@ -125,6 +141,11 @@ def test_at_the_permitted_limits_the_detail_kept_is_bounded_and_the_count_exact(
     assert (built.rows, built.error_count) == ([], 200 * MAX_ROWS)
     assert built.errors == [RowError(1, f"c{i}", "required") for i in range(LISTED_ERRORS)]
     assert built.skipped == [(n, "required") for n in range(1, MAX_ROWS + 1)]
+    # every column's errors counted, past the 100 each record lists: 200 groups, never one per error
+    names = sorted(f"c{i}" for i in range(200))  # all as frequent: by column, as text
+    assert [asdict(g) for g in built.groups] == [
+        {"column": name, "code": "required", "count": MAX_ROWS, "rows": [1, 2, 3, 4, 5]} for name in names
+    ]
 
 
 @pytest.mark.parametrize("length", [140_000, MAX_BYTES - 64])
```

- [ ] **Step 2: Run them**

Run:

```bash
cd backend && UV_FROZEN=1 UV_NO_SYNC=1 uv run pytest -q -n 6 \
  tests/apps/test_csv_input.py \
  tests/apps/api/test_csv_uploads_api.py
```

Expected: FAIL, 4 failed and 33 passed: `Built` has no `groups` (`AttributeError`, the two builder tests) and the
upload's answer no `error_groups` (`KeyError`, the two upload tests).

- [ ] **Step 3: Write the implementation**

Apply:

```diff
diff --git a/backend/src/dewpoint/apps/csv_input.py b/backend/src/dewpoint/apps/csv_input.py
index 41135768..4f3c3b25 100644
--- a/backend/src/dewpoint/apps/csv_input.py
+++ b/backend/src/dewpoint/apps/csv_input.py
@@ -30,6 +30,7 @@ FILE_CODES = frozenset(
 ROW_CODES = frozenset({"required", "cell_count"})  # beside a cell's conversion codes (`CELL_CODES`)
 MAPPING_CODES = frozenset({"required_unmapped", "unknown_column", "unknown_header", "header_reused"})
 LISTED_ERRORS = 100  # errors kept in detail; the count is every one
+GROUP_ROWS = 5  # each group's first record numbers
 
 csv.field_size_limit(max(csv.field_size_limit(), MAX_BYTES))
 
@@ -55,12 +56,23 @@ class RowError:
     code: str
 
 
+@dataclass(frozen=True)
+class ErrorGroup:
+    """Every error of one column and one code (the run form design §4.4): how many, and the first records."""
+
+    column: str | None  # the declared column's name; None for the record as a whole
+    code: str
+    count: int
+    rows: list[int]  # the first `GROUP_ROWS` record numbers that broke it
+
+
 @dataclass(frozen=True)
 class Built:
     rows: list[dict[str, Any]]  # every record that broke no rule
     skipped: list[tuple[int, str]]  # every other record: its number and the first rule it broke
     errors: list[RowError]  # the first `LISTED_ERRORS` errors, in order
     error_count: int  # every error
+    groups: list[ErrorGroup]  # every error by column and code: the most first, then by column, then by code
 
 
 def _records(text: str, delimiter: str) -> Iterator[list[str]]:
@@ -145,16 +157,24 @@ def mapping_problems(
 
 def build_rows(table: Table, columns: Sequence[Mapping[str, Any]], mapping: Mapping[str, str]) -> Built:
     """The rows `mapping` builds from `table` (its problems checked first, `mapping_problems`); a record that breaks a
-    rule builds none, and is reported within the builder's bounds."""
+    rule builds none, and is reported within the builder's bounds: every error is counted by its column and code, a
+    group per pair, never one per error."""
     position = {header: i for i, header in enumerate(table.headers)}
     rows: list[dict[str, Any]] = []
     skipped: list[tuple[int, str]] = []
     errors: list[RowError] = []
     count = 0
+    tally: dict[tuple[str | None, str], tuple[int, list[int]]] = {}
+
+    def broken(broke: list[RowError], error: RowError) -> None:
+        seen, first = tally.get((error.column, error.code), (0, []))
+        tally[(error.column, error.code)] = (seen + 1, first if len(first) == GROUP_ROWS else [*first, error.row])
+        broke.append(error)
+
     for number, record in enumerate(table.rows, start=1):
         broke: list[RowError] = []
         if len(record) != len(table.headers):
-            broke.append(RowError(number, None, "cell_count"))
+            broken(broke, RowError(number, None, "cell_count"))
         row: dict[str, Any] = {}
         for c in columns if not broke else ():
             header = mapping.get(c["name"])
@@ -163,11 +183,11 @@ def build_rows(table: Table, columns: Sequence[Mapping[str, Any]], mapping: Mapp
                 if "default" in c:
                     row[c["name"]] = c["default"]
                 elif c.get("required"):
-                    broke.append(RowError(number, c["name"], "required"))
+                    broken(broke, RowError(number, c["name"], "required"))
                 continue
             value, code = convert(c["type"], text, c.get("values"))
             if code is not None:
-                broke.append(RowError(number, c["name"], code))
+                broken(broke, RowError(number, c["name"], code))
             else:
                 row[c["name"]] = value
             if len(broke) > LISTED_ERRORS:  # a record keeps no more detail than the whole file lists
@@ -179,4 +199,6 @@ def build_rows(table: Table, columns: Sequence[Mapping[str, Any]], mapping: Mapp
         skipped.append((number, broke[0].code))
         count += len(broke)
         errors.extend(broke[: LISTED_ERRORS - len(errors)])
-    return Built(rows, skipped, errors, count)
+    groups = [ErrorGroup(column, code, n, first) for (column, code), (n, first) in tally.items()]
+    groups.sort(key=lambda g: (-g.count, g.column or "", g.code))
+    return Built(rows, skipped, errors, count, groups)
diff --git a/backend/src/dewpoint/apps/csv_uploads.py b/backend/src/dewpoint/apps/csv_uploads.py
index 44001ab8..487d3c9c 100644
--- a/backend/src/dewpoint/apps/csv_uploads.py
+++ b/backend/src/dewpoint/apps/csv_uploads.py
@@ -68,6 +68,8 @@ def described(table: Table, columns: Sequence[Mapping[str, Any]], mapping: Mappi
         "preview": preview,
         "errors": [asdict(e) for e in built.errors] if built else [],
         "error_count": built.error_count if built else 0,
+        "error_groups": [asdict(g) for g in built.groups] if built else [],  # every error, by column and code
+        "rows_with_errors": len(built.skipped) if built else 0,
     }
 
 
```

- [ ] **Step 4: Run them again**

Run: the same command.

Expected: PASS, 37 passed.

- [ ] **Step 5: Run the static checks**

Run: Task 2's static checks.

Expected: silent.

- [ ] **Step 6: Commit**

```bash
git add backend/src/dewpoint/apps/csv_input.py backend/src/dewpoint/apps/csv_uploads.py \
  backend/tests/apps/test_csv_input.py backend/tests/apps/api/test_csv_uploads_api.py
git commit -m "feat(csv): every error counted by column and problem (4e-2a)

The builder counts each error by its column and code as it finds it, with the first rows that broke it; an upload's
answer adds the groups and how many rows broke a rule (the run form design §4.4). What it keeps stays a group per
column and code.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: A staged file checked again under other columns (B11)

**Spec:** §4.3.

**Files:**
- Modify: `backend/src/dewpoint/apps/csv_uploads.py` (`UPLOAD_NOT_FOUND`, `UPLOAD_EXPIRED`, `UPLOAD_CONSUMED`,
  `UploadUnavailableError`, `previewed`), `backend/src/dewpoint/apps/admission.py` (the three codes, named from
  `csv_uploads`), `backend/src/dewpoint/apps/api/routes/csv_uploads.py` (`upload_csv`, `_staged`, `preview_csv`,
  `save_csv_mapping`), `backend/src/dewpoint/apps/api/responses.py` (`CsvProblemOut`, `CsvPreviewRowOut`,
  `CsvErrorGroupOut`, `CsvPreviewOut`, `CsvDefaultMappingOut`, `CsvUploadOut`, `CsvMappingOut`)
- Test: modify `backend/tests/apps/api/test_csv_uploads_api.py`, `backend/tests/apps/api/test_openapi.py`

**Interfaces:**
- Consumes: Task 4's `described` (`error_groups`, `rows_with_errors`); Task 3's `SLICE_4E2`.
- Produces:
  - `csv_uploads.previewed(s, keys, *, tenant_id, owner_id, workflow_id, upload_id, csv, version_id, mapping) ->
    dict[str, Any]`, raising `UploadUnavailableError(code)`;
  - `POST /api/v1/t/{tenant}/workflows/{workflow}/csv-uploads/{upload}/preview`, `run.start`, body
    `{"mapping": {...}}`, answering `CsvPreviewOut`;
  - the upload's answer `CsvUploadOut`, with `version_id`; the saved mapping's `CsvMappingOut`.

- [ ] **Step 1: Write the failing tests**

Apply:

```diff
diff --git a/backend/tests/apps/api/test_csv_uploads_api.py b/backend/tests/apps/api/test_csv_uploads_api.py
index 112ece29..597a1ad9 100644
--- a/backend/tests/apps/api/test_csv_uploads_api.py
+++ b/backend/tests/apps/api/test_csv_uploads_api.py
@@ -11,10 +11,12 @@ from typing import Any
 import pytest
 from sqlalchemy import text
 
+from dewpoint.apps.csv_slots import CsvSlots
 from dewpoint.engine.graph.csv import MAX_BYTES
 from tests.apps.api.helpers import member_client
 from tests.apps.api.test_run_requests_api import as_role
 from tests.apps.test_admission import KEYS, published
+from tests.apps.test_workflow_ops import publish, save
 from tests.support.graphs import G
 
 pytestmark = pytest.mark.usefixtures("development_deployment")
@@ -63,6 +65,9 @@ async def test_an_operator_uploads_a_csv_and_gets_its_mapping_preview_and_errors
     body = answer.json()
     assert body["headers"] == ["Site", "VLAN", "PSK", "Extra"]
     assert body["mapping"] == {"site": "Site", "vlan": "VLAN", "psk": "PSK"}
+    async with owner_sessionmaker() as s:
+        active = (await s.execute(text("select active_version_id from workflows where id = :w"), {"w": wf})).scalar()
+    assert (body["version_id"], body["default_mapping"]) == (str(active), {"status": "none"})  # the version it checked
     assert (body["row_count"], body["problems"], body["masked_columns"]) == (3, [], ["psk"])
     assert body["preview"] == [
         {"row": 1, "cells": {"site": "paris", "vlan": "10"}},
@@ -223,3 +228,89 @@ async def test_an_integer_cell_too_long_for_python_to_read_is_a_rows_error(
     assert answer.status_code == 201, answer.text[:200]
     body = answer.json()
     assert (body["errors"], body["error_count"]) == ([{"row": 1, "column": "vlan", "code": "out_of_range"}], 1)
+
+
+# --- a staged file checked again under other columns (B11; the run form design §4.3) --------------------------------
+
+
+def preview_url(ctx: Any, wf: uuid.UUID, upload: str) -> str:
+    return f"{uploads_url(ctx, wf)}/{upload}/preview"
+
+
+async def test_a_staged_file_is_checked_again_under_other_columns(
+    keyed_app, csv_workflow, owner_sessionmaker, api_settings
+) -> None:
+    ctx, wf = csv_workflow
+    client = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx)
+    upload = (await client.post(uploads_url(ctx, wf), content=FILE, headers=CSV_TYPE)).json()
+    url = preview_url(ctx, wf, upload["upload_id"])
+    answer = await client.post(url, json={"mapping": {"site": "Extra", "vlan": "VLAN"}})
+    assert answer.status_code == 200, answer.text
+    body = answer.json()
+    assert set(body) == {"version_id", "mapping", "problems", "masked_columns", "preview", "errors", "error_count",
+                         "error_groups", "rows_with_errors"}  # fmt: skip
+    assert (body["version_id"], body["mapping"]) == (upload["version_id"], {"site": "Extra", "vlan": "VLAN"})
+    assert (body["problems"], body["error_count"], body["error_groups"], body["rows_with_errors"]) == ([], 0, [], 0)
+    assert body["preview"][0] == {"row": 1, "cells": {"site": "x", "vlan": "10"}}  # the file's cells, as written
+    unmapped = (await client.post(url, json={"mapping": {"vlan": "VLAN"}})).json()
+    assert (unmapped["problems"], unmapped["errors"]) == ([{"column": "site", "code": "required_unmapped"}], [])
+
+
+async def test_a_preview_checks_the_file_against_the_version_active_now(
+    keyed_app, csv_workflow, owner_sessionmaker, api_sessionmaker, api_settings
+) -> None:
+    """A publish since the upload: the preview names the new version and checks the file against its declaration."""
+    ctx, wf = csv_workflow
+    client = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx)
+    upload = (await client.post(uploads_url(ctx, wf), content=FILE, headers=CSV_TYPE)).json()
+    vlan = {"header": "VLAN", "name": "vlan", "type": "integer", "required": True}  # was optional, defaulting to 1
+    stricter = {**CSV, "columns": [CSV["columns"][0], vlan, CSV["columns"][2]]}
+    changed = G().node("a", "testkit.echo@1", {"value": 2}).data() | {"settings": {"csv": stricter}}
+    await save(api_sessionmaker, ctx, wf, changed)
+    version = (await publish(api_sessionmaker, ctx, wf, api_settings)).version
+    assert version is not None
+    body = (await client.post(preview_url(ctx, wf, upload["upload_id"]), json={"mapping": upload["mapping"]})).json()
+    assert body["version_id"] == str(version.id) != upload["version_id"]
+    assert [(g["column"], g["code"], g["rows"]) for g in body["error_groups"]] == [
+        ("site", "required", [3]), ("vlan", "required", [2]),
+    ]  # fmt: skip
+
+
+async def test_a_preview_is_of_the_callers_own_upload_while_its_staged(
+    keyed_app, csv_workflow, owner_sessionmaker, api_settings
+) -> None:
+    """Another user's upload isn't found, as at start; an expired one is gone; a consumed one has started a run."""
+    ctx, wf = csv_workflow
+    mine = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx)
+    upload = (await mine.post(uploads_url(ctx, wf), content=FILE, headers=CSV_TYPE)).json()["upload_id"]
+    url, body = preview_url(ctx, wf, upload), {"mapping": {"site": "Site"}}
+    other = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx)
+    assert ((answer := await other.post(url, json=body)).status_code, answer.json()) == (
+        404, {"error": "upload_not_found"},
+    )  # fmt: skip
+    viewer = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "viewer")
+    assert (await viewer.post(url, json=body)).status_code == 403
+    for change, status, code in (
+        ("created_at = now() - interval '2 hours', expires_at = now() - interval '1 hour'", 410, "upload_expired"),
+        ("staged = null, consumed_by = gen_random_uuid(), consumed_at = now()", 409, "upload_consumed"),
+    ):
+        async with owner_sessionmaker() as s, s.begin():
+            await s.execute(text(f"update csv_uploads set {change} where id = :i"), {"i": upload})
+        assert ((answer := await mine.post(url, json=body)).status_code, answer.json()) == (status, {"error": code})
+
+
+async def test_a_preview_takes_a_csv_slot_and_records_nothing(
+    keyed_app, csv_workflow, owner_sessionmaker, api_settings
+) -> None:
+    ctx, wf = csv_workflow
+    client = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx)
+    upload = (await client.post(uploads_url(ctx, wf), content=FILE, headers=CSV_TYPE)).json()["upload_id"]
+    async with owner_sessionmaker() as s:
+        audited = (await s.execute(text("select count(*) from audit_log"))).scalar_one()
+    keyed_app.state.csv_slots = CsvSlots(1)
+    with keyed_app.state.csv_slots.held():  # another file, still being read
+        busy = await client.post(preview_url(ctx, wf, upload), json={"mapping": {"site": "Site"}})
+    assert (busy.status_code, busy.json(), busy.headers.get("retry-after")) == (503, {"error": "csv_busy"}, "1")
+    assert (await client.post(preview_url(ctx, wf, upload), json={"mapping": {"site": "Site"}})).status_code == 200
+    async with owner_sessionmaker() as s:
+        assert (await s.execute(text("select count(*) from audit_log"))).scalar_one() == audited
diff --git a/backend/tests/apps/api/test_openapi.py b/backend/tests/apps/api/test_openapi.py
index 2acad3d1..aba5dc39 100644
--- a/backend/tests/apps/api/test_openapi.py
+++ b/backend/tests/apps/api/test_openapi.py
@@ -214,6 +214,9 @@ def test_slice_4d1_routes_name_their_answer(method: str, path: str) -> None:
 SLICE_4E2 = [  # the run form's answers (the run form design §4)
     ("post", "/api/v1/t/{tenant_id}/workflows/{workflow_id}/runs"),
     ("post", "/api/v1/t/{tenant_id}/runs/{request_id}/rerun"),
+    ("post", "/api/v1/t/{tenant_id}/workflows/{workflow_id}/csv-uploads"),
+    ("post", "/api/v1/t/{tenant_id}/workflows/{workflow_id}/csv-uploads/{upload_id}/preview"),
+    ("put", "/api/v1/t/{tenant_id}/workflows/{workflow_id}/csv-mapping"),
 ]
 
 
```

- [ ] **Step 2: Run them**

Run:

```bash
cd backend && UV_FROZEN=1 UV_NO_SYNC=1 uv run pytest -q -n 6 \
  tests/apps/api/test_csv_uploads_api.py \
  tests/apps/api/test_csv_mappings_api.py \
  tests/apps/api/test_openapi.py
```

Expected: FAIL, 8 failed and 101 passed: the preview route doesn't exist (404 `not_found` for the four preview tests; no
such path in the schema), the upload's answer has no `version_id` (`KeyError`), and the upload's and the saved mapping's
answers are untyped objects.

- [ ] **Step 3: Write the implementation**

Apply:

```diff
diff --git a/backend/src/dewpoint/apps/admission.py b/backend/src/dewpoint/apps/admission.py
index 6411a029..cd573463 100644
--- a/backend/src/dewpoint/apps/admission.py
+++ b/backend/src/dewpoint/apps/admission.py
@@ -88,9 +88,9 @@ NODE_TYPE_RETIRED = "node_type_retired"
 CEL_PROFILE_RETIRED = "cel_profile_retired"
 CSV_NOT_DECLARED = "csv_not_declared"
 CSV_MAPPING_INVALID = "csv_mapping_invalid"
-UPLOAD_NOT_FOUND = "upload_not_found"
-UPLOAD_EXPIRED = "upload_expired"
-UPLOAD_CONSUMED = "upload_consumed"
+UPLOAD_NOT_FOUND = csv_uploads.UPLOAD_NOT_FOUND
+UPLOAD_EXPIRED = csv_uploads.UPLOAD_EXPIRED
+UPLOAD_CONSUMED = csv_uploads.UPLOAD_CONSUMED
 TARGET_INVALID = "target_invalid"
 CSV_NOT_SIMULATED = "csv_not_simulated"
 CSV_NOT_SIMULATED_MESSAGE = (
diff --git a/backend/src/dewpoint/apps/api/responses.py b/backend/src/dewpoint/apps/api/responses.py
index 0b337b39..1accc2fa 100644
--- a/backend/src/dewpoint/apps/api/responses.py
+++ b/backend/src/dewpoint/apps/api/responses.py
@@ -883,6 +883,62 @@ class CsvErrorOut(_Answer):
     code: str
 
 
+class CsvProblemOut(_Answer):
+    column: str  # the declared column's name
+    code: str  # what keeps the mapping from building rows
+
+
+class CsvPreviewRowOut(_Answer):
+    row: int
+    cells: dict[str, str]  # the file's cells as written, under the mapping; never a sensitive column's
+
+
+class CsvErrorGroupOut(_Answer):
+    column: str | None  # null for the record as a whole
+    code: str
+    count: int
+    rows: list[int]  # the first five records that broke it
+
+
+class CsvPreviewOut(_Answer):
+    """A staged CSV described under a mapping, against the active version's declaration (engine 2b spec §8.1; the run
+    form design §4.3, §4.4): what keeps the mapping from building rows, the first records' cells, the first 100 errors
+    in detail, and every error counted by column and code."""
+
+    version_id: str  # the version whose declaration it was checked against
+    mapping: dict[str, str]
+    problems: list[CsvProblemOut]
+    masked_columns: list[str]
+    preview: list[CsvPreviewRowOut]
+    errors: list[CsvErrorOut]
+    error_count: int
+    error_groups: list[CsvErrorGroupOut]
+    rows_with_errors: int
+
+
+class CsvDefaultMappingOut(_Answer):
+    status: Literal["none", "applied", "stale"]
+    problems: list[CsvProblemOut] | None = None  # a stale one's, left out otherwise
+
+
+class CsvUploadOut(CsvPreviewOut):
+    """A staged upload (engine 2b spec §8.1): its id and hour, the file's headers and records, the mapping proposed
+    (the saved default, else the exact matches), and the file described under it."""
+
+    upload_id: str
+    expires_at: str
+    headers: list[str]
+    row_count: int
+    default_mapping: CsvDefaultMappingOut
+
+
+class CsvMappingOut(_Answer):
+    """A workflow's saved default mapping, and the version it was checked against."""
+
+    mapping: dict[str, str]
+    version_id: str
+
+
 class CsvRecordOut(_Answer):
     """A CSV start's file as admission read it (engine 2b spec §8.1): the mapping from declared columns to its headers,
     the rows run, every skipped row, and the first errors in detail with their count."""
diff --git a/backend/src/dewpoint/apps/api/routes/csv_uploads.py b/backend/src/dewpoint/apps/api/routes/csv_uploads.py
index 120ad539..c92d7729 100644
--- a/backend/src/dewpoint/apps/api/routes/csv_uploads.py
+++ b/backend/src/dewpoint/apps/api/routes/csv_uploads.py
@@ -15,10 +15,11 @@ from pydantic import BaseModel, ConfigDict, Field
 from sqlalchemy.ext.asyncio import AsyncSession
 
 from dewpoint.apps import admission
+from dewpoint.apps.api.responses import CsvMappingOut, CsvPreviewOut, CsvUploadOut
 from dewpoint.apps.api.routes.run_requests import csv_slot, get_keys, key_unusable, taken
 from dewpoint.apps.csv_input import CsvFileError, mapping_problems
 from dewpoint.apps.csv_slots import Slot
-from dewpoint.apps.csv_uploads import byte_cap, declaration, save_default, stage
+from dewpoint.apps.csv_uploads import UploadUnavailableError, byte_cap, declaration, previewed, save_default, stage
 from dewpoint.core.authz.permissions import P
 from dewpoint.core.crypto.keys import KeySource
 from dewpoint.core.http import TenantContext, get_db, require
@@ -66,7 +67,12 @@ async def _read(request: Request, cap: int) -> bytes:
     return b"".join(chunks)
 
 
-@router.post("/t/{tenant_id}/workflows/{workflow_id}/csv-uploads", status_code=201)
+@router.post(
+    "/t/{tenant_id}/workflows/{workflow_id}/csv-uploads",
+    status_code=201,
+    response_model=CsvUploadOut,
+    response_model_exclude_unset=True,
+)
 async def upload_csv(
     workflow_id: uuid.UUID,
     request: Request,
@@ -78,33 +84,61 @@ async def upload_csv(
     """201 with the staged upload's id, its mapping, preview and errors."""
     if request.headers.get("content-type", "").split(";")[0].strip().lower() != "text/csv":
         raise HTTPException(415, detail={"error": "unsupported_media_type"})
-    _, csv = await _active_csv(db, workflow_id)
+    version, csv = await _active_csv(db, workflow_id)
     cap = byte_cap(csv)
     declared = request.headers.get("content-length", "")
     if declared.isdigit() and int(declared) > cap:
         raise HTTPException(413, detail=TOO_LARGE)
     taken(slot)  # before its body is read: a parse at the caps holds ~90 MiB, through its commit (2b-4b M3)
-    return await _staged(request, cap, db, keys, ctx, workflow_id, csv)
+    return await _staged(request, cap, db, keys, ctx, workflow_id, csv, version.id)
 
 
 async def _staged(
     request: Request, cap: int, db: AsyncSession, keys: KeySource, ctx: TenantContext, workflow_id: uuid.UUID,
-    csv: dict[str, Any],
+    csv: dict[str, Any], version_id: uuid.UUID,
 ) -> dict[str, object]:  # fmt: skip
     try:
         data = await _read(request, cap)
     except _TooLargeError:
         raise HTTPException(413, detail=TOO_LARGE) from None
     try:
-        return await stage(db, keys, tenant_id=ctx.tenant_id, owner_id=ctx.user.id, workflow_id=workflow_id, csv=csv,
-                           data=data)  # fmt: skip
+        staged = await stage(db, keys, tenant_id=ctx.tenant_id, owner_id=ctx.user.id, workflow_id=workflow_id,
+                             csv=csv, data=data)  # fmt: skip
+        return {"version_id": str(version_id), **staged}  # the version whose declaration it was checked against
     except CsvFileError as e:
         raise HTTPException(422, detail={"error": e.code}) from None
     except Exception as e:
         raise key_unusable(e) from None
 
 
-@router.put("/t/{tenant_id}/workflows/{workflow_id}/csv-mapping")
+@router.post("/t/{tenant_id}/workflows/{workflow_id}/csv-uploads/{upload_id}/preview", response_model=CsvPreviewOut)
+async def preview_csv(
+    workflow_id: uuid.UUID,
+    upload_id: uuid.UUID,
+    body: MappingIn,
+    slot: Slot = Depends(csv_slot, scope="function"),  # before the session: given back after its commit
+    ctx: TenantContext = Depends(require(P.RUN_START)),
+    db: AsyncSession = Depends(get_db, scope="function"),
+    keys: KeySource = Depends(get_keys),
+) -> dict[str, object]:
+    """The caller's staged upload described again under `body.mapping`, against the active version's declaration
+    (B11; the run form design §4.3): 404 `upload_not_found`, 409 `upload_consumed`, 410 `upload_expired`, as a start
+    finds them; 503 `csv_busy` with every CSV slot held."""
+    version, csv = await _active_csv(db, workflow_id)
+    taken(slot)  # before the file is opened: it's read whole, as at upload
+    try:
+        return await previewed(db, keys, tenant_id=ctx.tenant_id, owner_id=ctx.user.id, workflow_id=workflow_id,
+                               upload_id=upload_id, csv=csv, version_id=version.id, mapping=body.mapping)  # fmt: skip
+    except UploadUnavailableError as e:
+        status = {admission.UPLOAD_NOT_FOUND: 404, admission.UPLOAD_CONSUMED: 409, admission.UPLOAD_EXPIRED: 410}
+        raise HTTPException(status[e.code], detail={"error": e.code}) from None
+    except CsvFileError as e:  # the version's caps, lower than those it was uploaded under
+        raise HTTPException(422, detail={"error": e.code}) from None
+    except Exception as e:
+        raise key_unusable(e) from None
+
+
+@router.put("/t/{tenant_id}/workflows/{workflow_id}/csv-mapping", response_model=CsvMappingOut)
 async def save_csv_mapping(
     workflow_id: uuid.UUID,
     body: MappingIn,
diff --git a/backend/src/dewpoint/apps/csv_uploads.py b/backend/src/dewpoint/apps/csv_uploads.py
index 487d3c9c..24361585 100644
--- a/backend/src/dewpoint/apps/csv_uploads.py
+++ b/backend/src/dewpoint/apps/csv_uploads.py
@@ -22,7 +22,7 @@ from dataclasses import asdict
 from datetime import timedelta
 from typing import Any
 
-from sqlalchemy import func, update
+from sqlalchemy import func, select, update
 from sqlalchemy.dialects.postgresql import insert
 from sqlalchemy.ext.asyncio import AsyncSession
 
@@ -38,6 +38,18 @@ PURPOSE = "csv.upload"
 MAPPING_PURPOSE = "csv.mapping"
 TTL = timedelta(hours=1)
 PREVIEW_ROWS = 5
+UPLOAD_NOT_FOUND = "upload_not_found"
+UPLOAD_EXPIRED = "upload_expired"
+UPLOAD_CONSUMED = "upload_consumed"
+
+
+class UploadUnavailableError(Exception):
+    """A staged upload the caller can't use: another's, another workflow's or none (`upload_not_found`), consumed by a
+    start (`upload_consumed`), or past its hour (`upload_expired`)."""
+
+    def __init__(self, code: str) -> None:
+        super().__init__(code)
+        self.code = code
 
 
 def declaration(version: WorkflowVersion) -> dict[str, Any] | None:
@@ -115,6 +127,28 @@ async def stage(
     }
 
 
+async def previewed(
+    s: AsyncSession, keys: KeySource, *, tenant_id: uuid.UUID, owner_id: uuid.UUID, workflow_id: uuid.UUID,
+    upload_id: uuid.UUID, csv: Mapping[str, Any], version_id: uuid.UUID, mapping: Mapping[str, str],
+) -> dict[str, Any]:  # fmt: skip
+    """The staged upload described again under `mapping` (B11; the run form design §4.3), against version
+    `version_id`'s declaration `csv`: its owner's, for its workflow, unconsumed and in its hour, else
+    UploadUnavailableError, checked as a start checks it. Read and described in a thread, inside the caller's CSV slot;
+    nothing is logged or audited, as at upload."""
+    query = select(CsvUpload, CsvUpload.expires_at > func.statement_timestamp()).where(CsvUpload.id == upload_id)
+    found = (await s.execute(query)).one_or_none()  # row-level security: the caller's tenant's only
+    upload, live = found if found is not None else (None, False)
+    if upload is None or (upload.tenant_id, upload.owner_id, upload.workflow_id) != (tenant_id, owner_id, workflow_id):
+        raise UploadUnavailableError(UPLOAD_NOT_FOUND)
+    if upload.consumed_by is not None or upload.staged is None:
+        raise UploadUnavailableError(UPLOAD_CONSUMED)
+    if not live:
+        raise UploadUnavailableError(UPLOAD_EXPIRED)
+    data = await ClaimCipher(keys, purpose=PURPOSE).open(str(tenant_id), str(upload.id), upload.staged)
+    table = await asyncio.to_thread(read_table, data, max_rows=int(csv["max_rows"]), max_bytes=byte_cap(csv))
+    return {"version_id": str(version_id), **(await asyncio.to_thread(described, table, csv["columns"], mapping))}
+
+
 async def save_default(
     s: AsyncSession, keys: KeySource, *, tenant_id: uuid.UUID, workflow_id: uuid.UUID, version_id: uuid.UUID,
     user_id: uuid.UUID, mapping: Mapping[str, str],
```

- [ ] **Step 4: Run them again**

Run: the same command.

Expected: PASS, 109 passed.

- [ ] **Step 5: Run the static checks**

Run: Task 2's static checks.

Expected: silent.

- [ ] **Step 6: Commit**

```bash
git add backend/src/dewpoint/apps/csv_uploads.py backend/src/dewpoint/apps/admission.py \
  backend/src/dewpoint/apps/api/routes/csv_uploads.py backend/src/dewpoint/apps/api/responses.py \
  backend/tests/apps/api/test_csv_uploads_api.py backend/tests/apps/api/test_openapi.py
git commit -m "feat(api): a staged CSV checked again under other columns (B11, 4e-2a)

POST …/csv-uploads/{upload}/preview describes the caller's staged file under a new mapping, against the active
version's declaration, in a CSV slot, refused as a start refuses the upload; the upload's answer names the version it
checked; the CSV answers typed (the run form design §4.3).

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: A same-rows re-run keeps its rows' record

**Spec:** §4.5.

**Files:**
- Modify: `backend/src/dewpoint/apps/admission.py` (`_frozen`)
- Test: modify `backend/tests/apps/test_admission_csv.py`, `backend/tests/apps/api/test_csv_starts_api.py`

**Interfaces:**
- Consumes: `claims.read_csv_record`, `claims.write_csv_record`; `Rerun.of`.
- Produces: a re-run that rebuilds its original's rows (no new input, no new file) has its original's CSV record, and
  an audit entry with `csv_rows` and `csv_skipped`.

- [ ] **Step 1: Write the failing tests**

Apply:

```diff
diff --git a/backend/tests/apps/api/test_csv_starts_api.py b/backend/tests/apps/api/test_csv_starts_api.py
index 09b560c4..162cc85f 100644
--- a/backend/tests/apps/api/test_csv_starts_api.py
+++ b/backend/tests/apps/api/test_csv_starts_api.py
@@ -116,3 +116,19 @@ async def test_a_rerun_takes_a_new_upload(keyed_app, csv_ready, owner_sessionmak
     assert details["csv"]["row_count"] == 1
     again = await client.post(rerun_url, json=body, headers={"Idempotency-Key": "r1"})
     assert (again.status_code, again.json()["id"]) == (202, answer.json()["id"])  # found by its key, upload consumed
+
+
+async def test_a_rerun_of_the_same_rows_shows_its_originals_record(
+    keyed_app, csv_ready, owner_sessionmaker, api_settings
+) -> None:
+    """The run form design §4.5: what a CSV re-run's page shows of its rows (4e-1a's I1 left it to 4e-2)."""
+    ctx, wf = csv_ready
+    client = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx)
+    first = await client.post(runs_url(ctx, wf), json=csv_body(await uploaded(client, ctx, wf)),
+                              headers={"Idempotency-Key": "c1"})  # fmt: skip
+    rerun_url = f"/api/v1/t/{ctx.tenant_id}/runs/{first.json()['id']}/rerun"
+    answer = await client.post(rerun_url, headers={"Idempotency-Key": "r1"})
+    assert answer.status_code == 202, answer.text
+    runs = f"/api/v1/t/{ctx.tenant_id}/runs"
+    original = (await client.get(f"{runs}/{first.json()['id']}")).json()["csv"]
+    assert original["row_count"] == 1 and (await client.get(f"{runs}/{answer.json()['id']}")).json()["csv"] == original
diff --git a/backend/tests/apps/test_admission_csv.py b/backend/tests/apps/test_admission_csv.py
index 865758ba..c1fa4dce 100644
--- a/backend/tests/apps/test_admission_csv.py
+++ b/backend/tests/apps/test_admission_csv.py
@@ -301,6 +301,31 @@ async def test_a_rerun_takes_the_original_rows_or_a_new_csv(csv_ready, api_sessi
     assert (await full_input(dispatch_sessionmaker, ctx, fresh.request.id))["rows"] == [{"site": "nice", "vlan": 1}]
 
 
+async def test_a_same_rows_rerun_keeps_its_originals_csv_record_and_a_rerun_of_it_finds_it(
+    csv_ready, owner_sessionmaker, api_sessionmaker, dispatch_sessionmaker
+) -> None:
+    """The run form design §4.5: a re-run that rebuilds its original's rows copies that start's CSV record, its audit
+    entry counting them, so its page shows its rows and a re-run of it finds them; a new file has its own record."""
+    ctx, wf = csv_ready
+    first = (await admit(api_sessionmaker, ctx, wf, csv=start(await staged(api_sessionmaker, ctx, wf)))).request
+    kept = await record(api_sessionmaker, ctx, first.id)
+    again = (await admit(api_sessionmaker, ctx, wf, key="r1", source="rerun", rerun=admission.Rerun(first.id),
+                         input=await full_input(dispatch_sessionmaker, ctx, first.id))).request  # fmt: skip
+    twice = (await admit(api_sessionmaker, ctx, wf, key="r2", source="rerun", rerun=admission.Rerun(again.id),
+                         input=await full_input(dispatch_sessionmaker, ctx, again.id))).request  # fmt: skip
+    assert await record(api_sessionmaker, ctx, again.id) == await record(api_sessionmaker, ctx, twice.id) == kept
+    async with owner_sessionmaker() as s:
+        found = await s.execute(text("select details from audit_log where action = 'run.request' and target_id = :i"),
+                                {"i": str(again.id)})  # fmt: skip
+        details = found.scalar_one()
+    assert (details["csv_rows"], details["csv_skipped"]) == (2, 0)
+    upload = await staged(api_sessionmaker, ctx, wf, b"Site\nnice\n")
+    fresh = (await admit(api_sessionmaker, ctx, wf, key="r3", source="rerun", input={"token": TOKEN},
+                         rerun=admission.Rerun(again.id, {"token": TOKEN}, start(upload, {"site": "Site"})),
+                         csv=start(upload, {"site": "Site"}))).request  # fmt: skip
+    assert (await record(api_sessionmaker, ctx, fresh.id))["row_count"] == 1
+
+
 WIDE = {"columns": [{"header": f"h{i}", "name": f"c{i}", "type": "string", "required": True} for i in range(200)],
         "max_rows": 10_000, "max_bytes": MAX_BYTES}  # fmt: skip
 WIDE_FILE = (",".join(f"h{i}" for i in range(200)) + "\n" + ("," * 199 + "\n") * 10_000).encode()
```

- [ ] **Step 2: Run them**

Run:

```bash
cd backend && UV_FROZEN=1 UV_NO_SYNC=1 uv run pytest -q -n 6 \
  tests/apps/test_admission_csv.py \
  tests/apps/api/test_csv_starts_api.py
```

Expected: FAIL, 2 failed and 20 passed: a same-rows re-run has no CSV record (`None`), so the run's details show none.

- [ ] **Step 3: Write the implementation**

Apply:

```diff
diff --git a/backend/src/dewpoint/apps/admission.py b/backend/src/dewpoint/apps/admission.py
index cd573463..305f4bf3 100644
--- a/backend/src/dewpoint/apps/admission.py
+++ b/backend/src/dewpoint/apps/admission.py
@@ -480,6 +480,12 @@ async def _frozen(
     except InputRefusedError as e:
         raise _Refused(e.reason, e.reasons, version.id) from None
     envelope_id = await claims.write_envelope(s, ClaimCipher(keys), tenant_id, request_id=request_id, envelope=envelope)
+    if retained and rerun is not None:  # its original's rows again: their record too (the run form design §4.5)
+        kept = await claims.read_csv_record(s, ClaimCipher(keys), tenant_id, request_id=rerun.of)
+        if kept is not None:
+            await claims.write_csv_record(s, ClaimCipher(keys), tenant_id, request_id=request_id, record=kept)
+            counted = {"csv_rows": kept["row_count"], "csv_skipped": len(kept["skipped"])}
+            return _Frozen(version.id, envelope_id, counted)
     if built is None or csv is None:
         return _Frozen(version.id, envelope_id, {})
     record = {
```

- [ ] **Step 4: Run them again**

Run: the same command.

Expected: PASS, 22 passed.

- [ ] **Step 5: Run the static checks**

Run: Task 2's static checks.

Expected: silent.

- [ ] **Step 6: Commit**

```bash
git add backend/src/dewpoint/apps/admission.py backend/tests/apps/test_admission_csv.py \
  backend/tests/apps/api/test_csv_starts_api.py
git commit -m "feat(runs): a same-rows CSV re-run keeps its rows' record (4e-2a)

A re-run that rebuilds its original's rows copies that start's CSV record, its audit entry counting them, so its
page shows its rows and a re-run of it finds them (the run form design §4.5).

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

**Milestone 2 ends here.** Append `### 4e-2a, milestone 2 (<date>)` to the ledger, as for milestone 1, commit it as
`docs(editor-4): 4e-2a milestone 2`, and pause for the owner's review.

---

# Milestone 3 — The client, the docs, every check

### Task 7: The client, the docs, every check, the final checkpoint

**Spec:** §4 (the generated client), §6.

**Files:**
- Modify: `frontend/src/api/openapi.json`, `frontend/src/api/schema.d.ts` (regenerated), `docs/operations/runs.md`
  ("Starting a run", "Starting a run from a CSV", "Cancelling and re-running"),
  `docs/superpowers/plans/2026-10-05-editor-ui-4-ledger.md` (the final checkpoint)

**Interfaces:**
- Consumes: every route and model above.
- Produces: the typed client 4e-2b reads.

- [ ] **Step 1: Regenerate the client**

Run:

```bash
cd backend && UV_FROZEN=1 UV_NO_SYNC=1 uv run dewpoint api openapi > ../frontend/src/api/openapi.json
cd ../frontend && pnpm gen:api && pnpm check:api
```

Expected: `openapi.json` gains the preview route and the run form's models (434 lines added, 13 removed);
`schema.d.ts` gains their types (188 added, 13 removed); `check:api` passes. Never edit either by hand.

- [ ] **Step 2: Check that the frontend still passes**

Run:

```bash
cd frontend && pnpm exec tsc -b --noEmit && pnpm exec eslint . && pnpm exec vitest run
```

Expected: the type check and ESLint silent; 1288 passed in 99 files, as on main (ruling 12).

- [ ] **Step 3: The docs**

Apply:

```diff
diff --git a/docs/operations/runs.md b/docs/operations/runs.md
index 26401674..1e425da8 100644
--- a/docs/operations/runs.md
+++ b/docs/operations/runs.md
@@ -20,6 +20,11 @@ webhook's event, by the dispatcher ([webhook ingress](ingress.md)).
 `{"input": {...}, "mode": "live" | "simulate"}`, admits a request and answers 202 with it, `queued`. The API never
 talks to Temporal.
 
+- `"expected_version_id"`, optional, names the version the person confirmed (the run form shows it): once another
+  version is active, nothing is admitted and the answer is 409 `version_changed`, naming the `active_version_id` and
+  the `active_version_number`. The key covers it: an exact retry still returns its request, whatever is active now, and
+  the same key naming another version, or none, is 409 `idempotency_conflict`.
+
 - The same key with the same body returns the same request, as it is now; another body under the key is 409
   `idempotency_conflict`. Retrying after a lost answer is safe. A key is recognized only while its request is stored:
   past the request's retention cutoff a retry admits nothing and answers 410 `request_not_retained`, and once
@@ -34,13 +39,15 @@ talks to Temporal.
 - A refusal answers with its code and fixed messages that never quote a value: 503 `production_runs_disabled`,
   `environment_not_recorded`, `no_current_build` or `key_unusable` (the tenant's data key can't be read); 422
   `input_invalid` or `secret_index_limit`, with each place and rule the input breaks; 409 `workflow_disabled`,
-  `not_active`, `version_unusable`, `node_type_retired`, `cel_profile_retired` or `tenant_erasing`; 404 for a workflow
-  that isn't the tenant's. A refused start leaves no request.
+  `not_active`, `version_changed`, `version_unusable`, `node_type_retired`, `cel_profile_retired` or
+  `tenant_erasing`; 404 for a workflow that isn't the tenant's. A refused start leaves no request.
 
 `GET /api/v1/t/{tenant}/workflows/{workflow}/start-form` (`run.start`) describes the active version's input for a
 form: its typed top-level fields, each with its `type`, whether it's `required`, its `title`, `description`, `enum`
 and `default`, and `x-dewpoint-picker` as `picker`. A sensitive field never shows a value its schema holds:
-`default_masked` and `enum_masked` say there is one. 409 `not_active` without an active version.
+`default_masked` and `enum_masked` say there is one. It names the version (`version_id`, `version_number`,
+`published_at`, and `published_by`, its publisher's email, null once they're gone). 409 `not_active` without an active
+version.
 
 ## Starting a run from a CSV
 
@@ -61,9 +68,17 @@ sees `trigger.rows` (one object per row, each column by its name) and `trigger.r
   read as data only: UTF-8 with an optional BOM, the delimiter detected among comma, semicolon and tab, strict quoting,
   unique headers, a field as long as the file allows. A file that can't be read is 422 with its code (`csv_encoding`,
   `csv_empty`, `csv_duplicate_header`, `csv_malformed`, `csv_too_many_rows`, `csv_too_large`). The file is staged,
-  encrypted, for one hour, for its uploader only. The answer gives the headers, the proposed mapping (declared names to
-  headers), what keeps it from building rows, a preview of the first rows without the sensitive columns, and the
-  first 100 errors with their count, each a row number, a column and a code, never a cell.
+  encrypted, for one hour, for its uploader only. The answer gives the version whose declaration it was checked against
+  (`version_id`), the headers, the proposed mapping (declared names to headers), what keeps it from building rows, a
+  preview of the first rows' cells as written, without the sensitive columns, and the first 100 errors with their
+  count, each a row number, a column and a code, never a cell. Every error is also counted by its column and code
+  (`error_groups`: each one's count and first five rows, the most frequent first), with how many rows broke a rule
+  (`rows_with_errors`).
+- **Checking it again:** `POST …/csv-uploads/{upload}/preview` (`run.start`) with `{"mapping": {...}}` describes the
+  staged file again under that mapping, against the active version's declaration, as the upload's answer does without
+  its id, hour, headers, row count and default. It's its uploader's only (404 `upload_not_found`), 410
+  `upload_expired` past its hour, 409 `upload_consumed` once a start used it; it takes a CSV slot (503 `csv_busy`).
+  Nothing is logged or audited.
 - **The saved default mapping:** `PUT …/workflows/{workflow}/csv-mapping` (`trigger.manage`) saves one per workflow,
   encrypted. An upload proposes it while it fits the active version's declaration; one a later version no longer fits
   is reported `stale`, with each column's code, and never applied, until a new one is saved.
@@ -80,9 +95,9 @@ sees `trigger.rows` (one object per row, each column by its name) and `trigger.r
 - **Memory, per API process:** at the platform's caps, an upload's parse peaks near 145 MiB and holds about 90 MiB
   until it answers, and a CSV start's rows about 235 MiB until its transaction commits (measured as Python's own
   allocations: `tests/probes/csv_memory.py`). So each API process takes at most `DEWPOINT_CSV_CONCURRENCY` uploads,
-  CSV starts and re-runs keeping their original's input at once (2 by default); one past it is refused at once with
-  503 `csv_busy` and `Retry-After: 1`, before an upload's body is read or a start opens its file, nothing recorded:
-  ask again. A slot is held until the request's transaction commits. Measured as the process sees it
+  previews, CSV starts and re-runs keeping their original's input at once (2 by default); one past it is refused at
+  once with 503 `csv_busy` and `Retry-After: 1`, before an upload's body is read or a start opens its file, nothing
+  recorded: ask again. A slot is held until the request's transaction commits. Measured as the process sees it
   (`tests/probes/test_csv_rss.py`, the worst shape, through the commit, on one macOS development machine, 2026-10-09):
   two worst-case jobs at once raised the process's physical footprint (its resident memory with its compressed pages,
   the allocator's overhead included) about 465 MiB above idle, one about 325 MiB, and the allocator kept most of it
@@ -429,7 +444,9 @@ optional (the old one's by default). The key covers what was asked (the request
 checked before anything is rebuilt: an exact retry returns the request it admitted even once retention has removed the
 old input, while the re-run's own request is within its cutoff (410 `request_not_retained` past it), and another re-run
 under the key is 409 `idempotency_conflict`. The audit entry names the request re-run (`rerun_of`). A draft simulation's
-run, or any run of its tree, is never re-run: 409 `draft_run`.
+run, or any run of its tree, is never re-run: 409 `draft_run`. `{"expected_version_id": ...}` is checked as a start's
+(409 `version_changed`). A re-run that rebuilds a CSV start's rows keeps that start's record: its details show the same
+mapping, headers and rows, and its audit entry counts them.
 
 ## The worker
 
```

- [ ] **Step 4: The backend's checks**

Run:

```bash
cd backend \
  && uv run ruff check src tests migrations \
  && uv run ruff format --check src tests migrations \
  && uv run mypy src \
  && uv run lint-imports
```

Expected: silent; "Contracts: 11 kept, 0 broken."

Run:

```bash
cd backend && UV_FROZEN=1 UV_NO_SYNC=1 uv run pytest -q -n 6 \
  tests/apps/api \
  tests/apps/test_admission.py \
  tests/apps/test_admission_csv.py \
  tests/apps/test_admission_gate.py \
  tests/apps/test_admission_origins.py \
  tests/apps/test_csv_input.py \
  tests/core/requests \
  tests/apps/dispatcher/test_csv_rows_cost.py
```

Expected: PASS, 739 passed (about 2.5 minutes).

- [ ] **Step 5: CodeQL**

Run CI's python analysis locally (CLI 2.27.2, python-queries 1.8.12, CI's query filter) over the tree.

Expected: no finding.

- [ ] **Step 6: The whole backend suite**

Ask the owner before running it: it takes long locally. CI runs it on the PR. Run it on their word, as CI does (the
CEL gates in a process of their own, the rest with `-n auto`), and record every failure by name.

- [ ] **Step 7: Commit, and the final checkpoint**

```bash
git add frontend/src/api/openapi.json frontend/src/api/schema.d.ts docs/operations/runs.md
git commit -m "docs(runs): starting on a version, checking a file again; the client regenerated (4e-2a)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

Append `### 4e-2a, milestone 3 and the final checkpoint (<date>)` to the ledger. Record Task 7's checks as they ran,
the mid-slice rulings and "Nothing pushed". Commit it as `docs(editor-4): 4e-2a final checkpoint`, with the trailer.
The final whole-branch review follows. Nothing is pushed without the owner's word.
