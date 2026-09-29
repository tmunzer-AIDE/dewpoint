# Engine 2b-1a: Codec, Workflow Ids and Payload Sizes — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Before any production run, keep run data out of Temporal in plain text and keep every payload within
Temporal's limits. Record what the deployment is and keep its production gate off. Build every workflow id from its
tenant and run, and check it wherever a payload is used. Encrypt every Temporal payload with its tenant's data key,
and make each worker instance prove it can. Measure what a run sends and returns, so that a payload too large fails
its step, its loop or its run with a fixed error, never a retried workflow task or a run Temporal terminates.
`ENGINE_ABI` becomes 5.

**Architecture:**
- **The environment and the gate.** A single `platform_settings` row, recorded once by `dewpoint platform
  init-environment` in Compose's migrate step. Every process that talks to Temporal checks its namespace against it.
  `admit` refuses runs in a `production` deployment while `production_runs` is off.
- **Workflow ids.** `engine.runtime.ids` builds `t:<tenant>:run:<run>` for every run and reads it back with a strict
  grammar. `RunGraph`, `LoopBatch` and the worker's activities refuse an input whose tenant or run the id doesn't
  name.
- **The codec.** `apps.codec.TenantCodec` takes the tenant only from the serialization context, and reads keys
  through `KeyringKeys`, a bounded cache over the keyring's read-only `read_dek`. `data_converter()` is used by the
  worker, the CLI, every test server, the recorder and the replayers; goldens are recorded encrypted with fixture
  keys. A tenant gets its key when it's created, and `dewpoint keys ensure-tenants` gives one to older tenants.
- **Worker health.** `worker_instances` and `apps.worker.health` record each instance's build and capabilities. At
  startup and every 30 s, a self-check proves the KEK and the role's access to data keys, and tells a missing grant
  from an outage.
- **Sizes.** `engine.runtime.size` measures a payload as the SDK's JSON plus `CODEC_OVERHEAD`, and each payload is
  checked where it's produced:
  - results in the activities, and in the run and the batch that return them;
  - commands in the execution before they're sent, with `Scheduler.cut_batch` cutting a loop's batch by bytes;
  - `start_run` before admission.

  `Execution._send` extends #15's per-task byte budget to every payload a workflow task sends. The sensitive values a
  run carries are bounded (`SECRETS_BYTES`), so every result without outputs fits, and every final result is checked
  before it's recorded.

**Tech Stack:** Python 3.12, Temporal Python SDK 1.33.0 and CLI dev server 1.9.1 (server 1.32.0,
`WorkflowEnvironment.start_local`, approved), PostgreSQL 16 through testcontainers (`postgres:16-alpine`), SQLAlchemy
async with asyncpg, Alembic, `cryptography` (AES-256-GCM), pytest, ruff, mypy strict, import-linter; `uv`.

**Spec:** `docs/superpowers/specs/2026-09-29-engine-2b-design.md`, revision 4, on branch `docs/engine-2b-spec`, which
this plan's branch is cut from. Sections: §1 (scope of 2b-1a), §2.1–2.3 and §2.7 (environment, gate, worker health),
§4.6 (visible metadata), §5.2 and §5.3's 2b-1a promise (sizes), §6.1–6.3 and §6.6 (ids, codec, keys, ABI 5), §9
(codes), §11.1 (committed checks), §12 (testing), §15 (provisional values). Also engine-core
(`2026-09-25-engine-core-design.md`) §5.6–5.7, §7 and §9, which Task 12 brings to revision 5.7.

## Global Constraints

**Workflow**
- Implementation goes on one branch, `feat/engine-2b1a`, cut from `main` once this plan and spec revision 4 have
  landed. Nothing is pushed until the owner says so; the owner merges.
- Execution is inline, from the prototype's tested commits, with the owner's checkpoints after Task 6 and after Task
  12 (see "Executing this plan").
- Test first: every test fails before its implementation, for the stated reason. Task 7's tests describe Temporal
  itself, so each carries a control case in place of a red step.
- Commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Scratch files go in the session
  scratchpad, never `/tmp`.
- Docker: `postgres:16-alpine` and ryuk (testcontainers). The dev server comes from the SDK
  (`WorkflowEnvironment.start_local`). No other image.

**ABI and golden histories**
- `ENGINE_ABI` becomes 5 in Task 3, the first task that changes a run's commands. The abi4 histories stay as recorded.
- Task 3 records the abi5 histories in plain text; Task 6 deletes and re-records them encrypted. The replay gate
  compares with the merge base with `main`, so in-branch re-records are additions. Never touch another ABI's
  directory.

**Payloads and codes**
- The limits:
  - `PAYLOAD_BYTES = 1_835_008` (1.75 MiB), encoded;
  - `SNAPSHOT_BYTES = 1_572_864` (1.5 MiB), a continued run's encoded input;
  - `CODEC_OVERHEAD = 256`;
  - `YIELD_SEND_BYTES` stays `3 * 1024 * 1024`, and now counts every payload;
  - `CEL_REQUEST_BYTES` stays `1_835_008` of JSON;
  - `SECRETS_BYTES = 262_144` (256 KiB): the JSON of the sensitive values a run carries.
- New codes: `payload_too_large` and `snapshot_too_large` (spec §9). Every message is fixed and never quotes a value.
- No spilling: that's 2b-1b's. A payload that can't be split fails its step, loop or run, and is never sent. A batch
  item that can't fit fails its loop after the items before it.

**Security**
- Fail closed: no context, no tenant, or no key means refuse. There's never a default key, and plain text is never
  accepted. A workflow id supplied from outside is never parsed.
- Workflow ids: `t:<tenant>:run:<run>` for every run; `t:<tenant>:run:<run>/<step>/<iteration>/batch:<start>` for a
  batch.
- The key cache holds 1,024 keys for 300 s. A key version is never retired before the payload floor of spec §6.4
  (nothing in 2b-1a retires one).
- The health check runs every 30 s. A failed one makes the worker exit with code 3; an unanswered one (an outage)
  changes nothing.
- Roles: the dispatch role gains `SELECT` on `data_keys` (Task 5). The worker role gains the `worker_instances`
  table (Task 8).

**Tooling**
- Test order: list `tests/apps/...` files outside `worker/` first, then `tests/apps/worker/...`, then `tests/core/...`,
  then `tests/engine/...`, in one command. Never interleave worker and other apps files (#15's quirk).
- Workflow code imports names from a module's full path, `from dewpoint.engine.runtime.size import fits`. The
  sandbox copies a submodule taken from its package (`from dewpoint.engine.runtime import size`), so a limit a test
  lowers would never reach the workflow.
- Lint with `uv run ruff check --no-cache src tests migrations` and `uv run ruff format --no-cache --check src tests
  migrations`. Ruff's cache can hide the import order of a test written before its module exists.

**Checks after each task**
- The whole suite: `cd backend && uv run pytest -q -p no:cacheprovider`. Expected: all pass, 8 skipped (the Linux-only
  evaluator tests).
- Types and layers: `uv run mypy src` (no issues) and `uv run lint-imports` (10 contracts kept).

## Review Focus

1. **Sensitive values accumulating across valid steps** — each step's value fits, but together they'd pass the bound.
   The step that would pass it must fail (`payload_too_large`); what's carried must never be dropped; and every final
   result, a failure's included, must fit. Task 12 pins it:
   - `test_a_sensitive_value_past_the_bound_fails_the_step_that_would_add_it`;
   - `test_a_sub_flow_whose_sensitive_values_dont_fit_with_its_parents_fails_its_step`;
   - `test_a_trigger_whose_sensitive_values_dont_fit_fails_the_run_before_any_step`;
   - `test_every_final_result_fits_whatever_it_carries`;
   - `test_a_result_past_the_limit_anyway_ends_the_run_as_a_bug`.
2. **A tenant that has no data key** — one created before this build, or by an old API process after the migrate step
   ran `ensure-tenants`. Its runs must be refused at the start (`start_failed`, "couldn't be encrypted"), never left
   `running`, and `dewpoint keys ensure-tenants` fixes it. Task 6 pins it:
   `test_a_start_that_cant_be_encrypted_is_refused_and_its_run_failed`.
3. **A database outage during a worker's health check, against a missing grant.** An outage must leave the worker
   running, with its record going stale; a role that can't read data keys must stop it. Task 8 pins both:
   `test_an_outage_proves_nothing_and_keeps_the_instance_polling` and
   `test_the_check_proves_the_kek_and_the_roles_access_to_data_keys`.
4. **A large trigger, or a loop body reading large outside values.** Every batch carries the trigger and what its body
   reads. The cut must count them; an item that can't fit with them fails its loop, after the items before it, and
   none is dropped. Task 10 pins both: `test_a_batch_is_cut_by_bytes_and_keeps_every_item_in_order` and
   `test_an_item_too_large_for_a_batch_fails_its_loop_after_the_items_before_it`.
5. **A key rotation while runs are open.** Payloads encrypted with the old version still decrypt, and new ones use the
   new version within the cache's 300 s. Task 4 pins it: `test_after_a_rotation_older_payloads_still_decode` and
   `test_a_key_is_read_once_until_its_time_is_up`.

---

## File structure

**Environment and gate (Tasks 1–2)**
- `backend/migrations/versions/0010_platform_settings.py`
- `backend/src/dewpoint/core/models/platform.py`
- `backend/src/dewpoint/core/platform/service.py`
- `backend/src/dewpoint/apps/environment.py`
- `backend/src/dewpoint/core/config.py` (`environment`)
- `backend/src/dewpoint/apps/cli/main.py` (`platform init-environment`, and the check before Temporal)
- `backend/src/dewpoint/apps/worker/main.py`
- `backend/src/dewpoint/apps/runs.py` (the gate in `admit`)
- `deploy/compose/docker-compose.yml`

**Ids (Task 3)**
- `backend/src/dewpoint/engine/runtime/ids.py`
- `engine/runtime/execution.py` and `workflow.py` (child ids, cross-checks)
- `apps/worker/activities.py` (`_same_tenant`)
- `apps/runs.py`, `apps/cli/main.py` (roots' ids)
- `engine/__init__.py` (`ENGINE_ABI = 5`)
- `backend/tests/apps/worker/harness.py` (`run_id_of`)
- the recorder, and the abi5 goldens

**Codec and keys (Tasks 4–6)**
- `backend/src/dewpoint/apps/codec.py`
- `core/crypto/keyring.py` (`ensure_key`, `read_dek`, `NoKeyError`)
- `core/tenancy/service.py` (a key at creation; `ensure_tenant_keys`)
- `apps/api/routes/tenants.py`
- `backend/migrations/versions/0011_dispatch_reads_keys.py`
- `apps/cli/main.py` (`keys ensure-tenants`; `_temporal` becomes a context manager with the codec)
- `apps/worker/main.py`
- `apps/runs.py` (a start that can't be encrypted is refused)
- `backend/tests/support/keys.py` (`FixtureKeys`, `FIXTURE_CONVERTER`, `opened`)
- the test servers, the recorder and the replayers

**Temporal's contract (Task 7)**
- `backend/tests/apps/worker/test_temporal_contract.py`

**Worker health (Task 8)**
- `backend/migrations/versions/0012_worker_instances.py`
- `core/models/platform.py` (`WorkerInstance`)
- `core/platform/service.py` (`record_worker`)
- `core/crypto/keyring.py` (`self_check`)
- `apps/worker/health.py`
- `apps/worker/main.py`
- `apps/cli/main.py` (exit 3)

**Sizes (Tasks 9–12)**
- `backend/src/dewpoint/engine/runtime/size.py`
- `apps/worker/activities.py`
- `engine/runtime/workflow.py` and `execution.py`
- `engine/runtime/scheduler.py` (`cut_batch`)
- `engine/runtime/resolve.py` (docstring)
- `engine/cel/route.py` (comments)
- `apps/runs.py` (the check before admission)
- `backend/tests/support/plugins/testkit.py` (`testkit.blob@1`, `testkit.secret_blob@1`)
- `backend/tests/apps/worker/test_run_graph_sizes.py`

**Docs (Task 13)**
- `docs/operations/deployment.md`, `runs.md`, `key-rotation.md`
- engine-core revision 5.7; the architecture spec's §6.1 id

---

## How the steps give code

Each task's code is given as unified diffs against the tree the previous task left. The diffs are a prototype's
commits, and each was replayed onto that tree as its step says: its tests failed as stated, then passed with the
change. New files appear whole, as `new file mode` diffs.

The prototype is the local branch `proto/2b1a-v4`, cut from `main` at `e46297d`, with one commit per task:
Task 1 `1c18678`, Task 2 `e5715e5`, Task 3 `9d21df0`, Task 4 `9822195`, Task 5 `763b1bf`, Task 6 `8c75a8c`, Task 7 `553455a`, Task 8 `ffb339e`, Task 9 `8d17c51`, Task 10 `2b6839f`, Task 11 `4ff80f5`, Task 12 `053ff39`, Task 13 `d82f574`.

Each commit was verified this way:
- its tree was reproduced exactly by the replay;
- it passed the whole suite, ruff (without its cache), mypy and import-linter.

The golden histories are recorded, not diffed, and they come with Tasks 3 and 6's commits.

## Executing this plan

Inline, in one session, from the prototype's commits: the diffs aren't typed again. For each task, in order, on
`feat/engine-2b1a`:
1. Read the task. Its RED step was run by the replay, and its output is quoted: it isn't repeated.
2. Run `git cherry-pick --no-commit <the task's commit>`. The commit list is above.
3. Run the task's verification steps, every step after its code, and compare each output with its `Expected:` line.
   A golden recording step is already done: its files come with the commit.
4. Commit with the task's own message.

**Checkpoints:** stop for the owner's review after Task 6 (codec and key wiring), and after Task 12 (the size
guards). After Task 13, a fresh reviewer reviews the whole branch.

A mismatch is a finding: stop and report it, and don't patch around it. The diffs below remain the plan's record of
every change.

### Task 1: The deployment's environment, recorded once, and the namespace check

**Spec:** §2.1.

**Files:**
- Create: `backend/migrations/versions/0010_platform_settings.py`
- Create: `backend/src/dewpoint/apps/environment.py`
- Create: `backend/src/dewpoint/core/models/platform.py`
- Create: `backend/src/dewpoint/core/platform/__init__.py`
- Create: `backend/src/dewpoint/core/platform/service.py`
- Create: `backend/tests/apps/cli/test_platform_cli.py`
- Create: `backend/tests/apps/test_environment.py`
- Create: `backend/tests/core/platform/__init__.py`
- Create: `backend/tests/core/platform/test_service.py`
- Modify: `backend/src/dewpoint/apps/cli/main.py`
- Modify: `backend/src/dewpoint/apps/worker/main.py`
- Modify: `backend/src/dewpoint/core/config.py`
- Modify: `backend/tests/apps/cli/test_dev_run_cli.py`
- Modify: `backend/tests/apps/worker/test_deployment.py`
- Modify: `deploy/compose/docker-compose.yml`

**Interfaces:**
- Produces:
  - `dewpoint.core.platform.service`: `PRODUCTION`, `DEVELOPMENT`, `ENVIRONMENTS`, `NOT_RECORDED` (str),
    `EnvironmentNotRecordedError`, `EnvironmentMismatchError`;
  - `async recorded(s) -> PlatformSettings | None`;
  - `async record_environment(s, *, environment: str, namespace: str) -> PlatformSettings` (idempotent; different
    values raise `EnvironmentMismatchError`);
  - `async check_namespace(s, configured: str) -> PlatformSettings`.
  - `dewpoint.apps.environment.verify_environment(sessionmaker, settings) -> PlatformSettings`;
    `Settings.environment` (`DEWPOINT_ENVIRONMENT`, default `production`); model `PlatformSettings`; migration
    `0010`; CLI group `platform`.
- Consumes: nothing new.

A single `platform_settings` row says what the deployment is: `production` or `development`, with the
Temporal namespace it uses. `dewpoint platform init-environment` records it once, and Compose's migrate step runs it.
A trigger refuses any change to either value and refuses deleting the row. Every process that talks to Temporal (the
worker, and the CLI's Temporal commands) checks its configured namespace against the record before it connects, and
exits 2 when there's no record or it doesn't match.

- [ ] **Step 1: Write the tests**

````diff
diff --git a/backend/tests/apps/cli/test_dev_run_cli.py b/backend/tests/apps/cli/test_dev_run_cli.py
index 86f3e8b..0c14311 100644
--- a/backend/tests/apps/cli/test_dev_run_cli.py
+++ b/backend/tests/apps/cli/test_dev_run_cli.py
@@ -32,9 +32,14 @@ def cli_env(monkeypatch: pytest.MonkeyPatch) -> None:
     monkeypatch.setenv("DEWPOINT_KEK_B64", base64.b64encode(b"k" * 32).decode())
     monkeypatch.setenv("DEWPOINT_PUBLIC_ORIGIN", "https://dewpoint.test")
     monkeypatch.setattr(cli, "Client", _Client)
+    monkeypatch.setattr(cli, "verify_environment", _recorded)  # the check itself: tests/apps/test_environment.py
     get_settings.cache_clear()
 
 
+async def _recorded(*args: Any) -> None:
+    """A deployment whose record matches: the CLI's Temporal commands check it before connecting (2b spec §2.1)."""
+
+
 def _answer(monkeypatch: pytest.MonkeyPatch, outcome: RunResult | Exception, seen: dict[str, Any]) -> None:
     async def dev_run_version(settings: Any, client: Any, **kwargs: Any) -> tuple[uuid.UUID, RunResult | None]:
         seen.update(kwargs)
diff --git a/backend/tests/apps/cli/test_platform_cli.py b/backend/tests/apps/cli/test_platform_cli.py
new file mode 100644
index 0000000..6b504bf
--- /dev/null
+++ b/backend/tests/apps/cli/test_platform_cli.py
@@ -0,0 +1,44 @@
+# SPDX-License-Identifier: Apache-2.0
+"""`dewpoint platform init-environment` records what this deployment is, once (engine 2b spec §2.1). Compose's migrate
+step runs it; running it again with the same values changes nothing."""
+
+import base64
+
+import pytest
+from typer.testing import CliRunner
+
+from dewpoint.apps.cli import main as cli
+from dewpoint.core.config import get_settings
+
+
+@pytest.fixture
+def owner_env(monkeypatch: pytest.MonkeyPatch, pg_url: str) -> None:
+    monkeypatch.setenv("DEWPOINT_DATABASE_URL", pg_url)
+    monkeypatch.setenv("DEWPOINT_KEK_B64", base64.b64encode(b"k" * 32).decode())
+    monkeypatch.setenv("DEWPOINT_PUBLIC_ORIGIN", "https://dewpoint.test")
+    monkeypatch.delenv("DEWPOINT_ENVIRONMENT", raising=False)
+    monkeypatch.delenv("DEWPOINT_TEMPORAL_NAMESPACE", raising=False)
+    get_settings.cache_clear()
+
+
+@pytest.mark.usefixtures("owner_env")
+def test_a_deployment_is_production_unless_told_otherwise_and_records_it_once() -> None:
+    first = CliRunner().invoke(cli.app, ["platform", "init-environment"])
+    again = CliRunner().invoke(cli.app, ["platform", "init-environment", "--environment", "production"])
+    assert first.exit_code == 0
+    assert first.output == "this deployment is production, with the Temporal namespace `default`\n"
+    assert again.exit_code == 0
+    other = CliRunner().invoke(cli.app, ["platform", "init-environment", "--environment", "development"])
+    assert other.exit_code == 2
+    assert "recorded as production" in other.output
+
+
+@pytest.mark.usefixtures("owner_env")
+def test_a_development_setup_says_so_with_its_own_namespace(monkeypatch: pytest.MonkeyPatch) -> None:
+    monkeypatch.setenv("DEWPOINT_ENVIRONMENT", "development")
+    get_settings.cache_clear()
+    result = CliRunner().invoke(cli.app, ["platform", "init-environment", "--temporal-namespace", "dewpoint-ci"])
+    assert (result.exit_code, result.output) == (
+        0,
+        "this deployment is development, with the Temporal namespace `dewpoint-ci`\n",
+    )
diff --git a/backend/tests/apps/test_environment.py b/backend/tests/apps/test_environment.py
new file mode 100644
index 0000000..4743c1b
--- /dev/null
+++ b/backend/tests/apps/test_environment.py
@@ -0,0 +1,58 @@
+# SPDX-License-Identifier: Apache-2.0
+"""A process that talks to Temporal refuses to start unless its namespace is the one this deployment recorded (engine
+2b spec §2.1): the worker, and the CLI's Temporal commands."""
+
+import base64
+
+import pytest
+from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
+from typer.testing import CliRunner
+
+from dewpoint.apps.cli import main as cli
+from dewpoint.apps.worker.main import run
+from dewpoint.core.config import Settings, get_settings
+from dewpoint.core.platform.service import (
+    DEVELOPMENT,
+    EnvironmentMismatchError,
+    EnvironmentNotRecordedError,
+    record_environment,
+)
+from tests.conftest import _url_for
+
+
+def worker_settings(pg_url: str, namespace: str = "default") -> Settings:
+    return Settings(
+        database_url=_url_for(pg_url, "dewpoint_worker"),
+        kek_b64=base64.b64encode(b"k" * 32).decode(),
+        public_origin="https://dewpoint.test",
+        temporal_address="127.0.0.1:1",  # never reached: the check comes first
+        temporal_namespace=namespace,
+    )
+
+
+@pytest.mark.usefixtures("_test_users")
+async def test_a_worker_wont_start_before_the_environment_is_recorded(pg_url: str) -> None:
+    with pytest.raises(EnvironmentNotRecordedError):
+        await run(worker_settings(pg_url))
+
+
+@pytest.mark.usefixtures("_test_users")
+async def test_a_worker_wont_serve_another_namespace(
+    pg_url: str, owner_sessionmaker: async_sessionmaker[AsyncSession]
+) -> None:
+    async with owner_sessionmaker() as s, s.begin():
+        await record_environment(s, environment=DEVELOPMENT, namespace="dewpoint-dev")
+    with pytest.raises(EnvironmentMismatchError, match="configured for `default`"):
+        await run(worker_settings(pg_url))
+
+
+def test_the_clis_temporal_commands_wont_connect_before_the_record(
+    monkeypatch: pytest.MonkeyPatch, pg_url: str, _test_users: None
+) -> None:
+    monkeypatch.setenv("DEWPOINT_DATABASE_URL", _url_for(pg_url, "dewpoint_dispatch"))
+    monkeypatch.setenv("DEWPOINT_KEK_B64", base64.b64encode(b"k" * 32).decode())
+    monkeypatch.setenv("DEWPOINT_PUBLIC_ORIGIN", "https://dewpoint.test")
+    get_settings.cache_clear()
+    result = CliRunner().invoke(cli.app, ["deployment", "status"])
+    assert result.exit_code == 2
+    assert "isn't recorded" in result.output
diff --git a/backend/tests/apps/worker/test_deployment.py b/backend/tests/apps/worker/test_deployment.py
index 126b697..5cc159f 100644
--- a/backend/tests/apps/worker/test_deployment.py
+++ b/backend/tests/apps/worker/test_deployment.py
@@ -132,6 +132,10 @@ async def test_a_run_stays_on_the_build_it_started_on_with_its_children_and_cont
             assert ran.behaviours == {VersioningBehavior.VERSIONING_BEHAVIOR_PINNED}
 
 
+async def recorded(*args: object) -> None:
+    """A deployment whose record matches the worker's namespace (engine 2b spec §2.1)."""
+
+
 async def test_a_worker_set_to_makes_its_build_current_once_it_polls(
     dev_env: WorkflowEnvironment, monkeypatch: pytest.MonkeyPatch
 ) -> None:
@@ -147,6 +151,7 @@ async def test_a_worker_set_to_makes_its_build_current_once_it_polls(
     monkeypatch.setattr(main.Client, "connect", connect)
     monkeypatch.setattr(main, "make_engine", lambda url: Engine())
     monkeypatch.setattr(main, "make_sessionmaker", lambda engine: None)
+    monkeypatch.setattr(main, "verify_environment", recorded)  # the check itself: tests/apps/test_environment.py
     monkeypatch.setattr(main, "installed_plugins", lambda: [TESTKIT])
     worker = asyncio.create_task(main.run(settings(worker_set_current=True, worker_shutdown_grace_s=0.1)))
     try:
diff --git a/backend/tests/core/platform/__init__.py b/backend/tests/core/platform/__init__.py
new file mode 100644
index 0000000..e69de29
diff --git a/backend/tests/core/platform/test_service.py b/backend/tests/core/platform/test_service.py
new file mode 100644
index 0000000..c83845a
--- /dev/null
+++ b/backend/tests/core/platform/test_service.py
@@ -0,0 +1,103 @@
+# SPDX-License-Identifier: Apache-2.0
+"""What a deployment is, recorded once (engine 2b spec §2.1): its environment and its Temporal namespace never change,
+and a process configured for another namespace doesn't start."""
+
+import pytest
+from sqlalchemy import text
+from sqlalchemy.exc import DBAPIError
+from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
+
+from dewpoint.core.platform.service import (
+    DEVELOPMENT,
+    PRODUCTION,
+    EnvironmentMismatchError,
+    EnvironmentNotRecordedError,
+    check_namespace,
+    record_environment,
+    recorded,
+)
+
+
+async def test_an_environment_is_recorded_once_and_the_same_values_again_change_nothing(
+    owner_sessionmaker: async_sessionmaker[AsyncSession],
+) -> None:
+    async with owner_sessionmaker() as s, s.begin():
+        assert await recorded(s) is None
+        row = await record_environment(s, environment=DEVELOPMENT, namespace="dewpoint-dev")
+        assert (row.environment, row.temporal_namespace, row.production_runs) == (DEVELOPMENT, "dewpoint-dev", False)
+    async with owner_sessionmaker() as s, s.begin():
+        again = await record_environment(s, environment=DEVELOPMENT, namespace="dewpoint-dev")
+        assert (again.environment, again.temporal_namespace) == (DEVELOPMENT, "dewpoint-dev")
+
+
+@pytest.mark.parametrize("values", [(PRODUCTION, "dewpoint-dev"), (DEVELOPMENT, "other")])
+async def test_a_recorded_environment_never_changes(
+    owner_sessionmaker: async_sessionmaker[AsyncSession], values: tuple[str, str]
+) -> None:
+    async with owner_sessionmaker() as s, s.begin():
+        await record_environment(s, environment=DEVELOPMENT, namespace="dewpoint-dev")
+    with pytest.raises(EnvironmentMismatchError, match="Neither can change"):
+        async with owner_sessionmaker() as s, s.begin():
+            await record_environment(s, environment=values[0], namespace=values[1])
+
+
+@pytest.mark.parametrize(
+    "statement",
+    [
+        "UPDATE platform_settings SET environment = 'production'",
+        "UPDATE platform_settings SET temporal_namespace = 'other'",
+        "DELETE FROM platform_settings",
+    ],
+)
+async def test_the_database_refuses_to_change_or_remove_the_record(
+    owner_sessionmaker: async_sessionmaker[AsyncSession], statement: str
+) -> None:
+    """Even the table's owner, bypassing the service: a trigger enforces it. The gate is the one column that changes."""
+    async with owner_sessionmaker() as s, s.begin():
+        await record_environment(s, environment=DEVELOPMENT, namespace="dewpoint-dev")
+    with pytest.raises(DBAPIError, match="recorded once|never removed"):
+        async with owner_sessionmaker() as s, s.begin():
+            await s.execute(text(statement))
+    async with owner_sessionmaker() as s, s.begin():
+        await s.execute(text("UPDATE platform_settings SET production_runs = true"))
+
+
+async def test_an_unknown_environment_or_an_empty_namespace_is_refused(
+    owner_sessionmaker: async_sessionmaker[AsyncSession],
+) -> None:
+    async with owner_sessionmaker() as s, s.begin():
+        with pytest.raises(ValueError, match="production` or `development"):
+            await record_environment(s, environment="staging", namespace="n")
+        with pytest.raises(ValueError, match="can't be empty"):
+            await record_environment(s, environment=PRODUCTION, namespace="")
+
+
+async def test_a_process_starts_only_with_the_recorded_namespace(
+    owner_sessionmaker: async_sessionmaker[AsyncSession], worker_sessionmaker: async_sessionmaker[AsyncSession]
+) -> None:
+    async with worker_sessionmaker() as s:
+        with pytest.raises(EnvironmentNotRecordedError, match="platform init-environment"):
+            await check_namespace(s, "default")
+    async with owner_sessionmaker() as s, s.begin():
+        await record_environment(s, environment=PRODUCTION, namespace="default")
+    async with worker_sessionmaker() as s:
+        assert (await check_namespace(s, "default")).environment == PRODUCTION
+        with pytest.raises(EnvironmentMismatchError, match="configured for `other`"):
+            await check_namespace(s, "other")
+
+
+async def test_the_application_roles_read_the_record_and_never_write_it(
+    owner_sessionmaker: async_sessionmaker[AsyncSession],
+    api_sessionmaker: async_sessionmaker[AsyncSession],
+    dispatch_sessionmaker: async_sessionmaker[AsyncSession],
+    worker_sessionmaker: async_sessionmaker[AsyncSession],
+    admin_sessionmaker: async_sessionmaker[AsyncSession],
+) -> None:
+    async with owner_sessionmaker() as s, s.begin():
+        await record_environment(s, environment=PRODUCTION, namespace="default")
+    for sessionmaker in (api_sessionmaker, dispatch_sessionmaker, worker_sessionmaker, admin_sessionmaker):
+        async with sessionmaker() as s:
+            assert (await recorded(s)) is not None
+        with pytest.raises(DBAPIError, match="permission denied"):
+            async with sessionmaker() as s, s.begin():
+                await s.execute(text("UPDATE platform_settings SET production_runs = true"))
````

- [ ] **Step 2: Run them, and watch them fail**

Run: `cd backend && uv run pytest -q -p no:cacheprovider tests/apps/cli/test_dev_run_cli.py tests/apps/cli/test_platform_cli.py tests/apps/test_environment.py tests/apps/worker/test_deployment.py tests/core/platform/test_service.py`

Expected: FAIL. The new modules don't exist yet. The replay showed:

````text
E   ModuleNotFoundError: No module named 'dewpoint.core.platform.service'
ERROR tests/apps/test_environment.py
ERROR tests/core/platform/test_service.py
!!!!!!!!!!!!!!!!!!! Interrupted: 2 errors during collection !!!!!!!!!!!!!!!!!!!!
2 errors in 0.33s
````

- [ ] **Step 3: Implement**

````diff
diff --git a/backend/migrations/versions/0010_platform_settings.py b/backend/migrations/versions/0010_platform_settings.py
new file mode 100644
index 0000000..9870d61
--- /dev/null
+++ b/backend/migrations/versions/0010_platform_settings.py
@@ -0,0 +1,50 @@
+# SPDX-License-Identifier: Apache-2.0
+"""the deployment's environment, its Temporal namespace and its production gate (engine 2b spec §2, plan 2b-1a)"""
+
+import sqlalchemy as sa
+from alembic import op
+
+revision = "0010"
+down_revision = "0009"
+branch_labels = None
+depends_on = None
+
+
+def upgrade() -> None:
+    op.create_table(
+        "platform_settings",
+        sa.Column("id", sa.SmallInteger, primary_key=True, server_default="1"),
+        sa.Column("environment", sa.String(16), nullable=False),
+        sa.Column("temporal_namespace", sa.Text, nullable=False),
+        sa.Column("production_runs", sa.Boolean, nullable=False, server_default=sa.false()),
+        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
+        sa.CheckConstraint("id = 1", name="platform_settings_one_row"),
+        sa.CheckConstraint("environment IN ('production', 'development')", name="platform_settings_environment"),
+        sa.CheckConstraint("temporal_namespace <> ''", name="platform_settings_namespace"),
+    )
+    # Recorded once: the environment and the namespace never change, and the row is never removed. The gate
+    # (production_runs) is the one column that may change, and only through the audited command (2b-4).
+    op.execute(
+        """
+        CREATE FUNCTION platform_settings_recorded_once() RETURNS trigger LANGUAGE plpgsql AS $$
+        BEGIN
+            IF TG_OP = 'DELETE' THEN
+                RAISE EXCEPTION 'the platform settings are never removed';
+            END IF;
+            IF NEW.environment <> OLD.environment OR NEW.temporal_namespace <> OLD.temporal_namespace THEN
+                RAISE EXCEPTION 'the environment and the Temporal namespace are recorded once';
+            END IF;
+            RETURN NEW;
+        END $$
+        """
+    )
+    op.execute(
+        "CREATE TRIGGER platform_settings_recorded_once BEFORE UPDATE OR DELETE ON platform_settings "
+        "FOR EACH ROW EXECUTE FUNCTION platform_settings_recorded_once()"
+    )
+    op.execute("GRANT SELECT ON platform_settings TO dewpoint_api, dewpoint_dispatch, dewpoint_worker, dewpoint_admin")
+
+
+def downgrade() -> None:
+    op.execute("DROP TABLE platform_settings")
+    op.execute("DROP FUNCTION platform_settings_recorded_once()")
diff --git a/backend/src/dewpoint/apps/cli/main.py b/backend/src/dewpoint/apps/cli/main.py
index b69fbe3..dfd1cc0 100644
--- a/backend/src/dewpoint/apps/cli/main.py
+++ b/backend/src/dewpoint/apps/cli/main.py
@@ -15,6 +15,7 @@ from sqlalchemy import select
 from sqlalchemy.ext.asyncio import AsyncSession
 from temporalio.client import Client
 
+from dewpoint.apps.environment import verify_environment
 from dewpoint.apps.plugin_loader import PluginLoadError, installed_plugins, prepare
 from dewpoint.apps.runs import NotAdmissibleError, StartRefusedError, StartUncertainError, start_run
 from dewpoint.apps.worker.deployment import Deployment, describe, set_current, this_build
@@ -26,6 +27,7 @@ from dewpoint.core.crypto.kek import KekSet, UnknownKekError
 from dewpoint.core.crypto.keyring import Keyring
 from dewpoint.core.db import make_engine, make_sessionmaker
 from dewpoint.core.models.identity import User
+from dewpoint.core.platform.service import EnvironmentMismatchError, EnvironmentNotRecordedError, record_environment
 from dewpoint.core.plugins import lifecycle
 from dewpoint.core.plugins.lifecycle import Entry
 from dewpoint.core.plugins.registry import (
@@ -55,6 +57,8 @@ dev_cli = typer.Typer(no_args_is_help=True)
 app.add_typer(dev_cli, name="dev")
 deployment_cli = typer.Typer(no_args_is_help=True)
 app.add_typer(deployment_cli, name="deployment")
+platform_cli = typer.Typer(no_args_is_help=True)
+app.add_typer(platform_cli, name="platform")
 
 
 async def _init(email: str, password: str) -> None:
@@ -327,14 +331,59 @@ def lifecycle_retire(
 @app.command("worker")
 def worker() -> None:
     """Run the Temporal worker: RunGraph and its activities, and cel.evaluate when DEWPOINT_CEL_SOCKET is set."""
-    asyncio.run(run_worker(get_settings()))
+    try:
+        asyncio.run(run_worker(get_settings()))
+    except (EnvironmentNotRecordedError, EnvironmentMismatchError) as e:
+        typer.echo(f"ERROR: {e}")
+        raise typer.Exit(2) from None
 
 
 async def _temporal() -> Client:
+    """A Temporal client, once this process's namespace is the one this deployment recorded (engine 2b spec §2.1)."""
     settings = get_settings()
+    engine = make_engine(settings.database_url)
+    try:
+        await verify_environment(make_sessionmaker(engine), settings)
+    except (EnvironmentNotRecordedError, EnvironmentMismatchError) as e:
+        typer.echo(f"ERROR: {e}")
+        raise typer.Exit(2) from None
+    finally:
+        await engine.dispose()
     return await Client.connect(settings.temporal_address, namespace=settings.temporal_namespace)
 
 
+@platform_cli.command("init-environment")
+def platform_init_environment(
+    environment: str | None = typer.Option(
+        None, "--environment", help="production or development (default: DEWPOINT_ENVIRONMENT, else production)"
+    ),
+    namespace: str | None = typer.Option(
+        None, "--temporal-namespace", help="the Temporal namespace (default: DEWPOINT_TEMPORAL_NAMESPACE)"
+    ),
+) -> None:
+    """Record, once, whether this deployment is production or development and which Temporal namespace it uses
+    (engine 2b spec §2.1). The same values again change nothing; other values are refused. A development setup needs
+    its own database and namespace: the label proves nothing about the data."""
+    settings = get_settings()
+    env = environment or settings.environment
+    ns = namespace or settings.temporal_namespace
+
+    async def _go() -> None:
+        engine = make_engine(settings.database_url)
+        try:
+            async with make_sessionmaker(engine)() as s, s.begin():
+                await record_environment(s, environment=env, namespace=ns)
+        finally:
+            await engine.dispose()
+
+    try:
+        asyncio.run(_go())
+    except (ValueError, EnvironmentMismatchError) as e:
+        typer.echo(f"ERROR: {e}")
+        raise typer.Exit(2) from None
+    typer.echo(f"this deployment is {env}, with the Temporal namespace `{ns}`")
+
+
 @deployment_cli.command("set-current")
 def deployment_set_current(
     build: str | None = typer.Option(None, "--build-id", help="the build new runs start on (default: this one)"),
@@ -407,7 +456,7 @@ def dev_run(
 
     async def _go() -> tuple[uuid.UUID, RunResult | None]:
         settings = get_settings()
-        client = await Client.connect(settings.temporal_address, namespace=settings.temporal_namespace)
+        client = await _temporal()
         return await dev_run_version(
             settings,
             client,
diff --git a/backend/src/dewpoint/apps/environment.py b/backend/src/dewpoint/apps/environment.py
new file mode 100644
index 0000000..aa12b67
--- /dev/null
+++ b/backend/src/dewpoint/apps/environment.py
@@ -0,0 +1,16 @@
+# SPDX-License-Identifier: Apache-2.0
+"""The check every process that talks to Temporal runs before it connects (engine 2b spec §2.1): its configured
+namespace must be the one this deployment recorded. The worker and the CLI's Temporal commands run it; the API never
+talks to Temporal."""
+
+from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
+
+from dewpoint.core.config import Settings
+from dewpoint.core.models.platform import PlatformSettings
+from dewpoint.core.platform.service import check_namespace
+
+
+async def verify_environment(sessionmaker: async_sessionmaker[AsyncSession], settings: Settings) -> PlatformSettings:
+    """The deployment's record. Raises EnvironmentNotRecordedError or EnvironmentMismatchError: don't connect."""
+    async with sessionmaker() as s:
+        return await check_namespace(s, settings.temporal_namespace)
diff --git a/backend/src/dewpoint/apps/worker/main.py b/backend/src/dewpoint/apps/worker/main.py
index e1b5a96..f5a3081 100644
--- a/backend/src/dewpoint/apps/worker/main.py
+++ b/backend/src/dewpoint/apps/worker/main.py
@@ -13,6 +13,7 @@ from temporalio.client import Client
 from temporalio.worker import Worker
 
 from dewpoint.apps import cel_client
+from dewpoint.apps.environment import verify_environment
 from dewpoint.apps.plugin_loader import installed_plugins
 from dewpoint.apps.worker.activities import RunStore, cel_activity, engine_activities, remote_evaluator
 from dewpoint.apps.worker.deployment import deployment_config, set_current, this_build
@@ -78,9 +79,12 @@ async def promote(client: Client) -> None:
 
 
 async def run(settings: Settings) -> None:
-    client = await Client.connect(settings.temporal_address, namespace=settings.temporal_namespace)
+    """Raises EnvironmentNotRecordedError or EnvironmentMismatchError before connecting to Temporal: a worker never
+    serves a namespace its database wasn't recorded with (engine 2b spec §2.1)."""
     engine = make_engine(settings.database_url)
     try:
+        await verify_environment(make_sessionmaker(engine), settings)
+        client = await Client.connect(settings.temporal_address, namespace=settings.temporal_namespace)
         workers = [engine_worker(client, DbRunStore(make_sessionmaker(engine)), installed_plugins(), settings)]
         if settings.cel_socket:
             profile = await evaluator_profile(settings.cel_socket)
diff --git a/backend/src/dewpoint/core/config.py b/backend/src/dewpoint/core/config.py
index 21331c5..3416c7c 100644
--- a/backend/src/dewpoint/core/config.py
+++ b/backend/src/dewpoint/core/config.py
@@ -29,6 +29,9 @@ class Settings(BaseSettings):
     max_run_duration_days: int = 30  # spec §6: whole logical run, including continue-as-new and waits
     temporal_address: str = "localhost:7233"
     temporal_namespace: str = "default"
+    # What `dewpoint platform init-environment` records, once (engine 2b spec §2.1): production unless a development
+    # setup says otherwise. Every process that talks to Temporal checks its namespace against the record.
+    environment: str = "production"
     cel_socket: str | None = None  # the cel-evaluator's socket; a worker without one serves no CEL queue
     cel_max_concurrent: int = 2  # the evaluator's N (docs/operations/cel-evaluator.md)
     cel_schedule_to_start_s: float = 600  # spec §5.7: no evaluator for a profile after this: cel_profile_unavailable
diff --git a/backend/src/dewpoint/core/models/platform.py b/backend/src/dewpoint/core/models/platform.py
new file mode 100644
index 0000000..c7bd21e
--- /dev/null
+++ b/backend/src/dewpoint/core/models/platform.py
@@ -0,0 +1,19 @@
+# SPDX-License-Identifier: Apache-2.0
+from datetime import datetime
+
+from sqlalchemy import Boolean, DateTime, SmallInteger, String, Text, func
+from sqlalchemy.orm import Mapped, mapped_column
+
+from dewpoint.core.models.base import Base
+
+
+class PlatformSettings(Base):
+    """The one row that says what this deployment is (engine 2b spec §2): production or development, recorded once
+    with the Temporal namespace it uses, and whether production runs are on (off until the gate lifts)."""
+
+    __tablename__ = "platform_settings"
+    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, default=1)
+    environment: Mapped[str] = mapped_column(String(16))
+    temporal_namespace: Mapped[str] = mapped_column(Text)
+    production_runs: Mapped[bool] = mapped_column(Boolean, default=False)
+    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
diff --git a/backend/src/dewpoint/core/platform/__init__.py b/backend/src/dewpoint/core/platform/__init__.py
new file mode 100644
index 0000000..9881313
--- /dev/null
+++ b/backend/src/dewpoint/core/platform/__init__.py
@@ -0,0 +1 @@
+# SPDX-License-Identifier: Apache-2.0
diff --git a/backend/src/dewpoint/core/platform/service.py b/backend/src/dewpoint/core/platform/service.py
new file mode 100644
index 0000000..f693b0f
--- /dev/null
+++ b/backend/src/dewpoint/core/platform/service.py
@@ -0,0 +1,65 @@
+# SPDX-License-Identifier: Apache-2.0
+"""What this deployment is (engine 2b spec §2.1): production or development, and the Temporal namespace it uses,
+recorded once. A process that talks to Temporal checks its configured namespace against the record before it starts,
+so a development database can't drive a namespace it wasn't set up for, and a production database can't either. The
+label proves nothing about the data: keeping development's database and namespace apart from production's is the
+operator's job."""
+
+from sqlalchemy.ext.asyncio import AsyncSession
+
+from dewpoint.core.models.platform import PlatformSettings
+
+PRODUCTION = "production"
+DEVELOPMENT = "development"
+ENVIRONMENTS = (PRODUCTION, DEVELOPMENT)
+NOT_RECORDED = (
+    "This deployment's environment isn't recorded: run `dewpoint platform init-environment` (Compose's migrate step "
+    "does) before starting anything that talks to Temporal."
+)
+
+
+class EnvironmentNotRecordedError(Exception):
+    def __init__(self) -> None:
+        super().__init__(NOT_RECORDED)
+
+
+class EnvironmentMismatchError(Exception):
+    pass
+
+
+async def recorded(s: AsyncSession) -> PlatformSettings | None:
+    return await s.get(PlatformSettings, 1)
+
+
+async def record_environment(s: AsyncSession, *, environment: str, namespace: str) -> PlatformSettings:
+    """Record it once. Recording the same values again changes nothing; other values are refused: a deployment never
+    changes environment or namespace (a trigger enforces it too)."""
+    if environment not in ENVIRONMENTS:
+        raise ValueError(f"The environment is `production` or `development`, not `{environment}`.")
+    if not namespace:
+        raise ValueError("The Temporal namespace can't be empty.")
+    existing = await recorded(s)
+    if existing is None:
+        row = PlatformSettings(id=1, environment=environment, temporal_namespace=namespace)
+        s.add(row)
+        await s.flush()
+        return row
+    if (existing.environment, existing.temporal_namespace) != (environment, namespace):
+        raise EnvironmentMismatchError(
+            f"This deployment is recorded as {existing.environment}, with the Temporal namespace "
+            f"`{existing.temporal_namespace}`. Neither can change."
+        )
+    return existing
+
+
+async def check_namespace(s: AsyncSession, configured: str) -> PlatformSettings:
+    """The record, when this process's namespace is the recorded one. Raises otherwise: the process must not start."""
+    row = await recorded(s)
+    if row is None:
+        raise EnvironmentNotRecordedError()
+    if row.temporal_namespace != configured:
+        raise EnvironmentMismatchError(
+            f"This deployment uses the Temporal namespace `{row.temporal_namespace}`, but this process is configured "
+            f"for `{configured}` (DEWPOINT_TEMPORAL_NAMESPACE). It won't start."
+        )
+    return row
diff --git a/deploy/compose/docker-compose.yml b/deploy/compose/docker-compose.yml
index 2050671..01821cf 100644
--- a/deploy/compose/docker-compose.yml
+++ b/deploy/compose/docker-compose.yml
@@ -33,10 +33,13 @@ services:
 
   migrate:
     <<: *app
-    command: ["alembic", "upgrade", "head"]
+    # The schema, then what this deployment is, recorded once (engine 2b spec §2.1): production and gated unless a
+    # development setup opts in with its own database and Temporal namespace. Every later run checks the same values.
+    command: ["sh", "-c", "set -e; alembic upgrade head; dewpoint platform init-environment"]
     environment:
       <<: *appenv
       DEWPOINT_DATABASE_URL: postgresql+asyncpg://dewpoint_owner:${POSTGRES_PASSWORD}@postgres/dewpoint
+      DEWPOINT_ENVIRONMENT: ${DEWPOINT_ENVIRONMENT:-production}
     depends_on: { postgres: { condition: service_healthy } }
     restart: "no"
````

- [ ] **Step 4: Run the tests again**

Run: `cd backend && uv run pytest -q -p no:cacheprovider tests/apps/cli/test_dev_run_cli.py tests/apps/cli/test_platform_cli.py tests/apps/test_environment.py tests/apps/worker/test_deployment.py tests/core/platform/test_service.py`

Expected (the replay):

````text
26 passed in 35.00s
````

- [ ] **Step 5: The whole suite, lint, types and layers**

Run: `cd backend && uv run pytest -q -p no:cacheprovider`, then `uv run ruff check --no-cache src tests migrations`, `uv run ruff format --no-cache --check src tests migrations`, `uv run mypy src` and `uv run lint-imports`.

Expected: 1,110 passed, 8 skipped; ruff and its formatter clean; mypy: no issues; import-linter: 10 contracts kept.

- [ ] **Step 6: Commit**

```bash
git add -A backend deploy docs && git commit -m "feat(platform): the deployment's environment, recorded once, and the namespace check (2b-1a)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: The production gate at the start boundary

**Spec:** §2.2–2.3.

**Files:**
- Create: `backend/tests/apps/test_admission_gate.py`
- Modify: `backend/src/dewpoint/apps/runs.py`
- Modify: `backend/tests/apps/test_runs.py`
- Modify: `backend/tests/apps/worker/test_admission_abi.py`
- Modify: `backend/tests/apps/worker/test_dev_run.py`
- Modify: `backend/tests/apps/worker/test_worker_db.py`
- Modify: `backend/tests/conftest.py`

**Interfaces:**
- Consumes: Task 1's `recorded`, `NOT_RECORDED`, `PRODUCTION`, `record_environment`, `DEVELOPMENT`.
- Produces:
  - `dewpoint.apps.runs.PRODUCTION_RUNS_DISABLED` (str);
  - the async fixture `development_deployment` in `backend/tests/conftest.py`: it records `development` on the
    `default` namespace, and the per-test cleanup removes it.

`admit` refuses a run while the deployment's environment isn't recorded (`NOT_RECORDED`), and in a
`production` deployment while `production_runs` is off (`PRODUCTION_RUNS_DISABLED`). There's no test-tenant bypass,
and nothing in 2b-1a turns the gate on: 2b-4's `enable-production-runs` does, after its readiness checks. Tests that
admit runs record a `development` deployment through a new fixture.

- [ ] **Step 1: Write the tests**

````diff
diff --git a/backend/tests/apps/test_admission_gate.py b/backend/tests/apps/test_admission_gate.py
new file mode 100644
index 0000000..447d6ff
--- /dev/null
+++ b/backend/tests/apps/test_admission_gate.py
@@ -0,0 +1,66 @@
+# SPDX-License-Identifier: Apache-2.0
+"""The production gate at the start boundary (engine 2b spec §2.3): every start path comes through `admit`, the dev CLI
+included, and in a production deployment it admits nothing while the gate is off. The environment itself:
+tests/core/platform/test_service.py."""
+
+from typing import Any
+
+import pytest
+from sqlalchemy import func, select, text
+
+from dewpoint.apps.runs import PRODUCTION_RUNS_DISABLED, NotAdmissibleError, start_run
+from dewpoint.core.models.runs import Run
+from dewpoint.core.platform.service import NOT_RECORDED, PRODUCTION, record_environment
+from dewpoint.engine.runtime.activities import SIMULATE
+from tests.apps.test_runs import FakeClient, published
+
+
+async def refused(dispatch: Any, api_settings: Any, ctx: Any, version: Any) -> tuple[list[str], FakeClient]:
+    client = FakeClient()
+    with pytest.raises(NotAdmissibleError) as e:
+        await start_run(
+            dispatch, client, api_settings,  # type: ignore[arg-type]
+            tenant_id=ctx.tenant_id, version_id=version, trigger={}, mode=SIMULATE,
+        )  # fmt: skip
+    return e.value.reasons, client
+
+
+async def run_count(owner: Any) -> int:
+    async with owner() as s:
+        return int((await s.execute(select(func.count()).select_from(Run))).scalar_one())
+
+
+async def test_a_production_deployment_admits_nothing_while_its_gate_is_off(
+    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings
+) -> None:
+    async with owner_sessionmaker() as s, s.begin():
+        await record_environment(s, environment=PRODUCTION, namespace="default")
+    ctx, _, version = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings)
+    reasons, client = await refused(dispatch_sessionmaker, api_settings, ctx, version)
+    assert reasons == [PRODUCTION_RUNS_DISABLED]
+    assert (client.calls, await run_count(owner_sessionmaker)) == ([], 0)  # nothing started, no run row
+
+
+async def test_the_gate_is_the_only_thing_between_a_production_deployment_and_its_runs(
+    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings
+) -> None:
+    """2b-4's audited command turns it on; here the table's owner does."""
+    async with owner_sessionmaker() as s, s.begin():
+        await record_environment(s, environment=PRODUCTION, namespace="default")
+        await s.execute(text("UPDATE platform_settings SET production_runs = true"))
+    ctx, _, version = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings)
+    client = FakeClient()
+    await start_run(
+        dispatch_sessionmaker, client, api_settings,  # type: ignore[arg-type]
+        tenant_id=ctx.tenant_id, version_id=version, trigger={}, mode=SIMULATE,
+    )  # fmt: skip
+    assert len(client.started) == 1
+
+
+async def test_a_deployment_that_never_recorded_its_environment_admits_nothing(
+    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings
+) -> None:
+    ctx, _, version = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings)
+    reasons, client = await refused(dispatch_sessionmaker, api_settings, ctx, version)
+    assert reasons == [NOT_RECORDED]
+    assert (client.calls, await run_count(owner_sessionmaker)) == ([], 0)
diff --git a/backend/tests/apps/test_runs.py b/backend/tests/apps/test_runs.py
index afd8620..f24f9be 100644
--- a/backend/tests/apps/test_runs.py
+++ b/backend/tests/apps/test_runs.py
@@ -45,6 +45,8 @@ from tests.apps.test_workflow_ops import (
 )
 from tests.support.registry import sync_test_plugins
 
+pytestmark = pytest.mark.usefixtures("development_deployment")  # runs are admitted: engine 2b spec §2.3
+
 
 @dataclass(frozen=True)
 class LostAck:
diff --git a/backend/tests/apps/worker/test_admission_abi.py b/backend/tests/apps/worker/test_admission_abi.py
index 257be0b..69e12d6 100644
--- a/backend/tests/apps/worker/test_admission_abi.py
+++ b/backend/tests/apps/worker/test_admission_abi.py
@@ -24,6 +24,8 @@ from tests.engine.replay.record import executions
 from tests.support.plugins.testkit import TESTKIT
 from tests.support.registry import sync_test_plugins
 
+pytestmark = pytest.mark.usefixtures("development_deployment")  # runs are admitted: engine 2b spec §2.3
+
 OLD, NEW = ENGINE_ABI - 1, ENGINE_ABI  # the build before this one, and this one
 
 
diff --git a/backend/tests/apps/worker/test_dev_run.py b/backend/tests/apps/worker/test_dev_run.py
index eef1448..3bdd3bf 100644
--- a/backend/tests/apps/worker/test_dev_run.py
+++ b/backend/tests/apps/worker/test_dev_run.py
@@ -14,7 +14,8 @@ from tests.conftest import _url_for
 from tests.support.graphs import G, cel, ref
 from tests.support.registry import sync_test_plugins
 
-pytestmark = pytest.mark.usefixtures("this_build_is_current")  # its run starts on the time-skipping server
+# its run starts on the time-skipping server, in a development deployment (engine 2b spec §2.3)
+pytestmark = pytest.mark.usefixtures("this_build_is_current", "development_deployment")
 
 
 def graph() -> dict[str, Any]:
diff --git a/backend/tests/apps/worker/test_worker_db.py b/backend/tests/apps/worker/test_worker_db.py
index 958b8d0..6027e46 100644
--- a/backend/tests/apps/worker/test_worker_db.py
+++ b/backend/tests/apps/worker/test_worker_db.py
@@ -23,7 +23,8 @@ from tests.core.runs.test_service import seeded_run
 from tests.support.graphs import G, cel, ref
 from tests.support.registry import sync_test_plugins
 
-pytestmark = pytest.mark.usefixtures("this_build_is_current")  # its runs start on the time-skipping server
+# its runs start on the time-skipping server, in a development deployment (engine 2b spec §2.3)
+pytestmark = pytest.mark.usefixtures("this_build_is_current", "development_deployment")
 
 
 def graph() -> dict[str, Any]:
diff --git a/backend/tests/conftest.py b/backend/tests/conftest.py
index 3a34481..4ac98fb 100644
--- a/backend/tests/conftest.py
+++ b/backend/tests/conftest.py
@@ -14,6 +14,7 @@ from testcontainers.community.postgres import PostgresContainer
 from dewpoint.apps.api.main import create_app
 from dewpoint.core.config import Settings
 from dewpoint.core.db import make_engine, make_sessionmaker
+from dewpoint.core.platform.service import DEVELOPMENT, record_environment
 
 BACKEND = Path(__file__).resolve().parents[1]
 TEST_ROLES = [
@@ -138,3 +139,11 @@ async def client(app):  # type: ignore[no-untyped-def]
         transport=httpx.ASGITransport(app=app), base_url="https://testserver", headers={"X-Dewpoint-Client": "web"}
     ) as c:
         yield c
+
+
+@pytest.fixture
+async def development_deployment(owner_sessionmaker: async_sessionmaker[AsyncSession]) -> None:
+    """A development deployment on the default namespace: runs are admitted with no gate (engine 2b spec §2.1). The
+    record goes with the other rows after each test."""
+    async with owner_sessionmaker() as s, s.begin():
+        await record_environment(s, environment=DEVELOPMENT, namespace="default")
````

- [ ] **Step 2: Run them, and watch them fail**

Run: `cd backend && uv run pytest -q -p no:cacheprovider tests/apps/test_admission_gate.py tests/apps/test_runs.py tests/apps/worker/test_admission_abi.py tests/apps/worker/test_dev_run.py tests/apps/worker/test_worker_db.py`

Expected: FAIL. `PRODUCTION_RUNS_DISABLED` doesn't exist yet, so the gate's tests fail to collect. The replay showed:

````text
E   ImportError: cannot import name 'PRODUCTION_RUNS_DISABLED' from 'dewpoint.apps.runs'
ERROR tests/apps/test_admission_gate.py
!!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
1 error in 0.31s
````

- [ ] **Step 3: Implement**

````diff
diff --git a/backend/src/dewpoint/apps/runs.py b/backend/src/dewpoint/apps/runs.py
index 0184344..b52465f 100644
--- a/backend/src/dewpoint/apps/runs.py
+++ b/backend/src/dewpoint/apps/runs.py
@@ -31,6 +31,7 @@ from dewpoint.core.config import Settings
 from dewpoint.core.db import tenant_scope
 from dewpoint.core.models.runs import Run
 from dewpoint.core.models.workflows import WorkflowVersion
+from dewpoint.core.platform.service import NOT_RECORDED, PRODUCTION, recorded
 from dewpoint.core.plugins import lifecycle
 from dewpoint.core.runs import service as runs
 from dewpoint.core.workflows.service import lock_for_admission, other_abi
@@ -38,6 +39,11 @@ from dewpoint.engine.runtime.activities import ENGINE_QUEUE, LIVE, RunInput
 from dewpoint.engine.runtime.workflow import RunGraph
 
 START_FAILED = "start_failed"
+PRODUCTION_RUNS_DISABLED = (
+    "Production runs are off in this deployment: no run starts in a production deployment until its gate lifts "
+    "(engine 2b spec §2). A development deployment, on its own database and Temporal namespace, runs synthetic "
+    "fixtures."
+)
 NO_CURRENT_BUILD = (
     "No Dewpoint build is current in the `dewpoint-engine` deployment, so no worker would run it: make one current "
     "with `dewpoint deployment set-current`."
@@ -92,7 +98,15 @@ async def admit(
 ) -> Run:
     """Insert the run, or raise NotAdmissibleError. Call it inside a READ COMMITTED transaction. `abi` is the engine
     ABI of the deployment's current build, where the run will start (`current_abi`; None: no build is current). The
-    admitting process's own build doesn't matter: during a rollout, both builds' processes admit runs."""
+    admitting process's own build doesn't matter: during a rollout, both builds' processes admit runs.
+
+    First, what this deployment is (engine 2b spec §2.3): with no record, or in production while the gate is off, it
+    admits nothing — every start path comes through here, the dev CLI included."""
+    platform = await recorded(s)
+    if platform is None:
+        raise NotAdmissibleError([NOT_RECORDED])
+    if platform.environment == PRODUCTION and not platform.production_runs:
+        raise NotAdmissibleError([PRODUCTION_RUNS_DISABLED])
     await tenant_scope(s, tenant_id)
     version = await s.get(WorkflowVersion, version_id)
     if version is None:
@@ -193,6 +207,7 @@ async def _start(client: Client, start: RunInput, run_id: uuid.UUID) -> None:
 
 __all__ = [
     "START_FAILED",
+    "PRODUCTION_RUNS_DISABLED",
     "NO_CURRENT_BUILD",
     "START_RETRY_S",
     "NotAdmissibleError",
````

- [ ] **Step 4: Run the tests again**

Run: `cd backend && uv run pytest -q -p no:cacheprovider tests/apps/test_admission_gate.py tests/apps/test_runs.py tests/apps/worker/test_admission_abi.py tests/apps/worker/test_dev_run.py tests/apps/worker/test_worker_db.py`

Expected (the replay):

````text
31 passed in 15.25s
````

- [ ] **Step 5: The whole suite, lint, types and layers**

Run: `cd backend && uv run pytest -q -p no:cacheprovider`, then `uv run ruff check --no-cache src tests migrations`, `uv run ruff format --no-cache --check src tests migrations`, `uv run mypy src` and `uv run lint-imports`.

Expected: 1,113 passed, 8 skipped; ruff and its formatter clean; mypy: no issues; import-linter: 10 contracts kept.

- [ ] **Step 6: Commit**

```bash
git add -A backend deploy docs && git commit -m "feat(runs): the production gate at the start boundary (2b-1a)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Server-built workflow ids, their cross-checks, `ENGINE_ABI` 5

**Spec:** §6.1, §6.6.

**Files:**
- Create: `backend/src/dewpoint/engine/runtime/ids.py`
- Create: `backend/tests/apps/worker/test_run_graph_ids.py`
- Create: `backend/tests/engine/runtime/test_ids.py`
- Modify: `backend/src/dewpoint/apps/cli/main.py`
- Modify: `backend/src/dewpoint/apps/runs.py`
- Modify: `backend/src/dewpoint/apps/worker/activities.py`
- Modify: `backend/src/dewpoint/engine/__init__.py`
- Modify: `backend/src/dewpoint/engine/runtime/execution.py`
- Modify: `backend/src/dewpoint/engine/runtime/workflow.py`
- Modify: `backend/tests/apps/test_runs.py`
- Modify: `backend/tests/apps/worker/harness.py`
- Modify: `backend/tests/apps/worker/test_activities.py`
- Modify: `backend/tests/apps/worker/test_admission_abi.py`
- Modify: `backend/tests/apps/worker/test_dev_run.py`
- Modify: `backend/tests/apps/worker/test_gate_task_cost.py`
- Modify: `backend/tests/apps/worker/test_real_server.py`
- Modify: `backend/tests/apps/worker/test_run_graph.py`
- Modify: `backend/tests/apps/worker/test_run_graph_abi.py`
- Modify: `backend/tests/apps/worker/test_run_graph_cel_requests.py`
- Modify: `backend/tests/apps/worker/test_run_graph_children.py`
- Modify: `backend/tests/apps/worker/test_run_graph_continue.py`
- Modify: `backend/tests/apps/worker/test_run_graph_local_cel.py`
- Modify: `backend/tests/apps/worker/test_run_graph_policies.py`
- Modify: `backend/tests/apps/worker/test_run_graph_yield.py`
- Modify: `backend/tests/apps/worker/test_two_builds.py`
- Modify: `backend/tests/apps/worker/test_worker_db.py`
- Modify: `backend/tests/engine/cel/test_profile.py`
- Modify: `backend/tests/engine/replay/record.py`
- Modify: `backend/tests/engine/replay/test_replay.py`
- Record: `backend/tests/engine/replay/dewpoint-0.1.0+abi5/` (generated, below)

**Interfaces:**
- Produces:
  - `dewpoint.engine.runtime.ids`: `run_workflow_id(tenant_id: str, run_id: str) -> str`,
    `tenant_of(workflow_id: str) -> str | None`, `run_of(workflow_id: str) -> str | None`;
  - `ENGINE_ABI = 5`;
  - `tests.apps.worker.harness.run_id_of(workflow: WorkflowHandle | str) -> str`;
  - golden files carry a top-level `"workflowId"`, which `test_replay` pops.
- Consumes: nothing new.

Every run's workflow id is `t:<tenant>:run:<run id>`: a root (`start_run`, `dewpoint dev run`, the test
harness and the recorder), a sub-flow and a failure handler, whose ids the workflow builds from its tenant and
`workflow.uuid4()`. A batch appends `/<step>/<iteration>/batch:<start>` to its run's. `tenant_of` and `run_of` read
an id back with a strict grammar: a full match, or `None`.
- `RunGraph` and `LoopBatch` refuse a start whose id doesn't name the start's tenant and run: `internal_error`,
  non-retryable, before anything runs.
- The worker's activities that touch the store refuse an input of another tenant, and the failure isn't the node's
  (not `MAPPED`).
- The commands change, so `ENGINE_ABI` becomes 5, and the abi5 histories are recorded here, in plain text; Task 6
  records them again, encrypted. Each file keeps its execution's workflow id beside its events, since the replay must
  run under the id the run ran under.
- Tests that used `handle.id` as a run id now use the harness's `run_id_of`.

- [ ] **Step 1: Write the tests**

````diff
diff --git a/backend/tests/apps/test_runs.py b/backend/tests/apps/test_runs.py
index f24f9be..be32d50 100644
--- a/backend/tests/apps/test_runs.py
+++ b/backend/tests/apps/test_runs.py
@@ -31,6 +31,7 @@ from dewpoint.core.runs import service
 from dewpoint.core.workflows import service as workflows
 from dewpoint.engine import ENGINE_ABI
 from dewpoint.engine.runtime.activities import ENGINE_QUEUE, SIMULATE, RunInput
+from dewpoint.engine.runtime.ids import run_workflow_id
 from tests.apps.test_lifecycle_races import until_someone_waits_for_a_lock
 from tests.apps.test_workflow_ops import (
     ECHO,
@@ -120,7 +121,7 @@ async def run_row(sm: Any, tenant: uuid.UUID, run_id: uuid.UUID) -> Any:
         return await service.get_run(s, run_id)
 
 
-async def test_the_active_version_starts_with_its_run_id_as_the_workflow_id(
+async def test_the_active_version_starts_under_a_workflow_id_built_from_its_tenant_and_run(
     owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings
 ) -> None:
     ctx, _, version = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings)
@@ -130,7 +131,8 @@ async def test_the_active_version_starts_with_its_run_id_as_the_workflow_id(
         tenant_id=ctx.tenant_id, version_id=version, trigger={"x": 1}, mode=SIMULATE,
     )  # fmt: skip
     [(arg, workflow_id, queue)] = client.started
-    assert (workflow_id, queue) == (str(run_id), ENGINE_QUEUE)
+    assert (workflow_id, queue) == (run_workflow_id(str(ctx.tenant_id), str(run_id)), ENGINE_QUEUE)  # 2b spec §6.1
+    assert (arg.tenant_id, arg.run_id) == (str(ctx.tenant_id), str(run_id))
     assert (arg.version_id, arg.trigger, arg.mode) == (str(version), {"x": 1}, SIMULATE)
     assert arg.max_run_duration_s == api_settings.max_run_duration_days * 86_400
     row = await run_row(owner_sessionmaker, ctx.tenant_id, run_id)
@@ -288,7 +290,8 @@ async def test_a_lost_acknowledgement_is_reconciled_by_the_workflow_id(
         tenant_id=ctx.tenant_id, version_id=version, trigger={},
     )  # fmt: skip
     assert len(client.started) == 1  # started once, not twice
-    assert client.calls == [(str(run_id), WorkflowIDReusePolicy.REJECT_DUPLICATE)] * 2
+    workflow_id = run_workflow_id(str(ctx.tenant_id), str(run_id))
+    assert client.calls == [(workflow_id, WorkflowIDReusePolicy.REJECT_DUPLICATE)] * 2
     assert (await only_run(owner_sessionmaker, ctx.tenant_id)).status == "running"
 
 
diff --git a/backend/tests/apps/worker/harness.py b/backend/tests/apps/worker/harness.py
index edead78..e4e47c7 100644
--- a/backend/tests/apps/worker/harness.py
+++ b/backend/tests/apps/worker/harness.py
@@ -31,6 +31,7 @@ from dewpoint.engine.runtime.activities import (
     VersionData,
     cel_queue,
 )
+from dewpoint.engine.runtime.ids import run_of, run_workflow_id
 from dewpoint.engine.runtime.workflow import LoopBatch, RunGraph
 from dewpoint.sdk import Plugin
 from tests.engine.runtime.support import CATALOG, MANIFESTS
@@ -154,7 +155,16 @@ async def start_version(
     """A run of a version the store already has."""
     run_id = str(uuid.uuid4())
     run = RunInput(TENANT, run_id, version_id, trigger or {}, options.pop("mode", LIVE), **options)
-    return await client.start_workflow(RunGraph.run, run, id=run_id, task_queue=ENGINE_QUEUE)
+    return await client.start_workflow(RunGraph.run, run, id=run_workflow_id(TENANT, run_id), task_queue=ENGINE_QUEUE)
+
+
+def run_id_of(workflow: WorkflowHandle[Any, Any] | str) -> str:
+    """The run a run's handle or workflow id names, a sub-run's too: its id is built from the tenant and the run
+    (engine 2b spec §6.1)."""
+    workflow_id = workflow if isinstance(workflow, str) else workflow.id
+    run_id = run_of(workflow_id)
+    assert run_id is not None, workflow_id
+    return run_id
 
 
 async def run(
diff --git a/backend/tests/apps/worker/test_activities.py b/backend/tests/apps/worker/test_activities.py
index 44b8796..8ff73f4 100644
--- a/backend/tests/apps/worker/test_activities.py
+++ b/backend/tests/apps/worker/test_activities.py
@@ -27,6 +27,7 @@ from dewpoint.engine.cel import ipc
 from dewpoint.engine.cel import types as T
 from dewpoint.engine.cel.profile import CURRENT_CEL_PROFILE
 from dewpoint.engine.runtime.activities import MAPPED, CelInput, CelResult, StepInput, StepResult
+from dewpoint.engine.runtime.ids import run_workflow_id
 from dewpoint.sdk import Node, SideEffect, StepContext, sensitive
 from tests.support.plugins.testkit import AmbiguousSend, Echo, FailN, Reconcile, Sensitive, Slow
 
@@ -230,8 +231,15 @@ def step(ref: str, config: dict[str, Any] | None = None, **extra: Any) -> StepIn
     return StepInput(**IDS, node_key="s", iteration_key="l:0", ref=ref, config=config or {}, **extra)
 
 
+def activity_env() -> ActivityEnvironment:
+    """An activity of IDS's run: its workflow id names the tenant (engine 2b spec §6.1)."""
+    env = ActivityEnvironment()
+    env.info = dataclasses.replace(env.info, workflow_id=run_workflow_id(IDS["tenant_id"], IDS["run_id"]))
+    return env
+
+
 async def call(fn: Callable[[StepInput], Awaitable[StepResult]], data: StepInput) -> StepResult:
-    return await ActivityEnvironment().run(fn, data)
+    return await activity_env().run(fn, data)
 
 
 async def failure(fn: Callable[[StepInput], Awaitable[StepResult]], data: StepInput) -> Any:
@@ -344,7 +352,7 @@ async def test_simulation_calls_simulate_or_says_it_cannot() -> None:
 
 
 async def test_a_cancelled_step_stops() -> None:
-    env = ActivityEnvironment()
+    env = activity_env()
     task = asyncio.create_task(env.run(step_activity_for(Slow), step("testkit.slow@1", {"seconds": 30})))
     await asyncio.sleep(0.1)
     env.cancel()
@@ -438,3 +446,11 @@ async def test_a_field_serializer_emits_what_the_output_schema_declares() -> Non
     assert await call(step_activity_for(Serialized), step("testkit.serialized@1")) == StepResult(
         {"id": "id-3"}, "applied"
     )
+
+
+async def test_an_activity_refuses_an_input_of_another_tenant() -> None:
+    """Engine 2b spec §6.1: the store scopes every write by the input's tenant, so it must be the one the workflow id
+    names. The failure isn't the node's: it isn't `MAPPED`."""
+    other = dataclasses.replace(step("testkit.echo@1", {"value": 1}), tenant_id=str(uuid.UUID(int=9)))
+    refused = await failure(step_activity_for(Echo), other)
+    assert (refused.type, refused.non_retryable, refused.details) == ("internal_error", True, ())
diff --git a/backend/tests/apps/worker/test_admission_abi.py b/backend/tests/apps/worker/test_admission_abi.py
index 69e12d6..a7c277a 100644
--- a/backend/tests/apps/worker/test_admission_abi.py
+++ b/backend/tests/apps/worker/test_admission_abi.py
@@ -16,6 +16,7 @@ from dewpoint.apps.worker.main import engine_worker
 from dewpoint.apps.worker.store import DbRunStore
 from dewpoint.engine import ENGINE_ABI
 from dewpoint.engine.runtime.build import abi_of
+from dewpoint.engine.runtime.ids import run_workflow_id
 from dewpoint.engine.runtime.workflow import RunGraph
 from tests.apps.test_workflow_ops import ECHO_GRAPH, actor, create, publish, published_by_the_previous_build
 from tests.apps.worker.test_deployment import placement
@@ -61,6 +62,9 @@ async def test_admission_follows_the_current_build_through_a_promotion(
     new = (await publish(api_sessionmaker, ctx, new_wf, api_settings)).version
     assert new is not None
 
+    def workflow_id(run_id: uuid.UUID) -> str:
+        return run_workflow_id(str(ctx.tenant_id), str(run_id))
+
     async def started(version_id: uuid.UUID) -> uuid.UUID:
         return await start_run(
             dispatch_sessionmaker, client, api_settings, tenant_id=ctx.tenant_id, version_id=version_id, trigger={}
@@ -77,14 +81,14 @@ async def test_admission_follows_the_current_build_through_a_promotion(
             on_old = await started(old.id)
             # it ends before the promotion: a run whose first task hadn't run yet would start on N, and fail as it
             # loads its version (the loader's backstop, for a promotion that races a start)
-            results = [await client.get_workflow_handle_for(RunGraph.run, str(on_old)).result()]
+            results = [await client.get_workflow_handle_for(RunGraph.run, workflow_id(on_old)).result()]
             await set_current(client, n)
             assert await current_abi(client) == NEW
             with pytest.raises(NotAdmissibleError) as late:
                 await started(old.id)
             on_new = await started(new.id)
-            results.append(await client.get_workflow_handle_for(RunGraph.run, str(on_new)).result())
-            chains = [await executions(client, str(r), "") for r in (on_old, on_new)]
+            results.append(await client.get_workflow_handle_for(RunGraph.run, workflow_id(on_new)).result())
+            chains = [await executions(client, workflow_id(r), "") for r in (on_old, on_new)]
     assert early.value.reasons == [
         f"This version was published for engine ABI {NEW}, and the current build runs ABI {OLD}: make a build of ABI "
         f"{NEW} current first."
diff --git a/backend/tests/apps/worker/test_dev_run.py b/backend/tests/apps/worker/test_dev_run.py
index 3bdd3bf..1b78cef 100644
--- a/backend/tests/apps/worker/test_dev_run.py
+++ b/backend/tests/apps/worker/test_dev_run.py
@@ -8,6 +8,7 @@ from temporalio.testing import WorkflowEnvironment
 
 from dewpoint.apps.cli.main import dev_run_version
 from dewpoint.apps.worker.store import DbRunStore
+from dewpoint.engine.runtime.ids import run_workflow_id
 from tests.apps.test_workflow_ops import actor, create, publish
 from tests.apps.worker.harness import workers
 from tests.conftest import _url_for
@@ -46,7 +47,7 @@ async def test_dev_run_starts_the_active_version(
         _, waited = await dev_run_version(settings, env.client, **common)
         _, simulated = await dev_run_version(settings, env.client, simulate=True, **common)
         started, nothing = await dev_run_version(settings, env.client, wait=False, **common)
-        await env.client.get_workflow_handle(str(started)).result()
+        await env.client.get_workflow_handle(run_workflow_id(str(ctx.tenant_id), str(started))).result()
     assert waited is not None and (waited.status, waited.outputs) == ("succeeded", {"v": 2})
     assert simulated is not None and simulated.outputs == {"v": {"simulated": 2}}
     assert nothing is None
diff --git a/backend/tests/apps/worker/test_gate_task_cost.py b/backend/tests/apps/worker/test_gate_task_cost.py
index 37e8201..0316328 100644
--- a/backend/tests/apps/worker/test_gate_task_cost.py
+++ b/backend/tests/apps/worker/test_gate_task_cost.py
@@ -24,7 +24,7 @@ from dewpoint.engine.graph.validate import ValidationContext, validate
 from dewpoint.engine.runtime import execution
 from dewpoint.engine.runtime.activities import ENGINE_QUEUE, cel_queue
 from dewpoint.engine.runtime.workflow import LoopBatch, RunGraph
-from tests.apps.worker.harness import CATALOG, TESTKIT, MemoryStore, in_process, start
+from tests.apps.worker.harness import CATALOG, TESTKIT, MemoryStore, in_process, run_id_of, start
 from tests.engine.cel.test_gate_cost import ADVERSARIAL, AT_CAPS, BINDING, TASK_CPU_TARGET_S, WORST
 from tests.support.graphs import G, cel
 
@@ -137,7 +137,7 @@ async def test_no_workflow_task_passes_the_cpu_target(name: str, monkeypatch: py
                 handle = await start(env.client, store, g, AT_CAPS)
                 result = await asyncio.wait_for(handle.result(), 300)
     assert result.status == "succeeded"
-    assert {r.cel_mode for r in store.steps(handle.id) if r.node_key == "x"} == {"local"}
+    assert {r.cel_mode for r in store.steps(run_id_of(handle)) if r.node_key == "x"} == {"local"}
     worst = max(executor.cpu)
     REPORT["loads"][name] = {"expr_chars": len(expr), "tasks": len(executor.cpu), "worst_cpu_s": worst}
     assert worst <= TASK_CPU_TARGET_S, (name, sorted(executor.cpu, reverse=True)[:5])
diff --git a/backend/tests/apps/worker/test_real_server.py b/backend/tests/apps/worker/test_real_server.py
index 026b6d4..a434080 100644
--- a/backend/tests/apps/worker/test_real_server.py
+++ b/backend/tests/apps/worker/test_real_server.py
@@ -20,7 +20,7 @@ from dewpoint.apps.worker.main import engine_worker
 from dewpoint.engine.cel.profile import CURRENT_CEL_PROFILE
 from dewpoint.engine.runtime.activities import cel_queue
 from dewpoint.engine.runtime.execution import SUBFLOW_GRANT
-from tests.apps.worker.harness import MemoryStore, in_process, start
+from tests.apps.worker.harness import MemoryStore, in_process, run_id_of, start
 from tests.apps.worker.test_deployment import build
 from tests.apps.worker.test_main import settings
 from tests.engine.replay.record import executions
@@ -71,8 +71,8 @@ async def test_a_terminated_sub_flow_fails_its_step_and_its_row_records_the_end(
         await client.get_workflow_handle(child).terminate("an operator")
         result = await asyncio.wait_for(handle.result(), 60)
     assert (result.status, result.outputs, result.iterations) == ("succeeded", {"code": "terminated"}, SUBFLOW_GRANT)
-    assert store.starts[child].kind == "subflow"
-    end = store.runs[child]
+    assert store.starts[run_id_of(child)].kind == "subflow"
+    end = store.runs[run_id_of(child)]
     assert (end.status, end.error_code, end.iterations) == ("failed", "terminated", SUBFLOW_GRANT)
 
 
@@ -103,9 +103,10 @@ async def test_a_terminated_failure_handler_records_its_end_and_the_runs_stands(
         result = await asyncio.wait_for(handle.result(), 60)
     assert (result.status, result.error["code"] if result.error else None) == ("failed", "workflow_failed")
     assert result.iterations == SUBFLOW_GRANT  # the handler's whole grant: it never reported
-    assert store.starts[handler].kind == "failure_handler"
-    assert (store.runs[handler].status, store.runs[handler].error_code) == ("failed", "terminated")
-    assert store.runs[handle.id].status == "failed"
+    summary = store.runs[run_id_of(handler)]
+    assert store.starts[run_id_of(handler)].kind == "failure_handler"
+    assert (summary.status, summary.error_code) == ("failed", "terminated")
+    assert store.runs[run_id_of(handle)].status == "failed"
 
 
 def asks_for_more() -> G:
@@ -139,12 +140,13 @@ async def test_a_terminated_sub_run_that_asked_for_more_records_its_whole_grant(
     async with serving(client, store):
         handle = await start(client, store, g, {})
         child = await child_started(handle)
-        await filtered(store, child)
+        await filtered(store, run_id_of(child))
         await client.get_workflow_handle(child).terminate("an operator")
         result = await asyncio.wait_for(handle.result(), 60)
-    assert store.starts[child].kind == kind
+    sub = run_id_of(child)
+    assert store.starts[sub].kind == kind
     assert result.iterations > SUBFLOW_GRANT  # it had been granted more, and the parent debits all of it
-    assert (store.runs[child].error_code, store.runs[child].iterations) == ("terminated", result.iterations)
+    assert (store.runs[sub].error_code, store.runs[sub].iterations) == ("terminated", result.iterations)
 
 
 async def test_temporal_suggesting_continue_as_new_drains_the_run() -> None:
diff --git a/backend/tests/apps/worker/test_run_graph.py b/backend/tests/apps/worker/test_run_graph.py
index 7e71548..bb8ca1b 100644
--- a/backend/tests/apps/worker/test_run_graph.py
+++ b/backend/tests/apps/worker/test_run_graph.py
@@ -10,7 +10,7 @@ from temporalio.worker import Replayer
 
 from dewpoint.engine.cel.profile import CURRENT_CEL_PROFILE
 from dewpoint.engine.runtime.workflow import RunGraph
-from tests.apps.worker.harness import EVALUATOR_ONLY, RESULT_TIMEOUT_S, MemoryStore, run, start, workers
+from tests.apps.worker.harness import EVALUATOR_ONLY, RESULT_TIMEOUT_S, MemoryStore, run, run_id_of, start, workers
 from tests.support.graphs import G, cel, ref, template
 
 ECHO, IF, LOOP, FILTER = "testkit.echo@1", "flow.if@1", "flow.loop@1", "flow.filter@1"
@@ -49,9 +49,9 @@ async def test_a_cel_branch_runs_one_side_and_projects_control_steps(env: Workfl
         handle = await start(env.client, store, g, TRIGGER)
         result = await asyncio.wait_for(handle.result(), RESULT_TIMEOUT_S)
     assert (result.status, result.outputs) == ("succeeded", {"side": "yes"})
-    rows = {r.node_key: r for r in store.steps(handle.id)}
+    rows = {r.node_key: r for r in store.steps(run_id_of(handle))}
     assert rows["c"].status == "succeeded" and rows["c"].cel_mode == "local"  # this build runs its profile in-process
-    assert "no" not in rows and store.runs[handle.id].status == "succeeded"
+    assert "no" not in rows and store.runs[run_id_of(handle)].status == "succeeded"
 
 
 async def test_a_loop_collects_per_item_and_a_filter_keeps_matches(env: WorkflowEnvironment) -> None:
@@ -65,7 +65,7 @@ async def test_a_loop_collects_per_item_and_a_filter_keeps_matches(env: Workflow
         result = await asyncio.wait_for(handle.result(), RESULT_TIMEOUT_S)
     assert result.outputs == {"doubled": [2, 4, 6], "aps": ["ap-1", "ap-2"]}
     assert result.iterations == 3 + 3  # three iterations, three filter items
-    rows = [(r.node_key, r.iteration_key, r.status) for r in store.steps(handle.id)]
+    rows = [(r.node_key, r.iteration_key, r.status) for r in store.steps(run_id_of(handle))]
     assert sorted(rows) == [
         ("f", "", "succeeded"),
         ("l", "", "succeeded"),
@@ -91,7 +91,7 @@ async def test_retries_follow_the_manifest_and_each_attempt_is_projected(env: Wo
     async with workers(env.client, store):
         handle = await start(env.client, store, g, TRIGGER)
         assert (await asyncio.wait_for(handle.result(), RESULT_TIMEOUT_S)).status == "succeeded"
-    assert [(r.attempt, r.status, r.error_code) for r in store.steps(handle.id)] == [
+    assert [(r.attempt, r.status, r.error_code) for r in store.steps(run_id_of(handle))] == [
         (1, "failed", "testkit.transient"),
         (2, "failed", "testkit.transient"),
         (3, "succeeded", None),
@@ -119,7 +119,7 @@ async def test_an_unknown_outcome_is_never_retried_and_fails_the_run(env: Workfl
         "message": "the request may have been delivered",
         "attempt": 1,
     }
-    [row] = store.steps(handle.id)
+    [row] = store.steps(run_id_of(handle))
     assert (row.attempt, row.outcome) == (1, "outcome_unknown")
 
 
@@ -159,7 +159,7 @@ async def test_simulation_calls_simulate_and_records_it(env: WorkflowEnvironment
         handle = await start(env.client, store, g, TRIGGER, mode="simulate")
         result = await asyncio.wait_for(handle.result(), RESULT_TIMEOUT_S)
     assert result.outputs == {"v": {"simulated": 5}}
-    assert [r.outcome for r in store.steps(handle.id)] == ["simulated"]
+    assert [r.outcome for r in store.steps(run_id_of(handle))] == ["simulated"]
 
 
 async def test_without_an_evaluator_cel_fails_as_profile_unavailable(env: WorkflowEnvironment) -> None:
@@ -179,7 +179,7 @@ async def test_sensitive_outputs_are_redacted_in_the_projection(env: WorkflowEnv
     async with workers(env.client, store):
         handle = await start(env.client, store, g, TRIGGER)
         await asyncio.wait_for(handle.result(), RESULT_TIMEOUT_S)
-    [row] = store.steps(handle.id)
+    [row] = store.steps(run_id_of(handle))
     assert row.output_preview == {
         "public": "visible",
         "secret_value": "[redacted]",
diff --git a/backend/tests/apps/worker/test_run_graph_abi.py b/backend/tests/apps/worker/test_run_graph_abi.py
index f6ce60b..5d28d88 100644
--- a/backend/tests/apps/worker/test_run_graph_abi.py
+++ b/backend/tests/apps/worker/test_run_graph_abi.py
@@ -11,7 +11,7 @@ from typing import Any
 from temporalio.testing import WorkflowEnvironment
 
 from dewpoint.engine import ENGINE_ABI
-from tests.apps.worker.harness import RESULT_TIMEOUT_S, MemoryStore, start, start_version, workers
+from tests.apps.worker.harness import RESULT_TIMEOUT_S, MemoryStore, run_id_of, start, start_version, workers
 from tests.support.graphs import G
 
 OLD = ENGINE_ABI - 1  # the build before this one
@@ -36,7 +36,7 @@ async def test_a_version_of_another_abi_fails_before_any_step_runs(env: Workflow
         result = await asyncio.wait_for(handle.result(), RESULT_TIMEOUT_S)
     assert result.error is not None
     assert (result.status, result.error["code"], result.error["message"]) == ("failed", "version_unusable", REFUSED)
-    assert store.steps(handle.id) == []
+    assert store.steps(run_id_of(handle)) == []
 
 
 async def test_a_sub_flow_or_failure_handler_of_another_abi_fails_where_it_starts(env: WorkflowEnvironment) -> None:
diff --git a/backend/tests/apps/worker/test_run_graph_cel_requests.py b/backend/tests/apps/worker/test_run_graph_cel_requests.py
index 42b495a..44c8d59 100644
--- a/backend/tests/apps/worker/test_run_graph_cel_requests.py
+++ b/backend/tests/apps/worker/test_run_graph_cel_requests.py
@@ -15,7 +15,7 @@ from temporalio.testing import WorkflowEnvironment
 
 from dewpoint.engine.cel import route
 from dewpoint.engine.runtime import execution
-from tests.apps.worker.harness import MemoryStore, start, workers
+from tests.apps.worker.harness import MemoryStore, run_id_of, start, workers
 from tests.support.graphs import G, cel, ref
 
 SCHEMA: dict[str, Any] = {"type": "object", "properties": {"s": {"type": "string"}}, "required": ["s"]}
@@ -97,7 +97,7 @@ async def test_a_binding_set_over_the_limit_fails_its_step_with_input_too_large(
     handle, result = await finished(env, store, g, {"s": "x" * 5_000})
     assert (result.status, result.outputs) == ("succeeded", {"code": "input_too_large"})
     assert await requests(handle) == []  # nothing was sent
-    [row] = [r for r in store.steps(handle.id) if r.node_key == "t" and r.status == "failed"]
+    [row] = [r for r in store.steps(run_id_of(handle)) if r.node_key == "t" and r.status == "failed"]
     assert row.error_message == execution.REQUEST_TOO_LARGE  # fixed: it never quotes a value
 
 
diff --git a/backend/tests/apps/worker/test_run_graph_children.py b/backend/tests/apps/worker/test_run_graph_children.py
index 7e32288..2040d62 100644
--- a/backend/tests/apps/worker/test_run_graph_children.py
+++ b/backend/tests/apps/worker/test_run_graph_children.py
@@ -19,7 +19,7 @@ from dewpoint.engine.runtime import execution
 from dewpoint.engine.runtime import workflow as run_graph
 from dewpoint.engine.runtime.activities import ProjectInput, VersionData
 from dewpoint.engine.runtime.scheduler import Scheduler
-from tests.apps.worker.harness import MemoryStore, start, workers
+from tests.apps.worker.harness import MemoryStore, run_id_of, start, workers
 from tests.support.graphs import G, cel, ref
 
 ECHO, LOOP, FILTER, RUN, FAIL = "testkit.echo@1", "flow.loop@1", "flow.filter@1", "flow.run_workflow@1", "flow.fail@1"
@@ -56,7 +56,7 @@ async def test_a_loop_over_more_than_a_hundred_items_runs_in_batches_and_collect
     handle, result = await finished(env, store, g, {})
     assert result.status == "succeeded" and result.outputs == {"items": list(range(250)), "count": 250}
     assert result.iterations == 250 and await children_started(handle) == 3  # batches of 100, 100 and 50
-    rows = [r for r in store.steps(handle.id) if r.node_key == "x"]
+    rows = [r for r in store.steps(run_id_of(handle)) if r.node_key == "x"]
     assert sorted(r.iteration_key for r in rows) == sorted(f"l:{i}" for i in range(250))  # the inline keys
     assert {(r.status, r.output_preview["value"]) for r in rows} == {("succeeded", "from outside")}
     history = await handle.fetch_history()
@@ -78,7 +78,7 @@ async def test_a_secret_a_batch_learned_is_masked_in_its_parent_too(env: Workflo
     g.edge("l", "s", "body").edge("l", "e", "done")
     handle, result = await finished(env, store, g, {})
     assert result.status == "succeeded"
-    [echoed] = [r for r in store.steps(handle.id) if r.node_key == "e"]
+    [echoed] = [r for r in store.steps(run_id_of(handle)) if r.node_key == "e"]
     assert "s3cr3t-value" not in json.dumps(echoed.output_preview) and "[redacted]" in json.dumps(echoed.output_preview)
 
 
@@ -150,7 +150,7 @@ async def test_a_sub_flow_is_a_run_of_its_own_and_its_outputs_are_the_steps_outp
     step = next(n["id"] for n in g.nodes if n["key"] == "r")
     assert (row.kind, row.parent_run_id, row.parent_step_id, row.parent_iteration_key) == (
         "subflow",
-        handle.id,
+        run_id_of(handle),
         step,
         "",
     )
@@ -180,7 +180,7 @@ async def test_a_failed_run_runs_its_failure_handler_once_with_the_error(env: Wo
     handle, result = await finished(env, store, g, {})
     assert (result.status, result.error["code"]) == ("failed", "workflow_failed")  # the handler changes nothing
     [(child, row)] = store.starts.items()
-    assert (row.kind, row.parent_run_id, row.parent_step_id) == ("failure_handler", handle.id, None)
+    assert (row.kind, row.parent_run_id, row.parent_step_id) == ("failure_handler", run_id_of(handle), None)
     assert store.runs[child].status == "succeeded"
     [echoed] = store.steps(child)
     assert echoed.output_preview == {"value": "workflow_failed"}
@@ -369,7 +369,7 @@ async def test_a_batch_that_fails_on_a_bug_writes_its_rows_first(
         handle = await start(env.client, store, g, {})
         result = await asyncio.wait_for(handle.result(), 60)
     assert (result.status, result.outputs) == ("succeeded", {"code": "internal_error"})
-    rows = [r for r in store.steps(handle.id) if r.node_key == "x"]
+    rows = [r for r in store.steps(run_id_of(handle)) if r.node_key == "x"]
     assert len(rows) >= 50 and "running" not in {r.status for r in rows}
 
 
@@ -430,7 +430,7 @@ async def test_cancelling_a_run_cancels_its_children_and_each_reports_back(env:
         i for i, k in enumerate(kinds) if k == EventType.EVENT_TYPE_CHILD_WORKFLOW_EXECUTION_COMPLETED
     )
     [(child, _)] = store.starts.items()
-    assert (store.runs[handle.id].status, store.runs[child].status) == ("cancelled", "cancelled")
+    assert (store.runs[run_id_of(handle)].status, store.runs[child].status) == ("cancelled", "cancelled")
 
 
 async def test_a_batched_loop_inside_a_loop_runs_its_own_batches_per_iteration(env: WorkflowEnvironment) -> None:
@@ -443,7 +443,7 @@ async def test_a_batched_loop_inside_a_loop_runs_its_own_batches_per_iteration(e
     handle, result = await finished(env, store, g, {})
     assert (result.status, result.outputs, result.iterations) == ("succeeded", {"counts": [150, 150]}, 302)
     assert await children_started(handle) == 4
-    keys = {r.iteration_key for r in store.steps(handle.id) if r.node_key == "x"}
+    keys = {r.iteration_key for r in store.steps(run_id_of(handle)) if r.node_key == "x"}
     assert keys == {f"outer:{o}/inner:{i}" for o in (0, 1) for i in range(150)}
 
 
@@ -480,7 +480,7 @@ async def test_a_sub_flow_the_run_ends_before_it_starts_uses_nothing(env: Workfl
     g = graph()
     g.node("r", RUN, {"workflow_id": str(store.publish(sleeper()))}).node("f", FAIL, {"message": "at once"})
     handle, result = await finished(env, store, g, {})
-    assert (result.status, result.iterations, store.runs[handle.id].iterations) == ("failed", 0, 0)
+    assert (result.status, result.iterations, store.runs[run_id_of(handle)].iterations) == ("failed", 0, 0)
     assert await children_started(handle) == 0
 
 
@@ -490,7 +490,7 @@ async def test_a_batch_the_run_ends_before_it_starts_uses_nothing(env: WorkflowE
     g.node("l", LOOP, {"items": list(range(150))}).node("x", ECHO).edge("l", "x", "body")
     g.node("t", "flow.transform@1", {"fields": {"n": 1}}).node("f", FAIL, {"message": "at once"}).edge("t", "f")
     handle, result = await finished(env, store, g, {})  # `f` fails the run in the turn the first batch would start
-    assert (result.status, result.iterations, store.runs[handle.id].iterations) == ("failed", 0, 0)
+    assert (result.status, result.iterations, store.runs[run_id_of(handle)].iterations) == ("failed", 0, 0)
     assert await children_started(handle) == 0
 
 
@@ -522,7 +522,7 @@ async def test_a_batched_loop_in_a_sub_flow_writes_into_the_sub_run(env: Workflo
     assert (result.status, result.outputs, result.iterations) == ("succeeded", {"n": 150}, 150)
     [(child, _)] = store.starts.items()
     assert len([r for r in store.steps(child) if r.node_key == "x"]) == 150
-    assert not [r for r in store.steps(handle.id) if r.node_key == "x"]
+    assert not [r for r in store.steps(run_id_of(handle)) if r.node_key == "x"]
 
 
 # --- the owner's plan review: every end at a child's boundary is recorded ----------------------------------------
@@ -586,7 +586,7 @@ async def test_a_cancel_while_the_failure_handler_runs_leaves_the_run_failed(env
         await handle.cancel()
         result = await asyncio.wait_for(handle.result(), 60)
     assert (result.status, result.error["code"], result.iterations) == ("failed", "workflow_failed", 30)
-    assert (store.runs[handle.id].status, store.runs[handle.id].iterations) == ("failed", 30)
+    assert (store.runs[run_id_of(handle)].status, store.runs[run_id_of(handle)].iterations) == ("failed", 30)
     assert (store.runs[child].status, store.runs[child].iterations) == ("cancelled", 30)
 
 
@@ -626,8 +626,12 @@ async def test_a_failed_run_stays_non_terminal_until_its_failure_handler_has_end
     g.node("f", FAIL, {"message": "it went wrong"})
     handle, result = await finished(env, store, g, {})
     [(child, _)] = store.starts.items()
-    assert store.log.index(("start", child)) < store.log.index(("end", child)) < store.log.index(("end", handle.id))
-    assert (result.status, store.runs[handle.id].status) == ("failed", "failed")
+    assert (
+        store.log.index(("start", child))
+        < store.log.index(("end", child))
+        < store.log.index(("end", run_id_of(handle)))
+    )
+    assert (result.status, store.runs[run_id_of(handle)].status) == ("failed", "failed")
 
 
 async def test_a_failure_handlers_iterations_count_toward_its_run(env: WorkflowEnvironment) -> None:
@@ -639,7 +643,7 @@ async def test_a_failure_handlers_iterations_count_toward_its_run(env: WorkflowE
     g.settings["failure_handler"] = str(store.publish(handler))
     g.node("f", FAIL, {"message": "it went wrong"})
     handle, result = await finished(env, store, g, {})
-    assert (result.status, result.iterations, store.runs[handle.id].iterations) == ("failed", 50, 50)
+    assert (result.status, result.iterations, store.runs[run_id_of(handle)].iterations) == ("failed", 50, 50)
 
 
 async def test_a_run_past_its_deadline_runs_its_failure_handler(env: WorkflowEnvironment) -> None:
@@ -671,4 +675,4 @@ async def test_a_cancelled_run_runs_no_failure_handler(env: WorkflowEnvironment)
         await handle.cancel()
         with pytest.raises(WorkflowFailureError):
             await asyncio.wait_for(handle.result(), 60)
-    assert (store.runs[handle.id].status, store.starts) == ("cancelled", {})
+    assert (store.runs[run_id_of(handle)].status, store.starts) == ("cancelled", {})
diff --git a/backend/tests/apps/worker/test_run_graph_continue.py b/backend/tests/apps/worker/test_run_graph_continue.py
index 6b6811e..41919fd 100644
--- a/backend/tests/apps/worker/test_run_graph_continue.py
+++ b/backend/tests/apps/worker/test_run_graph_continue.py
@@ -25,8 +25,9 @@ from dewpoint.engine.runtime.activities import (
     ProjectInput,
     VersionData,
 )
+from dewpoint.engine.runtime.ids import run_workflow_id
 from dewpoint.engine.runtime.workflow import LoopBatch
-from tests.apps.worker.harness import TENANT, MemoryStore, start, workers
+from tests.apps.worker.harness import TENANT, MemoryStore, run_id_of, start, workers
 from tests.support.graphs import G, cel, ref
 from tests.support.plugins.testkit import Slow, SlowSend
 
@@ -83,7 +84,7 @@ async def test_a_long_run_continues_as_new_and_ends_as_it_would_have(env: Workfl
         runs[0].events[-1].workflow_execution_continued_as_new_event_attributes.input.payloads[0].data
     )
     assert continued["iterations"] == continued["snapshot"]["scheduler"]["budget"]["used"] > 0  # outside it too (M6)
-    rows = [r for r in store.steps(handle.id) if r.node_key == "x"]
+    rows = [r for r in store.steps(run_id_of(handle)) if r.node_key == "x"]
     assert len(rows) == 40 and {(r.attempt, r.status) for r in rows} == {(1, "succeeded")}
 
 
@@ -111,8 +112,8 @@ async def test_a_cancel_while_the_run_gets_ready_to_continue_as_new_ends_it_canc
         with pytest.raises(WorkflowFailureError):
             await asyncio.wait_for(handle.result(), 30)
         runs = await chain(env.client, handle.id, handle.first_execution_run_id or "")
-    assert len(runs) == 1 and store.runs[handle.id].status == "cancelled"
-    assert [(r.node_key, r.status) for r in store.steps(handle.id)] == [("a", "succeeded")]  # `b` never started
+    assert len(runs) == 1 and store.runs[run_id_of(handle)].status == "cancelled"
+    assert [(r.node_key, r.status) for r in store.steps(run_id_of(handle))] == [("a", "succeeded")]  # `b` never started
 
 
 @dataclasses.dataclass
@@ -161,8 +162,8 @@ async def test_a_cancel_while_the_run_settles_for_continue_as_new_lets_its_proje
             await asyncio.wait_for(handle.result(), 30)
         history = await first.fetch_history()
     requested = [e for e in history.events if e.event_type == EventType.EVENT_TYPE_ACTIVITY_TASK_CANCEL_REQUESTED]
-    assert requested == [] and store.runs[handle.id].status == "cancelled"
-    assert sorted(r.node_key for r in store.steps(handle.id)) == ["a", "c"]  # `b` never started
+    assert requested == [] and store.runs[run_id_of(handle)].status == "cancelled"
+    assert sorted(r.node_key for r in store.steps(run_id_of(handle))) == ["a", "c"]  # `b` never started
 
 
 def doubler() -> G:
@@ -195,13 +196,13 @@ async def test_draining_settles_what_is_outstanding_and_a_timer_keeps_its_wake_t
         runs = await chain(own_env.client, handle.id, handle.first_execution_run_id or "")
     assert (result.status, result.outputs) == ("succeeded", {"double": 42, "count": 150})
     assert len(runs) >= 2, "it never drained"
-    assert SlowSend.sent.count(handle.id) == 5  # each ambiguous send once
+    assert SlowSend.sent.count(run_id_of(handle)) == 5  # each ambiguous send once
     started = count(runs, EventType.EVENT_TYPE_CHILD_WORKFLOW_EXECUTION_STARTED)
     assert started == 3  # two batches and the sub-flow, none restarted
     assert count(runs, EventType.EVENT_TYPE_CHILD_WORKFLOW_EXECUTION_TERMINATED) == 0
     carried = [s for s in (snapshot(h) for h in runs[:-1]) if s["timers"]]
     assert carried, "the timer never went into a snapshot"
-    [delay] = [r for r in store.steps(handle.id) if r.node_key == "d"]
+    [delay] = [r for r in store.steps(run_id_of(handle)) if r.node_key == "d"]
     assert delay.started_at and delay.ended_at
     took = datetime.fromisoformat(delay.ended_at) - datetime.fromisoformat(delay.started_at)
     assert timedelta(seconds=3599) <= took <= timedelta(seconds=3601), took  # its original wake time
@@ -252,7 +253,7 @@ async def test_the_headroom_draining_adds_is_measured_and_bounded(own_env: Workf
         and e.signal_external_workflow_execution_initiated_event_attributes.signal_name == BUDGET
     ]
     assert (len(retried), len(granted)) == (10, 10)  # every retry and every grant happened while draining
-    beats = [at for run, at in Slow.beats if run == handle.id]
+    beats = [at for run, at in Slow.beats if run == run_id_of(handle)]
     assert len(beats) == 80 * 3 and min(beats) > datetime.fromisoformat(drained["at"])  # and every heartbeat
     events, added = continued - began, size_continued - size_began
     print(f"draining added {events} events and {added} bytes")  # the measurement the headroom is set from
@@ -269,7 +270,7 @@ async def test_a_snapshot_of_another_format_fails_the_run(env: WorkflowEnvironme
         handle = await start(env.client, store, g, {}, snapshot={"snapshot_format": 99}, iterations=37)
         result = await asyncio.wait_for(handle.result(), 30)
     assert (result.status, result.error["code"], result.iterations) == ("failed", "internal_error", 37)
-    assert store.runs[handle.id].iterations == 37
+    assert store.runs[run_id_of(handle)].iterations == 37
 
 
 async def test_a_batch_with_a_snapshot_of_another_format_fails_as_a_workflow(env: WorkflowEnvironment) -> None:
@@ -283,10 +284,12 @@ async def test_a_batch_with_a_snapshot_of_another_format_fails_as_a_workflow(env
         snapshot={"snapshot_format": 99},
     )  # fmt: skip
     async with workers(env.client, store):
-        handle = await env.client.start_workflow(LoopBatch.run, batch, id=str(uuid.uuid4()), task_queue=ENGINE_QUEUE)
+        batch_id = f"{run_workflow_id(TENANT, parent.run_id)}/{uuid.uuid4()}/l:0/batch:0"
+        handle = await env.client.start_workflow(LoopBatch.run, batch, id=batch_id, task_queue=ENGINE_QUEUE)
         with pytest.raises(WorkflowFailureError) as failed:
             await asyncio.wait_for(handle.result(), 30)
     assert isinstance(failed.value.cause, ApplicationError) and failed.value.cause.type == "internal_error"
+    assert failed.value.cause.message == "This build can't read the batch's continue-as-new snapshot."
 
 
 @dataclasses.dataclass
@@ -326,7 +329,7 @@ async def test_a_continued_sub_flow_that_cant_load_its_version_reports_what_it_u
         handle = await start(env.client, store, g, {}, checkpoint_events=120)
         result = await asyncio.wait_for(handle.result(), 60)
         [child] = [run_id for run_id, row in store.starts.items() if row.kind == "subflow"]
-        started = (await env.client.get_workflow_handle(child).fetch_history()).events[0]
+        started = (await env.client.get_workflow_handle(run_workflow_id(TENANT, child)).fetch_history()).events[0]
     carried = json.loads(started.workflow_execution_started_event_attributes.input.payloads[0].data)["iterations"]
     assert store.loads == 2 and carried > 0  # it continued as new, then couldn't run its version
     assert (store.runs[child].error_code, store.runs[child].iterations) == ("version_unusable", carried)
diff --git a/backend/tests/apps/worker/test_run_graph_ids.py b/backend/tests/apps/worker/test_run_graph_ids.py
new file mode 100644
index 0000000..a5a73d7
--- /dev/null
+++ b/backend/tests/apps/worker/test_run_graph_ids.py
@@ -0,0 +1,71 @@
+# SPDX-License-Identifier: Apache-2.0
+"""Engine 2b spec §6.1: every store write is scoped by a start's tenant, so a run and a batch refuse a start whose
+server-built workflow id names another tenant or run. Only a bug, or a start built outside Dewpoint, gets there: it
+fails before anything runs, and writes nothing."""
+
+import asyncio
+import uuid
+from typing import Any
+
+import pytest
+from temporalio.client import WorkflowFailureError
+from temporalio.exceptions import ApplicationError
+from temporalio.testing import WorkflowEnvironment
+
+from dewpoint.engine.runtime.activities import BATCH, ENGINE_QUEUE, BatchInput, Parent, RunInput
+from dewpoint.engine.runtime.execution import INTERNAL_ERROR
+from dewpoint.engine.runtime.ids import run_workflow_id
+from dewpoint.engine.runtime.workflow import LoopBatch, RunGraph
+from tests.apps.worker.harness import TENANT, MemoryStore, workers
+from tests.support.graphs import G
+
+OTHER = str(uuid.UUID(int=9))
+REFUSED = "This run's workflow id doesn't name its tenant and run."
+
+
+def graph() -> G:
+    g = G()
+    g.settings = {"input_schema": {"type": "object"}, "outputs": {}}
+    return g
+
+
+async def refused(handle: Any) -> ApplicationError:
+    with pytest.raises(WorkflowFailureError) as failed:
+        await asyncio.wait_for(handle.result(), 30)
+    assert isinstance(failed.value.cause, ApplicationError)
+    return failed.value.cause
+
+
+def ids(run_id: str) -> list[str]:
+    """Workflow ids that don't name TENANT's run `run_id`."""
+    return [run_workflow_id(OTHER, run_id), run_workflow_id(TENANT, OTHER), run_id]
+
+
+async def test_a_run_refuses_a_workflow_id_of_another_tenant_or_run(env: WorkflowEnvironment) -> None:
+    store = MemoryStore()
+    version = store.add(graph().node("a", "testkit.echo@1", {"value": 1}))
+    async with workers(env.client, store):
+        for workflow_id in ids(run_id := str(uuid.uuid4())):
+            start = RunInput(TENANT, run_id, version, {})
+            handle = await env.client.start_workflow(RunGraph.run, start, id=workflow_id, task_queue=ENGINE_QUEUE)
+            failure = await refused(handle)
+            assert (failure.type, failure.message, failure.non_retryable) == (INTERNAL_ERROR, REFUSED, True)
+    assert (store.starts, store.runs, store.rows) == ({}, {}, {})
+
+
+async def test_a_batch_refuses_a_workflow_id_of_another_tenant_or_run(env: WorkflowEnvironment) -> None:
+    store = MemoryStore()
+    version = store.add(
+        graph().node("l", "flow.loop@1", {"items": [1]}).node("x", "testkit.echo@1").edge("l", "x", "body")
+    )
+    now = (await env.get_current_time()).isoformat()
+    run_id = str(uuid.uuid4())
+    parent = Parent(run_workflow_id(TENANT, run_id), run_id, str(uuid.uuid4()), "", BATCH, now, 0)
+    batch = BatchInput(TENANT, run_id, version, str(uuid.uuid4()), [], [], 0, 1, True, {}, {}, now, parent)
+    async with workers(env.client, store):
+        for workflow_id in ids(run_id):
+            batch_id = f"{workflow_id}/{parent.step_id}/l:0/batch:0"
+            handle = await env.client.start_workflow(LoopBatch.run, batch, id=batch_id, task_queue=ENGINE_QUEUE)
+            failure = await refused(handle)
+            assert (failure.type, failure.message, failure.non_retryable) == (INTERNAL_ERROR, REFUSED, True)
+    assert (store.starts, store.runs, store.rows) == ({}, {}, {})
diff --git a/backend/tests/apps/worker/test_run_graph_local_cel.py b/backend/tests/apps/worker/test_run_graph_local_cel.py
index 62b8e18..1f19e21 100644
--- a/backend/tests/apps/worker/test_run_graph_local_cel.py
+++ b/backend/tests/apps/worker/test_run_graph_local_cel.py
@@ -10,7 +10,7 @@ from temporalio.client import WorkflowHistory
 from temporalio.testing import WorkflowEnvironment
 
 from dewpoint.engine.runtime.activities import CEL_EVALUATE
-from tests.apps.worker.harness import EVALUATOR_ONLY, RESULT_TIMEOUT_S, MemoryStore, start, workers
+from tests.apps.worker.harness import EVALUATOR_ONLY, RESULT_TIMEOUT_S, MemoryStore, run_id_of, start, workers
 from tests.support.graphs import G, cel, ref
 
 ITEMS = {"type": "object", "properties": {"xs": {"type": "array", "items": {"type": "integer"}}}, "required": ["xs"]}
@@ -28,7 +28,7 @@ async def finished(env: WorkflowEnvironment, g: G, xs: list[int]) -> tuple[Memor
         handle = await start(env.client, store, g, {"xs": xs})
         result = await asyncio.wait_for(handle.result(), RESULT_TIMEOUT_S)
         history = await handle.fetch_history()
-    return store, handle.id, result, history
+    return store, run_id_of(handle), result, history
 
 
 def evaluations(history: WorkflowHistory) -> int:
diff --git a/backend/tests/apps/worker/test_run_graph_policies.py b/backend/tests/apps/worker/test_run_graph_policies.py
index 7b1d645..bd2b0c8 100644
--- a/backend/tests/apps/worker/test_run_graph_policies.py
+++ b/backend/tests/apps/worker/test_run_graph_policies.py
@@ -24,8 +24,18 @@ from dewpoint.engine.runtime.activities import (
     ProjectInput,
     RunInput,
 )
+from dewpoint.engine.runtime.ids import run_workflow_id
 from dewpoint.engine.runtime.workflow import PROJECT_BYTES, RunGraph
-from tests.apps.worker.harness import EVALUATOR_ONLY, RESULT_TIMEOUT_S, TENANT, MemoryStore, run, start, workers
+from tests.apps.worker.harness import (
+    EVALUATOR_ONLY,
+    RESULT_TIMEOUT_S,
+    TENANT,
+    MemoryStore,
+    run,
+    run_id_of,
+    start,
+    workers,
+)
 from tests.support.graphs import G, cel, ref, template
 from tests.support.plugins.testkit import SlowSend
 
@@ -154,7 +164,7 @@ async def test_a_default_covers_a_missing_value_and_a_failed_expression_fails_th
         handle = await start(env.client, store, g, TRIGGER)
         result = await asyncio.wait_for(handle.result(), RESULT_TIMEOUT_S)
     assert result.outputs == {"a": "fallback", "b": "evaluation_error"}
-    rows = {r.node_key: r for r in store.steps(handle.id)}  # b never reached its activity, and still has its row
+    rows = {r.node_key: r for r in store.steps(run_id_of(handle))}  # b never reached its activity: it has its row
     assert (rows["b"].attempt, rows["b"].status, rows["b"].error_code) == (1, "failed", "evaluation_error")
 
 
@@ -214,7 +224,8 @@ async def test_one_projection_is_outstanding_at_a_time(env: WorkflowEnvironment)
         elif event.event_type == EventType.EVENT_TYPE_ACTIVITY_TASK_COMPLETED:
             outstanding.discard(event.activity_task_completed_event_attributes.scheduled_event_id)
     assert most == 1
-    assert sorted(r.node_key for r in store.steps(handle.id)) == sorted(f"{k}{i}" for k in "et" for i in range(4))
+    keys = sorted(r.node_key for r in store.steps(run_id_of(handle)))
+    assert keys == sorted(f"{k}{i}" for k in "et" for i in range(4))
 
 
 async def test_a_projection_in_flight_takes_no_units_slot(env: WorkflowEnvironment) -> None:
@@ -252,9 +263,9 @@ async def test_the_deadline_cancels_running_work(own_env: WorkflowEnvironment) -
         handle = await start(own_env.client, store, g, TRIGGER, max_run_duration_s=2)
         result = await asyncio.wait_for(handle.result(), RESULT_TIMEOUT_S)
     assert result.status == "deadline_exceeded"
-    [row] = store.steps(handle.id)
+    [row] = store.steps(run_id_of(handle))
     assert row.status == "cancelled"
-    assert store.runs[handle.id].status == "deadline_exceeded"
+    assert store.runs[run_id_of(handle)].status == "deadline_exceeded"
 
 
 async def test_a_cancelled_run_projects_its_end(env: WorkflowEnvironment) -> None:
@@ -266,7 +277,7 @@ async def test_a_cancelled_run_projects_its_end(env: WorkflowEnvironment) -> Non
         await handle.cancel()
         with pytest.raises(WorkflowFailureError):
             await asyncio.wait_for(handle.result(), RESULT_TIMEOUT_S)
-    assert store.runs[handle.id].status == "cancelled"
+    assert store.runs[run_id_of(handle)].status == "cancelled"
 
 
 async def test_a_version_this_build_cannot_run_fails_the_run(env: WorkflowEnvironment) -> None:
@@ -277,7 +288,10 @@ async def test_a_version_this_build_cannot_run_fails_the_run(env: WorkflowEnviro
     run_id = str(uuid.uuid4())
     async with workers(env.client, store):
         handle = await env.client.start_workflow(
-            RunGraph.run, RunInput(TENANT, run_id, version_id, TRIGGER), id=run_id, task_queue=ENGINE_QUEUE
+            RunGraph.run,
+            RunInput(TENANT, run_id, version_id, TRIGGER),
+            id=run_workflow_id(TENANT, run_id),
+            task_queue=ENGINE_QUEUE,
         )
         result = await asyncio.wait_for(handle.result(), 10)
     assert result.status == "failed" and result.error and result.error["code"] == "version_unusable"
@@ -304,7 +318,8 @@ async def test_a_bug_fails_the_run_instead_of_leaving_it_running(
         result = await asyncio.wait_for(handle.result(), 10)
     message = "The interpreter failed (RuntimeError); the worker's log has the details."  # never the raw text
     assert result.error == {"code": "internal_error", "message": message, "attempt": 1}
-    assert store.runs[handle.id].status == "failed" and [r.status for r in store.steps(handle.id)] == ["succeeded"]
+    run_id = run_id_of(handle)
+    assert store.runs[run_id].status == "failed" and [r.status for r in store.steps(run_id)] == ["succeeded"]
 
 
 async def test_a_trigger_that_breaks_its_schema_fails_a_step_not_the_workflow(env: WorkflowEnvironment) -> None:
@@ -352,9 +367,9 @@ async def test_a_timeout_after_an_ambiguous_send_is_never_retried(own_env: Workf
     async with workers(own_env.client, store):
         handle = await start(own_env.client, store, g, TRIGGER)
         result = await asyncio.wait_for(handle.result(), RESULT_TIMEOUT_S)
-    assert SlowSend.sent.count(handle.id) == 1
+    assert SlowSend.sent.count(run_id_of(handle)) == 1
     assert result.status == "failed" and result.error and result.error["code"] == "timeout"
-    [row] = store.steps(handle.id)
+    [row] = store.steps(run_id_of(handle))
     assert (row.attempt, row.status, row.error_code, row.outcome) == (1, "failed", "timeout", "outcome_unknown")
 
 
@@ -374,11 +389,11 @@ async def test_a_worker_lost_during_an_ambiguous_attempt_never_repeats_it(own_en
     g.nodes[0]["options"].update(max_attempts=3)
     async with workers(own_env.client, store, cache=0):  # no sticky queue: the next worker takes over at once
         handle = await start(own_env.client, store, g, TRIGGER)
-        await sent(handle.id)
+        await sent(run_id_of(handle))
     async with workers(own_env.client, store):  # another worker carries the run on
         result = await asyncio.wait_for(handle.result(), 30)
-    assert SlowSend.sent.count(handle.id) == 1
-    [row] = store.steps(handle.id)
+    assert SlowSend.sent.count(run_id_of(handle)) == 1
+    [row] = store.steps(run_id_of(handle))
     assert (row.attempt, row.status, row.error_code, row.outcome) == (1, "failed", "error", "outcome_unknown")
     assert result.status == "failed"
 
@@ -390,11 +405,11 @@ async def test_a_cancelled_ambiguous_attempt_says_its_outcome_is_unknown(own_env
     g = graph().node("s", "testkit.slow_send@1", {"seconds": 5})
     async with workers(own_env.client, store):
         handle = await start(own_env.client, store, g, TRIGGER)
-        await sent(handle.id)  # the attempt has sent its request (its history says so only once it ends)
+        await sent(run_id_of(handle))  # the attempt has sent its request (its history says so only once it ends)
         await handle.cancel()
         with pytest.raises(WorkflowFailureError):
             await asyncio.wait_for(handle.result(), 30)
-    [row] = [r for r in store.steps(handle.id) if r.node_key == "s"]
+    [row] = [r for r in store.steps(run_id_of(handle)) if r.node_key == "s"]
     assert (row.status, row.outcome) == ("cancelled", OUTCOME_UNKNOWN)
 
 
@@ -405,7 +420,7 @@ async def test_a_timeout_is_retried_when_repeating_is_safe(own_env: WorkflowEnvi
     async with workers(own_env.client, store):
         handle = await start(own_env.client, store, g, TRIGGER)
         await asyncio.wait_for(handle.result(), RESULT_TIMEOUT_S)
-    assert [(r.attempt, r.status, r.error_code, r.outcome) for r in store.steps(handle.id)] == [
+    assert [(r.attempt, r.status, r.error_code, r.outcome) for r in store.steps(run_id_of(handle))] == [
         (1, "failed", "timeout", None),
         (2, "failed", "timeout", None),
     ]
@@ -432,9 +447,9 @@ async def test_a_database_outage_never_repeats_an_effect_and_the_rows_catch_up(e
     async with workers(env.client, store):
         handle = await start(env.client, store, g, TRIGGER)
         result = await asyncio.wait_for(handle.result(), RESULT_TIMEOUT_S)
-    assert result.status == "succeeded" and SlowSend.sent.count(handle.id) == 1 and store.down == 0
-    assert [(r.node_key, r.status) for r in store.steps(handle.id)] == [("s", "succeeded"), ("t", "succeeded")]
-    assert store.runs[handle.id].status == "succeeded"
+    assert result.status == "succeeded" and SlowSend.sent.count(run_id_of(handle)) == 1 and store.down == 0
+    assert [(r.node_key, r.status) for r in store.steps(run_id_of(handle))] == [("s", "succeeded"), ("t", "succeeded")]
+    assert store.runs[run_id_of(handle)].status == "succeeded"
 
 
 class BatchStore(FlakyStore):
@@ -460,7 +475,7 @@ async def test_a_backlog_is_projected_in_bounded_batches(env: WorkflowEnvironmen
         result = await asyncio.wait_for(handle.result(), 60)
     assert result.status == "succeeded" and store.down == 0
     assert max(store.sizes) <= PROJECT_BYTES < sum(store.sizes)  # the backlog took more than one batch
-    assert sorted(r.iteration_key for r in store.steps(handle.id) if r.node_key == "e") == sorted(
+    assert sorted(r.iteration_key for r in store.steps(run_id_of(handle)) if r.node_key == "e") == sorted(
         f"l:{i}" for i in range(40)
     )
 
@@ -483,7 +498,7 @@ async def test_sensitive_values_never_reach_the_projection(env: WorkflowEnvironm
     async with workers(env.client, store):
         handle = await start(env.client, store, g, TRIGGER)
         result = await asyncio.wait_for(handle.result(), RESULT_TIMEOUT_S)
-    rows = {r.node_key: r for r in store.steps(handle.id)}
+    rows = {r.node_key: r for r in store.steps(run_id_of(handle))}
     assert rows["s"].output_preview == {
         "public": "visible",
         "secret_value": "[redacted]",
@@ -494,7 +509,7 @@ async def test_sensitive_values_never_reach_the_projection(env: WorkflowEnvironm
     assert rows["p"].error_message == "the receiver rejected the request: [redacted]"
     assert rows["f"].error_message == "gave up on [redacted]"
     assert rows["k"].error_message == 'NOT_FOUND: Key not found in map : "[redacted]"'
-    assert store.runs[handle.id].error_message == "gave up on [redacted]"
+    assert store.runs[run_id_of(handle)].error_message == "gave up on [redacted]"
     assert result.error and result.error["message"] == "gave up on [redacted]"
     dump = repr(store.rows) + repr(store.runs)
     assert "s3cr3t-value" not in dump and "pa55word" not in dump
@@ -512,7 +527,7 @@ async def test_a_sensitive_trigger_field_is_masked_where_it_is_copied(env: Workf
     async with workers(env.client, store):
         handle = await start(env.client, store, g, {"api_key": "k3y-k3y-k3y"})
         result = await asyncio.wait_for(handle.result(), RESULT_TIMEOUT_S)
-    [row] = store.steps(handle.id)
+    [row] = store.steps(run_id_of(handle))
     assert (row.input_preview, row.output_preview) == ({"value": "Bearer [redacted]"}, {"value": "Bearer [redacted]"})
     assert result.outputs == {"key": "k3y-k3y-k3y"}  # the workflow's own outputs are its contract, not a preview
 
@@ -530,7 +545,7 @@ async def test_a_sensitive_config_value_is_masked_where_it_is_copied_or_echoed(e
     async with workers(env.client, store):
         handle = await start(env.client, store, g, {"x": 7, "open": {"tok": passed}})
         await asyncio.wait_for(handle.result(), RESULT_TIMEOUT_S)
-    rows = {r.node_key: r for r in store.steps(handle.id)}
+    rows = {r.node_key: r for r in store.steps(run_id_of(handle))}
     assert rows["t"].output_preview == {"copy": "[redacted]"}  # projected before `p` ran
     assert rows["p"].input_preview == {"outcome": "rejected", "token": "[redacted]"}
     assert rows["p"].error_message == rows["q"].error_message == "the receiver rejected the request for [redacted]"
@@ -558,7 +573,7 @@ async def test_a_cancel_while_the_outputs_are_evaluated_projects_cancelled(env:
         await handle.cancel()
         with pytest.raises(WorkflowFailureError):
             await asyncio.wait_for(handle.result(), 10)
-    assert store.runs[handle.id].status == "cancelled"
+    assert store.runs[run_id_of(handle)].status == "cancelled"
 
 
 async def test_the_deadline_holds_while_the_outputs_are_evaluated(env: WorkflowEnvironment) -> None:
@@ -569,7 +584,7 @@ async def test_the_deadline_holds_while_the_outputs_are_evaluated(env: WorkflowE
         handle = await start(env.client, store, g, TRIGGER, max_run_duration_s=1, cel_schedule_to_start_s=5)
         result = await asyncio.wait_for(handle.result(), 10)
     assert (result.status, result.error and result.error["code"]) == ("deadline_exceeded", "deadline_exceeded")
-    assert store.runs[handle.id].status == "deadline_exceeded"
+    assert store.runs[run_id_of(handle)].status == "deadline_exceeded"
 
 
 async def test_a_damaged_output_fails_the_run_as_unusable(env: WorkflowEnvironment) -> None:
@@ -581,7 +596,10 @@ async def test_a_damaged_output_fails_the_run_as_unusable(env: WorkflowEnvironme
     run_id = str(uuid.uuid4())
     async with workers(env.client, store):
         handle = await env.client.start_workflow(
-            RunGraph.run, RunInput(TENANT, run_id, version_id, TRIGGER), id=run_id, task_queue=ENGINE_QUEUE
+            RunGraph.run,
+            RunInput(TENANT, run_id, version_id, TRIGGER),
+            id=run_workflow_id(TENANT, run_id),
+            task_queue=ENGINE_QUEUE,
         )
         result = await asyncio.wait_for(handle.result(), 10)
     assert result.error and result.error["code"] == "version_unusable" and store.steps(run_id) == []
@@ -612,7 +630,7 @@ async def test_a_cancel_after_the_run_concluded_leaves_its_outcome(env: Workflow
         await handle.cancel()
         store.release.set()
         result = await asyncio.wait_for(handle.result(), 10)
-    assert (result.status, result.outputs, store.runs[handle.id].status) == ("succeeded", {"v": 1}, "succeeded")
+    assert (result.status, result.outputs, store.runs[run_id_of(handle)].status) == ("succeeded", {"v": 1}, "succeeded")
 
 
 async def cancel_acted_on(handle: Any) -> None:
@@ -640,7 +658,7 @@ async def test_a_cancel_acted_on_before_the_end_is_written_still_leaves_its_outc
         await cancel_acted_on(handle)  # the held write outlives the cancel's activation
         store.release.set()
         result = await asyncio.wait_for(handle.result(), 10)
-    assert (result.status, result.outputs, store.runs[handle.id].status) == ("succeeded", {"v": 1}, "succeeded")
+    assert (result.status, result.outputs, store.runs[run_id_of(handle)].status) == ("succeeded", {"v": 1}, "succeeded")
 
 
 class LoadingStore(MemoryStore):
@@ -667,4 +685,5 @@ async def test_a_cancel_while_the_version_loads_cancels_the_run(env: WorkflowEnv
         with pytest.raises(WorkflowFailureError):
             await asyncio.wait_for(handle.result(), 10)
         store.release.set()
-    assert (store.runs[handle.id].status, store.runs[handle.id].error_code) == ("cancelled", "cancelled")
+    summary = store.runs[run_id_of(handle)]
+    assert (summary.status, summary.error_code) == ("cancelled", "cancelled")
diff --git a/backend/tests/apps/worker/test_run_graph_yield.py b/backend/tests/apps/worker/test_run_graph_yield.py
index 0978994..40ab8dd 100644
--- a/backend/tests/apps/worker/test_run_graph_yield.py
+++ b/backend/tests/apps/worker/test_run_graph_yield.py
@@ -16,7 +16,7 @@ from dewpoint.engine.cel import route
 from dewpoint.engine.cel.profile import CURRENT_CEL_PROFILE
 from dewpoint.engine.graph.validate import ValidationContext, validate
 from dewpoint.engine.runtime import execution
-from tests.apps.worker.harness import CATALOG, MemoryStore, start, workers
+from tests.apps.worker.harness import CATALOG, MemoryStore, run_id_of, start, workers
 from tests.engine.cel.test_gate_cost import ADVERSARIAL, AT_CAPS
 from tests.support.graphs import G, cel
 
@@ -102,7 +102,7 @@ async def test_concurrent_evaluations_share_one_budget_per_workflow_task(
     g.node("x", "flow.transform@1", {"fields": {"r": cel(heaviest_search())}}).edge("l", "x", "body")
     handle, result = await finished(env, store, g, cache=cache)
     assert (result.status, result.outputs) == ("succeeded", {"count": 20})
-    assert {r.cel_mode for r in store.steps(handle.id) if r.node_key == "x"} == {"local"}
+    assert {r.cel_mode for r in store.steps(run_id_of(handle)) if r.node_key == "x"} == {"local"}
     evaluating = [[w for kind, w in t if kind == "eval"] for t in recorded.values()]
     evaluating = [works for works in evaluating if works]
     assert sum(len(works) for works in evaluating) >= 20 and len(evaluating) >= 10  # the budget split them
@@ -119,7 +119,7 @@ async def test_a_local_filter_evaluates_its_items_within_the_budget(
     g.node("f", "flow.filter@1", {"items": cel("trigger.xs"), "predicate": cel("item % 3 == 0")})
     handle, result = await finished(env, store, g)
     assert (result.status, result.outputs) == ("succeeded", {"kept": 150})
-    assert [r.cel_mode for r in store.steps(handle.id) if r.node_key == "f"] == ["local"]
+    assert [r.cel_mode for r in store.steps(run_id_of(handle)) if r.node_key == "f"] == ["local"]
     counts = [sum(kind == "eval" for kind, _ in t) for t in recorded.values()]
     assert max(counts) <= route.YIELD_EVALUATIONS and sum(counts) >= 450
 
@@ -136,7 +136,7 @@ async def test_binding_is_charged_when_the_evaluator_runs_the_expression(
     g.node("f", "flow.filter@1", {"items": list(range(20)), "predicate": cel("size(trigger.c1) > item")})
     handle, result = await finished(env, store, g)
     assert (result.status, result.outputs) == ("succeeded", {"kept": 20})
-    assert [r.cel_mode for r in store.steps(handle.id) if r.node_key == "f"] == ["activity"]
+    assert [r.cel_mode for r in store.steps(run_id_of(handle)) if r.node_key == "f"] == ["activity"]
     binding = [[n for kind, n in t if kind == "bind" and n > 16_000] for t in recorded.values()]  # the 20 views
     binding = [nodes for nodes in binding if nodes]
     assert [len(nodes) for nodes in binding] == [1, 5, 5, 5, 4]  # 4 fit in 65,000 values, the 5th passes it
@@ -155,7 +155,7 @@ async def test_an_executions_first_workflow_task_leaves_heavy_cel_to_the_next_on
     g.node("b", "flow.transform@1", {"fields": {"r": cel(heaviest_search())}})
     handle, result = await finished(env, store, g)
     assert result.status == "succeeded"
-    assert {r.cel_mode for r in store.steps(handle.id)} == {"local"}
+    assert {r.cel_mode for r in store.steps(run_id_of(handle))} == {"local"}
     first, *later = [[w for kind, w in recorded[length] if kind == "eval"] for length in sorted(recorded)]
     assert len(first) == 1  # the light one: the heavy one waited
     tenth = route.YIELD_WORK // route.STARTUP_SHARE
diff --git a/backend/tests/apps/worker/test_two_builds.py b/backend/tests/apps/worker/test_two_builds.py
index 357d245..2b0a1ce 100644
--- a/backend/tests/apps/worker/test_two_builds.py
+++ b/backend/tests/apps/worker/test_two_builds.py
@@ -23,7 +23,7 @@ from dewpoint.engine import ENGINE_ABI
 from dewpoint.engine.cel.profile import CURRENT_CEL_PROFILE
 from dewpoint.engine.runtime.activities import cel_queue
 from dewpoint.sdk import Plugin
-from tests.apps.worker.harness import EVALUATOR_ONLY, MemoryStore, in_process, start, start_version
+from tests.apps.worker.harness import EVALUATOR_ONLY, MemoryStore, in_process, run_id_of, start, start_version
 from tests.apps.worker.test_deployment import build, placement
 from tests.apps.worker.test_main import settings
 from tests.engine.replay.record import executions
@@ -80,7 +80,7 @@ async def test_the_old_build_drains_while_the_new_one_serves_new_runs(dev_env: W
         chains = [await executions(client, h.id, h.first_execution_run_id or "") for h in (old, new)]
     assert [(r.status, r.outputs) for r in done] == [("succeeded", {"double": 42}), ("succeeded", {"n": 42})]
     assert (statuses[n1], statuses[n]) == ("drained", "current")
-    slow = [r for r in store.steps(old.id) if r.node_key == "s"]
+    slow = [r for r in store.steps(run_id_of(old)) if r.node_key == "s"]
     assert [(r.status, r.attempt) for r in slow] == [("succeeded", 1)]  # the retired type ran on N-1, once
     for chain, expected in ((chains[0], n1), (chains[1], n)):
         assert len(chain) >= (4 if expected == n1 else 1)
@@ -146,6 +146,6 @@ async def test_after_a_new_abi_is_promoted_old_versions_wait_to_be_published_aga
         ("succeeded", None, {"v": 1}),
     ]
     assert (done[1].error or {}).get("message") == refusal
-    [sub_run] = [c for c, row in store.starts.items() if row.parent_run_id == parent_only.id]
+    [sub_run] = [c for c, row in store.starts.items() if row.parent_run_id == run_id_of(parent_only)]
     assert (store.runs[sub_run].error_code, store.runs[sub_run].error_message) == ("version_unusable", refusal)
     assert len(chain) == 2 and all(placement(h).builds == {n1} for h in chain)  # the run and its sub-flow, on N-1
diff --git a/backend/tests/apps/worker/test_worker_db.py b/backend/tests/apps/worker/test_worker_db.py
index 6027e46..cf4733e 100644
--- a/backend/tests/apps/worker/test_worker_db.py
+++ b/backend/tests/apps/worker/test_worker_db.py
@@ -15,6 +15,7 @@ from dewpoint.apps.worker.store import DbRunStore
 from dewpoint.core.db import tenant_scope
 from dewpoint.core.runs import service as runs
 from dewpoint.engine.runtime.activities import ProjectInput, RunStart, RunSummary, StepRow
+from dewpoint.engine.runtime.ids import run_workflow_id
 from dewpoint.engine.runtime.workflow import RunGraph
 from tests.apps.api.helpers import member_client
 from tests.apps.test_workflow_ops import actor, create, publish
@@ -59,7 +60,8 @@ async def test_a_run_is_projected_and_readable_through_the_api(
             dispatch_sessionmaker, env.client, api_settings,
             tenant_id=ctx.tenant_id, version_id=out.version.id, trigger={"x": 1},
         )  # fmt: skip
-        result = await env.client.get_workflow_handle_for(RunGraph.run, str(run_id)).result()
+        handle = env.client.get_workflow_handle_for(RunGraph.run, run_workflow_id(str(ctx.tenant_id), str(run_id)))
+        result = await handle.result()
     assert (result.status, result.outputs) == ("succeeded", {"items": [10, 20]})
 
     viewer, _ = await member_client(app, owner_sessionmaker, api_settings, ctx.tenant_id, "viewer")
@@ -132,7 +134,7 @@ async def test_a_character_the_database_refuses_never_keeps_its_run_open(
             dispatch_sessionmaker, env.client, api_settings,
             tenant_id=ctx.tenant_id, version_id=out.version.id, trigger={"note": "bad \ud800 note"},
         )  # fmt: skip
-        handle = env.client.get_workflow_handle_for(RunGraph.run, str(run_id))
+        handle = env.client.get_workflow_handle_for(RunGraph.run, run_workflow_id(str(ctx.tenant_id), str(run_id)))
         result = await asyncio.wait_for(handle.result(), 30)
     assert result.status == "failed" and result.error is not None
     assert (result.error["code"], result.error["message"]) == ("workflow_failed", "bad \ufffd note")
@@ -206,7 +208,8 @@ async def test_a_sub_flow_is_projected_as_a_run_of_its_own(
             dispatch_sessionmaker, env.client, api_settings,
             tenant_id=ctx.tenant_id, version_id=out.version.id, trigger={},
         )  # fmt: skip
-        result = await asyncio.wait_for(env.client.get_workflow_handle_for(RunGraph.run, str(run_id)).result(), 60)
+        handle = env.client.get_workflow_handle_for(RunGraph.run, run_workflow_id(str(ctx.tenant_id), str(run_id)))
+        result = await asyncio.wait_for(handle.result(), 60)
     assert (result.status, result.outputs) == ("succeeded", {"double": 42})
     viewer, _ = await member_client(app, owner_sessionmaker, api_settings, ctx.tenant_id, "viewer")
     listed = (await viewer.get(f"/api/v1/t/{ctx.tenant_id}/runs")).json()
diff --git a/backend/tests/engine/cel/test_profile.py b/backend/tests/engine/cel/test_profile.py
index e24ed25..5f67a7e 100644
--- a/backend/tests/engine/cel/test_profile.py
+++ b/backend/tests/engine/cel/test_profile.py
@@ -13,4 +13,4 @@ def test_the_profile_names_the_installed_runtime() -> None:
 def test_local_evaluation_is_a_build_constant_tied_to_the_engine_abi() -> None:
     """Tripwire (spec §5.9 rollout): LOCAL_CEL_PROFILE is part of engine_abi. Changing it without bumping ENGINE_ABI
     would let an open run replay on a build that routes its CEL differently. Update both, then this pair."""
-    assert (ENGINE_ABI, profile.LOCAL_CEL_PROFILE) == (4, profile.CURRENT_CEL_PROFILE)
+    assert (ENGINE_ABI, profile.LOCAL_CEL_PROFILE) == (5, profile.CURRENT_CEL_PROFILE)
diff --git a/backend/tests/engine/replay/record.py b/backend/tests/engine/replay/record.py
index 52083c1..ffd8232 100644
--- a/backend/tests/engine/replay/record.py
+++ b/backend/tests/engine/replay/record.py
@@ -5,7 +5,9 @@ Only scenarios the build's directory lacks are recorded; a recorded history is n
 the command sequence increments ENGINE_ABI (`dewpoint.engine`), which starts a new directory.
 
 A scenario records every execution it ran: `<name>.json` is the run's first execution, and `<name>--<n>.json` each
-other one, in the order they're found: the runs it continued as, then its children's, and theirs."""
+other one, in the order they're found: the runs it continued as, then its children's, and theirs. Each file keeps its
+execution's workflow id beside the events (`workflowId`): the workflows check that it names their tenant and run
+(engine 2b spec §6.1), so a replay needs the one they ran under."""
 
 import asyncio
 import contextlib
@@ -23,6 +25,7 @@ from temporalio.testing import WorkflowEnvironment
 import dewpoint
 from dewpoint.engine.runtime.activities import ENGINE_QUEUE, RunInput, VersionData
 from dewpoint.engine.runtime.build import build_id
+from dewpoint.engine.runtime.ids import run_workflow_id
 from dewpoint.engine.runtime.workflow import RunGraph
 from tests.apps.worker.harness import TENANT, MemoryStore, workers
 from tests.engine.replay.scenarios import scenarios
@@ -94,7 +97,9 @@ async def record() -> list[str]:
             if scenario.unusable:
                 store.unusable.add(version)
             run = RunInput(TENANT, run_id, version, scenario.trigger, **scenario.options)
-            handle = await env.client.start_workflow(RunGraph.run, run, id=run_id, task_queue=ENGINE_QUEUE)
+            handle = await env.client.start_workflow(
+                RunGraph.run, run, id=run_workflow_id(TENANT, run_id), task_queue=ENGINE_QUEUE
+            )
             if scenario.cancel:
                 await delaying(handle)
                 await handle.cancel()
@@ -102,7 +107,7 @@ async def record() -> list[str]:
                 await asyncio.wait_for(handle.result(), 120)
             histories = await executions(env.client, handle.id, handle.first_execution_run_id or "")
             for n, history in enumerate(histories):
-                data = scrub(json.loads(history.to_json()))
+                data = {**scrub(json.loads(history.to_json())), "workflowId": history.workflow_id}
                 path = target / (f"{name}.json" if n == 0 else f"{name}--{n}.json")
                 path.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n")
     return sorted(missing)
diff --git a/backend/tests/engine/replay/test_replay.py b/backend/tests/engine/replay/test_replay.py
index 2558545..d1f966f 100644
--- a/backend/tests/engine/replay/test_replay.py
+++ b/backend/tests/engine/replay/test_replay.py
@@ -4,6 +4,7 @@ scenario ran, its continued runs and its children included. A build that keeps t
 the previous build's histories too. The Replayer needs no server."""
 
 import asyncio
+import json
 import re
 from pathlib import Path
 
@@ -35,5 +36,6 @@ def test_recorded_histories_carry_no_host_data() -> None:
     "path", HISTORIES, ids=lambda p: p.stem if p.parent == build_dir() else f"{p.parent.name}/{p.stem}"
 )
 async def test_a_golden_history_replays(path: Path) -> None:
-    history = WorkflowHistory.from_json(path.stem, await asyncio.to_thread(path.read_text))
+    data = json.loads(await asyncio.to_thread(path.read_text))
+    history = WorkflowHistory.from_json(data.pop("workflowId"), data)  # the id it ran under (see `record`)
     await Replayer(workflows=[RunGraph, LoopBatch]).replay_workflow(history)
diff --git a/backend/tests/engine/runtime/test_ids.py b/backend/tests/engine/runtime/test_ids.py
new file mode 100644
index 0000000..0d0c4d2
--- /dev/null
+++ b/backend/tests/engine/runtime/test_ids.py
@@ -0,0 +1,46 @@
+# SPDX-License-Identifier: Apache-2.0
+"""Workflow ids (engine 2b spec §6.1): the server builds them, and reads back only the tenant and run it put in."""
+
+import uuid
+
+import pytest
+
+from dewpoint.engine.runtime.ids import run_of, run_workflow_id, tenant_of
+
+TENANT = "8f14e45f-ceea-467a-9575-8f6a1b2c3d4e"  # letters too: the server writes uuids in lower case
+RUN = str(uuid.UUID(int=2))
+ROOT = run_workflow_id(TENANT, RUN)
+
+
+def test_a_runs_id_names_its_tenant_and_run() -> None:
+    assert ROOT == f"t:{TENANT}:run:{RUN}"
+    assert (tenant_of(ROOT), run_of(ROOT)) == (TENANT, RUN)
+
+
+def test_a_batch_names_the_run_it_belongs_to() -> None:
+    batch = f"{ROOT}/{uuid.UUID(int=3)}/l:0/batch:1000"
+    assert (tenant_of(batch), run_of(batch)) == (TENANT, RUN)
+
+
+def test_a_schedules_firing_names_its_tenant_and_no_run() -> None:
+    firing = f"t:{TENANT}:sched:{uuid.UUID(int=4)}-2026-09-29T10:00:00Z"
+    assert (tenant_of(firing), run_of(firing)) == (TENANT, None)
+
+
+@pytest.mark.parametrize(
+    "workflow_id",
+    [
+        RUN,  # an id from before 2b-1a
+        f"t:{TENANT}:run:{RUN}\n",  # nothing may follow the id, not even a line end
+        f"t:{TENANT.upper()}:run:{RUN}",
+        f"t:{TENANT}:run:{RUN}x",
+        f"t:{TENANT}:run:{RUN}/",  # a batch's suffix is never empty
+        f"t:{TENANT}:run:{RUN}/a b",
+        f"t:{TENANT}:runs:{RUN}",
+        f"x:{TENANT}:run:{RUN}",
+        f"t:{TENANT}:sched:{RUN}/batch:0",
+        "",
+    ],
+)
+def test_any_other_string_names_nothing(workflow_id: str) -> None:
+    assert (tenant_of(workflow_id), run_of(workflow_id)) == (None, None)
````

- [ ] **Step 2: Run them, and watch them fail**

Run: `cd backend && uv run pytest -q -p no:cacheprovider tests/apps/test_runs.py tests/apps/worker/test_activities.py tests/apps/worker/test_admission_abi.py tests/apps/worker/test_dev_run.py tests/apps/worker/test_gate_task_cost.py tests/apps/worker/test_real_server.py tests/apps/worker/test_run_graph.py tests/apps/worker/test_run_graph_abi.py tests/apps/worker/test_run_graph_cel_requests.py tests/apps/worker/test_run_graph_children.py tests/apps/worker/test_run_graph_continue.py tests/apps/worker/test_run_graph_ids.py tests/apps/worker/test_run_graph_local_cel.py tests/apps/worker/test_run_graph_policies.py tests/apps/worker/test_run_graph_yield.py tests/apps/worker/test_two_builds.py tests/apps/worker/test_worker_db.py tests/engine/cel/test_profile.py tests/engine/replay/test_replay.py tests/engine/runtime/test_ids.py`

Expected: FAIL. `dewpoint.engine.runtime.ids` doesn't exist yet: every file that imports it (the harness included) fails to collect. The replay showed:

````text
E   ModuleNotFoundError: No module named 'dewpoint.engine.runtime.ids'
ERROR tests/apps/test_runs.py
ERROR tests/apps/worker/test_activities.py
ERROR tests/apps/worker/test_admission_abi.py
ERROR tests/apps/worker/test_dev_run.py
ERROR tests/apps/worker/test_gate_task_cost.py
ERROR tests/apps/worker/test_real_server.py
ERROR tests/apps/worker/test_run_graph.py
ERROR tests/apps/worker/test_run_graph_abi.py
ERROR tests/apps/worker/test_run_graph_cel_requests.py
ERROR tests/apps/worker/test_run_graph_children.py
ERROR tests/apps/worker/test_run_graph_continue.py
ERROR tests/apps/worker/test_run_graph_ids.py
ERROR tests/apps/worker/test_run_graph_local_cel.py
...
19 errors in 0.64s
````

- [ ] **Step 3: Implement**

````diff
diff --git a/backend/src/dewpoint/apps/cli/main.py b/backend/src/dewpoint/apps/cli/main.py
index dfd1cc0..c8504f1 100644
--- a/backend/src/dewpoint/apps/cli/main.py
+++ b/backend/src/dewpoint/apps/cli/main.py
@@ -39,6 +39,7 @@ from dewpoint.core.plugins.registry import (
 )
 from dewpoint.engine.cel.profile import CURRENT_CEL_PROFILE
 from dewpoint.engine.runtime.activities import LIVE, SIMULATE, RunResult
+from dewpoint.engine.runtime.ids import run_workflow_id
 from dewpoint.engine.runtime.workflow import RunGraph
 from dewpoint.sdk import ManifestError
 
@@ -437,7 +438,9 @@ async def dev_run_version(
         await engine.dispose()
     if not wait:
         return run_id, None
-    return run_id, await client.get_workflow_handle_for(RunGraph.run, str(run_id)).result()
+    return run_id, await client.get_workflow_handle_for(
+        RunGraph.run, run_workflow_id(str(tenant_id), str(run_id))
+    ).result()
 
 
 @dev_cli.command("run")
diff --git a/backend/src/dewpoint/apps/runs.py b/backend/src/dewpoint/apps/runs.py
index b52465f..e3cd497 100644
--- a/backend/src/dewpoint/apps/runs.py
+++ b/backend/src/dewpoint/apps/runs.py
@@ -36,6 +36,7 @@ from dewpoint.core.plugins import lifecycle
 from dewpoint.core.runs import service as runs
 from dewpoint.core.workflows.service import lock_for_admission, other_abi
 from dewpoint.engine.runtime.activities import ENGINE_QUEUE, LIVE, RunInput
+from dewpoint.engine.runtime.ids import run_workflow_id
 from dewpoint.engine.runtime.workflow import RunGraph
 
 START_FAILED = "start_failed"
@@ -184,7 +185,7 @@ async def _start(client: Client, start: RunInput, run_id: uuid.UUID) -> None:
             await client.start_workflow(
                 RunGraph.run,
                 start,
-                id=str(run_id),
+                id=run_workflow_id(start.tenant_id, str(run_id)),
                 task_queue=ENGINE_QUEUE,
                 id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
             )
diff --git a/backend/src/dewpoint/apps/worker/activities.py b/backend/src/dewpoint/apps/worker/activities.py
index e691ff2..6bd4401 100644
--- a/backend/src/dewpoint/apps/worker/activities.py
+++ b/backend/src/dewpoint/apps/worker/activities.py
@@ -54,7 +54,8 @@ from dewpoint.engine.runtime.activities import (
     VersionData,
     step_activity,
 )
-from dewpoint.engine.runtime.execution import VERSION_UNUSABLE
+from dewpoint.engine.runtime.execution import INTERNAL_ERROR, VERSION_UNUSABLE
+from dewpoint.engine.runtime.ids import tenant_of
 from dewpoint.engine.runtime.projection import location
 from dewpoint.sdk import (
     FatalError,
@@ -160,6 +161,16 @@ async def _call(node: type[Node], step: StepInput, schema: Mapping[str, Any]) ->
         raise _StepFailed(UNEXPECTED_ERROR, message, retryable=True) from None
 
 
+def _same_tenant(tenant_id: str) -> None:
+    """The input's tenant is the one this activity's server-built workflow id names (engine 2b spec §6.1): the store
+    scopes every read and write by it. Only a bug, or a workflow started outside Dewpoint, gets here; the failure isn't
+    the node's (`MAPPED`), so `RunGraph` doesn't take it for one."""
+    if tenant_of(activity.info().workflow_id or "") != tenant_id:
+        raise ApplicationError(
+            "This activity's input doesn't name its workflow's tenant.", type=INTERNAL_ERROR, non_retryable=True
+        )
+
+
 def step_activity_for(node: type[Node]) -> Callable[[StepInput], Awaitable[StepResult]]:
     ref = f"{node.type}@{node.version}"
     config_schema = node.Config.model_json_schema(mode="validation")
@@ -184,6 +195,7 @@ def step_activity_for(node: type[Node]) -> Callable[[StepInput], Awaitable[StepR
 
     @activity.defn(name=step_activity(ref))
     async def run_step(step: StepInput) -> StepResult:
+        _same_tenant(step.tenant_id)
         try:
             result, outcome = await _call(node, step, config_schema)
         except _StepFailed as f:
@@ -211,6 +223,7 @@ def engine_activities(store: RunStore, plugins: Iterable[Plugin], *, abi: int =
 
     @activity.defn(name=LOAD_VERSION)
     async def load_version(data: LoadVersionInput) -> VersionData:
+        _same_tenant(data.tenant_id)
         version = await store.version(data.tenant_id, data.version_id)
         if version.engine_abi != abi:  # the run fails `version_unusable`, with this message
             remedy = (
@@ -228,6 +241,7 @@ def engine_activities(store: RunStore, plugins: Iterable[Plugin], *, abi: int =
 
     @activity.defn(name=PROJECT)
     async def project(data: ProjectInput) -> None:
+        _same_tenant(data.tenant_id)
         await store.project(data)
 
     steps = [step_activity_for(node) for plugin in plugins for node in plugin.nodes if node.kind == NodeKind.ACTION]
diff --git a/backend/src/dewpoint/engine/__init__.py b/backend/src/dewpoint/engine/__init__.py
index 9446e64..794b227 100644
--- a/backend/src/dewpoint/engine/__init__.py
+++ b/backend/src/dewpoint/engine/__init__.py
@@ -4,5 +4,6 @@
 # The one engine ABI (spec §7): publishing stamps and hashes a version with it, and the build id names it. Bump it on
 # any change that can alter a run's command sequence. 2: 2a-3b's loop batches, sub-flows, the failure handler and
 # continue-as-new. 3: 2a-3c's local CEL. 4: issue #15's cel.evaluate requests, cut by their bytes, refused when one
-# binding set can't fit, and paced per workflow task.
-ENGINE_ABI = 4
+# binding set can't fit, and paced per workflow task. 5: 2b-1a's workflow ids, built from the tenant and the run
+# (sub-flows' and failure handlers' too).
+ENGINE_ABI = 5
diff --git a/backend/src/dewpoint/engine/runtime/execution.py b/backend/src/dewpoint/engine/runtime/execution.py
index 224f191..90e0850 100644
--- a/backend/src/dewpoint/engine/runtime/execution.py
+++ b/backend/src/dewpoint/engine/runtime/execution.py
@@ -59,6 +59,7 @@ with workflow.unsafe.imports_passed_through():
         step_activity,
     )
     from dewpoint.engine.runtime.budget import LOCAL, Need
+    from dewpoint.engine.runtime.ids import run_workflow_id
     from dewpoint.engine.runtime.program import Program, Step
     from dewpoint.engine.runtime.projection import (
         Secrets,
@@ -839,7 +840,8 @@ class Execution:
         if version is None or self.depth >= MAX_DEPTH:
             reason = "no pinned version" if version is None else f"more than {MAX_DEPTH} sub-flows deep"
             return _Effect(failure=Failure(VERSION_UNUSABLE, f"`{step.key}` can't run its sub-flow: {reason}."))
-        child = str(workflow.uuid4())
+        child_run = str(workflow.uuid4())
+        child = run_workflow_id(self.tenant_id, child_run)  # its workflow id, and its key in this budget
         grant = self.sched.budget.start_child(child, SUBFLOW_GRANT)
         parent = Parent(
             workflow_id=workflow.info().workflow_id,
@@ -854,7 +856,7 @@ class Execution:
         )
         run = RunInput(
             self.tenant_id,
-            child,
+            child_run,
             version,
             start.input,
             self.mode,
@@ -902,7 +904,7 @@ class Execution:
         references (spec §4.5). Its parent writes it, unless it has one, with its whole grant as counted here: its
         first grant and every one it asked for since, which the parent debits as it settles the child. It writes the
         row too, in case the child was ended before its own: a start written later changes nothing."""
-        whole = self.sched.budget.reserved.get(run.run_id, 0)  # read before the child is settled
+        whole = self.sched.budget.reserved.get(run_workflow_id(run.tenant_id, run.run_id), 0)  # before it's settled
         end = RunSummary(run.run_id, "failed", workflow.now().isoformat(), failure.code, failure.message, whole, True)
         await self._shielded([], end, RunStart.of(run, started_at))
 
@@ -926,7 +928,9 @@ class Execution:
         loop = self.sched.loops[b.loop]
         # from the input, not the workflow id: a replay of this history sees the same id (the run id names the logical
         # run, the loop step and its scope name the loop, the start names the batch)
-        child = f"{self.run_id}/{step.id}/{iteration_key(b.loop.scope)}/batch:{b.start}"
+        child = (
+            f"{run_workflow_id(self.tenant_id, self.run_id)}/{step.id}/{iteration_key(b.loop.scope)}/batch:{b.start}"
+        )
         grant = self.sched.budget.start_child(child, len(b.items))
         parent = Parent(
             workflow_id=workflow.info().workflow_id,
diff --git a/backend/src/dewpoint/engine/runtime/ids.py b/backend/src/dewpoint/engine/runtime/ids.py
new file mode 100644
index 0000000..d35ebe1
--- /dev/null
+++ b/backend/src/dewpoint/engine/runtime/ids.py
@@ -0,0 +1,27 @@
+# SPDX-License-Identifier: Apache-2.0
+"""Workflow ids, always built by the server (engine 2b spec §6.1). Every run — root, sub-flow, failure handler — is
+`t:<tenant>:run:<run_id>`; a batch appends `/<step>/<iteration>/batch:<start>` to its run's; a schedule (2b-3) is
+`t:<tenant>:sched:<schedule_id>`, to which Temporal appends each firing's time. The codec reads a payload's tenant
+from its workflow id with `tenant_of`, and an id supplied from outside is never parsed for anything else."""
+
+import re
+
+_UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
+_RUN = re.compile(rf"t:({_UUID}):run:({_UUID})(?:/[^\s]+)?")  # always matched whole (`fullmatch`)
+_SCHEDULE = re.compile(rf"t:({_UUID}):sched:({_UUID})(?:-[^\s/]+)?")
+
+
+def run_workflow_id(tenant_id: str, run_id: str) -> str:
+    return f"t:{tenant_id}:run:{run_id}"
+
+
+def tenant_of(workflow_id: str) -> str | None:
+    """The tenant a server-built workflow id names, or None for any other string: nothing is inferred from it."""
+    m = _RUN.fullmatch(workflow_id) or _SCHEDULE.fullmatch(workflow_id)
+    return m.group(1) if m else None
+
+
+def run_of(workflow_id: str) -> str | None:
+    """The run a run's (or a batch's) workflow id names, or None."""
+    m = _RUN.fullmatch(workflow_id)
+    return m.group(2) if m else None
diff --git a/backend/src/dewpoint/engine/runtime/workflow.py b/backend/src/dewpoint/engine/runtime/workflow.py
index 75bf9f1..d0004e7 100644
--- a/backend/src/dewpoint/engine/runtime/workflow.py
+++ b/backend/src/dewpoint/engine/runtime/workflow.py
@@ -50,6 +50,7 @@ with workflow.unsafe.imports_passed_through():
         _unloadable,
         child_options,
     )
+    from dewpoint.engine.runtime.ids import run_of, run_workflow_id, tenant_of
     from dewpoint.engine.runtime.program import Program, compile_program
     from dewpoint.engine.runtime.projection import mask
     from dewpoint.engine.runtime.scheduler import (
@@ -65,6 +66,17 @@ with workflow.unsafe.imports_passed_through():
 HANDLED = ("failed", DEADLINE_EXCEEDED)  # the ends that run a failure handler (a cancel is no failure)
 
 
+def _same_run(tenant_id: str, run_id: str) -> None:
+    """The start's tenant and run are the ones its server-built workflow id names (engine 2b spec §6.1). Every store
+    write is scoped by the start's tenant, so a start that disagrees is refused before anything runs: only a bug, or a
+    start built outside Dewpoint, gets here."""
+    workflow_id = workflow.info().workflow_id
+    if tenant_of(workflow_id) != tenant_id or run_of(workflow_id) != run_id:
+        raise ApplicationError(
+            "This run's workflow id doesn't name its tenant and run.", type=INTERNAL_ERROR, non_retryable=True
+        )
+
+
 @workflow.defn(name="RunGraph", versioning_behavior=VersioningBehavior.PINNED)  # spec §7
 class RunGraph(Execution):
     @workflow.run
@@ -85,6 +97,7 @@ class RunGraph(Execution):
         non-terminal until the handler has ended, so something non-terminal always holds the handler's closure,
         and with it the CEL profiles it pins (spec §4.5). The end is recorded once, counting the handler's
         iterations."""
+        _same_run(start.tenant_id, start.run_id)
         snapshot = start.snapshot
         unreadable = snapshot is not None and snapshot.get("snapshot_format") != SNAPSHOT_FORMAT
         if unreadable:
@@ -281,7 +294,8 @@ class RunGraph(Execution):
         This run's end is already decided: a cancel meanwhile comes too late to change it. It cancels the handler,
         which reports back first, so its iterations still count."""
         version, workflow_id = pin
-        child = str(workflow.uuid4())
+        child_run = str(workflow.uuid4())
+        child = run_workflow_id(self.tenant_id, child_run)  # its workflow id, and its key in this budget
         grant = self.sched.budget.start_child(child, SUBFLOW_GRANT)
         parent = Parent(
             workflow_id=workflow.info().workflow_id,
@@ -302,7 +316,7 @@ class RunGraph(Execution):
         }
         run = RunInput(
             self.tenant_id,
-            child,
+            child_run,
             version,
             trigger,
             self.mode,
@@ -349,6 +363,7 @@ class LoopBatch(Execution):
         they would inline, with the loop's concurrency and error policy, over read-only copies of the scopes around
         the loop; their rows go into the parent's run. It returns what they collected, the failures, and how many
         iterations it used. A fail or stop node, or the deadline, ends the run: the batch reports it as `end`."""
+        _same_run(start.tenant_id, start.run_id)
         snapshot = start.snapshot
         if snapshot is not None and snapshot.get("snapshot_format") != SNAPSHOT_FORMAT:  # it can't carry on: fail
             message = "This build can't read the batch's continue-as-new snapshot."  # its loop (decision 4)
````

- [ ] **Step 4: Record the abi5 golden histories**

Run: `cd backend && uv run python -m tests.engine.replay.record`
Expected: `dewpoint-0.1.0+abi5: recorded batches, branches, cancelled, continue_as_new, deadline, drain, errors,
evaluator, failed, failure_handler, grants, local_cel, loops, simulate, stop, subflows, variables_and_timers,
version_unusable`. The version-unusable scenario logs a `ProgramError` traceback: that's the scenario. The files go
into `backend/tests/engine/replay/dewpoint-0.1.0+abi5/`. Their count varies from recording to recording (continue-as-new
falls where a race puts it: #17's ruling); every one must replay.

- [ ] **Step 5: Run the tests again**

Run: `cd backend && uv run pytest -q -p no:cacheprovider tests/apps/test_runs.py tests/apps/worker/test_activities.py tests/apps/worker/test_admission_abi.py tests/apps/worker/test_dev_run.py tests/apps/worker/test_gate_task_cost.py tests/apps/worker/test_real_server.py tests/apps/worker/test_run_graph.py tests/apps/worker/test_run_graph_abi.py tests/apps/worker/test_run_graph_cel_requests.py tests/apps/worker/test_run_graph_children.py tests/apps/worker/test_run_graph_continue.py tests/apps/worker/test_run_graph_ids.py tests/apps/worker/test_run_graph_local_cel.py tests/apps/worker/test_run_graph_policies.py tests/apps/worker/test_run_graph_yield.py tests/apps/worker/test_two_builds.py tests/apps/worker/test_worker_db.py tests/engine/cel/test_profile.py tests/engine/replay/test_replay.py tests/engine/runtime/test_ids.py`

Expected (the replay):

````text
235 passed in 182.56s (0:03:02)
````

- [ ] **Step 6: The whole suite, lint, types and layers**

Run: `cd backend && uv run pytest -q -p no:cacheprovider`, then `uv run ruff check --no-cache src tests migrations`, `uv run ruff format --no-cache --check src tests migrations`, `uv run mypy src` and `uv run lint-imports`.

Expected: 1,129 passed, 8 skipped; ruff and its formatter clean; mypy: no issues; import-linter: 10 contracts kept.

- [ ] **Step 7: Commit**

```bash
git add -A backend deploy docs && git commit -m "feat(engine): server-built workflow ids, their cross-checks, ENGINE_ABI 5 (2b-1a)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: `TenantCodec`, its key cache, and the keyring's read-only keys

**Spec:** §6.2–6.3.

**Files:**
- Create: `backend/src/dewpoint/apps/codec.py`
- Create: `backend/tests/apps/test_codec.py`
- Create: `backend/tests/apps/test_codec_keys.py`
- Create: `backend/tests/support/keys.py`
- Modify: `backend/src/dewpoint/core/crypto/keyring.py`
- Modify: `backend/tests/core/crypto/test_keyring.py`

**Interfaces:**
- Produces:
  - `dewpoint.apps.codec`: `ENCODING`, `TENANT`, `KEY_VERSION`, `NONCE_BYTES`, `CodecRefusedError`;
  - `KeySource` (Protocol: `async active(tenant_id) -> (int, AESGCM)`, `async get(tenant_id, version) -> AESGCM`);
  - `TenantCodec(keys, tenant_id=None)` (a `PayloadCodec` with `with_context`), and `data_converter(keys) ->
    DataConverter`;
  - `KeyringKeys(sessionmaker, keyring, *, size=1024, ttl_s=300.0, clock=time.monotonic)`;
  - `CODEC_OVERHEAD = 256`, here until Task 9 moves it to `engine.runtime.size`;
  - `Keyring.ensure_key(s, tenant_id) -> int`, `Keyring.read_dek(s, tenant_id, version=None) -> (int, bytes)`,
    `NoKeyError`;
  - `tests.support.keys.FixtureKeys(version=1, missing=set())`.
- Consumes: Task 3's `tenant_of`.

`TenantCodec` encrypts each payload with AES-256-GCM under the data key of the tenant its serialization
context's workflow id names.
- The payload's metadata records the encoding (`binary/dewpoint-tenant-v1`), the tenant and the key version, which
  are also bound into the associated data, `dewpoint|<tenant>|temporal|<version>`.
- Without a context that names a tenant, it refuses to encode or to decode. It refuses a payload of another tenant,
  a plain one, one without a key version, and one whose tag doesn't verify. All of these raise
  `CodecRefusedError`, with fixed messages.
- It checks nothing of the payload's content: the tenant cross-checks are Task 3's.

`KeyringKeys` reads keys through `Keyring.read_dek`: read-only, under the tenant's RLS scope, and cached in the
process for at most 1,024 keys and 300 s. A missing key is never cached. `Keyring.ensure_key` is what tenant
creation calls (Task 5). `FixtureKeys` derives test keys from the tenant and version, so a recorded history decrypts
on any later replay.

- [ ] **Step 1: Write the tests**

````diff
diff --git a/backend/tests/apps/test_codec.py b/backend/tests/apps/test_codec.py
new file mode 100644
index 0000000..d17a841
--- /dev/null
+++ b/backend/tests/apps/test_codec.py
@@ -0,0 +1,126 @@
+# SPDX-License-Identifier: Apache-2.0
+"""`TenantCodec` (engine 2b spec §6.2, §12 "codec fail-closed"): a payload is encrypted with the key of the tenant its
+workflow id names, and nothing else chooses the key."""
+
+import uuid
+
+import pytest
+from temporalio.api.common.v1 import Payload
+from temporalio.converter import (
+    ActivitySerializationContext,
+    DataConverter,
+    WorkflowSerializationContext,
+)
+
+from dewpoint.apps.codec import (
+    CODEC_OVERHEAD,
+    ENCODING,
+    KEY_VERSION,
+    TENANT,
+    CodecRefusedError,
+    TenantCodec,
+)
+from dewpoint.engine.runtime.ids import run_workflow_id
+from tests.support.keys import FixtureKeys
+
+A, B = str(uuid.UUID(int=1)), str(uuid.UUID(int=2))
+RUN = str(uuid.UUID(int=3))
+
+
+def workflow(tenant_id: str, suffix: str = "") -> WorkflowSerializationContext:
+    return WorkflowSerializationContext(namespace="default", workflow_id=run_workflow_id(tenant_id, RUN) + suffix)
+
+
+def activity(workflow_id: str | None) -> ActivitySerializationContext:
+    return ActivitySerializationContext(
+        namespace="default",
+        activity_id="1",
+        activity_type="dewpoint.project",
+        activity_task_queue="dewpoint-engine",
+        workflow_id=workflow_id,
+        workflow_type="RunGraph",
+        is_local=False,
+    )
+
+
+def payload(value: object) -> Payload:
+    [p] = DataConverter.default.payload_converter.to_payloads([value])
+    return p
+
+
+def codec(keys: FixtureKeys | None = None) -> TenantCodec:
+    return TenantCodec(keys or FixtureKeys())
+
+
+async def test_a_payload_round_trips_under_its_tenants_key() -> None:
+    plain = payload({"tenant_id": A, "x": "secret"})
+    for context in (workflow(A), workflow(A, "/s/l:0/batch:0"), activity(run_workflow_id(A, RUN))):
+        c = codec().with_context(context)
+        [sealed] = await c.encode([plain])
+        assert sealed.metadata["encoding"] == ENCODING
+        assert (sealed.metadata[TENANT], sealed.metadata[KEY_VERSION]) == (A.encode(), b"1")
+        assert b"secret" not in sealed.SerializeToString()
+        assert await c.decode([sealed]) == [plain]
+
+
+@pytest.mark.parametrize(
+    "context",
+    [
+        None,
+        WorkflowSerializationContext(namespace="default", workflow_id=RUN),  # an id from before 2b-1a
+        WorkflowSerializationContext(namespace="default", workflow_id=f"t:{A}:run:{RUN}\n"),
+        activity(None),  # an activity no workflow started
+    ],
+)
+async def test_without_a_tenant_it_refuses_both_ways(context: WorkflowSerializationContext | None) -> None:
+    sealed = (await codec().with_context(workflow(A)).encode([payload(1)]))[0]
+    c = codec() if context is None else codec().with_context(context)
+    with pytest.raises(CodecRefusedError, match="No tenant"):
+        await c.encode([payload(1)])
+    with pytest.raises(CodecRefusedError, match="No tenant"):
+        await c.decode([sealed])
+
+
+async def test_another_tenants_payload_is_refused_whatever_its_metadata_says() -> None:
+    [sealed] = await codec().with_context(workflow(A)).encode([payload(1)])
+    with pytest.raises(CodecRefusedError, match="another tenant"):
+        await codec().with_context(workflow(B)).decode([sealed])
+    relabeled = Payload(metadata={**sealed.metadata, TENANT: B.encode()}, data=sealed.data)
+    with pytest.raises(CodecRefusedError, match="doesn't decrypt"):  # the tenant is bound into the associated data
+        await codec().with_context(workflow(B)).decode([relabeled])
+
+
+async def test_a_plaintext_or_tampered_payload_is_refused() -> None:
+    c = codec().with_context(workflow(A))
+    with pytest.raises(CodecRefusedError, match="isn't encrypted"):
+        await c.decode([payload(1)])
+    [sealed] = await c.encode([payload(1)])
+    flipped = Payload(metadata=dict(sealed.metadata), data=sealed.data[:-1] + bytes([sealed.data[-1] ^ 1]))
+    with pytest.raises(CodecRefusedError, match="doesn't decrypt"):
+        await c.decode([flipped])
+    for version in (b"", b"x", b"2"):  # no version, a garbled one, another (its key doesn't open it)
+        other = Payload(metadata={**sealed.metadata, KEY_VERSION: version}, data=sealed.data)
+        with pytest.raises(CodecRefusedError):
+            await c.decode([other])
+
+
+async def test_after_a_rotation_older_payloads_still_decode() -> None:
+    [old] = await codec(FixtureKeys(version=1)).with_context(workflow(A)).encode([payload("before")])
+    rotated = codec(FixtureKeys(version=2)).with_context(workflow(A))
+    [new] = await rotated.encode([payload("after")])
+    assert (old.metadata[KEY_VERSION], new.metadata[KEY_VERSION]) == (b"1", b"2")
+    assert await rotated.decode([old, new]) == [payload("before"), payload("after")]
+
+
+async def test_a_tenant_without_a_key_is_refused() -> None:
+    c = codec(FixtureKeys(missing={A})).with_context(workflow(A))
+    with pytest.raises(LookupError):
+        await c.encode([payload(1)])
+
+
+@pytest.mark.parametrize("size", [0, 1, 1_000, 65_536, 1_835_008, 2_097_152])
+async def test_the_overhead_bound_covers_every_size(size: int) -> None:
+    """Spec §5.2: the guard adds CODEC_OVERHEAD to a payload's JSON bytes; Temporal measures the encoded payload."""
+    plain = payload("x" * size)  # the guard measures the JSON with the SDK's own converter, as this does
+    [sealed] = await codec(FixtureKeys(version=999_999_999)).with_context(workflow(A)).encode([plain])
+    assert sealed.ByteSize() <= len(plain.data) + CODEC_OVERHEAD
diff --git a/backend/tests/apps/test_codec_keys.py b/backend/tests/apps/test_codec_keys.py
new file mode 100644
index 0000000..a30d8ba
--- /dev/null
+++ b/backend/tests/apps/test_codec_keys.py
@@ -0,0 +1,89 @@
+# SPDX-License-Identifier: Apache-2.0
+"""The codec's keys from the keyring (engine 2b spec §6.3): read-only, as the worker's role, under the tenant's RLS
+scope; cached in the process, bounded in size and time; a missing key is never cached."""
+
+import os
+import uuid
+from typing import Any
+
+import pytest
+from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
+
+from dewpoint.apps.codec import KeyringKeys, TenantCodec
+from dewpoint.core.crypto.kek import Kek, KekSet
+from dewpoint.core.crypto.keyring import Keyring, NoKeyError
+from dewpoint.core.db import tenant_scope
+from tests.apps.test_codec import payload, workflow
+
+KEYRING = Keyring(KekSet(Kek("k1", os.urandom(32))))
+
+
+class Counted:
+    """A sessionmaker that counts the sessions it opens: each is a read of the keyring."""
+
+    def __init__(self, inner: async_sessionmaker[AsyncSession]) -> None:
+        self.inner, self.opened = inner, 0
+
+    def __call__(self) -> Any:
+        self.opened += 1
+        return self.inner()
+
+
+async def with_key(owner_sessionmaker: async_sessionmaker[AsyncSession], tenant: uuid.UUID) -> int:
+    async with owner_sessionmaker() as s, s.begin():
+        return await KEYRING.ensure_key(s, tenant)
+
+
+async def test_the_worker_reads_a_tenants_key_and_the_codec_uses_it(owner_sessionmaker, worker_sessionmaker) -> None:
+    tenant = uuid.uuid4()
+    await with_key(owner_sessionmaker, tenant)
+    keys = KeyringKeys(worker_sessionmaker, KEYRING)
+    c = TenantCodec(keys).with_context(workflow(str(tenant)))
+    assert await c.decode(await c.encode([payload({"x": 1})])) == [payload({"x": 1})]
+
+
+async def test_a_key_is_read_once_until_its_time_is_up(owner_sessionmaker, worker_sessionmaker) -> None:
+    tenant, now = uuid.uuid4(), [0.0]
+    await with_key(owner_sessionmaker, tenant)
+    counted = Counted(worker_sessionmaker)
+    keys = KeyringKeys(counted, KEYRING, ttl_s=60, clock=lambda: now[0])  # type: ignore[arg-type]
+    first = await keys.active(str(tenant))
+    assert (await keys.active(str(tenant)), await keys.get(str(tenant), 1)) == (first, first[1])
+    assert counted.opened == 1
+    async with owner_sessionmaker() as s, s.begin():
+        assert await KEYRING.rotate(s, tenant) == 2
+    assert (await keys.active(str(tenant)))[0] == 1  # still cached: a rotation takes effect within the ttl
+    now[0] = 61
+    assert (await keys.active(str(tenant)))[0] == 2
+    assert counted.opened == 2
+
+
+async def test_a_missing_key_is_not_cached(owner_sessionmaker, worker_sessionmaker) -> None:
+    tenant = uuid.uuid4()
+    keys = KeyringKeys(worker_sessionmaker, KEYRING)
+    with pytest.raises(NoKeyError):
+        await keys.active(str(tenant))
+    await with_key(owner_sessionmaker, tenant)
+    assert (await keys.active(str(tenant)))[0] == 1
+
+
+async def test_the_cache_holds_at_most_its_size(owner_sessionmaker, worker_sessionmaker) -> None:
+    tenants = [uuid.uuid4() for _ in range(3)]
+    for t in tenants:
+        await with_key(owner_sessionmaker, t)
+    counted = Counted(worker_sessionmaker)
+    keys = KeyringKeys(counted, KEYRING, size=4)  # type: ignore[arg-type]
+    for t in tenants:  # each read caches the active key twice: as active, and by its version
+        await keys.active(str(t))
+    await keys.active(str(tenants[0]))  # evicted: read again
+    assert counted.opened == 4
+
+
+async def test_another_tenants_key_is_invisible_to_the_worker(owner_sessionmaker, worker_sessionmaker) -> None:
+    """RLS: the read is scoped to the tenant it asks for, so a scope bug can't hand the codec another tenant's key."""
+    a, b = uuid.uuid4(), uuid.uuid4()
+    await with_key(owner_sessionmaker, a)
+    async with worker_sessionmaker() as s, s.begin():
+        await tenant_scope(s, b)
+        with pytest.raises(NoKeyError):
+            await KEYRING.read_dek(s, a)
diff --git a/backend/tests/core/crypto/test_keyring.py b/backend/tests/core/crypto/test_keyring.py
index 3b4eb4a..23b3b0c 100644
--- a/backend/tests/core/crypto/test_keyring.py
+++ b/backend/tests/core/crypto/test_keyring.py
@@ -6,7 +6,7 @@ import pytest
 from cryptography.exceptions import InvalidTag
 
 from dewpoint.core.crypto.kek import Kek, KekSet, UnknownKekError
-from dewpoint.core.crypto.keyring import Keyring
+from dewpoint.core.crypto.keyring import Keyring, NoKeyError
 
 
 def _kek(kid: str = "k1") -> Kek:
@@ -61,3 +61,22 @@ async def test_kek_rollout_phases(owner_sessionmaker) -> None:
         # phase D: the old KEK can be removed from configuration
         assert await only_new.decrypt(s, tenant_id=t1, purpose="p", context="x", blob=b1) == b"one"
         assert await only_new.decrypt(s, tenant_id=t2, purpose="p", context="x", blob=b2) == b"two"
+
+
+async def test_reading_a_data_key_never_creates_one(owner_sessionmaker) -> None:
+    """Engine 2b spec §6.3: the codec reads keys; only tenant creation (`ensure_key`) makes one."""
+    kr, t = Keyring(KekSet(_kek())), uuid.uuid4()
+    async with owner_sessionmaker() as s, s.begin():
+        with pytest.raises(NoKeyError):
+            await kr.read_dek(s, t)
+        with pytest.raises(NoKeyError):
+            await kr.read_dek(s, t)  # still none: the failed read created nothing
+        assert await kr.ensure_key(s, t) == 1
+        assert await kr.ensure_key(s, t) == 1  # once
+        first = await kr.read_dek(s, t)
+        assert first[0] == 1 and len(first[1]) == 32
+        assert await kr.rotate(s, t) == 2
+        assert (await kr.read_dek(s, t))[0] == 2
+        assert await kr.read_dek(s, t, 1) == first  # an older version stays readable
+        with pytest.raises(NoKeyError):
+            await kr.read_dek(s, t, 3)
diff --git a/backend/tests/support/keys.py b/backend/tests/support/keys.py
new file mode 100644
index 0000000..8cf46fd
--- /dev/null
+++ b/backend/tests/support/keys.py
@@ -0,0 +1,24 @@
+# SPDX-License-Identifier: Apache-2.0
+"""Fixture data keys for tests and golden histories: derived from the tenant and version, so a history recorded
+today decrypts on any later replay. Never a real key: only tests import this module."""
+
+import hashlib
+from dataclasses import dataclass, field
+
+from cryptography.hazmat.primitives.ciphers.aead import AESGCM
+
+
+@dataclass
+class FixtureKeys:
+    """A `KeySource` (`dewpoint.apps.codec`). `version`: the active one; `missing`: tenants without a key."""
+
+    version: int = 1
+    missing: set[str] = field(default_factory=set)
+
+    async def active(self, tenant_id: str) -> tuple[int, AESGCM]:
+        return self.version, await self.get(tenant_id, self.version)
+
+    async def get(self, tenant_id: str, version: int) -> AESGCM:
+        if tenant_id in self.missing:
+            raise LookupError(f"no key for tenant {tenant_id}")
+        return AESGCM(hashlib.sha256(f"dewpoint-fixture-key|{tenant_id}|{version}".encode()).digest())
````

- [ ] **Step 2: Run them, and watch them fail**

Run: `cd backend && uv run pytest -q -p no:cacheprovider tests/apps/test_codec.py tests/apps/test_codec_keys.py tests/core/crypto/test_keyring.py`

Expected: FAIL. The codec module and the keyring's new methods don't exist yet. The replay showed:

````text
E   ModuleNotFoundError: No module named 'dewpoint.apps.codec'
E   ImportError: cannot import name 'NoKeyError' from 'dewpoint.core.crypto.keyring'
ERROR tests/apps/test_codec.py
ERROR tests/apps/test_codec_keys.py
ERROR tests/core/crypto/test_keyring.py
!!!!!!!!!!!!!!!!!!! Interrupted: 3 errors during collection !!!!!!!!!!!!!!!!!!!!
3 errors in 0.35s
````

- [ ] **Step 3: Implement**

````diff
diff --git a/backend/src/dewpoint/apps/codec.py b/backend/src/dewpoint/apps/codec.py
new file mode 100644
index 0000000..4d5c62c
--- /dev/null
+++ b/backend/src/dewpoint/apps/codec.py
@@ -0,0 +1,159 @@
+# SPDX-License-Identifier: Apache-2.0
+"""Temporal payloads, encrypted with their tenant's data key (engine 2b spec §6.2–6.3).
+
+The tenant comes only from the serialization context: the workflow id Dewpoint built (`engine.runtime.ids`). Without
+a context whose workflow id names a tenant, `TenantCodec` refuses to encode or decode: there's no default key, and
+a payload's metadata is never trusted to choose one. Every client and worker uses `data_converter`, which also
+encrypts failure messages and stack traces (`DefaultFailureConverterWithEncodedAttributes`)."""
+
+import dataclasses
+import os
+import time
+import uuid
+from collections import OrderedDict
+from collections.abc import Callable, Sequence
+from typing import Protocol
+
+from cryptography.exceptions import InvalidTag
+from cryptography.hazmat.primitives.ciphers.aead import AESGCM
+from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
+from temporalio.api.common.v1 import Payload
+from temporalio.converter import (
+    ActivitySerializationContext,
+    DataConverter,
+    DefaultFailureConverterWithEncodedAttributes,
+    PayloadCodec,
+    SerializationContext,
+    WithSerializationContext,
+    WorkflowSerializationContext,
+)
+
+from dewpoint.core.crypto.keyring import Keyring
+from dewpoint.core.db import tenant_scope
+from dewpoint.engine.runtime.ids import tenant_of
+
+ENCODING = b"binary/dewpoint-tenant-v1"
+TENANT = "dewpoint-tenant"
+KEY_VERSION = "dewpoint-key-version"
+NONCE_BYTES = 12
+# What encoding adds to a payload's serialized size, at most: the metadata above, the nonce, the tag and the inner
+# payload's own framing. The outgoing-payload guard adds it to a payload's JSON bytes (spec §5.2); a test proves it.
+CODEC_OVERHEAD = 256
+
+
+class CodecRefusedError(Exception):
+    """A payload the codec won't encode or decode. The messages are fixed: they never quote a payload."""
+
+
+class KeySource(Protocol):
+    """A tenant's data keys, by version. Read-only: the codec never creates a key (a tenant gets one when it's
+    created)."""
+
+    async def active(self, tenant_id: str) -> tuple[int, AESGCM]: ...
+
+    async def get(self, tenant_id: str, version: int) -> AESGCM: ...
+
+
+def _aad(tenant_id: str, version: int) -> bytes:
+    return f"dewpoint|{tenant_id}|temporal|{version}".encode()  # the keyring's layout: scope, purpose, context
+
+
+class TenantCodec(PayloadCodec, WithSerializationContext):
+    def __init__(self, keys: KeySource, tenant_id: str | None = None) -> None:
+        self._keys, self._tenant_id = keys, tenant_id
+
+    def with_context(self, context: SerializationContext) -> "TenantCodec":
+        workflow_id = (
+            context.workflow_id
+            if isinstance(context, WorkflowSerializationContext | ActivitySerializationContext)
+            else None
+        )
+        return TenantCodec(self._keys, tenant_of(workflow_id) if workflow_id else None)
+
+    def _tenant(self) -> str:
+        if self._tenant_id is None:
+            raise CodecRefusedError("No tenant: the payload's workflow id doesn't name one.")
+        return self._tenant_id
+
+    async def encode(self, payloads: Sequence[Payload]) -> list[Payload]:
+        tenant = self._tenant()
+        version, key = await self._keys.active(tenant)
+        out = []
+        for p in payloads:
+            nonce = os.urandom(NONCE_BYTES)
+            metadata = {"encoding": ENCODING, TENANT: tenant.encode(), KEY_VERSION: str(version).encode()}
+            data = nonce + key.encrypt(nonce, p.SerializeToString(), _aad(tenant, version))
+            out.append(Payload(metadata=metadata, data=data))
+        return out
+
+    async def decode(self, payloads: Sequence[Payload]) -> list[Payload]:
+        tenant = self._tenant()
+        out = []
+        for p in payloads:
+            if p.metadata.get("encoding") != ENCODING:
+                raise CodecRefusedError("A payload that isn't encrypted for a tenant.")
+            if p.metadata.get(TENANT) != tenant.encode():
+                raise CodecRefusedError("A payload of another tenant than its workflow id names.")
+            raw_version = p.metadata.get(KEY_VERSION, b"")
+            if not raw_version.isdigit() or len(raw_version) > 9:
+                raise CodecRefusedError("A payload without a key version.")
+            version = int(raw_version)
+            key = await self._keys.get(tenant, version)
+            try:
+                plain = key.decrypt(p.data[:NONCE_BYTES], p.data[NONCE_BYTES:], _aad(tenant, version))
+            except InvalidTag:
+                raise CodecRefusedError("A payload that doesn't decrypt under its tenant's key.") from None
+            out.append(Payload.FromString(plain))
+        return out
+
+
+def data_converter(keys: KeySource) -> DataConverter:
+    """The one converter of every Dewpoint client, worker and replayer."""
+    return dataclasses.replace(
+        DataConverter.default,
+        payload_codec=TenantCodec(keys),
+        failure_converter_class=DefaultFailureConverterWithEncodedAttributes,
+    )
+
+
+class KeyringKeys:
+    """Tenants' data keys from the keyring, read-only, cached unwrapped in this process and nowhere else: at most
+    `size` of them, each for at most `ttl_s` seconds, so a rotation takes effect within `ttl_s`. A missing key is
+    never cached: a tenant created after this process started is served at once (spec §6.3)."""
+
+    def __init__(
+        self,
+        sessionmaker: async_sessionmaker[AsyncSession],
+        keyring: Keyring,
+        *,
+        size: int = 1024,
+        ttl_s: float = 300.0,
+        clock: Callable[[], float] = time.monotonic,
+    ) -> None:
+        self._sessionmaker, self._keyring = sessionmaker, keyring
+        self._size, self._ttl_s, self._clock = size, ttl_s, clock
+        self._cache: OrderedDict[tuple[str, int | None], tuple[float, int, AESGCM]] = OrderedDict()
+
+    async def active(self, tenant_id: str) -> tuple[int, AESGCM]:
+        return await self._read(tenant_id, None)
+
+    async def get(self, tenant_id: str, version: int) -> AESGCM:
+        return (await self._read(tenant_id, version))[1]
+
+    async def _read(self, tenant_id: str, version: int | None) -> tuple[int, AESGCM]:
+        now = self._clock()
+        hit = self._cache.get((tenant_id, version))
+        if hit is not None and hit[0] > now:
+            self._cache.move_to_end((tenant_id, version))
+            return hit[1], hit[2]
+        tenant = uuid.UUID(tenant_id)
+        async with self._sessionmaker() as s, s.begin():
+            await tenant_scope(s, tenant)
+            found, raw = await self._keyring.read_dek(s, tenant, version)
+        entry = (now + self._ttl_s, found, AESGCM(raw))
+        for k in {(tenant_id, version), (tenant_id, found)}:
+            self._cache[k] = entry
+            self._cache.move_to_end(k)
+        while len(self._cache) > self._size:
+            self._cache.popitem(last=False)
+        return found, entry[2]
diff --git a/backend/src/dewpoint/core/crypto/keyring.py b/backend/src/dewpoint/core/crypto/keyring.py
index b9a1893..7351440 100644
--- a/backend/src/dewpoint/core/crypto/keyring.py
+++ b/backend/src/dewpoint/core/crypto/keyring.py
@@ -17,6 +17,10 @@ FORMAT_V1 = b"\x01"
 type AnyKey = DataKey | PlatformKey
 
 
+class NoKeyError(LookupError):
+    """A tenant has no data key of that version, or none at all (or RLS hides it): nothing reads creates one."""
+
+
 def _scope(tenant_id: uuid.UUID | None) -> str:
     return str(tenant_id) if tenant_id else "platform"
 
@@ -92,6 +96,20 @@ class Keyring:
             raise InvalidTag()
         return self._dek(row).decrypt(blob[5:17], blob[17:], _aad(_scope(tenant_id), purpose, context))
 
+    async def ensure_key(self, s: AsyncSession, tenant_id: uuid.UUID) -> int:
+        """The tenant's active key version, created if it has none. Tenant creation calls it, so a tenant has a key
+        before anything encrypts for it (engine 2b spec §6.3)."""
+        return (await self._active(s, tenant_id)).version
+
+    async def read_dek(self, s: AsyncSession, tenant_id: uuid.UUID, version: int | None = None) -> tuple[int, bytes]:
+        """A tenant's data key, unwrapped: its active one, or `version`. Read-only, with no lock and no creation: the
+        payload codec's cache reads it (engine 2b spec §6.3), under the tenant's RLS scope."""
+        which = DataKey.active.is_(True) if version is None else DataKey.version == version
+        row = (await s.execute(select(DataKey).where(DataKey.tenant_id == tenant_id, which))).scalar_one_or_none()
+        if row is None:
+            raise NoKeyError(f"tenant {tenant_id} has no data key" + ("" if version is None else f" {version}"))
+        return row.version, self._keks.get(row.kek_id).unwrap(row.wrapped_key, _dek_aad(row))
+
     async def rotate(self, s: AsyncSession, tenant_id: uuid.UUID | None) -> int:
         current = await self._active(s, tenant_id)
         await s.execute(update(type(current)).where(type(current).id == current.id).values(active=False))
````

- [ ] **Step 4: Run the tests again**

Run: `cd backend && uv run pytest -q -p no:cacheprovider tests/apps/test_codec.py tests/apps/test_codec_keys.py tests/core/crypto/test_keyring.py`

Expected (the replay):

````text
24 passed in 4.52s
````

- [ ] **Step 5: The whole suite, lint, types and layers**

Run: `cd backend && uv run pytest -q -p no:cacheprovider`, then `uv run ruff check --no-cache src tests migrations`, `uv run ruff format --no-cache --check src tests migrations`, `uv run mypy src` and `uv run lint-imports`.

Expected: 1,150 passed, 8 skipped; ruff and its formatter clean; mypy: no issues; import-linter: 10 contracts kept.

- [ ] **Step 6: Commit**

```bash
git add -A backend deploy docs && git commit -m "feat(codec): TenantCodec, its key cache, and the keyring's read-only keys (2b-1a)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: A data key for every tenant; the dispatch role reads keys

**Spec:** §6.3.

**Files:**
- Create: `backend/migrations/versions/0011_dispatch_reads_keys.py`
- Create: `backend/tests/core/tenancy/test_tenant_keys.py`
- Modify: `backend/src/dewpoint/apps/api/routes/tenants.py`
- Modify: `backend/src/dewpoint/apps/cli/main.py`
- Modify: `backend/src/dewpoint/core/tenancy/service.py`
- Modify: `backend/tests/apps/api/test_tenant_matrix.py`
- Modify: `backend/tests/apps/cli/test_keys.py`
- Modify: `backend/tests/apps/test_codec_keys.py`
- Modify: `deploy/compose/docker-compose.yml`

**Interfaces:**
- Consumes: Task 4's `Keyring.ensure_key`, `Keyring.read_dek`, `KeyringKeys`, `TenantCodec`.
- Produces:
  - `create_tenant(s, keyring, *, name, slug, owner_id)`, whose signature changes;
  - `ensure_tenant_keys(s, keyring) -> list[uuid.UUID]`;
  - the CLI command `keys ensure-tenants`;
  - migration `0011`, and the Compose migrate step's third command.

The codec only reads keys, so every tenant needs one before anything encrypts for it:
- `create_tenant` creates it, and the API route passes its keyring.
- `ensure_tenant_keys`, behind `dewpoint keys ensure-tenants`, gives one to every tenant that has none. It reads
  every tenant, past RLS, so it runs as the database owner, as Compose's migrate step does.
- Migration 0011 grants the dispatch role `SELECT` on `data_keys`: until 2b-2, `dewpoint dev run` starts runs through
  that role, and encrypts the start.

- [ ] **Step 1: Write the tests**

````diff
diff --git a/backend/tests/apps/api/test_tenant_matrix.py b/backend/tests/apps/api/test_tenant_matrix.py
index 9f6bc65..c2d7bad 100644
--- a/backend/tests/apps/api/test_tenant_matrix.py
+++ b/backend/tests/apps/api/test_tenant_matrix.py
@@ -57,6 +57,8 @@ async def test_platform_admin_creates_tenant_and_last_owner_protected(app, owner
         r = await c.post("/api/v1/tenants", json={"name": "Acme Retail", "slug": "acme-retail"})
         assert r.status_code == 201
         tid = r.json()["id"]
+        async with owner_sessionmaker() as s, s.begin():  # engine 2b spec §6.3: its data key comes with it
+            assert (await app.state.keyring.read_dek(s, uuid.UUID(tid)))[0] == 1
         mine = (await c.get("/api/v1/tenants")).json()
         assert [(t["slug"], t["role"]) for t in mine] == [("acme-retail", "owner")]
         me = (await c.get("/api/v1/auth/session")).json()["user"]["id"]
diff --git a/backend/tests/apps/cli/test_keys.py b/backend/tests/apps/cli/test_keys.py
index 77f8d80..3886cb3 100644
--- a/backend/tests/apps/cli/test_keys.py
+++ b/backend/tests/apps/cli/test_keys.py
@@ -1,12 +1,15 @@
 # SPDX-License-Identifier: Apache-2.0
+import asyncio
 import base64
 import os
 import uuid
 
+from sqlalchemy import text
 from typer.testing import CliRunner
 
 from dewpoint.apps.cli.main import app
 from dewpoint.core.config import get_settings
+from dewpoint.core.db import make_engine
 
 OLD, NEW = base64.b64encode(os.urandom(32)).decode(), base64.b64encode(os.urandom(32)).decode()
 
@@ -69,3 +72,25 @@ def test_key_commands_work_as_the_admin_role(pg_url, _test_users, monkeypatch) -
     assert "rewrapped 6" in r.invoke(app, ["keys", "rewrap", "--batch-size", "4"]).output
     assert r.invoke(app, ["keys", "status"]).output.strip() == "new=6"
     assert r.invoke(app, ["keys", "rotate-dek", "--tenant", "not-a-uuid"]).exit_code == 2
+
+
+def test_ensure_tenants_gives_every_tenant_without_a_key_one(pg_url, monkeypatch) -> None:
+    """Engine 2b spec §6.3: tenants created before 2b-1a. Compose's migrate step runs it as the database owner."""
+
+    async def add() -> None:
+        engine = make_engine(pg_url)
+        async with engine.begin() as c:
+            for n in range(2):
+                await c.execute(
+                    text("insert into tenants(id,name,slug) values (:t,'T',:s)"), {"t": uuid.uuid4(), "s": f"t{n}"}
+                )
+        await engine.dispose()
+
+    asyncio.run(add())
+    r = CliRunner()
+    _env(monkeypatch, pg_url, DEWPOINT_KEK_B64=OLD, DEWPOINT_KEK_ID="old")
+    first = r.invoke(app, ["keys", "ensure-tenants"])
+    assert (first.exit_code, first.output) == (0, "created a data key for 2 tenant(s)\n")
+    again = r.invoke(app, ["keys", "ensure-tenants"])
+    assert (again.exit_code, again.output) == (0, "created a data key for 0 tenant(s)\n")
+    assert "old=2" in r.invoke(app, ["keys", "status"]).output
diff --git a/backend/tests/apps/test_codec_keys.py b/backend/tests/apps/test_codec_keys.py
index a30d8ba..7ff99ab 100644
--- a/backend/tests/apps/test_codec_keys.py
+++ b/backend/tests/apps/test_codec_keys.py
@@ -34,12 +34,15 @@ async def with_key(owner_sessionmaker: async_sessionmaker[AsyncSession], tenant:
         return await KEYRING.ensure_key(s, tenant)
 
 
-async def test_the_worker_reads_a_tenants_key_and_the_codec_uses_it(owner_sessionmaker, worker_sessionmaker) -> None:
+async def test_the_worker_and_dispatch_read_a_tenants_key_for_the_codec(
+    owner_sessionmaker, worker_sessionmaker, dispatch_sessionmaker
+) -> None:
+    """The worker, and the dev CLI's start through the dispatch role (engine 2b spec §6.3)."""
     tenant = uuid.uuid4()
     await with_key(owner_sessionmaker, tenant)
-    keys = KeyringKeys(worker_sessionmaker, KEYRING)
-    c = TenantCodec(keys).with_context(workflow(str(tenant)))
-    assert await c.decode(await c.encode([payload({"x": 1})])) == [payload({"x": 1})]
+    for role in (worker_sessionmaker, dispatch_sessionmaker):
+        c = TenantCodec(KeyringKeys(role, KEYRING)).with_context(workflow(str(tenant)))
+        assert await c.decode(await c.encode([payload({"x": 1})])) == [payload({"x": 1})]
 
 
 async def test_a_key_is_read_once_until_its_time_is_up(owner_sessionmaker, worker_sessionmaker) -> None:
diff --git a/backend/tests/core/tenancy/test_tenant_keys.py b/backend/tests/core/tenancy/test_tenant_keys.py
new file mode 100644
index 0000000..34ee3b7
--- /dev/null
+++ b/backend/tests/core/tenancy/test_tenant_keys.py
@@ -0,0 +1,35 @@
+# SPDX-License-Identifier: Apache-2.0
+"""Engine 2b spec §6.3: every tenant has a data key before anything encrypts for it. The payload codec only reads
+keys, so a tenant gets one when it's created, and tenants created before 2b-1a get one from `ensure_tenant_keys`."""
+
+import os
+import uuid
+
+from sqlalchemy import text
+
+from dewpoint.core.auth.users import create_user
+from dewpoint.core.crypto.kek import Kek, KekSet
+from dewpoint.core.crypto.keyring import Keyring
+from dewpoint.core.tenancy import service
+
+KEYRING = Keyring(KekSet(Kek("k1", os.urandom(32))))
+
+
+async def test_a_new_tenant_has_a_data_key(owner_sessionmaker, api_sessionmaker) -> None:
+    async with owner_sessionmaker() as s, s.begin():
+        owner = await create_user(s, email="owner@corp.test", password="violet-otter-canyon-42")
+    async with api_sessionmaker() as s, s.begin():  # as the API creates it
+        tenant = await service.create_tenant(s, KEYRING, name="Acme", slug="acme", owner_id=owner.id)
+        assert (await KEYRING.read_dek(s, tenant.id))[0] == 1
+
+
+async def test_tenants_without_a_key_get_one_once(owner_sessionmaker) -> None:
+    older, keyed = uuid.uuid4(), uuid.uuid4()
+    async with owner_sessionmaker() as s, s.begin():
+        for tid, slug in ((older, "older"), (keyed, "keyed")):
+            await s.execute(text("insert into tenants(id,name,slug) values (:t,'T',:s)"), {"t": tid, "s": slug})
+        await KEYRING.ensure_key(s, keyed)
+    async with owner_sessionmaker() as s, s.begin():  # the database owner, as the migrate step runs it
+        assert await service.ensure_tenant_keys(s, KEYRING) == [older]
+        assert await service.ensure_tenant_keys(s, KEYRING) == []
+        assert [(await KEYRING.read_dek(s, t))[0] for t in (older, keyed)] == [1, 1]
````

- [ ] **Step 2: Run them, and watch them fail**

Run: `cd backend && uv run pytest -q -p no:cacheprovider tests/apps/api/test_tenant_matrix.py tests/apps/cli/test_keys.py tests/apps/test_codec_keys.py tests/core/tenancy/test_tenant_keys.py`

Expected: FAIL. `create_tenant` has no keyring parameter, `ensure_tenant_keys` and the CLI command don't exist, and the dispatch role can't read `data_keys`. The replay showed:

````text
E           dewpoint.core.crypto.keyring.NoKeyError: tenant 9911ab0a-c9e6-4a71-8360-5711598ac4c3 has no data key
E       AssertionError: assert (2, 'Usage: r...─────────╯\n') == (0, 'created ... tenant(s)\n')
E         
E         At index 0 diff: 2 != 0
E         Use -v to get more diff
E   asyncpg.exceptions.InsufficientPrivilegeError: permission denied for table data_keys
E                   sqlalchemy.dialects.postgresql.asyncpg.AsyncAdapt_asyncpg_dbapi.ProgrammingError: permission denied for table data_keys
E                   sqlalchemy.exc.ProgrammingError: (sqlalchemy.dialects.postgresql.asyncpg.ProgrammingError) permission denied for table data_keys
E                   [SQL: SELECT data_keys.tenant_id, data_keys.version, data_keys.wrapped_key, data_keys.kek_id, data_keys.active, data_keys.created_at, data_keys.id 
E                   FROM data_keys 
E                   WHERE data_keys.tenant_id = $1::UUID AND data_keys.active IS true]
E                   [parameters: (UUID('bbf6910a-b2a7-49ff-8844-f8589028c4ce'),)]
E                   (Background on this error at: https://sqlalche.me/e/21/f405)
E           TypeError: create_tenant() takes 1 positional argument but 2 positional arguments (and 3 keyword-only arguments) were given
...
5 failed, 15 passed in 6.62s
````

- [ ] **Step 3: Implement**

````diff
diff --git a/backend/migrations/versions/0011_dispatch_reads_keys.py b/backend/migrations/versions/0011_dispatch_reads_keys.py
new file mode 100644
index 0000000..2c9e55f
--- /dev/null
+++ b/backend/migrations/versions/0011_dispatch_reads_keys.py
@@ -0,0 +1,18 @@
+# SPDX-License-Identifier: Apache-2.0
+"""the dispatch role reads data keys: its starts are encrypted with the tenant's key (engine 2b spec §6.3, plan 2b-1a)"""
+
+from alembic import op
+
+revision = "0011"
+down_revision = "0010"
+branch_labels = None
+depends_on = None
+
+
+def upgrade() -> None:
+    # Read-only, and RLS still scopes each read to the tenant the session is set to (data_keys_tenant).
+    op.execute("GRANT SELECT ON data_keys TO dewpoint_dispatch")
+
+
+def downgrade() -> None:
+    op.execute("REVOKE SELECT ON data_keys FROM dewpoint_dispatch")
diff --git a/backend/src/dewpoint/apps/api/routes/tenants.py b/backend/src/dewpoint/apps/api/routes/tenants.py
index 08798ab..6de4f7d 100644
--- a/backend/src/dewpoint/apps/api/routes/tenants.py
+++ b/backend/src/dewpoint/apps/api/routes/tenants.py
@@ -4,8 +4,10 @@ from pydantic import BaseModel, Field
 from sqlalchemy.exc import IntegrityError
 from sqlalchemy.ext.asyncio import AsyncSession
 
+from dewpoint.apps.api.deps import get_keyring
 from dewpoint.core.audit.service import record
 from dewpoint.core.authz.permissions import P
+from dewpoint.core.crypto.keyring import Keyring
 from dewpoint.core.http import TenantContext, current_user, get_db, require, require_platform_admin
 from dewpoint.core.models.identity import User
 from dewpoint.core.models.tenancy import Tenant
@@ -48,10 +50,13 @@ async def my_tenants(
 
 @router.post("/tenants", status_code=201)
 async def create(
-    body: TenantIn, admin: User = Depends(require_platform_admin), db: AsyncSession = Depends(get_db, scope="function")
+    body: TenantIn,
+    admin: User = Depends(require_platform_admin),
+    db: AsyncSession = Depends(get_db, scope="function"),
+    keyring: Keyring = Depends(get_keyring),
 ) -> dict[str, object]:
     try:
-        t = await service.create_tenant(db, name=body.name, slug=body.slug, owner_id=admin.id)
+        t = await service.create_tenant(db, keyring, name=body.name, slug=body.slug, owner_id=admin.id)
     except IntegrityError:
         raise HTTPException(409, detail={"error": "slug_taken"}) from None
     await record(
diff --git a/backend/src/dewpoint/apps/cli/main.py b/backend/src/dewpoint/apps/cli/main.py
index c8504f1..b24d232 100644
--- a/backend/src/dewpoint/apps/cli/main.py
+++ b/backend/src/dewpoint/apps/cli/main.py
@@ -37,6 +37,7 @@ from dewpoint.core.plugins.registry import (
     list_node_types,
     sync_plugins,
 )
+from dewpoint.core.tenancy.service import ensure_tenant_keys
 from dewpoint.engine.cel.profile import CURRENT_CEL_PROFILE
 from dewpoint.engine.runtime.activities import LIVE, SIMULATE, RunResult
 from dewpoint.engine.runtime.ids import run_workflow_id
@@ -222,6 +223,19 @@ def keys_rotate_dek(tenant: str | None = typer.Option(None), platform: bool = ty
     typer.echo(f"active data key version: {asyncio.run(_in_session(_run))}")
 
 
+@keys.command("ensure-tenants")
+def keys_ensure_tenants() -> None:
+    """A data key for every tenant that has none (tenants created before 2b-1a): the payload codec only reads keys.
+    Idempotent. Run as the database owner, as Compose's migrate step does."""
+    keyring = Keyring(KekSet.from_settings(get_settings()))
+
+    async def _run(s: AsyncSession) -> list[uuid.UUID]:
+        async with s.begin():
+            return await ensure_tenant_keys(s, keyring)
+
+    typer.echo(f"created a data key for {len(asyncio.run(_in_session(_run)))} tenant(s)")
+
+
 @plugins_cli.command("sync")
 def plugins_sync() -> None:
     """Register installed plugins and this build's CEL profile. Run as dewpoint_admin on every deploy."""
diff --git a/backend/src/dewpoint/core/tenancy/service.py b/backend/src/dewpoint/core/tenancy/service.py
index 5c11724..29a9780 100644
--- a/backend/src/dewpoint/core/tenancy/service.py
+++ b/backend/src/dewpoint/core/tenancy/service.py
@@ -6,7 +6,9 @@ from sqlalchemy.ext.asyncio import AsyncSession
 
 from dewpoint.core.auth.users import get_user_by_email
 from dewpoint.core.authz.permissions import ROLE_PERMISSIONS, P
+from dewpoint.core.crypto.keyring import Keyring
 from dewpoint.core.db import tenant_scope, user_scope
+from dewpoint.core.models.keys import DataKey
 from dewpoint.core.models.tenancy import Membership, Tenant
 
 
@@ -23,7 +25,8 @@ class ActorNotAuthorizedError(Exception):
     """The acting user no longer holds a role allowing this change (re-checked under the tenant lock)."""
 
 
-async def create_tenant(s: AsyncSession, *, name: str, slug: str, owner_id: uuid.UUID) -> Tenant:
+async def create_tenant(s: AsyncSession, keyring: Keyring, *, name: str, slug: str, owner_id: uuid.UUID) -> Tenant:
+    """A tenant, its owner, and its data key: the payload codec only reads keys (engine 2b spec §6.3)."""
     tid = uuid.uuid4()
     await tenant_scope(s, tid)
     tenant = Tenant(id=tid, name=name, slug=slug)
@@ -31,9 +34,21 @@ async def create_tenant(s: AsyncSession, *, name: str, slug: str, owner_id: uuid
     await s.flush()
     s.add(Membership(tenant_id=tid, user_id=owner_id, role="owner"))
     await s.flush()
+    await keyring.ensure_key(s, tid)
     return tenant
 
 
+async def ensure_tenant_keys(s: AsyncSession, keyring: Keyring) -> list[uuid.UUID]:
+    """A data key for every tenant that has none — tenants created before 2b-1a — and which ones got one. It reads
+    every tenant, past RLS, so it runs as the database owner, as Compose's migrate step does."""
+    keyed = select(DataKey.id).where(DataKey.tenant_id == Tenant.id).exists()
+    created = list((await s.execute(select(Tenant.id).where(~keyed).order_by(Tenant.id))).scalars())
+    for tid in created:
+        await tenant_scope(s, tid)
+        await keyring.ensure_key(s, tid)
+    return created
+
+
 async def list_user_tenants(s: AsyncSession, user_id: uuid.UUID) -> list[tuple[Tenant, str]]:
     await user_scope(s, user_id)
     rows = await s.execute(
diff --git a/deploy/compose/docker-compose.yml b/deploy/compose/docker-compose.yml
index 01821cf..fc88336 100644
--- a/deploy/compose/docker-compose.yml
+++ b/deploy/compose/docker-compose.yml
@@ -35,7 +35,8 @@ services:
     <<: *app
     # The schema, then what this deployment is, recorded once (engine 2b spec §2.1): production and gated unless a
     # development setup opts in with its own database and Temporal namespace. Every later run checks the same values.
-    command: ["sh", "-c", "set -e; alembic upgrade head; dewpoint platform init-environment"]
+    # Then a data key for any tenant without one (created before 2b-1a): the payload codec only reads keys (§6.3).
+    command: ["sh", "-c", "set -e; alembic upgrade head; dewpoint platform init-environment; dewpoint keys ensure-tenants"]
     environment:
       <<: *appenv
       DEWPOINT_DATABASE_URL: postgresql+asyncpg://dewpoint_owner:${POSTGRES_PASSWORD}@postgres/dewpoint
````

- [ ] **Step 4: Run the tests again**

Run: `cd backend && uv run pytest -q -p no:cacheprovider tests/apps/api/test_tenant_matrix.py tests/apps/cli/test_keys.py tests/apps/test_codec_keys.py tests/core/tenancy/test_tenant_keys.py`

Expected (the replay):

````text
20 passed in 6.19s
````

- [ ] **Step 5: The whole suite, lint, types and layers**

Run: `cd backend && uv run pytest -q -p no:cacheprovider`, then `uv run ruff check --no-cache src tests migrations`, `uv run ruff format --no-cache --check src tests migrations`, `uv run mypy src` and `uv run lint-imports`.

Expected: 1,153 passed, 8 skipped; ruff and its formatter clean; mypy: no issues; import-linter: 10 contracts kept.

- [ ] **Step 6: Commit**

```bash
git add -A backend deploy docs && git commit -m "feat(keys): a data key for every tenant; the dispatch role reads keys (2b-1a)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: The codec on every client, worker, test server and replayer

**Spec:** §6.2, §12.

**Files:**
- Create: `backend/tests/apps/worker/test_codec_history.py`
- Modify: `backend/src/dewpoint/apps/cli/main.py`
- Modify: `backend/src/dewpoint/apps/runs.py`
- Modify: `backend/src/dewpoint/apps/worker/main.py`
- Modify: `backend/tests/apps/cli/test_dev_run_cli.py`
- Modify: `backend/tests/apps/test_runs.py`
- Modify: `backend/tests/apps/worker/conftest.py`
- Modify: `backend/tests/apps/worker/test_gate_task_cost.py`
- Modify: `backend/tests/apps/worker/test_main.py`
- Modify: `backend/tests/apps/worker/test_real_server.py`
- Modify: `backend/tests/apps/worker/test_run_graph.py`
- Modify: `backend/tests/apps/worker/test_run_graph_cel_requests.py`
- Modify: `backend/tests/apps/worker/test_run_graph_children.py`
- Modify: `backend/tests/apps/worker/test_run_graph_continue.py`
- Modify: `backend/tests/apps/worker/test_run_graph_ids.py`
- Modify: `backend/tests/engine/replay/record.py`
- Modify: `backend/tests/engine/replay/test_replay.py`
- Modify: `backend/tests/support/keys.py`
- Record: `backend/tests/engine/replay/dewpoint-0.1.0+abi5/` (generated, below)

**Interfaces:**
- Consumes: Task 4's `data_converter`, `KeyringKeys`, `TenantCodec`, `CodecRefusedError`, `ENCODING`, `TENANT`,
  `FixtureKeys`, and Task 5's grant.
- Produces:
  - `tests.support.keys.FIXTURE_CONVERTER`, and `async opened(payload) -> Any`;
  - `_temporal()` is an `@asynccontextmanager` (`async with _temporal() as client:`);
  - `FakeClient(..., data_converter=FIXTURE_CONVERTER)` in `tests/apps/test_runs.py`.

The worker and the CLI connect with `data_converter(KeyringKeys(...))`, reading keys through their
database roles. The CLI's `_temporal` becomes an async context manager that owns its engine.
- `start_run` encrypts the start once before trying to send it. A start that can't be encrypted (a tenant without a
  key) is a refusal: the run is recorded `failed` (`start_failed`), never left `running`.
- Every test server, the recorder and the replayers use `FIXTURE_CONVERTER`. Tests that read payloads out of a
  history decrypt them with `opened`.
- The abi5 histories are deleted and recorded again, encrypted. A test proves that no payload in them is plain,
  except the SDK core's own local-activity bookkeeping (spec §4.6).
- A canary run proves that no execution's raw history holds its payloads in plain text: the run, its sub-flow, its
  batches, a `cel.evaluate` request and the load marker.
- A workflow id that names no tenant never reaches Temporal: the client's codec refuses it.

- [ ] **Step 1: Write the tests**

````diff
diff --git a/backend/tests/apps/cli/test_dev_run_cli.py b/backend/tests/apps/cli/test_dev_run_cli.py
index 0c14311..ff54ece 100644
--- a/backend/tests/apps/cli/test_dev_run_cli.py
+++ b/backend/tests/apps/cli/test_dev_run_cli.py
@@ -10,9 +10,11 @@ from pathlib import Path
 from typing import Any
 
 import pytest
+from temporalio.converter import DefaultFailureConverterWithEncodedAttributes
 from typer.testing import CliRunner
 
 from dewpoint.apps.cli import main as cli
+from dewpoint.apps.codec import TenantCodec
 from dewpoint.apps.runs import NotAdmissibleError, StartRefusedError, StartUncertainError
 from dewpoint.core.config import get_settings
 from dewpoint.engine.runtime.activities import RunResult
@@ -118,3 +120,23 @@ def test_an_input_that_isnt_a_json_object_is_refused_before_anything_starts(
         cli.app, ["dev", "run", str(uuid.uuid4()), "--tenant", str(uuid.uuid4()), "--input", str(trigger)]
     )
     assert (result.exit_code, result.output) == (2, "ERROR: --input must hold a JSON object\n") and seen == {}
+
+
+@pytest.mark.usefixtures("cli_env")
+def test_the_cli_connects_with_the_tenant_codec(monkeypatch: pytest.MonkeyPatch) -> None:
+    """Engine 2b spec §6.2: the dev CLI's start and its result go through the codec, failures too."""
+    connected: dict[str, Any] = {}
+
+    class Recording(_Client):
+        @staticmethod
+        async def connect(*args: Any, **kwargs: Any) -> "_Client":
+            connected.update(kwargs)
+            return _Client()
+
+    monkeypatch.setattr(cli, "Client", Recording)
+    _answer(monkeypatch, RunResult("succeeded", {}), {})
+    result = CliRunner().invoke(cli.app, ["dev", "run", str(uuid.uuid4()), "--tenant", str(uuid.uuid4())])
+    assert result.exit_code == 0, result.output
+    converter = connected["data_converter"]
+    assert isinstance(converter.payload_codec, TenantCodec)
+    assert converter.failure_converter_class is DefaultFailureConverterWithEncodedAttributes
diff --git a/backend/tests/apps/test_runs.py b/backend/tests/apps/test_runs.py
index be32d50..17ad7a7 100644
--- a/backend/tests/apps/test_runs.py
+++ b/backend/tests/apps/test_runs.py
@@ -11,11 +11,13 @@ from typing import Any
 import pytest
 from temporalio.api.workflowservice.v1 import DescribeWorkerDeploymentRequest, DescribeWorkerDeploymentResponse
 from temporalio.common import WorkflowIDReusePolicy
+from temporalio.converter import DataConverter
 from temporalio.exceptions import WorkflowAlreadyStartedError
 from temporalio.service import RPCError, RPCStatusCode
 
 from dewpoint.apps import runs as run_ops
 from dewpoint.apps import workflow_ops
+from dewpoint.apps.codec import data_converter
 from dewpoint.apps.runs import (
     NO_CURRENT_BUILD,
     START_FAILED,
@@ -44,6 +46,7 @@ from tests.apps.test_workflow_ops import (
     save,
     update,
 )
+from tests.support.keys import FIXTURE_CONVERTER, FixtureKeys
 from tests.support.registry import sync_test_plugins
 
 pytestmark = pytest.mark.usefixtures("development_deployment")  # runs are admitted: engine 2b spec §2.3
@@ -81,8 +84,14 @@ class FakeClient:
 
     namespace = "default"
 
-    def __init__(self, *answers: BaseException | LostAck | None, current: str | None = this_build()) -> None:
+    def __init__(
+        self,
+        *answers: BaseException | LostAck | None,
+        current: str | None = this_build(),
+        data_converter: DataConverter = FIXTURE_CONVERTER,
+    ) -> None:
         self.workflow_service = FakeDeployment(current)
+        self.data_converter = data_converter  # what the client encrypts starts with
         self.answers = list(answers)
         self.started: list[tuple[RunInput, str, str]] = []
         self.calls: list[tuple[str, WorkflowIDReusePolicy]] = []
@@ -506,3 +515,20 @@ async def test_admission_reads_the_workflow_afresh_in_a_session_that_loaded_it(
         await change_committed(api_sessionmaker, ctx, wf, change)
         with pytest.raises(NotAdmissibleError, match=REFUSED[how]):
             await run_ops.admit(s, tenant_id=ctx.tenant_id, version_id=version, abi=ENGINE_ABI)
+
+
+async def test_a_start_that_cant_be_encrypted_is_refused_and_its_run_failed(
+    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings
+) -> None:
+    """Engine 2b spec §6.2–6.3: a tenant whose data key can't be read (one created before 2b-1a, not yet given a key):
+    nothing reached Temporal, so the start is refused and the run recorded as failed, never left `running`."""
+    ctx, _, version = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings)
+    client = FakeClient(data_converter=data_converter(FixtureKeys(missing={str(ctx.tenant_id)})))
+    with pytest.raises(StartRefusedError, match="couldn't be encrypted"):
+        await start_run(
+            dispatch_sessionmaker, client, api_settings,  # type: ignore[arg-type]
+            tenant_id=ctx.tenant_id, version_id=version, trigger={},
+        )  # fmt: skip
+    assert client.calls == []  # never sent
+    row = await only_run(owner_sessionmaker, ctx.tenant_id)
+    assert (row.status, row.error_code) == ("failed", START_FAILED)
diff --git a/backend/tests/apps/worker/conftest.py b/backend/tests/apps/worker/conftest.py
index 4846f9b..c1d44c9 100644
--- a/backend/tests/apps/worker/conftest.py
+++ b/backend/tests/apps/worker/conftest.py
@@ -7,12 +7,14 @@ from temporalio.testing import WorkflowEnvironment
 
 from dewpoint.apps import runs as run_ops
 from dewpoint.engine import ENGINE_ABI
+from tests.support.keys import FIXTURE_CONVERTER
 
 
 @pytest.fixture(scope="session")
 async def env() -> AsyncIterator[WorkflowEnvironment]:
-    """Temporal's time-skipping test server (downloaded once by the SDK), shared by the session."""
-    async with await WorkflowEnvironment.start_time_skipping() as environment:
+    """Temporal's time-skipping test server (downloaded once by the SDK), shared by the session. Its client encrypts
+    as every Dewpoint process does, with fixture keys (engine 2b spec §6.2)."""
+    async with await WorkflowEnvironment.start_time_skipping(data_converter=FIXTURE_CONVERTER) as environment:
         yield environment
 
 
@@ -21,7 +23,7 @@ async def own_env() -> AsyncIterator[WorkflowEnvironment]:
     """A test server of the test's own, for a test that ends a run while an activity still runs. That activity never
     completes against its closed run, and the time-skipping server stops skipping time while any activity is
     outstanding: every later timer on a shared server would wait in real time."""
-    async with await WorkflowEnvironment.start_time_skipping() as environment:
+    async with await WorkflowEnvironment.start_time_skipping(data_converter=FIXTURE_CONVERTER) as environment:
         yield environment
 
 
@@ -35,7 +37,9 @@ async def dev_env() -> AsyncIterator[WorkflowEnvironment]:
         "matching.wv.VersionDrainageStatusRefreshInterval",
     ]
     args = [a for key in drainage for a in ("--dynamic-config-value", f'{key}="1s"')]
-    async with await WorkflowEnvironment.start_local(dev_server_extra_args=args) as environment:
+    async with await WorkflowEnvironment.start_local(
+        data_converter=FIXTURE_CONVERTER, dev_server_extra_args=args
+    ) as environment:
         yield environment
 
 
diff --git a/backend/tests/apps/worker/test_codec_history.py b/backend/tests/apps/worker/test_codec_history.py
new file mode 100644
index 0000000..27e38f0
--- /dev/null
+++ b/backend/tests/apps/worker/test_codec_history.py
@@ -0,0 +1,43 @@
+# SPDX-License-Identifier: Apache-2.0
+"""Engine 2b spec §6.2: every payload a run puts in Temporal's history is encrypted with its tenant's key — the start
+and the result, a sub-flow's, a batch's, a `cel.evaluate` request's, every activity's input and result, local
+activities' markers. A canary in the trigger reaches all of them, and no history holds it in plain text."""
+
+import asyncio
+
+from temporalio.testing import WorkflowEnvironment
+
+from dewpoint.apps.codec import ENCODING
+from tests.apps.worker.harness import EVALUATOR_ONLY, RESULT_TIMEOUT_S, MemoryStore, start, workers
+from tests.engine.replay.record import executions
+from tests.support.graphs import G, cel, ref
+
+CANARY = "canary-4f1b2c9e-never-in-plain-text"
+SECRET = {"type": "object", "properties": {"s": {"type": "string"}}, "required": ["s"]}
+
+
+def echoed() -> G:
+    sub = G()
+    sub.settings = {"input_schema": SECRET, "outputs": {"s": ref("steps.e.output.value")}}
+    return sub.node("e", "testkit.echo@1", {"value": ref("trigger.s")})
+
+
+async def test_no_history_of_a_run_holds_its_payloads_in_plain_text(env: WorkflowEnvironment) -> None:
+    store = MemoryStore()
+    g = G()
+    outputs = {"sub": ref("steps.r.output.s"), "cel": ref("steps.c.output.value"), "items": ref("steps.l.output.items")}
+    g.settings = {"input_schema": SECRET, "outputs": outputs}
+    g.node("r", "flow.run_workflow@1", {"workflow_id": str(store.publish(echoed())), "input": {"s": ref("trigger.s")}})
+    g.node("c", "testkit.echo@1", {"value": cel(f"{EVALUATOR_ONLY} == 1 ? trigger.s : ''")})  # the evaluator's
+    g.node("l", "flow.loop@1", {"items": list(range(101)), "collect": ref("steps.x.output.value")})  # a batch
+    g.node("x", "testkit.echo@1", {"value": ref("trigger.s")}).edge("l", "x", "body")
+    async with workers(env.client, store):
+        handle = await start(env.client, store, g, {"s": CANARY})
+        result = await asyncio.wait_for(handle.result(), RESULT_TIMEOUT_S)
+        histories = await executions(env.client, handle.id, handle.first_execution_run_id or "")
+    assert result.outputs == {"sub": CANARY, "cel": CANARY, "items": [CANARY] * 101}  # the client decrypts it
+    types = [h.events[0].workflow_execution_started_event_attributes.workflow_type.name for h in histories]
+    assert types.count("RunGraph") == 2 and "LoopBatch" in types  # the run, its sub-flow, its batches
+    for history in histories:
+        raw = b"".join(e.SerializeToString() for e in history.events)
+        assert ENCODING in raw and CANARY.encode() not in raw, history.workflow_id
diff --git a/backend/tests/apps/worker/test_gate_task_cost.py b/backend/tests/apps/worker/test_gate_task_cost.py
index 0316328..3106783 100644
--- a/backend/tests/apps/worker/test_gate_task_cost.py
+++ b/backend/tests/apps/worker/test_gate_task_cost.py
@@ -27,6 +27,7 @@ from dewpoint.engine.runtime.workflow import LoopBatch, RunGraph
 from tests.apps.worker.harness import CATALOG, TESTKIT, MemoryStore, in_process, run_id_of, start
 from tests.engine.cel.test_gate_cost import ADVERSARIAL, AT_CAPS, BINDING, TASK_CPU_TARGET_S, WORST
 from tests.support.graphs import G, cel
+from tests.support.keys import FIXTURE_CONVERTER
 
 S = {"type": "string"}
 INTS = {"type": "array", "items": {"type": "integer"}}
@@ -121,7 +122,7 @@ async def test_no_workflow_task_passes_the_cpu_target(name: str, monkeypatch: py
     g = graph().node("l", "flow.loop@1", {"items": list(range(20)), "concurrency": 10})
     g.node("x", "flow.transform@1", {"fields": {"r": cel(expr)}}).edge("l", "x", "body")
     with Timed() as executor:
-        async with await WorkflowEnvironment.start_time_skipping() as env:
+        async with await WorkflowEnvironment.start_time_skipping(data_converter=FIXTURE_CONVERTER) as env:
             engine = Worker(
                 env.client,
                 task_queue=ENGINE_QUEUE,
diff --git a/backend/tests/apps/worker/test_main.py b/backend/tests/apps/worker/test_main.py
index 4b6bf06..2d187a0 100644
--- a/backend/tests/apps/worker/test_main.py
+++ b/backend/tests/apps/worker/test_main.py
@@ -4,9 +4,13 @@
 from datetime import timedelta
 from typing import Any
 
+import pytest
+from temporalio.converter import DefaultFailureConverterWithEncodedAttributes
 from temporalio.testing import WorkflowEnvironment
 
 import dewpoint
+from dewpoint.apps.codec import TenantCodec
+from dewpoint.apps.worker import main
 from dewpoint.apps.worker.main import engine_worker
 from dewpoint.core.config import Settings
 from dewpoint.engine.runtime.build import build_id
@@ -48,3 +52,30 @@ async def test_the_engine_worker_serves_this_builds_version_of_the_deployment(ow
         "dewpoint-engine",
         build_id(dewpoint.__version__),
     )
+
+
+async def test_the_worker_connects_with_the_tenant_codec(monkeypatch: pytest.MonkeyPatch) -> None:
+    """Engine 2b spec §6.2: every payload a worker sends or reads goes through the codec, failures too."""
+    connected: dict[str, Any] = {}
+
+    class Connected(Exception):
+        """Where the test stops the worker: nothing else of it runs."""
+
+    class Engine:
+        async def dispose(self) -> None: ...
+
+    async def recorded(*args: object) -> None: ...
+
+    async def connect(*args: object, **kwargs: Any) -> None:
+        connected.update(kwargs)
+        raise Connected
+
+    monkeypatch.setattr(main.Client, "connect", connect)
+    monkeypatch.setattr(main, "make_engine", lambda url: Engine())
+    monkeypatch.setattr(main, "make_sessionmaker", lambda engine: None)
+    monkeypatch.setattr(main, "verify_environment", recorded)
+    with pytest.raises(Connected):
+        await main.run(settings())
+    converter = connected["data_converter"]
+    assert isinstance(converter.payload_codec, TenantCodec)
+    assert converter.failure_converter_class is DefaultFailureConverterWithEncodedAttributes
diff --git a/backend/tests/apps/worker/test_real_server.py b/backend/tests/apps/worker/test_real_server.py
index a434080..8815358 100644
--- a/backend/tests/apps/worker/test_real_server.py
+++ b/backend/tests/apps/worker/test_real_server.py
@@ -25,6 +25,7 @@ from tests.apps.worker.test_deployment import build
 from tests.apps.worker.test_main import settings
 from tests.engine.replay.record import executions
 from tests.support.graphs import G, cel, ref
+from tests.support.keys import FIXTURE_CONVERTER
 from tests.support.plugins.testkit import TESTKIT
 
 
@@ -157,7 +158,8 @@ async def test_temporal_suggesting_continue_as_new_drains_the_run() -> None:
     g = graph(items=ref("steps.l.output.items"))
     g.node("l", "flow.loop@1", {"items": list(range(40)), "collect": cel("steps.x.output.value")})
     g.node("x", "testkit.echo@1", {"value": ref("item")}).edge("l", "x", "body")
-    async with await WorkflowEnvironment.start_local(dev_server_extra_args=args) as env, serving(env.client, store):
+    local = WorkflowEnvironment.start_local(data_converter=FIXTURE_CONVERTER, dev_server_extra_args=args)
+    async with await local as env, serving(env.client, store):
         handle = await start(env.client, store, g, {})
         result = await asyncio.wait_for(handle.result(), 120)
         chain = await executions(env.client, handle.id, handle.first_execution_run_id or "")
diff --git a/backend/tests/apps/worker/test_run_graph.py b/backend/tests/apps/worker/test_run_graph.py
index bb8ca1b..62ad485 100644
--- a/backend/tests/apps/worker/test_run_graph.py
+++ b/backend/tests/apps/worker/test_run_graph.py
@@ -12,6 +12,7 @@ from dewpoint.engine.cel.profile import CURRENT_CEL_PROFILE
 from dewpoint.engine.runtime.workflow import RunGraph
 from tests.apps.worker.harness import EVALUATOR_ONLY, RESULT_TIMEOUT_S, MemoryStore, run, run_id_of, start, workers
 from tests.support.graphs import G, cel, ref, template
+from tests.support.keys import FIXTURE_CONVERTER
 
 ECHO, IF, LOOP, FILTER = "testkit.echo@1", "flow.if@1", "flow.loop@1", "flow.filter@1"
 SET, DELAY, STOP, FAIL = "flow.set_variables@1", "flow.delay@1", "flow.stop@1", "flow.fail@1"
@@ -196,4 +197,5 @@ async def test_a_recorded_history_replays(env: WorkflowEnvironment) -> None:
         handle = await start(env.client, store, g, TRIGGER)
         await asyncio.wait_for(handle.result(), RESULT_TIMEOUT_S)
         history = await handle.fetch_history()
-    await Replayer(workflows=[RunGraph]).replay_workflow(WorkflowHistory.from_json(handle.id, history.to_json()))
+    replayer = Replayer(workflows=[RunGraph], data_converter=FIXTURE_CONVERTER)
+    await replayer.replay_workflow(WorkflowHistory.from_json(handle.id, history.to_json()))
diff --git a/backend/tests/apps/worker/test_run_graph_cel_requests.py b/backend/tests/apps/worker/test_run_graph_cel_requests.py
index 44c8d59..0332944 100644
--- a/backend/tests/apps/worker/test_run_graph_cel_requests.py
+++ b/backend/tests/apps/worker/test_run_graph_cel_requests.py
@@ -5,7 +5,6 @@ well as by 1,000 binding sets, and a binding set that alone passes the limit fai
 test_real_server.py shows it at the real one."""
 
 import asyncio
-import json
 from typing import Any
 
 import pytest
@@ -17,6 +16,7 @@ from dewpoint.engine.cel import route
 from dewpoint.engine.runtime import execution
 from tests.apps.worker.harness import MemoryStore, run_id_of, start, workers
 from tests.support.graphs import G, cel, ref
+from tests.support.keys import opened
 
 SCHEMA: dict[str, Any] = {"type": "object", "properties": {"s": {"type": "string"}}, "required": ["s"]}
 
@@ -33,7 +33,7 @@ async def sent_sets(handle: WorkflowHandle[Any, Any]) -> list[int]:
     async for e in handle.fetch_history_events():
         a = e.activity_task_scheduled_event_attributes
         if e.event_type == EventType.EVENT_TYPE_ACTIVITY_TASK_SCHEDULED and a.activity_type.name == "cel.evaluate":
-            out.append(len(json.loads(a.input.payloads[0].data)["request"]["bindings"]))
+            out.append(len((await opened(a.input.payloads[0]))["request"]["bindings"]))
     return out
 
 
diff --git a/backend/tests/apps/worker/test_run_graph_children.py b/backend/tests/apps/worker/test_run_graph_children.py
index 2040d62..0b23fc1 100644
--- a/backend/tests/apps/worker/test_run_graph_children.py
+++ b/backend/tests/apps/worker/test_run_graph_children.py
@@ -21,6 +21,7 @@ from dewpoint.engine.runtime.activities import ProjectInput, VersionData
 from dewpoint.engine.runtime.scheduler import Scheduler
 from tests.apps.worker.harness import MemoryStore, run_id_of, start, workers
 from tests.support.graphs import G, cel, ref
+from tests.support.keys import opened
 
 ECHO, LOOP, FILTER, RUN, FAIL = "testkit.echo@1", "flow.loop@1", "flow.filter@1", "flow.run_workflow@1", "flow.fail@1"
 LISTS = {"type": "object", "properties": {"items": {"type": "array"}}, "required": ["items"]}
@@ -61,7 +62,7 @@ async def test_a_loop_over_more_than_a_hundred_items_runs_in_batches_and_collect
     assert {(r.status, r.output_preview["value"]) for r in rows} == {("succeeded", "from outside")}
     history = await handle.fetch_history()
     batches = [
-        json.loads(e.start_child_workflow_execution_initiated_event_attributes.input.payloads[0].data)
+        await opened(e.start_child_workflow_execution_initiated_event_attributes.input.payloads[0])
         for e in history.events
         if e.HasField("start_child_workflow_execution_initiated_event_attributes")
     ]
diff --git a/backend/tests/apps/worker/test_run_graph_continue.py b/backend/tests/apps/worker/test_run_graph_continue.py
index 41919fd..bb94544 100644
--- a/backend/tests/apps/worker/test_run_graph_continue.py
+++ b/backend/tests/apps/worker/test_run_graph_continue.py
@@ -5,7 +5,6 @@ the budget carries over; and draining adds a bounded number of events (the measu
 
 import asyncio
 import dataclasses
-import json
 import uuid
 from datetime import datetime, timedelta
 from typing import Any
@@ -29,6 +28,7 @@ from dewpoint.engine.runtime.ids import run_workflow_id
 from dewpoint.engine.runtime.workflow import LoopBatch
 from tests.apps.worker.harness import TENANT, MemoryStore, run_id_of, start, workers
 from tests.support.graphs import G, cel, ref
+from tests.support.keys import opened
 from tests.support.plugins.testkit import Slow, SlowSend
 
 ECHO, LOOP, RUN = "testkit.echo@1", "flow.loop@1", "flow.run_workflow@1"
@@ -58,10 +58,10 @@ async def chain(client: Client, workflow_id: str, first_run: str) -> list[Workfl
     return out
 
 
-def snapshot(history: WorkflowHistory) -> dict[str, Any]:
+async def snapshot(history: WorkflowHistory) -> dict[str, Any]:
     """The snapshot a run continued with: the continued run's input."""
     attrs = history.events[-1].workflow_execution_continued_as_new_event_attributes
-    return dict(json.loads(attrs.input.payloads[0].data)["snapshot"])
+    return dict((await opened(attrs.input.payloads[0]))["snapshot"])
 
 
 def count(histories: list[WorkflowHistory], kind: int) -> int:
@@ -80,9 +80,7 @@ async def test_a_long_run_continues_as_new_and_ends_as_it_would_have(env: Workfl
     assert len(runs) >= 2, "it never continued as new"
     assert (result.status, result.outputs) == ("succeeded", {"items": list(range(40))})
     assert result.iterations == 40  # the budget carried over: no fresh cap after continue-as-new
-    continued = json.loads(
-        runs[0].events[-1].workflow_execution_continued_as_new_event_attributes.input.payloads[0].data
-    )
+    continued = await opened(runs[0].events[-1].workflow_execution_continued_as_new_event_attributes.input.payloads[0])
     assert continued["iterations"] == continued["snapshot"]["scheduler"]["budget"]["used"] > 0  # outside it too (M6)
     rows = [r for r in store.steps(run_id_of(handle)) if r.node_key == "x"]
     assert len(rows) == 40 and {(r.attempt, r.status) for r in rows} == {(1, "succeeded")}
@@ -200,7 +198,7 @@ async def test_draining_settles_what_is_outstanding_and_a_timer_keeps_its_wake_t
     started = count(runs, EventType.EVENT_TYPE_CHILD_WORKFLOW_EXECUTION_STARTED)
     assert started == 3  # two batches and the sub-flow, none restarted
     assert count(runs, EventType.EVENT_TYPE_CHILD_WORKFLOW_EXECUTION_TERMINATED) == 0
-    carried = [s for s in (snapshot(h) for h in runs[:-1]) if s["timers"]]
+    carried = [s for s in [await snapshot(h) for h in runs[:-1]] if s["timers"]]
     assert carried, "the timer never went into a snapshot"
     [delay] = [r for r in store.steps(run_id_of(handle)) if r.node_key == "d"]
     assert delay.started_at and delay.ended_at
@@ -236,7 +234,7 @@ async def test_the_headroom_draining_adds_is_measured_and_bounded(own_env: Workf
         runs = await chain(own_env.client, handle.id, handle.first_execution_run_id or "")
     assert result.status == "succeeded", result.error
     assert len(runs) >= 2, "it never drained"
-    drained = snapshot(runs[0])["drained"]
+    drained = (await snapshot(runs[0]))["drained"]
     assert drained["units"] == {"activities": 90, "children": 10}  # the cap was saturated when draining began
     (began, continued), (size_began, size_continued) = drained["events"], drained["bytes"]
     during = [e for e in runs[0].events if began < e.event_id <= continued]
@@ -330,7 +328,7 @@ async def test_a_continued_sub_flow_that_cant_load_its_version_reports_what_it_u
         result = await asyncio.wait_for(handle.result(), 60)
         [child] = [run_id for run_id, row in store.starts.items() if row.kind == "subflow"]
         started = (await env.client.get_workflow_handle(run_workflow_id(TENANT, child)).fetch_history()).events[0]
-    carried = json.loads(started.workflow_execution_started_event_attributes.input.payloads[0].data)["iterations"]
+    carried = (await opened(started.workflow_execution_started_event_attributes.input.payloads[0]))["iterations"]
     assert store.loads == 2 and carried > 0  # it continued as new, then couldn't run its version
     assert (store.runs[child].error_code, store.runs[child].iterations) == ("version_unusable", carried)
     assert result.error is not None
diff --git a/backend/tests/apps/worker/test_run_graph_ids.py b/backend/tests/apps/worker/test_run_graph_ids.py
index a5a73d7..81a0edc 100644
--- a/backend/tests/apps/worker/test_run_graph_ids.py
+++ b/backend/tests/apps/worker/test_run_graph_ids.py
@@ -10,8 +10,10 @@ from typing import Any
 import pytest
 from temporalio.client import WorkflowFailureError
 from temporalio.exceptions import ApplicationError
+from temporalio.service import RPCError
 from temporalio.testing import WorkflowEnvironment
 
+from dewpoint.apps.codec import CodecRefusedError
 from dewpoint.engine.runtime.activities import BATCH, ENGINE_QUEUE, BatchInput, Parent, RunInput
 from dewpoint.engine.runtime.execution import INTERNAL_ERROR
 from dewpoint.engine.runtime.ids import run_workflow_id
@@ -37,8 +39,9 @@ async def refused(handle: Any) -> ApplicationError:
 
 
 def ids(run_id: str) -> list[str]:
-    """Workflow ids that don't name TENANT's run `run_id`."""
-    return [run_workflow_id(OTHER, run_id), run_workflow_id(TENANT, OTHER), run_id]
+    """Workflow ids that don't name TENANT's run `run_id`. One that names no tenant never gets this far: the client's
+    codec refuses to encode its input (test_a_workflow_id_that_names_no_tenant_is_never_started)."""
+    return [run_workflow_id(OTHER, run_id), run_workflow_id(TENANT, OTHER)]
 
 
 async def test_a_run_refuses_a_workflow_id_of_another_tenant_or_run(env: WorkflowEnvironment) -> None:
@@ -69,3 +72,15 @@ async def test_a_batch_refuses_a_workflow_id_of_another_tenant_or_run(env: Workf
             failure = await refused(handle)
             assert (failure.type, failure.message, failure.non_retryable) == (INTERNAL_ERROR, REFUSED, True)
     assert (store.starts, store.runs, store.rows) == ({}, {}, {})
+
+
+async def test_a_workflow_id_that_names_no_tenant_is_never_started(env: WorkflowEnvironment) -> None:
+    """An id from before 2b-1a, or any other: the client's codec has no key to encrypt the start with (spec §6.2)."""
+    store = MemoryStore()
+    version = store.add(graph().node("a", "testkit.echo@1", {"value": 1}))
+    run_id = str(uuid.uuid4())
+    start = RunInput(TENANT, run_id, version, {})
+    with pytest.raises(CodecRefusedError, match="No tenant"):
+        await env.client.start_workflow(RunGraph.run, start, id=run_id, task_queue=ENGINE_QUEUE)
+    with pytest.raises(RPCError, match="not found"):  # nothing reached Temporal
+        await env.client.get_workflow_handle(run_id).describe()
diff --git a/backend/tests/engine/replay/record.py b/backend/tests/engine/replay/record.py
index ffd8232..137a8aa 100644
--- a/backend/tests/engine/replay/record.py
+++ b/backend/tests/engine/replay/record.py
@@ -7,7 +7,8 @@ the command sequence increments ENGINE_ABI (`dewpoint.engine`), which starts a n
 A scenario records every execution it ran: `<name>.json` is the run's first execution, and `<name>--<n>.json` each
 other one, in the order they're found: the runs it continued as, then its children's, and theirs. Each file keeps its
 execution's workflow id beside the events (`workflowId`): the workflows check that it names their tenant and run
-(engine 2b spec §6.1), so a replay needs the one they ran under."""
+(engine 2b spec §6.1), so a replay needs the one they ran under. Payloads are recorded encrypted, with fixture keys
+(`tests.support.keys`), and replay decrypts them with the same (§12)."""
 
 import asyncio
 import contextlib
@@ -29,6 +30,7 @@ from dewpoint.engine.runtime.ids import run_workflow_id
 from dewpoint.engine.runtime.workflow import RunGraph
 from tests.apps.worker.harness import TENANT, MemoryStore, workers
 from tests.engine.replay.scenarios import scenarios
+from tests.support.keys import FIXTURE_CONVERTER
 
 HERE = Path(__file__).parent
 SCRUBBED = {"identity": "replay-recorder", "stackTrace": ""}  # host names and local paths stay out of the repo
@@ -91,7 +93,10 @@ async def record() -> list[str]:
         return []
     target.mkdir(exist_ok=True)
     store = RecorderStore()
-    async with await WorkflowEnvironment.start_time_skipping() as env, workers(env.client, store):
+    async with (
+        await WorkflowEnvironment.start_time_skipping(data_converter=FIXTURE_CONVERTER) as env,
+        workers(env.client, store),
+    ):
         for name, scenario in sorted(missing.items()):
             version, run_id = store.add(scenario.build(store)), str(uuid.uuid4())
             if scenario.unusable:
diff --git a/backend/tests/engine/replay/test_replay.py b/backend/tests/engine/replay/test_replay.py
index d1f966f..d39ace6 100644
--- a/backend/tests/engine/replay/test_replay.py
+++ b/backend/tests/engine/replay/test_replay.py
@@ -4,18 +4,23 @@ scenario ran, its continued runs and its children included. A build that keeps t
 the previous build's histories too. The Replayer needs no server."""
 
 import asyncio
+import base64
 import json
 import re
+from collections.abc import Iterator
 from pathlib import Path
+from typing import Any
 
 import pytest
 from temporalio.client import WorkflowHistory
 from temporalio.worker import Replayer
 
+from dewpoint.apps.codec import ENCODING
 from dewpoint.engine import ENGINE_ABI
 from dewpoint.engine.runtime.workflow import LoopBatch, RunGraph
 from tests.engine.replay.record import HERE, build_dir
 from tests.engine.replay.scenarios import scenarios
+from tests.support.keys import FIXTURE_CONVERTER
 
 HISTORIES = sorted(HERE.glob(f"*+abi{ENGINE_ABI}/*.json"))
 
@@ -32,10 +37,47 @@ def test_recorded_histories_carry_no_host_data() -> None:
         assert not re.search(r'"stackTrace": "[^"]', text), path.name
 
 
+# What the SDK's core records beside a local activity's result, in plain JSON and never through a codec: its own
+# bookkeeping, no value of the run's (engine 2b spec §4.6, visible metadata).
+LOCAL_ACTIVITY_MARKER = {
+    "seq",
+    "attempt",
+    "activity_id",
+    "activity_type",
+    "complete_time",
+    "backoff",
+    "original_schedule_time",
+}
+
+
+def payloads(value: Any, path: str = "") -> Iterator[tuple[str, dict[str, Any]]]:
+    if isinstance(value, dict):
+        if isinstance(value.get("metadata"), dict) and "encoding" in value["metadata"]:
+            yield path, value
+        for key, inner in value.items():
+            yield from payloads(inner, f"{path}/{key}")
+    elif isinstance(value, list):
+        for inner in value:
+            yield from payloads(inner, path)
+
+
+def test_recorded_payloads_are_encrypted() -> None:
+    """Engine 2b spec §12: this ABI's histories are recorded with the codec and fixture keys, so every payload in them
+    is encrypted, but for the SDK's own local-activity bookkeeping."""
+    for path in HISTORIES:
+        for where, p in payloads(json.loads(path.read_text())):
+            encoding = base64.b64decode(p["metadata"]["encoding"])
+            if where.endswith("/markerRecordedEventAttributes/details/data/payloads"):
+                assert encoding == b"json/plain", (path.name, where)
+                assert set(json.loads(base64.b64decode(p["data"]))) <= LOCAL_ACTIVITY_MARKER, (path.name, where)
+            else:
+                assert encoding == ENCODING, (path.name, where)
+
+
 @pytest.mark.parametrize(
     "path", HISTORIES, ids=lambda p: p.stem if p.parent == build_dir() else f"{p.parent.name}/{p.stem}"
 )
 async def test_a_golden_history_replays(path: Path) -> None:
     data = json.loads(await asyncio.to_thread(path.read_text))
     history = WorkflowHistory.from_json(data.pop("workflowId"), data)  # the id it ran under (see `record`)
-    await Replayer(workflows=[RunGraph, LoopBatch]).replay_workflow(history)
+    await Replayer(workflows=[RunGraph, LoopBatch], data_converter=FIXTURE_CONVERTER).replay_workflow(history)
diff --git a/backend/tests/support/keys.py b/backend/tests/support/keys.py
index 8cf46fd..da032cf 100644
--- a/backend/tests/support/keys.py
+++ b/backend/tests/support/keys.py
@@ -3,9 +3,17 @@
 today decrypts on any later replay. Never a real key: only tests import this module."""
 
 import hashlib
+import json
+import uuid
 from dataclasses import dataclass, field
+from typing import Any
 
 from cryptography.hazmat.primitives.ciphers.aead import AESGCM
+from temporalio.api.common.v1 import Payload
+from temporalio.converter import WorkflowSerializationContext
+
+from dewpoint.apps.codec import TENANT, TenantCodec, data_converter
+from dewpoint.engine.runtime.ids import run_workflow_id
 
 
 @dataclass
@@ -22,3 +30,16 @@ class FixtureKeys:
         if tenant_id in self.missing:
             raise LookupError(f"no key for tenant {tenant_id}")
         return AESGCM(hashlib.sha256(f"dewpoint-fixture-key|{tenant_id}|{version}".encode()).digest())
+
+
+# Every test server, recorder and replayer of Dewpoint's workflows uses it, as every process uses the keyring's.
+FIXTURE_CONVERTER = data_converter(FixtureKeys())
+
+
+async def opened(payload: Payload) -> Any:
+    """What a payload in a history carries, decrypted with the fixture keys and parsed: tests read what a workflow
+    sent with it. It takes the tenant from the payload's metadata, which only a test may do (the codec never does)."""
+    workflow_id = run_workflow_id(payload.metadata[TENANT].decode(), str(uuid.UUID(int=0)))
+    codec = TenantCodec(FixtureKeys()).with_context(WorkflowSerializationContext("default", workflow_id))
+    [plain] = await codec.decode([payload])
+    return json.loads(plain.data)
````

- [ ] **Step 2: Run them, and watch them fail**

Run: `cd backend && uv run pytest -q -p no:cacheprovider tests/apps/cli/test_dev_run_cli.py tests/apps/test_runs.py tests/apps/worker/test_codec_history.py tests/apps/worker/test_gate_task_cost.py tests/apps/worker/test_main.py tests/apps/worker/test_real_server.py tests/apps/worker/test_run_graph.py tests/apps/worker/test_run_graph_cel_requests.py tests/apps/worker/test_run_graph_children.py tests/apps/worker/test_run_graph_continue.py tests/apps/worker/test_run_graph_ids.py tests/engine/replay/test_replay.py`

Expected: FAIL. The canary finds its payloads in plain text, the goldens aren't encrypted, the clients have no codec, and an unencryptable start isn't refused. The replay showed:

````text
E       KeyError: 'data_converter'
E       Failed: DID NOT RAISE StartRefusedError
E                   AssertionError: ('batches--1.json', '/events/workflowExecutionStartedEventAttributes/input/payloads')
E                   assert b'json/plain' == b'binary/dewpoint-tenant-v1'
E                     
E                     At index 0 diff: b'j' != b'b'
E                     Use -v to get more diff
E                   RuntimeError: 4: Workflow activation completion failed: Failure { failure: Some(Failure { message: "Encoded failure", source: "", stack_trace: "", encoded_attributes: Some([hn0sQrLDK9lEovAKFzrD4LSAOda
ERROR    temporalio.worker._workflow:_workflow.py:440 Failed handling activation on workflow with run ID f0e29117-9692-4c1b-855a-fb015ccea2f1
E                   RuntimeError: 4: Workflow activation completion failed: Failure { failure: Some(Failure { message: "Encoded failure", source: "", stack_trace: "", encoded_attributes: Some([gBjp38FXNDignkZNJbfywC7CcbL
ERROR    temporalio.worker._workflow:_workflow.py:440 Failed handling activation on workflow with run ID e3cdc142-d894-4f96-8856-cb9fe8f03a5d
E                   RuntimeError: 4: Workflow activation completion failed: Failure { failure: Some(Failure { message: "Encoded failure", source: "", stack_trace: "", encoded_attributes: Some([eKqWJGmeEfkicrvJwBtwWv6kevO
ERROR    temporalio.worker._workflow:_workflow.py:440 Failed handling activation on workflow with run ID 943f411f-83ce-4da8-af3b-b1951e1f313c
E                   RuntimeError: 4: Workflow activation completion failed: Failure { failure: Some(Failure { message: "Encoded failure", source: "", stack_trace: "", encoded_attributes: Some([d4LGhWI05U0V1/J+77mcZGFw+uo
...
E                   RuntimeError: 4: Workflow activation completion failed: Failure { failure: Some(Failure { message: "Encoded failure", source: "", stack_trace: "", encoded_attributes: Some([HW/slSiQ0BGTf/YGmIVGehgu7nd
````

- [ ] **Step 3: Implement**

````diff
diff --git a/backend/src/dewpoint/apps/cli/main.py b/backend/src/dewpoint/apps/cli/main.py
index b24d232..917f401 100644
--- a/backend/src/dewpoint/apps/cli/main.py
+++ b/backend/src/dewpoint/apps/cli/main.py
@@ -4,7 +4,8 @@ import base64
 import json
 import os
 import uuid
-from collections.abc import Awaitable, Callable
+from collections.abc import AsyncIterator, Awaitable, Callable
+from contextlib import asynccontextmanager
 from dataclasses import asdict
 from datetime import timedelta
 from pathlib import Path
@@ -15,6 +16,7 @@ from sqlalchemy import select
 from sqlalchemy.ext.asyncio import AsyncSession
 from temporalio.client import Client
 
+from dewpoint.apps.codec import KeyringKeys, data_converter
 from dewpoint.apps.environment import verify_environment
 from dewpoint.apps.plugin_loader import PluginLoadError, installed_plugins, prepare
 from dewpoint.apps.runs import NotAdmissibleError, StartRefusedError, StartUncertainError, start_run
@@ -353,18 +355,25 @@ def worker() -> None:
         raise typer.Exit(2) from None
 
 
-async def _temporal() -> Client:
-    """A Temporal client, once this process's namespace is the one this deployment recorded (engine 2b spec §2.1)."""
+@asynccontextmanager
+async def _temporal() -> AsyncIterator[Client]:
+    """A Temporal client, once this process's namespace is the one this deployment recorded (engine 2b spec §2.1).
+    Its payloads are encrypted with each tenant's key, read through this process's database role (§6.2–6.3)."""
     settings = get_settings()
     engine = make_engine(settings.database_url)
     try:
-        await verify_environment(make_sessionmaker(engine), settings)
-    except (EnvironmentNotRecordedError, EnvironmentMismatchError) as e:
-        typer.echo(f"ERROR: {e}")
-        raise typer.Exit(2) from None
+        sessionmaker = make_sessionmaker(engine)
+        try:
+            await verify_environment(sessionmaker, settings)
+        except (EnvironmentNotRecordedError, EnvironmentMismatchError) as e:
+            typer.echo(f"ERROR: {e}")
+            raise typer.Exit(2) from None
+        keys = KeyringKeys(sessionmaker, Keyring(KekSet.from_settings(settings)))
+        yield await Client.connect(
+            settings.temporal_address, namespace=settings.temporal_namespace, data_converter=data_converter(keys)
+        )
     finally:
         await engine.dispose()
-    return await Client.connect(settings.temporal_address, namespace=settings.temporal_namespace)
 
 
 @platform_cli.command("init-environment")
@@ -408,7 +417,8 @@ def deployment_set_current(
     target = build or this_build()
 
     async def _go() -> None:
-        await set_current(await _temporal(), target, wait_s=wait)
+        async with _temporal() as client:
+            await set_current(client, target, wait_s=wait)
 
     asyncio.run(_go())
     typer.echo(f"current: {target}")
@@ -419,7 +429,8 @@ def deployment_status() -> None:
     """The build new runs start on, and every version with its status: a draining one still serves its runs."""
 
     async def _go() -> Deployment:
-        return await describe(await _temporal())
+        async with _temporal() as client:
+            return await describe(client)
 
     deployment = asyncio.run(_go())
     typer.echo(f"current: {deployment.current or 'none'}")
@@ -472,17 +483,16 @@ def dev_run(
         raise typer.Exit(2)
 
     async def _go() -> tuple[uuid.UUID, RunResult | None]:
-        settings = get_settings()
-        client = await _temporal()
-        return await dev_run_version(
-            settings,
-            client,
-            tenant_id=uuid.UUID(tenant),
-            version_id=version_id,
-            trigger=trigger,
-            simulate=simulate,
-            wait=wait,
-        )
+        async with _temporal() as client:
+            return await dev_run_version(
+                get_settings(),
+                client,
+                tenant_id=uuid.UUID(tenant),
+                version_id=version_id,
+                trigger=trigger,
+                simulate=simulate,
+                wait=wait,
+            )
 
     try:
         run_id, result = asyncio.run(_go())
diff --git a/backend/src/dewpoint/apps/runs.py b/backend/src/dewpoint/apps/runs.py
index e3cd497..84e60ec 100644
--- a/backend/src/dewpoint/apps/runs.py
+++ b/backend/src/dewpoint/apps/runs.py
@@ -22,6 +22,7 @@ from typing import Any
 from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
 from temporalio.client import Client
 from temporalio.common import WorkflowIDReusePolicy
+from temporalio.converter import WorkflowSerializationContext
 from temporalio.exceptions import WorkflowAlreadyStartedError
 from temporalio.service import RPCError, RPCStatusCode
 
@@ -178,6 +179,12 @@ async def start_run(
 
 
 async def _start(client: Client, start: RunInput, run_id: uuid.UUID) -> None:
+    workflow_id = run_workflow_id(start.tenant_id, str(run_id))
+    context = WorkflowSerializationContext(namespace=client.namespace, workflow_id=workflow_id)
+    try:  # encrypted with its tenant's key first (engine 2b spec §6.2): a start that can't be was never sent
+        await client.data_converter.with_context(context).encode([start])
+    except Exception as e:
+        raise StartRefusedError(f"The run's start couldn't be encrypted ({type(e).__name__}).") from e
     uncertain = False
     last: BaseException | None = None
     for wait in (*START_RETRY_S, None):
@@ -185,7 +192,7 @@ async def _start(client: Client, start: RunInput, run_id: uuid.UUID) -> None:
             await client.start_workflow(
                 RunGraph.run,
                 start,
-                id=run_workflow_id(start.tenant_id, str(run_id)),
+                id=workflow_id,
                 task_queue=ENGINE_QUEUE,
                 id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
             )
diff --git a/backend/src/dewpoint/apps/worker/main.py b/backend/src/dewpoint/apps/worker/main.py
index f5a3081..86a9d42 100644
--- a/backend/src/dewpoint/apps/worker/main.py
+++ b/backend/src/dewpoint/apps/worker/main.py
@@ -13,12 +13,15 @@ from temporalio.client import Client
 from temporalio.worker import Worker
 
 from dewpoint.apps import cel_client
+from dewpoint.apps.codec import KeyringKeys, data_converter
 from dewpoint.apps.environment import verify_environment
 from dewpoint.apps.plugin_loader import installed_plugins
 from dewpoint.apps.worker.activities import RunStore, cel_activity, engine_activities, remote_evaluator
 from dewpoint.apps.worker.deployment import deployment_config, set_current, this_build
 from dewpoint.apps.worker.store import DbRunStore
 from dewpoint.core.config import Settings
+from dewpoint.core.crypto.kek import KekSet
+from dewpoint.core.crypto.keyring import Keyring
 from dewpoint.core.db import make_engine, make_sessionmaker
 from dewpoint.engine import ENGINE_ABI
 from dewpoint.engine.runtime.activities import ENGINE_QUEUE, cel_queue
@@ -80,12 +83,17 @@ async def promote(client: Client) -> None:
 
 async def run(settings: Settings) -> None:
     """Raises EnvironmentNotRecordedError or EnvironmentMismatchError before connecting to Temporal: a worker never
-    serves a namespace its database wasn't recorded with (engine 2b spec §2.1)."""
+    serves a namespace its database wasn't recorded with (engine 2b spec §2.1). Every payload it sends or reads is
+    encrypted with its tenant's key, read through the worker's role (§6.2–6.3)."""
     engine = make_engine(settings.database_url)
     try:
-        await verify_environment(make_sessionmaker(engine), settings)
-        client = await Client.connect(settings.temporal_address, namespace=settings.temporal_namespace)
-        workers = [engine_worker(client, DbRunStore(make_sessionmaker(engine)), installed_plugins(), settings)]
+        sessionmaker = make_sessionmaker(engine)
+        await verify_environment(sessionmaker, settings)
+        keys = KeyringKeys(sessionmaker, Keyring(KekSet.from_settings(settings)))
+        client = await Client.connect(
+            settings.temporal_address, namespace=settings.temporal_namespace, data_converter=data_converter(keys)
+        )
+        workers = [engine_worker(client, DbRunStore(sessionmaker), installed_plugins(), settings)]
         if settings.cel_socket:
             profile = await evaluator_profile(settings.cel_socket)
             log.info("cel_queue", profile=profile)
````

- [ ] **Step 4: Record the abi5 golden histories again, encrypted**

Run: `cd backend && git rm -q -r tests/engine/replay/dewpoint-0.1.0+abi5 && uv run python -m tests.engine.replay.record`
Expected: the same `recorded ...` line as Task 3's. `git status` shows the directory's files as deleted and added again;
relative to `main` they're all additions, which the replay gate accepts.

- [ ] **Step 5: Run the tests again**

Run: `cd backend && uv run pytest -q -p no:cacheprovider tests/apps/cli/test_dev_run_cli.py tests/apps/test_runs.py tests/apps/worker/test_codec_history.py tests/apps/worker/test_gate_task_cost.py tests/apps/worker/test_main.py tests/apps/worker/test_real_server.py tests/apps/worker/test_run_graph.py tests/apps/worker/test_run_graph_cel_requests.py tests/apps/worker/test_run_graph_children.py tests/apps/worker/test_run_graph_continue.py tests/apps/worker/test_run_graph_ids.py tests/engine/replay/test_replay.py`

Expected (the replay):

````text
165 passed in 94.92s (0:01:34)
````

- [ ] **Step 6: The whole suite, lint, types and layers**

Run: `cd backend && uv run pytest -q -p no:cacheprovider`, then `uv run ruff check --no-cache src tests migrations`, `uv run ruff format --no-cache --check src tests migrations`, `uv run mypy src` and `uv run lint-imports`.

Expected: 1,159 passed, 8 skipped; ruff and its formatter clean; mypy: no issues; import-linter: 10 contracts kept.

- [ ] **Step 7: Commit**

```bash
git add -A backend deploy docs && git commit -m "feat(codec): the tenant codec on every client, worker, test server and replayer (2b-1a)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Temporal's behavior 2b relies on, as committed checks

**Spec:** §11.1.

**Files:**
- Create: `backend/tests/apps/worker/test_temporal_contract.py`

**Interfaces:**
- Consumes: Task 4's codec, Task 6's `FIXTURE_CONVERTER`, `opened`, the session `dev_env`.
- Produces: `backend/tests/apps/worker/test_temporal_contract.py`.

The go/no-go experiments become tests on the CLI dev server, pinned to the SDK and server versions they
were measured on. `test_the_versions_these_checks_were_measured_on` fails on any other version, so an upgrade has to
verify them again. They use test-only workflows, through a recording tenant codec, with two tenants side by side:
- every path encodes and decodes under the tenant its workflow id names, replay included;
- a schedule's `TemporalScheduledStartTime` is whole seconds, the same under replay; a backfill over times that
  already fired starts them again; missed times catch up after an outage;
- the SDK checks a payload's size after the codec (`TMPRL1103`), and a payload that fits with `CODEC_OVERHEAD` goes
  through;
- three 1.5 MiB commands in one workflow task get the workflow terminated; two complete.

These describe Temporal, so there's no implementation to write. Each has a control case: a path with no context
fails its run, a smaller payload passes, two commands complete. The test's power comes from those, not from a red
step.

- [ ] **Step 1: Write the tests**

````diff
diff --git a/backend/tests/apps/worker/test_temporal_contract.py b/backend/tests/apps/worker/test_temporal_contract.py
new file mode 100644
index 0000000..765bb19
--- /dev/null
+++ b/backend/tests/apps/worker/test_temporal_contract.py
@@ -0,0 +1,411 @@
+# SPDX-License-Identifier: Apache-2.0
+"""What 2b's design takes from Temporal itself (engine 2b spec §11.1), pinned to the versions it was measured on. An
+upgrade that changes any of it fails a test here, and the spec's premises are verified again before it lands.
+
+Test-only workflows on the CLI dev server, through the tenant codec with fixture keys, two tenants side by side:
+- every payload, on every path, is encoded and decoded with a context whose workflow id names its tenant;
+- a schedule's `TemporalScheduledStartTime` is whole seconds and the same under replay, and a backfill over a time
+  that already fired starts a second execution with the same time;
+- the SDK checks a payload's size after the codec;
+- a workflow task whose completion passes the gRPC message limit gets its workflow terminated."""
+
+import asyncio
+import contextlib
+import dataclasses
+import uuid
+from collections.abc import AsyncIterator, Sequence
+from datetime import UTC, datetime, timedelta
+from pathlib import Path
+from typing import Any
+
+import temporalio
+from temporalio import activity, workflow
+from temporalio.api.common.v1 import Payload
+from temporalio.api.enums.v1 import EventType
+from temporalio.api.workflowservice.v1 import GetSystemInfoRequest
+from temporalio.client import (
+    Client,
+    Schedule,
+    ScheduleActionStartWorkflow,
+    ScheduleBackfill,
+    ScheduleIntervalSpec,
+    ScheduleOverlapPolicy,
+    SchedulePolicy,
+    ScheduleSpec,
+    ScheduleState,
+    WorkflowExecutionStatus,
+    WorkflowFailureError,
+    WorkflowHandle,
+    WorkflowHistory,
+)
+from temporalio.common import RetryPolicy, SearchAttributeKey
+from temporalio.converter import ActivitySerializationContext, DataConverter, SerializationContext
+from temporalio.exceptions import ActivityError, ApplicationError, ChildWorkflowError
+from temporalio.testing import WorkflowEnvironment
+from temporalio.worker import Replayer, UnsandboxedWorkflowRunner, Worker
+
+from dewpoint.apps.codec import CODEC_OVERHEAD, TENANT, KeySource, TenantCodec, data_converter
+from dewpoint.engine.runtime.ids import run_workflow_id, tenant_of
+from tests.support.keys import FixtureKeys, opened
+
+SDK, SERVER = "1.33.0", "1.32.0"  # what §11.1 measured
+PAYLOAD_LIMIT = 2 * 1024 * 1024  # Temporal's per-payload limit, which the SDK checks
+QUEUE = "temporal-contract"
+A, B = str(uuid.uuid4()), str(uuid.uuid4())
+SCHEDULED = SearchAttributeKey.for_datetime("TemporalScheduledStartTime")
+TIMEOUT = timedelta(seconds=10)
+
+CALLS: list[tuple[str, str, str | None]] = []  # (encode or decode, the context's kind, the tenant it names)
+TICKS: list[tuple[str, str | None, bool]] = []  # (a tick's workflow id, its TemporalScheduledStartTime, replaying)
+
+
+class Recording(TenantCodec):
+    """The tenant codec, recording each call's context: which paths the SDK gives one to, and whose tenant it names."""
+
+    def __init__(self, keys: KeySource, tenant_id: str | None = None, kind: str = "none") -> None:
+        super().__init__(keys, tenant_id)
+        self.keys, self.tenant_id, self.kind = keys, tenant_id, kind
+
+    def with_context(self, context: SerializationContext) -> "Recording":
+        workflow_id = getattr(context, "workflow_id", None)
+        local = isinstance(context, ActivitySerializationContext) and context.is_local
+        kind = "local activity" if local else type(context).__name__
+        return Recording(self.keys, tenant_of(workflow_id) if workflow_id else None, kind)
+
+    async def encode(self, payloads: Sequence[Payload]) -> list[Payload]:
+        CALLS.append(("encode", self.kind, self.tenant_id))
+        return await super().encode(payloads)
+
+    async def decode(self, payloads: Sequence[Payload]) -> list[Payload]:
+        CALLS.append(("decode", self.kind, self.tenant_id))
+        return await super().decode(payloads)
+
+
+RECORDING = dataclasses.replace(data_converter(FixtureKeys()), payload_codec=Recording(FixtureKeys()))
+
+
+@activity.defn
+async def echo(value: dict[str, Any]) -> dict[str, Any]:
+    return value
+
+
+@activity.defn
+async def fail(value: dict[str, Any]) -> dict[str, Any]:
+    raise ApplicationError("the activity failed", {"detail": "d"}, non_retryable=True)
+
+
+@activity.defn
+async def beat(value: dict[str, Any]) -> dict[str, Any]:
+    activity.heartbeat({"progress": 1})
+    return value
+
+
+@activity.defn
+async def sink(value: str) -> int:
+    return len(value)
+
+
+@workflow.defn
+class Child:
+    def __init__(self) -> None:
+        self.released = False
+
+    @workflow.signal
+    def release(self, value: dict[str, Any]) -> None:
+        self.released = True
+
+    @workflow.run
+    async def run(self, start: dict[str, Any]) -> dict[str, Any]:
+        await workflow.execute_activity(echo, {"from": "child"}, start_to_close_timeout=TIMEOUT)
+        if not start.get("continued"):
+            await workflow.get_external_workflow_handle(start["parent"]).signal("arrived", workflow.info().workflow_id)
+            await workflow.wait_condition(lambda: self.released)
+            if start.get("continue"):
+                workflow.continue_as_new({**start, "continued": True})
+        if start.get("fail"):
+            raise ApplicationError("the child failed", {"detail": "d"}, non_retryable=True)
+        return {"continued": bool(start.get("continued"))}
+
+
+@workflow.defn
+class Parent:
+    """Every path a Dewpoint run takes: activities, their failures and heartbeats; a local activity; children started,
+    signalled both ways, continued as new and failed; a batch-style child id; continue-as-new."""
+
+    def __init__(self) -> None:
+        self.arrived: set[str] = set()
+
+    @workflow.signal(name="arrived")
+    def on_arrived(self, child_id: str) -> None:
+        self.arrived.add(child_id)
+
+    async def child(self, child_id: str, **start: Any) -> Any:
+        me = workflow.info().workflow_id
+        handle = await workflow.start_child_workflow(Child.run, {"parent": me, **start}, id=child_id)
+        await workflow.wait_condition(lambda: child_id in self.arrived)
+        await handle.signal(Child.release, {})
+        return await handle
+
+    @workflow.run
+    async def run(self, start: dict[str, Any]) -> dict[str, Any]:
+        tenant, me = start["tenant"], workflow.info().workflow_id
+        await workflow.execute_activity(echo, {"tenant_id": tenant}, start_to_close_timeout=TIMEOUT)
+        if start.get("continued"):
+            return {"tenant": tenant}
+        await workflow.execute_local_activity(echo, {"local": True}, start_to_close_timeout=TIMEOUT)
+        try:
+            await workflow.execute_activity(
+                fail, {}, start_to_close_timeout=TIMEOUT, retry_policy=RetryPolicy(maximum_attempts=1)
+            )
+        except ActivityError:
+            pass
+        await workflow.execute_activity(beat, {}, start_to_close_timeout=TIMEOUT, heartbeat_timeout=TIMEOUT)
+        await self.child(run_workflow_id(tenant, str(workflow.uuid4())), **{"continue": True})
+        await self.child(f"{me}/step/l:0/batch:0")
+        try:
+            await self.child(run_workflow_id(tenant, str(workflow.uuid4())), fail=True)
+        except ChildWorkflowError:
+            pass
+        workflow.continue_as_new({**start, "continued": True})
+
+
+@workflow.defn
+class Failer:
+    @workflow.run
+    async def run(self, start: dict[str, Any]) -> None:
+        raise ApplicationError("the workflow failed", {"detail": "d"}, non_retryable=True)
+
+
+@workflow.defn
+class Tick:
+    @workflow.run
+    async def run(self, schedule_id: str) -> str | None:
+        at = workflow.info().typed_search_attributes.get(SCHEDULED)
+        stamp = at.isoformat() if at else None
+        TICKS.append((workflow.info().workflow_id, stamp, workflow.unsafe.is_replaying()))
+        await workflow.execute_activity(echo, {"at": stamp}, start_to_close_timeout=TIMEOUT)
+        return stamp
+
+
+@workflow.defn
+class Sends:
+    @workflow.run
+    async def run(self, sizes: list[int]) -> list[int]:
+        """One activity per size, all scheduled in the same workflow task."""
+        sent = [workflow.execute_activity(sink, "x" * n, start_to_close_timeout=TIMEOUT) for n in sizes]
+        return list(await asyncio.gather(*sent))
+
+
+WORKFLOWS = [Parent, Child, Failer, Tick, Sends]
+
+
+@contextlib.asynccontextmanager
+async def serving(client: Client) -> AsyncIterator[None]:
+    async with Worker(
+        client,
+        task_queue=QUEUE,
+        workflows=WORKFLOWS,
+        activities=[echo, fail, beat, sink],
+        workflow_runner=UnsandboxedWorkflowRunner(),
+    ):
+        yield
+
+
+async def begin(client: Client, run: Any, arg: Any, tenant: str = A) -> WorkflowHandle[Any, Any]:
+    """A run of a test workflow, under a workflow id that names `tenant`, as Dewpoint builds them (spec §6.1)."""
+    return await client.start_workflow(run, arg, id=run_workflow_id(tenant, str(uuid.uuid4())), task_queue=QUEUE)
+
+
+async def histories(client: Client, query: str) -> list[WorkflowHistory]:
+    return [
+        await client.get_workflow_handle(w.id, run_id=w.run_id).fetch_history()
+        async for w in client.list_workflows(query)
+    ]
+
+
+async def test_the_versions_these_checks_were_measured_on(dev_env: WorkflowEnvironment) -> None:
+    info = await dev_env.client.workflow_service.get_system_info(GetSystemInfoRequest())
+    assert (temporalio.__version__, info.server_version) == (SDK, SERVER)
+
+
+async def test_every_path_encrypts_under_the_tenant_its_workflow_id_names(dev_env: WorkflowEnvironment) -> None:
+    """§11.1, experiment 1: the codec refuses without a tenant, so a path with no context fails its run. Each run's
+    calls name only its own tenant, and the recording shows which paths ran: workflow and activity sides, local
+    activities, children, signals, continue-as-new, failures with encoded attributes, and a replay of all of it."""
+    CALLS.clear()
+    client = Client(dev_env.client.service_client, namespace=dev_env.client.namespace, data_converter=RECORDING)
+    async with serving(client):
+        parents = [await begin(client, Parent.run, {"tenant": t}, t) for t in (A, B)]
+        assert await asyncio.gather(*(h.result() for h in parents)) == [{"tenant": A}, {"tenant": B}]
+        failer = await begin(client, Failer.run, {})
+        try:
+            await failer.result()
+            raise AssertionError("the workflow didn't fail")
+        except WorkflowFailureError as e:  # its message went encrypted, and came back decrypted
+            assert isinstance(e.cause, ApplicationError) and e.cause.message == "the workflow failed"
+    assert {tenant for _, _, tenant in CALLS} == {A, B}
+    assert {(op, kind) for op, kind, _ in CALLS} >= {
+        (op, kind)
+        for op in ("encode", "decode")
+        for kind in ("WorkflowSerializationContext", "ActivitySerializationContext", "local activity")
+    }
+    CALLS.clear()
+    await replay([Parent, Child], await histories(client, "WorkflowType='Parent' OR WorkflowType='Child'"))
+    assert CALLS and {tenant for _, _, tenant in CALLS} == {A, B}
+
+
+async def test_a_schedules_time_is_whole_seconds_the_same_on_replay_and_a_backfill_repeats_it(
+    dev_env: WorkflowEnvironment,
+) -> None:
+    """§11.1, experiment 1: `ScheduleTick` (2b-3) keys its request on `TemporalScheduledStartTime`. Temporal gives it
+    in whole seconds, and replay sees the same; a backfill over a time that already fired starts another execution
+    with the same time, which the key collapses (spec §8.2). The schedule's own payloads go through the codec too:
+    its id names the tenant, as its workflows' ids do."""
+    TICKS.clear()
+    client = Client(dev_env.client.service_client, namespace=dev_env.client.namespace, data_converter=RECORDING)
+    schedule_id = f"t:{B}:sched:{uuid.uuid4()}"
+    async with serving(client):
+        handle = await client.create_schedule(
+            schedule_id,
+            Schedule(
+                action=ScheduleActionStartWorkflow(Tick.run, schedule_id, id=schedule_id, task_queue=QUEUE),
+                spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=timedelta(minutes=1))]),
+                policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.ALLOW_ALL),
+                state=ScheduleState(paused=True),  # only the backfills fire
+            ),
+        )
+        described = await handle.describe()
+        assert isinstance(described.schedule.action, ScheduleActionStartWorkflow)
+        [arg] = described.schedule.action.args  # as Temporal holds it: sealed under the schedule's tenant
+        assert isinstance(arg, Payload) and arg.metadata[TENANT] == B.encode() and await opened(arg) == schedule_id
+        end = described.info.created_at.replace(second=0, microsecond=0)
+        start = end - timedelta(minutes=2)
+        window = ScheduleBackfill(start_at=start, end_at=end, overlap=ScheduleOverlapPolicy.ALLOW_ALL)
+        await handle.backfill(window)
+        await ticked(client, 3)
+        await handle.backfill(window)  # the same times again, once the first three have ended
+        await ticked(client, 6)
+        runs = await ticks_of(client, schedule_id)
+        await handle.delete()
+    times = stamps(replaying=False)
+    assert all(t.endswith(":00+00:00") for t in times), times  # whole seconds: whole minutes, here
+    assert len(times) == 6 and len(set(times)) == 3  # the second backfill started each time again
+    TICKS.clear()
+    await replay([Tick], runs)
+    assert stamps(replaying=True) == times
+
+
+async def replay(workflows: list[type], runs: list[WorkflowHistory]) -> None:
+    """Every history, replayed through the recording codec: a nondeterminism, or a path without a tenant, raises."""
+
+    async def each() -> AsyncIterator[WorkflowHistory]:
+        for run in runs:
+            yield run
+
+    replayer = Replayer(workflows=workflows, data_converter=RECORDING, workflow_runner=UnsandboxedWorkflowRunner())
+    await replayer.replay_workflows(each())
+
+
+async def ticks_of(client: Client, schedule_id: str) -> list[WorkflowHistory]:
+    return [h for h in await histories(client, "WorkflowType='Tick'") if h.workflow_id.startswith(schedule_id)]
+
+
+def stamps(*, replaying: bool) -> list[str]:
+    """The `TemporalScheduledStartTime` each tick saw, running or replaying."""
+    return sorted(s for _, s, r in TICKS if r == replaying and s)
+
+
+async def ticked(client: Client, n: int) -> None:
+    """Until `n` ticks have run to their end."""
+    for _ in range(120):
+        if len([w for w, _, replaying in TICKS if not replaying]) >= n:
+            break
+        await asyncio.sleep(0.5)
+    for workflow_id, _, replaying in list(TICKS):
+        if not replaying:
+            await asyncio.wait_for(client.get_workflow_handle(workflow_id).result(), 30)
+
+
+def plain_bytes(n: int) -> int:
+    """What the SDK measures of an `n`-character string's payload before the codec."""
+    [p] = DataConverter.default.payload_converter.to_payloads(["x" * n])
+    return p.ByteSize()
+
+
+async def task_failures(handle: WorkflowHandle[Any, Any]) -> list[str]:
+    return [
+        e.workflow_task_failed_event_attributes.failure.message
+        async for e in handle.fetch_history_events()
+        if e.event_type == EventType.EVENT_TYPE_WORKFLOW_TASK_FAILED
+    ]
+
+
+async def test_the_sdk_checks_a_payloads_size_after_the_codec(dev_env: WorkflowEnvironment) -> None:
+    """§11.1, experiment 2: a payload under the limit before the codec, over it once encrypted, fails its workflow
+    task, which retries. So a guard counts the codec's overhead (CODEC_OVERHEAD): one that fits with it passes."""
+    over = PAYLOAD_LIMIT - 64
+    while plain_bytes(over) >= PAYLOAD_LIMIT:
+        over -= 1
+    fits = over - CODEC_OVERHEAD
+    client = dev_env.client
+    async with serving(client):
+        ok = await begin(client, Sends.run, [fits])
+        assert await asyncio.wait_for(ok.result(), 30) == [fits]
+        refused = await begin(client, Sends.run, [over])
+        failures: list[str] = []
+        for _ in range(60):
+            failures = await task_failures(refused)
+            if failures:
+                break
+            await asyncio.sleep(0.25)
+        await refused.terminate("checked")
+    assert plain_bytes(over) < PAYLOAD_LIMIT and failures and "TMPRL1103" in failures[0], failures[:1]
+
+
+async def test_a_completion_past_the_grpc_limit_gets_its_workflow_terminated(dev_env: WorkflowEnvironment) -> None:
+    """§11.1, experiment 2: three commands of 1.5 MiB in one workflow task pass the 4 MiB gRPC message limit; Temporal
+    terminates the workflow, with no chance to record an end (spec §5.2's per-task invariant). Two of them fit."""
+    big = 1536 * 1024
+    client = dev_env.client
+    async with serving(client):
+        two = await begin(client, Sends.run, [big] * 2)
+        assert await asyncio.wait_for(two.result(), 60) == [big] * 2
+        three = await begin(client, Sends.run, [big] * 3)
+        with contextlib.suppress(WorkflowFailureError):
+            await asyncio.wait_for(three.result(), 60)
+        status = (await three.describe()).status
+    assert status == WorkflowExecutionStatus.TERMINATED
+
+
+async def test_a_schedules_missed_times_catch_up_after_an_outage_with_their_own_time(tmp_path: Path) -> None:
+    """§11.1, experiment 1: a server that was down fires the times it missed when it's back, within the catch-up
+    window, each with its own `TemporalScheduledStartTime`, and replay sees the same (the 2b-3 tick's key)."""
+    TICKS.clear()
+    args = ["--db-filename", str(tmp_path / "temporal.db")]
+    schedule_id = f"t:{A}:sched:{uuid.uuid4()}"
+    every = timedelta(seconds=5)
+    async with await WorkflowEnvironment.start_local(data_converter=RECORDING, dev_server_extra_args=args) as env:
+        async with serving(env.client):
+            await env.client.create_schedule(
+                schedule_id,
+                Schedule(
+                    action=ScheduleActionStartWorkflow(Tick.run, schedule_id, id=schedule_id, task_queue=QUEUE),
+                    spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=every)]),
+                    policy=SchedulePolicy(catchup_window=timedelta(minutes=1), overlap=ScheduleOverlapPolicy.ALLOW_ALL),
+                ),
+            )
+            await ticked(env.client, 1)
+    down = datetime.now(UTC)
+    await asyncio.sleep(16)  # about three firings missed
+    async with await WorkflowEnvironment.start_local(data_converter=RECORDING, dev_server_extra_args=args) as env:
+        async with serving(env.client):
+            await ticked(env.client, 4)
+            runs = await ticks_of(env.client, schedule_id)
+            await env.client.get_schedule_handle(schedule_id).delete()
+    times = stamps(replaying=False)
+    missed = [t for t in times if datetime.fromisoformat(t) > down]
+    assert len(missed) >= 2, times  # each missed time fired, with its own time
+    assert all(datetime.fromisoformat(t).microsecond == 0 for t in times)
+    TICKS.clear()
+    await replay([Tick], runs)
+    assert stamps(replaying=True) == times
````

- [ ] **Step 2: Run them: each passes, with its control case**

Run: `cd backend && uv run pytest -q -p no:cacheprovider tests/apps/worker/test_temporal_contract.py`

Expected (the replay):

````text
6 passed in 27.21s
````

- [ ] **Step 3: The whole suite, lint, types and layers**

Run: `cd backend && uv run pytest -q -p no:cacheprovider`, then `uv run ruff check --no-cache src tests migrations`, `uv run ruff format --no-cache --check src tests migrations`, `uv run mypy src` and `uv run lint-imports`.

Expected: 1,165 passed, 8 skipped; ruff and its formatter clean; mypy: no issues; import-linter: 10 contracts kept.

- [ ] **Step 4: Commit**

```bash
git add -A backend deploy docs && git commit -m "test(temporal): the Temporal behavior 2b relies on, as committed checks (2b-1a)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Engine worker instances record and prove their capabilities

**Spec:** §2.7.

**Files:**
- Create: `backend/migrations/versions/0012_worker_instances.py`
- Create: `backend/src/dewpoint/apps/worker/health.py`
- Create: `backend/tests/apps/cli/test_worker_cli.py`
- Create: `backend/tests/apps/worker/test_health.py`
- Create: `backend/tests/core/platform/test_workers.py`
- Modify: `backend/src/dewpoint/apps/cli/main.py`
- Modify: `backend/src/dewpoint/apps/worker/main.py`
- Modify: `backend/src/dewpoint/core/crypto/keyring.py`
- Modify: `backend/src/dewpoint/core/models/platform.py`
- Modify: `backend/src/dewpoint/core/platform/service.py`
- Modify: `backend/tests/apps/worker/test_deployment.py`
- Modify: `backend/tests/apps/worker/test_main.py`
- Modify: `backend/tests/core/crypto/test_keyring.py`

**Interfaces:**
- Produces:
  - `dewpoint.apps.worker.health`: `CAPABILITIES`, `HEALTH_INTERVAL_S = 30.0`, `WorkerUnhealthyError`,
    `async self_check(keyring, sessionmaker) -> bool | None`, `reporter(sessionmaker, instance_id, build_id)`,
    `async start_healthy(check, report)`, `async watch(check, report, stop, *, interval_s=HEALTH_INTERVAL_S)`, where
    `check` is an async callable returning `bool | None`;
  - `record_worker(s, *, instance_id, build_id, capabilities, healthy)`;
  - model `WorkerInstance`; `Keyring.self_check()`;
  - in `tests.apps.worker.test_main`: `unrecorded` (a no-op report), `proven` and `failed` (stub checks), for the
    tests that run `main.run` with a stand-in database.
- Consumes: Task 6's worker `run()`.

Each worker instance records itself in `worker_instances` (migration 0012): its build, its capabilities
(`payload_codec`, `cel_request_size_guard`), and whether its self-check passed. The check proves what `payload_codec`
needs of the instance, and answers True, False or None (no answer):
- its KEK wraps and unwraps a fresh key (`Keyring.self_check()`), and
- its database role may read data keys: `has_table_privilege('data_keys', 'SELECT')`, read from the catalog, so the
  answer doesn't depend on a tenant. A missing grant is False; a database that doesn't answer is None.

How it's used:
- `run()` checks and records before it connects to Temporal. Anything but True raises `WorkerUnhealthyError`, and the
  CLI exits 3: an instance that can't prove itself never polls.
- `watch` checks again every 30 s. False stops the workers polling (running attempts get the shutdown grace), then
  raises. None is an outage, which the engine rides out: the instance keeps polling and records nothing, so its row
  goes stale. A record it can't write is only logged, the same way.
- The check is deliberately light. The grant says nothing about what the role's RLS-scoped reads return, and the
  KEK round trip uses a fresh key, not the stored ones: a wrong KEK under the right id passes both, and passes
  `dewpoint keys status` too, which compares KEK ids. Lifting the production gate (2b-4) unwraps every stored key
  and reads each tenant's key along the workers' own path (spec §10.6).

- [ ] **Step 1: Write the tests**

````diff
diff --git a/backend/tests/apps/cli/test_worker_cli.py b/backend/tests/apps/cli/test_worker_cli.py
new file mode 100644
index 0000000..95bffad
--- /dev/null
+++ b/backend/tests/apps/cli/test_worker_cli.py
@@ -0,0 +1,32 @@
+# SPDX-License-Identifier: Apache-2.0
+"""`dewpoint worker`'s exits: 2 when the deployment's record doesn't match (engine 2b spec §2.1), 3 when the instance
+failed its self-check (§2.7). Its orchestrator restarts it either way."""
+
+import base64
+from typing import Any
+
+import pytest
+from typer.testing import CliRunner
+
+from dewpoint.apps.cli import main as cli
+from dewpoint.apps.worker.health import WorkerUnhealthyError
+from dewpoint.core.config import get_settings
+from dewpoint.core.platform.service import EnvironmentNotRecordedError
+
+
+@pytest.mark.parametrize(
+    ("error", "code"),
+    [(EnvironmentNotRecordedError(), 2), (WorkerUnhealthyError("This worker failed its self-check."), 3)],
+)
+def test_the_worker_exits_with_its_reason(monkeypatch: pytest.MonkeyPatch, error: Exception, code: int) -> None:
+    monkeypatch.setenv("DEWPOINT_DATABASE_URL", "postgresql+asyncpg://nobody@localhost/none")
+    monkeypatch.setenv("DEWPOINT_KEK_B64", base64.b64encode(b"k" * 32).decode())
+    monkeypatch.setenv("DEWPOINT_PUBLIC_ORIGIN", "https://dewpoint.test")
+    get_settings.cache_clear()
+
+    async def run_worker(settings: Any) -> None:
+        raise error
+
+    monkeypatch.setattr(cli, "run_worker", run_worker)
+    result = CliRunner().invoke(cli.app, ["worker"])
+    assert (result.exit_code, result.output) == (code, f"ERROR: {error}\n")
diff --git a/backend/tests/apps/worker/test_deployment.py b/backend/tests/apps/worker/test_deployment.py
index 5cc159f..7e93ffc 100644
--- a/backend/tests/apps/worker/test_deployment.py
+++ b/backend/tests/apps/worker/test_deployment.py
@@ -22,7 +22,7 @@ from dewpoint.apps.worker.main import engine_worker
 from dewpoint.engine.cel.profile import CURRENT_CEL_PROFILE
 from dewpoint.engine.runtime.activities import ENGINE_QUEUE, cel_queue
 from tests.apps.worker.harness import MemoryStore, in_process, start
-from tests.apps.worker.test_main import settings
+from tests.apps.worker.test_main import proven, settings, unrecorded
 from tests.engine.replay.record import executions
 from tests.support.graphs import G, cel, ref
 from tests.support.plugins.testkit import TESTKIT
@@ -152,6 +152,8 @@ async def test_a_worker_set_to_makes_its_build_current_once_it_polls(
     monkeypatch.setattr(main, "make_engine", lambda url: Engine())
     monkeypatch.setattr(main, "make_sessionmaker", lambda engine: None)
     monkeypatch.setattr(main, "verify_environment", recorded)  # the check itself: tests/apps/test_environment.py
+    monkeypatch.setattr(main, "reporter", lambda *args: unrecorded)  # the record itself: tests/core/platform
+    monkeypatch.setattr(main, "self_check", proven)  # the check itself: test_health.py
     monkeypatch.setattr(main, "installed_plugins", lambda: [TESTKIT])
     worker = asyncio.create_task(main.run(settings(worker_set_current=True, worker_shutdown_grace_s=0.1)))
     try:
diff --git a/backend/tests/apps/worker/test_health.py b/backend/tests/apps/worker/test_health.py
new file mode 100644
index 0000000..033bc81
--- /dev/null
+++ b/backend/tests/apps/worker/test_health.py
@@ -0,0 +1,98 @@
+# SPDX-License-Identifier: Apache-2.0
+"""A worker instance proves what it records (engine 2b spec §2.7): its KEK wraps and unwraps, and its role may read
+data keys. A failed check stops it polling, at startup or later; a database that doesn't answer (an outage, which
+the engine rides out) proves nothing either way, and neither does a record it can't write."""
+
+import pytest
+
+from dewpoint.apps.worker.health import WorkerUnhealthyError, self_check, start_healthy, watch
+from dewpoint.core.crypto.kek import Kek, KekSet
+from dewpoint.core.crypto.keyring import Keyring
+from dewpoint.core.db import make_engine, make_sessionmaker
+from tests.conftest import _url_for
+
+
+class Log:
+    def __init__(self, checks: list[bool | None], fail_reports: int = 0) -> None:
+        self.checks, self.fail_reports = checks, fail_reports
+        self.events: list[str] = []
+
+    async def check(self) -> bool | None:
+        healthy = self.checks.pop(0)
+        self.events.append(f"check {healthy}")
+        return healthy
+
+    async def report(self, healthy: bool) -> None:
+        if self.fail_reports:
+            self.fail_reports -= 1
+            self.events.append("report failed")
+            raise ConnectionError("the database is down")
+        self.events.append(f"report {healthy}")
+
+    async def stop(self) -> None:
+        self.events.append("stop")
+
+
+@pytest.mark.parametrize("answer", [False, None])
+async def test_an_instance_that_cant_prove_itself_at_startup_records_it_and_never_polls(answer: bool | None) -> None:
+    log = Log([answer])
+    with pytest.raises(WorkerUnhealthyError):
+        await start_healthy(log.check, log.report)
+    assert log.events == [f"check {answer}", "report False"]
+
+
+async def test_a_healthy_start_is_recorded() -> None:
+    log = Log([True])
+    await start_healthy(log.check, log.report)
+    assert log.events == ["check True", "report True"]
+
+
+async def test_a_failed_check_stops_the_workers_then_ends_the_process() -> None:
+    log = Log([True, False])
+    with pytest.raises(WorkerUnhealthyError):
+        await watch(log.check, log.report, log.stop, interval_s=0)
+    assert log.events == ["check True", "report True", "check False", "report False", "stop"]
+
+
+async def test_an_outage_proves_nothing_and_keeps_the_instance_polling() -> None:
+    """Nothing is recorded while the database doesn't answer: the row goes stale, and a stale row isn't live."""
+    log = Log([True, None, None, False])
+    with pytest.raises(WorkerUnhealthyError):
+        await watch(log.check, log.report, log.stop, interval_s=0)
+    assert log.events == [
+        "check True",
+        "report True",
+        "check None",
+        "check None",
+        "check False",
+        "report False",
+        "stop",
+    ]
+
+
+async def test_a_record_it_cant_write_keeps_a_healthy_instance_polling() -> None:
+    log = Log([True, True, False], fail_reports=2)
+    with pytest.raises(WorkerUnhealthyError):
+        await watch(log.check, log.report, log.stop, interval_s=0)
+    events = ["check True", "report failed", "check True", "report failed", "check False", "report False", "stop"]
+    assert log.events == events
+
+
+async def test_the_check_proves_the_kek_and_the_roles_access_to_data_keys(
+    pg_url, _test_users, worker_sessionmaker, monkeypatch: pytest.MonkeyPatch
+) -> None:
+    """A role without `SELECT` on `data_keys` fails the check; a database that doesn't answer is no answer."""
+    keyring = Keyring(KekSet(Kek("k1", b"k" * 32)))
+    assert await self_check(keyring, worker_sessionmaker) is True
+    ingress, unreachable = (
+        make_engine(_url_for(pg_url, "dewpoint_ingress")),
+        make_engine("postgresql+asyncpg://nobody@127.0.0.1:9/none"),
+    )
+    try:
+        assert await self_check(keyring, make_sessionmaker(ingress)) is False  # no grant: a definite answer
+        assert await self_check(keyring, make_sessionmaker(unreachable)) is None
+    finally:
+        await ingress.dispose()
+        await unreachable.dispose()
+    monkeypatch.setattr(Kek, "unwrap", lambda self, blob, aad: b"not the key")
+    assert await self_check(keyring, worker_sessionmaker) is False
diff --git a/backend/tests/apps/worker/test_main.py b/backend/tests/apps/worker/test_main.py
index 2d187a0..38d4e42 100644
--- a/backend/tests/apps/worker/test_main.py
+++ b/backend/tests/apps/worker/test_main.py
@@ -11,6 +11,7 @@ from temporalio.testing import WorkflowEnvironment
 import dewpoint
 from dewpoint.apps.codec import TenantCodec
 from dewpoint.apps.worker import main
+from dewpoint.apps.worker.health import WorkerUnhealthyError
 from dewpoint.apps.worker.main import engine_worker
 from dewpoint.core.config import Settings
 from dewpoint.engine.runtime.build import build_id
@@ -74,8 +75,49 @@ async def test_the_worker_connects_with_the_tenant_codec(monkeypatch: pytest.Mon
     monkeypatch.setattr(main, "make_engine", lambda url: Engine())
     monkeypatch.setattr(main, "make_sessionmaker", lambda engine: None)
     monkeypatch.setattr(main, "verify_environment", recorded)
+    monkeypatch.setattr(main, "reporter", lambda *args: unrecorded)
+    monkeypatch.setattr(main, "self_check", proven)
     with pytest.raises(Connected):
         await main.run(settings())
     converter = connected["data_converter"]
     assert isinstance(converter.payload_codec, TenantCodec)
     assert converter.failure_converter_class is DefaultFailureConverterWithEncodedAttributes
+
+
+async def unrecorded(healthy: bool) -> None:
+    """Where a test's worker records its health: nowhere (the record itself: tests/core/platform/test_workers.py)."""
+
+
+async def proven(*args: object) -> bool:
+    """A test worker's self-check, with its stand-in database: passed (the check itself: test_health.py)."""
+    return True
+
+
+async def failed(*args: object) -> bool:
+    return False
+
+
+async def test_a_worker_that_fails_its_self_check_never_polls(monkeypatch: pytest.MonkeyPatch) -> None:
+    """Engine 2b spec §2.7: it records itself unhealthy and exits before connecting to Temporal."""
+    reports: list[bool] = []
+
+    class Engine:
+        async def dispose(self) -> None: ...
+
+    async def recorded(*args: object) -> None: ...
+
+    async def report(healthy: bool) -> None:
+        reports.append(healthy)
+
+    async def connect(*args: object, **kwargs: Any) -> None:
+        raise AssertionError("it connected")
+
+    monkeypatch.setattr(main.Client, "connect", connect)
+    monkeypatch.setattr(main, "make_engine", lambda url: Engine())
+    monkeypatch.setattr(main, "make_sessionmaker", lambda engine: None)
+    monkeypatch.setattr(main, "verify_environment", recorded)
+    monkeypatch.setattr(main, "reporter", lambda *args: report)
+    monkeypatch.setattr(main, "self_check", failed)
+    with pytest.raises(WorkerUnhealthyError):
+        await main.run(settings())
+    assert reports == [False]
diff --git a/backend/tests/core/crypto/test_keyring.py b/backend/tests/core/crypto/test_keyring.py
index 23b3b0c..f4e6062 100644
--- a/backend/tests/core/crypto/test_keyring.py
+++ b/backend/tests/core/crypto/test_keyring.py
@@ -80,3 +80,12 @@ async def test_reading_a_data_key_never_creates_one(owner_sessionmaker) -> None:
         assert await kr.read_dek(s, t, 1) == first  # an older version stays readable
         with pytest.raises(NoKeyError):
             await kr.read_dek(s, t, 3)
+
+
+def test_the_self_check_proves_the_current_kek_wraps_and_unwraps(monkeypatch) -> None:
+    """Engine 2b spec §2.7: what a worker instance proves every 30 seconds."""
+    kr = Keyring(KekSet(_kek()))
+    kr.self_check()
+    monkeypatch.setattr(Kek, "unwrap", lambda self, blob, aad: b"not the key")
+    with pytest.raises(ValueError, match="doesn't unwrap"):
+        kr.self_check()
diff --git a/backend/tests/core/platform/test_workers.py b/backend/tests/core/platform/test_workers.py
new file mode 100644
index 0000000..749b284
--- /dev/null
+++ b/backend/tests/core/platform/test_workers.py
@@ -0,0 +1,30 @@
+# SPDX-License-Identifier: Apache-2.0
+"""Engine worker instances (engine 2b spec §2.7): each records its build, its capabilities and whether it's healthy;
+the dispatcher reads them."""
+
+import uuid
+
+from sqlalchemy import select
+
+from dewpoint.core.models.platform import WorkerInstance
+from dewpoint.core.platform.service import record_worker
+
+
+async def test_an_instance_records_itself_and_each_check_updates_its_row(
+    worker_sessionmaker, dispatch_sessionmaker
+) -> None:
+    instance = uuid.uuid4()
+    for healthy in (True, False):
+        async with worker_sessionmaker() as s, s.begin():  # as the worker records it
+            await record_worker(
+                s, instance_id=instance, build_id="dewpoint-0.1.0+abi5", capabilities=("a", "b"), healthy=healthy
+            )
+    async with dispatch_sessionmaker() as s:  # as the dispatcher reads it (2b-2)
+        [row] = (await s.execute(select(WorkerInstance))).scalars().all()
+    assert (row.instance_id, row.build_id, row.capabilities, row.healthy) == (
+        instance,
+        "dewpoint-0.1.0+abi5",
+        ["a", "b"],
+        False,
+    )
+    assert row.checked_at >= row.started_at
````

- [ ] **Step 2: Run them, and watch them fail**

Run: `cd backend && uv run pytest -q -p no:cacheprovider tests/apps/cli/test_worker_cli.py tests/apps/worker/test_deployment.py tests/apps/worker/test_health.py tests/apps/worker/test_main.py tests/core/crypto/test_keyring.py tests/core/platform/test_workers.py`

Expected: FAIL. The health module, `WorkerInstance` and `record_worker` don't exist yet. The replay showed:

````text
E   ModuleNotFoundError: No module named 'dewpoint.apps.worker.health'
E   ImportError: cannot import name 'WorkerInstance' from 'dewpoint.core.models.platform'
ERROR tests/apps/cli/test_worker_cli.py
ERROR tests/apps/worker/test_deployment.py
ERROR tests/apps/worker/test_health.py
ERROR tests/apps/worker/test_main.py
ERROR tests/core/platform/test_workers.py
!!!!!!!!!!!!!!!!!!! Interrupted: 5 errors during collection !!!!!!!!!!!!!!!!!!!!
5 errors in 0.78s
````

- [ ] **Step 3: Implement**

````diff
diff --git a/backend/migrations/versions/0012_worker_instances.py b/backend/migrations/versions/0012_worker_instances.py
new file mode 100644
index 0000000..ff81ebd
--- /dev/null
+++ b/backend/migrations/versions/0012_worker_instances.py
@@ -0,0 +1,32 @@
+# SPDX-License-Identifier: Apache-2.0
+"""engine worker instances: what each one's build can do, and whether it proved it lately (engine 2b spec §2.7)"""
+
+import sqlalchemy as sa
+from alembic import op
+from sqlalchemy.dialects import postgresql as pg
+
+revision = "0012"
+down_revision = "0011"
+branch_labels = None
+depends_on = None
+
+
+def upgrade() -> None:
+    op.create_table(
+        "worker_instances",
+        sa.Column("instance_id", pg.UUID(as_uuid=True), primary_key=True),
+        sa.Column("build_id", sa.Text, nullable=False),
+        sa.Column("capabilities", pg.ARRAY(sa.Text), nullable=False),
+        sa.Column("healthy", sa.Boolean, nullable=False),
+        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
+        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
+    )
+    op.create_index("ix_worker_instances_build_checked", "worker_instances", ["build_id", "checked_at"])
+    # A platform table, with no tenant data: each worker writes its own row; the dispatcher (2b-2) and the readiness
+    # checks (2b-4) read them.
+    op.execute("GRANT SELECT, INSERT, UPDATE ON worker_instances TO dewpoint_worker")
+    op.execute("GRANT SELECT ON worker_instances TO dewpoint_dispatch, dewpoint_admin")
+
+
+def downgrade() -> None:
+    op.drop_table("worker_instances")
diff --git a/backend/src/dewpoint/apps/cli/main.py b/backend/src/dewpoint/apps/cli/main.py
index 917f401..96f0e68 100644
--- a/backend/src/dewpoint/apps/cli/main.py
+++ b/backend/src/dewpoint/apps/cli/main.py
@@ -21,6 +21,7 @@ from dewpoint.apps.environment import verify_environment
 from dewpoint.apps.plugin_loader import PluginLoadError, installed_plugins, prepare
 from dewpoint.apps.runs import NotAdmissibleError, StartRefusedError, StartUncertainError, start_run
 from dewpoint.apps.worker.deployment import Deployment, describe, set_current, this_build
+from dewpoint.apps.worker.health import WorkerUnhealthyError
 from dewpoint.apps.worker.main import run as run_worker
 from dewpoint.core.audit.anchor import FileAnchorSink, anchor_all, anchor_freshness, verify_anchors
 from dewpoint.core.auth.users import PasswordPolicyError, create_user
@@ -353,6 +354,9 @@ def worker() -> None:
     except (EnvironmentNotRecordedError, EnvironmentMismatchError) as e:
         typer.echo(f"ERROR: {e}")
         raise typer.Exit(2) from None
+    except WorkerUnhealthyError as e:  # its orchestrator restarts it (engine 2b spec §2.7)
+        typer.echo(f"ERROR: {e}")
+        raise typer.Exit(3) from None
 
 
 @asynccontextmanager
diff --git a/backend/src/dewpoint/apps/worker/health.py b/backend/src/dewpoint/apps/worker/health.py
new file mode 100644
index 0000000..f453305
--- /dev/null
+++ b/backend/src/dewpoint/apps/worker/health.py
@@ -0,0 +1,99 @@
+# SPDX-License-Identifier: Apache-2.0
+"""An engine worker instance records what its build can do, and proves it (engine 2b spec §2.7). At startup and every
+HEALTH_INTERVAL_S seconds it checks that its KEK wraps and unwraps a key and that its database role may read data
+keys — what `payload_codec` needs of the instance — and records the result with its build and capabilities. One that
+fails stops polling and exits: it never keeps taking tasks. The dispatcher (2b-2) and the readiness checks (2b-4)
+read the records; a row that hasn't been checked lately is an instance that isn't live.
+
+The check is deliberately light. The grant says nothing about what the role's RLS-scoped reads return, and the KEK
+round trip uses a fresh key, not the stored ones: a wrong KEK under the right id passes both. Lifting the production
+gate (2b-4) unwraps every stored key and reads each tenant's key along the workers' own path (spec §10.6).
+
+A database that doesn't answer is an outage, not a failed check: the engine rides it out (its rows catch up), so the
+instance keeps polling, records nothing, and its row goes stale. A record it can't write is logged the same way."""
+
+import asyncio
+import uuid
+from collections.abc import Awaitable, Callable
+
+import structlog
+from sqlalchemy import text
+from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
+
+from dewpoint.core.crypto.keyring import Keyring
+from dewpoint.core.platform.service import record_worker
+
+log = structlog.get_logger()
+
+# Compiled into the build: what every live instance of the current build must hold before runs start on it (2b-2).
+# 2b-1b adds claim_check.
+CAPABILITIES = ("cel_request_size_guard", "payload_codec")
+HEALTH_INTERVAL_S = 30.0
+
+
+class WorkerUnhealthyError(Exception):
+    """This instance failed its self-check: it stopped polling, and recorded itself unhealthy where it could."""
+
+
+async def self_check(keyring: Keyring, sessionmaker: async_sessionmaker[AsyncSession]) -> bool | None:
+    """True when this instance can encrypt for its tenants: its KEK wraps and unwraps, and its role may read data
+    keys. False when either is definitely not so. None when the database didn't answer: nothing is proven either way."""
+    try:
+        keyring.self_check()
+    except Exception as e:  # whatever fails, the answer is the same: this instance can't unwrap keys
+        log.error("worker_self_check_failed", check="kek", error=type(e).__name__)
+        return False
+    try:
+        async with sessionmaker() as s:  # the grant, read from the catalog: an answer, whichever tenant is asked for
+            readable: bool = (await s.execute(text("SELECT has_table_privilege('data_keys', 'SELECT')"))).scalar_one()
+    except Exception as e:
+        log.warning("worker_self_check_unanswered", error=type(e).__name__)
+        return None
+    if not readable:
+        log.error("worker_self_check_failed", check="data_keys")
+    return readable
+
+
+def reporter(
+    sessionmaker: async_sessionmaker[AsyncSession], instance_id: uuid.UUID, build_id: str
+) -> Callable[[bool], Awaitable[None]]:
+    async def report(healthy: bool) -> None:
+        async with sessionmaker() as s, s.begin():
+            await record_worker(
+                s, instance_id=instance_id, build_id=build_id, capabilities=CAPABILITIES, healthy=healthy
+            )
+
+    return report
+
+
+async def start_healthy(check: Callable[[], Awaitable[bool | None]], report: Callable[[bool], Awaitable[None]]) -> None:
+    """Before any worker polls: raises WorkerUnhealthyError unless the check passes. An instance that can't prove itself
+    yet doesn't start, whatever the reason."""
+    healthy = await check()
+    await report(healthy is True)
+    if healthy is not True:
+        raise WorkerUnhealthyError("This worker couldn't prove its capabilities at startup: it never polled.")
+
+
+async def watch(
+    check: Callable[[], Awaitable[bool | None]],
+    report: Callable[[bool], Awaitable[None]],
+    stop: Callable[[], Awaitable[None]],
+    *,
+    interval_s: float = HEALTH_INTERVAL_S,
+) -> None:
+    """Every `interval_s`: check, and record the result. A failed check stops the workers polling (`stop`, which lets
+    running attempts finish within the shutdown grace), then raises WorkerUnhealthyError. An unanswered one records
+    nothing and changes nothing."""
+    while True:
+        await asyncio.sleep(interval_s)
+        healthy = await check()
+        if healthy is None:
+            continue
+        try:
+            await report(healthy)
+        except Exception as e:  # an outage: the row goes stale, and stale rows aren't live instances
+            log.warning("worker_health_not_recorded", error=type(e).__name__)
+        if not healthy:
+            await stop()
+            raise WorkerUnhealthyError("This worker failed its self-check: it stopped polling.")
diff --git a/backend/src/dewpoint/apps/worker/main.py b/backend/src/dewpoint/apps/worker/main.py
index 86a9d42..21c1567 100644
--- a/backend/src/dewpoint/apps/worker/main.py
+++ b/backend/src/dewpoint/apps/worker/main.py
@@ -5,6 +5,7 @@ evaluator, then asks its identity. The engine worker serves this build's version
 Deployment (deployment.py); the CEL worker is outside it, routed by profile."""
 
 import asyncio
+import uuid
 from collections.abc import Iterable
 from datetime import timedelta
 
@@ -18,6 +19,7 @@ from dewpoint.apps.environment import verify_environment
 from dewpoint.apps.plugin_loader import installed_plugins
 from dewpoint.apps.worker.activities import RunStore, cel_activity, engine_activities, remote_evaluator
 from dewpoint.apps.worker.deployment import deployment_config, set_current, this_build
+from dewpoint.apps.worker.health import reporter, self_check, start_healthy, watch
 from dewpoint.apps.worker.store import DbRunStore
 from dewpoint.core.config import Settings
 from dewpoint.core.crypto.kek import KekSet
@@ -84,21 +86,32 @@ async def promote(client: Client) -> None:
 async def run(settings: Settings) -> None:
     """Raises EnvironmentNotRecordedError or EnvironmentMismatchError before connecting to Temporal: a worker never
     serves a namespace its database wasn't recorded with (engine 2b spec §2.1). Every payload it sends or reads is
-    encrypted with its tenant's key, read through the worker's role (§6.2–6.3)."""
+    encrypted with its tenant's key, read through the worker's role (§6.2–6.3). It records itself as an instance of
+    its build, with its capabilities, and raises WorkerUnhealthyError once a self-check fails, at startup before it
+    polls or later after its workers stop polling (§2.7)."""
     engine = make_engine(settings.database_url)
     try:
         sessionmaker = make_sessionmaker(engine)
         await verify_environment(sessionmaker, settings)
-        keys = KeyringKeys(sessionmaker, Keyring(KekSet.from_settings(settings)))
+        keyring = Keyring(KekSet.from_settings(settings))
+        report = reporter(sessionmaker, uuid.uuid4(), this_build())
+        await start_healthy(lambda: self_check(keyring, sessionmaker), report)
         client = await Client.connect(
-            settings.temporal_address, namespace=settings.temporal_namespace, data_converter=data_converter(keys)
+            settings.temporal_address,
+            namespace=settings.temporal_namespace,
+            data_converter=data_converter(KeyringKeys(sessionmaker, keyring)),
         )
         workers = [engine_worker(client, DbRunStore(sessionmaker), installed_plugins(), settings)]
         if settings.cel_socket:
             profile = await evaluator_profile(settings.cel_socket)
             log.info("cel_queue", profile=profile)
             workers.append(cel_worker(client, settings.cel_socket, profile, max_concurrent=settings.cel_max_concurrent))
+
+        async def stop() -> None:
+            await asyncio.gather(*(w.shutdown() for w in workers))
+
         tasks = [w.run() for w in workers]
+        tasks.append(watch(lambda: self_check(keyring, sessionmaker), report, stop))
         if settings.worker_set_current:
             tasks.append(promote(client))
         await asyncio.gather(*tasks)
diff --git a/backend/src/dewpoint/core/crypto/keyring.py b/backend/src/dewpoint/core/crypto/keyring.py
index 7351440..edae370 100644
--- a/backend/src/dewpoint/core/crypto/keyring.py
+++ b/backend/src/dewpoint/core/crypto/keyring.py
@@ -96,6 +96,13 @@ class Keyring:
             raise InvalidTag()
         return self._dek(row).decrypt(blob[5:17], blob[17:], _aad(_scope(tenant_id), purpose, context))
 
+    def self_check(self) -> None:
+        """Wraps a fresh key with the current KEK and unwraps it, or raises: what an engine worker instance proves at
+        startup and every 30 seconds (engine 2b spec §2.7)."""
+        dek, aad, kek = AESGCM.generate_key(256), b"dek|self-check|0", self._keks.current
+        if kek.unwrap(kek.wrap(dek, aad), aad) != dek:
+            raise ValueError("the current KEK doesn't unwrap what it wraps")
+
     async def ensure_key(self, s: AsyncSession, tenant_id: uuid.UUID) -> int:
         """The tenant's active key version, created if it has none. Tenant creation calls it, so a tenant has a key
         before anything encrypts for it (engine 2b spec §6.3)."""
diff --git a/backend/src/dewpoint/core/models/platform.py b/backend/src/dewpoint/core/models/platform.py
index c7bd21e..e33625e 100644
--- a/backend/src/dewpoint/core/models/platform.py
+++ b/backend/src/dewpoint/core/models/platform.py
@@ -1,7 +1,9 @@
 # SPDX-License-Identifier: Apache-2.0
+import uuid
 from datetime import datetime
 
 from sqlalchemy import Boolean, DateTime, SmallInteger, String, Text, func
+from sqlalchemy.dialects.postgresql import ARRAY, UUID
 from sqlalchemy.orm import Mapped, mapped_column
 
 from dewpoint.core.models.base import Base
@@ -17,3 +19,16 @@ class PlatformSettings(Base):
     temporal_namespace: Mapped[str] = mapped_column(Text)
     production_runs: Mapped[bool] = mapped_column(Boolean, default=False)
     recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
+
+
+class WorkerInstance(Base):
+    """An engine worker instance: its build, the capabilities compiled into it, and whether its last self-check passed
+    (engine 2b spec §2.7). One that hasn't checked lately isn't live."""
+
+    __tablename__ = "worker_instances"
+    instance_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
+    build_id: Mapped[str] = mapped_column(Text)
+    capabilities: Mapped[list[str]] = mapped_column(ARRAY(Text))
+    healthy: Mapped[bool] = mapped_column(Boolean)
+    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
+    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
diff --git a/backend/src/dewpoint/core/platform/service.py b/backend/src/dewpoint/core/platform/service.py
index f693b0f..b98ddfe 100644
--- a/backend/src/dewpoint/core/platform/service.py
+++ b/backend/src/dewpoint/core/platform/service.py
@@ -3,11 +3,16 @@
 recorded once. A process that talks to Temporal checks its configured namespace against the record before it starts,
 so a development database can't drive a namespace it wasn't set up for, and a production database can't either. The
 label proves nothing about the data: keeping development's database and namespace apart from production's is the
-operator's job."""
+operator's job. Its engine worker instances record what they can do (§2.7)."""
 
+import uuid
+from collections.abc import Sequence
+
+from sqlalchemy import func
+from sqlalchemy.dialects.postgresql import insert
 from sqlalchemy.ext.asyncio import AsyncSession
 
-from dewpoint.core.models.platform import PlatformSettings
+from dewpoint.core.models.platform import PlatformSettings, WorkerInstance
 
 PRODUCTION = "production"
 DEVELOPMENT = "development"
@@ -63,3 +68,14 @@ async def check_namespace(s: AsyncSession, configured: str) -> PlatformSettings:
             f"for `{configured}` (DEWPOINT_TEMPORAL_NAMESPACE). It won't start."
         )
     return row
+
+
+async def record_worker(
+    s: AsyncSession, *, instance_id: uuid.UUID, build_id: str, capabilities: Sequence[str], healthy: bool
+) -> None:
+    """An engine worker instance's row, written at startup and after each self-check (engine 2b spec §2.7)."""
+    values = {"build_id": build_id, "capabilities": list(capabilities), "healthy": healthy}
+    statement = insert(WorkerInstance).values(instance_id=instance_id, **values)
+    await s.execute(
+        statement.on_conflict_do_update(index_elements=["instance_id"], set_={**values, "checked_at": func.now()})
+    )
````

- [ ] **Step 4: Run the tests again**

Run: `cd backend && uv run pytest -q -p no:cacheprovider tests/apps/cli/test_worker_cli.py tests/apps/worker/test_deployment.py tests/apps/worker/test_health.py tests/apps/worker/test_main.py tests/core/crypto/test_keyring.py tests/core/platform/test_workers.py`

Expected (the replay):

````text
23 passed in 39.26s
````

- [ ] **Step 5: The whole suite, lint, types and layers**

Run: `cd backend && uv run pytest -q -p no:cacheprovider`, then `uv run ruff check --no-cache src tests migrations`, `uv run ruff format --no-cache --check src tests migrations`, `uv run mypy src` and `uv run lint-imports`.

Expected: 1,177 passed, 8 skipped; ruff and its formatter clean; mypy: no issues; import-linter: 10 contracts kept.

- [ ] **Step 6: Commit**

```bash
git add -A backend deploy docs && git commit -m "feat(worker): engine worker instances record and prove their capabilities (2b-1a)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: Results guarded where they're produced

**Spec:** §5.2.

**Files:**
- Create: `backend/src/dewpoint/engine/runtime/size.py`
- Create: `backend/tests/apps/worker/test_run_graph_sizes.py`
- Create: `backend/tests/engine/runtime/test_size.py`
- Modify: `backend/src/dewpoint/apps/codec.py`
- Modify: `backend/src/dewpoint/apps/worker/activities.py`
- Modify: `backend/src/dewpoint/engine/runtime/workflow.py`
- Modify: `backend/tests/apps/test_codec.py`
- Modify: `backend/tests/apps/worker/test_activities.py`
- Modify: `backend/tests/apps/worker/test_temporal_contract.py`
- Modify: `backend/tests/core/plugins/test_registry.py`
- Modify: `backend/tests/support/plugins/testkit.py`

**Interfaces:**
- Produces `dewpoint.engine.runtime.size`: `CODEC_OVERHEAD`, `PAYLOAD_BYTES`, `PAYLOAD_TOO_LARGE`,
  `STEP_OUTPUT_TOO_LARGE`, `VERSION_TOO_LARGE`, `OUTPUTS_TOO_LARGE`, `BATCH_RESULTS_TOO_LARGE`,
  `encoded_bytes(value, converter) -> int`, `fits(value, converter) -> bool`. The limit is read when `fits` runs.
- Also produces `tests.support.plugins.testkit.Blob` (`testkit.blob@1`, `{size}`).
- Consumes: Task 4's codec, for the overhead test.

`engine.runtime.size` measures a payload as the SDK's payload converter writes it, plus `CODEC_OVERHEAD`,
which moves here from the codec; the codec test proves it bounds what encryption adds. A result is checked where
it's produced, because a workflow-side check can't rescue a result Temporal refused to record:
- **A step's output**, in its activity: too large fails the step once, `payload_too_large`, keeping its outcome,
  since the node ran.
- **The version loader's result**, in its activity: `version_unusable`, with a fixed message.
- **A run's result**, in the run: its outputs too large fail the run with `payload_too_large`, and no outputs.
- **A batch's result**, in the batch: too large, it returns a small result whose `stopped` fails its loop, and still
  reports the iterations it used.

The test node `testkit.blob@1` makes a large output from a small config. Its node count now derives the registry
test's count.

- [ ] **Step 1: Write the tests**

````diff
diff --git a/backend/tests/apps/test_codec.py b/backend/tests/apps/test_codec.py
index d17a841..449bf5d 100644
--- a/backend/tests/apps/test_codec.py
+++ b/backend/tests/apps/test_codec.py
@@ -13,7 +13,6 @@ from temporalio.converter import (
 )
 
 from dewpoint.apps.codec import (
-    CODEC_OVERHEAD,
     ENCODING,
     KEY_VERSION,
     TENANT,
@@ -21,6 +20,7 @@ from dewpoint.apps.codec import (
     TenantCodec,
 )
 from dewpoint.engine.runtime.ids import run_workflow_id
+from dewpoint.engine.runtime.size import CODEC_OVERHEAD
 from tests.support.keys import FixtureKeys
 
 A, B = str(uuid.UUID(int=1)), str(uuid.UUID(int=2))
diff --git a/backend/tests/apps/worker/test_activities.py b/backend/tests/apps/worker/test_activities.py
index 8ff73f4..3705e2e 100644
--- a/backend/tests/apps/worker/test_activities.py
+++ b/backend/tests/apps/worker/test_activities.py
@@ -21,15 +21,33 @@ from pydantic_core import PydanticCustomError
 from temporalio.exceptions import ApplicationError
 from temporalio.testing import ActivityEnvironment
 
-from dewpoint.apps.worker.activities import CHECKED_FORMATS, cel_activity, remote_evaluator, step_activity_for
+from dewpoint.apps.worker.activities import (
+    CHECKED_FORMATS,
+    cel_activity,
+    engine_activities,
+    remote_evaluator,
+    step_activity_for,
+)
 from dewpoint.apps.worker.context import idempotency_key
+from dewpoint.engine import ENGINE_ABI
 from dewpoint.engine.cel import ipc
 from dewpoint.engine.cel import types as T
 from dewpoint.engine.cel.profile import CURRENT_CEL_PROFILE
-from dewpoint.engine.runtime.activities import MAPPED, CelInput, CelResult, StepInput, StepResult
+from dewpoint.engine.runtime import size
+from dewpoint.engine.runtime.activities import (
+    MAPPED,
+    CelInput,
+    CelResult,
+    LoadVersionInput,
+    StepInput,
+    StepResult,
+    VersionData,
+)
+from dewpoint.engine.runtime.execution import VERSION_UNUSABLE
 from dewpoint.engine.runtime.ids import run_workflow_id
+from dewpoint.engine.runtime.size import PAYLOAD_TOO_LARGE, STEP_OUTPUT_TOO_LARGE, VERSION_TOO_LARGE
 from dewpoint.sdk import Node, SideEffect, StepContext, sensitive
-from tests.support.plugins.testkit import AmbiguousSend, Echo, FailN, Reconcile, Sensitive, Slow
+from tests.support.plugins.testkit import AmbiguousSend, Blob, Echo, FailN, Reconcile, Sensitive, Slow
 
 IDS = {"tenant_id": str(uuid.UUID(int=1)), "run_id": str(uuid.UUID(int=2)), "step_id": str(uuid.UUID(int=3))}
 SECRET = "hunter22"
@@ -454,3 +472,40 @@ async def test_an_activity_refuses_an_input_of_another_tenant() -> None:
     other = dataclasses.replace(step("testkit.echo@1", {"value": 1}), tenant_id=str(uuid.UUID(int=9)))
     refused = await failure(step_activity_for(Echo), other)
     assert (refused.type, refused.non_retryable, refused.details) == ("internal_error", True, ())
+
+
+async def test_an_output_too_large_to_record_fails_the_step_without_a_retry(monkeypatch: pytest.MonkeyPatch) -> None:
+    """Engine 2b spec §5.2: guarded where it's produced. Temporal would refuse to record the result, and the step
+    would hang in retries; the node ran, so its outcome stands, and nothing repeats it."""
+    monkeypatch.setattr(size, "PAYLOAD_BYTES", 10_000)
+    assert await call(step_activity_for(Blob), step("testkit.blob@1", {"size": 9_000}))  # fits, with the codec's share
+    refused = await failure(step_activity_for(Blob), step("testkit.blob@1", {"size": 10_000}))
+    assert (refused.type, refused.message, refused.non_retryable) == (PAYLOAD_TOO_LARGE, STEP_OUTPUT_TOO_LARGE, True)
+    assert refused.details == ({"outcome": "applied", MAPPED: True},)
+
+
+async def test_a_version_too_large_to_load_is_unusable(monkeypatch: pytest.MonkeyPatch) -> None:
+    """Its result would pass Temporal's payload limit: the run fails `version_unusable`, with a fixed message."""
+    monkeypatch.setattr(size, "PAYLOAD_BYTES", 10_000)
+    big = VersionData(
+        version_id=str(uuid.uuid4()),
+        workflow_id=str(uuid.uuid4()),
+        graph={"note": "x" * 10_000},
+        expressions=[],
+        cel_profile="",
+        manifests={},
+        subflow_version_ids={},
+        failure_handler_version_id=None,
+        engine_abi=ENGINE_ABI,
+    )
+
+    class Store:
+        async def version(self, tenant_id: str, version_id: str) -> VersionData:
+            return big
+
+        async def project(self, data: Any) -> None: ...
+
+    [load] = [a for a in engine_activities(Store(), []) if a.__name__ == "load_version"]
+    with pytest.raises(ApplicationError) as e:
+        await activity_env().run(load, LoadVersionInput(IDS["tenant_id"], big.version_id))
+    assert (e.value.type, e.value.message, e.value.non_retryable) == (VERSION_UNUSABLE, VERSION_TOO_LARGE, True)
diff --git a/backend/tests/apps/worker/test_run_graph_sizes.py b/backend/tests/apps/worker/test_run_graph_sizes.py
new file mode 100644
index 0000000..6b3db9d
--- /dev/null
+++ b/backend/tests/apps/worker/test_run_graph_sizes.py
@@ -0,0 +1,89 @@
+# SPDX-License-Identifier: Apache-2.0
+"""Engine 2b spec §5.2: every payload the engine sends Temporal, and every result it gets back, stays under Temporal's
+payload limit once encoded. Each is checked where it's produced: too large fails its step, its loop or its run with
+`payload_too_large`, never a retried or terminated workflow task. The limit is lowered here so small values show it;
+test_real_server.py shows it at the real one."""
+
+import asyncio
+from typing import Any
+
+import pytest
+from temporalio.client import WorkflowHandle
+from temporalio.testing import WorkflowEnvironment
+
+from dewpoint.engine.runtime import size
+from dewpoint.engine.runtime.activities import RunResult
+from dewpoint.engine.runtime.size import OUTPUTS_TOO_LARGE, PAYLOAD_TOO_LARGE
+from tests.apps.worker.harness import MemoryStore, run_id_of, start, workers
+from tests.support.graphs import G, ref
+
+LIMIT = 50_000
+BLOB, LOOP, RUN = "testkit.blob@1", "flow.loop@1", "flow.run_workflow@1"
+
+
+@pytest.fixture(autouse=True)
+def lowered(monkeypatch: pytest.MonkeyPatch) -> None:
+    monkeypatch.setattr(size, "PAYLOAD_BYTES", LIMIT)
+
+
+def graph(**outputs: Any) -> G:
+    g = G()
+    g.settings = {"input_schema": {"type": "object"}, "outputs": outputs}
+    return g
+
+
+async def finished(env: WorkflowEnvironment, store: MemoryStore, g: G) -> tuple[WorkflowHandle[Any, Any], RunResult]:
+    async with workers(env.client, store):
+        handle = await start(env.client, store, g, {})
+        return handle, await asyncio.wait_for(handle.result(), 60)
+
+
+async def test_a_step_output_too_large_to_record_fails_the_step_once(env: WorkflowEnvironment) -> None:
+    """Its node ran: the row says so (`applied`), and nothing repeats it."""
+    store = MemoryStore()
+    g = graph(code=ref("steps.b.error.code", default="none"))
+    g.node("b", BLOB, {"size": LIMIT}, on_error="continue")
+    handle, result = await finished(env, store, g)
+    assert (result.status, result.outputs) == ("succeeded", {"code": PAYLOAD_TOO_LARGE})
+    [row] = store.steps(run_id_of(handle))
+    assert (row.attempt, row.status, row.error_code, row.outcome) == (1, "failed", PAYLOAD_TOO_LARGE, "applied")
+
+
+async def test_outputs_too_large_to_return_fail_the_run(env: WorkflowEnvironment) -> None:
+    """Each output fits; together they don't. The run fails, and its result carries no outputs."""
+    store = MemoryStore()
+    g = graph(a=ref("steps.a.output.value"), b=ref("steps.b.output.value"))
+    g.node("a", BLOB, {"size": LIMIT // 2}).node("b", BLOB, {"size": LIMIT // 2})
+    handle, result = await finished(env, store, g)
+    assert (result.status, result.outputs) == ("failed", None)
+    assert result.error is not None and (result.error["code"], result.error["message"]) == (
+        PAYLOAD_TOO_LARGE,
+        OUTPUTS_TOO_LARGE,
+    )
+    summary = store.runs[run_id_of(handle)]
+    assert (summary.status, summary.error_code) == ("failed", PAYLOAD_TOO_LARGE)
+
+
+async def test_a_sub_flow_whose_outputs_are_too_large_fails_its_step(env: WorkflowEnvironment) -> None:
+    """The sub-run fails where its result is produced, so its parent's step fails with it."""
+    store = MemoryStore()
+    sub = graph(a=ref("steps.a.output.value"), b=ref("steps.b.output.value"))
+    sub.node("a", BLOB, {"size": LIMIT // 2}).node("b", BLOB, {"size": LIMIT // 2})
+    g = graph(code=ref("steps.r.error.code", default="none"))
+    g.node("r", RUN, {"workflow_id": str(store.publish(sub)), "input": {}}, on_error="continue")
+    _, result = await finished(env, store, g)
+    assert (result.status, result.outputs) == ("succeeded", {"code": PAYLOAD_TOO_LARGE})
+    [(child, _)] = store.starts.items()
+    assert (store.runs[child].status, store.runs[child].error_code) == ("failed", PAYLOAD_TOO_LARGE)
+
+
+async def test_a_batch_that_collected_too_much_to_return_fails_its_loop(env: WorkflowEnvironment) -> None:
+    """A batch of 100 iterations collecting 1,000 characters each: it reports what it used, and its loop fails; no
+    collected item is dropped silently."""
+    store = MemoryStore()
+    g = graph(code=ref("steps.l.error.code", default="none"))
+    g.node("l", LOOP, {"items": list(range(150)), "collect": ref("steps.b.output.value")}, on_error="continue")
+    g.node("b", BLOB, {"size": 1_000}).edge("l", "b", "body")
+    _, result = await finished(env, store, g)
+    assert (result.status, result.outputs) == ("succeeded", {"code": PAYLOAD_TOO_LARGE})
+    assert result.iterations == 100  # the batch reported what it used
diff --git a/backend/tests/apps/worker/test_temporal_contract.py b/backend/tests/apps/worker/test_temporal_contract.py
index 765bb19..b14d8ee 100644
--- a/backend/tests/apps/worker/test_temporal_contract.py
+++ b/backend/tests/apps/worker/test_temporal_contract.py
@@ -44,8 +44,9 @@ from temporalio.exceptions import ActivityError, ApplicationError, ChildWorkflow
 from temporalio.testing import WorkflowEnvironment
 from temporalio.worker import Replayer, UnsandboxedWorkflowRunner, Worker
 
-from dewpoint.apps.codec import CODEC_OVERHEAD, TENANT, KeySource, TenantCodec, data_converter
+from dewpoint.apps.codec import TENANT, KeySource, TenantCodec, data_converter
 from dewpoint.engine.runtime.ids import run_workflow_id, tenant_of
+from dewpoint.engine.runtime.size import CODEC_OVERHEAD
 from tests.support.keys import FixtureKeys, opened
 
 SDK, SERVER = "1.33.0", "1.32.0"  # what §11.1 measured
diff --git a/backend/tests/core/plugins/test_registry.py b/backend/tests/core/plugins/test_registry.py
index 14a0200..cdeabab 100644
--- a/backend/tests/core/plugins/test_registry.py
+++ b/backend/tests/core/plugins/test_registry.py
@@ -15,14 +15,16 @@ from dewpoint.plugins.flow import PLUGIN
 from dewpoint.sdk import Node, NodeKind, Plugin
 from tests.support.plugins.testkit import TESTKIT
 
+NODES = len(PLUGIN.nodes) + len(TESTKIT.nodes)
+
 
 async def test_sync_registers_and_is_idempotent(admin_sessionmaker) -> None:
     async with admin_sessionmaker() as s, s.begin():
         report = await sync_installed(s, [PLUGIN, TESTKIT])
-    assert len(report.added) == 18 and report.unchanged == []
+    assert len(report.added) == NODES and report.unchanged == []
     async with admin_sessionmaker() as s, s.begin():
         report = await sync_installed(s, [PLUGIN, TESTKIT])
-    assert report.added == [] and len(report.unchanged) == 18
+    assert report.added == [] and len(report.unchanged) == NODES
     async with admin_sessionmaker() as s:
         refs = {r.ref for r in await registry.list_node_types(s)}
         state = (
diff --git a/backend/tests/engine/runtime/test_size.py b/backend/tests/engine/runtime/test_size.py
new file mode 100644
index 0000000..937c579
--- /dev/null
+++ b/backend/tests/engine/runtime/test_size.py
@@ -0,0 +1,30 @@
+# SPDX-License-Identifier: Apache-2.0
+"""Engine 2b spec §5.2: a payload is measured as the SDK's JSON converter writes it, plus a bound on what the codec
+adds (test_codec.py proves the bound), against a margin under Temporal's 2 MiB."""
+
+from temporalio.converter import DataConverter
+
+from dewpoint.engine.runtime import size
+from dewpoint.engine.runtime.execution import CEL_REQUEST_BYTES
+
+TEMPORAL_PAYLOAD_LIMIT = 2 * 1024 * 1024
+JSON = DataConverter.default.payload_converter
+
+
+def test_a_payload_weighs_its_json_and_the_codecs_share() -> None:
+    value = {"s": "é" * 10}  # escaped as the converter writes it: 6 bytes each, not UTF-8's 2
+    assert size.encoded_bytes(value, JSON) == len(JSON.to_payloads([value])[0].data) + size.CODEC_OVERHEAD
+    assert size.encoded_bytes(value, JSON) == len('{"s":"' + "\\u00e9" * 10 + '"}') + size.CODEC_OVERHEAD
+
+
+def test_the_limits_leave_a_margin_under_temporals() -> None:
+    """Every payload the guard lets through, and #15's largest cel.evaluate request once encoded (spec §5.2: its guard
+    verified again after the codec)."""
+    assert size.PAYLOAD_BYTES < TEMPORAL_PAYLOAD_LIMIT
+    assert CEL_REQUEST_BYTES + size.CODEC_OVERHEAD < TEMPORAL_PAYLOAD_LIMIT
+
+
+def test_fits_reads_the_limit_when_its_called(monkeypatch) -> None:
+    assert size.fits("x" * 1_000, JSON)
+    monkeypatch.setattr(size, "PAYLOAD_BYTES", 1_000)
+    assert not size.fits("x" * 1_000, JSON)
diff --git a/backend/tests/support/plugins/testkit.py b/backend/tests/support/plugins/testkit.py
index 354c845..31e40fb 100644
--- a/backend/tests/support/plugins/testkit.py
+++ b/backend/tests/support/plugins/testkit.py
@@ -169,6 +169,27 @@ class Reconcile(Node):
         return ReconcileOutput(found=True)
 
 
+class BlobConfig(BaseModel):
+    size: int = Field(ge=0, le=4 * 1024 * 1024)
+
+
+class Blob(Node):
+    """An output of `size` characters from a small config: what a step returns can pass Temporal's payload limit
+    when what it was sent doesn't (engine 2b spec §5.2)."""
+
+    type = "testkit.blob"
+    version = 1
+    title = "Blob"
+    Config = BlobConfig
+    Output = EchoOutput
+
+    async def run(self, ctx: StepContext, config: BlobConfig) -> EchoOutput:
+        return EchoOutput(value="x" * config.size)
+
+    async def simulate(self, ctx: StepContext, config: BlobConfig) -> EchoOutput:
+        return EchoOutput(value="x" * config.size)
+
+
 TESTKIT = Plugin(
-    name="testkit", version="0.0.0", nodes=(Echo, FailN, Slow, Sensitive, AmbiguousSend, SlowSend, Reconcile)
+    name="testkit", version="0.0.0", nodes=(Echo, FailN, Slow, Sensitive, AmbiguousSend, SlowSend, Reconcile, Blob)
 )
````

- [ ] **Step 2: Run them, and watch them fail**

Run: `cd backend && uv run pytest -q -p no:cacheprovider tests/apps/test_codec.py tests/apps/worker/test_activities.py tests/apps/worker/test_run_graph_sizes.py tests/apps/worker/test_temporal_contract.py tests/core/plugins/test_registry.py tests/engine/runtime/test_size.py`

Expected: FAIL. `dewpoint.engine.runtime.size` doesn't exist yet. The replay showed:

````text
E   ModuleNotFoundError: No module named 'dewpoint.engine.runtime.size'
E   ImportError: cannot import name 'size' from 'dewpoint.engine.runtime'
ERROR tests/apps/test_codec.py
ERROR tests/apps/worker/test_activities.py
ERROR tests/apps/worker/test_run_graph_sizes.py
ERROR tests/apps/worker/test_temporal_contract.py
ERROR tests/engine/runtime/test_size.py
!!!!!!!!!!!!!!!!!!! Interrupted: 5 errors during collection !!!!!!!!!!!!!!!!!!!!
5 errors in 0.48s
````

- [ ] **Step 3: Implement**

````diff
diff --git a/backend/src/dewpoint/apps/codec.py b/backend/src/dewpoint/apps/codec.py
index 4d5c62c..c15b6a5 100644
--- a/backend/src/dewpoint/apps/codec.py
+++ b/backend/src/dewpoint/apps/codec.py
@@ -36,9 +36,6 @@ ENCODING = b"binary/dewpoint-tenant-v1"
 TENANT = "dewpoint-tenant"
 KEY_VERSION = "dewpoint-key-version"
 NONCE_BYTES = 12
-# What encoding adds to a payload's serialized size, at most: the metadata above, the nonce, the tag and the inner
-# payload's own framing. The outgoing-payload guard adds it to a payload's JSON bytes (spec §5.2); a test proves it.
-CODEC_OVERHEAD = 256
 
 
 class CodecRefusedError(Exception):
diff --git a/backend/src/dewpoint/apps/worker/activities.py b/backend/src/dewpoint/apps/worker/activities.py
index 6bd4401..6a06861 100644
--- a/backend/src/dewpoint/apps/worker/activities.py
+++ b/backend/src/dewpoint/apps/worker/activities.py
@@ -30,12 +30,14 @@ from pydantic import BaseModel, ValidationError
 from pydantic_core import PydanticSerializationError
 from pydantic_core.core_schema import ErrorType
 from temporalio import activity
+from temporalio.converter import DataConverter
 from temporalio.exceptions import ApplicationError
 
 from dewpoint.apps.cel_client import EvaluatorUnavailable, evaluate_remote
 from dewpoint.apps.worker.context import context
 from dewpoint.engine import ENGINE_ABI
 from dewpoint.engine.cel import ipc
+from dewpoint.engine.runtime import size
 from dewpoint.engine.runtime.activities import (
     APPLIED,
     CEL_EVALUATE,
@@ -83,6 +85,9 @@ _PYDANTIC_CODES = frozenset(get_args(ErrorType))  # every built-in validation er
 CHECKED_FORMATS = ("date", "uuid", "email", "ipv4", "ipv6", "regex")
 
 
+JSON = DataConverter.default.payload_converter  # what the SDK encodes a result with, before the codec
+
+
 class RunStore(Protocol):
     async def version(self, tenant_id: str, version_id: str) -> VersionData: ...
     async def project(self, data: ProjectInput) -> None: ...
@@ -201,7 +206,10 @@ def step_activity_for(node: type[Node]) -> Callable[[StepInput], Awaitable[StepR
         except _StepFailed as f:
             raise f.mapped() from None
         try:  # the node ran: whatever fails from here, its effect happened, so nothing is retried
-            return StepResult(output_of(result), outcome)
+            done = StepResult(output_of(result), outcome)
+            if not size.fits(done, JSON):  # Temporal would refuse to record it (engine 2b spec §5.2)
+                raise _StepFailed(size.PAYLOAD_TOO_LARGE, size.STEP_OUTPUT_TOO_LARGE, retryable=False, outcome=outcome)
+            return done
         except _StepFailed as f:
             raise f.mapped() from None
         except PydanticSerializationError:
@@ -237,6 +245,8 @@ def engine_activities(store: RunStore, plugins: Iterable[Plugin], *, abi: int =
                 type=VERSION_UNUSABLE,
                 non_retryable=True,
             )
+        if not size.fits(version, JSON):  # its result would pass Temporal's payload limit (engine 2b spec §5.2)
+            raise ApplicationError(size.VERSION_TOO_LARGE, type=VERSION_UNUSABLE, non_retryable=True)
         return version
 
     @activity.defn(name=PROJECT)
diff --git a/backend/src/dewpoint/engine/runtime/size.py b/backend/src/dewpoint/engine/runtime/size.py
new file mode 100644
index 0000000..e229ed7
--- /dev/null
+++ b/backend/src/dewpoint/engine/runtime/size.py
@@ -0,0 +1,31 @@
+# SPDX-License-Identifier: Apache-2.0
+"""What the engine sends Temporal, and what it gets back, measured before it goes (engine 2b spec §5.2). Temporal
+refuses a payload over 2 MiB once the codec has encoded it, and its SDK then retries the workflow task forever; so
+each payload is checked where it's produced — a step's result in its activity, a run's result in the run, a command
+before the workflow sends it — against PAYLOAD_BYTES, measured as the payload converter's JSON plus CODEC_OVERHEAD,
+a bound on what the tenant codec adds (a test of the codec proves it). Too large fails the step, the loop or the run
+with `payload_too_large`: a result, never a retried workflow task. Nothing is spilled before 2b-1b's claims.
+
+`fits` reads the limit from this module when it's called, so a test can lower it; workflow code imports names from
+this module's full path, which the sandbox passes through (a submodule taken from its package would be a copy)."""
+
+from typing import Any
+
+from temporalio.converter import PayloadConverter
+
+CODEC_OVERHEAD = 256  # bytes the tenant codec adds to a payload, at most: its metadata, the nonce and the tag
+PAYLOAD_BYTES = 1_835_008  # 1.75 MiB, encoded: a margin under Temporal's 2 MiB (2,097,152) payload limit
+PAYLOAD_TOO_LARGE = "payload_too_large"
+STEP_OUTPUT_TOO_LARGE = "The step's output is too large to record (over 1.75 MiB)."
+VERSION_TOO_LARGE = "The version is too large to load (over 1.75 MiB)."
+OUTPUTS_TOO_LARGE = "The run's outputs are too large to return (over 1.75 MiB)."
+BATCH_RESULTS_TOO_LARGE = "A batch of this loop collected too much to return (over 1.75 MiB)."
+
+
+def encoded_bytes(value: Any, converter: PayloadConverter) -> int:
+    """At most what `value`'s payload weighs once the codec has encoded it."""
+    return len(converter.to_payloads([value])[0].data) + CODEC_OVERHEAD
+
+
+def fits(value: Any, converter: PayloadConverter) -> bool:
+    return encoded_bytes(value, converter) <= PAYLOAD_BYTES
diff --git a/backend/src/dewpoint/engine/runtime/workflow.py b/backend/src/dewpoint/engine/runtime/workflow.py
index d0004e7..90fdb3f 100644
--- a/backend/src/dewpoint/engine/runtime/workflow.py
+++ b/backend/src/dewpoint/engine/runtime/workflow.py
@@ -61,6 +61,7 @@ with workflow.unsafe.imports_passed_through():
         RunEnd,
         Scheduler,
     )
+    from dewpoint.engine.runtime.size import BATCH_RESULTS_TOO_LARGE, OUTPUTS_TOO_LARGE, PAYLOAD_TOO_LARGE, fits
 
 
 HANDLED = ("failed", DEADLINE_EXCEEDED)  # the ends that run a failure handler (a cancel is no failure)
@@ -169,6 +170,8 @@ class RunGraph(Execution):
             end = self.sched.ended or RunEnd("failed", Failure("error", "The run ended without a result."))
             if end.status == "succeeded":
                 end, outputs = await self._outputs_by(end)
+            if outputs is not None and not self._returnable(outputs):  # checked here, where the result is made
+                end, outputs = RunEnd("failed", Failure(PAYLOAD_TOO_LARGE, OUTPUTS_TOO_LARGE)), None
         except asyncio.CancelledError:
             self.sched.end(RunEnd("cancelled", CANCELLED))
             result = await self._finish(RunEnd("cancelled", CANCELLED))
@@ -221,6 +224,12 @@ class RunGraph(Execution):
         except resolve.ValueFailure as e:
             return RunEnd("failed", e.failure), None
 
+    def _returnable(self, outputs: dict[str, Any]) -> bool:
+        """The run's result, with these outputs, within Temporal's payload limit (engine 2b spec §5.2). Past it,
+        Temporal would refuse to record the result, and the workflow task would retry until the deadline."""
+        result = RunResult("succeeded", outputs, None, self.sched.iterations, list(self._secrets))
+        return fits(result, workflow.payload_converter())
+
     async def _outputs(self) -> dict[str, Any]:
         settings_outputs = self.program.graph.settings.outputs
         pairs = [(pointer_str(p), v) for p, v in iter_values(settings_outputs, ("settings", "outputs"))]
@@ -445,13 +454,19 @@ class LoopBatch(Execution):
         if outcome is None:  # the run ended inside the batch
             end = end or RunEnd("failed", Failure("error", "The batch ended without a result."))
             return BatchResult([], [], end=end.to_json(), iterations=self.sched.iterations, secrets=list(self._secrets))
-        return BatchResult(
+        result = BatchResult(
             collected=outcome.collected,
             failures=outcome.failures,
             stopped=outcome.stopped.to_json() if outcome.stopped else None,
             iterations=self.sched.iterations,
             secrets=list(self._secrets),
         )
+        if fits(result, workflow.payload_converter()):
+            return result
+        # Temporal would refuse to record it (engine 2b spec §5.2): the loop fails instead, and no collected item is
+        # dropped silently. The iterations it used still reach the parent.
+        stopped = Failure(PAYLOAD_TOO_LARGE, BATCH_RESULTS_TOO_LARGE)
+        return BatchResult([], [], stopped.to_json(), iterations=self.sched.iterations, secrets=list(self._secrets))
 
 
 __all__ = [
````

- [ ] **Step 4: Run the tests again**

Run: `cd backend && uv run pytest -q -p no:cacheprovider tests/apps/test_codec.py tests/apps/worker/test_activities.py tests/apps/worker/test_run_graph_sizes.py tests/apps/worker/test_temporal_contract.py tests/core/plugins/test_registry.py tests/engine/runtime/test_size.py`

Expected (the replay):

````text
53 passed in 31.74s
````

- [ ] **Step 5: The whole suite, lint, types and layers**

Run: `cd backend && uv run pytest -q -p no:cacheprovider`, then `uv run ruff check --no-cache src tests migrations`, `uv run ruff format --no-cache --check src tests migrations`, `uv run mypy src` and `uv run lint-imports`.

Expected: 1,186 passed, 8 skipped; ruff and its formatter clean; mypy: no issues; import-linter: 10 contracts kept.

- [ ] **Step 6: Commit**

```bash
git add -A backend deploy docs && git commit -m "feat(engine): results guarded where they're produced (2b-1a)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: Commands checked before they're sent

**Spec:** §5.2, §5.3.

**Files:**
- Modify: `backend/src/dewpoint/apps/runs.py`
- Modify: `backend/src/dewpoint/engine/__init__.py`
- Modify: `backend/src/dewpoint/engine/runtime/execution.py`
- Modify: `backend/src/dewpoint/engine/runtime/resolve.py`
- Modify: `backend/src/dewpoint/engine/runtime/scheduler.py`
- Modify: `backend/src/dewpoint/engine/runtime/size.py`
- Modify: `backend/src/dewpoint/engine/runtime/workflow.py`
- Modify: `backend/tests/apps/test_runs.py`
- Modify: `backend/tests/apps/worker/test_run_graph_sizes.py`
- Modify: `backend/tests/engine/runtime/test_scheduler_batches.py`

**Interfaces:**
- Consumes: Task 9's `size` module and `fits`.
- Produces:
  - in `size`: `SNAPSHOT_BYTES`, `SNAPSHOT_TOO_LARGE`, `RUN_INPUT_TOO_LARGE`, `STEP_INPUT_TOO_LARGE`,
    `SUBFLOW_INPUT_TOO_LARGE`, `HANDLER_INPUT_TOO_LARGE`, `BATCH_ITEM_TOO_LARGE`, `RUN_SNAPSHOT_TOO_LARGE`,
    `BATCH_SNAPSHOT_TOO_LARGE`, `payload_bytes() -> int`, `snapshot_fits(value, converter) -> bool`;
  - `Scheduler.cut_batch(loop_inst, start, end)`;
  - `Execution._batch_input(b, grant) -> BatchInput`.

Each command is measured before it's sent, and nothing that doesn't fit is sent:
- **A step's input**: too large fails the step, its attempt-1 row saying why.
- **A sub-flow's start**: too large fails the step, and its grant is given back.
- **A failure handler's start**: too large, the handler's row records `payload_too_large`, and the run's end stands.
- **A loop's batch** is cut by bytes as well as count. `resolve.request_end` finds how many items fit with the
  batch's envelope (the trigger, the outer scopes it reads, its parent); `Scheduler.cut_batch` hands the rest to the
  next batch. A first item that can't fit fails the loop, after the items before it.
- **A continued run's input**, over `SNAPSHOT_BYTES`, fails the run with `snapshot_too_large`; a batch fails its loop.
- **`start_run`** measures the start it would send before admission. Too large is `NotAdmissibleError`, with no row.

- [ ] **Step 1: Write the tests**

````diff
diff --git a/backend/tests/apps/test_runs.py b/backend/tests/apps/test_runs.py
index 17ad7a7..4cf3e1c 100644
--- a/backend/tests/apps/test_runs.py
+++ b/backend/tests/apps/test_runs.py
@@ -32,8 +32,10 @@ from dewpoint.core.plugins import lifecycle
 from dewpoint.core.runs import service
 from dewpoint.core.workflows import service as workflows
 from dewpoint.engine import ENGINE_ABI
+from dewpoint.engine.runtime import size
 from dewpoint.engine.runtime.activities import ENGINE_QUEUE, SIMULATE, RunInput
 from dewpoint.engine.runtime.ids import run_workflow_id
+from dewpoint.engine.runtime.size import RUN_INPUT_TOO_LARGE
 from tests.apps.test_lifecycle_races import until_someone_waits_for_a_lock
 from tests.apps.test_workflow_ops import (
     ECHO,
@@ -532,3 +534,23 @@ async def test_a_start_that_cant_be_encrypted_is_refused_and_its_run_failed(
     assert client.calls == []  # never sent
     row = await only_run(owner_sessionmaker, ctx.tenant_id)
     assert (row.status, row.error_code) == ("failed", START_FAILED)
+
+
+async def test_a_run_whose_input_is_too_large_to_start_is_refused_before_admission(
+    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings, monkeypatch
+) -> None:
+    """Engine 2b spec §5.2: the client checks the start it would send, before the run is admitted: no row, no start,
+    and a fixed reason, never Temporal's refusal."""
+    monkeypatch.setattr(size, "PAYLOAD_BYTES", 10_000)
+    ctx, _, version = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings)
+    client = FakeClient()
+    with pytest.raises(NotAdmissibleError) as refused:
+        await start_run(
+            dispatch_sessionmaker, client, api_settings,  # type: ignore[arg-type]
+            tenant_id=ctx.tenant_id, version_id=version, trigger={"x": "y" * 10_000},
+        )  # fmt: skip
+    assert refused.value.reasons == [RUN_INPUT_TOO_LARGE]
+    async with owner_sessionmaker() as s, s.begin():
+        await tenant_scope(s, ctx.tenant_id)
+        assert await service.list_runs(s) == []
+    assert client.started == []
diff --git a/backend/tests/apps/worker/test_run_graph_sizes.py b/backend/tests/apps/worker/test_run_graph_sizes.py
index 6b3db9d..f324f49 100644
--- a/backend/tests/apps/worker/test_run_graph_sizes.py
+++ b/backend/tests/apps/worker/test_run_graph_sizes.py
@@ -8,17 +8,25 @@ import asyncio
 from typing import Any
 
 import pytest
+from temporalio.api.enums.v1 import EventType
 from temporalio.client import WorkflowHandle
 from temporalio.testing import WorkflowEnvironment
 
 from dewpoint.engine.runtime import size
 from dewpoint.engine.runtime.activities import RunResult
-from dewpoint.engine.runtime.size import OUTPUTS_TOO_LARGE, PAYLOAD_TOO_LARGE
+from dewpoint.engine.runtime.size import (
+    OUTPUTS_TOO_LARGE,
+    PAYLOAD_TOO_LARGE,
+    RUN_SNAPSHOT_TOO_LARGE,
+    SNAPSHOT_TOO_LARGE,
+    STEP_INPUT_TOO_LARGE,
+)
 from tests.apps.worker.harness import MemoryStore, run_id_of, start, workers
 from tests.support.graphs import G, ref
 
 LIMIT = 50_000
-BLOB, LOOP, RUN = "testkit.blob@1", "flow.loop@1", "flow.run_workflow@1"
+ITEMS = {"type": "object", "properties": {"items": {"type": "array"}}, "required": ["items"]}
+BLOB, ECHO, LOOP, RUN = "testkit.blob@1", "testkit.echo@1", "flow.loop@1", "flow.run_workflow@1"
 
 
 @pytest.fixture(autouse=True)
@@ -87,3 +95,144 @@ async def test_a_batch_that_collected_too_much_to_return_fails_its_loop(env: Wor
     _, result = await finished(env, store, g)
     assert (result.status, result.outputs) == ("succeeded", {"code": PAYLOAD_TOO_LARGE})
     assert result.iterations == 100  # the batch reported what it used
+
+
+async def children_started(handle: WorkflowHandle[Any, Any]) -> int:
+    events = (await handle.fetch_history()).events
+    return sum(e.event_type == EventType.EVENT_TYPE_CHILD_WORKFLOW_EXECUTION_STARTED for e in events)
+
+
+async def activities_scheduled(handle: WorkflowHandle[Any, Any], name: str) -> int:
+    return sum(
+        e.activity_task_scheduled_event_attributes.activity_type.name == name
+        for e in (await handle.fetch_history()).events
+        if e.event_type == EventType.EVENT_TYPE_ACTIVITY_TASK_SCHEDULED
+    )
+
+
+async def test_a_step_input_too_large_to_send_fails_the_step_before_any_attempt(env: WorkflowEnvironment) -> None:
+    store = MemoryStore()
+    g = graph(code=ref("steps.e.error.code", default="none"))
+    g.node("a", BLOB, {"size": LIMIT // 2}).node("b", BLOB, {"size": LIMIT // 2})
+    g.node("e", ECHO, {"value": [ref("steps.a.output.value"), ref("steps.b.output.value")]}, on_error="continue")
+    g.edge("a", "e").edge("b", "e")
+    handle, result = await finished(env, store, g)
+    assert (result.status, result.outputs) == ("succeeded", {"code": PAYLOAD_TOO_LARGE})
+    [row] = [r for r in store.steps(run_id_of(handle)) if r.node_key == "e"]
+    assert (row.attempt, row.status, row.error_code, row.error_message) == (
+        1,
+        "failed",
+        PAYLOAD_TOO_LARGE,
+        STEP_INPUT_TOO_LARGE,
+    )
+    assert await activities_scheduled(handle, "testkit.echo.v1") == 0  # never sent
+
+
+async def test_a_sub_flow_input_too_large_to_send_fails_its_step_and_starts_nothing(env: WorkflowEnvironment) -> None:
+    store = MemoryStore()
+    sub = graph().node("e", ECHO, {"value": 1})
+    g = graph(code=ref("steps.r.error.code", default="none"))
+    g.node("a", BLOB, {"size": LIMIT // 2}).node("b", BLOB, {"size": LIMIT // 2})
+    g.node(
+        "r",
+        RUN,
+        {
+            "workflow_id": str(store.publish(sub)),
+            "input": {"a": ref("steps.a.output.value"), "b": ref("steps.b.output.value")},
+        },
+        on_error="continue",
+    )
+    g.edge("a", "r").edge("b", "r")
+    handle, result = await finished(env, store, g)
+    assert (result.status, result.outputs, result.iterations) == ("succeeded", {"code": PAYLOAD_TOO_LARGE}, 0)
+    assert store.starts == {}  # no sub-run
+
+
+def items(n: int, each: int) -> list[str]:
+    return [f"{i:05d}" + "x" * (each - 5) for i in range(n)]
+
+
+async def test_a_batch_is_cut_by_bytes_and_keeps_every_item_in_order(env: WorkflowEnvironment) -> None:
+    """A batch carries the trigger too: 150 items of 250 characters each fit about 49 to a batch under the limit, not
+    100 (the count cut). Every item is still run once, in order."""
+    store = MemoryStore()
+    g = graph(items=ref("steps.l.output.items"))
+    g.settings["input_schema"] = ITEMS
+    g.node("l", LOOP, {"items": ref("trigger.items"), "collect": ref("steps.x.output.value")})
+    g.node("x", ECHO, {"value": ref("item")}).edge("l", "x", "body")
+    trigger = {"items": items(150, 250)}
+    async with workers(env.client, store):
+        handle = await start(env.client, store, g, trigger)
+        result = await asyncio.wait_for(handle.result(), 60)
+    assert (result.status, result.outputs) == ("succeeded", {"items": trigger["items"]})
+    assert await children_started(handle) > 2  # cut by bytes: the count alone would have made two
+
+
+async def test_an_item_too_large_for_a_batch_fails_its_loop_after_the_items_before_it(env: WorkflowEnvironment) -> None:
+    """It's never dropped: the loop fails with `payload_too_large` once it reaches it."""
+    store = MemoryStore()
+    g = graph(code=ref("steps.l.error.code", default="none"))
+    g.settings["input_schema"] = ITEMS
+    g.node("l", LOOP, {"items": ref("trigger.items"), "collect": ref("steps.x.output.value")}, on_error="continue")
+    g.node("x", ECHO, {"value": ref("item")}).edge("l", "x", "body")
+    trigger = {"items": [*items(120, 10), "y" * (LIMIT // 2), *items(10, 10)]}
+    async with workers(env.client, store):
+        handle = await start(env.client, store, g, trigger)
+        result = await asyncio.wait_for(handle.result(), 60)
+    assert (result.status, result.outputs) == ("succeeded", {"code": PAYLOAD_TOO_LARGE})
+    ran = {r.iteration_key for r in store.steps(run_id_of(handle)) if r.node_key == "x"}
+    assert ran == {f"l:{i}" for i in range(120)}  # every item before it, and none after
+
+
+async def test_a_snapshot_too_large_to_carry_on_fails_the_run(
+    env: WorkflowEnvironment, monkeypatch: pytest.MonkeyPatch
+) -> None:
+    """2b-1a's promise for continue-as-new (spec §5.3): a clean `snapshot_too_large`, never a retried workflow task."""
+    monkeypatch.setattr(size, "SNAPSHOT_BYTES", 5_000)
+    store = MemoryStore()
+    g = graph(items=ref("steps.l.output.items"))
+    g.node("l", LOOP, {"items": list(range(40)), "collect": ref("steps.x.output.value")})
+    g.node("x", ECHO, {"value": "v" * 200}).edge("l", "x", "body")
+    async with workers(env.client, store):
+        handle = await start(env.client, store, g, {}, checkpoint_events=120)
+        result = await asyncio.wait_for(handle.result(), 60)
+    assert result.status == "failed" and result.error is not None
+    assert (result.error["code"], result.error["message"]) == (SNAPSHOT_TOO_LARGE, RUN_SNAPSHOT_TOO_LARGE)
+    assert store.runs[run_id_of(handle)].error_code == SNAPSHOT_TOO_LARGE
+
+
+async def test_a_batch_whose_snapshot_is_too_large_fails_its_loop(
+    env: WorkflowEnvironment, monkeypatch: pytest.MonkeyPatch
+) -> None:
+    monkeypatch.setattr(size, "SNAPSHOT_BYTES", 5_000)
+    store = MemoryStore()
+    g = graph(code=ref("steps.l.error.code", default="none"))
+    g.node("l", LOOP, {"items": list(range(150)), "collect": ref("steps.x.output.value")}, on_error="continue")
+    g.node("x", ECHO, {"value": "v" * 200}).edge("l", "x", "body")
+    async with workers(env.client, store):
+        handle = await start(env.client, store, g, {}, checkpoint_events=120)
+        result = await asyncio.wait_for(handle.result(), 60)
+    assert (result.status, result.outputs) == ("succeeded", {"code": SNAPSHOT_TOO_LARGE})
+
+
+async def test_a_failure_handler_whose_input_is_too_large_never_starts_and_says_why(env: WorkflowEnvironment) -> None:
+    """Its input carries what the run learned is sensitive, to mask it too: past the limit, the handler's row records
+    `payload_too_large`, and the run's own end stands."""
+    store = MemoryStore()
+    g = graph()
+    g.settings["input_schema"] = {
+        "type": "object",
+        "properties": {"key": {"type": "string", "x-sensitive": True}},
+        "required": ["key"],
+    }
+    g.settings["failure_handler"] = str(store.publish(graph().node("h", ECHO, {"value": 1})))
+    g.node("f", "flow.fail@1", {"message": "it went wrong"})
+    async with workers(env.client, store):
+        handle = await start(env.client, store, g, {"key": "k" * LIMIT})
+        result = await asyncio.wait_for(handle.result(), 60)
+    assert result.status == "failed" and result.error is not None and result.error["code"] == "workflow_failed"
+    [(child, row)] = store.starts.items()
+    assert row.kind == "failure_handler"
+    assert (store.runs[child].status, store.runs[child].error_code) == ("failed", PAYLOAD_TOO_LARGE)
+    assert store.runs[run_id_of(handle)].status == "failed"
+    assert await children_started(handle) == 0  # it was never sent
diff --git a/backend/tests/engine/runtime/test_scheduler_batches.py b/backend/tests/engine/runtime/test_scheduler_batches.py
index 7f32870..0603abc 100644
--- a/backend/tests/engine/runtime/test_scheduler_batches.py
+++ b/backend/tests/engine/runtime/test_scheduler_batches.py
@@ -164,3 +164,31 @@ def test_a_batched_loop_survives_a_snapshot() -> None:
     s.batch_done(loop, b.start, BatchOutcome(list(b.items), []))
     [b2] = s.take_batches()
     assert b2 == Batch(loop, 100, list(range(100, 150)))
+
+
+def test_a_batch_cut_short_hands_its_remaining_items_to_the_next_one() -> None:
+    """Engine 2b spec §5.2: a batch whose items don't all fit in one payload is cut as it starts; the rest go in the
+    next batch, in order."""
+    s, loop = parent_at_loop(250)
+    [b] = s.take_batches()
+    s.cut_batch(loop, b.start, 40)
+    s.batch_done(loop, 0, BatchOutcome([i * 10 for i in range(40)], []))
+    [following] = s.take_batches()
+    assert (following.start, len(following.items), following.items[0]) == (40, 100, 40)
+    s.batch_done(loop, 40, BatchOutcome([i * 10 for i in range(40, 140)], []))
+    [last] = s.take_batches()
+    s.batch_done(loop, 140, BatchOutcome([i * 10 for i in range(140, 240)], []))
+    [tail] = s.take_batches()
+    s.batch_done(loop, 240, BatchOutcome([i * 10 for i in range(240, 250)], []))
+    assert (last.start, tail.start, len(tail.items)) == (140, 240, 10)
+    assert s.scopes[()].results["l"]["output"]["items"] == [i * 10 for i in range(250)]
+
+
+def test_a_cut_that_isnt_shorter_changes_nothing() -> None:
+    s, loop = parent_at_loop(250)
+    [b] = s.take_batches()
+    s.cut_batch(loop, b.start, 100)  # the whole batch fits
+    s.cut_batch(loop, 100, 150)  # not the batch that's running
+    s.batch_done(loop, 0, BatchOutcome(list(range(100)), []))
+    [following] = s.take_batches()
+    assert following.start == 100
````

- [ ] **Step 2: Run them, and watch them fail**

Run: `cd backend && uv run pytest -q -p no:cacheprovider tests/apps/test_runs.py tests/apps/worker/test_run_graph_sizes.py tests/engine/runtime/test_scheduler_batches.py`

Expected: FAIL. `size` has none of the new names yet. The replay showed:

````text
E   ImportError: cannot import name 'RUN_INPUT_TOO_LARGE' from 'dewpoint.engine.runtime.size'
E   ImportError: cannot import name 'RUN_SNAPSHOT_TOO_LARGE' from 'dewpoint.engine.runtime.size'
ERROR tests/apps/test_runs.py
ERROR tests/apps/worker/test_run_graph_sizes.py
!!!!!!!!!!!!!!!!!!! Interrupted: 2 errors during collection !!!!!!!!!!!!!!!!!!!!
2 errors in 0.46s
````

- [ ] **Step 3: Implement**

````diff
diff --git a/backend/src/dewpoint/apps/runs.py b/backend/src/dewpoint/apps/runs.py
index 84e60ec..6488542 100644
--- a/backend/src/dewpoint/apps/runs.py
+++ b/backend/src/dewpoint/apps/runs.py
@@ -22,7 +22,7 @@ from typing import Any
 from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
 from temporalio.client import Client
 from temporalio.common import WorkflowIDReusePolicy
-from temporalio.converter import WorkflowSerializationContext
+from temporalio.converter import DataConverter, WorkflowSerializationContext
 from temporalio.exceptions import WorkflowAlreadyStartedError
 from temporalio.service import RPCError, RPCStatusCode
 
@@ -36,6 +36,7 @@ from dewpoint.core.platform.service import NOT_RECORDED, PRODUCTION, recorded
 from dewpoint.core.plugins import lifecycle
 from dewpoint.core.runs import service as runs
 from dewpoint.core.workflows.service import lock_for_admission, other_abi
+from dewpoint.engine.runtime import size
 from dewpoint.engine.runtime.activities import ENGINE_QUEUE, LIVE, RunInput
 from dewpoint.engine.runtime.ids import run_workflow_id
 from dewpoint.engine.runtime.workflow import RunGraph
@@ -153,19 +154,26 @@ async def start_run(
 ) -> uuid.UUID:
     """Admit the run and start it. Raises NotAdmissibleError, StartRefusedError (the run is recorded as failed) or
     StartUncertainError (the run stays `running`: it may be executing). A promotion between the admission and the
-    start is caught when the run loads its version (§7)."""
+    start is caught when the run loads its version (§7). A start too large to send is refused before admission, so
+    it leaves no row (engine 2b spec §5.2)."""
+
+    def start_of(run_id: uuid.UUID) -> RunInput:
+        return RunInput(
+            tenant_id=str(tenant_id),
+            run_id=str(run_id),
+            version_id=str(version_id),
+            trigger=trigger,
+            mode=mode,
+            max_run_duration_s=settings.max_run_duration_days * 86_400,
+            cel_schedule_to_start_s=settings.cel_schedule_to_start_s,
+        )
+
+    if not size.fits(start_of(uuid.UUID(int=0)), DataConverter.default.payload_converter):  # a run id's length
+        raise NotAdmissibleError([size.RUN_INPUT_TOO_LARGE])
     abi = await current_abi(client)  # before the transaction: no lock is held across a call to Temporal
     async with sessionmaker() as s, s.begin():
         run = await admit(s, tenant_id=tenant_id, version_id=version_id, abi=abi, mode=mode, started_by=started_by)
-    start = RunInput(
-        tenant_id=str(tenant_id),
-        run_id=str(run.id),
-        version_id=str(version_id),
-        trigger=trigger,
-        mode=mode,
-        max_run_duration_s=settings.max_run_duration_days * 86_400,
-        cel_schedule_to_start_s=settings.cel_schedule_to_start_s,
-    )
+    start = start_of(run.id)
     try:
         await _start(client, start, run.id)
     except StartRefusedError as e:
diff --git a/backend/src/dewpoint/engine/__init__.py b/backend/src/dewpoint/engine/__init__.py
index 794b227..955ebe6 100644
--- a/backend/src/dewpoint/engine/__init__.py
+++ b/backend/src/dewpoint/engine/__init__.py
@@ -5,5 +5,6 @@
 # any change that can alter a run's command sequence. 2: 2a-3b's loop batches, sub-flows, the failure handler and
 # continue-as-new. 3: 2a-3c's local CEL. 4: issue #15's cel.evaluate requests, cut by their bytes, refused when one
 # binding set can't fit, and paced per workflow task. 5: 2b-1a's workflow ids, built from the tenant and the run
-# (sub-flows' and failure handlers' too).
+# (sub-flows' and failure handlers' too), and what a run sends Temporal, measured before it's sent: a loop's batch cut
+# by bytes, a continued run's state within 1.5 MiB.
 ENGINE_ABI = 5
diff --git a/backend/src/dewpoint/engine/runtime/execution.py b/backend/src/dewpoint/engine/runtime/execution.py
index 90e0850..7102780 100644
--- a/backend/src/dewpoint/engine/runtime/execution.py
+++ b/backend/src/dewpoint/engine/runtime/execution.py
@@ -84,6 +84,15 @@ with workflow.unsafe.imports_passed_through():
         ScopeKey,
         iteration_key,
     )
+    from dewpoint.engine.runtime.size import (
+        BATCH_ITEM_TOO_LARGE,
+        PAYLOAD_TOO_LARGE,
+        STEP_INPUT_TOO_LARGE,
+        SUBFLOW_INPUT_TOO_LARGE,
+        encoded_bytes,
+        fits,
+        payload_bytes,
+    )
 
 IN_FLIGHT_CAP = 100  # activities and child workflows outstanding per execution (spec §6)
 PROJECT_BYTES = 256 * 1024  # a projection's rows at most, as JSON: far below Temporal's 2 MiB payload limit
@@ -867,6 +876,10 @@ class Execution:
             checkpoint_events=self.checkpoint_events,
             drain_events=self.drain_events,
         )
+        if not fits(run, workflow.payload_converter()):  # engine 2b spec §5.2: never sent, so it never ran
+            self.sched.budget.settle_child(child, 0)
+            self._dirty = True
+            return _Effect(failure=Failure(PAYLOAD_TOO_LARGE, SUBFLOW_INPUT_TOO_LARGE), cel_mode=cel_mode)
         used: int | None = None  # until it reports, all it was granted counts: it may have run
         started = workflow.now().isoformat()
         try:
@@ -925,13 +938,61 @@ class Execution:
         """A batch of a loop's items, as a child `LoopBatch`. It writes its iterations' rows into this run, and
         returns what they collected."""
         step = self.sched.step(b.loop)
-        loop = self.sched.loops[b.loop]
         # from the input, not the workflow id: a replay of this history sees the same id (the run id names the logical
         # run, the loop step and its scope name the loop, the start names the batch)
         child = (
             f"{run_workflow_id(self.tenant_id, self.run_id)}/{step.id}/{iteration_key(b.loop.scope)}/batch:{b.start}"
         )
+        converter = workflow.payload_converter()
+        draft = self._batch_input(b, len(b.items))
+        if not fits(draft, converter):  # engine 2b spec §5.2: as many of its items as fit, in order; the rest follow
+            items = b.items
+            envelope = encoded_bytes(replace(draft, items=[]), converter)
+            fit, _ = resolve.request_end(
+                0,
+                len(items),
+                lambda i: len(converter.to_payloads([items[i]])[0].data),
+                envelope=envelope,
+                batch=len(items),
+                limit=payload_bytes(),
+            )
+            if fit == 0:  # its first item alone doesn't fit: the loop fails there, and nothing is dropped
+                return _Effect(failure=Failure(PAYLOAD_TOO_LARGE, BATCH_ITEM_TOO_LARGE))
+            self.sched.cut_batch(b.loop, b.start, b.start + fit)
+            b = replace(b, items=items[:fit])
         grant = self.sched.budget.start_child(child, len(b.items))
+        batch = self._batch_input(b, grant)
+        used: int | None = None  # until it reports, all it was granted counts: it may have run
+        try:
+            try:
+                handle = await workflow.start_child_workflow(
+                    "LoopBatch", batch, result_type=BatchResult, **child_options(child)
+                )
+            except ChildWorkflowError:  # cancelled before its start went out, as the SDK reports it: it never ran
+                used = 0
+                raise asyncio.CancelledError from None
+            result = await handle
+            used = result.iterations
+        except ChildWorkflowError as e:  # its version didn't load or compile, a bug, or it was terminated
+            cause = e.cause
+            if isinstance(cause, ApplicationError) and cause.type in (VERSION_UNUSABLE, INTERNAL_ERROR):
+                return _Effect(failure=Failure(cause.type, cause.message))
+            return _Effect(failure=self._lost("batch", e))
+        finally:
+            self.sched.budget.settle_child(child, used)
+            self._dirty = True
+        self._secrets = remember(self._secrets, tuple(result.secrets))
+        if result.end is not None:
+            end = RunEnd.from_json(result.end)
+            if end.status == "cancelled":
+                return _Effect(failure=CANCELLED)
+            return _Effect(end=end)
+        stopped = Failure.from_json(result.stopped) if result.stopped else None
+        return _Effect(batch=BatchOutcome(list(result.collected), list(result.failures), stopped))
+
+    def _batch_input(self, b: Batch, grant: int) -> BatchInput:
+        step = self.sched.step(b.loop)
+        loop = self.sched.loops[b.loop]
         parent = Parent(
             workflow_id=workflow.info().workflow_id,
             run_id=self.run_id,
@@ -943,7 +1004,7 @@ class Execution:
             depth=self.depth,
             secrets=list(self._secrets),
         )
-        batch = BatchInput(
+        return BatchInput(
             tenant_id=self.tenant_id,
             run_id=self.run_id,
             version_id=self.version_id,
@@ -962,33 +1023,6 @@ class Execution:
             checkpoint_events=self.checkpoint_events,
             drain_events=self.drain_events,
         )
-        used: int | None = None  # until it reports, all it was granted counts: it may have run
-        try:
-            try:
-                handle = await workflow.start_child_workflow(
-                    "LoopBatch", batch, result_type=BatchResult, **child_options(child)
-                )
-            except ChildWorkflowError:  # cancelled before its start went out, as the SDK reports it: it never ran
-                used = 0
-                raise asyncio.CancelledError from None
-            result = await handle
-            used = result.iterations
-        except ChildWorkflowError as e:  # its version didn't load or compile, a bug, or it was terminated
-            cause = e.cause
-            if isinstance(cause, ApplicationError) and cause.type in (VERSION_UNUSABLE, INTERNAL_ERROR):
-                return _Effect(failure=Failure(cause.type, cause.message))
-            return _Effect(failure=self._lost("batch", e))
-        finally:
-            self.sched.budget.settle_child(child, used)
-            self._dirty = True
-        self._secrets = remember(self._secrets, tuple(result.secrets))
-        if result.end is not None:
-            end = RunEnd.from_json(result.end)
-            if end.status == "cancelled":
-                return _Effect(failure=CANCELLED)
-            return _Effect(end=end)
-        stopped = Failure.from_json(result.stopped) if result.stopped else None
-        return _Effect(batch=BatchOutcome(list(result.collected), list(result.failures), stopped))
 
     # --- plugin steps ---------------------------------------------------------------------------------------------
 
@@ -1016,20 +1050,30 @@ class Execution:
                 cel_mode=cel_mode,
             )
             self._queue(row)
+            sent = StepInput(
+                tenant_id=self.tenant_id,
+                run_id=self.run_id,
+                step_id=str(step.id),
+                node_key=step.key,
+                iteration_key=iteration_key(inst.scope),
+                ref=step.ref,
+                config=config,
+                mode=self.mode,
+                attempt=attempt,
+            )
+            if not fits(sent, workflow.payload_converter()):  # engine 2b spec §5.2: never sent, so it never ran
+                failure = Failure(PAYLOAD_TOO_LARGE, STEP_INPUT_TOO_LARGE, attempt)
+                ended = workflow.now().isoformat()
+                self._queue(
+                    replace(
+                        row, status="failed", ended_at=ended, error_code=failure.code, error_message=failure.message
+                    )
+                )
+                return _Effect(failure=failure, cel_mode=cel_mode)
             try:
                 result = await workflow.execute_activity(
                     step_activity(step.ref),
-                    StepInput(
-                        tenant_id=self.tenant_id,
-                        run_id=self.run_id,
-                        step_id=str(step.id),
-                        node_key=step.key,
-                        iteration_key=iteration_key(inst.scope),
-                        ref=step.ref,
-                        config=config,
-                        mode=self.mode,
-                        attempt=attempt,
-                    ),
+                    sent,
                     result_type=StepResult,
                     start_to_close_timeout=timeout,
                     retry_policy=RetryPolicy(maximum_attempts=1),
diff --git a/backend/src/dewpoint/engine/runtime/resolve.py b/backend/src/dewpoint/engine/runtime/resolve.py
index 8319589..abe4d77 100644
--- a/backend/src/dewpoint/engine/runtime/resolve.py
+++ b/backend/src/dewpoint/engine/runtime/resolve.py
@@ -154,7 +154,8 @@ def request_end(
     """Where the `cel.evaluate` request that starts at binding set `start` ends (exclusive), and its JSON bytes: as
     many sets as fit in `limit`, at most `batch` (#15). A request's JSON is its envelope (no sets) plus each set's JSON
     and a comma between sets, so `size_of(i)` measures one set at a time. Requests that fit are cut every `batch` sets,
-    as before. An end equal to `start` means set `start` alone passes the limit."""
+    as before. An end equal to `start` means set `start` alone passes the limit. A loop's batch is cut the same way,
+    its items in place of the sets (engine 2b spec §5.2)."""
     end, size = start, envelope
     while end < min(start + batch, count):
         extra = size_of(end) + (1 if end > start else 0)
diff --git a/backend/src/dewpoint/engine/runtime/scheduler.py b/backend/src/dewpoint/engine/runtime/scheduler.py
index 70bba5d..7448ef1 100644
--- a/backend/src/dewpoint/engine/runtime/scheduler.py
+++ b/backend/src/dewpoint/engine/runtime/scheduler.py
@@ -330,6 +330,13 @@ class Scheduler:
             return
         self._advance(loop)
 
+    def cut_batch(self, loop_inst: Instance, start: int, end: int) -> None:
+        """The running batch that starts at `start` ends at `end` instead: the items after it didn't fit in one payload
+        with it (engine 2b spec §5.2). They go in the loop's next batch."""
+        loop = self.loops.get(loop_inst)
+        if loop is not None and loop.running_batch == start and start < end < loop.next:
+            loop.next = end
+
     def batch_failed(self, loop_inst: Instance, start: int, failure: Failure) -> None:
         """A batch child failed as a whole (not one of its iterations): the loop fails with it."""
         loop = self.loops.get(loop_inst)
diff --git a/backend/src/dewpoint/engine/runtime/size.py b/backend/src/dewpoint/engine/runtime/size.py
index e229ed7..ab49a95 100644
--- a/backend/src/dewpoint/engine/runtime/size.py
+++ b/backend/src/dewpoint/engine/runtime/size.py
@@ -15,7 +15,16 @@ from temporalio.converter import PayloadConverter
 
 CODEC_OVERHEAD = 256  # bytes the tenant codec adds to a payload, at most: its metadata, the nonce and the tag
 PAYLOAD_BYTES = 1_835_008  # 1.75 MiB, encoded: a margin under Temporal's 2 MiB (2,097,152) payload limit
+SNAPSHOT_BYTES = 1_572_864  # 1.5 MiB, encoded: a continued run's input (spec §5.3's SNAPSHOT_MAX)
 PAYLOAD_TOO_LARGE = "payload_too_large"
+SNAPSHOT_TOO_LARGE = "snapshot_too_large"
+RUN_INPUT_TOO_LARGE = "The run's input is too large to start (over 1.75 MiB)."
+STEP_INPUT_TOO_LARGE = "The step's input is too large to send (over 1.75 MiB)."
+SUBFLOW_INPUT_TOO_LARGE = "The sub-flow's input is too large to send (over 1.75 MiB)."
+HANDLER_INPUT_TOO_LARGE = "The failure handler's input is too large to send (over 1.75 MiB)."
+BATCH_ITEM_TOO_LARGE = "An item of this loop, with what its batch reads, is too large to send (over 1.75 MiB)."
+RUN_SNAPSHOT_TOO_LARGE = "The run's state is too large to carry on (over 1.5 MiB)."
+BATCH_SNAPSHOT_TOO_LARGE = "A batch of this loop has too much state to carry on (over 1.5 MiB)."
 STEP_OUTPUT_TOO_LARGE = "The step's output is too large to record (over 1.75 MiB)."
 VERSION_TOO_LARGE = "The version is too large to load (over 1.75 MiB)."
 OUTPUTS_TOO_LARGE = "The run's outputs are too large to return (over 1.75 MiB)."
@@ -27,5 +36,15 @@ def encoded_bytes(value: Any, converter: PayloadConverter) -> int:
     return len(converter.to_payloads([value])[0].data) + CODEC_OVERHEAD
 
 
+def payload_bytes() -> int:
+    """PAYLOAD_BYTES, read when it's called."""
+    return PAYLOAD_BYTES
+
+
 def fits(value: Any, converter: PayloadConverter) -> bool:
     return encoded_bytes(value, converter) <= PAYLOAD_BYTES
+
+
+def snapshot_fits(value: Any, converter: PayloadConverter) -> bool:
+    """A continued run's input, snapshot and all, within SNAPSHOT_BYTES."""
+    return encoded_bytes(value, converter) <= SNAPSHOT_BYTES
diff --git a/backend/src/dewpoint/engine/runtime/workflow.py b/backend/src/dewpoint/engine/runtime/workflow.py
index 90fdb3f..6c7a8af 100644
--- a/backend/src/dewpoint/engine/runtime/workflow.py
+++ b/backend/src/dewpoint/engine/runtime/workflow.py
@@ -61,7 +61,17 @@ with workflow.unsafe.imports_passed_through():
         RunEnd,
         Scheduler,
     )
-    from dewpoint.engine.runtime.size import BATCH_RESULTS_TOO_LARGE, OUTPUTS_TOO_LARGE, PAYLOAD_TOO_LARGE, fits
+    from dewpoint.engine.runtime.size import (
+        BATCH_RESULTS_TOO_LARGE,
+        BATCH_SNAPSHOT_TOO_LARGE,
+        HANDLER_INPUT_TOO_LARGE,
+        OUTPUTS_TOO_LARGE,
+        PAYLOAD_TOO_LARGE,
+        RUN_SNAPSHOT_TOO_LARGE,
+        SNAPSHOT_TOO_LARGE,
+        fits,
+        snapshot_fits,
+    )
 
 
 HANDLED = ("failed", DEADLINE_EXCEEDED)  # the ends that run a failure handler (a cancel is no failure)
@@ -166,7 +176,11 @@ class RunGraph(Execution):
                 self._fresh(program)
             if await self._drive() == CONTINUE:
                 await self._flush()
-                workflow.continue_as_new(replace(start, snapshot=self._snapshot(), iterations=self.sched.iterations))
+                continued = replace(start, snapshot=self._snapshot(), iterations=self.sched.iterations)
+                if snapshot_fits(continued, workflow.payload_converter()):
+                    workflow.continue_as_new(continued)
+                # engine 2b spec §5.3: too large to carry on, the run ends here, cleanly (2b-1b bounds the state)
+                self.sched.end(RunEnd("failed", Failure(SNAPSHOT_TOO_LARGE, RUN_SNAPSHOT_TOO_LARGE)))
             end = self.sched.ended or RunEnd("failed", Failure("error", "The run ended without a result."))
             if end.status == "succeeded":
                 end, outputs = await self._outputs_by(end)
@@ -336,6 +350,12 @@ class RunGraph(Execution):
             checkpoint_events=self.checkpoint_events,
             drain_events=self.drain_events,
         )
+        if not fits(run, workflow.payload_converter()):  # engine 2b spec §5.2: never sent; its row says why
+            self.sched.budget.settle_child(child, 0)
+            failure = Failure(PAYLOAD_TOO_LARGE, HANDLER_INPUT_TOO_LARGE)
+            await self._lost_end(run, workflow.now().isoformat(), failure)
+            await self._send_signals()
+            return
         handler = asyncio.create_task(self._handler(run, child))
         while not handler.done():  # it draws its iterations from this run: answer as it asks
             wake = asyncio.create_task(workflow.wait_condition(lambda: bool(self._mail or self._answers)))
@@ -436,7 +456,12 @@ class LoopBatch(Execution):
                 )
             if await self._drive() == CONTINUE:
                 await self._flush()
-                workflow.continue_as_new(replace(start, snapshot=self._snapshot(), iterations=self.sched.iterations))
+                continued = replace(start, snapshot=self._snapshot(), iterations=self.sched.iterations)
+                if snapshot_fits(continued, workflow.payload_converter()):
+                    workflow.continue_as_new(continued)
+                # engine 2b spec §5.3: too large to carry on, the batch ends here and its loop fails
+                stopped = Failure(SNAPSHOT_TOO_LARGE, BATCH_SNAPSHOT_TOO_LARGE).to_json()
+                return BatchResult([], [], stopped, iterations=self.sched.iterations, secrets=list(self._secrets))
         except asyncio.CancelledError:
             self.sched.end(RunEnd("cancelled", CANCELLED))
             await self._project_end(None)
````

- [ ] **Step 4: Run the tests again**

Run: `cd backend && uv run pytest -q -p no:cacheprovider tests/apps/test_runs.py tests/apps/worker/test_run_graph_sizes.py tests/engine/runtime/test_scheduler_batches.py`

Expected (the replay):

````text
44 passed in 10.79s
````

- [ ] **Step 5: The whole suite, lint, types and layers**

Run: `cd backend && uv run pytest -q -p no:cacheprovider`, then `uv run ruff check --no-cache src tests migrations`, `uv run ruff format --no-cache --check src tests migrations`, `uv run mypy src` and `uv run lint-imports`.

Expected: 1,196 passed, 8 skipped; ruff and its formatter clean; mypy: no issues; import-linter: 10 contracts kept.

- [ ] **Step 6: Commit**

```bash
git add -A backend deploy docs && git commit -m "feat(engine): commands checked before they're sent (2b-1a)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 11: A workflow task's byte budget covers every command

**Spec:** §5.2.

**Files:**
- Modify: `backend/src/dewpoint/engine/__init__.py`
- Modify: `backend/src/dewpoint/engine/cel/route.py`
- Modify: `backend/src/dewpoint/engine/runtime/execution.py`
- Modify: `backend/src/dewpoint/engine/runtime/workflow.py`
- Modify: `backend/tests/apps/worker/test_real_server.py`
- Modify: `backend/tests/apps/worker/test_run_graph_sizes.py`

**Interfaces:**
- Consumes: Task 9's `encoded_bytes`; #15's `YieldBudget`, `_yield_point`.
- Produces: `Execution._task_budget()`, `async Execution._send(value)`, `async Execution._returned(result)`, and
  `Execution._charge_sent(value)`.

#15's per-task send budget (`YIELD_SEND_BYTES`, 3 MiB) now counts every payload a workflow task sends.
`Execution._send(value)` waits for the next task once this one has sent its bytes, then counts them. It covers:
- a step's input, a projection, and a sub-flow's, a batch's and a failure handler's start;
- a continued run's input;
- the execution's result, through `_returned`.

A local activity's result, whose marker goes out with the task's completion, is charged when it lands
(`_charge_sent`). Each payload is at most 1.75 MiB, so a task's completion stays under Temporal's 4 MiB gRPC message
limit. A cancel that arrives before a send leaves nothing started: a step's row says `cancelled`, and a child counts
nothing. `cel.evaluate` requests keep #15's own accounting.

- [ ] **Step 1: Write the tests**

````diff
diff --git a/backend/tests/apps/worker/test_real_server.py b/backend/tests/apps/worker/test_real_server.py
index 8815358..f427ab3 100644
--- a/backend/tests/apps/worker/test_real_server.py
+++ b/backend/tests/apps/worker/test_real_server.py
@@ -219,6 +219,32 @@ async def test_a_binding_set_over_the_request_limit_fails_its_step(dev_env: Work
     assert await task_failures(handle) == []
 
 
+async def test_large_step_and_sub_flow_inputs_are_paced_under_temporals_message_limit(
+    dev_env: WorkflowEnvironment,
+) -> None:
+    """Engine 2b spec §5.2's per-task invariant at the real limits: three step inputs and two sub-flow inputs of about
+    1.6 MiB each become ready together. Sent in one workflow task, they'd pass Temporal's 4 MiB gRPC message limit,
+    and Temporal would terminate the run (test_temporal_contract.py); they go out in separate tasks."""
+    client, store = dev_env.client, MemoryStore()
+    big = 1_600_000
+    sub = G()
+    sub.settings = {"input_schema": strings("v"), "outputs": {"n": cel("size(trigger.v)")}}
+    sub.node("e", "testkit.echo@1", {"value": 1})
+    sub_id = str(store.publish(sub))
+    g = graph(**{k: ref(f"steps.{k}.output.n") for k in ("r", "s")})
+    g.node("b", "testkit.blob@1", {"size": big})
+    for k in ("x", "y", "z"):
+        g.node(k, "testkit.echo@1", {"value": ref("steps.b.output.value")}).edge("b", k)
+    for k in ("r", "s"):
+        g.node(k, "flow.run_workflow@1", {"workflow_id": sub_id, "input": {"v": ref("steps.b.output.value")}})
+        g.edge("b", k)
+    async with serving(client, store):
+        handle = await start(client, store, g, {})
+        result = await asyncio.wait_for(handle.result(), 120)
+    assert (result.status, result.outputs) == ("succeeded", {"r": big, "s": big})
+    assert await task_failures(handle) == []
+
+
 async def test_three_large_requests_are_paced_under_temporals_message_limit(dev_env: WorkflowEnvironment) -> None:
     """Three steps ready together each send about 1.6 MiB. In one workflow task that passes Temporal's 4 MiB gRPC
     message limit, and Temporal terminates the run; paced, they go out in separate tasks (review focus 4)."""
diff --git a/backend/tests/apps/worker/test_run_graph_sizes.py b/backend/tests/apps/worker/test_run_graph_sizes.py
index f324f49..98b0866 100644
--- a/backend/tests/apps/worker/test_run_graph_sizes.py
+++ b/backend/tests/apps/worker/test_run_graph_sizes.py
@@ -12,6 +12,7 @@ from temporalio.api.enums.v1 import EventType
 from temporalio.client import WorkflowHandle
 from temporalio.testing import WorkflowEnvironment
 
+from dewpoint.engine.cel import route
 from dewpoint.engine.runtime import size
 from dewpoint.engine.runtime.activities import RunResult
 from dewpoint.engine.runtime.size import (
@@ -22,7 +23,7 @@ from dewpoint.engine.runtime.size import (
     STEP_INPUT_TOO_LARGE,
 )
 from tests.apps.worker.harness import MemoryStore, run_id_of, start, workers
-from tests.support.graphs import G, ref
+from tests.support.graphs import G, cel, ref
 
 LIMIT = 50_000
 ITEMS = {"type": "object", "properties": {"items": {"type": "array"}}, "required": ["items"]}
@@ -236,3 +237,33 @@ async def test_a_failure_handler_whose_input_is_too_large_never_starts_and_says_
     assert (store.runs[child].status, store.runs[child].error_code) == ("failed", PAYLOAD_TOO_LARGE)
     assert store.runs[run_id_of(handle)].status == "failed"
     assert await children_started(handle) == 0  # it was never sent
+
+
+async def scheduled_in(handle: WorkflowHandle[Any, Any], name: str) -> list[int]:
+    """The workflow task that scheduled each `name` activity, in order."""
+    return [
+        e.activity_task_scheduled_event_attributes.workflow_task_completed_event_id
+        for e in (await handle.fetch_history()).events
+        if e.event_type == EventType.EVENT_TYPE_ACTIVITY_TASK_SCHEDULED
+        and e.activity_task_scheduled_event_attributes.activity_type.name == name
+    ]
+
+
+@pytest.mark.parametrize("cache", [1000, 0], ids=["cached", "replaying every task"])
+async def test_a_workflow_task_sends_at_most_its_bytes_of_every_command(
+    env: WorkflowEnvironment, monkeypatch: pytest.MonkeyPatch, cache: int
+) -> None:
+    """Engine 2b spec §5.2's per-task invariant, with the budget lowered: three step inputs of about 30 KB, ready
+    together, pass a 70 KB budget, so the third waits for the next workflow task; replay decides the same."""
+    monkeypatch.setattr(route, "YIELD_SEND_BYTES", 70_000)
+    store = MemoryStore()
+    g = graph(**{k: cel(f"size(steps.{k}.output.value)") for k in "xyz"})
+    g.node("b", BLOB, {"size": 30_000})
+    for k in "xyz":
+        g.node(k, ECHO, {"value": ref("steps.b.output.value")}).edge("b", k)
+    async with workers(env.client, store, cache=cache):
+        handle = await start(env.client, store, g, {})
+        result = await asyncio.wait_for(handle.result(), 60)
+    assert (result.status, result.outputs) == ("succeeded", {k: 30_000 for k in "xyz"})
+    tasks = await scheduled_in(handle, "testkit.echo.v1")
+    assert len(tasks) == 3 and len(set(tasks)) == 2
````

- [ ] **Step 2: Run them, and watch them fail**

Run: `cd backend && uv run pytest -q -p no:cacheprovider tests/apps/worker/test_real_server.py tests/apps/worker/test_run_graph_sizes.py`

Expected: FAIL. The three step inputs go out in the same workflow task, and on the dev server the run doesn't survive. The replay showed:

````text
E                       temporalio.client._exceptions.WorkflowFailureError: Workflow execution failed
E       assert (3 == 3 and 1 == 2)
E        +  where 3 = len([11, 11, 11])
E        +  and   1 = len({11})
E        +    where {11} = set([11, 11, 11])
FAILED tests/apps/worker/test_real_server.py::test_large_step_and_sub_flow_inputs_are_paced_under_temporals_message_limit
FAILED tests/apps/worker/test_run_graph_sizes.py::test_a_workflow_task_sends_at_most_its_bytes_of_every_command[cached]
FAILED tests/apps/worker/test_run_graph_sizes.py::test_a_workflow_task_sends_at_most_its_bytes_of_every_command[replaying every task]
3 failed, 20 passed in 30.58s
````

- [ ] **Step 3: Implement**

````diff
diff --git a/backend/src/dewpoint/engine/__init__.py b/backend/src/dewpoint/engine/__init__.py
index 955ebe6..4bcd777 100644
--- a/backend/src/dewpoint/engine/__init__.py
+++ b/backend/src/dewpoint/engine/__init__.py
@@ -6,5 +6,5 @@
 # continue-as-new. 3: 2a-3c's local CEL. 4: issue #15's cel.evaluate requests, cut by their bytes, refused when one
 # binding set can't fit, and paced per workflow task. 5: 2b-1a's workflow ids, built from the tenant and the run
 # (sub-flows' and failure handlers' too), and what a run sends Temporal, measured before it's sent: a loop's batch cut
-# by bytes, a continued run's state within 1.5 MiB.
+# by bytes, a continued run's state within 1.5 MiB, every command paced per workflow task.
 ENGINE_ABI = 5
diff --git a/backend/src/dewpoint/engine/cel/route.py b/backend/src/dewpoint/engine/cel/route.py
index 663c5a1..76a9e43 100644
--- a/backend/src/dewpoint/engine/cel/route.py
+++ b/backend/src/dewpoint/engine/cel/route.py
@@ -18,8 +18,8 @@ YIELD_WORK = (
 YIELD_EVALUATIONS = 130
 YIELD_NODES = 65_000  # the values the evaluations bind: converting them costs CPU their stored bounds don't count
 STARTUP_SHARE = 10  # an execution's first workflow task gets this fraction of each threshold: it also starts it
-YIELD_SEND_BYTES = 3 * 1024 * 1024  # cel.evaluate request bytes one workflow task sends: under Temporal's 4 MiB gRPC
-# message limit, which terminates the workflow when a task's completion passes it (#15)
+YIELD_SEND_BYTES = 3 * 1024 * 1024  # the payload bytes one workflow task sends, every command's (#15, engine 2b spec
+# §5.2): under Temporal's 4 MiB gRPC message limit, which terminates the workflow when a task's completion passes it
 
 
 def route(
@@ -34,8 +34,7 @@ def route(
 
 @dataclass
 class YieldBudget:
-    """One workflow task's local evaluations, the values they bound (`Measure.nodes`), and the cel.evaluate requests it
-    sends."""
+    """One workflow task's local evaluations, the values they bound (`Measure.nodes`), and the payloads it sends."""
 
     iterations: int = 0
     bytes: int = 0
@@ -47,7 +46,7 @@ class YieldBudget:
 
     def must_yield(self, record: ExpressionRecord | None = None, *, send: int = 0) -> bool:
         """True when the interpreter must await a 1 ms durable timer before binding a view (`record` None), before
-        evaluating `record` locally, or before sending a request of `send` bytes. The first thing a workflow task does
+        evaluating `record` locally, or before sending a payload of `send` bytes. The first thing a workflow task does
         always runs; a view is always bound first, so an evaluation whose bounds pass an execution's first task's share
         waits for the next task. Sending has its own limit, Temporal's, with no startup share."""
         if send:
@@ -63,7 +62,7 @@ class YieldBudget:
         )
 
     def charge(self, record: ExpressionRecord | None = None, *, nodes: int = 0, sent: int = 0) -> None:
-        """A view bound (`nodes`: the values it bound), `record` evaluated locally, or a request of `sent` bytes."""
+        """A view bound (`nodes`: the values it bound), `record` evaluated locally, or a payload of `sent` bytes."""
         self.nodes += nodes
         self.sent += sent
         if record is not None:
diff --git a/backend/src/dewpoint/engine/runtime/execution.py b/backend/src/dewpoint/engine/runtime/execution.py
index 7102780..69ebc02 100644
--- a/backend/src/dewpoint/engine/runtime/execution.py
+++ b/backend/src/dewpoint/engine/runtime/execution.py
@@ -605,9 +605,11 @@ class Execution:
     async def _project(
         self, rows: list[StepRow], summary: RunSummary | None = None, start: RunStart | None = None
     ) -> None:
+        data = ProjectInput(self.tenant_id, rows, summary, start)
+        await self._send(data)
         await workflow.execute_activity(
             PROJECT,
-            ProjectInput(self.tenant_id, rows, summary, start),
+            data,
             start_to_close_timeout=timedelta(seconds=30),
             retry_policy=RetryPolicy(maximum_interval=timedelta(seconds=30)),
         )
@@ -745,24 +747,45 @@ class Execution:
             start = end
         return out
 
+    def _task_budget(self) -> YieldBudget:
+        """The current workflow task's budget: it starts afresh when the history length changes, which happens only
+        between tasks, in a replay too. The execution's first task gets a tenth of it: that task also starts it."""
+        length = workflow.info().get_current_history_length()
+        if length != self._yield_task:
+            self._yield_task = length
+            self._yield.reset(startup=length == self._startup_task)
+        return self._yield
+
     async def _yield_point(self, record: ExpressionRecord | None, *, send: int = 0) -> None:
         """Before binding a view (`record` None) or evaluating `record` locally: when the current workflow task's budget
-        is spent, await a 1 ms durable timer, which ends the task (spec §5.6). The budget belongs to one workflow task:
-        it starts afresh when the history length changes, which happens only between tasks, in a replay too. The
-        execution's first task gets a tenth of it: that task also starts the execution. Concurrent units share the
-        budget and one timer, and each checks again once it fires. Before sending a cel.evaluate request (`send` its
-        bytes), the same wait keeps a task's requests under Temporal's gRPC message limit (#15)."""
+        is spent, await a 1 ms durable timer, which ends the task (spec §5.6). Concurrent units share the budget and
+        one timer, and each checks again once it fires. Before sending a payload (`send` its bytes), the same wait
+        keeps a task's commands under Temporal's gRPC message limit (#15, engine 2b spec §5.2)."""
         while True:
-            length = workflow.info().get_current_history_length()
-            if length != self._yield_task:
-                self._yield_task = length
-                self._yield.reset(startup=length == self._startup_task)
-            if not self._yield.must_yield(record, send=send):
+            if not self._task_budget().must_yield(record, send=send):
                 return
             if self._yield_timer is None or self._yield_timer.done():
                 self._yield_timer = asyncio.create_task(asyncio.sleep(0.001))
             await asyncio.shield(self._yield_timer)
 
+    async def _send(self, value: Any) -> None:
+        """Before a command carries `value`'s payload: wait for the next workflow task once this one has sent its
+        bytes (YIELD_SEND_BYTES), then count them. Every payload the engine sends goes through here — a step's input,
+        a request, a projection, a child's start, a continued run's input, the result — and each is at most
+        PAYLOAD_BYTES, so a task's completion stays under Temporal's gRPC message limit (engine 2b spec §5.2)."""
+        n = encoded_bytes(value, workflow.payload_converter())
+        await self._yield_point(None, send=n)
+        self._yield.charge(sent=n)
+
+    async def _returned[R](self, result: R) -> R:
+        """The execution's result, paced as a command is: it goes out with its workflow task's completion."""
+        await self._send(result)
+        return result
+
+    def _charge_sent(self, value: Any) -> None:
+        """A payload this workflow task records without sending it as a command: a local activity's result."""
+        self._task_budget().charge(sent=encoded_bytes(value, workflow.payload_converter()))
+
     # --- steps -----------------------------------------------------------------------------------------------------
 
     async def _step(self, inst: Instance) -> _Effect:
@@ -883,6 +906,11 @@ class Execution:
         used: int | None = None  # until it reports, all it was granted counts: it may have run
         started = workflow.now().isoformat()
         try:
+            try:
+                await self._send(run)
+            except asyncio.CancelledError:  # cancelled before it was sent: it never ran
+                used = 0
+                raise
             try:
                 handle = await workflow.start_child_workflow(
                     "RunGraph", run, result_type=RunResult, **child_options(child)
@@ -964,6 +992,11 @@ class Execution:
         batch = self._batch_input(b, grant)
         used: int | None = None  # until it reports, all it was granted counts: it may have run
         try:
+            try:
+                await self._send(batch)
+            except asyncio.CancelledError:  # cancelled before it was sent: it never ran
+                used = 0
+                raise
             try:
                 handle = await workflow.start_child_workflow(
                     "LoopBatch", batch, result_type=BatchResult, **child_options(child)
@@ -1070,6 +1103,11 @@ class Execution:
                     )
                 )
                 return _Effect(failure=failure, cel_mode=cel_mode)
+            try:
+                await self._send(sent)
+            except asyncio.CancelledError:  # the run or the scope ended before it was sent: nothing ran
+                self._queue(replace(row, status="cancelled", ended_at=workflow.now().isoformat()))
+                raise
             try:
                 result = await workflow.execute_activity(
                     step_activity(step.ref),
diff --git a/backend/src/dewpoint/engine/runtime/workflow.py b/backend/src/dewpoint/engine/runtime/workflow.py
index 6c7a8af..6135f7e 100644
--- a/backend/src/dewpoint/engine/runtime/workflow.py
+++ b/backend/src/dewpoint/engine/runtime/workflow.py
@@ -155,6 +155,7 @@ class RunGraph(Execution):
                 return await self._cancelled_early(start.iterations)
             workflow.logger.error("run_version_unusable", exc_info=True)
             return await self._end_early(RunEnd("failed", Failure(VERSION_UNUSABLE, _unloadable(e))), start.iterations)
+        self._charge_sent(data)  # its marker goes out with this workflow task's commands (engine 2b spec §5.2)
         try:
             program = compile_program(
                 data.graph,
@@ -178,6 +179,7 @@ class RunGraph(Execution):
                 await self._flush()
                 continued = replace(start, snapshot=self._snapshot(), iterations=self.sched.iterations)
                 if snapshot_fits(continued, workflow.payload_converter()):
+                    await self._send(continued)
                     workflow.continue_as_new(continued)
                 # engine 2b spec §5.3: too large to carry on, the run ends here, cleanly (2b-1b bounds the state)
                 self.sched.end(RunEnd("failed", Failure(SNAPSHOT_TOO_LARGE, RUN_SNAPSHOT_TOO_LARGE)))
@@ -264,12 +266,14 @@ class RunGraph(Execution):
             iterations=self.sched.iterations,
         )
         await self._project_end(summary)
-        return RunResult(
-            status=end.status,
-            outputs=outputs,
-            error=error,
-            iterations=self.sched.iterations,
-            secrets=list(self._secrets),
+        return await self._returned(
+            RunResult(
+                status=end.status,
+                outputs=outputs,
+                error=error,
+                iterations=self.sched.iterations,
+                secrets=list(self._secrets),
+            )
         )
 
     def _end_error(self, end: RunEnd) -> dict[str, Any] | None:
@@ -292,7 +296,7 @@ class RunGraph(Execution):
             iterations=iterations,
         )
         await self._shielded([], summary)
-        return RunResult(status=end.status, error=error, iterations=iterations)
+        return await self._returned(RunResult(status=end.status, error=error, iterations=iterations))
 
     async def _cancelled_early(self, iterations: int) -> RunResult:
         """Cancelled before the run restored its snapshot or started: it reports what it used before continuing as new
@@ -373,6 +377,10 @@ class RunGraph(Execution):
         """The failure handler's run: the iterations it used, or None when it ended without saying (its end is then
         written here, as a sub-flow's is)."""
         started = workflow.now().isoformat()
+        try:
+            await self._send(run)
+        except asyncio.CancelledError:  # cancelled before it was sent: it never ran
+            return 0
         try:
             result: RunResult = await workflow.execute_child_workflow(
                 "RunGraph", run, result_type=RunResult, **child_options(child)
@@ -435,6 +443,7 @@ class LoopBatch(Execution):
             workflow.logger.error("batch_version_unusable", exc_info=True)
             message = f"This build can't run the version ({type(e).__name__}); the worker's log has the details."
             raise ApplicationError(message, type=VERSION_UNUSABLE, non_retryable=True) from None
+        self._charge_sent(data)  # its marker goes out with this workflow task's commands (engine 2b spec §5.2)
         try:
             if snapshot is not None:
                 self._restore(program, snapshot)
@@ -458,21 +467,24 @@ class LoopBatch(Execution):
                 await self._flush()
                 continued = replace(start, snapshot=self._snapshot(), iterations=self.sched.iterations)
                 if snapshot_fits(continued, workflow.payload_converter()):
+                    await self._send(continued)
                     workflow.continue_as_new(continued)
                 # engine 2b spec §5.3: too large to carry on, the batch ends here and its loop fails
                 stopped = Failure(SNAPSHOT_TOO_LARGE, BATCH_SNAPSHOT_TOO_LARGE).to_json()
-                return BatchResult([], [], stopped, iterations=self.sched.iterations, secrets=list(self._secrets))
+                return await self._returned(
+                    BatchResult([], [], stopped, iterations=self.sched.iterations, secrets=list(self._secrets))
+                )
         except asyncio.CancelledError:
             self.sched.end(RunEnd("cancelled", CANCELLED))
             await self._project_end(None)
-            return self._result(RunEnd("cancelled", CANCELLED))
+            return await self._returned(self._result(RunEnd("cancelled", CANCELLED)))
         except Exception as e:
             workflow.logger.error("batch_internal_error", exc_info=True)
             await self._project_end(None)  # its steps' rows land first, as a run's do
             message = f"The batch failed ({type(e).__name__}); the worker's log has the details."
             raise ApplicationError(message, type=INTERNAL_ERROR, non_retryable=True) from None
         await self._project_end(None)
-        return self._result(self.sched.ended)
+        return await self._returned(self._result(self.sched.ended))
 
     def _result(self, end: RunEnd | None) -> BatchResult:
         outcome = self.sched.outcome
````

- [ ] **Step 4: Run the tests again**

Run: `cd backend && uv run pytest -q -p no:cacheprovider tests/apps/worker/test_real_server.py tests/apps/worker/test_run_graph_sizes.py`

Expected (the replay):

````text
23 passed in 33.80s
````

- [ ] **Step 5: The whole suite, lint, types and layers**

Run: `cd backend && uv run pytest -q -p no:cacheprovider`, then `uv run ruff check --no-cache src tests migrations`, `uv run ruff format --no-cache --check src tests migrations`, `uv run mypy src` and `uv run lint-imports`.

Expected: 1,199 passed, 8 skipped; ruff and its formatter clean; mypy: no issues; import-linter: 10 contracts kept.

- [ ] **Step 6: Commit**

```bash
git add -A backend deploy docs && git commit -m "feat(engine): a workflow task's byte budget covers every command (2b-1a)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 12: Carried sensitive values bounded, every final result checked

**Spec:** §5.2.

**Files:**
- Modify: `backend/src/dewpoint/engine/runtime/execution.py`
- Modify: `backend/src/dewpoint/engine/runtime/size.py`
- Modify: `backend/src/dewpoint/engine/runtime/workflow.py`
- Modify: `backend/tests/apps/worker/test_run_graph_sizes.py`
- Modify: `backend/tests/engine/runtime/test_size.py`
- Modify: `backend/tests/support/plugins/testkit.py`

**Interfaces:**
- Consumes: Task 9's `size` module and `fits`; Task 10's handler guard; Task 11's `_returned`.
- Produces:
  - in `size`: `SECRETS_BYTES = 262_144`, `SECRETS_TOO_LARGE`, `RESULT_TOO_LARGE`, `secret_bytes(value) -> int`,
    `secrets_bytes(values) -> int`, `secrets_limit() -> int`;
  - `Execution._carry(secrets)`, `Execution._learned(values) -> bool`, and `Execution._learn(...) -> bool` (it returns
    whether the values were learned);
  - `RunGraph._fresh(program) -> bool`, `RunGraph._final(end, outputs, iterations, secrets) -> (RunEnd, RunResult)`,
    `LoopBatch._checked(result) -> BatchResult`;
  - `tests.support.plugins.testkit.SecretBlob` (`testkit.secret_blob@1`, `{seed, size}`).

A run carries the sensitive values it learned in its result, its children's starts and its snapshot,
so that they're masked there too. Until 2b-1b's claims they travel inline, so they're bounded now:
- `SECRETS_BYTES` (256 KiB) of JSON, measured as the list grows (`Execution._learned`). Measuring the whole list on
  every value learned would cost CPU in the workflow task, as #18's binding does.
- A value that would pass the bound fails what would add it, with `payload_too_large` and a fixed message:
  - a step: before it's sent if its config holds it, or after it ran if its output does (once, keeping its
    outcome);
  - a sub-flow's or a batch's step, when its result would bring the parent past the bound;
  - the run, before any step, when its trigger or a literal holds it.
- Whatever held the value is never used afterwards, so nothing unmasked goes on. What's carried is never dropped: a
  parent always masks everything its children tell it.

With that bound, a result with no outputs or collected items carries only an error (a stored message, at most 500
characters) and the bounded values, and a test proves it fits at the real limits. Every final result is checked
before it's recorded, a failure's, a cancel's, `snapshot_too_large`'s and a stopped batch's included
(`RunGraph._final`, `LoopBatch._checked`). Past the limit anyway is a bug: the run ends `internal_error`, or the batch
fails its loop, with no outputs and nothing left to mask, and no workflow task retries.

The test node `testkit.secret_blob@1` teaches a sensitive value of a chosen size. Task 10's failure-handler test now
sets its limit just above the run's own failed result, since the bound keeps a handler's input far under the real
limit.

- [ ] **Step 1: Write the tests**

````diff
diff --git a/backend/tests/apps/worker/test_run_graph_sizes.py b/backend/tests/apps/worker/test_run_graph_sizes.py
index 98b0866..8801e69 100644
--- a/backend/tests/apps/worker/test_run_graph_sizes.py
+++ b/backend/tests/apps/worker/test_run_graph_sizes.py
@@ -10,6 +10,7 @@ from typing import Any
 import pytest
 from temporalio.api.enums.v1 import EventType
 from temporalio.client import WorkflowHandle
+from temporalio.converter import DataConverter
 from temporalio.testing import WorkflowEnvironment
 
 from dewpoint.engine.cel import route
@@ -18,7 +19,9 @@ from dewpoint.engine.runtime.activities import RunResult
 from dewpoint.engine.runtime.size import (
     OUTPUTS_TOO_LARGE,
     PAYLOAD_TOO_LARGE,
+    RESULT_TOO_LARGE,
     RUN_SNAPSHOT_TOO_LARGE,
+    SECRETS_TOO_LARGE,
     SNAPSHOT_TOO_LARGE,
     STEP_INPUT_TOO_LARGE,
 )
@@ -216,9 +219,17 @@ async def test_a_batch_whose_snapshot_is_too_large_fails_its_loop(
     assert (result.status, result.outputs) == ("succeeded", {"code": SNAPSHOT_TOO_LARGE})
 
 
-async def test_a_failure_handler_whose_input_is_too_large_never_starts_and_says_why(env: WorkflowEnvironment) -> None:
-    """Its input carries what the run learned is sensitive, to mask it too: past the limit, the handler's row records
-    `payload_too_large`, and the run's own end stands."""
+async def test_a_failure_handler_whose_input_is_too_large_never_starts_and_says_why(
+    env: WorkflowEnvironment, monkeypatch: pytest.MonkeyPatch
+) -> None:
+    """Its input carries what the run learned is sensitive, to mask it too. The bound on those values keeps it far
+    under the limit, so the limit is set here just above the run's own failed result, which carries them too: the
+    handler's input passes it, its row records `payload_too_large`, and the run's end stands."""
+    key = "k" * LIMIT
+    failed = RunResult("failed", None, {"code": "workflow_failed", "message": "it went wrong", "attempt": 1}, 0, [key])
+    monkeypatch.setattr(
+        size, "PAYLOAD_BYTES", size.encoded_bytes(failed, DataConverter.default.payload_converter) + 100
+    )
     store = MemoryStore()
     g = graph()
     g.settings["input_schema"] = {
@@ -229,7 +240,7 @@ async def test_a_failure_handler_whose_input_is_too_large_never_starts_and_says_
     g.settings["failure_handler"] = str(store.publish(graph().node("h", ECHO, {"value": 1})))
     g.node("f", "flow.fail@1", {"message": "it went wrong"})
     async with workers(env.client, store):
-        handle = await start(env.client, store, g, {"key": "k" * LIMIT})
+        handle = await start(env.client, store, g, {"key": key})
         result = await asyncio.wait_for(handle.result(), 60)
     assert result.status == "failed" and result.error is not None and result.error["code"] == "workflow_failed"
     [(child, row)] = store.starts.items()
@@ -267,3 +278,91 @@ async def test_a_workflow_task_sends_at_most_its_bytes_of_every_command(
     assert (result.status, result.outputs) == ("succeeded", {k: 30_000 for k in "xyz"})
     tasks = await scheduled_in(handle, "testkit.echo.v1")
     assert len(tasks) == 3 and len(set(tasks)) == 2
+
+
+SECRET = "testkit.secret_blob@1"
+
+
+@pytest.fixture
+def few_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
+    """A run may carry 5,000 bytes of sensitive values: two 3,000-character ones don't fit together."""
+    monkeypatch.setattr(size, "SECRETS_BYTES", 5_000)
+
+
+@pytest.mark.usefixtures("few_secrets")
+async def test_a_sensitive_value_past_the_bound_fails_the_step_that_would_add_it(env: WorkflowEnvironment) -> None:
+    """What the run carries is never dropped: the step that would pass the bound fails once (its node ran, so its
+    outcome stands), and its output goes nowhere."""
+    store = MemoryStore()
+    g = graph(code=ref("steps.b.error.code", default="none"))
+    g.node("a", SECRET, {"seed": "a", "size": 3_000})
+    g.node("b", SECRET, {"seed": "b", "size": 3_000}, on_error="continue").edge("a", "b")
+    handle, result = await finished(env, store, g)
+    assert (result.status, result.outputs) == ("succeeded", {"code": PAYLOAD_TOO_LARGE})
+    assert result.secrets == ["a" + "s" * 2_999]
+    [row] = [r for r in store.steps(run_id_of(handle)) if r.node_key == "b"]
+    assert (row.status, row.error_code, row.error_message, row.outcome) == (
+        "failed",
+        PAYLOAD_TOO_LARGE,
+        SECRETS_TOO_LARGE,
+        "applied",
+    )
+    assert row.output_preview is None
+
+
+@pytest.mark.usefixtures("few_secrets")
+async def test_a_sub_flow_whose_sensitive_values_dont_fit_with_its_parents_fails_its_step(
+    env: WorkflowEnvironment,
+) -> None:
+    """The sub-flow starts before its parent learns anything, and learns a value that fits alone; meanwhile the parent
+    learns one too, and together they'd pass the bound. The parent fails the step, and never uses the sub-flow's
+    outputs, which it couldn't mask."""
+    store = MemoryStore()
+    sub = graph(n=ref("steps.s.output.token")).node("w", "testkit.slow@1", {"seconds": 1})
+    sub.node("s", SECRET, {"seed": "sub", "size": 3_000}).edge("w", "s")  # the parent's step ends first
+    g = graph(code=ref("steps.r.error.code", default="none"))
+    g.node("a", SECRET, {"seed": "a", "size": 3_000})
+    g.node("r", RUN, {"workflow_id": str(store.publish(sub)), "input": {}}, on_error="continue")
+    _, result = await finished(env, store, g)
+    assert (result.status, result.outputs) == ("succeeded", {"code": PAYLOAD_TOO_LARGE})
+    [(child, _)] = store.starts.items()
+    assert store.runs[child].status == "succeeded"  # the sub-run itself was fine
+
+
+@pytest.mark.usefixtures("few_secrets")
+async def test_a_trigger_whose_sensitive_values_dont_fit_fails_the_run_before_any_step(
+    env: WorkflowEnvironment,
+) -> None:
+    store = MemoryStore()
+    g = graph().node("e", ECHO, {"value": 1})
+    g.settings["input_schema"] = {
+        "type": "object",
+        "properties": {"key": {"type": "string", "x-sensitive": True}},
+        "required": ["key"],
+    }
+    async with workers(env.client, store):
+        handle = await start(env.client, store, g, {"key": "k" * 6_000})
+        result = await asyncio.wait_for(handle.result(), 60)
+    assert result.status == "failed" and result.error is not None
+    assert (result.error["code"], result.error["message"], result.secrets) == (PAYLOAD_TOO_LARGE, SECRETS_TOO_LARGE, [])
+    assert store.steps(run_id_of(handle)) == []
+
+
+async def test_a_result_past_the_limit_anyway_ends_the_run_as_a_bug(
+    env: WorkflowEnvironment, monkeypatch: pytest.MonkeyPatch
+) -> None:
+    """Every final result is checked, a failure's too. With the limits set inconsistently (a 6,000-byte payload
+    limit, and the default bound on sensitive values), a step's 5,500-character sensitive output fits in its result,
+    but not in the failed run's with its message: the run ends `internal_error`, with no outputs and nothing to mask,
+    rather than retry its workflow task."""
+    monkeypatch.setattr(size, "PAYLOAD_BYTES", 6_000)
+    store = MemoryStore()
+    g = graph().node("a", SECRET, {"seed": "a", "size": 5_500})
+    g.node("f", "flow.fail@1", {"message": "n" * 400}).edge("a", "f")
+    handle, result = await finished(env, store, g)
+    assert (result.status, result.outputs, result.secrets) == ("failed", None, [])
+    assert result.error is not None and (result.error["code"], result.error["message"]) == (
+        "internal_error",
+        RESULT_TOO_LARGE,
+    )
+    assert store.runs[run_id_of(handle)].error_code == "internal_error"
diff --git a/backend/tests/engine/runtime/test_size.py b/backend/tests/engine/runtime/test_size.py
index 937c579..fe67c66 100644
--- a/backend/tests/engine/runtime/test_size.py
+++ b/backend/tests/engine/runtime/test_size.py
@@ -2,9 +2,12 @@
 """Engine 2b spec §5.2: a payload is measured as the SDK's JSON converter writes it, plus a bound on what the codec
 adds (test_codec.py proves the bound), against a margin under Temporal's 2 MiB."""
 
+import json
+
 from temporalio.converter import DataConverter
 
 from dewpoint.engine.runtime import size
+from dewpoint.engine.runtime.activities import BatchResult, RunResult
 from dewpoint.engine.runtime.execution import CEL_REQUEST_BYTES
 
 TEMPORAL_PAYLOAD_LIMIT = 2 * 1024 * 1024
@@ -28,3 +31,36 @@ def test_fits_reads_the_limit_when_its_called(monkeypatch) -> None:
     assert size.fits("x" * 1_000, JSON)
     monkeypatch.setattr(size, "PAYLOAD_BYTES", 1_000)
     assert not size.fits("x" * 1_000, JSON)
+
+
+def secrets_at_the_bound() -> list[str]:
+    """Sensitive values whose JSON is SECRETS_BYTES exactly: 1,000-character strings, then one to fill up."""
+    values, used = [], 2  # the list's brackets
+    while used + 1_003 <= size.SECRETS_BYTES:
+        values.append(f"{len(values):06d}" + "s" * 994)
+        used += len(json.dumps(values[-1])) + (1 if len(values) > 1 else 0)
+    values.append("t" * (size.SECRETS_BYTES - used - 3))
+    assert size.secrets_bytes(values) == size.SECRETS_BYTES
+    return values
+
+
+def test_the_carried_sensitive_values_are_measured_as_the_converter_writes_them() -> None:
+    values = ["é" * 10, "plain-token", '"quoted"']
+    assert size.secrets_bytes(values) == len(JSON.to_payloads([values])[0].data)
+    assert size.secrets_bytes([]) == 2
+
+
+def test_every_final_result_fits_whatever_it_carries() -> None:
+    """Engine 2b spec §5.2: without outputs or collected items, a result carries an error (a stored message, at most
+    500 characters, each escaped to at most 6 bytes) and the sensitive values (at most SECRETS_BYTES): a failure, a
+    cancel, `snapshot_too_large`, a stopped batch. Each fits with room to spare."""
+    worst = {"code": "x" * 500, "message": "é" * 500, "attempt": 10}
+    secrets = secrets_at_the_bound()
+    results = [
+        RunResult("failed", None, worst, 100_000, secrets),
+        BatchResult([], [], stopped=worst, iterations=100_000, secrets=secrets),
+        BatchResult(
+            [], [], end={"status": "failed", "failure": worst, "stopped": False}, iterations=1, secrets=secrets
+        ),
+    ]
+    assert all(size.encoded_bytes(r, JSON) <= size.PAYLOAD_BYTES // 4 for r in results)
diff --git a/backend/tests/support/plugins/testkit.py b/backend/tests/support/plugins/testkit.py
index 31e40fb..84df468 100644
--- a/backend/tests/support/plugins/testkit.py
+++ b/backend/tests/support/plugins/testkit.py
@@ -190,6 +190,34 @@ class Blob(Node):
         return EchoOutput(value="x" * config.size)
 
 
+class SecretBlobConfig(BaseModel):
+    seed: str
+    size: int = Field(ge=0, le=4 * 1024 * 1024)
+
+
+class SecretBlobOutput(BaseModel):
+    token: str = sensitive()
+
+
+class SecretBlob(Node):
+    """A sensitive output of `size` characters, starting with `seed` so each step's is its own: the run learns it,
+    and carries it to be masked wherever it reappears (engine 2b spec §5.2)."""
+
+    type = "testkit.secret_blob"
+    version = 1
+    title = "Secret blob"
+    Config = SecretBlobConfig
+    Output = SecretBlobOutput
+
+    async def run(self, ctx: StepContext, config: SecretBlobConfig) -> SecretBlobOutput:
+        return SecretBlobOutput(token=(config.seed + "s" * config.size)[: config.size])
+
+    async def simulate(self, ctx: StepContext, config: SecretBlobConfig) -> SecretBlobOutput:
+        return await self.run(ctx, config)
+
+
 TESTKIT = Plugin(
-    name="testkit", version="0.0.0", nodes=(Echo, FailN, Slow, Sensitive, AmbiguousSend, SlowSend, Reconcile, Blob)
+    name="testkit",
+    version="0.0.0",
+    nodes=(Echo, FailN, Slow, Sensitive, AmbiguousSend, SlowSend, Reconcile, Blob, SecretBlob),
 )
````

- [ ] **Step 2: Run them, and watch them fail**

Run: `cd backend && uv run pytest -q -p no:cacheprovider tests/apps/worker/test_run_graph_sizes.py tests/engine/runtime/test_size.py`

Expected: FAIL. `size` has none of the new names yet. With only those names added, the four workflow tests fail on behavior instead: nothing refuses the values, and the oversized result is returned. The replay showed:

````text
E   ImportError: cannot import name 'RESULT_TOO_LARGE' from 'dewpoint.engine.runtime.size'
ERROR tests/apps/worker/test_run_graph_sizes.py
!!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
1 error in 0.45s
````

- [ ] **Step 3: Write the documentation**

````diff
diff --git a/backend/src/dewpoint/engine/runtime/execution.py b/backend/src/dewpoint/engine/runtime/execution.py
index 69ebc02..1b27079 100644
--- a/backend/src/dewpoint/engine/runtime/execution.py
+++ b/backend/src/dewpoint/engine/runtime/execution.py
@@ -13,7 +13,7 @@ isn't outstanding: its wake time goes into the snapshot, and the continued run r
 
 import asyncio
 import uuid
-from collections.abc import Mapping, Sequence
+from collections.abc import Iterable, Mapping, Sequence
 from dataclasses import asdict, dataclass, replace
 from datetime import UTC, datetime, timedelta
 from typing import Any
@@ -87,11 +87,14 @@ with workflow.unsafe.imports_passed_through():
     from dewpoint.engine.runtime.size import (
         BATCH_ITEM_TOO_LARGE,
         PAYLOAD_TOO_LARGE,
+        SECRETS_TOO_LARGE,
         STEP_INPUT_TOO_LARGE,
         SUBFLOW_INPUT_TOO_LARGE,
         encoded_bytes,
         fits,
         payload_bytes,
+        secret_bytes,
+        secrets_limit,
     )
 
 IN_FLIGHT_CAP = 100  # activities and child workflows outstanding per execution (spec §6)
@@ -223,6 +226,7 @@ class Execution:
         self._yield_timer: asyncio.Task[None] | None = None  # the one yield point every waiter shares
         self._rows: dict[tuple[str, str, int], StepRow] = {}  # queued for the next projection, per attempt
         self._secrets: Secrets = ()  # sensitive values seen so far: masked in everything projected
+        self._secrets_json = 0  # their JSON bytes, without the list's brackets and commas (`_learned`)
         self._started: dict[Instance, str] = {}
         self._cel_modes: dict[Instance, str] = {}
         self._projects = 0
@@ -280,7 +284,7 @@ class Execution:
         self.checkpoint_events, self.drain_events = checkpoint_events, drain_events
         self.vars: dict[str, Any] = {}
         if parent is not None:
-            self._secrets = remember((), tuple(parent.secrets))
+            self._carry(remember((), tuple(parent.secrets)))
 
     # --- the scheduler loop ----------------------------------------------------------------------------------------
 
@@ -571,8 +575,27 @@ class Execution:
             size += row_size
         return taken
 
-    def _learn(self, value: Any, schema: Mapping[str, Any] | None) -> None:
-        self._secrets = remember(self._secrets, sensitive_values(value, schema))
+    def _carry(self, secrets: Secrets) -> None:
+        """What a parent or a snapshot hands over: within the bound already."""
+        self._secrets, self._secrets_json = secrets, sum(secret_bytes(v) for v in secrets)
+
+    def _learned(self, values: Iterable[str]) -> bool:
+        """Remember `values` as sensitive, unless carrying them would pass SECRETS_BYTES: the execution carries what it
+        learned in its result, its children's starts and its snapshot, so that they're masked there too (engine 2b
+        spec §5.2). Past the bound nothing is remembered, and False tells the caller to fail what taught them, and
+        never use it. What's carried is never dropped: a parent masks everything its children tell it. Measured as it
+        grows, since binding and learning happen in one workflow task (#18)."""
+        grown = remember(self._secrets, values)
+        if grown is self._secrets:
+            return True
+        json_bytes = self._secrets_json + sum(secret_bytes(v) for v in set(grown).difference(self._secrets))
+        if 2 + json_bytes + len(grown) - 1 > secrets_limit():
+            return False
+        self._secrets, self._secrets_json = grown, json_bytes
+        return True
+
+    def _learn(self, value: Any, schema: Mapping[str, Any] | None) -> bool:
+        return self._learned(sensitive_values(value, schema))
 
     def _preview(self, value: Any, schema: Mapping[str, Any] | None = None) -> Any:
         return preview(value, schema, self._secrets)
@@ -927,7 +950,8 @@ class Execution:
         finally:
             self.sched.budget.settle_child(child, used)
             self._dirty = True
-        self._secrets = remember(self._secrets, tuple(result.secrets))
+        if not self._learned(result.secrets):  # its outputs go unused, so nothing here needs them masked
+            return _Effect(failure=Failure(PAYLOAD_TOO_LARGE, SECRETS_TOO_LARGE), cel_mode=cel_mode)
         if result.status == "succeeded":
             return _Effect(output=dict(result.outputs or {}), cel_mode=cel_mode)
         error = result.error or {"code": result.status, "message": f"The sub-flow ended {result.status}."}
@@ -1014,7 +1038,8 @@ class Execution:
         finally:
             self.sched.budget.settle_child(child, used)
             self._dirty = True
-        self._secrets = remember(self._secrets, tuple(result.secrets))
+        if not self._learned(result.secrets):  # what it collected goes unused: its loop fails
+            return _Effect(failure=Failure(PAYLOAD_TOO_LARGE, SECRETS_TOO_LARGE))
         if result.end is not None:
             end = RunEnd.from_json(result.end)
             if end.status == "cancelled":
@@ -1068,7 +1093,10 @@ class Execution:
         attempts = step.max_attempts or int(retry["max_attempts"])
         timeout = timedelta(seconds=step.timeout_s or float(manifest["timeout_s"]))
         ambiguous = manifest["side_effect"] == AMBIGUOUS
-        self._learn(config, manifest["config_schema"])  # a resolved sensitive value, before anything can echo it
+        if not self._learn(config, manifest["config_schema"]):  # a resolved sensitive value, before anything echoes it
+            failure = Failure(PAYLOAD_TOO_LARGE, SECRETS_TOO_LARGE)
+            self._queue_unstarted(inst, step, failure)  # never sent
+            return _Effect(failure=failure, cel_mode=cel_mode)
         attempt = 1
         while True:
             row = StepRow(
@@ -1128,7 +1156,13 @@ class Execution:
                 outcome = OUTCOME_UNKNOWN if ambiguous else None  # its request may have been sent
                 self._queue(replace(row, status="cancelled", ended_at=workflow.now().isoformat(), outcome=outcome))
                 raise asyncio.CancelledError from None
-            self._learn(result.output, manifest["output_schema"])
+            if not self._learn(result.output, manifest["output_schema"]):
+                # the node ran, so its outcome stands; its output goes nowhere
+                failure = Failure(PAYLOAD_TOO_LARGE, SECRETS_TOO_LARGE, attempt)
+                ended = workflow.now().isoformat()
+                failed = replace(row, status="failed", ended_at=ended, error_code=failure.code, outcome=result.outcome)
+                self._queue(replace(failed, error_message=failure.message))
+                return _Effect(failure=failure, cel_mode=cel_mode)
             self._queue(
                 replace(
                     row,
@@ -1206,7 +1240,7 @@ class Execution:
         self.program = program
         self.sched = Scheduler.from_json(program, snapshot["scheduler"])
         self.vars = dict(snapshot["variables"])
-        self._secrets = remember((), tuple(snapshot["secrets"]))
+        self._carry(remember((), tuple(snapshot["secrets"])))
         for key, step, wake, started, mode in snapshot["timers"]:
             inst = Instance(tuple((str(k), int(n)) for k, n in key), uuid.UUID(step))
             self._timers[inst] = datetime.fromisoformat(wake)
diff --git a/backend/src/dewpoint/engine/runtime/size.py b/backend/src/dewpoint/engine/runtime/size.py
index ab49a95..689cf15 100644
--- a/backend/src/dewpoint/engine/runtime/size.py
+++ b/backend/src/dewpoint/engine/runtime/size.py
@@ -9,6 +9,8 @@ with `payload_too_large`: a result, never a retried workflow task. Nothing is sp
 `fits` reads the limit from this module when it's called, so a test can lower it; workflow code imports names from
 this module's full path, which the sandbox passes through (a submodule taken from its package would be a copy)."""
 
+import json
+from collections.abc import Sequence
 from typing import Any
 
 from temporalio.converter import PayloadConverter
@@ -16,6 +18,9 @@ from temporalio.converter import PayloadConverter
 CODEC_OVERHEAD = 256  # bytes the tenant codec adds to a payload, at most: its metadata, the nonce and the tag
 PAYLOAD_BYTES = 1_835_008  # 1.75 MiB, encoded: a margin under Temporal's 2 MiB (2,097,152) payload limit
 SNAPSHOT_BYTES = 1_572_864  # 1.5 MiB, encoded: a continued run's input (spec §5.3's SNAPSHOT_MAX)
+# The sensitive values a run carries — in its result, its children's starts and its snapshot, so they're masked there
+# too — as JSON: a bound on them keeps every result that has no outputs far under PAYLOAD_BYTES (engine 2b spec §5.2).
+SECRETS_BYTES = 262_144
 PAYLOAD_TOO_LARGE = "payload_too_large"
 SNAPSHOT_TOO_LARGE = "snapshot_too_large"
 RUN_INPUT_TOO_LARGE = "The run's input is too large to start (over 1.75 MiB)."
@@ -25,6 +30,8 @@ HANDLER_INPUT_TOO_LARGE = "The failure handler's input is too large to send (ove
 BATCH_ITEM_TOO_LARGE = "An item of this loop, with what its batch reads, is too large to send (over 1.75 MiB)."
 RUN_SNAPSHOT_TOO_LARGE = "The run's state is too large to carry on (over 1.5 MiB)."
 BATCH_SNAPSHOT_TOO_LARGE = "A batch of this loop has too much state to carry on (over 1.5 MiB)."
+SECRETS_TOO_LARGE = "The sensitive values this run would have to carry are too many (over 256 KiB)."
+RESULT_TOO_LARGE = "The result is too large to return (over 1.75 MiB): please report it."
 STEP_OUTPUT_TOO_LARGE = "The step's output is too large to record (over 1.75 MiB)."
 VERSION_TOO_LARGE = "The version is too large to load (over 1.75 MiB)."
 OUTPUTS_TOO_LARGE = "The run's outputs are too large to return (over 1.75 MiB)."
@@ -36,6 +43,21 @@ def encoded_bytes(value: Any, converter: PayloadConverter) -> int:
     return len(converter.to_payloads([value])[0].data) + CODEC_OVERHEAD
 
 
+def secret_bytes(value: str) -> int:
+    """A sensitive value's JSON bytes, as the SDK's converter writes it (escaped as `json.dumps` does)."""
+    return len(json.dumps(value))
+
+
+def secrets_bytes(values: Sequence[str]) -> int:
+    """The JSON bytes of a list of sensitive values: its brackets, each value, and a comma between two."""
+    return 2 + sum(secret_bytes(v) for v in values) + max(len(values) - 1, 0)
+
+
+def secrets_limit() -> int:
+    """SECRETS_BYTES, read when it's called."""
+    return SECRETS_BYTES
+
+
 def payload_bytes() -> int:
     """PAYLOAD_BYTES, read when it's called."""
     return PAYLOAD_BYTES
diff --git a/backend/src/dewpoint/engine/runtime/workflow.py b/backend/src/dewpoint/engine/runtime/workflow.py
index 6135f7e..756b7ae 100644
--- a/backend/src/dewpoint/engine/runtime/workflow.py
+++ b/backend/src/dewpoint/engine/runtime/workflow.py
@@ -67,7 +67,9 @@ with workflow.unsafe.imports_passed_through():
         HANDLER_INPUT_TOO_LARGE,
         OUTPUTS_TOO_LARGE,
         PAYLOAD_TOO_LARGE,
+        RESULT_TOO_LARGE,
         RUN_SNAPSHOT_TOO_LARGE,
+        SECRETS_TOO_LARGE,
         SNAPSHOT_TOO_LARGE,
         fits,
         snapshot_fits,
@@ -173,8 +175,8 @@ class RunGraph(Execution):
         try:
             if snapshot is not None:
                 self._restore(program, snapshot)
-            else:
-                self._fresh(program)
+            elif not self._fresh(program):  # its trigger, or a literal, holds more sensitive values than a run carries
+                self.sched.end(RunEnd("failed", Failure(PAYLOAD_TOO_LARGE, SECRETS_TOO_LARGE)))
             if await self._drive() == CONTINUE:
                 await self._flush()
                 continued = replace(start, snapshot=self._snapshot(), iterations=self.sched.iterations)
@@ -204,20 +206,21 @@ class RunGraph(Execution):
             await self._failure_handler(pin, data, self._end_error(end))  # (a cancel meanwhile: no handler)
         return await self._finish(end, outputs, ended)
 
-    def _fresh(self, program: Program) -> None:
+    def _fresh(self, program: Program) -> bool:
         """A new run's state: its budget (the cap, or what its parent granted), the sensitive values it can see
-        already, and its variables."""
+        already, and its variables. False when those values are more than a run carries (engine 2b spec §5.2)."""
         self.program = program
         parent = self.parent
         budget = Budget(ITERATION_CAP, root=True) if parent is None else Budget(parent.grant, root=False)
         self.sched = Scheduler(program, budget=budget)
-        self._learn(self.trigger, program.graph.settings.input_schema)
+        learned = self._learn(self.trigger, program.graph.settings.input_schema)
         for step in program.steps.values():  # sensitive literals in plugin configs: masked from the start
-            if not step.control:
-                self._learn(resolve.assemble(step.config, {}), program.manifests[step.ref]["config_schema"])
+            if learned and not step.control:
+                learned = self._learn(resolve.assemble(step.config, {}), program.manifests[step.ref]["config_schema"])
         schema = program.graph.settings.vars_schema
         self.vars = {k: p.get("default") for k, p in sorted(schema.get("properties", {}).items())}
         self.sched.start()
+        return learned
 
     async def _outputs_by(self, end: RunEnd) -> tuple[RunEnd, dict[str, Any] | None]:
         """The workflow's outputs, within the run's deadline. Past it, their evaluation is cancelled and the run ends
@@ -256,25 +259,31 @@ class RunGraph(Execution):
     async def _finish(
         self, end: RunEnd, outputs: dict[str, Any] | None = None, ended: datetime | None = None
     ) -> RunResult:
-        error = self._end_error(end)
+        end, result = self._final(end, outputs, self.sched.iterations, list(self._secrets))
         summary = RunSummary(
             run_id=self.run_id,
             status=end.status,
             ended_at=(ended or workflow.now()).isoformat(),
-            error_code=error["code"] if error else None,
-            error_message=error["message"] if error else None,
+            error_code=result.error["code"] if result.error else None,
+            error_message=result.error["message"] if result.error else None,
             iterations=self.sched.iterations,
         )
         await self._project_end(summary)
-        return await self._returned(
-            RunResult(
-                status=end.status,
-                outputs=outputs,
-                error=error,
-                iterations=self.sched.iterations,
-                secrets=list(self._secrets),
-            )
-        )
+        return await self._returned(result)
+
+    def _final(
+        self, end: RunEnd, outputs: dict[str, Any] | None, iterations: int, secrets: list[str]
+    ) -> tuple[RunEnd, RunResult]:
+        """The run's end and its result, checked before either is recorded: every way a run ends returns through
+        here (engine 2b spec §5.2). Outputs were checked where they were made, and everything else a result carries
+        is bounded (a stored message, SECRETS_BYTES), so a result past the limit anyway is a bug: the run ends as one,
+        with no outputs, so nothing it returns needs masking by its parent, and its workflow task never retries."""
+        result = RunResult(end.status, outputs, self._end_error(end), iterations, secrets)
+        if fits(result, workflow.payload_converter()):
+            return end, result
+        workflow.logger.error("run_result_too_large")
+        end = RunEnd("failed", Failure(INTERNAL_ERROR, RESULT_TOO_LARGE))
+        return end, RunResult(end.status, None, self._end_error(end), iterations, [])
 
     def _end_error(self, end: RunEnd) -> dict[str, Any] | None:
         """The run's error as it's stored: its summary, its result and its failure handler's trigger all say this."""
@@ -286,17 +295,17 @@ class RunGraph(Execution):
     async def _end_early(self, end: RunEnd, iterations: int) -> RunResult:
         """The run ends before it has a program: nothing ran in this execution, so only the run is projected, with
         what it used before continuing as new (`iterations`)."""
-        error = self._stored(end.failure.to_json() if end.failure is not None else None)
+        end, result = self._final(end, None, iterations, [])
         summary = RunSummary(
             run_id=self.run_id,
             status=end.status,
             ended_at=workflow.now().isoformat(),
-            error_code=error["code"] if error else None,
-            error_message=error["message"] if error else None,
+            error_code=result.error["code"] if result.error else None,
+            error_message=result.error["message"] if result.error else None,
             iterations=iterations,
         )
         await self._shielded([], summary)
-        return await self._returned(RunResult(status=end.status, error=error, iterations=iterations))
+        return await self._returned(result)
 
     async def _cancelled_early(self, iterations: int) -> RunResult:
         """Cancelled before the run restored its snapshot or started: it reports what it used before continuing as new
@@ -472,7 +481,9 @@ class LoopBatch(Execution):
                 # engine 2b spec §5.3: too large to carry on, the batch ends here and its loop fails
                 stopped = Failure(SNAPSHOT_TOO_LARGE, BATCH_SNAPSHOT_TOO_LARGE).to_json()
                 return await self._returned(
-                    BatchResult([], [], stopped, iterations=self.sched.iterations, secrets=list(self._secrets))
+                    self._checked(
+                        BatchResult([], [], stopped, iterations=self.sched.iterations, secrets=list(self._secrets))
+                    )
                 )
         except asyncio.CancelledError:
             self.sched.end(RunEnd("cancelled", CANCELLED))
@@ -490,7 +501,10 @@ class LoopBatch(Execution):
         outcome = self.sched.outcome
         if outcome is None:  # the run ended inside the batch
             end = end or RunEnd("failed", Failure("error", "The batch ended without a result."))
-            return BatchResult([], [], end=end.to_json(), iterations=self.sched.iterations, secrets=list(self._secrets))
+            ended = BatchResult(
+                [], [], end=end.to_json(), iterations=self.sched.iterations, secrets=list(self._secrets)
+            )
+            return self._checked(ended)
         result = BatchResult(
             collected=outcome.collected,
             failures=outcome.failures,
@@ -503,7 +517,19 @@ class LoopBatch(Execution):
         # Temporal would refuse to record it (engine 2b spec §5.2): the loop fails instead, and no collected item is
         # dropped silently. The iterations it used still reach the parent.
         stopped = Failure(PAYLOAD_TOO_LARGE, BATCH_RESULTS_TOO_LARGE)
-        return BatchResult([], [], stopped.to_json(), iterations=self.sched.iterations, secrets=list(self._secrets))
+        return self._checked(
+            BatchResult([], [], stopped.to_json(), iterations=self.sched.iterations, secrets=list(self._secrets))
+        )
+
+    def _checked(self, result: BatchResult) -> BatchResult:
+        """A result with nothing collected carries only an error and the bounded sensitive values, so past the limit
+        anyway is a bug (engine 2b spec §5.2): the batch fails its loop as one, with nothing its parent would need to
+        mask, and its workflow task never retries."""
+        if fits(result, workflow.payload_converter()):
+            return result
+        workflow.logger.error("batch_result_too_large")
+        stopped = Failure(INTERNAL_ERROR, RESULT_TOO_LARGE).to_json()
+        return BatchResult([], [], stopped, iterations=result.iterations, secrets=[])
 
 
 __all__ = [
````

- [ ] **Step 4: Run the tests again**

Run: `cd backend && uv run pytest -q -p no:cacheprovider tests/apps/worker/test_run_graph_sizes.py tests/engine/runtime/test_size.py`

Expected (the replay):

````text
22 passed in 8.45s
````

- [ ] **Step 5: The whole suite, lint, types and layers**

Run: `cd backend && uv run pytest -q -p no:cacheprovider`, then `uv run ruff check --no-cache src tests migrations`, `uv run ruff format --no-cache --check src tests migrations`, `uv run mypy src` and `uv run lint-imports`.

Expected: 1,205 passed, 8 skipped; ruff and its formatter clean; mypy: no issues; import-linter: 10 contracts kept.

- [ ] **Step 6: Commit**

```bash
git add -A backend deploy docs && git commit -m "feat(engine): carried sensitive values bounded, every final result checked (2b-1a)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 13: Operations guides, and the older specs

**Spec:** §13.

**Files:**
- Modify: `docs/operations/deployment.md`
- Modify: `docs/operations/key-rotation.md`
- Modify: `docs/operations/runs.md`
- Modify: `docs/superpowers/specs/2026-09-24-dewpoint-architecture-design.md`
- Modify: `docs/superpowers/specs/2026-09-25-engine-core-design.md`

**Interfaces:**
- Consumes: every earlier task's behavior. Produces: documentation only.

- `deployment.md`:
  - the environment record and the namespace check;
  - the production gate;
  - encrypted payloads and workflow ids;
  - worker health;
  - Compose's migrate step;
  - build-id examples for ABI 5.
- `runs.md`: what the worker and `dev run` need; the new codes and limits, the bound on sensitive values included.
- `key-rotation.md`: data keys encrypt Temporal payloads; the cache's 5 minutes; the floor before an older version
  may be retired, since nothing records its last use for payloads.
- `deployment.md`'s worker health: what the check proves (the KEK, and the role's access to data keys), that an
  outage proves nothing, and what it doesn't: that stored keys unwrap, which `dewpoint keys status` (KEK ids) doesn't
  prove either, and which lifting the gate checks.
- Engine-core revision 5.7 (§5.6, §5.7, §9), and the architecture spec's §6.1 workflow id.

- [ ] **Step 1: Implement**

````diff
diff --git a/docs/operations/deployment.md b/docs/operations/deployment.md
index 84d4fcd..1fffb85 100644
--- a/docs/operations/deployment.md
+++ b/docs/operations/deployment.md
@@ -1,6 +1,7 @@
 # Deploying builds: Temporal and the engine worker
 
-Spec: `docs/superpowers/specs/2026-09-25-engine-core-design.md` §7.
+Specs: `docs/superpowers/specs/2026-09-25-engine-core-design.md` §7, and `2026-09-29-engine-2b-design.md` §2 and §6
+(the environment, the production gate, encrypted payloads, worker health).
 
 A run is **pinned** to the build it started on. Its sub-flows, its loop batches and the runs it continues as finish
 on that build too, even after a newer build takes over. That's what lets a new build change how runs execute without
@@ -9,7 +10,7 @@ breaking the runs already going. Runs of a build from before versioning aren't p
 
 ## Builds and versions
 
-- Each build of Dewpoint has a build ID, `dewpoint-<version>+abi<engine ABI>`, for example `dewpoint-0.1.0+abi3`. The
+- Each build of Dewpoint has a build ID, `dewpoint-<version>+abi<engine ABI>`, for example `dewpoint-0.1.0+abi5`. The
   engine ABI changes whenever a build could execute a workflow differently, so such a build always has a new ID.
 - Every engine worker joins one Temporal **Worker Deployment**, `dewpoint-engine`, as its build's version.
 - New runs start on the deployment's **current** version. Nothing becomes current by itself: making a build current
@@ -20,9 +21,9 @@ breaking the runs already going. Runs of a build from before versioning aren't p
 `dewpoint deployment status` shows the current build and every version Temporal knows:
 
 ```text
-current: dewpoint-0.1.0+abi3
-dewpoint-0.1.0+abi2  draining
-dewpoint-0.1.0+abi3  current
+current: dewpoint-0.1.0+abi5
+dewpoint-0.1.0+abi4  draining
+dewpoint-0.1.0+abi5  current
 ```
 
 A `draining` version still has runs pinned to it. A `drained` one has none left.
@@ -47,14 +48,14 @@ old build's runs that still use it finish on the old build's workers, which stil
 
 ## A build with a new engine ABI
 
-A build ID ends with its engine ABI (`+abi3`), which changes whenever a build could execute a workflow differently. A
+A build ID ends with its engine ABI (`+abi5`), which changes whenever a build could execute a workflow differently. A
 version runs only on a build of the ABI it was published for. So when a new build changes it:
 
 - Runs already started on the old build finish there, pinned to it, with their sub-flows and failure handlers. (A
   build from before versioning doesn't pin them: see below.)
 - A new run starts on the deployment's current build, so that's the build admission compares versions with,
   whichever build's process admits the run. While the old build is current, the new build's versions are refused
-  ("make a build of ABI 3 current first"). Once the new build is current, the old build's versions are refused
+  ("make a build of ABI 5 current first"). Once the new build is current, the old build's versions are refused
   ("publish the workflow again"), and `dewpoint dev run` prints which ones. A sub-flow or failure handler of the other
   ABI refuses its parent's runs the same way.
 - Publish each workflow again with the new build once it's current. Start with the workflows that others run as
@@ -81,11 +82,65 @@ Until a versioned build is current, the new build admits nothing: no build is cu
 don't check the ABI when they admit a run, but a run they start after the promotion starts on the new build, whose
 loader refuses a version of another ABI.
 
+## The deployment's environment and the production gate
+
+A deployment is `production` or `development`, recorded once with the Temporal namespace it uses:
+
+```bash
+dewpoint platform init-environment --environment production --temporal-namespace dewpoint
+```
+
+- The defaults are `DEWPOINT_ENVIRONMENT` (else `production`) and `DEWPOINT_TEMPORAL_NAMESPACE` (else `default`).
+  Running it again with the same values changes nothing; with other values it refuses: neither can change.
+- Every process that talks to Temporal — the worker and the CLI's Temporal commands — compares its configured
+  namespace with the record before it connects, and exits 2 when there's no record or it doesn't match. So a
+  development database can't drive a namespace it wasn't set up for, and a production database can't either. The
+  label proves nothing about the data: keep development's database and namespace apart from production's, with
+  synthetic data only.
+- In `production`, no run starts until the production gate is lifted (sub-project 2b-4, after its readiness checks):
+  `dewpoint dev run` is refused, exit 2, with "Production runs are off in this deployment". In `development`, runs
+  start freely.
+
+## Encrypted payloads
+
+Every payload Dewpoint's workflows exchange with Temporal — a run's input and result, each step's input and output,
+children's starts and results, failures' messages — is encrypted with its tenant's data key
+([`key-rotation.md`](key-rotation.md)). The tenant is the one the workflow id names: `t:<tenant>:run:<run id>` for
+every run, a sub-flow and a failure handler included, and `t:<tenant>:run:<run id>/<step>/<iteration>/batch:<start>`
+for a loop's batch. Temporal's Web UI shows ciphertext; what stays readable there is the ids, workflow and activity
+types, task queues, timestamps, and a local activity's own bookkeeping (its type and times).
+
+- The worker and `dewpoint dev run` need the KEK (`DEWPOINT_KEK_B64`, `DEWPOINT_KEK_ID`) and read tenants' data keys
+  through their database roles; they cache them for at most 5 minutes.
+- A tenant gets its data key when it's created. `dewpoint keys ensure-tenants`, run as the database owner, gives one
+  to every tenant that has none (tenants created before this build); Compose's migrate step runs it.
+- A run of an older build (ABI 4 and before) keeps its plain-text payloads and its old workflow id; it finishes on its
+  own build, as any pinned run does.
+
+## Worker health
+
+Each engine worker instance records itself in `worker_instances`: its build, its capabilities (`payload_codec`,
+`cel_request_size_guard`), and whether its self-check passed — at startup, before it polls, and every 30 seconds. The
+check proves what `payload_codec` needs of the instance: its KEK wraps and unwraps a key, and its database role may
+read data keys. An instance that fails it stops polling (running attempts get the shutdown grace) and exits with code
+3; its process manager should restart it. A database that doesn't answer proves nothing either way: during an outage
+the worker keeps running, records nothing, and its row goes stale. Sub-project 2b-2's dispatcher starts runs only
+while every live instance of the current build is healthy and holds every capability.
+
+The check is deliberately light: it proves a grant and a fresh key's round trip, not that stored keys unwrap. A wrong
+KEK configured under the right id passes it, and passes `dewpoint keys status`, which compares KEK ids
+([`key-rotation.md`](key-rotation.md)). Lifting the production gate (sub-project 2b-4) unwraps every stored data key
+and reads each tenant's key the way the workers do, first.
+
 ## Docker Compose (evaluation)
 
 Compose runs Temporal's dev server (the `temporal` service: its state in SQLite on the `temporal-data` volume, its Web
 UI at <http://127.0.0.1:8233>) and one `worker`. Production uses a Temporal cluster instead.
 
+Its `migrate` service upgrades the schema, records the environment (`DEWPOINT_ENVIRONMENT`, `production` unless set),
+and gives every tenant a data key. Ordinary Compose is `production`, so no run starts; CI and local development set
+`DEWPOINT_ENVIRONMENT=development` through their own override, on a database of their own.
+
 Compose runs one build at a time, so its worker makes its own build current as it starts
 (`DEWPOINT_WORKER_SET_CURRENT=true`). Replacing the `worker` container with a new image removes the old build's only
 worker: **let runs end before upgrading**, or their build's worker must come back for them to finish. When the new
diff --git a/docs/operations/key-rotation.md b/docs/operations/key-rotation.md
index 882a6b8..091a08b 100644
--- a/docs/operations/key-rotation.md
+++ b/docs/operations/key-rotation.md
@@ -2,7 +2,9 @@
 
 Dewpoint uses envelope encryption:
 
-- **Data keys** (one per tenant, plus one platform key for user TOTP secrets) encrypt secrets such as Mist API tokens.
+- **Data keys** (one per tenant, plus one platform key for user TOTP secrets) encrypt secrets such as Mist API tokens,
+  and every payload a tenant's runs exchange with Temporal. A tenant gets its key when it's created; `dewpoint keys
+  ensure-tenants`, as the database owner, gives one to tenants created before (Compose's migrate step runs it).
 - The **key-encryption key (KEK)** wraps every data key. It is supplied through `DEWPOINT_KEK_B64` (with its id in
   `DEWPOINT_KEK_ID`) and is never stored in the database.
 
@@ -47,7 +49,18 @@ dewpoint keys rotate-dek --platform
 ```
 
 Existing ciphertext stays readable (old data-key versions are kept); new encryptions use the new version. This is
-independent of KEK rotation.
+independent of KEK rotation. Workers and the CLI cache a tenant's key for up to 5 minutes, so their Temporal payloads
+switch to the new version within that time.
+
+Never delete an older version before Temporal can hold no payload encrypted with it. Nothing records a version's last
+use for payloads; its bound is:
+
+> the new version's creation + 5 minutes (the cache) + twice `DEWPOINT_MAX_RUN_DURATION_DAYS` (a run, then its
+> failure handler, with the longest duration ever configured) + the Temporal namespace's retention.
+
+No run that could hold such a payload may still be open either: a run stalled past its deadline (its build's workers
+gone) keeps its history until it closes. Dewpoint has no command that deletes a data key version yet; the one that retires
+versions (sub-project 2b-4) enforces this, and the spec's other conditions for records stored under the version.
 
 ## Backups
 
diff --git a/docs/operations/runs.md b/docs/operations/runs.md
index c0456c6..74b43bf 100644
--- a/docs/operations/runs.md
+++ b/docs/operations/runs.md
@@ -16,9 +16,14 @@ public run API arrive with sub-project 2b, and so do admission control and idemp
 `dewpoint worker` polls the `dewpoint-engine` task queue: the `RunGraph` and `LoopBatch` workflows, the version
 loader, the projection, and one activity per installed plugin node type. It needs:
 
-- `DEWPOINT_DATABASE_URL` with a login in the `dewpoint_worker` role. That role reads versions and writes `runs` and
-  `run_steps`, inside the run's tenant only (row-level security).
-- `DEWPOINT_TEMPORAL_ADDRESS` (default `localhost:7233`) and `DEWPOINT_TEMPORAL_NAMESPACE` (default `default`).
+- `DEWPOINT_DATABASE_URL` with a login in the `dewpoint_worker` role. That role reads versions and the tenant's data
+  keys, and writes `runs` and `run_steps`, inside the run's tenant only (row-level security); it also records the
+  instance in `worker_instances`.
+- `DEWPOINT_TEMPORAL_ADDRESS` (default `localhost:7233`) and `DEWPOINT_TEMPORAL_NAMESPACE` (default `default`), the
+  namespace this deployment recorded ([`deployment.md`](deployment.md)): on any other, or with none recorded, the worker
+  exits 2 before it connects.
+- The KEK (`DEWPOINT_KEK_B64`, `DEWPOINT_KEK_ID`): every payload it exchanges with Temporal is encrypted with its
+  tenant's data key. It checks its KEK at startup and every 30 seconds, and exits 3 when the check fails.
 - `DEWPOINT_CEL_SOCKET` when a `cel-evaluator` runs next to it. The worker then waits for the evaluator, asks which
   CEL profile it serves, and serves `cel.evaluate` on that profile's queue (`dewpoint-cel.<profile>`) with
   `DEWPOINT_CEL_MAX_CONCURRENT` activities at a time (default 2; match the evaluator's slots,
@@ -57,14 +62,16 @@ dewpoint dev run <version-id> --tenant <tenant-id> --input trigger.json
   simulation fails its step with `simulation_unavailable`. Timers still wait, as they would in a live run.
 - By default the command waits and prints the result. `--no-wait` prints the run id and returns.
 - Exit codes: 0 when the run succeeded; 1 when it ended otherwise, or Temporal refused to start it; 2 when it wasn't
-  admitted (each reason is printed); 3 when Temporal never confirmed the start (see below).
-- It needs `DEWPOINT_DATABASE_URL` with a login in the `dewpoint_dispatch` role, and the Temporal settings above.
+  admitted (each reason is printed: in a `production` deployment, "Production runs are off in this deployment"; a
+  trigger too large to send, over 1.75 MiB); 3 when Temporal never confirmed the start (see below).
+- It needs `DEWPOINT_DATABASE_URL` with a login in the `dewpoint_dispatch` role, the Temporal settings above, and the
+  KEK: it encrypts the start with the tenant's data key.
 
 The trigger file is test data: 2a doesn't validate it against the workflow's input schema (2b's triggers will). A
 value that breaks the schema fails the step that reads it.
 
 **An unconfirmed start.** A start whose answer is lost looks like a failure, so it's retried with the same workflow id
-(the run's id), which Temporal refuses as a duplicate if the first attempt went through. Only a confirmed refusal
+(`t:<tenant>:run:<run id>`), which Temporal refuses as a duplicate if the first attempt went through. Only a confirmed refusal
 records the run as failed (`start_failed`). If no attempt is answered at all, the run may be executing: it stays
 `running`, and the command exits 3.
 
@@ -128,7 +135,9 @@ Anyone who can view runs can read the projection, so it keeps secrets out:
 - Characters Postgres can't store (NUL, lone surrogates) show as U+FFFD, and a number JSON can't hold (NaN,
   infinity) as its name.
 
-Temporal's own history still holds the values in full until 2b's payload encryption: restrict access to Temporal.
+Temporal's own history holds every payload encrypted with the tenant's data key: its Web UI shows ciphertext. A run's
+workflow id is `t:<tenant>:run:<run id>`, a sub-flow's and a failure handler's too
+([`deployment.md`](deployment.md#encrypted-payloads)).
 
 ## How a run ends
 
@@ -139,15 +148,17 @@ Temporal's own history still holds the values in full until 2b's payload encrypt
 | `failed` | `workflow_failed` | A `fail` node ended the run. |
 | `failed` | `start_failed` | Temporal refused to start it. |
 | `failed` | `version_unusable` | This build can't load or run the version, for example a node type it lacks. Nothing ran. |
-| `failed` | `internal_error` | A bug in the interpreter. The message names the exception's type, and the worker's log has the details; please report it. |
+| `failed` | `internal_error` | A bug in the interpreter. The message names the exception's type, and the worker's log has the details, or says the result was too large to return; please report it. |
+| `failed` | `payload_too_large` | The run's outputs were too large to return (over 1.75 MiB once encrypted). A step or a loop fails with the same code, below. |
+| `failed` | `snapshot_too_large` | The run's state was too large to carry on as a new Temporal execution (over 1.5 MiB). |
 | `failed` | `terminated` | A sub-run that an operator terminated in Temporal. It couldn't record its end, so its parent did, and the step or loop that started it failed with the same code. |
 | `deadline_exceeded` | `deadline_exceeded` | The run passed `DEWPOINT_MAX_RUN_DURATION_DAYS` (default 30). Running steps were cancelled. |
 | `cancelled` | `cancelled` | The run was cancelled in Temporal. A cancel that arrives while the run's end is being written leaves that end. |
 
 Step error codes include the plugin's own codes and `config_invalid`, `output_schema_violation`, `unexpected_error`,
 `evaluation_error`, `type_mismatch`, `timeout`, `cel_profile_unavailable`, `input_too_large`, `item_cap_exceeded`,
-`iteration_cap_exceeded` and `node_type_unavailable` (the registry lists the node type, but no worker of this build
-runs it: install its plugin on the workers). A sub-flow step fails with its sub-flow's code, and with `terminated`
+`iteration_cap_exceeded`, `node_type_unavailable` (the registry lists the node type, but no worker of this build
+runs it: install its plugin on the workers) and `payload_too_large`. A sub-flow step fails with its sub-flow's code, and with `terminated`
 when an operator terminated the sub-flow; a loop fails with `terminated` when one of its batches was.
 
 ## Attempts and retries
@@ -168,9 +179,19 @@ retry settings (`max_attempts` and `timeout_s` can be overridden per step), and
 
 - At most 100 steps, batches and sub-flows run at once per run (and per child).
 - A run counts at most 100,000 loop iterations and filter items, its children's included (`iteration_cap_exceeded`).
-- A batch's or a sub-flow's input, and a run's continue-as-new snapshot, travel through Temporal, whose payloads are
-  limited to 2 MiB: a loop body that reads very large outside values, or a very large loop, can pass it until 2b's
-  claim check.
+- Everything a run sends Temporal, or returns, is checked where it's produced, against 1.75 MiB once encrypted
+  (Temporal's limit is 2 MiB): too large fails the step, the loop or the run with `payload_too_large`, never a stuck
+  run. That covers a step's input (nothing is sent) and its output (the step ran once: its row says `applied`), a
+  sub-flow's input and its outputs, a failure handler's input (its row records the failure), and the run's outputs.
+  A loop's batch is cut by bytes as well as by count; an item that doesn't fit in a batch with what the batch reads
+  fails the loop after the items before it. Large values move by reference with 2b-1b's claim check.
+- A run continues as a new Temporal execution when its history grows long; its state must stay within 1.5 MiB, or it
+  fails with `snapshot_too_large` (a batch fails its loop).
+- A run carries the sensitive values it has learned (to mask them in its result, its sub-runs and its batches) up to
+  256 KiB: the step, sub-flow or batch that would add more fails with `payload_too_large` ("The sensitive values this
+  run would have to carry are too many"), and a trigger that holds more fails the run before any step.
+- A workflow task sends at most 3 MiB of payloads, so its completion stays under Temporal's 4 MiB message limit: more
+  wait for the next task.
 - `flow.delay` waits 0 to 30 days, and `wait_until` takes instants from year 1 to 9999 in UTC. A value outside that,
   resolved at run time, fails the step with `type_mismatch`.
 
diff --git a/docs/superpowers/specs/2026-09-24-dewpoint-architecture-design.md b/docs/superpowers/specs/2026-09-24-dewpoint-architecture-design.md
index 49b627e..d0b6de0 100644
--- a/docs/superpowers/specs/2026-09-24-dewpoint-architecture-design.md
+++ b/docs/superpowers/specs/2026-09-24-dewpoint-architecture-design.md
@@ -172,7 +172,8 @@ Every run starts as a durable `run_requests` row, unique on `(tenant_id, idempot
 - **Schedule:** a Temporal Schedule fires the `ScheduleTick` workflow. Its single activity inserts a `run_requests` row keyed `sched:{schedule_id}:{scheduled_time}`. Schedules never start `RunGraph` directly.
 - **Admission:** `dispatcher` is the only component that starts `RunGraph`.
   - It reserves a per-tenant concurrency slot (`tenant_run_slots`, row lock). The request stays queued, FIFO per tenant, while the tenant is at its limit.
-  - It starts the run with workflow ID `run:{run_request_id}`, which makes the start idempotent.
+  - It starts the run with workflow ID `t:<tenant>:run:<run_id>`, the run id being its request's, which makes the
+    start idempotent (engine 2b spec §6.1).
   - The run releases its slot in a final activity. A reconciler compares slots against Temporal state to recover leaks.
   - Sub-flow child workflows and agent loops run inside the parent's slot.
 - Failure handling: backoff, then a dead-letter state visible to admins.
diff --git a/docs/superpowers/specs/2026-09-25-engine-core-design.md b/docs/superpowers/specs/2026-09-25-engine-core-design.md
index b46db65..81ac8df 100644
--- a/docs/superpowers/specs/2026-09-25-engine-core-design.md
+++ b/docs/superpowers/specs/2026-09-25-engine-core-design.md
@@ -93,6 +93,12 @@
   - Revision 5.6.1 (issue #15): a `cel.evaluate` request is cut by its JSON bytes as well as by 1,000 binding sets,
     a binding set that alone passes 1.75 MiB is `input_too_large`, and a workflow task sends at most 3 MiB of CEL
     requests (§5.6, §5.7). A run's commands can change, so `engine_abi` becomes 4, with its own golden histories.
+  - Revision 5.7 (sub-project 2b-1a, from `2026-09-29-engine-2b-design.md` §5.2 and §6): every run's workflow id is
+    built from its tenant and its run, a sub-flow's and a failure handler's too (§9); every payload a run sends
+    Temporal or returns is checked where it's produced, and fails with `payload_too_large` or
+    `snapshot_too_large` rather than retry a workflow task; the sensitive values a run carries are bounded (256 KiB),
+    so every result without outputs fits; a workflow task's byte budget covers every command it sends (§5.6, §5.7).
+    `engine_abi` becomes 5, with its own golden histories, recorded encrypted.
 - **Parent spec:** `2026-09-24-dewpoint-architecture-design.md` (§3 boundaries, §6 execution engine, §7 SDK).
   This spec **narrows parent §6.4** (where CEL runs) and resolves the CEL item in parent §15.
 - **Evidence:** CEL spike, branch `spike/cel-evaluation`, commits `d6a8162` and `13a62e1`. See
@@ -653,8 +659,8 @@ result is recorded in history. This is the parent's `eval` activity (§6.5).
   - Thresholds: 13,000 iterations, 5.5 MiB, 2,700,000 work units or 65,000 bound values (§5.5), a third below the
     first ones (20,000, 8 MiB, 4,000,000, 200 evaluations and 100,000), which took three of gate 7b's loads past 1 s
     on Linux.
-  - Apart from them, the cel.evaluate requests a task sends: at most 3 MiB (§5.7). It has no startup share, since that
-    limit is Temporal's, not CPU.
+  - Apart from them, the payloads a task sends: at most 3 MiB, every command's, its result's and a local activity's
+    marker (§5.7; 2b spec §5.2). It has no startup share, since that limit is Temporal's, not CPU.
   - The decision uses only stored bounds and a count, so it replays identically. The timer events count toward the continue-as-new threshold.
   - **This is a policy to measure, not a proven CPU bound.** A p99 latency says nothing about the worst case.
     Before local evaluation is enabled, the plan must run an adversarial test: expressions that max out the
@@ -724,8 +730,8 @@ not inside a worker that holds credentials.
   outcome `input_too_large`, and no request is sent for it (issue #15); nor for the sets after it, which can't change
   the result (a filter fails at its first failing item), so a workflow task never measures more than one refused set. A workflow task sends at most 3 MiB of these
   requests (`YIELD_SEND_BYTES`); the next one waits for the next task, so CEL requests alone can't push a task's
-  completion past Temporal's 4 MiB gRPC message limit, past which Temporal terminates the workflow. Other commands in
-  the same task aren't counted: the invariant over every command is sub-project 2b's.
+  completion past Temporal's 4 MiB gRPC message limit, past which Temporal terminates the workflow. Since revision
+  5.7 the budget counts every command a task sends, each payload at most 1.75 MiB once encoded (2b spec §5.2).
 - **Responses ≤ 256 KiB** plus the envelope. A malformed or oversized frame closes the connection.
 - **Aggregate limits.** The evaluator container has cgroup limits: memory (Compose `mem_limit`; initially 2 GiB),
   CPU, and pids.
@@ -1168,7 +1174,8 @@ cancel while the version loads cancels the run.
 - **No public run API in 2a.** Admission, idempotency keys and tenant slots arrive in 2b.
 - **Payloads are test data in 2a.** 2b validates them against the input schema. Until then a payload that breaks its
   schema fails the step that reads the bad value.
-- **A start is failed only when Temporal refused it.** The workflow id is the run id, with `REJECT_DUPLICATE`. An
+- **A start is failed only when Temporal refused it.** The workflow id is `t:<tenant>:run:<run id>` (2b spec §6.1),
+  with `REJECT_DUPLICATE`. An
   unanswered start is retried with the same id, and a duplicate refusal confirms it. `start_failed` is recorded only
   for a confirmed refusal; a start that stays unanswered leaves the run `running`.
````

- [ ] **Step 2: The whole suite, lint, types and layers**

Run: `cd backend && uv run pytest -q -p no:cacheprovider`, then `uv run ruff check --no-cache src tests migrations`, `uv run ruff format --no-cache --check src tests migrations`, `uv run mypy src` and `uv run lint-imports`.

Expected: 1,205 passed, 8 skipped; ruff and its formatter clean; mypy: no issues; import-linter: 10 contracts kept.

- [ ] **Step 3: Commit**

```bash
git add -A backend deploy docs && git commit -m "docs: 2b-1a in the operations guides, engine-core revision 5.7, the architecture spec's workflow id" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## During execution

- **The golden histories** come with Tasks 3 and 6's commits.
  - If one doesn't replay, find the cause first; re-record only the abi5 directory, and only in this branch.
  - The abi4 histories are immutable: a change that breaks their replay on their own build is a bug in the change.
  - The abi5 recordings vary in count from run to run (continue-as-new falls where a race puts it: #17's ruling).
    Each recording is valid if it replays.
- **A known test-isolation quirk, from before this plan.**
  - Run `tests/apps/worker/test_run_graph_policies.py` in one command with a time-skipping deadline test that comes
    after it (for example `test_run_graph.py::test_timers_are_durable_and_the_deadline_ends_the_run`), and the
    deadline test times out: a policies test leaves an activity outstanding on the shared server, and the server stops
    skipping time.
  - The suite's own order (alphabetical) never does this. It happens on `main` too, so it isn't this plan's; don't
    "fix" it by reordering files.
- **A start the client can't encrypt raises `CodecRefusedError`** (no tenant in the id) or the key source's error (no
  key) from `start_workflow`. Tests expect it there, before anything reaches Temporal.
- **mypy checks `src` only, as CI does** (`uv run mypy src`). Tests follow the repository's own style: fixture
  parameters untyped where the existing tests leave them so.

## Handoff

**Rolling out 2b-1a** (ABI 5, the codec) on an existing deployment, in this order:
1. **Migrate.** Migrations 0010–0012, then `dewpoint platform init-environment` (production unless
   `DEWPOINT_ENVIRONMENT` says otherwise), then `dewpoint keys ensure-tenants`. Compose's migrate step runs all three.
   A development setup sets `DEWPOINT_ENVIRONMENT=development` and its own namespace before its first migrate: the
   record never changes.
2. **Start the new workers.** They need the KEK, and they exit 2 on a namespace mismatch and 3 on a failed
   self-check.
3. **Switch builds.** Make the new build current (`dewpoint deployment set-current`), then publish every workflow
   again for ABI 5, children first (`docs/operations/deployment.md`). Runs of the ABI-4 build finish on it, with their
   plain payloads and bare ids, and it's stopped once `drained`.

**In a production deployment no run starts**: the gate stays off until 2b-4 lifts it after its readiness checks.

**Next: 2b-1b** (spec §1, `ENGINE_ABI` 6):
- claims, handles and grants;
- spilling before failing (§5.2), and the snapshot's compaction and live-state bound (§5.3), with its own dev-server
  go/no-go first;
- sensitive values moved into claims, replacing the inline bound (§5.2, `SECRETS_BYTES`).

**Left for 2b-2**, which consumes what this plan records:
- the dispatcher, which reads `worker_instances`, requires every live instance of the current build to be healthy
  with `payload_codec` and `cel_request_size_guard`, and encrypts starts;
- the dev CLI's move onto admission;
- the gate's recheck at dispatch.

**Left for 2b-4:** the readiness checks, among them §10.6's stored-key checks: as the key-admin role, every stored data
key unwraps with the configured KEKs (comparing KEK ids isn't enough), and with the workers' own role and KEKs, each
tenant's active key is read under RLS and unwrapped. Also the command that retires key versions, which enforces §6.4's
floor.

**Left to the spec, and not in any plan yet:** `dewpoint runs diagnose` (§6.7).

**To file separately:** the test-isolation quirk above (a policies test blocks time skipping for later tests on the
shared server; `own_env` exists for such tests).
