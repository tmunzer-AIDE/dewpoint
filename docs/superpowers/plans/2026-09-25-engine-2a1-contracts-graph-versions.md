# Engine 2a-1: Contracts, Graph and Versions — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Everything needed to author, validate and publish a workflow graph, without executing it yet. That covers:
- the public plugin SDK;
- the first-party `flow` plugin (control-node contracts) and a test-only `testkit` plugin;
- the manifest registry;
- the graph model and validator: structure, loop regions, typed references, path availability, variables, waits and sub-flows;
- immutable workflow versions with stored pinned closures;
- the node-type and CEL-profile lifecycle, locked so it serializes with publish and activate;
- the workflow API;
- CLI commands for plugins and the lifecycle.

**Architecture:**
- `dewpoint.sdk` is the plugin API and imports nothing internal. `dewpoint.plugins.*` depend only on the SDK.
- `dewpoint.engine` is pure (no DB, no network): graph model, validator and registry checks.
- `dewpoint.core` stores workflows, versions and the registry, and owns the lifecycle locks. It knows nothing about the engine.
- `dewpoint.apps` wires them: the API routes, `apps/workflow_ops.py` (validate/publish/activate) and `apps/plugin_loader.py` (entry points → registry).

**Tech Stack:** Python 3.12, Pydantic v2, SQLAlchemy 2 async + asyncpg, Alembic, FastAPI, Typer, `jsonschema` (Draft 2020-12), pytest + Hypothesis + testcontainers.

**Dry run before publication:** the code in Tasks 1–10 was extracted into a scratch worktree and run.
- 270 tests passed: the 101 foundations tests plus 169 new ones. That count is from revision 3 of this plan, after two rounds of review fixes.
- ruff, mypy `strict` and import-linter (6 contracts) were clean.
- Migration 0007 survived an upgrade → downgrade → upgrade round trip.

Test counts in the steps below come from that run.

**Spec:** `docs/superpowers/specs/2026-09-25-engine-core-design.md` (revision 5.2; §2, §3, §4; §5.2's 16,384-character limit; §10's unit and property tests). Parent: `docs/superpowers/specs/2026-09-24-dewpoint-architecture-design.md`.

## Where this plan sits

Sub-project 2a ships as three plans, each producing working, tested software:

| Plan | Scope | Depends on |
|---|---|---|
| **2a-1 (this plan)** | SDK, flow + testkit plugins, registry, graph model + validator, workflows/versions + lifecycle, API, CLI | foundations |
| 2a-2 | CEL: runtime adapter, typed environment (typed-path proof first), `fn-1`, classifier, bound estimator, canonicalization, `cel-evaluator` service, CEL gates; replaces this plan's `cel.unavailable` diagnostic | 2a-1 |
| 2a-3 | Execution: `RunGraph` (scopes, edge states, node kinds), iteration grants, quiescent continue-as-new, `runs`/`run_steps`, `start_run` with lifecycle locks at admission, worker, Compose, golden replays, two-build test | 2a-1, 2a-2 |

2a-3 carries the reviewer's measurable acceptance items. They are recorded here so they aren't lost:
- **Drain headroom:** measure the events and bytes added while draining with 100 activities and children in flight, including retries, failures, heartbeats and grant traffic. Assert they stay within the stated headroom, and adjust the initial numbers from the measurement.
- **No premature rejection:** with 10 child slots and one busy child, that child can use nearly the whole 100,000 budget. `iteration_cap_exceeded` happens only at the exact cap (spec revision 5).
- **Adversarial yield test and two-build deployment test** (spec §5.6, §7).

## Spec refinements made while planning

Each item keeps the spec's intent. They are folded into the spec (revision 5.1) in the same commit as this plan.

1. **Lock mechanism.** "`FOR SHARE` / `FOR UPDATE` on lifecycle rows" is implemented as **shared/exclusive transaction advisory locks** keyed `dewpoint:lifecycle:<node|cel>:<key>`. Postgres requires UPDATE privilege for row locks, and the API role must not hold it on the registry. Semantics, lock order (sorted) and the READ COMMITTED requirement are unchanged.
2. **Reference availability** uses *liveness conditions*: DNF formulas over branch decisions, computed per region. Dominators reject a reference after a parallel fan-out/join, even though the join waits for both paths. Liveness conditions accept that case and reduce to dominance when branches are exclusive. A Hypothesis soundness test checks them against simulated executions.
3. **`loops.<loop_key>.item` / `.index`** reach an enclosing loop's item from inside nested loops. `loop.*` still means the innermost loop.
4. **Workflow-level data lives in `graph.settings`:** `input_schema`, `vars_schema` (every variable declares a `default`), `outputs` (values evaluated when the run succeeds; they define the version's `output_schema`) and `failure_handler`. The draft compare-and-swap therefore covers them, and `workflows` needs no `vars_schema` column.
5. **Template parts** may carry a `default` (text), like refs.

The spec review of this plan added three more, folded into spec revision 5.2:

6. **Contract hash.** A node type version's registered contract is every manifest field except display metadata:
   - the manifest's `title` and `description`;
   - schema annotations, stripped only where schemas appear.

   A re-sync that changes credentials, capabilities, retry policy, timeout, schemas, ports, kind or side effect is refused.
7. **Local references only.** Tenant-authored schemas (`input_schema`, `vars_schema`) and manifest schemas may use only
   `#/$defs/<name>` references that resolve, with no cycle that recurses without descending into the data. Anything
   else is a diagnostic (`settings.unresolvable_ref`) or a manifest problem, never an exception during validation.
8. **Two hashes per version.**
   - `graph_hash` covers the authored graph only.
   - `version_hash` also covers the resolved sub-flow and failure-handler pins, the CEL profile and the engine ABI.
   - Audit and the versions API carry both. Integrity means `version_hash`.

## Global Constraints

- License header on every source file: `# SPDX-License-Identifier: Apache-2.0`.
- Python ≥ 3.12; mypy `strict` on `src`; ruff rules `E,F,I,B,UP,S,ASYNC`, line length 120. No `assert` in `src/` (S101); use explicit checks.
- **Import rules (import-linter, added in Task 1):**
  - `dewpoint.sdk` imports nothing from `dewpoint.core|engine|plugins|apps`;
  - `dewpoint.plugins` imports nothing from `dewpoint.core|engine|apps`;
  - `dewpoint.engine` imports nothing from `dewpoint.core|plugins|apps`, `sqlalchemy`, `asyncpg`, `fastapi` or `httpx`;
  - `dewpoint.core` imports nothing from `dewpoint.engine|plugins|apps`.
- The foundations rules still apply:
  - Every error body is `{"error": <code>, ...}`, and routes raise `HTTPException(detail={"error": ...})`.
  - `get_db` is always `Depends(get_db, scope="function")`.
  - Tenant scope comes only from the route; `require(P.X)` authorizes and sets `tenant_scope`.
  - Never return `str(exc)` to clients.
- **Tenant-scoped tables:**
  - `tenant_id`, `ENABLE` + `FORCE ROW LEVEL SECURITY`;
  - policy `USING (tenant_id = app_tenant_id()) WITH CHECK (tenant_id = app_tenant_id())`;
  - one SQL statement per `op.execute`.
- **`workflow_versions` is insert-only.** A trigger rejects UPDATE and DELETE, even for the table owner.
- **Audit details** never use keys matching `password|secret|token|code|credential` (`core/audit/service.py` rejects them).
- **Initial limits (to measure, not guarantees):**
  - graph: ≤ 500 nodes, ≤ 2,000 edges; draft request body ≤ 1 MiB;
  - loop nesting depth ≤ 3; sub-flow closure depth ≤ 5;
  - `max_run_duration_days` = 30; switch ≤ 20 cases;
  - CEL text ≤ 16,384 characters.
- **Constants:**
  - `ENGINE_ABI = 1`;
  - `CURRENT_CEL_PROFILE = "cel-cpp-0.1.3/fn-1/cls-1"` (seeded by migration 0007 and by `plugins sync`).
- In this plan, every `cel` value produces the error diagnostic `cel.unavailable`. Plan 2a-2 replaces it with classification.
- **Lifecycle locking.** Publish, activate and (later) admission and dispatch call `lifecycle.lock_shared(closure entries)` and then re-read `lifecycle.states()` in the same transaction. Retirement calls `lifecycle.lock_exclusive(entry)` first, then counts references. All of them assert READ COMMITTED.
- **Commits:**
  - Run the checks and the commit in **one `&&` chain**, so a failing check blocks the commit. Every commit message ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
  - Standard check chain, from `backend/`: `uv run ruff format . && uv run ruff check . && uv run mypy src && uv run lint-imports && uv run pytest <paths> -q`.
  - `ruff format .` runs first, so the layout of code blocks in this plan never blocks a commit. CI still runs `ruff format --check`.

## File Structure

```
backend/pyproject.toml                                 # + jsonschema, types-jsonschema, flow entry point, import contracts
backend/migrations/versions/0007_workflows.py          # registry, lifecycle states, workflows, versions, RLS, trigger
backend/src/dewpoint/sdk/__init__.py                   # public exports
backend/src/dewpoint/sdk/version.py                    # SDK_VERSION
backend/src/dewpoint/sdk/errors.py                     # NodeError, RetryableError, FatalError, OutcomeUnknownError
backend/src/dewpoint/sdk/context.py                    # StepContext / StepLogger protocols
backend/src/dewpoint/sdk/fields.py                     # literal_only, value_kinds, sensitive (JSON Schema markers)
backend/src/dewpoint/sdk/node.py                       # Node, NodeKind, SideEffect, RetryDefaults, Empty
backend/src/dewpoint/sdk/manifest.py                   # node_manifest, Plugin, ManifestError
backend/src/dewpoint/plugins/__init__.py
backend/src/dewpoint/plugins/flow/__init__.py          # PLUGIN
backend/src/dewpoint/plugins/flow/nodes.py             # control-node contracts
backend/src/dewpoint/engine/__init__.py                # ENGINE_ABI
backend/src/dewpoint/engine/canonical.py               # canonical_json, sha256_hex
backend/src/dewpoint/engine/cel/__init__.py
backend/src/dewpoint/engine/cel/profile.py             # CURRENT_CEL_PROFILE
backend/src/dewpoint/engine/registry/__init__.py
backend/src/dewpoint/engine/registry/control.py        # control type refs
backend/src/dewpoint/engine/schema_refs.py             # ref_problems: only resolvable, acyclic local $refs
backend/src/dewpoint/engine/registry/catalog.py        # NodeTypeSpec, Catalog, contract_hash, validate_plugin_manifest
backend/src/dewpoint/engine/graph/__init__.py
backend/src/dewpoint/engine/graph/diagnostics.py       # Diagnostic
backend/src/dewpoint/engine/graph/model.py             # Graph model, parse_graph, graph_json, graph_hash, version_hash
backend/src/dewpoint/engine/graph/values.py            # envelopes, RefPath, iter_values, strip_values
backend/src/dewpoint/engine/graph/schemas.py           # navigate, target_schema, json_types, compatible, markers
backend/src/dewpoint/engine/graph/structure.py         # analyze_structure: types, ports, edges, topo, regions
backend/src/dewpoint/engine/graph/liveness.py          # liveness conditions per region
backend/src/dewpoint/engine/graph/validate.py          # validate(): values, refs, availability, vars, waits, sub-flows
backend/src/dewpoint/core/config.py                    # + max_run_duration_days
backend/src/dewpoint/core/models/__init__.py           # + plugins, workflows
backend/src/dewpoint/core/models/plugins.py            # PluginManifest, NodeTypeVersion, CelProfile
backend/src/dewpoint/core/models/workflows.py          # Workflow, WorkflowVersion
backend/src/dewpoint/core/plugins/__init__.py
backend/src/dewpoint/core/plugins/registry.py          # sync_plugins, ensure_cel_profile, load/list node types
backend/src/dewpoint/core/plugins/lifecycle.py         # Entry, locks, states, deprecate, retire (+ preview)
backend/src/dewpoint/core/workflows/__init__.py
backend/src/dewpoint/core/workflows/service.py         # create, drafts (CAS), versions, activate, blocked_by
backend/src/dewpoint/apps/plugin_loader.py             # entry points → validated rows → registry
backend/src/dewpoint/apps/workflow_ops.py              # check_draft, publish, activate (engine + core)
backend/src/dewpoint/apps/api/routes/workflows.py
backend/src/dewpoint/apps/api/routes/node_types.py
backend/src/dewpoint/apps/api/main.py                  # + routers
backend/src/dewpoint/apps/cli/main.py                  # + plugins, lifecycle command groups
backend/tests/support/plugins/__init__.py
backend/tests/support/plugins/testkit.py               # TESTKIT plugin (never packaged)
backend/tests/support/catalog.py                       # catalog(*plugins, states=...)
backend/tests/support/graphs.py                        # G builder, nid(), ref(), cel(), template()
backend/tests/support/registry.py                      # sync_test_plugins()
backend/tests/support/workflows.py                     # seed_workflow() (owner-level SQL seeding)
backend/tests/sdk/test_manifest.py
backend/tests/plugins/test_flow_manifests.py
backend/tests/engine/registry/test_catalog.py
backend/tests/engine/test_schema_refs.py
backend/tests/engine/graph/test_model.py
backend/tests/engine/graph/test_structure.py
backend/tests/engine/graph/test_values.py
backend/tests/engine/graph/test_schemas.py
backend/tests/engine/graph/test_liveness.py
backend/tests/engine/graph/test_validate.py
backend/tests/core/workflows/test_rls_workflows.py
backend/tests/core/plugins/test_registry.py
backend/tests/core/plugins/test_lifecycle.py
backend/tests/apps/test_workflow_ops.py
backend/tests/apps/test_lifecycle_races.py
backend/tests/apps/api/test_workflows.py
backend/tests/apps/cli/test_plugins_cli.py
docs/operations/plugin-lifecycle.md
```

Every new test directory gets an empty `__init__.py` with the license header, as the existing `tests/` tree does.

---

### Task 1: Plugin SDK and import boundaries

**Files:**
- Create: `backend/src/dewpoint/sdk/{__init__,version,errors,context,fields,node,manifest}.py`
- Create: `backend/src/dewpoint/engine/__init__.py`, `backend/src/dewpoint/plugins/__init__.py`, `backend/src/dewpoint/plugins/flow/__init__.py` (a stub, completed in Task 2)
- Modify: `backend/pyproject.toml` (dependencies, import-linter contracts)
- Test: `backend/tests/sdk/__init__.py`, `backend/tests/sdk/test_manifest.py`

**Interfaces:**
- Produces:
  - `dewpoint.sdk`:
    - classes and enums: `Node`, `NodeKind(ACTION|CONTROL)`, `SideEffect(NONE|IDEMPOTENT|KEYED|RECONCILABLE|AMBIGUOUS)`, `RetryDefaults`, `Empty`, `StepContext`, `StepLogger`, `Plugin(name, version, nodes)`;
    - errors: `NodeError(code, message)`, `RetryableError`, `FatalError`, `OutcomeUnknownError`, `ManifestError(problems)`;
    - functions and constants: `node_manifest(cls) -> dict`, `literal_only(...)`, `value_kinds(*kinds, ...)`, `sensitive(...)`, `SDK_VERSION`.
  - `dewpoint.sdk.fields`: `LITERAL="x-dewpoint-literal"`, `KINDS="x-dewpoint-kinds"`, `SENSITIVE="x-sensitive"`, `VALUE_KINDS`.
  - `dewpoint.sdk.node`: `TYPE_RE`, `PORT_RE`, `RESERVED_PORTS=frozenset({"error"})`, `MAX_RETRY_ATTEMPTS=20`.
  - `node_manifest` marks output objects closed. Pydantic serialization emits only declared fields, so every output object that declares `properties` and says nothing about `additionalProperties` gets `additionalProperties: false`; models with `extra="allow"` keep `true`. The SDK defines its own `SCHEMA_ONE`/`SCHEMA_LIST`/`SCHEMA_MAP` (it can't import the engine), and a Task 3 test checks they match the engine's.
  - `node_manifest` rejects a retry policy the engine can't run: `max_attempts` outside 1–20, an `initial_interval` that isn't positive, a `backoff` below 1 or not finite, `max_interval < initial_interval`, or empty error codes in `non_retryable`.
  - `dewpoint.sdk.version`: `SDK_VERSION="0.1.0"`, `SDK_MAJOR="0"`.
  - `dewpoint.engine.ENGINE_ABI = 1`.
  - Node manifest dict keys: `type, version, kind, title, description, ports, dynamic_ports, config_schema, output_schema, credentials, capabilities, side_effect, retry{max_attempts, initial_interval_s, backoff, max_interval_s, non_retryable}, timeout_s`.
  - Plugin manifest keys: `name, version, sdk_version, nodes`.

- [ ] **Step 1: Add dependencies**

Run (from `backend/`): `uv add "jsonschema>=4.23" && uv add --dev "types-jsonschema>=4.23"`
Expected: `pyproject.toml` and `uv.lock` updated, exit 0.

- [ ] **Step 2: Write the failing test**

`backend/tests/sdk/__init__.py`:

```python
# SPDX-License-Identifier: Apache-2.0
```

`backend/tests/sdk/test_manifest.py`:

```python
# SPDX-License-Identifier: Apache-2.0
from datetime import timedelta
from typing import Any

import pytest
from pydantic import BaseModel, ConfigDict

from dewpoint.sdk import (
    FatalError,
    ManifestError,
    Node,
    NodeKind,
    Plugin,
    RetryDefaults,
    SideEffect,
    StepContext,
    literal_only,
    node_manifest,
    sensitive,
    value_kinds,
)
from dewpoint.sdk.fields import KINDS, LITERAL, SENSITIVE


class SendConfig(BaseModel):
    target: str
    retries: int = literal_only(2, ge=0, le=5)
    body: str = value_kinds("literal", "template", default="")


class SendOutput(BaseModel):
    message_id: str
    token_hint: str = sensitive()


class Send(Node):
    type = "demo.send"
    version = 2
    title = "Send"
    Config = SendConfig
    Output = SendOutput
    side_effect = SideEffect.KEYED
    retry = RetryDefaults(max_attempts=4, non_retryable=("demo.bad_request",))
    timeout = timedelta(seconds=30)

    async def run(self, ctx: StepContext, config: SendConfig) -> SendOutput:
        return SendOutput(message_id="m1", token_hint="t")


async def _run(self: Node, ctx: StepContext, config: Any) -> BaseModel:
    raise FatalError("demo.unused", "unused")


def _node(**attrs: Any) -> type[Node]:
    base: dict[str, Any] = {"type": "demo.x", "version": 1, "title": "X"}
    base.update(attrs)
    return type("X", (Node,), base)


def test_node_manifest_carries_schemas_and_markers() -> None:
    m = node_manifest(Send)
    assert (m["type"], m["version"], m["kind"], m["ports"]) == ("demo.send", 2, "action", ["out"])
    props = m["config_schema"]["properties"]
    assert props["retries"][LITERAL] is True
    assert props["body"][KINDS] == ["literal", "template"]
    assert m["output_schema"]["properties"]["token_hint"][SENSITIVE] is True
    assert m["retry"] == {
        "max_attempts": 4,
        "initial_interval_s": 1.0,
        "backoff": 2.0,
        "max_interval_s": 60.0,
        "non_retryable": ["demo.bad_request"],
    }
    assert m["timeout_s"] == 30.0 and m["side_effect"] == "keyed"


class Nested(BaseModel):
    name: str


class OpenOut(BaseModel):
    model_config = ConfigDict(extra="allow")
    nested: Nested


def test_output_schemas_say_which_objects_are_closed() -> None:
    closed = node_manifest(Send)["output_schema"]
    assert closed["additionalProperties"] is False  # serialization never emits undeclared fields
    opened = node_manifest(_node(run=_run, Output=OpenOut))["output_schema"]
    assert opened["additionalProperties"] is True  # extra="allow" keeps its extras
    assert opened["$defs"]["Nested"]["additionalProperties"] is False


def test_manifest_problems() -> None:
    cases = [
        (_node(type="Demo", run=_run), "type must look like"),
        (_node(version=0, run=_run), "version must be an integer"),
        (_node(ports=("out", "error"), run=_run), "invalid port 'error'"),
        (_node(ports=("a", "a"), run=_run), "duplicate ports"),
        (_node(dynamic_ports="cases", run=_run), "unknown config field"),
        (_node(), "must implement run()"),
        (_node(run=_run, side_effect=SideEffect.RECONCILABLE), "must implement reconcile()"),
        (_node(run=_run, retry=RetryDefaults(max_attempts=0)), "retry.max_attempts must be between 1 and 20"),
        (_node(run=_run, retry=RetryDefaults(max_attempts=21)), "retry.max_attempts must be between 1 and 20"),
        (
            _node(run=_run, retry=RetryDefaults(initial_interval=timedelta(0))),
            "retry.initial_interval must be positive",
        ),
        (_node(run=_run, retry=RetryDefaults(backoff=0.0)), "retry.backoff must be a finite number ≥ 1"),
        (_node(run=_run, retry=RetryDefaults(backoff=float("nan"))), "retry.backoff must be a finite number ≥ 1"),
        (
            _node(run=_run, retry=RetryDefaults(max_interval=timedelta(milliseconds=500))),
            "retry.max_interval must be ≥ retry.initial_interval",
        ),
        (_node(run=_run, retry=RetryDefaults(non_retryable=("",))), "retry.non_retryable must list error codes"),
    ]
    for node, fragment in cases:
        with pytest.raises(ManifestError) as e:
            node_manifest(node)
        assert fragment in str(e.value), (fragment, e.value.problems)


def test_control_nodes_need_no_run() -> None:
    assert node_manifest(_node(kind=NodeKind.CONTROL))["kind"] == "control"


def test_plugin_manifest_checks_prefix_and_duplicates() -> None:
    ok = Plugin(name="demo", version="1.0.0", nodes=(Send,))
    manifest = ok.manifest()
    assert manifest["nodes"][0]["type"] == "demo.send"
    assert manifest["sdk_version"] == "0.1.0"
    with pytest.raises(ManifestError, match="must start with 'other.'"):
        Plugin(name="other", version="1", nodes=(Send,)).manifest()
    with pytest.raises(ManifestError, match="duplicate"):
        Plugin(name="demo", version="1", nodes=(Send, Send)).manifest()


def test_value_kinds_rejects_unknown_kind() -> None:
    with pytest.raises(ValueError, match="value_kinds"):
        value_kinds("python")
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `uv run pytest tests/sdk -q`
Expected: FAIL: `ModuleNotFoundError: No module named 'dewpoint.sdk'`.

- [ ] **Step 4: Implement the SDK**

`backend/src/dewpoint/sdk/version.py`:

```python
# SPDX-License-Identifier: Apache-2.0
SDK_VERSION = "0.1.0"
SDK_MAJOR = SDK_VERSION.split(".", 1)[0]
```

`backend/src/dewpoint/sdk/errors.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""Errors a node raises. `code` is a stable, documented identifier; `message` must be safe to show users."""


class NodeError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class RetryableError(NodeError):
    """Transient: the engine retries it within the step's retry policy."""


class FatalError(NodeError):
    """Permanent: retrying can't help. The step fails and follows its error policy."""


class OutcomeUnknownError(NodeError):
    """The request may have been delivered. The engine never retries it automatically (`outcome_unknown`)."""
```

`backend/src/dewpoint/sdk/context.py`:

```python
# SPDX-License-Identifier: Apache-2.0
import uuid
from typing import Protocol


class StepLogger(Protocol):
    def info(self, event: str, **fields: object) -> None: ...

    def warning(self, event: str, **fields: object) -> None: ...


class StepContext(Protocol):
    """What a node sees while it runs. Sub-project 3 adds connection() and http. It is an API, not a sandbox."""

    @property
    def tenant_id(self) -> uuid.UUID: ...

    @property
    def run_id(self) -> uuid.UUID: ...

    @property
    def step_id(self) -> uuid.UUID: ...

    @property
    def iteration_key(self) -> str: ...

    @property
    def attempt(self) -> int: ...

    @property
    def log(self) -> StepLogger: ...

    @property
    def cancelled(self) -> bool: ...

    def idempotency_key(self) -> str: ...

    def heartbeat(self, *details: object) -> None: ...
```

`backend/src/dewpoint/sdk/fields.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""JSON Schema markers the engine reads from a node's Config and Output models."""

from typing import Any

from pydantic import Field
from pydantic_core import PydanticUndefined

LITERAL = "x-dewpoint-literal"  # written in the graph, never computed: ports, limits, pinned ids
KINDS = "x-dewpoint-kinds"  # value kinds a field accepts: literal, ref, template, cel
SENSITIVE = "x-sensitive"  # output field kept out of run_steps, previews and samples
VALUE_KINDS = frozenset({"literal", "ref", "template", "cel"})


def literal_only(default: Any = PydanticUndefined, **kwargs: Any) -> Any:
    return Field(default, json_schema_extra={LITERAL: True}, **kwargs)


def value_kinds(*kinds: str, default: Any = PydanticUndefined, **kwargs: Any) -> Any:
    if not kinds or set(kinds) - VALUE_KINDS:
        raise ValueError(f"value_kinds needs one or more of {sorted(VALUE_KINDS)}, got {sorted(kinds)}")
    extra: dict[str, Any] = {KINDS: sorted(kinds)}
    return Field(default, json_schema_extra=extra, **kwargs)


def sensitive(default: Any = PydanticUndefined, **kwargs: Any) -> Any:
    return Field(default, json_schema_extra={SENSITIVE: True}, **kwargs)
```

`backend/src/dewpoint/sdk/node.py`:

```python
# SPDX-License-Identifier: Apache-2.0
import builtins
import re
from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict

from dewpoint.sdk.context import StepContext

TYPE_RE = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")
PORT_RE = re.compile(r"^[a-z][a-z0-9_]{0,30}$")
RESERVED_PORTS = frozenset({"error"})  # added by the engine when a step routes errors to a port
MAX_RETRY_ATTEMPTS = 20  # same ceiling as a step's max_attempts override in the graph


class NodeKind(StrEnum):
    ACTION = "action"  # runs as a versioned activity
    CONTROL = "control"  # executed by the engine itself (flow plugin only)


class SideEffect(StrEnum):
    NONE = "none"
    IDEMPOTENT = "idempotent"
    KEYED = "keyed"
    RECONCILABLE = "reconcilable"
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True)
class RetryDefaults:
    max_attempts: int = 3
    initial_interval: timedelta = timedelta(seconds=1)
    backoff: float = 2.0
    max_interval: timedelta = timedelta(minutes=1)
    non_retryable: tuple[str, ...] = ()


class Empty(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Node:
    """Base class for node types. Subclasses set the class attributes; action nodes implement run()."""

    type: ClassVar[str]
    version: ClassVar[int]
    title: ClassVar[str]
    description: ClassVar[str] = ""
    kind: ClassVar[NodeKind] = NodeKind.ACTION
    # `builtins.type`: inside this class body, `type` names the class attribute above.
    Config: ClassVar[builtins.type[BaseModel]] = Empty
    Output: ClassVar[builtins.type[BaseModel]] = Empty
    ports: ClassVar[tuple[str, ...]] = ("out",)
    dynamic_ports: ClassVar[str | None] = None  # a config field whose entries each declare a `port`
    credentials: ClassVar[tuple[str, ...]] = ()
    capabilities: ClassVar[frozenset[str]] = frozenset()
    side_effect: ClassVar[SideEffect] = SideEffect.NONE
    retry: ClassVar[RetryDefaults] = RetryDefaults()
    timeout: ClassVar[timedelta] = timedelta(minutes=1)

    async def run(self, ctx: StepContext, config: Any) -> BaseModel:
        raise NotImplementedError

    async def simulate(self, ctx: StepContext, config: Any) -> BaseModel:
        raise NotImplementedError

    async def reconcile(self, ctx: StepContext, config: Any) -> BaseModel | None:
        raise NotImplementedError
```

`backend/src/dewpoint/sdk/manifest.py`:

```python
# SPDX-License-Identifier: Apache-2.0
import math
import re
from dataclasses import dataclass
from typing import Any

from dewpoint.sdk.node import MAX_RETRY_ATTEMPTS, PORT_RE, RESERVED_PORTS, TYPE_RE, Node, NodeKind, SideEffect
from dewpoint.sdk.version import SDK_VERSION

PLUGIN_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,40}$")

# JSON Schema 2020-12 keywords whose values are schemas. The engine keeps the same lists (engine/schema_refs.py; a test
# checks they agree): the SDK can't import the engine.
SCHEMA_ONE = frozenset(
    {
        "additionalProperties",
        "items",
        "contains",
        "propertyNames",
        "not",
        "if",
        "then",
        "else",
        "unevaluatedItems",
        "unevaluatedProperties",
        "contentSchema",
    }
)
SCHEMA_LIST = frozenset({"allOf", "anyOf", "oneOf", "prefixItems"})
SCHEMA_MAP = frozenset({"properties", "patternProperties", "$defs", "dependentSchemas"})


def _closed(schema: Any) -> Any:
    """Pydantic serialization emits only declared fields unless a model allows extras (it then says
    `additionalProperties: true`). Say so in the output schema, so references to undeclared fields are caught."""
    if not isinstance(schema, dict):
        return schema
    out = dict(schema)
    if "properties" in out and "additionalProperties" not in out:
        out["additionalProperties"] = False
    for key, value in out.items():
        if key in SCHEMA_ONE:
            out[key] = _closed(value)
        elif key in SCHEMA_LIST and isinstance(value, list):
            out[key] = [_closed(sub) for sub in value]
        elif key in SCHEMA_MAP and isinstance(value, dict):
            out[key] = {name: _closed(sub) for name, sub in value.items()}
    return out


class ManifestError(ValueError):
    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


def _retry_problems(name: str, node: type[Node]) -> list[str]:
    """A retry policy the engine can actually run (Temporal needs a positive interval and a backoff of at least 1)."""
    r = node.retry
    out: list[str] = []
    if (
        isinstance(r.max_attempts, bool)
        or not isinstance(r.max_attempts, int)
        or not 1 <= r.max_attempts <= MAX_RETRY_ATTEMPTS
    ):
        out.append(f"{name}: retry.max_attempts must be between 1 and {MAX_RETRY_ATTEMPTS}")
    if r.initial_interval.total_seconds() <= 0:
        out.append(f"{name}: retry.initial_interval must be positive")
    if (
        isinstance(r.backoff, bool)
        or not isinstance(r.backoff, int | float)
        or not math.isfinite(r.backoff)
        or r.backoff < 1
    ):
        out.append(f"{name}: retry.backoff must be a finite number ≥ 1")
    if r.max_interval < r.initial_interval:
        out.append(f"{name}: retry.max_interval must be ≥ retry.initial_interval")
    if not all(isinstance(code, str) and code for code in r.non_retryable):
        out.append(f"{name}: retry.non_retryable must list error codes")
    return out


def _problems(node: type[Node]) -> list[str]:
    missing = [a for a in ("type", "version", "title") if not hasattr(node, a)]
    if missing:
        return [f"{node.__name__}: missing {', '.join(missing)}"]
    name = f"{node.type}@{node.version}"
    out: list[str] = []
    if not TYPE_RE.match(node.type):
        out.append(f"{name}: type must look like 'plugin.name'")
    if isinstance(node.version, bool) or not isinstance(node.version, int) or node.version < 1:
        out.append(f"{name}: version must be an integer ≥ 1")
    if len(set(node.ports)) != len(node.ports):
        out.append(f"{name}: duplicate ports")
    for port in node.ports:
        if not PORT_RE.match(port) or port in RESERVED_PORTS:
            out.append(f"{name}: invalid port {port!r}")
    if node.dynamic_ports is not None and node.dynamic_ports not in node.Config.model_fields:
        out.append(f"{name}: dynamic_ports names unknown config field {node.dynamic_ports!r}")
    out += _retry_problems(name, node)
    if node.timeout.total_seconds() <= 0:
        out.append(f"{name}: timeout must be positive")
    if node.kind is NodeKind.ACTION:
        if node.run is Node.run:
            out.append(f"{name}: action nodes must implement run()")
        if node.side_effect is SideEffect.RECONCILABLE and node.reconcile is Node.reconcile:
            out.append(f"{name}: RECONCILABLE nodes must implement reconcile()")
    return out


def node_manifest(node: type[Node]) -> dict[str, Any]:
    problems = _problems(node)
    if problems:
        raise ManifestError(problems)
    r = node.retry
    return {
        "type": node.type,
        "version": node.version,
        "kind": node.kind.value,
        "title": node.title,
        "description": node.description,
        "ports": list(node.ports),
        "dynamic_ports": node.dynamic_ports,
        "config_schema": node.Config.model_json_schema(mode="validation"),
        "output_schema": _closed(node.Output.model_json_schema(mode="serialization")),
        "credentials": list(node.credentials),
        "capabilities": sorted(node.capabilities),
        "side_effect": node.side_effect.value,
        "retry": {
            "max_attempts": r.max_attempts,
            "initial_interval_s": r.initial_interval.total_seconds(),
            "backoff": r.backoff,
            "max_interval_s": r.max_interval.total_seconds(),
            "non_retryable": list(r.non_retryable),
        },
        "timeout_s": node.timeout.total_seconds(),
    }


@dataclass(frozen=True)
class Plugin:
    name: str
    version: str
    nodes: tuple[type[Node], ...]

    def manifest(self) -> dict[str, Any]:
        problems: list[str] = []
        if not PLUGIN_NAME_RE.match(self.name):
            problems.append(f"plugin name {self.name!r} must be a lowercase identifier")
        nodes: list[dict[str, Any]] = []
        seen: set[str] = set()
        for node in self.nodes:
            try:
                m = node_manifest(node)
            except ManifestError as e:
                problems.extend(e.problems)
                continue
            ref = f"{m['type']}@{m['version']}"
            if not m["type"].startswith(f"{self.name}."):
                problems.append(f"{ref}: type must start with '{self.name}.'")
            if ref in seen:
                problems.append(f"{ref}: duplicate node type version")
            seen.add(ref)
            nodes.append(m)
        if problems:
            raise ManifestError(problems)
        return {"name": self.name, "version": self.version, "sdk_version": SDK_VERSION, "nodes": nodes}
```

`backend/src/dewpoint/sdk/__init__.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""Dewpoint plugin SDK. Semver'd separately from the platform; plugins import only this package."""

from dewpoint.sdk.context import StepContext, StepLogger
from dewpoint.sdk.errors import FatalError, NodeError, OutcomeUnknownError, RetryableError
from dewpoint.sdk.fields import literal_only, sensitive, value_kinds
from dewpoint.sdk.manifest import ManifestError, Plugin, node_manifest
from dewpoint.sdk.node import Empty, Node, NodeKind, RetryDefaults, SideEffect
from dewpoint.sdk.version import SDK_VERSION

__all__ = [
    "SDK_VERSION",
    "Empty",
    "FatalError",
    "ManifestError",
    "Node",
    "NodeError",
    "NodeKind",
    "OutcomeUnknownError",
    "Plugin",
    "RetryDefaults",
    "RetryableError",
    "SideEffect",
    "StepContext",
    "StepLogger",
    "literal_only",
    "node_manifest",
    "sensitive",
    "value_kinds",
]
```

`backend/src/dewpoint/engine/__init__.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""Pure engine code: graph model, validator, registry checks. No DB, no network, no clock."""

ENGINE_ABI = 1  # bump on any change that can alter a run's command sequence (spec §7)
```

`backend/src/dewpoint/plugins/__init__.py` and `backend/src/dewpoint/plugins/flow/__init__.py` (the stub; Task 2 fills it in):

```python
# SPDX-License-Identifier: Apache-2.0
```

- [ ] **Step 5: Add the import contracts**

Append to `backend/pyproject.toml`, after the existing `[[tool.importlinter.contracts]]` blocks:

```toml
[[tool.importlinter.contracts]]
name = "sdk is self-contained"
type = "forbidden"
source_modules = ["dewpoint.sdk"]
forbidden_modules = ["dewpoint.core", "dewpoint.engine", "dewpoint.plugins", "dewpoint.apps"]

[[tool.importlinter.contracts]]
name = "plugins depend only on the sdk"
type = "forbidden"
source_modules = ["dewpoint.plugins"]
forbidden_modules = ["dewpoint.core", "dewpoint.engine", "dewpoint.apps"]

[[tool.importlinter.contracts]]
name = "engine is pure and depends only on the sdk"
type = "forbidden"
source_modules = ["dewpoint.engine"]
forbidden_modules = ["dewpoint.core", "dewpoint.plugins", "dewpoint.apps", "sqlalchemy", "asyncpg", "fastapi", "httpx"]

[[tool.importlinter.contracts]]
name = "core depends on neither engine nor plugins"
type = "forbidden"
source_modules = ["dewpoint.core"]
forbidden_modules = ["dewpoint.engine", "dewpoint.plugins"]
```

- [ ] **Step 6: Run the tests and the contracts**

Run: `uv run pytest tests/sdk -q && uv run lint-imports`
Expected: 5 passed; import-linter reports every contract KEPT.

- [ ] **Step 7: Commit**

```bash
uv run ruff format . && uv run ruff check . && uv run mypy src && uv run lint-imports && uv run pytest tests/sdk -q && \
git add pyproject.toml uv.lock src/dewpoint/sdk src/dewpoint/engine/__init__.py src/dewpoint/plugins tests/sdk && \
git commit -m "feat(sdk): plugin SDK with manifests, schema markers and import boundaries

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: The `flow` plugin (control-node contracts) and the `testkit` plugin

**Files:**
- Create: `backend/src/dewpoint/plugins/flow/nodes.py`
- Modify: `backend/src/dewpoint/plugins/flow/__init__.py`, `backend/pyproject.toml` (entry point)
- Create: `backend/tests/support/plugins/__init__.py`, `backend/tests/support/plugins/testkit.py`
- Test: `backend/tests/plugins/__init__.py`, `backend/tests/plugins/test_flow_manifests.py`

**Interfaces:**
- Consumes: `dewpoint.sdk` (Task 1).
- Produces:
  - `dewpoint.plugins.flow.PLUGIN` (name `flow`). Its nodes: `flow.if@1` (ports `true,false`), `flow.switch@1` (port `default` + dynamic `cases[*].port`), `flow.loop@1` (ports `body,done`), `flow.filter@1`, `flow.set_variables@1`, `flow.delay@1`, `flow.wait_until@1`, `flow.stop@1` (no ports), `flow.fail@1` (no ports), `flow.run_workflow@1`, `flow.transform@1`. All are `kind=control`.
  - Config fields:
    - if: `condition: bool`;
    - switch: `cases: list[{port (literal), when: bool}]`;
    - loop: `items: list`, `concurrency` (literal, 1–10), `item_cap` (literal, ≤ 10,000), `on_item_error` (literal `stop|continue`), `collect: Any`;
    - filter: `items: list`, `predicate: bool` (kinds `["cel"]`);
    - set_variables: `assignments: dict`;
    - delay: `duration_s: int`;
    - wait_until: `until: datetime`;
    - fail: `message: str`;
    - run_workflow: `workflow_id` (literal UUID), `input: dict`;
    - transform: `fields: dict`.
  - Outputs: loop `{items, failures[{index, code, message}], count}`; filter `{items, count}`; run_workflow and transform `OpenOutput` (extra allowed).
  - `tests.support.plugins.testkit.TESTKIT` (name `testkit`):
    - `testkit.echo@1`: config `{value}` → output `{value}` (required);
    - `testkit.fail_n@1`: `{failures}`, IDEMPOTENT;
    - `testkit.slow@1`: `{seconds}`;
    - `testkit.sensitive@1`: output `{public, secret_value (x-sensitive)}`;
    - `testkit.ambiguous_send@1`: `{outcome: sent|unknown|rejected}`, AMBIGUOUS.

- [ ] **Step 1: Write the failing test**

`backend/tests/plugins/__init__.py` and `backend/tests/support/plugins/__init__.py`:

```python
# SPDX-License-Identifier: Apache-2.0
```

`backend/tests/plugins/test_flow_manifests.py`:

```python
# SPDX-License-Identifier: Apache-2.0
from typing import Any

from dewpoint.plugins.flow import PLUGIN
from dewpoint.sdk import Plugin
from dewpoint.sdk.fields import KINDS, LITERAL, SENSITIVE
from tests.support.plugins.testkit import TESTKIT


def _nodes(plugin: Plugin) -> dict[str, dict[str, Any]]:
    return {f"{n['type']}@{n['version']}": n for n in plugin.manifest()["nodes"]}


def test_flow_plugin_declares_every_control_node() -> None:
    nodes = _nodes(PLUGIN)
    assert set(nodes) == {
        "flow.if@1",
        "flow.switch@1",
        "flow.loop@1",
        "flow.filter@1",
        "flow.set_variables@1",
        "flow.delay@1",
        "flow.wait_until@1",
        "flow.stop@1",
        "flow.fail@1",
        "flow.run_workflow@1",
        "flow.transform@1",
    }
    assert all(n["kind"] == "control" for n in nodes.values())


def test_control_contracts() -> None:
    n = _nodes(PLUGIN)
    assert n["flow.if@1"]["ports"] == ["true", "false"]
    assert n["flow.switch@1"]["dynamic_ports"] == "cases" and n["flow.switch@1"]["ports"] == ["default"]
    assert n["flow.loop@1"]["ports"] == ["body", "done"]
    assert n["flow.stop@1"]["ports"] == [] and n["flow.fail@1"]["ports"] == []
    loop = n["flow.loop@1"]["config_schema"]["properties"]
    assert loop["concurrency"][LITERAL] is True and loop["item_cap"]["maximum"] == 10_000
    assert n["flow.filter@1"]["config_schema"]["properties"]["predicate"][KINDS] == ["cel"]
    case = n["flow.switch@1"]["config_schema"]["$defs"]["SwitchCase"]["properties"]["port"]
    assert case[LITERAL] is True
    assert n["flow.run_workflow@1"]["config_schema"]["properties"]["workflow_id"][LITERAL] is True


def test_testkit_is_a_valid_plugin() -> None:
    nodes = _nodes(TESTKIT)
    assert nodes["testkit.ambiguous_send@1"]["side_effect"] == "ambiguous"
    assert nodes["testkit.sensitive@1"]["output_schema"]["properties"]["secret_value"][SENSITIVE] is True
    assert nodes["testkit.echo@1"]["output_schema"]["required"] == ["value"]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/plugins -q`
Expected: FAIL: `ImportError: cannot import name 'PLUGIN'`.

- [ ] **Step 3: Implement the flow plugin**

`backend/src/dewpoint/plugins/flow/nodes.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""Control nodes. The engine executes them itself (kind=CONTROL); these classes declare only their contract."""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from dewpoint.sdk import Node, NodeKind, literal_only, value_kinds


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class OpenOutput(BaseModel):
    """Output whose fields are defined per step (sub-flow outputs, transform fields)."""

    model_config = ConfigDict(extra="allow")


class _Control(Node):
    kind = NodeKind.CONTROL


class IfConfig(_Strict):
    condition: bool


class If(_Control):
    type = "flow.if"
    version = 1
    title = "If"
    description = "Continues on `true` or `false`."
    Config = IfConfig
    ports = ("true", "false")


class SwitchCase(_Strict):
    port: str = literal_only(pattern=r"^[a-z][a-z0-9_]{0,30}$")
    when: bool


class SwitchConfig(_Strict):
    cases: list[SwitchCase] = Field(min_length=1, max_length=20)


class Switch(_Control):
    type = "flow.switch"
    version = 1
    title = "Switch"
    description = "Continues on the first case whose condition holds, otherwise on `default`."
    Config = SwitchConfig
    ports = ("default",)
    dynamic_ports = "cases"


class LoopConfig(_Strict):
    items: list[Any]
    concurrency: int = literal_only(1, ge=1, le=10)
    item_cap: int = literal_only(10_000, ge=1, le=10_000)
    on_item_error: Literal["stop", "continue"] = literal_only("stop")
    collect: Any = None


class LoopFailure(BaseModel):
    index: int
    code: str
    message: str


class LoopOutput(BaseModel):
    items: list[Any]
    failures: list[LoopFailure]
    count: int


class Loop(_Control):
    type = "flow.loop"
    version = 1
    title = "Loop"
    description = "Runs the `body` region once per item, then continues on `done`."
    Config = LoopConfig
    Output = LoopOutput
    ports = ("body", "done")


class FilterConfig(_Strict):
    items: list[Any]
    predicate: bool = value_kinds("cel")


class FilterOutput(BaseModel):
    items: list[Any]
    count: int


class Filter(_Control):
    type = "flow.filter"
    version = 1
    title = "Filter"
    description = "Keeps the items for which the predicate holds. Each item is a separate evaluation."
    Config = FilterConfig
    Output = FilterOutput


class SetVariablesConfig(_Strict):
    assignments: dict[str, Any] = Field(min_length=1, max_length=50)


class SetVariables(_Control):
    type = "flow.set_variables"
    version = 1
    title = "Set variables"
    Config = SetVariablesConfig


class DelayConfig(_Strict):
    duration_s: int = Field(ge=0, le=30 * 86_400)


class Delay(_Control):
    type = "flow.delay"
    version = 1
    title = "Delay"
    Config = DelayConfig


class WaitUntilConfig(_Strict):
    until: datetime


class WaitUntil(_Control):
    type = "flow.wait_until"
    version = 1
    title = "Wait until"
    Config = WaitUntilConfig


class Stop(_Control):
    type = "flow.stop"
    version = 1
    title = "Stop"
    description = "Ends the run as succeeded."
    ports = ()


class FailConfig(_Strict):
    message: str = Field(min_length=1, max_length=500)


class Fail(_Control):
    type = "flow.fail"
    version = 1
    title = "Fail"
    description = "Ends the run as failed."
    Config = FailConfig
    ports = ()


class RunWorkflowConfig(_Strict):
    workflow_id: uuid.UUID = literal_only()
    input: dict[str, Any] = Field(default_factory=dict)


class RunWorkflow(_Control):
    type = "flow.run_workflow"
    version = 1
    title = "Run workflow"
    description = "Runs another workflow's version pinned at publish, and returns its outputs."
    Config = RunWorkflowConfig
    Output = OpenOutput


class TransformConfig(_Strict):
    fields: dict[str, Any] = Field(min_length=1, max_length=100)


class Transform(_Control):
    type = "flow.transform"
    version = 1
    title = "Transform"
    description = "Builds an object from values, references and expressions."
    Config = TransformConfig
    Output = OpenOutput


NODES: tuple[type[Node], ...] = (
    If,
    Switch,
    Loop,
    Filter,
    SetVariables,
    Delay,
    WaitUntil,
    Stop,
    Fail,
    RunWorkflow,
    Transform,
)
```

`backend/src/dewpoint/plugins/flow/__init__.py`:

```python
# SPDX-License-Identifier: Apache-2.0
from dewpoint.plugins.flow.nodes import NODES
from dewpoint.sdk import Plugin

PLUGIN = Plugin(name="flow", version="1.0.0", nodes=NODES)
```

Add to `backend/pyproject.toml`, after `[project.scripts]`:

```toml
[project.entry-points."dewpoint.plugins"]
flow = "dewpoint.plugins.flow:PLUGIN"
```

Then run `uv sync`, so the entry point is registered in the environment.

- [ ] **Step 4: Implement the testkit plugin**

`backend/tests/support/plugins/testkit.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""Engine test fixtures. Lives under tests/, so it is never packaged or registered in production."""

import asyncio
from typing import Any, Literal

from pydantic import BaseModel, Field

from dewpoint.sdk import (
    Empty,
    FatalError,
    Node,
    OutcomeUnknownError,
    Plugin,
    RetryableError,
    SideEffect,
    StepContext,
    sensitive,
)


class EchoConfig(BaseModel):
    value: Any = None


class EchoOutput(BaseModel):
    value: Any


class Echo(Node):
    type = "testkit.echo"
    version = 1
    title = "Echo"
    Config = EchoConfig
    Output = EchoOutput

    async def run(self, ctx: StepContext, config: EchoConfig) -> EchoOutput:
        return EchoOutput(value=config.value)


class FailNConfig(BaseModel):
    failures: int = Field(ge=0, le=10)


class FailN(Node):
    type = "testkit.fail_n"
    version = 1
    title = "Fail N times"
    Config = FailNConfig
    side_effect = SideEffect.IDEMPOTENT

    async def run(self, ctx: StepContext, config: FailNConfig) -> Empty:
        if ctx.attempt <= config.failures:
            raise RetryableError("testkit.transient", f"attempt {ctx.attempt} fails on purpose")
        return Empty()


class SlowConfig(BaseModel):
    seconds: float = Field(ge=0, le=600)


class Slow(Node):
    type = "testkit.slow"
    version = 1
    title = "Slow"
    Config = SlowConfig

    async def run(self, ctx: StepContext, config: SlowConfig) -> Empty:
        remaining = config.seconds
        while remaining > 0 and not ctx.cancelled:
            step = min(remaining, 1.0)
            await asyncio.sleep(step)
            remaining -= step
            ctx.heartbeat(remaining)
        return Empty()


class SensitiveOutput(BaseModel):
    public: str
    secret_value: str = sensitive()


class Sensitive(Node):
    type = "testkit.sensitive"
    version = 1
    title = "Sensitive"
    Output = SensitiveOutput

    async def run(self, ctx: StepContext, config: Empty) -> SensitiveOutput:
        return SensitiveOutput(public="visible", secret_value="s3cr3t-value")


class AmbiguousConfig(BaseModel):
    outcome: Literal["sent", "unknown", "rejected"] = "sent"


class AmbiguousSend(Node):
    type = "testkit.ambiguous_send"
    version = 1
    title = "Ambiguous send"
    Config = AmbiguousConfig
    side_effect = SideEffect.AMBIGUOUS

    async def run(self, ctx: StepContext, config: AmbiguousConfig) -> Empty:
        if config.outcome == "unknown":
            raise OutcomeUnknownError("testkit.timeout_after_send", "the request may have been delivered")
        if config.outcome == "rejected":
            raise FatalError("testkit.rejected", "the receiver rejected the request")
        return Empty()


TESTKIT = Plugin(name="testkit", version="0.0.0", nodes=(Echo, FailN, Slow, Sensitive, AmbiguousSend))
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/plugins -q`
Expected: 3 passed.

- [ ] **Step 6: Commit**

```bash
uv run ruff format . && uv run ruff check . && uv run mypy src && uv run lint-imports && uv run pytest tests/sdk tests/plugins -q && \
git add pyproject.toml uv.lock src/dewpoint/plugins tests/plugins tests/support/plugins && \
git commit -m "feat(plugins): flow control-node contracts and the test-only testkit plugin

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Canonical JSON and the manifest registry (engine side)

**Files:**
- Create: `backend/src/dewpoint/engine/canonical.py`, `backend/src/dewpoint/engine/schema_refs.py`, `backend/src/dewpoint/engine/cel/__init__.py`, `backend/src/dewpoint/engine/cel/profile.py`, `backend/src/dewpoint/engine/registry/__init__.py`, `backend/src/dewpoint/engine/registry/control.py`, `backend/src/dewpoint/engine/registry/catalog.py`
- Create: `backend/tests/support/catalog.py`
- Test: `backend/tests/engine/__init__.py`, `backend/tests/engine/registry/__init__.py`, `backend/tests/engine/registry/test_catalog.py`, `backend/tests/engine/test_schema_refs.py`

**Interfaces:**
- Consumes: `dewpoint.sdk.node.{TYPE_RE, PORT_RE, RESERVED_PORTS, NodeKind, SideEffect}`, `dewpoint.sdk.version.SDK_MAJOR`.
- Produces:
  - `canonical_json(value) -> bytes`, `sha256_hex(value) -> str`.
  - `CURRENT_CEL_PROFILE: str`.
  - `control.IF, SWITCH, LOOP, FILTER, SET_VARIABLES, DELAY, WAIT_UNTIL, STOP, FAIL, RUN_WORKFLOW, TRANSFORM` (refs such as `"flow.if@1"`), and `CONTROL_TYPES: frozenset[str]`.
  - `NodeTypeSpec(type, version, kind, title, ports, dynamic_ports, config_schema, output_schema, side_effect, state)` with `.ref`.
  - `spec_from_manifest(node_manifest, state="active")`.
  - `contract_hash(node_manifest) -> str`: covers **everything except display metadata**.
    - Display metadata is the manifest's `title` and `description`, plus these schema annotations: `title`, `description`, `examples`, `x-widget`, `x-group`.
    - Annotations are stripped only from schema objects, reached through schema-valued keywords (`schema_refs.SCHEMA_ONE`, `SCHEMA_LIST`, `SCHEMA_MAP`).
    - Every other value is hashed verbatim: `default`, `const`, `enum`, `required`, `dependentRequired` and vendor `x-*` keys. So a property called `title`, or `dependentRequired: {"title": [...]}`, stays part of the contract.
    - Credentials, capabilities, retry, timeout, ports, kind, side effect, schemas and the engine markers are all covered, as is any manifest key added later (unless it is explicitly declared display metadata).
  - `dewpoint.engine.schema_refs.ref_problems(schema) -> list[str]`: empty only when the schema passes the rules below. Only schema positions are inspected; data such as `default`, `const`, `enum`, `examples` and vendor keys never is.
    - every `$ref` is `#/$defs/<name>` and resolves;
    - there is no `$id`, `$anchor`, `$dynamicRef`, `$dynamicAnchor`, `$recursiveRef` or `$recursiveAnchor`;
    - no chain of definitions refers back to itself without descending into the data (through `$ref`, `allOf`, `anyOf`, `oneOf`, `not`, `if`/`then`/`else` or `dependentSchemas`).
  - `Catalog(specs)` with `.get(ref) -> NodeTypeSpec | None` and `.refs()`.
  - `validate_plugin_manifest(manifest) -> list[str]`. It **never raises** on malformed data: every field is type-checked before it is used.
    - `title` must be non-empty text.
    - `kind` and `side_effect` must be known strings.
    - `dynamic_ports` must be `null` or name a config field.
    - `retry` must be exactly `{max_attempts: 1–20, initial_interval_s: > 0, backoff: ≥ 1, max_interval_s: ≥ initial_interval_s, non_retryable: [codes]}`, with finite numbers.
    - `timeout_s` must be a positive, finite number.
  - Test helper `tests.support.catalog.catalog(*plugins, states=None) -> Catalog`.

- [ ] **Step 1: Write the failing test**

`backend/tests/engine/__init__.py` and `backend/tests/engine/registry/__init__.py`:

```python
# SPDX-License-Identifier: Apache-2.0
```

`backend/tests/engine/test_schema_refs.py`:

```python
# SPDX-License-Identifier: Apache-2.0
from typing import Any

import pytest

from dewpoint.engine.schema_refs import ref_problems

TREE = {
    "type": "object",
    "properties": {"root": {"$ref": "#/$defs/Node"}},
    "$defs": {
        "Node": {"type": "object", "properties": {"children": {"type": "array", "items": {"$ref": "#/$defs/Node"}}}}
    },
}


def test_local_and_structurally_recursive_refs_are_fine() -> None:
    assert ref_problems(TREE) == []
    assert ref_problems({"type": "object", "properties": {"title": {"type": "string"}}}) == []


@pytest.mark.parametrize(
    "schema",
    [
        {"type": "object", "default": {"$ref": "literal data"}},
        {"type": "object", "properties": {"x": {"const": {"$id": "not-an-id"}}}},
        {"type": "array", "items": {"enum": [{"$ref": "#/nowhere"}]}},
        {"type": "string", "examples": [{"$id": "x", "$ref": "y"}]},
        {"type": "object", "x-dewpoint-note": {"$ref": "vendor data"}},
        {"type": "object", "properties": {"$ref": {"type": "string"}, "$id": {"type": "string"}}},  # property names
        {"type": "object", "dependentRequired": {"$ref": ["x"]}},
    ],
)
def test_data_positions_are_never_treated_as_schemas(schema: dict[str, Any]) -> None:
    assert ref_problems(schema) == []


def test_every_schema_position_is_checked() -> None:
    bad = {"$ref": "https://example.com/s.json"}
    for schema in (
        {"items": bad},
        {"prefixItems": [bad]},
        {"additionalProperties": bad},
        {"patternProperties": {"^x": bad}},
        {"dependentSchemas": {"a": bad}},
        {"if": bad},
        {"unevaluatedProperties": bad},
        {"$defs": {"A": bad}},
    ):
        assert ref_problems(schema), schema


@pytest.mark.parametrize(
    ("schema", "fragment"),
    [
        ({"properties": {"x": {"$ref": "#/$defs/Missing"}}}, "must name an entry"),
        ({"properties": {"x": {"$ref": "https://example.com/s.json"}}}, "must name an entry"),
        ({"properties": {"x": {"$ref": "#"}}}, "must name an entry"),
        ({"$id": "https://example.com/s.json", "type": "object"}, "`$id` isn't supported"),
        ({"$defs": {"A": {"$dynamicAnchor": "a"}}}, "`$dynamicAnchor` isn't supported"),
        ({"$defs": {"A": {"$ref": "#/$defs/B"}, "B": {"$ref": "#/$defs/A"}}}, "cycle"),
        ({"$defs": {"A": {"allOf": [{"$ref": "#/$defs/A"}]}}}, "cycle"),
        ({"$defs": {"A": {"anyOf": [{"type": "string"}, {"not": {"$ref": "#/$defs/A"}}]}}}, "cycle"),
    ],
)
def test_unsupported_references_are_reported(schema: dict[str, Any], fragment: str) -> None:
    problems = ref_problems(schema)
    assert problems and any(fragment in p for p in problems), problems


def test_the_sdk_and_the_engine_agree_on_schema_positions() -> None:
    from dewpoint.engine import schema_refs
    from dewpoint.sdk import manifest

    assert (manifest.SCHEMA_ONE, manifest.SCHEMA_LIST, manifest.SCHEMA_MAP) == (
        schema_refs.SCHEMA_ONE,
        schema_refs.SCHEMA_LIST,
        schema_refs.SCHEMA_MAP,
    )
```

`backend/tests/engine/registry/test_catalog.py`:

```python
# SPDX-License-Identifier: Apache-2.0
import copy
from typing import Any

import pytest

from dewpoint.engine.canonical import canonical_json
from dewpoint.engine.registry.catalog import Catalog, contract_hash, spec_from_manifest, validate_plugin_manifest
from dewpoint.plugins.flow import PLUGIN
from tests.support.catalog import catalog
from tests.support.plugins.testkit import TESTKIT


def test_canonical_json_is_order_independent() -> None:
    assert canonical_json({"b": 1, "a": [2, {"d": 3, "c": 4}]}) == canonical_json({"a": [2, {"c": 4, "d": 3}], "b": 1})
    assert canonical_json({"é": 1}) == '{"é":1}'.encode()


def test_first_party_manifests_validate() -> None:
    assert validate_plugin_manifest(PLUGIN.manifest()) == []
    assert validate_plugin_manifest(TESTKIT.manifest()) == []


def test_manifest_problems_are_reported() -> None:
    m = copy.deepcopy(TESTKIT.manifest())
    m["nodes"][0]["kind"] = "control"
    m["nodes"][1]["config_schema"] = {"type": 5}
    m["nodes"].append(copy.deepcopy(m["nodes"][2]))
    m["sdk_version"] = "9.0.0"
    problems = validate_plugin_manifest(m)
    assert any("only engine control types" in p for p in problems)
    assert any("not a valid JSON Schema" in p for p in problems)
    assert any("duplicate node type version" in p for p in problems)
    assert any("built for SDK" in p for p in problems)


def test_flow_must_declare_every_control_type() -> None:
    m = copy.deepcopy(PLUGIN.manifest())
    m["nodes"] = [n for n in m["nodes"] if n["type"] != "flow.stop"]
    assert "flow: missing control type flow.stop@1" in validate_plugin_manifest(m)


ECHO = TESTKIT.manifest()["nodes"][0]


def _changed(path: tuple[str, ...], value: Any) -> dict[str, Any]:
    m = copy.deepcopy(ECHO)
    target = m
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    return m


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("credentials",), ["mist"]),
        (("capabilities",), ["mist.write"]),
        (("retry", "max_attempts"), 9),
        (("retry", "non_retryable"), ["testkit.bad"]),
        (("timeout_s",), 5.0),
        (("side_effect",), "keyed"),
        (("ports",), ["out", "other"]),
        (("dynamic_ports",), "value"),
        (("kind",), "control"),
        (("config_schema", "properties", "value", "type"), "string"),
        (("config_schema", "properties", "value", "x-dewpoint-literal"), True),
        (("output_schema", "properties", "value", "x-sensitive"), True),
        (("config_schema", "properties", "title"), {"type": "string"}),  # a *property* named title is contract
    ],
)
def test_contract_hash_covers_everything_that_changes_behaviour(path: tuple[str, ...], value: Any) -> None:
    assert contract_hash(_changed(path, value)) != contract_hash(ECHO)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("title",), "Echo (renamed)"),
        (("description",), "Returns its input."),
        (("config_schema", "properties", "value", "title"), "Payload"),
        (("config_schema", "properties", "value", "description"), "Any JSON value."),
        (("config_schema", "properties", "value", "examples"), [1, "a"]),
        (("config_schema", "properties", "value", "x-widget"), "pill-text"),
    ],
)
def test_display_metadata_is_not_part_of_the_contract(path: tuple[str, ...], value: Any) -> None:
    assert contract_hash(_changed(path, value)) == contract_hash(ECHO)


@pytest.mark.parametrize(
    ("path", "before", "after"),
    [
        (("config_schema", "dependentRequired"), {"title": ["value"]}, {"title": ["other"]}),
        (("config_schema", "properties", "value", "default"), {"title": "a"}, {"title": "b"}),
        (("config_schema", "properties", "value", "const"), {"description": "a"}, {"description": "b"}),
        (("config_schema", "properties", "value", "enum"), [{"title": "a"}], [{"title": "b"}]),
        (("config_schema", "x-dewpoint-note"), {"title": "a"}, {"title": "b"}),
    ],
)
def test_annotation_names_inside_data_are_part_of_the_contract(path: tuple[str, ...], before: Any, after: Any) -> None:
    assert contract_hash(_changed(path, before)) != contract_hash(_changed(path, after))


@pytest.mark.parametrize(
    ("field", "value", "fragment"),
    [
        ("kind", ["action"], "unknown kind"),
        ("side_effect", {"none": True}, "unknown side_effect"),
        ("title", None, "title must be non-empty text"),
        ("dynamic_ports", ["value"], "dynamic_ports must name a config field"),
        ("dynamic_ports", "nope", "dynamic_ports must name a config field"),
        ("retry", "fast", "retry must be"),
        ("retry", {**ECHO["retry"], "max_attempts": 0}, "retry must be"),
        ("retry", {**ECHO["retry"], "initial_interval_s": 0}, "retry must be"),
        ("retry", {**ECHO["retry"], "backoff": 0}, "retry must be"),
        ("retry", {**ECHO["retry"], "backoff": float("nan")}, "retry must be"),
        ("retry", {**ECHO["retry"], "max_interval_s": 0.5}, "retry must be"),
        ("retry", {**ECHO["retry"], "non_retryable": "testkit.bad"}, "retry must be"),
        ("retry", {**ECHO["retry"], "jitter": 1}, "retry must be"),
    ],
)
def test_malformed_manifest_fields_are_problems_not_exceptions(field: str, value: Any, fragment: str) -> None:
    m = copy.deepcopy(TESTKIT.manifest())
    m["nodes"][0][field] = value
    problems = validate_plugin_manifest(m)
    assert any(fragment in p for p in problems), problems


def test_manifest_schemas_must_use_resolvable_local_refs() -> None:
    m = copy.deepcopy(TESTKIT.manifest())
    m["nodes"][0]["config_schema"]["properties"]["value"] = {"$ref": "https://example.com/value.json"}
    assert any("must name an entry" in p for p in validate_plugin_manifest(m))


def test_catalog_lookup_and_states() -> None:
    cat = Catalog(spec_from_manifest(n, "deprecated") for n in TESTKIT.manifest()["nodes"])
    spec = cat.get("testkit.echo@1")
    assert spec is not None and spec.state == "deprecated" and spec.ref == "testkit.echo@1"
    assert cat.get("testkit.echo@2") is None
    both = catalog(PLUGIN, TESTKIT, states={"flow.if@1": "retired"})
    if_spec = both.get("flow.if@1")
    assert if_spec is not None and if_spec.state == "retired" and if_spec.ports == ("true", "false")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/engine -q`
Expected: FAIL: `ModuleNotFoundError: No module named 'dewpoint.engine.canonical'` (or `schema_refs`).

- [ ] **Step 3: Implement**

`backend/src/dewpoint/engine/schema_refs.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""Dewpoint supports only local `$ref`s (`#/$defs/<name>`) that resolve, and no reference chain that recurses without
descending into the data. Anything else would make validation depend on base-URI rules, network fetches or unbounded
recursion, so it is reported as a problem instead of raising during validation."""

from collections.abc import Iterator, Mapping
from typing import Any

PREFIX = "#/$defs/"
UNSUPPORTED = ("$id", "$anchor", "$dynamicRef", "$dynamicAnchor", "$recursiveRef", "$recursiveAnchor")
_SAME_INSTANCE_LISTS = ("allOf", "anyOf", "oneOf")
_SAME_INSTANCE_ONE = ("not", "if", "then", "else")

# Schema positions (JSON Schema 2020-12): the only keywords whose values are schemas. Everything else is data or a
# non-schema keyword (`default`, `const`, `enum`, `examples`, `required`, `dependentRequired`, vendor `x-*` keys, ...)
# and must be treated verbatim: never searched for `$ref`, never stripped of annotation-like names.
SCHEMA_ONE = frozenset(
    {
        "additionalProperties",
        "items",
        "contains",
        "propertyNames",
        "not",
        "if",
        "then",
        "else",
        "unevaluatedItems",
        "unevaluatedProperties",
        "contentSchema",
    }
)
SCHEMA_LIST = frozenset({"allOf", "anyOf", "oneOf", "prefixItems"})
SCHEMA_MAP = frozenset({"properties", "patternProperties", "$defs", "dependentSchemas"})


def subschemas(schema: Mapping[str, Any]) -> Iterator[tuple[str, Any]]:
    """(relative JSON pointer, subschema) for every schema-valued keyword of `schema`, and nothing else."""
    for key, value in schema.items():
        if key in SCHEMA_ONE:
            yield f"/{key}", value
        elif key in SCHEMA_LIST and isinstance(value, list):
            for index, sub in enumerate(value):
                yield f"/{key}/{index}", sub
        elif key in SCHEMA_MAP and isinstance(value, Mapping):
            for name, sub in value.items():
                yield f"/{key}/{name}", sub


def _same_instance_refs(node: Any) -> set[str]:
    """Definitions applied to the *same* instance as `node`, so recursion through them consumes no data."""
    if not isinstance(node, Mapping):
        return set()
    out: set[str] = set()
    ref = node.get("$ref")
    if isinstance(ref, str) and ref.startswith(PREFIX):
        out.add(ref[len(PREFIX) :])
    for key in _SAME_INSTANCE_LISTS:
        value = node.get(key)
        if isinstance(value, list):
            for sub in value:
                out |= _same_instance_refs(sub)
    for key in _SAME_INSTANCE_ONE:
        out |= _same_instance_refs(node.get(key))
    dependent = node.get("dependentSchemas")
    if isinstance(dependent, Mapping):
        for sub in dependent.values():
            out |= _same_instance_refs(sub)
    return out


def ref_problems(schema: Any) -> list[str]:
    if not isinstance(schema, Mapping):
        return []
    defs = schema.get("$defs", {})
    if not isinstance(defs, Mapping):
        return ["`$defs` must be an object"]
    problems: list[str] = []

    def walk(node: Any, path: str) -> None:
        if not isinstance(node, Mapping):
            return  # a boolean schema
        for key in UNSUPPORTED:
            if key in node:
                problems.append(f"{path or '/'}: `{key}` isn't supported")
        if "$ref" in node:
            ref = node["$ref"]
            if not isinstance(ref, str) or not ref.startswith(PREFIX) or ref[len(PREFIX) :] not in defs:
                problems.append(f"{path or '/'}: `$ref` must name an entry of this schema's `$defs` (#/$defs/<name>)")
        for suffix, sub in subschemas(node):  # schema positions only: data such as `default` is never inspected
            walk(sub, path + suffix)

    walk(schema, "")
    if problems:
        return problems
    edges = {name: _same_instance_refs(sub) for name, sub in defs.items()}
    state: dict[str, int] = {}  # 1 = on the current path, 2 = finished

    def cyclic(name: str) -> bool:
        if state.get(name) == 1:
            return True
        if state.get(name) == 2:
            return False
        state[name] = 1
        found = any(cyclic(target) for target in sorted(edges.get(name, ())))
        state[name] = 2
        return found

    for name in sorted(defs):
        if cyclic(name):
            return [f"/$defs/{name}: `$ref` cycle that never descends into the data"]
    return []
```

`backend/src/dewpoint/engine/canonical.py`:

```python
# SPDX-License-Identifier: Apache-2.0
import hashlib
import json
from typing import Any


def canonical_json(value: Any) -> bytes:
    """Sorted keys, no whitespace, UTF-8, no NaN/Infinity: equal values always give equal bytes."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def sha256_hex(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()
```

`backend/src/dewpoint/engine/cel/__init__.py`:

```python
# SPDX-License-Identifier: Apache-2.0
```

`backend/src/dewpoint/engine/cel/profile.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""The CEL profile this build publishes with (spec §5.1): runtime pin / function library / classifier rules."""

CURRENT_CEL_PROFILE = "cel-cpp-0.1.3/fn-1/cls-1"
```

`backend/src/dewpoint/engine/registry/__init__.py`:

```python
# SPDX-License-Identifier: Apache-2.0
```

`backend/src/dewpoint/engine/registry/control.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""Control node types the engine executes itself. Only the `flow` plugin may declare kind=control."""

IF = "flow.if@1"
SWITCH = "flow.switch@1"
LOOP = "flow.loop@1"
FILTER = "flow.filter@1"
SET_VARIABLES = "flow.set_variables@1"
DELAY = "flow.delay@1"
WAIT_UNTIL = "flow.wait_until@1"
STOP = "flow.stop@1"
FAIL = "flow.fail@1"
RUN_WORKFLOW = "flow.run_workflow@1"
TRANSFORM = "flow.transform@1"

CONTROL_TYPES = frozenset(
    {IF, SWITCH, LOOP, FILTER, SET_VARIABLES, DELAY, WAIT_UNTIL, STOP, FAIL, RUN_WORKFLOW, TRANSFORM}
)
```

`backend/src/dewpoint/engine/registry/catalog.py`:

```python
# SPDX-License-Identifier: Apache-2.0
import math
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, TypeGuard

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from dewpoint.engine.canonical import sha256_hex
from dewpoint.engine.registry.control import CONTROL_TYPES
from dewpoint.engine.schema_refs import SCHEMA_LIST, SCHEMA_MAP, SCHEMA_ONE, ref_problems
from dewpoint.sdk.node import MAX_RETRY_ATTEMPTS, PORT_RE, RESERVED_PORTS, TYPE_RE, NodeKind, SideEffect
from dewpoint.sdk.version import SDK_MAJOR

_DISPLAY = frozenset({"title", "description"})  # manifest keys that may change within a version
_SCHEMA_ANNOTATIONS = frozenset({"title", "description", "examples", "x-widget", "x-group"})
_KINDS = {k.value for k in NodeKind}
_SIDE_EFFECTS = {s.value for s in SideEffect}


@dataclass(frozen=True)
class NodeTypeSpec:
    type: str
    version: int
    kind: str
    title: str
    ports: tuple[str, ...]
    dynamic_ports: str | None
    config_schema: Mapping[str, Any]
    output_schema: Mapping[str, Any]
    side_effect: str
    state: str = "active"

    @property
    def ref(self) -> str:
        return f"{self.type}@{self.version}"


def spec_from_manifest(m: Mapping[str, Any], state: str = "active") -> NodeTypeSpec:
    return NodeTypeSpec(
        type=m["type"],
        version=int(m["version"]),
        kind=m["kind"],
        title=m["title"],
        ports=tuple(m["ports"]),
        dynamic_ports=m.get("dynamic_ports"),
        config_schema=m["config_schema"],
        output_schema=m["output_schema"],
        side_effect=m["side_effect"],
        state=state,
    )


def _schema_contract(schema: Any) -> Any:
    """A schema without display annotations. Annotations are dropped only from schema objects, and only schema-valued
    keywords are traversed. Every other value (`default`, `const`, `enum`, `required`, `dependentRequired`, vendor
    `x-*` keys, ...) is kept verbatim, so `dependentRequired: {"title": [...]}` or a property named `title` stays part
    of the contract."""
    if not isinstance(schema, Mapping):
        return schema  # a boolean schema, or a malformed value: hashed verbatim
    out: dict[str, Any] = {}
    for key, value in schema.items():
        if key in _SCHEMA_ANNOTATIONS:
            continue
        if key in SCHEMA_ONE:
            out[key] = _schema_contract(value)
        elif key in SCHEMA_LIST and isinstance(value, list):
            out[key] = [_schema_contract(sub) for sub in value]
        elif key in SCHEMA_MAP and isinstance(value, Mapping):
            out[key] = {name: _schema_contract(sub) for name, sub in value.items()}
        else:
            out[key] = value
    return out


def contract_hash(m: Mapping[str, Any]) -> str:
    """Identity of a node type version's execution contract: every manifest field except display metadata.
    Published versions depend on it, so a registered version's contract may never change (sync refuses)."""
    contract = {k: v for k, v in m.items() if k not in _DISPLAY}
    for key in ("config_schema", "output_schema"):
        contract[key] = _schema_contract(m.get(key))
    return sha256_hex(contract)


class Catalog:
    def __init__(self, specs: Iterable[NodeTypeSpec]) -> None:
        self._by_ref = {s.ref: s for s in specs}

    def get(self, ref: str) -> NodeTypeSpec | None:
        return self._by_ref.get(ref)

    def refs(self) -> list[str]:
        return sorted(self._by_ref)


def _schema_problems(ref: str, label: str, schema: Any) -> list[str]:
    if not isinstance(schema, dict):
        return [f"{ref}: {label} must be an object"]
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as e:
        return [f"{ref}: {label} is not a valid JSON Schema ({e.message})"]
    if schema.get("type") != "object":
        return [f"{ref}: {label} must describe an object"]
    return [f"{ref}: {label}: {p}" for p in ref_problems(schema)]


_RETRY_KEYS = frozenset({"max_attempts", "initial_interval_s", "backoff", "max_interval_s", "non_retryable"})


def _finite(value: Any) -> TypeGuard[int | float]:
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)


def _retry_problems(ref: str, retry: Any) -> list[str]:
    """The same rules the SDK applies to RetryDefaults, for manifests received as data."""
    usable = (
        isinstance(retry, Mapping)
        and set(retry) == _RETRY_KEYS
        and isinstance(retry["max_attempts"], int)
        and not isinstance(retry["max_attempts"], bool)
        and 1 <= retry["max_attempts"] <= MAX_RETRY_ATTEMPTS
        and _finite(retry["initial_interval_s"])
        and retry["initial_interval_s"] > 0
        and _finite(retry["backoff"])
        and retry["backoff"] >= 1
        and _finite(retry["max_interval_s"])
        and retry["max_interval_s"] >= retry["initial_interval_s"]
        and isinstance(retry["non_retryable"], list)
        and all(isinstance(code, str) and code for code in retry["non_retryable"])
    )
    if usable:
        return []
    return [
        f"{ref}: retry must be {{max_attempts: 1-{MAX_RETRY_ATTEMPTS}, initial_interval_s: > 0, backoff: ≥ 1, "
        "max_interval_s: ≥ initial_interval_s, non_retryable: [error codes]}"
    ]


def _dynamic_ports_problems(ref: str, n: Mapping[str, Any]) -> list[str]:
    field = n.get("dynamic_ports")
    if field is None:
        return []
    schema = n.get("config_schema")
    props = schema.get("properties") if isinstance(schema, Mapping) else None
    if isinstance(field, str) and isinstance(props, Mapping) and field in props:
        return []
    return [f"{ref}: dynamic_ports must name a config field"]


def _node_problems(plugin: str, n: Mapping[str, Any], seen: set[str]) -> list[str]:
    t, v = n.get("type"), n.get("version")
    ref = f"{t}@{v}"
    if not isinstance(t, str) or not TYPE_RE.match(t) or not t.startswith(f"{plugin}."):
        return [f"{ref}: type must start with '{plugin}.'"]
    out: list[str] = []
    if isinstance(v, bool) or not isinstance(v, int) or v < 1:
        out.append(f"{ref}: version must be an integer ≥ 1")
    if ref in seen:
        out.append(f"{ref}: duplicate node type version")
    seen.add(ref)
    title = n.get("title")
    if not isinstance(title, str) or not title:
        out.append(f"{ref}: title must be non-empty text")
    kind = n.get("kind")
    if not isinstance(kind, str) or kind not in _KINDS:  # type first: a list or dict is unhashable
        out.append(f"{ref}: unknown kind {kind!r}")
    elif kind == NodeKind.CONTROL and ref not in CONTROL_TYPES:
        out.append(f"{ref}: only engine control types may use kind 'control'")
    ports = n.get("ports")
    if (
        not isinstance(ports, list)
        or len(set(map(str, ports))) != len(ports)
        or any(not isinstance(p, str) or not PORT_RE.match(p) or p in RESERVED_PORTS for p in ports)
    ):
        out.append(f"{ref}: invalid ports")
    side_effect = n.get("side_effect")
    if not isinstance(side_effect, str) or side_effect not in _SIDE_EFFECTS:
        out.append(f"{ref}: unknown side_effect {side_effect!r}")
    out += _schema_problems(ref, "config_schema", n.get("config_schema"))
    out += _schema_problems(ref, "output_schema", n.get("output_schema"))
    out += _dynamic_ports_problems(ref, n)
    out += _retry_problems(ref, n.get("retry"))
    timeout = n.get("timeout_s")
    if not _finite(timeout) or timeout <= 0:
        out.append(f"{ref}: timeout_s must be a positive number")
    return out


def validate_plugin_manifest(m: Mapping[str, Any]) -> list[str]:
    """Checks a plugin manifest received as data. The SDK already checked first-party classes."""
    name = m.get("name")
    if not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,40}", name):
        return ["plugin name must be a lowercase identifier"]
    problems: list[str] = []
    if str(m.get("sdk_version", "")).split(".", 1)[0] != SDK_MAJOR:
        problems.append(f"{name}: built for SDK {m.get('sdk_version')!r}; this build provides SDK {SDK_MAJOR}.x")
    nodes = m.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        return [*problems, f"{name}: declares no nodes"]
    seen: set[str] = set()
    for n in nodes:
        problems += _node_problems(name, n if isinstance(n, Mapping) else {}, seen)
    if name == "flow":
        problems += [f"flow: missing control type {ref}" for ref in sorted(CONTROL_TYPES - seen)]
    return problems
```

`backend/tests/support/catalog.py`:

```python
# SPDX-License-Identifier: Apache-2.0
from dewpoint.engine.registry.catalog import Catalog, spec_from_manifest
from dewpoint.sdk import Plugin


def catalog(*plugins: Plugin, states: dict[str, str] | None = None) -> Catalog:
    wanted = states or {}
    return Catalog(
        spec_from_manifest(n, wanted.get(f"{n['type']}@{n['version']}", "active"))
        for p in plugins
        for n in p.manifest()["nodes"]
    )
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/engine -q`
Expected: all passed.

- [ ] **Step 5: Commit**

```bash
uv run ruff format . && uv run ruff check . && uv run mypy src && uv run lint-imports && uv run pytest tests/engine tests/plugins -q && \
git add src/dewpoint/engine tests/engine tests/support/catalog.py && \
git commit -m "feat(engine): canonical JSON, contract hashing, local-ref rules and manifest registry checks

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Graph model and structural analysis

**Files:**
- Create: `backend/src/dewpoint/engine/graph/{__init__,diagnostics,model,structure}.py`
- Create: `backend/tests/support/graphs.py`
- Test: `backend/tests/engine/graph/__init__.py`, `backend/tests/engine/graph/test_model.py`, `backend/tests/engine/graph/test_structure.py`

**Interfaces:**
- Consumes: `Catalog`, `NodeTypeSpec`, `control.LOOP` (Task 3); `canonical.sha256_hex`; `sdk.node.PORT_RE`, `RESERVED_PORTS`.
- Produces:
  - `Diagnostic(code, message, node=None, field=None, fix=None, severity="error")` with `.to_json()`; `Severity`.
  - Graph model:
    - `Graph(graph_format=1, nodes: tuple[GraphNode], edges: tuple[Edge], settings: GraphSettings)`;
    - `GraphNode(id, key, type, config, position, options: Options(timeout_s, max_attempts, on_error: fail|continue|port))`;
    - `Edge(source: EdgeFrom(node, port="out") [JSON alias "from"], to: EdgeTo(node))`;
    - `GraphSettings(input_schema, vars_schema, outputs, failure_handler: UUID | None)`.
  - Functions: `parse_graph(data) -> Graph`, which raises `GraphFormatError(diagnostics)`; `graph_json(graph) -> dict`.
  - Hashes:
    - `graph_hash(graph) -> str` identifies **the authored graph only**;
    - `version_hash(*, graph_hash, subflow_pins, failure_handler_version_id, cel_profile, engine_abi) -> str` identifies an **executable version**: the graph plus everything publish resolves. Audit and integrity checks use this one.
  - Constants: `MAX_NODES = 500`, `MAX_EDGES = 2000`.
  - `analyze_structure(graph, catalog) -> tuple[Structure | None, list[Diagnostic]]`.
    - `Structure` fields: `nodes`, `specs`, `ports` (normal ports: static, then dynamic), `out_edges`, `in_edges`, `topo`, `regions: {loop_id | None: Region(loop, parent, members, depth)}`, `region_of`, `by_key`, and `.chain(region)`.
    - Constants: `MAX_LOOP_DEPTH = 3`, `ERROR_PORT = "error"`.
  - Test helpers (`tests/support/graphs.py`): `G` builder (`.node(key, type_ref, config=None, on_error="fail")`, `.edge(src, dst, port="out")`, `.settings`, `.data()`, `.build()`), `nid(key)`, `ref(path, **extra)`, `cel(expr)`, `template(*parts)`.
- Diagnostic codes introduced:
  - graph: `graph.format`, `graph.duplicate_id`, `graph.duplicate_key`, `graph.cycle`;
  - nodes and edges: `node.unknown_type`, `node.dynamic_ports`, `node.error_port_unconnected`, `edge.unknown_node`, `edge.unknown_port`, `edge.self`, `edge.duplicate`;
  - loops: `loop.empty_body`, `loop.region_crossing`, `loop.region_entry`, `loop.too_deep`;
  - lifecycle: `lifecycle.deprecated`, `lifecycle.retired`.

- [ ] **Step 1: Write the test helper and failing tests**

`backend/tests/engine/graph/__init__.py`:

```python
# SPDX-License-Identifier: Apache-2.0
```

`backend/tests/support/graphs.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""A tiny graph builder for tests. Node ids derive from keys, so tests refer to nodes by key."""

import uuid
from typing import Any

from dewpoint.engine.graph.model import Graph, parse_graph

NS = uuid.UUID("8f5a3c1e-7d2b-4e6a-9c0d-5b1f2e3a4c6d")


def nid(key: str) -> uuid.UUID:
    return uuid.uuid5(NS, key)


class G:
    def __init__(self) -> None:
        self.nodes: list[dict[str, Any]] = []
        self.edges: list[dict[str, Any]] = []
        self.settings: dict[str, Any] = {}

    def node(self, key: str, type_ref: str, config: dict[str, Any] | None = None, on_error: str = "fail") -> "G":
        self.nodes.append(
            {"id": str(nid(key)), "key": key, "type": type_ref, "config": config or {}, "options": {"on_error": on_error}}
        )
        return self

    def edge(self, src: str, dst: str, port: str = "out") -> "G":
        self.edges.append({"from": {"node": str(nid(src)), "port": port}, "to": {"node": str(nid(dst))}})
        return self

    def data(self) -> dict[str, Any]:
        return {"graph_format": 1, "nodes": self.nodes, "edges": self.edges, "settings": self.settings}

    def build(self) -> Graph:
        return parse_graph(self.data())


def ref(path: str, **extra: Any) -> dict[str, Any]:
    return {"$value": {"kind": "ref", "path": path, **extra}}


def cel(expr: str) -> dict[str, Any]:
    return {"$value": {"kind": "cel", "expr": expr}}


def template(*parts: str | dict[str, Any]) -> dict[str, Any]:
    return {"$value": {"kind": "template", "parts": [{"text": p} if isinstance(p, str) else p for p in parts]}}
```

`backend/tests/engine/graph/test_model.py`:

```python
# SPDX-License-Identifier: Apache-2.0
from typing import Any

import pytest

from dewpoint.engine.graph.model import MAX_NODES, GraphFormatError, graph_hash, graph_json, parse_graph, version_hash
from tests.support.graphs import G, nid


def test_round_trip_keeps_the_from_alias() -> None:
    g = G().node("a", "testkit.echo@1").node("b", "testkit.echo@1").edge("a", "b").build()
    data = graph_json(g)
    assert data["edges"][0]["from"] == {"node": str(nid("a")), "port": "out"}
    assert parse_graph(data) == g


def test_graph_hash_is_stable_and_sensitive() -> None:
    a = G().node("a", "testkit.echo@1", {"value": 1}).build()
    b = G().node("a", "testkit.echo@1", {"value": 1}).build()
    c = G().node("a", "testkit.echo@1", {"value": 2}).build()
    assert graph_hash(a) == graph_hash(b) != graph_hash(c)


def test_version_hash_covers_what_publish_resolves() -> None:
    base: dict[str, Any] = {
        "graph_hash": "g",
        "subflow_pins": {"node": "v1"},
        "failure_handler_version_id": None,
        "cel_profile": "p",
        "engine_abi": 1,
    }
    h = version_hash(**base)
    for change in (
        {"graph_hash": "g2"},
        {"subflow_pins": {"node": "v2"}},
        {"failure_handler_version_id": "f"},
        {"cel_profile": "p2"},
        {"engine_abi": 2},
    ):
        assert version_hash(**{**base, **change}) != h, change


@pytest.mark.parametrize(
    ("data", "field"),
    [
        ({"graph_format": 2}, "/graph_format"),
        ({"nodes": [{"id": str(nid("a")), "key": "Bad Key", "type": "testkit.echo@1"}]}, "/nodes/0/key"),
        ({"nodes": [{"id": str(nid("a")), "key": "a", "type": "testkit.echo"}]}, "/nodes/0/type"),
        ({"surprise": True}, "/surprise"),
    ],
)
def test_format_errors_point_at_the_field(data: dict[str, Any], field: str) -> None:
    with pytest.raises(GraphFormatError) as e:
        parse_graph(data)
    assert [d.field for d in e.value.diagnostics] == [field]
    assert all(d.code == "graph.format" for d in e.value.diagnostics)


def test_node_count_is_capped() -> None:
    g = G()
    for i in range(MAX_NODES + 1):
        g.node(f"n{i}", "testkit.echo@1")
    with pytest.raises(GraphFormatError):
        g.build()
```

`backend/tests/engine/graph/test_structure.py`:

```python
# SPDX-License-Identifier: Apache-2.0
from dewpoint.engine.graph.model import Graph
from dewpoint.engine.graph.structure import analyze_structure
from dewpoint.engine.registry.catalog import Catalog
from dewpoint.plugins.flow import PLUGIN
from tests.support.catalog import catalog
from tests.support.graphs import G, nid
from tests.support.plugins.testkit import TESTKIT

CAT = catalog(PLUGIN, TESTKIT)
ECHO = "testkit.echo@1"
LOOP = "flow.loop@1"


def codes(graph: Graph, cat: Catalog = CAT) -> list[str]:
    return [d.code for d in analyze_structure(graph, cat)[1]]


def test_linear_graph() -> None:
    s, diags = analyze_structure(G().node("b", ECHO).node("a", ECHO).edge("a", "b").build(), CAT)
    assert diags == [] and s is not None
    assert s.topo == (nid("a"), nid("b"))
    assert s.regions[None].members == (nid("a"), nid("b"))


def test_duplicate_key() -> None:
    g = G().node("a", ECHO).node("b", ECHO)
    g.nodes[1]["key"] = "a"
    assert codes(g.build()) == ["graph.duplicate_key"]


def test_unknown_type_stops_analysis() -> None:
    s, diags = analyze_structure(G().node("a", "testkit.nope@1").build(), CAT)
    assert s is None and [d.code for d in diags] == ["node.unknown_type"]


def test_ports_and_error_routing() -> None:
    assert codes(G().node("a", ECHO).node("b", ECHO).edge("a", "b", "true").build()) == ["edge.unknown_port"]
    assert codes(G().node("a", ECHO).node("b", ECHO).edge("a", "b", "error").build()) == ["edge.unknown_port"]
    assert codes(G().node("a", ECHO, on_error="port").build()) == ["node.error_port_unconnected"]
    assert codes(G().node("a", ECHO, on_error="port").node("h", ECHO).edge("a", "h", "error").build()) == []


def test_cycle_is_rejected() -> None:
    s, diags = analyze_structure(G().node("a", ECHO).node("b", ECHO).edge("a", "b").edge("b", "a").build(), CAT)
    assert s is None and [d.code for d in diags] == ["graph.cycle"]


def test_switch_dynamic_ports() -> None:
    cases = [{"port": "high", "when": True}, {"port": "low", "when": False}]
    s, diags = analyze_structure(G().node("sw", "flow.switch@1", {"cases": cases}).build(), CAT)
    assert diags == [] and s is not None and s.ports[nid("sw")] == ("default", "high", "low")
    dup = [{"port": "high", "when": True}, {"port": "high", "when": False}]
    assert codes(G().node("sw", "flow.switch@1", {"cases": dup}).build()) == ["node.dynamic_ports"]
    computed = {"$value": {"kind": "ref", "path": "trigger.cases"}}
    assert codes(G().node("sw", "flow.switch@1", {"cases": computed}).build()) == ["node.dynamic_ports"]


def test_nested_loop_regions() -> None:
    g = (
        G()
        .node("outer", LOOP, {"items": [1, 2]})
        .node("inner", LOOP, {"items": [3]})
        .node("x", ECHO)
        .node("y", ECHO)
        .node("z", ECHO)
        .edge("outer", "inner", "body")
        .edge("inner", "x", "body")
        .edge("inner", "y", "done")
        .edge("outer", "z", "done")
    )
    s, diags = analyze_structure(g.build(), CAT)
    assert diags == [] and s is not None
    assert s.region_of[nid("inner")] == nid("outer")
    assert s.region_of[nid("x")] == nid("inner") and s.region_of[nid("y")] == nid("outer")
    assert s.region_of[nid("z")] is None
    assert s.chain(nid("inner")) == [nid("inner"), nid("outer"), None]
    assert s.regions[nid("inner")].depth == 2


def test_region_entry_from_outside_is_rejected() -> None:
    g = (
        G()
        .node("l", LOOP, {"items": [1]})
        .node("a", ECHO)
        .node("c", ECHO)
        .edge("l", "a", "body")
        .edge("a", "c")
        .edge("l", "c", "done")
    )
    assert codes(g.build()) == ["loop.region_entry"]


def test_crossing_regions_are_rejected() -> None:
    g = (
        G()
        .node("l1", LOOP, {"items": [1]})
        .node("l2", LOOP, {"items": [1]})
        .node("a", ECHO)
        .node("b", ECHO)
        .node("m", ECHO)
        .edge("l1", "a", "body")
        .edge("l2", "b", "body")
        .edge("a", "m")
        .edge("b", "m")
    )
    assert "loop.region_crossing" in codes(g.build())


def test_loop_depth_is_capped() -> None:
    g = G()
    for i in range(4):
        g.node(f"l{i}", LOOP, {"items": [1]})
    g.node("leaf", ECHO)
    for i in range(3):
        g.edge(f"l{i}", f"l{i + 1}", "body")
    g.edge("l3", "leaf", "body")
    assert codes(g.build()) == ["loop.too_deep"]


def test_lifecycle_states_are_reported() -> None:
    cat = catalog(PLUGIN, TESTKIT, states={ECHO: "deprecated", "testkit.slow@1": "retired"})
    g = G().node("a", ECHO).node("b", "testkit.slow@1", {"seconds": 1}).build()
    assert codes(g, cat) == ["lifecycle.deprecated", "lifecycle.retired"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/engine/graph -q`
Expected: FAIL: `ModuleNotFoundError: No module named 'dewpoint.engine.graph'`.

- [ ] **Step 3: Implement the model**

`backend/src/dewpoint/engine/graph/__init__.py`:

```python
# SPDX-License-Identifier: Apache-2.0
```

`backend/src/dewpoint/engine/graph/diagnostics.py`:

```python
# SPDX-License-Identifier: Apache-2.0
import uuid
from dataclasses import dataclass
from typing import Any, Literal

Severity = Literal["error", "warning"]


@dataclass(frozen=True)
class Diagnostic:
    """One validation finding. `code` is stable and documented; `message` is shown to the author."""

    code: str
    message: str
    node: uuid.UUID | None = None
    field: str | None = None  # JSON pointer inside the node's config, or /settings/...
    fix: str | None = None
    severity: Severity = "error"

    def to_json(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "node": str(self.node) if self.node else None,
            "field": self.field,
            "fix": self.fix,
            "severity": self.severity,
        }
```

`backend/src/dewpoint/engine/graph/model.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""The workflow graph document (`graph_format: 1`)."""

import uuid
from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from dewpoint.engine.canonical import sha256_hex
from dewpoint.engine.graph.diagnostics import Diagnostic

KEY_PATTERN = r"^[a-z][a-z0-9_]{0,62}$"
TYPE_REF_PATTERN = r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+@[1-9][0-9]{0,3}$"
PORT_PATTERN = r"^[a-z][a-z0-9_]{0,30}$"
MAX_NODES = 500
MAX_EDGES = 2000


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Position(_Strict):
    x: float = 0
    y: float = 0


class Options(_Strict):
    timeout_s: float | None = Field(default=None, gt=0, le=86_400)
    max_attempts: int | None = Field(default=None, ge=1, le=20)
    on_error: Literal["fail", "continue", "port"] = "fail"


class GraphNode(_Strict):
    id: uuid.UUID
    key: str = Field(pattern=KEY_PATTERN)
    type: str = Field(pattern=TYPE_REF_PATTERN)
    config: dict[str, Any] = Field(default_factory=dict)
    position: Position = Field(default_factory=Position)
    options: Options = Field(default_factory=Options)


class EdgeFrom(_Strict):
    node: uuid.UUID
    port: str = Field(default="out", pattern=PORT_PATTERN)


class EdgeTo(_Strict):
    node: uuid.UUID


class Edge(_Strict):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    source: EdgeFrom = Field(alias="from")
    to: EdgeTo


def _object_schema() -> dict[str, Any]:
    return {"type": "object"}


def _vars_schema() -> dict[str, Any]:
    return {"type": "object", "properties": {}}


class GraphSettings(_Strict):
    input_schema: dict[str, Any] = Field(default_factory=_object_schema)
    vars_schema: dict[str, Any] = Field(default_factory=_vars_schema)  # every variable declares a default
    outputs: dict[str, Any] = Field(default_factory=dict)  # evaluated when the run succeeds
    failure_handler: uuid.UUID | None = None  # a workflow id, pinned to its active version at publish


class Graph(_Strict):
    graph_format: Literal[1] = 1
    nodes: tuple[GraphNode, ...] = Field(default=(), max_length=MAX_NODES)
    edges: tuple[Edge, ...] = Field(default=(), max_length=MAX_EDGES)
    settings: GraphSettings = Field(default_factory=GraphSettings)


class GraphFormatError(ValueError):
    def __init__(self, diagnostics: list[Diagnostic]) -> None:
        super().__init__("; ".join(d.message for d in diagnostics))
        self.diagnostics = diagnostics


def parse_graph(data: Any) -> Graph:
    try:
        return Graph.model_validate(data)
    except ValidationError as e:
        raise GraphFormatError(
            [
                Diagnostic(code="graph.format", field="".join(f"/{p}" for p in err["loc"]), message=err["msg"])
                for err in e.errors()
            ]
        ) from None


def graph_json(graph: Graph) -> dict[str, Any]:
    return graph.model_dump(mode="json", by_alias=True)


def graph_hash(graph: Graph) -> str:
    """The authored graph only. Two versions with equal graph hashes may still run different sub-flow versions."""
    return sha256_hex(graph_json(graph))


def version_hash(
    *,
    graph_hash: str,
    subflow_pins: Mapping[str, str],
    failure_handler_version_id: str | None,
    cel_profile: str,
    engine_abi: int,
) -> str:
    """Identity of an executable version: the graph plus everything resolved at publish that changes what runs.
    Pinned versions are immutable, so the pins identify the whole closure. Audit and integrity checks use this."""
    return sha256_hex(
        {
            "graph_hash": graph_hash,
            "subflow_pins": dict(subflow_pins),
            "failure_handler_version_id": failure_handler_version_id,
            "cel_profile": cel_profile,
            "engine_abi": engine_abi,
        }
    )
```

- [ ] **Step 4: Implement structural analysis**

`backend/src/dewpoint/engine/graph/structure.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""Structural analysis: node types, ports, edges, acyclicity and loop regions (spec §4.2)."""

import heapq
import uuid
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass

from dewpoint.engine.graph.diagnostics import Diagnostic
from dewpoint.engine.graph.model import Edge, Graph, GraphNode
from dewpoint.engine.registry.catalog import Catalog, NodeTypeSpec
from dewpoint.engine.registry.control import LOOP
from dewpoint.sdk.node import PORT_RE, RESERVED_PORTS

MAX_LOOP_DEPTH = 3
ERROR_PORT = "error"


@dataclass(frozen=True)
class Region:
    loop: uuid.UUID | None  # None is the run's root region
    parent: uuid.UUID | None  # the region containing the loop node (None = root; also None for the root itself)
    members: tuple[uuid.UUID, ...]  # nodes whose innermost region this is, in topological order
    depth: int  # 0 for the root, 1 for a top-level loop body, ...


@dataclass(frozen=True)
class Structure:
    nodes: Mapping[uuid.UUID, GraphNode]
    specs: Mapping[uuid.UUID, NodeTypeSpec]
    ports: Mapping[uuid.UUID, tuple[str, ...]]  # normal ports: static then dynamic ("error" excluded)
    out_edges: Mapping[uuid.UUID, tuple[Edge, ...]]
    in_edges: Mapping[uuid.UUID, tuple[Edge, ...]]
    topo: tuple[uuid.UUID, ...]
    regions: Mapping[uuid.UUID | None, Region]
    region_of: Mapping[uuid.UUID, uuid.UUID | None]
    by_key: Mapping[str, uuid.UUID]

    def chain(self, region: uuid.UUID | None) -> list[uuid.UUID | None]:
        """`region` and every region enclosing it, innermost first, ending with the root (None)."""
        out: list[uuid.UUID | None] = [region]
        while region is not None:
            region = self.regions[region].parent
            out.append(region)
        return out


def _dynamic_ports(node: GraphNode, spec: NodeTypeSpec) -> tuple[list[str], list[Diagnostic]]:
    field = spec.dynamic_ports
    if field is None:
        return [], []
    raw = node.config.get(field)
    bad = Diagnostic(
        code="node.dynamic_ports",
        node=node.id,
        field=f"/{field}",
        message=f"`{field}` must be a list written in the graph, each entry with a unique literal `port` name "
        f"other than {', '.join(sorted({*spec.ports, *RESERVED_PORTS}))}.",
    )
    if not isinstance(raw, list):
        return [], [bad]
    ports: list[str] = []
    for item in raw:
        port = item.get("port") if isinstance(item, dict) else None
        if not isinstance(port, str) or not PORT_RE.match(port) or port in RESERVED_PORTS:
            return [], [bad]
        if port in spec.ports or port in ports:
            return [], [bad]
        ports.append(port)
    return ports, []


def _topo(nodes: Mapping[uuid.UUID, GraphNode], out_edges: Mapping[uuid.UUID, list[Edge]]) -> list[uuid.UUID]:
    """Kahn's algorithm; ties broken by node key so the order is deterministic."""
    indeg = {i: 0 for i in nodes}
    for edges in out_edges.values():
        for e in edges:
            indeg[e.to.node] += 1
    ready = [(nodes[i].key, i) for i, d in indeg.items() if d == 0]
    heapq.heapify(ready)
    order: list[uuid.UUID] = []
    while ready:
        _, i = heapq.heappop(ready)
        order.append(i)
        for e in out_edges[i]:
            indeg[e.to.node] -= 1
            if indeg[e.to.node] == 0:
                heapq.heappush(ready, (nodes[e.to.node].key, e.to.node))
    return order


def analyze_structure(graph: Graph, catalog: Catalog) -> tuple[Structure | None, list[Diagnostic]]:
    diags: list[Diagnostic] = []
    nodes: dict[uuid.UUID, GraphNode] = {}
    by_key: dict[str, uuid.UUID] = {}
    for n in graph.nodes:
        if n.id in nodes:
            diags.append(Diagnostic(code="graph.duplicate_id", node=n.id, message="Two steps share this id."))
            continue
        if n.key in by_key:
            diags.append(
                Diagnostic(
                    code="graph.duplicate_key",
                    node=n.id,
                    message=f"Another step is already called `{n.key}`.",
                    fix="Rename one of them.",
                )
            )
            continue
        nodes[n.id] = n
        by_key[n.key] = n.id

    specs: dict[uuid.UUID, NodeTypeSpec] = {}
    ports: dict[uuid.UUID, tuple[str, ...]] = {}
    for n in nodes.values():
        spec = catalog.get(n.type)
        if spec is None:
            diags.append(
                Diagnostic(code="node.unknown_type", node=n.id, message=f"`{n.type}` isn't installed on this platform.")
            )
            continue
        if spec.state == "retired":
            diags.append(
                Diagnostic(
                    code="lifecycle.retired", node=n.id, message=f"`{n.type}` has been retired.", fix="Replace this step."
                )
            )
        elif spec.state == "deprecated":
            diags.append(
                Diagnostic(
                    code="lifecycle.deprecated",
                    node=n.id,
                    message=f"`{n.type}` is deprecated; new versions can't use it.",
                    fix="Migrate this step to the newer version.",
                )
            )
        specs[n.id] = spec
        dynamic, problems = _dynamic_ports(n, spec)
        diags += problems
        ports[n.id] = (*spec.ports, *dynamic)
    if len(specs) != len(nodes):
        return None, diags  # edges can't be checked without every step's contract

    out_edges: dict[uuid.UUID, list[Edge]] = {i: [] for i in nodes}
    in_edges: dict[uuid.UUID, list[Edge]] = {i: [] for i in nodes}
    seen: set[tuple[uuid.UUID, str, uuid.UUID]] = set()
    for e in graph.edges:
        src, dst = e.source.node, e.to.node
        if src not in nodes or dst not in nodes:
            diags.append(Diagnostic(code="edge.unknown_node", message="An edge points to a step that doesn't exist."))
            continue
        allowed = ports[src] + ((ERROR_PORT,) if nodes[src].options.on_error == "port" else ())
        if e.source.port not in allowed:
            diags.append(
                Diagnostic(
                    code="edge.unknown_port",
                    node=src,
                    message=f"`{nodes[src].key}` has no `{e.source.port}` output.",
                )
            )
            continue
        if src == dst:
            diags.append(Diagnostic(code="edge.self", node=src, message="A step can't connect to itself."))
            continue
        if (src, e.source.port, dst) in seen:
            diags.append(Diagnostic(code="edge.duplicate", node=src, message="This connection exists twice."))
            continue
        seen.add((src, e.source.port, dst))
        out_edges[src].append(e)
        in_edges[dst].append(e)
    for n in nodes.values():
        if n.options.on_error == "port" and not any(e.source.port == ERROR_PORT for e in out_edges[n.id]):
            diags.append(
                Diagnostic(
                    code="node.error_port_unconnected",
                    node=n.id,
                    message="Errors go to the `error` output, but nothing is connected to it.",
                    fix="Connect the error output, or choose another error behaviour.",
                )
            )

    topo = _topo(nodes, out_edges)
    if len(topo) != len(nodes):
        placed = set(topo)
        stuck = sorted(nodes[i].key for i in nodes if i not in placed)
        diags.append(
            Diagnostic(
                code="graph.cycle",
                message=f"These steps form a cycle: {', '.join(stuck)}.",
                fix="Use a Loop step to repeat work.",
            )
        )
        return None, diags

    loops = [i for i in topo if specs[i].ref == LOOP]
    bodies: dict[uuid.UUID, set[uuid.UUID]] = {}
    for loop in loops:
        start = [e.to.node for e in out_edges[loop] if e.source.port == "body"]
        if not start:
            diags.append(
                Diagnostic(
                    code="loop.empty_body", node=loop, message="Nothing is connected to the loop's `body` output."
                )
            )
        body: set[uuid.UUID] = set()
        queue = deque(start)
        while queue:
            v = queue.popleft()
            if v not in body:
                body.add(v)
                queue.extend(e.to.node for e in out_edges[v])
        bodies[loop] = body

    regions_ok = True
    for index, a in enumerate(loops):
        for b in loops[index + 1 :]:
            if bodies[a] & bodies[b] and b not in bodies[a] and a not in bodies[b]:
                diags.append(
                    Diagnostic(
                        code="loop.region_crossing",
                        node=b,
                        message=f"The bodies of loops `{nodes[a].key}` and `{nodes[b].key}` overlap, "
                        "but neither contains the other.",
                        fix="Nest one loop entirely inside the other, or keep their bodies separate.",
                    )
                )
                regions_ok = False
    for loop in loops:
        for v in sorted(bodies[loop], key=lambda i: nodes[i].key):
            for e in in_edges[v]:
                src = e.source.node
                if src in bodies[loop] or (src == loop and e.source.port == "body"):
                    continue
                diags.append(
                    Diagnostic(
                        code="loop.region_entry",
                        node=v,
                        message=f"`{nodes[v].key}` is inside loop `{nodes[loop].key}` but is also reached from "
                        f"`{nodes[src].key}`, outside it.",
                        fix="Connect steps that follow the loop to its `done` output only.",
                    )
                )
                regions_ok = False
    if not regions_ok:
        return None, diags

    containing = {i: [loop for loop in loops if i in bodies[loop]] for i in nodes}
    for loop in loops:
        if 1 + len(containing[loop]) > MAX_LOOP_DEPTH:
            diags.append(
                Diagnostic(
                    code="loop.too_deep", node=loop, message=f"Loops can be nested at most {MAX_LOOP_DEPTH} deep."
                )
            )
            regions_ok = False
    if not regions_ok:
        return None, diags

    region_of: dict[uuid.UUID, uuid.UUID | None] = {
        i: (min(containing[i], key=lambda loop: len(bodies[loop])) if containing[i] else None) for i in nodes
    }
    regions: dict[uuid.UUID | None, Region] = {
        None: Region(loop=None, parent=None, members=tuple(i for i in topo if region_of[i] is None), depth=0)
    }
    for loop in loops:
        regions[loop] = Region(
            loop=loop,
            parent=region_of[loop],
            members=tuple(i for i in topo if region_of[i] == loop),
            depth=1 + len(containing[loop]),
        )
    structure = Structure(
        nodes=nodes,
        specs=specs,
        ports=ports,
        out_edges={k: tuple(v) for k, v in out_edges.items()},
        in_edges={k: tuple(v) for k, v in in_edges.items()},
        topo=tuple(topo),
        regions=regions,
        region_of=region_of,
        by_key=by_key,
    )
    return structure, diags
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/engine/graph -q`
Expected: all passed (7 in `test_model.py`, counting each parametrized case, and 11 in `test_structure.py`).

- [ ] **Step 6: Commit**

```bash
uv run ruff format . && uv run ruff check . && uv run mypy src && uv run lint-imports && uv run pytest tests/engine -q && \
git add src/dewpoint/engine/graph tests/engine/graph tests/support/graphs.py && \
git commit -m "feat(engine): graph model and structural analysis with loop regions

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Value envelopes, reference paths and schema navigation

**Files:**
- Create: `backend/src/dewpoint/engine/graph/values.py`, `backend/src/dewpoint/engine/graph/schemas.py`
- Test: `backend/tests/engine/graph/test_values.py`, `backend/tests/engine/graph/test_schemas.py`

**Interfaces:**
- Consumes: `dewpoint.sdk.fields.{LITERAL, KINDS}`.
- Produces from `values.py`:
  - `ENVELOPE = "$value"`, `MAX_CEL = 16_384`, `Pointer = tuple[str | int, ...]`.
  - Reference paths: `RefPath(text, root, name, section, rest)`, `parse_ref(text) -> RefPath` (raises `RefSyntaxError`).
  - Value classes, each with a `kind` ClassVar:
    - `LiteralValue(value)`;
    - `RefValue(path, default, has_default)`;
    - `TemplateRef(path, default: str | None)`;
    - `TemplateValue(parts: tuple[str | TemplateRef, ...])`;
    - `CelValue(expr)`;
    - the union `Value`.
  - `ValueSyntaxError(message)`: a plain dataclass, not an exception.
  - `parse_envelope` and `iter_values` never raise on malformed data: every field is type-checked before it is used, including `kind`. A Hypothesis test feeds them arbitrary JSON.
  - Helpers: `is_envelope(obj)`, `parse_envelope(body) -> Value`, `iter_values(config, base=()) -> Iterator[(Pointer, Value | ValueSyntaxError)]`, `strip_values(config) -> (stripped, [Pointer])`, `pointer_str(pointer) -> str`.
- Produces from `schemas.py`:
  - `Resolved(schema, conditional)`, `PathError`.
  - `navigate(root, path, start=None) -> Resolved`, `target_schema(root, pointer)`, `element_schema(schema)`, `standalone(root, schema)`.
    - `navigate` follows JSON Schema. Only `additionalProperties: false` makes an undeclared field an error (`PathError`). Otherwise the field may exist, so it resolves as unknown and possibly missing.
  - `json_types(schema) -> frozenset[str] | None`, `compatible(source, target) -> bool`, `describe(schema) -> str`, `literal_type(value) -> str`.
    - `compatible` requires **every** type the source admits to fit the target (an integer fits a number). If either side is unknown, the runtime check decides.
  - `object_schema(props, required) -> dict`: a closed object built from per-field schemas that keep their own `$defs` scope. Definitions are renamed `f<index>.<name>` and `$ref`s rewritten, so two fields may each define `Item` differently.
  - Marker checks: `literal_on_path(root, pointer)`, `contains_literal(root, schema)`, `allowed_kinds(root, pointer)`.
- Reference roots: `trigger.<path>`, `steps.<key>.output.<path>`, `steps.<key>.error[.code|.message|.attempt]`, `vars.<name>.<path>`, `loop.item.<path>`, `loop.index`, `loops.<loop_key>.item.<path>`, `loops.<loop_key>.index`, `run.id|started_at|now`. Path segments are identifiers or `[n]` indexes.

- [ ] **Step 1: Write the failing tests**

`backend/tests/engine/graph/test_values.py`:

```python
# SPDX-License-Identifier: Apache-2.0
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from dewpoint.engine.graph.values import (
    CelValue,
    LiteralValue,
    RefSyntaxError,
    RefValue,
    TemplateRef,
    TemplateValue,
    ValueSyntaxError,
    iter_values,
    parse_ref,
    pointer_str,
    strip_values,
)


@pytest.mark.parametrize(
    ("text", "root", "name", "section", "rest"),
    [
        ("trigger.site.devices[0].mac", "trigger", None, None, ("site", "devices", 0, "mac")),
        ("steps.get_site.output.name", "steps", "get_site", "output", ("name",)),
        ("steps.get_site.error.code", "steps", "get_site", "error", ("code",)),
        ("vars.count", "vars", "count", None, ()),
        ("loop.item.name", "loop", None, "item", ("name",)),
        ("loop.index", "loop", None, "index", ()),
        ("loops.outer.item", "loops", "outer", "item", ()),
        ("run.now", "run", None, "now", ()),
    ],
)
def test_parse_ref(text: str, root: str, name: str | None, section: str | None, rest: tuple[Any, ...]) -> None:
    r = parse_ref(text)
    assert (r.root, r.name, r.section, r.rest, r.text) == (root, name, section, rest, text)


@pytest.mark.parametrize(
    "text",
    [
        "",
        "steps",
        "steps.a",
        "steps.a.oops",
        "steps.a.error.detail",
        "loop.index.x",
        "run.clock",
        "env.HOME",
        "trigger..x",
        "trigger.x[01]",
        "trigger.x[",
        ".trigger",
    ],
)
def test_bad_refs(text: str) -> None:
    with pytest.raises(RefSyntaxError):
        parse_ref(text)


def test_iter_values_finds_nested_envelopes_in_order() -> None:
    config = {
        "b": {"$value": {"kind": "ref", "path": "vars.x", "default": 0}},
        "a": [
            1,
            {"$value": {"kind": "cel", "expr": "1 + 1"}},
            {"deep": {"$value": {"kind": "literal", "value": {"$value": 1}}}},
        ],
        "t": {"$value": {"kind": "template", "parts": [{"text": "hi "}, {"ref": "vars.name", "default": "you"}]}},
    }
    found = list(iter_values(config))
    assert [pointer_str(p) for p, _ in found] == ["/a/1", "/a/2/deep", "/b", "/t"]
    cel = found[0][1]
    assert isinstance(cel, CelValue) and cel.expr == "1 + 1"
    assert found[1][1] == LiteralValue({"$value": 1})
    ref = found[2][1]
    assert isinstance(ref, RefValue) and ref.has_default and ref.default == 0
    tpl = found[3][1]
    assert isinstance(tpl, TemplateValue) and tpl.parts[0] == "hi "
    assert isinstance(tpl.parts[1], TemplateRef) and tpl.parts[1].default == "you"


@pytest.mark.parametrize(
    "body",
    [
        {"$value": {"kind": "python", "code": "x"}},
        {"$value": {"kind": "ref", "path": "vars.x", "extra": 1}},
        {"$value": {"kind": "ref", "path": "nope.x"}},
        {"$value": {"kind": "template", "parts": []}},
        {"$value": {"kind": "template", "parts": [{"ref": "vars.x", "default": 3}]}},
        {"$value": {"kind": "cel", "expr": "x" * 16_385}},
        {"$value": {"kind": "literal"}},
        {"$value": {"kind": "ref", "path": "vars.x"}, "other": 1},
    ],
)
def test_envelope_errors_are_reported_in_place(body: dict[str, Any]) -> None:
    [(pointer, value)] = list(iter_values({"f": body}))
    assert pointer == ("f",) and isinstance(value, ValueSyntaxError)


def test_strip_values_replaces_envelopes_with_null() -> None:
    stripped, pointers = strip_values({"a": 1, "b": [{"$value": {"kind": "cel", "expr": "x"}}, 2]})
    assert stripped == {"a": 1, "b": [None, 2]} and pointers == [("b", 0)]


def test_pointer_escaping() -> None:
    assert pointer_str(("a/b", "c~d", 0)) == "/a~1b/c~0d/0"


@pytest.mark.parametrize("kind", [[], {}, 3, None, True])
def test_non_text_kinds_are_syntax_errors(kind: Any) -> None:
    [(_, value)] = list(iter_values({"f": {"$value": {"kind": kind}}}))
    assert isinstance(value, ValueSyntaxError)


KEYS = st.sampled_from(["$value", "kind", "path", "parts", "expr", "value", "default", "text", "ref"]) | st.text(
    max_size=6
)
JSON = st.recursive(
    st.none() | st.booleans() | st.integers() | st.floats(allow_nan=False) | st.text(max_size=8),
    lambda inner: st.lists(inner, max_size=4) | st.dictionaries(KEYS, inner, max_size=4),
    max_leaves=20,
)


@settings(max_examples=300, deadline=None)
@given(JSON)
def test_arbitrary_envelopes_are_reported_never_raised(body: Any) -> None:
    for _, value in iter_values({"f": {"$value": body}, "g": body}):
        assert value is not None
```

`backend/tests/engine/graph/test_schemas.py`:

```python
# SPDX-License-Identifier: Apache-2.0
import pytest
from jsonschema import Draft202012Validator
from pydantic import BaseModel

from dewpoint.engine.graph.schemas import (
    PathError,
    allowed_kinds,
    compatible,
    contains_literal,
    element_schema,
    json_types,
    literal_on_path,
    navigate,
    object_schema,
    target_schema,
)
from dewpoint.plugins.flow.nodes import FilterConfig, LoopConfig, SwitchConfig


class Site(BaseModel):
    name: str
    tags: list[str]
    note: str | None = None


class Out(BaseModel):
    site: Site
    sites: list[Site]
    maybe: Site | None = None


OUT = Out.model_json_schema(mode="serialization")


def test_navigate_through_refs_lists_and_optionals() -> None:
    r = navigate(OUT, ["site", "name"])
    assert json_types(r.schema) == {"string"} and not r.conditional
    r = navigate(OUT, ["sites", 0, "tags"])
    assert json_types(r.schema) == {"array"} and r.conditional  # the list may be shorter
    r = navigate(OUT, ["site", "note"])
    assert json_types(r.schema) == {"string"} and r.conditional  # optional and nullable
    assert navigate(OUT, ["maybe", "name"]).conditional
    element = element_schema(navigate(OUT, ["sites"]).schema)
    assert element is not None and json_types(navigate(element, ["name"]).schema) == {"string"}


def test_only_closed_objects_reject_undeclared_fields() -> None:
    closed = {"type": "object", "properties": {"a": {"type": "string"}}, "additionalProperties": False}
    with pytest.raises(PathError, match="no field `nope`"):
        navigate(closed, ["nope"])
    with pytest.raises(PathError, match="isn't a list"):
        navigate(OUT, ["site", 0])
    for open_object in (OUT, {"type": "object"}):  # additionalProperties omitted: undeclared fields may exist
        path = ["site", "nope"] if open_object is OUT else ["anything"]
        r = navigate(open_object, path)
        assert r.schema is None and r.conditional


def test_compatibility() -> None:
    assert compatible({"type": "integer"}, {"type": "number"})
    assert not compatible({"type": "string"}, {"type": "boolean"})
    assert compatible(None, {"type": "boolean"}) and compatible({"type": "string"}, {})
    assert compatible({"type": "string"}, {"anyOf": [{"type": "string"}, {"type": "null"}]})
    assert json_types({"enum": ["a", 1]}) == {"string", "integer"}


def test_every_possible_source_type_must_fit_the_target() -> None:
    union = {"type": ["string", "integer"]}
    assert not compatible(union, {"type": "string"})
    assert compatible(union, {"type": ["string", "integer", "null"]})
    assert compatible({"anyOf": [{"type": "integer"}, {"type": "number"}]}, {"type": "number"})
    assert not compatible({"anyOf": [{"type": "string"}, {"type": "null"}]}, {"type": "string"})


def test_composed_objects_keep_each_fields_definitions() -> None:
    text = {"$ref": "#/$defs/Item", "$defs": {"Item": {"type": "string"}}}
    number = {"$ref": "#/$defs/Item", "$defs": {"Item": {"type": "integer"}}}
    schema = object_schema({"a": text, "b": number}, ["a", "b"])
    assert json_types(navigate(schema, ["a"]).schema) == {"string"}
    assert json_types(navigate(schema, ["b"]).schema) == {"integer"}
    assert list(Draft202012Validator(schema).iter_errors({"a": "x", "b": 1})) == []
    assert list(Draft202012Validator(schema).iter_errors({"a": 1, "b": "x"})) != []


def test_markers() -> None:
    loop = LoopConfig.model_json_schema()
    assert literal_on_path(loop, ["concurrency"]) and not literal_on_path(loop, ["items"])
    switch = SwitchConfig.model_json_schema()
    assert contains_literal(switch, target_schema(switch, ["cases"]))  # entries carry literal ports
    assert literal_on_path(switch, ["cases", 0, "port"])
    assert not contains_literal(switch, target_schema(switch, ["cases", 0, "when"]))
    assert allowed_kinds(FilterConfig.model_json_schema(), ["predicate"]) == frozenset({"cel"})
    assert allowed_kinds(loop, ["items"]) is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/engine/graph/test_values.py tests/engine/graph/test_schemas.py -q`
Expected: FAIL: `ModuleNotFoundError: No module named 'dewpoint.engine.graph.values'`.

- [ ] **Step 3: Implement values**

`backend/src/dewpoint/engine/graph/values.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""Value envelopes inside node configs, and reference paths (spec §4.3).

Any JSON object of the form {"$value": {...}} is an envelope; everything else in a config is literal JSON."""

import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Any, ClassVar

ENVELOPE = "$value"
MAX_REF_LENGTH = 512
MAX_TEMPLATE_PARTS = 100
MAX_TEXT = 4096
MAX_CEL = 16_384  # spec §5.2: longer expressions are rejected

Pointer = tuple[str | int, ...]
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_INDEX = re.compile(r"\[(0|[1-9][0-9]{0,5})\]")
_ALLOWED_KEYS = {
    "literal": {"kind", "value"},
    "ref": {"kind", "path", "default"},
    "template": {"kind", "parts"},
    "cel": {"kind", "expr"},
}


class RefSyntaxError(ValueError):
    pass


@dataclass(frozen=True)
class RefPath:
    text: str
    root: str  # trigger | steps | vars | loop | loops | run
    name: str | None  # step key, variable name or loop key
    section: str | None  # output | error | item | index | id | started_at | now
    rest: tuple[str | int, ...]


def _tokens(text: str) -> list[str | int]:
    first = _IDENT.match(text)
    if first is None:
        raise RefSyntaxError("a reference starts with a name")
    out: list[str | int] = [first.group()]
    pos = first.end()
    while pos < len(text):
        if text[pos] == ".":
            m = _IDENT.match(text, pos + 1)
            if m is None:
                raise RefSyntaxError("expected a field name after `.`")
            out.append(m.group())
        else:
            m = _INDEX.match(text, pos)
            if m is None:
                raise RefSyntaxError("expected `.name` or `[n]`")
            out.append(int(m.group(1)))
        pos = m.end()
    return out


def _name(tokens: list[str | int], i: int, what: str) -> str:
    value = tokens[i] if i < len(tokens) else None
    if not isinstance(value, str):
        raise RefSyntaxError(f"expected {what}")
    return value


def _loop_ref(text: str, root: str, name: str | None, section: str, rest: list[str | int]) -> RefPath:
    if section not in ("item", "index"):
        raise RefSyntaxError("a loop reference reads `item` or `index`")
    if section == "index" and rest:
        raise RefSyntaxError("`index` has no fields")
    return RefPath(text, root, name, section, tuple(rest))


def parse_ref(text: Any) -> RefPath:
    if not isinstance(text, str) or not text or len(text) > MAX_REF_LENGTH:
        raise RefSyntaxError("a reference must be a non-empty path")
    t = _tokens(text)
    root = t[0]
    if root == "trigger":
        return RefPath(text, "trigger", None, None, tuple(t[1:]))
    if root == "steps":
        name, section = _name(t, 1, "a step key"), _name(t, 2, "`output` or `error`")
        rest = tuple(t[3:])
        if section not in ("output", "error"):
            raise RefSyntaxError("after `steps.<key>` comes `output` or `error`")
        if section == "error" and (len(rest) > 1 or (rest and rest[0] not in ("code", "message", "attempt"))):
            raise RefSyntaxError("`error` has `code`, `message` and `attempt`")
        return RefPath(text, "steps", name, section, rest)
    if root == "vars":
        return RefPath(text, "vars", _name(t, 1, "a variable name"), None, tuple(t[2:]))
    if root == "loop":
        return _loop_ref(text, "loop", None, _name(t, 1, "`item` or `index`"), t[2:])
    if root == "loops":
        return _loop_ref(text, "loops", _name(t, 1, "a loop key"), _name(t, 2, "`item` or `index`"), t[3:])
    if root == "run":
        section = _name(t, 1, "`id`, `started_at` or `now`")
        if section not in ("id", "started_at", "now") or len(t) > 2:
            raise RefSyntaxError("`run` has `id`, `started_at` and `now`")
        return RefPath(text, "run", None, section, ())
    raise RefSyntaxError(f"references start with trigger, steps, vars, loop, loops or run, not `{root}`")


@dataclass(frozen=True)
class LiteralValue:
    kind: ClassVar[str] = "literal"
    value: Any


@dataclass(frozen=True)
class RefValue:
    kind: ClassVar[str] = "ref"
    path: RefPath
    default: Any = None
    has_default: bool = False


@dataclass(frozen=True)
class TemplateRef:
    path: RefPath
    default: str | None = None


@dataclass(frozen=True)
class TemplateValue:
    kind: ClassVar[str] = "template"
    parts: tuple[str | TemplateRef, ...]


@dataclass(frozen=True)
class CelValue:
    kind: ClassVar[str] = "cel"
    expr: str


Value = LiteralValue | RefValue | TemplateValue | CelValue


@dataclass(frozen=True)
class ValueSyntaxError:
    """Not an exception: iter_values yields it in place of a value, so every problem gets reported."""

    message: str


def is_envelope(obj: Any) -> bool:
    return isinstance(obj, Mapping) and ENVELOPE in obj


def _template_part(part: Any) -> str | TemplateRef:
    if isinstance(part, Mapping) and set(part) == {"text"} and isinstance(part["text"], str):
        if len(part["text"]) > MAX_TEXT:
            raise ValueError(f"template text is limited to {MAX_TEXT} characters")
        return part["text"]
    if isinstance(part, Mapping) and "ref" in part and set(part) <= {"ref", "default"}:
        default = part.get("default")
        if default is not None and not isinstance(default, str):
            raise ValueError("a template default must be text")
        return TemplateRef(parse_ref(part["ref"]), default)
    raise ValueError("each template part is {text} or {ref, default?}")


def parse_envelope(body: Any) -> Value:
    if not isinstance(body, Mapping):
        raise ValueError("`$value` must be an object")
    kind = body.get("kind")
    if not isinstance(kind, str) or kind not in _ALLOWED_KEYS:  # type first: a list or dict is unhashable
        raise ValueError("`kind` must be literal, ref, template or cel")
    extra = set(body) - _ALLOWED_KEYS[kind]
    if extra:
        raise ValueError(f"unexpected keys: {', '.join(sorted(extra))}")
    if kind == "literal":
        if "value" not in body:
            raise ValueError("a literal needs `value`")
        return LiteralValue(body["value"])
    if kind == "ref":
        return RefValue(parse_ref(body.get("path")), body.get("default"), "default" in body)
    if kind == "template":
        parts = body.get("parts")
        if not isinstance(parts, list) or not parts or len(parts) > MAX_TEMPLATE_PARTS:
            raise ValueError(f"a template has 1 to {MAX_TEMPLATE_PARTS} parts")
        return TemplateValue(tuple(_template_part(p) for p in parts))
    expr = body.get("expr")
    if not isinstance(expr, str) or not expr.strip():
        raise ValueError("`expr` must be non-empty text")
    if len(expr) > MAX_CEL:
        raise ValueError(f"expressions are limited to {MAX_CEL} characters")
    return CelValue(expr)


def iter_values(config: Any, base: Pointer = ()) -> Iterator[tuple[Pointer, Value | ValueSyntaxError]]:
    """Every envelope in `config`, in a deterministic order (object keys sorted). Literals are not yielded."""
    if isinstance(config, Mapping):
        if ENVELOPE in config:
            if len(config) != 1:
                yield base, ValueSyntaxError("an object with `$value` can't have other keys")
                return
            try:
                yield base, parse_envelope(config[ENVELOPE])
            except ValueError as e:
                yield base, ValueSyntaxError(str(e))
            return
        for key in sorted(config):
            yield from iter_values(config[key], (*base, key))
    elif isinstance(config, list):
        for index, item in enumerate(config):
            yield from iter_values(item, (*base, index))


def strip_values(config: Any) -> tuple[Any, list[Pointer]]:
    """`config` with every envelope replaced by null, plus the envelopes' pointers."""
    pointers = [p for p, _ in iter_values(config)]

    def walk(obj: Any) -> Any:
        if isinstance(obj, Mapping):
            return None if ENVELOPE in obj else {k: walk(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [walk(v) for v in obj]
        return obj

    return walk(config), pointers


def pointer_str(pointer: Pointer) -> str:
    return "".join("/" + str(seg).replace("~", "~0").replace("/", "~1") for seg in pointer)
```

- [ ] **Step 4: Implement schema navigation**

`backend/src/dewpoint/engine/graph/schemas.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""Just enough JSON Schema to type references: navigation, nullability, type compatibility and markers.

Schemas returned by `navigate`, `target_schema` and `element_schema` are *standalone*: they carry the root's
`$defs`, so they can be navigated again on their own."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from dewpoint.engine.schema_refs import PREFIX, SCHEMA_LIST, SCHEMA_MAP, SCHEMA_ONE
from dewpoint.sdk.fields import KINDS, LITERAL

Schema = Mapping[str, Any]
_PY_TYPES: tuple[tuple[type, str], ...] = (
    (bool, "boolean"),  # before int: bool is a subclass of int
    (int, "integer"),
    (float, "number"),
    (str, "string"),
    (list, "array"),
    (dict, "object"),
    (type(None), "null"),
)


class PathError(ValueError):
    """The path names something the schema says can't exist."""


@dataclass(frozen=True)
class Resolved:
    schema: Schema | None  # None: unknown, any value
    conditional: bool  # may be missing or null at run time


def literal_type(value: Any) -> str:
    for py, name in _PY_TYPES:
        if isinstance(value, py):
            return name
    return "object"


def _deref(root: Schema, schema: Any) -> Schema | None:
    hops = 0
    while isinstance(schema, Mapping) and "$ref" in schema:
        ref = schema["$ref"]
        defs = root.get("$defs")
        if not isinstance(ref, str) or not ref.startswith("#/$defs/") or not isinstance(defs, Mapping) or hops > 32:
            return None
        schema = defs.get(ref[len("#/$defs/") :])
        hops += 1
    return schema if isinstance(schema, Mapping) else None


def _strip_null(schema: Schema) -> tuple[Schema, bool]:
    for key in ("anyOf", "oneOf"):
        options = schema.get(key)
        if isinstance(options, list):
            non_null = [o for o in options if not (isinstance(o, Mapping) and o.get("type") == "null")]
            if len(non_null) == 1 and len(options) > 1 and isinstance(non_null[0], Mapping):
                rest = {k: v for k, v in schema.items() if k != key}
                return {**rest, **non_null[0]}, True
    t = schema.get("type")
    if isinstance(t, list) and "null" in t:
        others = [x for x in t if x != "null"]
        return {**schema, "type": others[0] if len(others) == 1 else others}, True
    return schema, False


def standalone(root: Schema, schema: Schema) -> Schema:
    defs = root.get("$defs")
    if isinstance(defs, Mapping) and "$defs" not in schema:
        return {**schema, "$defs": defs}
    return schema


def json_types(schema: Any) -> frozenset[str] | None:
    """The JSON types a (standalone) schema admits, or None for 'anything'."""
    if not isinstance(schema, Mapping):
        return None
    s = _deref(schema, schema)
    if s is None:
        return None
    if "const" in s:
        return frozenset({literal_type(s["const"])})
    if isinstance(s.get("enum"), list):
        return frozenset(literal_type(v) for v in s["enum"])
    t = s.get("type")
    if isinstance(t, str):
        return frozenset({t})
    if isinstance(t, list):
        return frozenset(x for x in t if isinstance(x, str))
    for key in ("anyOf", "oneOf"):
        options = s.get(key)
        if isinstance(options, list):
            out: set[str] = set()
            for option in options:
                inner = standalone(schema, option) if isinstance(option, Mapping) else option
                types = json_types(inner)
                if types is None:
                    return None
                out |= types
            return frozenset(out)
    return None


def compatible(source: Any, target: Any) -> bool:
    """True when every type the source admits fits the target. Unknown on either side: the runtime check decides."""
    s, t = json_types(source), json_types(target)
    if s is None or t is None:
        return True
    return all(kind in t or (kind == "integer" and "number" in t) for kind in s)


def describe(schema: Any) -> str:
    types = json_types(schema)
    return "any value" if types is None else " or ".join(sorted(types))


def navigate(root: Any, path: Sequence[str | int], start: Any = None) -> Resolved:
    """Follow a reference path through an output schema. Raises PathError for fields a closed schema lacks."""
    if not isinstance(root, Mapping):
        return Resolved(None, bool(path))
    current: Any = root if start is None else start
    conditional = False
    for seg in path:
        schema = _deref(root, current)
        if schema is None:
            return Resolved(None, True)
        schema, nullable = _strip_null(schema)
        schema = _deref(root, schema)
        if schema is None:
            return Resolved(None, True)
        conditional |= nullable
        types = json_types(standalone(root, schema))
        if isinstance(seg, int):
            if types is not None and "array" not in types:
                raise PathError(f"[{seg}] indexes a value that isn't a list")
            items = schema.get("items")
            if not isinstance(items, Mapping) or not items:
                return Resolved(None, True)
            current, conditional = items, True  # the list may be shorter
            continue
        props = schema.get("properties")
        if isinstance(props, Mapping) and seg in props:
            required = schema.get("required")
            if not (isinstance(required, list) and seg in required):
                conditional = True
            current = props[seg]
            continue
        if types is not None and "object" not in types:
            raise PathError(f"`{seg}` reads a field of a value that isn't an object")
        extra = schema.get("additionalProperties")
        if isinstance(extra, Mapping) and extra:
            current, conditional = extra, True
            continue
        if extra is False:  # only a closed object rules the field out; otherwise it may exist
            raise PathError(f"there is no field `{seg}`")
        return Resolved(None, True)
    final = _deref(root, current)
    if final is None:
        return Resolved(None, conditional)
    final, nullable = _strip_null(final)
    resolved = _deref(root, final)
    if resolved is None:
        return Resolved(None, True)
    return Resolved(standalone(root, resolved), conditional or nullable)


def element_schema(schema: Schema | None) -> Schema | None:
    """The item schema of a list schema, or None when unknown."""
    if schema is None:
        return None
    types = json_types(schema)
    if types is not None and "array" not in types:
        return None
    try:
        return navigate(schema, [0]).schema
    except PathError:
        return None


def _steps(root: Schema, pointer: Sequence[str | int]) -> list[tuple[Schema, Schema]] | None:
    """For each pointer segment in a *config* schema: the subschema as written and after $ref resolution.
    None when the pointer leaves the schema."""
    out: list[tuple[Schema, Schema]] = []
    current: Schema = root
    for seg in pointer:
        base = _deref(root, _strip_null(current)[0])
        if base is None:
            return None
        if isinstance(seg, int):
            nxt = base.get("items")
        else:
            props = base.get("properties")
            if isinstance(props, Mapping) and seg in props:
                nxt = props[seg]
            else:
                extra = base.get("additionalProperties")
                nxt = extra if isinstance(extra, Mapping) else None
        if not isinstance(nxt, Mapping):
            return None
        resolved = _deref(root, nxt)
        if resolved is None:
            return None
        out.append((nxt, resolved))
        current = resolved
    return out


def target_schema(root: Any, pointer: Sequence[str | int]) -> Schema | None:
    """The schema a value written at `pointer` in a config must satisfy (nullability kept), or None if unknown."""
    if not isinstance(root, Mapping):
        return None
    if not pointer:
        return root
    steps = _steps(root, pointer)
    return standalone(root, steps[-1][1]) if steps else None


def literal_on_path(root: Any, pointer: Sequence[str | int]) -> bool:
    if not isinstance(root, Mapping):
        return False
    steps = _steps(root, pointer) or []
    return any(raw.get(LITERAL) is True or resolved.get(LITERAL) is True for raw, resolved in steps)


def contains_literal(root: Any, schema: Any, _seen: frozenset[str] = frozenset()) -> bool:
    """True when `schema` or anything nested in it must be written literally."""
    if not isinstance(root, Mapping) or not isinstance(schema, Mapping):
        return False
    if schema.get(LITERAL) is True:
        return True
    ref = schema.get("$ref")
    if isinstance(ref, str) and ref not in _seen:
        if contains_literal(root, _deref(standalone(root, schema), {"$ref": ref}), _seen | {ref}):
            return True
    children: list[Any] = []
    props = schema.get("properties")
    if isinstance(props, Mapping):
        children += list(props.values())
    for key in ("items", "additionalProperties"):
        if isinstance(schema.get(key), Mapping):
            children.append(schema[key])
    for key in ("anyOf", "oneOf", "allOf", "prefixItems"):
        if isinstance(schema.get(key), list):
            children += schema[key]
    return any(contains_literal(root, child, _seen) for child in children)


def allowed_kinds(root: Any, pointer: Sequence[str | int]) -> frozenset[str] | None:
    if not isinstance(root, Mapping) or not pointer:
        return None
    steps = _steps(root, pointer)
    if not steps:
        return None
    raw, resolved = steps[-1]
    kinds = raw.get(KINDS, resolved.get(KINDS))
    return frozenset(kinds) if isinstance(kinds, list) else None


def _rename_refs(node: Any, names: Mapping[str, str]) -> Any:
    """Rewrite `#/$defs/<old>` to `#/$defs/<new>` in schema positions. Data (defaults, enums, ...) is copied as is."""
    if not isinstance(node, Mapping):
        return node
    out: dict[str, Any] = {}
    for key, value in node.items():
        if key == "$ref" and isinstance(value, str) and value.startswith(PREFIX) and value[len(PREFIX) :] in names:
            out[key] = PREFIX + names[value[len(PREFIX) :]]
        elif key in SCHEMA_ONE:
            out[key] = _rename_refs(value, names)
        elif key in SCHEMA_LIST and isinstance(value, list):
            out[key] = [_rename_refs(sub, names) for sub in value]
        elif key in SCHEMA_MAP and isinstance(value, Mapping):
            out[key] = {name: _rename_refs(sub, names) for name, sub in value.items()}
        else:
            out[key] = value
    return out


def object_schema(props: Mapping[str, Mapping[str, Any]], required: Sequence[str]) -> dict[str, Any]:
    """A closed object schema built from per-field schemas that may each carry their own `$defs`.
    Each field keeps its reference scope: its definitions move under a per-field name (`f<index>.<name>`) and its
    `$ref`s are rewritten to match, so two fields may both define `Item` differently."""
    defs: dict[str, Any] = {}
    fields: dict[str, Any] = {}
    for index, (name, schema) in enumerate(props.items()):
        local = schema.get("$defs")
        names = {key: f"f{index}.{key}" for key in local} if isinstance(local, Mapping) else {}
        fields[name] = _rename_refs({k: v for k, v in schema.items() if k != "$defs"}, names)
        for key, sub in local.items() if isinstance(local, Mapping) else ():
            defs[names[key]] = _rename_refs(sub, names)
    out: dict[str, Any] = {
        "type": "object",
        "properties": fields,
        "required": list(required),
        "additionalProperties": False,
    }
    if defs:
        out["$defs"] = defs
    return out
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/engine/graph/test_values.py tests/engine/graph/test_schemas.py -q`
Expected: all passed.

- [ ] **Step 6: Commit**

```bash
uv run ruff format . && uv run ruff check . && uv run mypy src && uv run lint-imports && uv run pytest tests/engine -q && \
git add src/dewpoint/engine/graph/values.py src/dewpoint/engine/graph/schemas.py tests/engine/graph/test_values.py tests/engine/graph/test_schemas.py && \
git commit -m "feat(engine): value envelopes, reference paths and schema navigation

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Liveness conditions and the graph validator

**Files:**
- Create: `backend/src/dewpoint/engine/graph/liveness.py`, `backend/src/dewpoint/engine/graph/validate.py`
- Test: `backend/tests/engine/graph/test_liveness.py`, `backend/tests/engine/graph/test_validate.py`

**Interfaces:**
- Consumes: Tasks 3–5.
- Produces from `liveness.py`:
  - Types: `Lit = (node_id, port | "#err")`, `Term = frozenset[Lit]`, `Cond = frozenset[Term] | None`.
  - Constants: `TRUE`, `FALSE`, `ERR = "#err"`, `MAX_TERMS = 256`.
  - Functions: `simplify(terms, values) -> Cond`, `implies(consumer, producer) -> bool`, `exclusive(a, b) -> bool`, `analyze_region(structure, region) -> RegionLiveness(live, ok, err, exit)`.
- Produces from `validate.py`:
  - `SubflowInfo(workflow_id, version_id, input_schema, output_schema)`.
  - `ValidationContext(catalog, subflows={}, max_run_duration=30 days)`.
  - `ValidationResult(diagnostics, node_refs, subflow_pins: {node_id_str: version_id_str}, failure_handler_version_id, output_schema)` with `.ok`.
  - Functions: `referenced_workflows(graph) -> set[UUID]`, `validate(graph, ctx) -> ValidationResult`. `validate` reports and never raises; a Hypothesis test runs it on arbitrary node configs and outputs.
  - `MAX_SUBFLOW_DEPTH = 5`.
- Diagnostic codes introduced:
  - settings and values: `settings.invalid_schema`, `settings.unresolvable_ref`, `settings.output_name`, `value.syntax`, `value.literal_only`, `value.kind_not_allowed`, `config.invalid`, `cel.unavailable`;
  - references: `ref.unknown_step`, `ref.unknown_var`, `ref.unknown_field`, `ref.out_of_scope`, `ref.not_upstream`, `ref.no_error_output`, `ref.conditional`, `ref.type_mismatch`, `ref.loop_outside`;
  - templates: `template.not_string`, `template.part_not_scalar`;
  - variables: `vars.invalid_name`, `vars.no_default`, `vars.bad_default`, `vars.undeclared`, `vars.write_in_loop`, `vars.concurrent_writers`;
  - waits and sub-flows: `wait.exceeds_deadline`, `subflow.unknown`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/engine/graph/test_liveness.py`:

```python
# SPDX-License-Identifier: Apache-2.0
import itertools
import uuid
from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st

from dewpoint.engine.graph import liveness as lv
from dewpoint.engine.graph.model import Graph
from dewpoint.engine.graph.structure import analyze_structure
from dewpoint.plugins.flow import PLUGIN
from tests.support.catalog import catalog
from tests.support.graphs import G, nid
from tests.support.plugins.testkit import TESTKIT

CAT = catalog(PLUGIN, TESTKIT)
A, B = uuid.uuid4(), uuid.uuid4()


def test_simplify_merges_complements_and_absorbs() -> None:
    values = {A: ("true", "false"), B: ("x", "y", "z")}
    t, f = frozenset({(A, "true")}), frozenset({(A, "false")})
    assert lv.simplify([t, f], values) == lv.TRUE
    assert lv.simplify([t, t | {(B, "x")}], values) == frozenset({t})
    assert lv.simplify([t | {(A, "false")}], values) == lv.FALSE  # contradictory
    partial = [frozenset({(B, v)}) for v in ("x", "y")]
    assert lv.simplify(partial, values) == frozenset(partial)  # `z` is missing: no merge


def test_implies_and_exclusive() -> None:
    t, f = frozenset({(A, "true")}), frozenset({(A, "false")})
    assert lv.implies(frozenset({t}), frozenset({t}))
    assert not lv.implies(lv.TRUE, frozenset({t}))
    assert lv.implies(frozenset({t}), lv.TRUE) and lv.implies(None, lv.TRUE)
    assert not lv.implies(frozenset({t}), None)
    assert lv.exclusive(frozenset({t}), frozenset({f})) and not lv.exclusive(frozenset({t}), lv.TRUE)


def test_parallel_join_is_live_whenever_its_inputs_are() -> None:
    g = G().node("x", "testkit.echo@1").node("a", "testkit.echo@1").node("b", "testkit.echo@1").node("j", "testkit.echo@1")
    s, _ = analyze_structure(g.edge("x", "a").edge("x", "b").edge("a", "j").edge("b", "j").build(), CAT)
    assert s is not None
    region = lv.analyze_region(s, None)
    assert lv.implies(region.live[nid("j")], region.ok[nid("a")])


@st.composite
def dags(draw: st.DrawFn) -> tuple[list[str], list[tuple[int, int, str]], Graph]:
    n = draw(st.integers(2, 8))
    kinds = draw(st.lists(st.sampled_from(["echo", "if"]), min_size=n, max_size=n))
    g = G()
    for i, kind in enumerate(kinds):
        if kind == "if":
            g.node(f"n{i}", "flow.if@1", {"condition": True})
        else:
            g.node(f"n{i}", "testkit.echo@1")
    edges: set[tuple[int, int, str]] = set()
    for j in range(1, n):
        for i in range(j):
            if draw(st.booleans()):
                port = draw(st.sampled_from(["true", "false"])) if kinds[i] == "if" else "out"
                edges.add((i, j, port))
    for i, j, port in sorted(edges):
        g.edge(f"n{i}", f"n{j}", port)
    return kinds, sorted(edges), g.build()


@settings(max_examples=200, deadline=None)
@given(dags())
def test_liveness_is_sound_against_simulated_runs(case: Any) -> None:
    kinds, edges, graph = case
    s, diags = analyze_structure(graph, CAT)
    assert s is not None and diags == []
    region = lv.analyze_region(s, None)
    ifs = [i for i, k in enumerate(kinds) if k == "if"]
    runs: list[list[bool]] = []
    for choice in itertools.product(["true", "false"], repeat=len(ifs)):
        decision = dict(zip(ifs, choice, strict=True))
        ran = [False] * len(kinds)
        for j in range(len(kinds)):
            incoming = [(i, p) for i, jj, p in edges if jj == j]
            ran[j] = not incoming or any(ran[i] and (kinds[i] == "echo" or decision[i] == p) for i, p in incoming)
        runs.append(ran)
    for c in range(len(kinds)):
        cond = region.live[nid(f"n{c}")]
        if lv.implies(lv.TRUE, cond):
            assert all(r[c] for r in runs), f"n{c} claimed to always run"
        for p in range(c):
            if lv.implies(cond, region.ok[nid(f"n{p}")]):
                assert all(r[p] for r in runs if r[c]), f"n{p} claimed available at n{c}"
```

`backend/tests/engine/graph/test_validate.py`:

```python
# SPDX-License-Identifier: Apache-2.0
import copy
import uuid
from datetime import timedelta
from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st
from jsonschema import Draft202012Validator

from dewpoint.engine.graph.model import GraphFormatError
from dewpoint.engine.graph.validate import (
    SubflowInfo,
    ValidationContext,
    ValidationResult,
    referenced_workflows,
    validate,
)
from dewpoint.plugins.flow import PLUGIN
from tests.engine.graph.test_values import JSON
from tests.support.catalog import catalog
from tests.support.graphs import G, cel, nid, ref, template
from tests.support.plugins.testkit import TESTKIT

CAT = catalog(PLUGIN, TESTKIT)
ECHO, IF, LOOP, SET = "testkit.echo@1", "flow.if@1", "flow.loop@1", "flow.set_variables@1"


def check(g: G, **ctx: Any) -> ValidationResult:
    return validate(g.build(), ValidationContext(catalog=CAT, **ctx))


def codes(g: G, **ctx: Any) -> list[str]:
    return [d.code for d in check(g, **ctx).diagnostics]


def test_linear_reference_is_available() -> None:
    g = G().node("a", ECHO, {"value": 1}).node("b", ECHO, {"value": ref("steps.a.output.value")}).edge("a", "b")
    result = check(g)
    assert result.ok and result.diagnostics == () and result.node_refs == (ECHO,)


def _diamond(consumer_value: Any) -> G:
    return (
        G()
        .node("c", IF, {"condition": True})
        .node("a", ECHO)
        .node("b", ECHO)
        .node("j", ECHO, {"value": consumer_value})
        .edge("c", "a", "true")
        .edge("c", "b", "false")
        .edge("a", "j")
        .edge("b", "j")
    )


def test_branch_reference_needs_a_default() -> None:
    assert codes(_diamond(ref("steps.a.output.value"))) == ["ref.conditional"]
    assert codes(_diamond(ref("steps.a.output.value", default=0))) == []
    assert codes(_diamond(ref("steps.c.output"))) == []  # the branch point itself always ran


def test_parallel_join_references_are_available() -> None:
    g = (
        G()
        .node("x", ECHO)
        .node("a", ECHO)
        .node("b", ECHO)
        .node("j", ECHO, {"value": [ref("steps.a.output.value"), ref("steps.b.output.value")]})
        .edge("x", "a")
        .edge("x", "b")
        .edge("a", "j")
        .edge("b", "j")
    )
    assert codes(g) == []


def test_error_port_references() -> None:
    def g(h_value: Any, b_value: Any = None) -> G:
        return (
            G()
            .node("a", ECHO, on_error="port")
            .node("b", ECHO, {"value": b_value})
            .node("h", ECHO, {"value": h_value})
            .edge("a", "b")
            .edge("a", "h", "error")
        )

    assert codes(g(ref("steps.a.error.code"), ref("steps.a.output.value"))) == []
    assert codes(g(ref("steps.a.output.value"))) == ["ref.conditional"]
    assert codes(g(None, ref("steps.a.error.code"))) == ["ref.conditional"]


def test_error_reference_needs_an_error_behaviour() -> None:
    g = G().node("a", ECHO).node("b", ECHO, {"value": ref("steps.a.error.message")}).edge("a", "b")
    assert codes(g) == ["ref.no_error_output"]
    g = G().node("a", ECHO, on_error="continue").node("b", ECHO, {"value": ref("steps.a.output.value")}).edge("a", "b")
    assert codes(g) == ["ref.conditional"]  # a failed step that continues has no output


def test_ordering_and_names() -> None:
    siblings = (
        G()
        .node("x", ECHO)
        .node("a", ECHO)
        .node("b", ECHO, {"value": ref("steps.a.output.value")})
        .edge("x", "a")
        .edge("x", "b")
    )
    assert codes(siblings) == ["ref.not_upstream"]
    assert codes(G().node("a", ECHO, {"value": ref("steps.nope.output")})) == ["ref.unknown_step"]
    assert codes(G().node("a", ECHO, {"value": ref("steps.a.output.value")})) == ["ref.not_upstream"]
    g = G().node("s", "testkit.sensitive@1").node("b", ECHO, {"value": ref("steps.s.output.nope")}).edge("s", "b")
    assert codes(g) == ["ref.unknown_field"]


def _loops(collect: Any, leaf_value: Any, after_value: Any = None) -> G:
    return (
        G()
        .node("outer", LOOP, {"items": [{"n": 1}], "collect": collect})
        .node("inner", LOOP, {"items": [1, 2]})
        .node("leaf", ECHO, {"value": leaf_value})
        .node("after", ECHO, {"value": after_value})
        .edge("outer", "inner", "body")
        .edge("inner", "leaf", "body")
        .edge("outer", "after", "done")
    )


def test_loop_scopes() -> None:
    assert codes(_loops(ref("steps.inner.output.count"), [ref("loop.item"), ref("loops.outer.item")])) == []
    assert codes(_loops(None, None, ref("loop.item"))) == ["ref.loop_outside"]
    assert codes(_loops(None, None, ref("steps.leaf.output.value"))) == ["ref.out_of_scope"]
    assert codes(_loops(ref("steps.leaf.output.value"), None)) == ["ref.out_of_scope"]
    assert codes(_loops(None, None, ref("steps.outer.output.count"))) == []


SITES = {
    "type": "object",
    "properties": {
        "sites": {
            "type": "array",
            "items": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
        }
    },
    "required": ["sites"],
}


def test_loop_item_is_typed_from_the_items_reference() -> None:
    def g(value: Any, schema: dict[str, Any] = SITES) -> G:
        b = G().node("l", LOOP, {"items": ref("trigger.sites")}).node("leaf", ECHO, {"value": value})
        b.edge("l", "leaf", "body").settings["input_schema"] = schema
        return b

    closed = copy.deepcopy(SITES)
    closed["properties"]["sites"]["items"]["additionalProperties"] = False
    assert codes(g(ref("loop.item.name"))) == []
    assert codes(g(ref("loop.item.nope"))) == ["ref.conditional"]  # open item schema: the field may exist
    assert codes(g(ref("loop.item.nope"), closed)) == ["ref.unknown_field"]


def test_undeclared_fields_of_open_schemas_are_possibly_missing() -> None:
    def g(value: Any) -> G:
        b = G().node("a", ECHO, {"value": value})
        b.settings["input_schema"] = {"type": "object", "properties": {"site": {"type": "string"}}}
        return b

    assert codes(g(ref("trigger.other"))) == ["ref.conditional"]
    assert codes(g(ref("trigger.other", default="x"))) == []


def test_a_union_source_must_fit_the_target_entirely() -> None:
    g = G().node("d", "flow.delay@1", {"duration_s": ref("trigger.wait")})
    g.settings["input_schema"] = {
        "type": "object",
        "properties": {"wait": {"type": ["string", "integer"]}},
        "required": ["wait"],
    }
    assert codes(g) == ["ref.type_mismatch"]


def test_composed_schemas_keep_each_producers_definitions() -> None:
    w1, w2 = uuid.UUID(int=1), uuid.UUID(int=2)

    def sub(workflow: uuid.UUID, item: str) -> SubflowInfo:
        out = {
            "type": "object",
            "properties": {"x": {"type": "object", "properties": {"v": {"$ref": "#/$defs/Item"}}, "required": ["v"]}},
            "required": ["x"],
            "additionalProperties": False,
            "$defs": {"Item": {"type": item}},
        }
        return SubflowInfo(workflow, uuid.UUID(int=10 + workflow.int), {"type": "object"}, out)

    g = (
        G()
        .node("r1", "flow.run_workflow@1", {"workflow_id": str(w1)})
        .node("r2", "flow.run_workflow@1", {"workflow_id": str(w2)})
        .node("t", "flow.transform@1", {"fields": {"a": ref("steps.r1.output.x"), "b": ref("steps.r2.output.x")}})
        .node("f", "flow.fail@1", {"message": ref("steps.t.output.a.v")})
        .node("d", "flow.delay@1", {"duration_s": ref("steps.t.output.b.v")})
        .edge("r1", "t")
        .edge("r2", "t")
        .edge("t", "f")
        .edge("t", "d")
    )
    g.settings["outputs"] = {"a": ref("steps.r1.output.x"), "b": ref("steps.r2.output.x")}
    result = check(g, subflows={w1: sub(w1, "string"), w2: sub(w2, "integer")})
    assert result.diagnostics == ()
    valid = {"a": {"v": "text"}, "b": {"v": 3}}
    assert list(Draft202012Validator(result.output_schema).iter_errors(valid)) == []


def test_type_mismatch() -> None:
    g = G().node("s", "testkit.sensitive@1").node("c", IF, {"condition": ref("steps.s.output.public")}).edge("s", "c")
    assert codes(g) == ["ref.type_mismatch"]


def test_literal_only_kinds_and_cel() -> None:
    computed = G().node("l", LOOP, {"items": [1], "concurrency": ref("vars.n", default=1)}).node("e", ECHO)
    assert codes(computed.edge("l", "e", "body")) == ["value.literal_only"]
    assert codes(G().node("f", "flow.filter@1", {"items": [1], "predicate": True})) == ["value.kind_not_allowed"]
    filtered = G().node("f", "flow.filter@1", {"items": [1], "predicate": ref("vars.x", default=True)})
    assert codes(filtered) == ["value.kind_not_allowed"]
    assert codes(G().node("f", "flow.filter@1", {"items": [1], "predicate": cel("item > 1")})) == ["cel.unavailable"]


def test_literal_config_is_validated() -> None:
    result = check(G().node("d", "flow.delay@1", {"duration_s": "soon"}))
    assert [(d.code, d.field) for d in result.diagnostics] == [("config.invalid", "/duration_s")]
    too_wide = G().node("l", LOOP, {"items": [1], "concurrency": 50}).node("e", ECHO).edge("l", "e", "body")
    assert codes(too_wide) == ["config.invalid"]


VARS = {"type": "object", "properties": {"count": {"type": "integer", "default": 0}}}


def _vars(g: G) -> G:
    g.settings["vars_schema"] = VARS
    return g


def test_variables() -> None:
    ok = G().node("s", SET, {"assignments": {"count": 1}}).node("b", ECHO, {"value": ref("vars.count")}).edge("s", "b")
    assert codes(_vars(ok)) == []
    assert codes(_vars(G().node("s", SET, {"assignments": {"count": "one"}}))) == ["config.invalid"]
    assert codes(_vars(G().node("s", SET, {"assignments": {"nope": 1}}))) == ["vars.undeclared"]
    in_loop = G().node("l", LOOP, {"items": [1]}).node("s", SET, {"assignments": {"count": 1}}).edge("l", "s", "body")
    assert codes(_vars(in_loop)) == ["vars.write_in_loop"]
    parallel = (
        G()
        .node("x", ECHO)
        .node("s1", SET, {"assignments": {"count": 1}})
        .node("s2", SET, {"assignments": {"count": 2}})
        .edge("x", "s1")
        .edge("x", "s2")
    )
    assert codes(_vars(parallel)) == ["vars.concurrent_writers"]
    exclusive = (
        G()
        .node("c", IF, {"condition": True})
        .node("s1", SET, {"assignments": {"count": 1}})
        .node("s2", SET, {"assignments": {"count": 2}})
        .edge("c", "s1", "true")
        .edge("c", "s2", "false")
    )
    assert codes(_vars(exclusive)) == []
    no_default = G().node("a", ECHO)
    no_default.settings["vars_schema"] = {"type": "object", "properties": {"x": {"type": "string"}}}
    assert codes(no_default) == ["vars.no_default"]


def test_settings_schemas_must_use_resolvable_local_refs() -> None:
    missing = G().node("a", ECHO)
    missing.settings["vars_schema"] = {"type": "object", "properties": {"x": {"$ref": "#/$defs/Missing", "default": 1}}}
    assert codes(missing) == ["settings.unresolvable_ref"]  # reported, never raised
    remote = G().node("a", ECHO)
    remote.settings["input_schema"] = {"type": "object", "properties": {"s": {"$ref": "https://example.com/s.json"}}}
    assert codes(remote) == ["settings.unresolvable_ref"]
    cyclic = G().node("a", ECHO)
    cyclic.settings["vars_schema"] = {
        "type": "object",
        "properties": {"x": {"$ref": "#/$defs/A", "default": 1}},
        "$defs": {"A": {"allOf": [{"$ref": "#/$defs/A"}]}},
    }
    assert codes(cyclic) == ["settings.unresolvable_ref"]
    data = G().node("a", ECHO)
    data.settings["vars_schema"] = {
        "type": "object",
        "properties": {"x": {"type": "object", "default": {"$ref": "literal data", "$id": "also data"}}},
    }
    assert codes(data) == []  # defaults are data, not schemas


def test_static_waits_must_fit_the_run_deadline() -> None:
    day = 86_400
    g = (
        G()
        .node("d1", "flow.delay@1", {"duration_s": 20 * day})
        .node("d2", "flow.delay@1", {"duration_s": 15 * day})
        .edge("d1", "d2")
    )
    assert codes(g) == ["wait.exceeds_deadline"]
    assert codes(g, max_run_duration=timedelta(days=40)) == []


W = uuid.UUID("0b0e7a52-3d6c-4a53-9b58-7c2f0d4a1e11")
V = uuid.UUID("5a2f1c3e-8d9b-4c7a-a6e5-2b1d0f9e8c77")
SUB = SubflowInfo(
    workflow_id=W,
    version_id=V,
    input_schema={
        "type": "object",
        "properties": {"site": {"type": "string"}},
        "required": ["site"],
        "additionalProperties": False,
    },
    output_schema={
        "type": "object",
        "properties": {"count": {"type": "integer"}},
        "required": ["count"],
        "additionalProperties": False,
    },
)


def _sub(input_: dict[str, Any]) -> G:
    return (
        G()
        .node("r", "flow.run_workflow@1", {"workflow_id": str(W), "input": input_})
        .node("b", ECHO, {"value": ref("steps.r.output.count")})
        .edge("r", "b")
    )


def test_subflow_pins_and_typing() -> None:
    result = check(_sub({"site": "paris"}), subflows={W: SUB})
    assert result.ok and result.subflow_pins == {str(nid("r")): str(V)}
    assert codes(_sub({}), subflows={W: SUB}) == ["config.invalid"]
    assert codes(_sub({"site": "paris"})) == ["subflow.unknown"]
    handler = _sub({"site": "x"})
    handler.settings["failure_handler"] = str(V)
    assert referenced_workflows(handler.build()) == {W, V}


def test_workflow_outputs_define_the_output_schema() -> None:
    g = G().node("a", ECHO, {"value": 1})
    g.settings["outputs"] = {"total": ref("steps.a.output.value"), "label": "fixed"}
    result = check(g)
    assert result.ok and result.output_schema["required"] == ["label", "total"]
    d = _diamond(None)
    d.settings["outputs"] = {"picked": ref("steps.a.output.value")}
    assert codes(d) == ["ref.conditional"]
    s = G().node("x", ECHO).node("a", ECHO).node("stop", "flow.stop@1").edge("x", "a").edge("x", "stop")
    s.settings["outputs"] = {"v": ref("steps.a.output.value")}
    assert codes(s) == ["ref.conditional"]  # `stop` may end the run before `a` finishes


def test_templates() -> None:
    assert codes(G().node("d", "flow.delay@1", {"duration_s": template("5")})) == ["template.not_string"]
    whole = template("failed: ", {"ref": "steps.s.output"})
    g = G().node("s", "testkit.sensitive@1").node("f", "flow.fail@1", {"message": whole}).edge("s", "f")
    assert codes(g) == ["template.part_not_scalar"]
    part = template("failed: ", {"ref": "steps.s.output.public"})
    ok = G().node("s", "testkit.sensitive@1").node("f", "flow.fail@1", {"message": part}).edge("s", "f")
    assert codes(ok) == []


def test_transform_output_is_typed_from_its_fields() -> None:
    def g(condition: Any) -> G:
        return (
            G()
            .node("s", "testkit.sensitive@1")
            .node("t", "flow.transform@1", {"fields": {"name": ref("steps.s.output.public"), "n": 3}})
            .node("c", IF, {"condition": condition})
            .edge("s", "t")
            .edge("t", "c")
        )

    assert codes(g(ref("steps.t.output.name"))) == ["ref.type_mismatch"]  # text into a boolean
    assert codes(g(ref("steps.t.output.nope"))) == ["ref.unknown_field"]


CONFIG = st.dictionaries(
    st.sampled_from(
        [
            "value",
            "condition",
            "items",
            "cases",
            "collect",
            "predicate",
            "assignments",
            "duration_s",
            "until",
            "message",
            "workflow_id",
            "input",
            "fields",
            "concurrency",
        ]
    )
    | st.text(max_size=5),
    JSON,
    max_size=5,
)
TYPES = st.sampled_from(
    [
        ECHO,
        IF,
        LOOP,
        SET,
        "flow.switch@1",
        "flow.filter@1",
        "flow.delay@1",
        "flow.wait_until@1",
        "flow.fail@1",
        "flow.run_workflow@1",
        "flow.transform@1",
        "flow.stop@1",
    ]
)


@settings(max_examples=300, deadline=None)
@given(
    st.lists(st.tuples(TYPES, CONFIG), min_size=1, max_size=4), st.dictionaries(st.text(max_size=5), JSON, max_size=3)
)
def test_validate_reports_never_raises_on_arbitrary_configs(nodes: Any, outputs: Any) -> None:
    g = G()
    for index, (type_ref, config) in enumerate(nodes):
        g.node(f"n{index}", type_ref, config)
    for index in range(1, len(nodes)):
        g.edge(f"n{index - 1}", f"n{index}", "true" if nodes[index - 1][0] == IF else "out")
    g.settings["outputs"] = outputs
    try:
        graph = g.build()
    except GraphFormatError:
        return  # rejected at parse time, which is also a report
    validate(graph, ValidationContext(catalog=CAT))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/engine/graph/test_liveness.py tests/engine/graph/test_validate.py -q`
Expected: FAIL: `ImportError: cannot import name 'liveness'`.

- [ ] **Step 3: Implement liveness conditions**

`backend/src/dewpoint/engine/graph/liveness.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""When is a step guaranteed to have completed? (spec §4.3 path availability)

Each region (the root, or one loop body) is analysed separately. A step's liveness condition is a formula in
disjunctive normal form over branch decisions: which port a branching step took. A parallel fan-out adds no
literals, so a join after it is live exactly when its inputs are. Dominators would wrongly reject that case. For
exclusive branches the result matches dominance. `None` means "too complex to analyse", and callers treat it
conservatively."""

import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from dewpoint.engine.graph.structure import Structure
from dewpoint.engine.registry import control as C

Lit = tuple[uuid.UUID, str]
Term = frozenset[Lit]
Cond = frozenset[Term] | None
TRUE: frozenset[Term] = frozenset({frozenset()})
FALSE: frozenset[Term] = frozenset()
ERR = "#err"
MAX_TERMS = 256


def _consistent(term: Term) -> bool:
    seen: dict[uuid.UUID, str] = {}
    return all(seen.setdefault(node, value) == value for node, value in term)


def simplify(terms: Iterable[Term], values: Mapping[uuid.UUID, tuple[str, ...]]) -> Cond:
    """Drop contradictions, absorb supersets, and merge terms that cover every value of one decision."""
    current = {t for t in terms if _consistent(t)}
    while True:
        if len(current) > MAX_TERMS:
            return None
        current = {t for t in current if not any(other < t for other in current)}
        additions: set[Term] = set()
        for term in current:
            for node, _ in term:
                options = values.get(node, ())
                base = frozenset(lit for lit in term if lit[0] != node)
                if base not in current and options and all(base | {(node, v)} in current for v in options):
                    additions.add(base)
        if not additions:
            return frozenset(current)
        current |= additions


def implies(consumer: Cond, producer: Cond) -> bool:
    """True when every situation in `consumer` guarantees `producer`. Sound; may say False when unsure."""
    if producer is None:
        return False
    if frozenset() in producer:
        return True
    if consumer is None:
        return False
    return all(any(p <= c for p in producer) for c in consumer)


def exclusive(a: Cond, b: Cond) -> bool:
    """True when the two conditions can never hold together."""
    if a is None or b is None:
        return False
    return all(not _consistent(x | y) for x in a for y in b)


def _add(cond: Cond, lit: Lit) -> Cond:
    return None if cond is None else frozenset(t | {lit} for t in cond)


def _union(conds: Iterable[Cond], values: Mapping[uuid.UUID, tuple[str, ...]]) -> Cond:
    terms: set[Term] = set()
    for cond in conds:
        if cond is None:
            return None
        terms |= cond
    return simplify(terms, values)


@dataclass(frozen=True)
class RegionLiveness:
    live: Mapping[uuid.UUID, Cond]  # the step runs
    ok: Mapping[uuid.UUID, Cond]  # the step ran and succeeded (its output exists)
    err: Mapping[uuid.UUID, Cond]  # the step ran and followed its error port
    exit: Cond  # the region finished normally (not through `fail`)


def normal_ports(s: Structure, node: uuid.UUID) -> tuple[str, ...]:
    ports = s.ports[node]
    return tuple(p for p in ports if p != "body") if s.specs[node].ref == C.LOOP else ports


def analyze_region(s: Structure, region: uuid.UUID | None) -> RegionLiveness:
    members = s.regions[region].members
    member_set = set(members)
    values: dict[uuid.UUID, tuple[str, ...]] = {
        n: normal_ports(s, n) + ((ERR,) if s.nodes[n].options.on_error == "port" else ()) for n in members
    }
    live: dict[uuid.UUID, Cond] = {}

    def edge(src: uuid.UUID, port: str) -> Cond:
        value = ERR if port == "error" else port
        return _add(live[src], (src, value)) if len(values[src]) > 1 else live[src]

    for n in members:
        incoming: list[Cond] = []
        for e in s.in_edges[n]:
            # An edge from outside the members can only be the loop's `body` port, which opens this region.
            incoming.append(TRUE if e.source.node not in member_set else edge(e.source.node, e.source.port))
        live[n] = TRUE if not incoming else _union(incoming, values)

    ok: dict[uuid.UUID, Cond] = {}
    err: dict[uuid.UUID, Cond] = {}
    for n in members:
        normal = normal_ports(s, n)
        if s.nodes[n].options.on_error == "port" and normal:
            ok[n] = _union((_add(live[n], (n, p)) for p in normal), values)
        else:
            ok[n] = live[n]
        err[n] = _add(live[n], (n, ERR)) if s.nodes[n].options.on_error == "port" else FALSE

    ends: list[Cond] = []
    for n in members:
        if s.specs[n].ref == C.FAIL:
            continue
        normal = normal_ports(s, n)
        if not normal:
            ends.append(live[n])  # `stop` ends the scope successfully
        for p in normal:
            if not any(e.source.port == p and e.to.node in member_set for e in s.out_edges[n]):
                ends.append(edge(n, p))
    return RegionLiveness(live=live, ok=ok, err=err, exit=_union(ends, values))
```

- [ ] **Step 4: Implement the validator**

`backend/src/dewpoint/engine/graph/validate.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""Publish-time validation of a workflow graph (spec §4). Pure: the caller loads the catalog and sub-flow data."""

import contextlib
import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from dewpoint.engine.graph import liveness as lv
from dewpoint.engine.graph.diagnostics import Diagnostic
from dewpoint.engine.graph.model import Graph, GraphNode
from dewpoint.engine.graph.schemas import (
    PathError,
    Resolved,
    allowed_kinds,
    compatible,
    contains_literal,
    describe,
    element_schema,
    json_types,
    literal_on_path,
    literal_type,
    navigate,
    object_schema,
    standalone,
    target_schema,
)
from dewpoint.engine.graph.structure import Structure, analyze_structure
from dewpoint.engine.graph.values import (
    ENVELOPE,
    LiteralValue,
    Pointer,
    RefPath,
    RefValue,
    TemplateRef,
    TemplateValue,
    Value,
    ValueSyntaxError,
    is_envelope,
    iter_values,
    pointer_str,
    strip_values,
)
from dewpoint.engine.registry import control as C
from dewpoint.engine.registry.catalog import Catalog, NodeTypeSpec
from dewpoint.engine.schema_refs import ref_problems
from dewpoint.sdk.fields import KINDS

MAX_SUBFLOW_DEPTH = 5
IDENT = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
ERROR_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"code": {"type": "string"}, "message": {"type": "string"}, "attempt": {"type": "integer"}},
    "required": ["code", "message", "attempt"],
    "additionalProperties": False,
}
RUN_SCHEMAS: dict[str, dict[str, Any]] = {
    "id": {"type": "string", "format": "uuid"},
    "started_at": {"type": "string", "format": "date-time"},
    "now": {"type": "string", "format": "date-time"},
}
_WHOLE_LITERAL = {(C.SET_VARIABLES, "assignments"), (C.TRANSFORM, "fields")}
_LITERAL_ONLY = "This field must be written directly; it can't come from another step."


@dataclass(frozen=True)
class SubflowInfo:
    workflow_id: uuid.UUID
    version_id: uuid.UUID
    input_schema: Mapping[str, Any]
    output_schema: Mapping[str, Any]


@dataclass(frozen=True)
class ValidationContext:
    catalog: Catalog
    subflows: Mapping[uuid.UUID, SubflowInfo] = field(default_factory=dict)
    max_run_duration: timedelta = timedelta(days=30)


@dataclass(frozen=True)
class ValidationResult:
    diagnostics: tuple[Diagnostic, ...]
    node_refs: tuple[str, ...] = ()
    subflow_pins: Mapping[str, str] = field(default_factory=dict)  # node id -> pinned version id
    failure_handler_version_id: uuid.UUID | None = None
    output_schema: Mapping[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not any(d.severity == "error" for d in self.diagnostics)


def referenced_workflows(graph: Graph) -> set[uuid.UUID]:
    """Workflows this graph pins (run_workflow targets and the failure handler). The caller loads their active
    versions and passes them back through ValidationContext.subflows."""
    out: set[uuid.UUID] = set()
    for n in graph.nodes:
        raw = n.config.get("workflow_id")
        if n.type == C.RUN_WORKFLOW and isinstance(raw, str):
            with contextlib.suppress(ValueError):
                out.add(uuid.UUID(raw))
    if graph.settings.failure_handler is not None:
        out.add(graph.settings.failure_handler)
    return out


@dataclass(frozen=True)
class _Site:
    node: uuid.UUID | None  # None for workflow outputs
    field: str  # JSON pointer, for diagnostics
    region: uuid.UUID | None  # the scope the value is evaluated in
    at_exit: bool = False  # evaluated when that scope ends (loop `collect`, workflow outputs)


def _descendants(s: Structure) -> dict[uuid.UUID, frozenset[uuid.UUID]]:
    desc: dict[uuid.UUID, frozenset[uuid.UUID]] = {}
    for n in reversed(s.topo):
        acc: set[uuid.UUID] = set()
        for e in s.out_edges[n]:
            acc.add(e.to.node)
            acc |= desc[e.to.node]
        desc[n] = frozenset(acc)
    return desc


def _static_delay(node: GraphNode, spec: NodeTypeSpec) -> float:
    if spec.ref != C.DELAY:
        return 0.0
    raw: Any = node.config.get("duration_s")
    body = raw.get(ENVELOPE) if is_envelope(raw) else None
    if isinstance(body, Mapping) and body.get("kind") == "literal":
        raw = body.get("value")
    return float(raw) if isinstance(raw, int) and not isinstance(raw, bool) and raw > 0 else 0.0


def _settings(graph: Graph) -> list[Diagnostic]:
    st = graph.settings
    out: list[Diagnostic] = []
    for label, schema in (("input_schema", st.input_schema), ("vars_schema", st.vars_schema)):
        try:
            Draft202012Validator.check_schema(schema)
        except SchemaError as e:
            out.append(
                Diagnostic(
                    code="settings.invalid_schema",
                    field=f"/settings/{label}",
                    message=f"Not a valid JSON Schema: {e.message}",
                )
            )
            continue
        if schema.get("type", "object") != "object":
            out.append(
                Diagnostic(
                    code="settings.invalid_schema", field=f"/settings/{label}", message="It must describe an object."
                )
            )
        # Tenant-authored schemas: only resolvable local $refs, so validation can never raise (see schema_refs).
        out += [
            Diagnostic(code="settings.unresolvable_ref", field=f"/settings/{label}", message=f"{problem}.")
            for problem in ref_problems(schema)
        ]
    if any(d.field == "/settings/vars_schema" for d in out):
        return out
    props = st.vars_schema.get("properties", {})
    defs = st.vars_schema.get("$defs", {})
    for name, schema in props.items() if isinstance(props, Mapping) else ():
        where = f"/settings/vars_schema/properties/{name}"
        if not IDENT.match(name):
            out.append(
                Diagnostic(code="vars.invalid_name", field=where, message="Variable names are lowercase identifiers.")
            )
        if not isinstance(schema, Mapping) or "default" not in schema:
            out.append(Diagnostic(code="vars.no_default", field=where, message="Every variable needs a default value."))
        elif list(Draft202012Validator({**schema, "$defs": defs}).iter_errors(schema["default"])):
            out.append(
                Diagnostic(code="vars.bad_default", field=where, message="The default value doesn't match the type.")
            )
    for name in st.outputs:
        if not IDENT.match(name):
            out.append(
                Diagnostic(
                    code="settings.output_name",
                    field=f"/settings/outputs/{name}",
                    message="Output names are lowercase identifiers.",
                )
            )
    return out


class _Validator:
    def __init__(self, graph: Graph, s: Structure, ctx: ValidationContext, settings_ok: bool) -> None:
        self.g, self.s, self.ctx = graph, s, ctx
        self.diags: list[Diagnostic] = []
        self.live = {r: lv.analyze_region(s, r) for r in s.regions}
        self.desc = _descendants(s)
        self.out_schema: dict[uuid.UUID, Mapping[str, Any] | None] = {}
        self.item_schema: dict[uuid.UUID, Mapping[str, Any] | None] = {}
        self.pins: dict[str, str] = {}
        self.failure_handler_version_id: uuid.UUID | None = None
        self.output_schema: dict[str, Any] = {}
        self.deferred: list[tuple[_Site, Value | ValueSyntaxError]] = []
        vars_schema = graph.settings.vars_schema
        props = vars_schema.get("properties") if settings_ok else None
        self.vars: dict[str, Any] = dict(props) if isinstance(props, Mapping) else {}
        self.vars_root: dict[str, Any] = {"type": "object", "properties": self.vars, "additionalProperties": False}
        if settings_ok and isinstance(vars_schema.get("$defs"), Mapping):
            self.vars_root["$defs"] = vars_schema["$defs"]
        self.root_has_stop = any(s.specs[i].ref == C.STOP for i in s.regions[None].members)

    def err(
        self, code: str, message: str, *, node: uuid.UUID | None = None, fld: str | None = None, fix: str | None = None
    ) -> None:
        self.diags.append(Diagnostic(code=code, message=message, node=node, field=fld, fix=fix))

    def run(self) -> None:
        for n_id in self.s.topo:
            self._node(self.s.nodes[n_id])
        for site, value in self.deferred:
            self._value(site, value, None, ())
        self._variables()
        self._waits()
        self._outputs()
        self._failure_handler()

    # ---- per node -------------------------------------------------------------------------------------------

    def _node(self, n: GraphNode) -> None:
        spec = self.s.specs[n.id]
        self._check_literals(n, spec)
        resolved: dict[Pointer, Resolved | None] = {}
        region = self.s.region_of[n.id]
        for pointer, value in iter_values(n.config):
            where = pointer_str(pointer)
            if not pointer or ((spec.ref, pointer[0]) in _WHOLE_LITERAL and len(pointer) == 1):
                self.err("value.literal_only", _LITERAL_ONLY, node=n.id, fld=where)
                continue
            if spec.ref == C.LOOP and pointer[0] == "collect":
                self.deferred.append((_Site(n.id, where, n.id, at_exit=True), value))
                continue
            root, inner = self._value_root(n, spec, pointer)
            resolved[pointer] = self._value(_Site(n.id, where, region), value, root, inner)
        if spec.ref == C.LOOP:
            items = resolved.get(("items",))
            self.item_schema[n.id] = element_schema(items.schema) if items is not None else None
        elif spec.ref == C.RUN_WORKFLOW:
            info = self._subflow(n)
            if info is None:
                self.err(
                    "subflow.unknown",
                    "The workflow this step runs doesn't exist here or has no published version.",
                    node=n.id,
                    fld="/workflow_id",
                    fix="Publish that workflow first.",
                )
            else:
                self.pins[str(n.id)] = str(info.version_id)
        self.out_schema[n.id] = self._output_schema(n, spec, resolved)

    def _subflow(self, n: GraphNode) -> SubflowInfo | None:
        raw = n.config.get("workflow_id")
        if not isinstance(raw, str):
            return None
        try:
            return self.ctx.subflows.get(uuid.UUID(raw))
        except ValueError:
            return None

    def _value_root(
        self, n: GraphNode, spec: NodeTypeSpec, pointer: Pointer
    ) -> tuple[Mapping[str, Any] | None, Pointer]:
        if spec.ref == C.SET_VARIABLES and pointer[0] == "assignments":
            return self.vars_root, pointer[1:]
        if spec.ref == C.RUN_WORKFLOW and pointer[0] == "input":
            info = self._subflow(n)
            return (info.input_schema if info else None), pointer[1:]
        return spec.config_schema, pointer

    def _check_literals(self, n: GraphNode, spec: NodeTypeSpec) -> None:
        stripped, envelopes = strip_values(n.config)
        self._schema_errors(n.id, "", spec.config_schema, stripped, envelopes)
        props = spec.config_schema.get("properties")
        for name, prop in props.items() if isinstance(props, Mapping) else ():
            kinds = prop.get(KINDS) if isinstance(prop, Mapping) else None
            written = name in n.config and not is_envelope(n.config[name])
            if isinstance(kinds, list) and "literal" not in kinds and written:
                self.err(
                    "value.kind_not_allowed",
                    f"This field accepts only: {', '.join(sorted(kinds))}.",
                    node=n.id,
                    fld=pointer_str((name,)),
                )
        if not isinstance(stripped, dict):
            return
        if spec.ref == C.SET_VARIABLES and isinstance(stripped.get("assignments"), dict):
            for name, value in stripped["assignments"].items():
                if name in self.vars:
                    inner = [p[2:] for p in envelopes if p[:2] == ("assignments", name)]
                    schema = standalone(self.vars_root, self.vars[name])
                    self._schema_errors(n.id, pointer_str(("assignments", name)), schema, value, inner)
        if spec.ref == C.RUN_WORKFLOW:
            info = self._subflow(n)
            if info is not None:
                inner = [p[1:] for p in envelopes if p[:1] == ("input",)]
                self._schema_errors(n.id, "/input", info.input_schema, stripped.get("input", {}), inner)

    def _schema_errors(
        self, node: uuid.UUID, prefix: str, schema: Mapping[str, Any], instance: Any, envelopes: list[Pointer]
    ) -> None:
        errors = sorted(Draft202012Validator(schema).iter_errors(instance), key=lambda e: str(list(e.absolute_path)))
        for e in errors:
            path = tuple(e.absolute_path)
            if any(path[: len(p)] == p for p in envelopes):
                continue  # computed at run time; checked through its reference type instead
            self.err("config.invalid", e.message, node=node, fld=prefix + pointer_str(path))

    def _output_schema(
        self, n: GraphNode, spec: NodeTypeSpec, resolved: Mapping[Pointer, Resolved | None]
    ) -> Mapping[str, Any] | None:
        if spec.ref == C.RUN_WORKFLOW:
            info = self._subflow(n)
            return info.output_schema if info else None
        if spec.ref == C.TRANSFORM:
            fields = n.config.get("fields")
            if not isinstance(fields, Mapping) or is_envelope(fields):
                return None
            props: dict[str, Mapping[str, Any]] = {}
            required: list[str] = []
            for name in sorted(fields):
                if is_envelope(fields[name]):
                    r = resolved.get(("fields", name))
                    props[name] = r.schema if r is not None and r.schema is not None else {}
                    if r is not None and not r.conditional:
                        required.append(name)
                else:
                    props[name] = {"type": literal_type(fields[name])}
                    required.append(name)
            return object_schema(props, required)
        return spec.output_schema

    # ---- values ---------------------------------------------------------------------------------------------

    def _value(
        self, site: _Site, value: Value | ValueSyntaxError, root: Mapping[str, Any] | None, pointer: Pointer
    ) -> Resolved | None:
        if isinstance(value, ValueSyntaxError):
            self.err("value.syntax", value.message, node=site.node, fld=site.field)
            return None
        target = target_schema(root, pointer) if root is not None else None
        if (
            root is not None
            and value.kind != "literal"
            and (literal_on_path(root, pointer) or contains_literal(root, target))
        ):
            self.err("value.literal_only", _LITERAL_ONLY, node=site.node, fld=site.field)
            return None
        kinds = allowed_kinds(root, pointer) if root is not None else None
        if kinds is not None and value.kind not in kinds:
            self.err(
                "value.kind_not_allowed",
                f"This field accepts only: {', '.join(sorted(kinds))}.",
                node=site.node,
                fld=site.field,
            )
            return None
        if isinstance(value, LiteralValue):
            self._check_instance(site, target, value.value)
            return Resolved({"type": literal_type(value.value)}, False)
        if isinstance(value, RefValue):
            return self._ref_value(site, value, target)
        if isinstance(value, TemplateValue):
            return self._template(site, value, target)
        self.err(
            "cel.unavailable",
            "CEL expressions aren't available in this build yet.",
            node=site.node,
            fld=site.field,
            fix="Use a reference or a template for now.",
        )
        return None

    def _check_instance(self, site: _Site, schema: Mapping[str, Any] | None, instance: Any) -> None:
        if schema is None:
            return
        for e in sorted(Draft202012Validator(schema).iter_errors(instance), key=lambda e: str(list(e.absolute_path))):
            self.err("config.invalid", e.message, node=site.node, fld=site.field + pointer_str(tuple(e.absolute_path)))

    def _ref_value(self, site: _Site, value: RefValue, target: Mapping[str, Any] | None) -> Resolved | None:
        resolved = self._resolve(site, value.path)
        if resolved is None:
            return None
        if resolved.conditional and not value.has_default:
            self.err(
                "ref.conditional",
                f"`{value.path.text}` may be missing when this runs: a branch may skip it, or the field is optional.",
                node=site.node,
                fld=site.field,
                fix="Add a default value.",
            )
        if not compatible(resolved.schema, target):
            self.err(
                "ref.type_mismatch",
                f"`{value.path.text}` is {describe(resolved.schema)}, but this field expects {describe(target)}.",
                node=site.node,
                fld=site.field,
            )
        if value.has_default:
            self._check_instance(site, target, value.default)
        return Resolved(resolved.schema, resolved.conditional and not value.has_default)

    def _template(self, site: _Site, value: TemplateValue, target: Mapping[str, Any] | None) -> Resolved:
        if target is not None and not compatible({"type": "string"}, target):
            self.err(
                "template.not_string", "Text with references can only fill text fields.", node=site.node, fld=site.field
            )
        for part in value.parts:
            if not isinstance(part, TemplateRef):
                continue
            r = self._resolve(site, part.path)
            if r is None:
                continue
            if r.conditional and part.default is None:
                self.err(
                    "ref.conditional",
                    f"`{part.path.text}` may be missing when this runs.",
                    node=site.node,
                    fld=site.field,
                    fix="Give this part a default.",
                )
            types = json_types(r.schema)
            if types is not None and types & {"object", "array"}:
                self.err(
                    "template.part_not_scalar",
                    f"`{part.path.text}` is {describe(r.schema)}; only text, numbers and booleans go into text.",
                    node=site.node,
                    fld=site.field,
                )
        return Resolved({"type": "string"}, False)

    # ---- references -----------------------------------------------------------------------------------------

    def _resolve(self, site: _Site, p: RefPath) -> Resolved | None:
        try:
            if p.root == "trigger":
                return navigate(self.g.settings.input_schema, p.rest)
            if p.root == "run":
                return Resolved(RUN_SCHEMAS[str(p.section)], False)
            if p.root == "vars":
                if p.name not in self.vars:
                    self.err(
                        "ref.unknown_var", f"`{p.name}` isn't a declared variable.", node=site.node, fld=site.field
                    )
                    return None
                return navigate(self.vars_root, p.rest, start=self.vars[str(p.name)])
            if p.root in ("loop", "loops"):
                return self._resolve_loop(site, p)
            return self._resolve_step(site, p)
        except PathError as e:
            self.err("ref.unknown_field", f"`{p.text}`: {e}", node=site.node, fld=site.field)
            return None

    def _resolve_loop(self, site: _Site, p: RefPath) -> Resolved | None:
        if p.root == "loop":
            loop = site.region
            if loop is None:
                self.err(
                    "ref.loop_outside",
                    "`loop.*` is only available inside a loop's body.",
                    node=site.node,
                    fld=site.field,
                )
                return None
        else:
            found = self.s.by_key.get(str(p.name))
            if found is None or self.s.specs[found].ref != C.LOOP:
                self.err("ref.unknown_step", f"There's no loop called `{p.name}`.", node=site.node, fld=site.field)
                return None
            if found not in self.s.chain(site.region):
                self.err(
                    "ref.loop_outside",
                    f"`{p.text}` is only available inside loop `{p.name}`.",
                    node=site.node,
                    fld=site.field,
                )
                return None
            loop = found
        if p.section == "index":
            return Resolved({"type": "integer"}, False)
        item = self.item_schema.get(loop)
        if item is None:
            return Resolved(None, bool(p.rest))
        return navigate(item, p.rest)

    def _resolve_step(self, site: _Site, p: RefPath) -> Resolved | None:
        producer = self.s.by_key.get(str(p.name))
        if producer is None:
            self.err("ref.unknown_step", f"There's no step called `{p.name}`.", node=site.node, fld=site.field)
            return None
        home = self.s.region_of[producer]
        chain = self.s.chain(site.region)
        if home not in chain:
            self.err(
                "ref.out_of_scope",
                f"`{p.name}` runs inside a loop body, so its result isn't available here.",
                node=site.node,
                fld=site.field,
                fix="Return it through the loop's `collect` value.",
            )
            return None
        region = self.live[home]
        consumer: lv.Cond
        if home == site.region and site.at_exit:
            consumer, upstream = region.exit, True
        elif home == site.region and site.node is not None:
            consumer, upstream = region.live[site.node], site.node in self.desc[producer]
        else:
            ancestor = chain[chain.index(home) - 1]  # the loop node, in `home`, that contains the consumer
            if ancestor is None:
                return None
            consumer, upstream = region.live[ancestor], ancestor in self.desc[producer]
        if not upstream:
            self.err(
                "ref.not_upstream",
                f"`{p.name}` doesn't run before this step.",
                node=site.node,
                fld=site.field,
                fix="Connect it upstream of this step.",
            )
            return None
        on_error = self.s.nodes[producer].options.on_error
        if p.section == "error":
            if on_error == "fail":
                self.err(
                    "ref.no_error_output",
                    f"`{p.name}` stops the run when it fails, so it never has an error value.",
                    node=site.node,
                    fld=site.field,
                    fix="Set its error behaviour to continue or to an error output.",
                )
                return None
            available = on_error == "port" and lv.implies(consumer, region.err[producer])
            r = navigate(ERROR_SCHEMA, p.rest)
            return Resolved(r.schema, r.conditional or not available)
        available = on_error != "continue" and lv.implies(consumer, region.ok[producer])
        if site.at_exit and site.region is None and self.root_has_stop:
            available = False  # `stop` may end the run while this step is still pending
        schema = self.out_schema.get(producer)
        if schema is None:  # only when the producer is already reported (unknown sub-flow): don't add noise
            return Resolved(None, not available)
        r = navigate(schema, p.rest)
        return Resolved(r.schema, r.conditional or not available)

    # ---- whole-graph checks ---------------------------------------------------------------------------------

    def _variables(self) -> None:
        writers: dict[str, list[uuid.UUID]] = {}
        for n_id in self.s.topo:
            n = self.s.nodes[n_id]
            if self.s.specs[n_id].ref != C.SET_VARIABLES:
                continue
            if self.s.region_of[n_id] is not None:
                self.err(
                    "vars.write_in_loop",
                    "Variables can't be set inside a loop body.",
                    node=n_id,
                    fix="Return per-item results through the loop's `collect` value.",
                )
                continue
            assignments = n.config.get("assignments")
            if not isinstance(assignments, Mapping) or is_envelope(assignments):
                continue
            for name in assignments:
                if name not in self.vars:
                    self.err(
                        "vars.undeclared",
                        f"`{name}` isn't declared.",
                        node=n_id,
                        fld=pointer_str(("assignments", name)),
                        fix="Declare it in the workflow's variables.",
                    )
                    continue
                writers.setdefault(name, []).append(n_id)
        root = self.live[None]
        for name, nodes in writers.items():
            for i, a in enumerate(nodes):
                for b in nodes[i + 1 :]:
                    ordered = b in self.desc[a] or a in self.desc[b]
                    if not ordered and not lv.exclusive(root.live[a], root.live[b]):
                        self.err(
                            "vars.concurrent_writers",
                            f"`{self.s.nodes[a].key}` and `{self.s.nodes[b].key}` can both set `{name}` at once.",
                            node=b,
                            fix="Order them, or put them on exclusive branches.",
                        )

    def _waits(self) -> None:
        limit = self.ctx.max_run_duration.total_seconds()
        longest: dict[uuid.UUID, float] = {}
        for n_id in self.s.topo:
            before = max((longest[e.source.node] for e in self.s.in_edges[n_id]), default=0.0)
            own = _static_delay(self.s.nodes[n_id], self.s.specs[n_id])
            longest[n_id] = before + own
            if own and longest[n_id] > limit:
                self.err(
                    "wait.exceeds_deadline",
                    f"Waits on this path add up to {longest[n_id] / 86_400:.1f} days, more than the "
                    f"{limit / 86_400:.0f}-day run limit.",
                    node=n_id,
                )

    def _outputs(self) -> None:
        props: dict[str, Mapping[str, Any]] = {}
        required: list[str] = []
        for name in sorted(self.g.settings.outputs):
            raw = self.g.settings.outputs[name]
            where = pointer_str(("settings", "outputs", name))
            if is_envelope(raw):
                [(_, value)] = list(iter_values(raw))
                r = self._value(_Site(None, where, None, at_exit=True), value, None, ())
                props[name] = r.schema if r is not None and r.schema is not None else {}
                if r is not None and not r.conditional:
                    required.append(name)
                continue
            for pointer, value in iter_values(raw):
                self._value(_Site(None, where + pointer_str(pointer), None, at_exit=True), value, None, ())
            props[name] = {"type": literal_type(raw)}
            required.append(name)
        self.output_schema = object_schema(props, required)

    def _failure_handler(self) -> None:
        workflow = self.g.settings.failure_handler
        if workflow is None:
            return
        info = self.ctx.subflows.get(workflow)
        if info is None:
            self.err(
                "subflow.unknown",
                "The failure-handler workflow doesn't exist here or has no published version.",
                fld="/settings/failure_handler",
            )
        else:
            self.failure_handler_version_id = info.version_id


def validate(graph: Graph, ctx: ValidationContext) -> ValidationResult:
    settings = _settings(graph)
    structure, structural = analyze_structure(graph, ctx.catalog)
    node_refs = tuple(sorted({n.type for n in graph.nodes}))
    if structure is None:
        return ValidationResult(tuple([*settings, *structural]), node_refs)
    unusable = ("settings.invalid_schema", "settings.unresolvable_ref")
    v = _Validator(graph, structure, ctx, settings_ok=not any(d.code in unusable for d in settings))
    v.run()
    return ValidationResult(
        diagnostics=tuple([*settings, *structural, *v.diags]),
        node_refs=node_refs,
        subflow_pins=dict(v.pins),
        failure_handler_version_id=v.failure_handler_version_id,
        output_schema=v.output_schema,
    )
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/engine/graph -q`
Expected: all passed, including the Hypothesis soundness test (200 examples).

- [ ] **Step 6: Commit**

```bash
uv run ruff format . && uv run ruff check . && uv run mypy src && uv run lint-imports && uv run pytest tests/engine -q && \
git add src/dewpoint/engine/graph/liveness.py src/dewpoint/engine/graph/validate.py tests/engine/graph/test_liveness.py tests/engine/graph/test_validate.py && \
git commit -m "feat(engine): liveness conditions and the publish-time graph validator

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Schema for the registry, lifecycle states, workflows and versions

**Files:**
- Create: `backend/migrations/versions/0007_workflows.py`
- Create: `backend/src/dewpoint/core/models/plugins.py`, `backend/src/dewpoint/core/models/workflows.py`
- Modify: `backend/src/dewpoint/core/models/__init__.py`
- Create: `backend/tests/support/workflows.py`
- Test: `backend/tests/core/workflows/__init__.py`, `backend/tests/core/workflows/test_rls_workflows.py`

**Interfaces:**
- Produces these tables:
  - Global: `plugin_manifests(name pk, version, sdk_version, manifest, synced_at)`; `node_type_versions((type, version) pk, plugin, kind, manifest, contract_hash, state, state_changed_at, created_at)`; `cel_profiles(profile pk, state, state_changed_at, created_at)`.
  - Tenant, RLS: `workflows(id, tenant_id, name, enabled, active_version_id, draft, draft_revision, created_by, created_at, updated_at)`.
  - Tenant, RLS, insert-only: `workflow_versions(id, tenant_id, workflow_id, number, graph, node_refs, engine_abi, cel_profile, connection_ids, subflow_version_ids, failure_handler_version_id, input_schema, output_schema, vars_schema, expressions, closure_version_ids, closure_workflow_ids, closure_node_refs, closure_cel_profiles, closure_depth, graph_hash, version_hash, published_by, published_at)`.
  - `workflows_active_version_fk`: a composite key `(active_version_id, id) → workflow_versions(id, workflow_id)`, so the active version always belongs to its workflow.
- Grants:
  - API: `SELECT, INSERT, UPDATE` on `workflows`; `SELECT, INSERT` on `workflow_versions`; `SELECT` on the registry tables.
  - Worker and dispatch: `SELECT` on all of them.
  - Admin: `SELECT` on workflows and versions (a platform read policy), and `SELECT, INSERT, UPDATE` on the registry tables.
- ORM models `PluginManifest`, `NodeTypeVersion` (with `.ref`), `CelProfile`, `Workflow`, `WorkflowVersion`.
- Test helper `seed_workflow(owner_sessionmaker, *, tenant_id=None, name="W", node_refs=("testkit.echo@1",), enabled=True, active=True) -> (tenant_id, workflow_id, version_id)`.

- [ ] **Step 1: Write the failing test**

`backend/tests/core/workflows/__init__.py`:

```python
# SPDX-License-Identifier: Apache-2.0
```

`backend/tests/support/workflows.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""Seed workflows and versions directly (as the table owner), for tests that don't exercise publishing."""

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import text

PROFILE = "cel-cpp-0.1.3/fn-1/cls-1"


async def seed_workflow(
    owner_sessionmaker: Any,
    *,
    tenant_id: uuid.UUID | None = None,
    name: str = "W",
    node_refs: Sequence[str] = ("testkit.echo@1",),
    enabled: bool = True,
    active: bool = True,
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    tenant, wf, version = tenant_id or uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    async with owner_sessionmaker() as s, s.begin():
        if tenant_id is None:
            await s.execute(
                text("insert into tenants(id,name,slug) values (:t,'T',:slug)"), {"t": tenant, "slug": tenant.hex[:12]}
            )
        await s.execute(text("insert into cel_profiles(profile) values (:p) on conflict do nothing"), {"p": PROFILE})
        await s.execute(
            text("insert into workflows(id,tenant_id,name,enabled,draft) values (:w,:t,:n,:e,'{}')"),
            {"w": wf, "t": tenant, "n": name, "e": enabled},
        )
        await s.execute(
            text(
                "insert into workflow_versions(id,tenant_id,workflow_id,number,graph,node_refs,engine_abi,cel_profile,"
                "input_schema,output_schema,vars_schema,closure_version_ids,closure_workflow_ids,closure_node_refs,"
                "closure_cel_profiles,closure_depth,graph_hash,version_hash) "
                "values (:v,:t,:w,1,'{}',cast(:refs as text[]),1,"
                "cast(:p as text),"
                "'{}','{}','{}',array[cast(:v as uuid)],array[cast(:w as uuid)],cast(:refs as text[]),"
                "array[cast(:p as text)],0,'g','v')"
            ),
            {"v": version, "t": tenant, "w": wf, "p": PROFILE, "refs": list(node_refs)},
        )
        if active:
            await s.execute(text("update workflows set active_version_id = :v where id = :w"), {"v": version, "w": wf})
    return tenant, wf, version
```

`backend/tests/core/workflows/test_rls_workflows.py`:

```python
# SPDX-License-Identifier: Apache-2.0
import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from dewpoint.core.db import tenant_scope
from dewpoint.core.models.workflows import Workflow, WorkflowVersion
from tests.support.workflows import seed_workflow


async def test_workflows_and_versions_are_tenant_scoped(owner_sessionmaker, api_sessionmaker) -> None:
    a, wf, v = await seed_workflow(owner_sessionmaker)
    b, _, _ = await seed_workflow(owner_sessionmaker, name="Other")
    async with api_sessionmaker() as s, s.begin():
        assert (await s.execute(select(Workflow))).scalars().all() == []  # no tenant context
        await tenant_scope(s, a)
        assert [w.id for w in (await s.execute(select(Workflow))).scalars()] == [wf]
        assert [x.id for x in (await s.execute(select(WorkflowVersion))).scalars()] == [v]
        await tenant_scope(s, b)
        assert v not in [x.id for x in (await s.execute(select(WorkflowVersion))).scalars()]


async def test_versions_are_immutable_even_for_the_owner(owner_sessionmaker) -> None:
    _, _, v = await seed_workflow(owner_sessionmaker)
    for stmt in ("update workflow_versions set number = 2 where id = :v", "delete from workflow_versions where id = :v"):
        with pytest.raises(DBAPIError, match="immutable"):
            async with owner_sessionmaker() as s, s.begin():
                await s.execute(text(stmt), {"v": v})


async def test_api_role_cannot_delete_versions_or_workflows(owner_sessionmaker, api_sessionmaker) -> None:
    tenant, wf, v = await seed_workflow(owner_sessionmaker)
    for stmt, target in (("delete from workflow_versions where id = :x", v), ("delete from workflows where id = :x", wf)):
        with pytest.raises(DBAPIError, match="permission denied"):
            async with api_sessionmaker() as s, s.begin():
                await tenant_scope(s, tenant)
                await s.execute(text(stmt), {"x": target})


async def test_admin_reads_across_tenants_but_cannot_write(owner_sessionmaker, admin_sessionmaker) -> None:
    _, wf, _ = await seed_workflow(owner_sessionmaker)
    async with admin_sessionmaker() as s, s.begin():
        assert [w.id for w in (await s.execute(select(Workflow))).scalars()] == [wf]
    with pytest.raises(DBAPIError, match="permission denied"):
        async with admin_sessionmaker() as s, s.begin():
            await s.execute(text("update workflows set enabled = false where id = :w"), {"w": wf})


async def test_active_version_must_belong_to_its_workflow(owner_sessionmaker) -> None:
    tenant, _, v = await seed_workflow(owner_sessionmaker)
    with pytest.raises(DBAPIError, match="workflows_active_version_fk"):
        async with owner_sessionmaker() as s, s.begin():
            await s.execute(
                text("insert into workflows(id,tenant_id,name,draft,active_version_id) values (:o,:t,'Other','{}',:v)"),
                {"o": uuid.uuid4(), "t": tenant, "v": v},
            )
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/core/workflows -q`
Expected: FAIL: `ModuleNotFoundError: No module named 'dewpoint.core.models.workflows'`.

- [ ] **Step 3: Write the migration**

`backend/migrations/versions/0007_workflows.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""workflows, immutable versions, plugin registry and lifecycle states"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

INITIAL_CEL_PROFILE = "cel-cpp-0.1.3/fn-1/cls-1"
STATE_CHECK = "state IN ('active', 'deprecated', 'retired')"

STATEMENTS = [
    "ALTER TABLE workflows ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE workflows FORCE ROW LEVEL SECURITY",
    "CREATE POLICY workflows_scope ON workflows "
    "USING (tenant_id = app_tenant_id()) WITH CHECK (tenant_id = app_tenant_id())",
    # Platform lifecycle previews (retire --force) list affected workflows across tenants. Read-only.
    "CREATE POLICY workflows_platform_read ON workflows FOR SELECT TO dewpoint_admin USING (true)",
    "ALTER TABLE workflow_versions ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE workflow_versions FORCE ROW LEVEL SECURITY",
    "CREATE POLICY workflow_versions_scope ON workflow_versions "
    "USING (tenant_id = app_tenant_id()) WITH CHECK (tenant_id = app_tenant_id())",
    "CREATE POLICY workflow_versions_platform_read ON workflow_versions FOR SELECT TO dewpoint_admin USING (true)",
    "CREATE FUNCTION workflow_versions_immutable() RETURNS trigger LANGUAGE plpgsql AS "
    "$$ BEGIN RAISE EXCEPTION 'workflow_versions rows are immutable'; END $$",
    "CREATE TRIGGER workflow_versions_immutable BEFORE UPDATE OR DELETE ON workflow_versions "
    "FOR EACH ROW EXECUTE FUNCTION workflow_versions_immutable()",
    "GRANT SELECT, INSERT, UPDATE ON workflows TO dewpoint_api",
    "GRANT SELECT ON workflows TO dewpoint_worker, dewpoint_dispatch, dewpoint_admin",
    "GRANT SELECT, INSERT ON workflow_versions TO dewpoint_api",
    "GRANT SELECT ON workflow_versions TO dewpoint_worker, dewpoint_dispatch, dewpoint_admin",
    "GRANT SELECT ON plugin_manifests, node_type_versions, cel_profiles TO dewpoint_api, dewpoint_worker, dewpoint_dispatch",
    "GRANT SELECT, INSERT, UPDATE ON plugin_manifests, node_type_versions, cel_profiles TO dewpoint_admin",
    f"INSERT INTO cel_profiles (profile, state) VALUES ('{INITIAL_CEL_PROFILE}', 'active')",
]


def _timestamps() -> list[sa.Column]:  # type: ignore[type-arg]
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    ]


def upgrade() -> None:
    op.create_table(
        "plugin_manifests",
        sa.Column("name", sa.String(41), primary_key=True),
        sa.Column("version", sa.String(64), nullable=False),
        sa.Column("sdk_version", sa.String(32), nullable=False),
        sa.Column("manifest", pg.JSONB, nullable=False),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "node_type_versions",
        sa.Column("type", sa.String(120), primary_key=True),
        sa.Column("version", sa.Integer, primary_key=True),
        sa.Column("plugin", sa.String(41), sa.ForeignKey("plugin_manifests.name"), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("manifest", pg.JSONB, nullable=False),
        sa.Column("contract_hash", sa.String(64), nullable=False),  # everything but display metadata
        sa.Column("state", sa.String(16), nullable=False, server_default="active"),
        sa.Column("state_changed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(STATE_CHECK, name="node_type_versions_state"),
    )
    op.create_table(
        "cel_profiles",
        sa.Column("profile", sa.String(120), primary_key=True),
        sa.Column("state", sa.String(16), nullable=False, server_default="active"),
        sa.Column("state_changed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(STATE_CHECK, name="cel_profiles_state"),
    )
    op.create_table(
        "workflows",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", pg.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("active_version_id", pg.UUID(as_uuid=True)),
        sa.Column("draft", pg.JSONB, nullable=False),
        sa.Column("draft_revision", sa.Integer, nullable=False, server_default="1"),
        sa.Column("created_by", pg.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")),
        *_timestamps(),
        sa.UniqueConstraint("tenant_id", "name"),
    )
    op.create_table(
        "workflow_versions",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", pg.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("workflow_id", pg.UUID(as_uuid=True), sa.ForeignKey("workflows.id"), nullable=False),
        sa.Column("number", sa.Integer, nullable=False),
        sa.Column("graph", pg.JSONB, nullable=False),
        sa.Column("node_refs", pg.ARRAY(sa.Text), nullable=False),
        sa.Column("engine_abi", sa.Integer, nullable=False),
        sa.Column("cel_profile", sa.String(120), sa.ForeignKey("cel_profiles.profile"), nullable=False),
        sa.Column("connection_ids", pg.ARRAY(pg.UUID(as_uuid=True)), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("subflow_version_ids", pg.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("failure_handler_version_id", pg.UUID(as_uuid=True)),
        sa.Column("input_schema", pg.JSONB, nullable=False),
        sa.Column("output_schema", pg.JSONB, nullable=False),
        sa.Column("vars_schema", pg.JSONB, nullable=False),
        sa.Column("expressions", pg.JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("closure_version_ids", pg.ARRAY(pg.UUID(as_uuid=True)), nullable=False),
        sa.Column("closure_workflow_ids", pg.ARRAY(pg.UUID(as_uuid=True)), nullable=False),
        sa.Column("closure_node_refs", pg.ARRAY(sa.Text), nullable=False),
        sa.Column("closure_cel_profiles", pg.ARRAY(sa.Text), nullable=False),
        sa.Column("closure_depth", sa.Integer, nullable=False),
        sa.Column("graph_hash", sa.String(64), nullable=False),  # the authored graph only
        sa.Column("version_hash", sa.String(64), nullable=False),  # graph + resolved pins + CEL profile + engine ABI
        # No foreign key: an ON DELETE action would have to UPDATE an immutable row.
        sa.Column("published_by", pg.UUID(as_uuid=True)),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("workflow_id", "number"),
        sa.UniqueConstraint("id", "workflow_id", name="workflow_versions_id_workflow"),
    )
    op.create_foreign_key(
        "workflows_active_version_fk",
        "workflows",
        "workflow_versions",
        ["active_version_id", "id"],
        ["id", "workflow_id"],
    )
    op.create_index(
        "ix_workflow_versions_closure_node_refs", "workflow_versions", ["closure_node_refs"], postgresql_using="gin"
    )
    op.create_index(
        "ix_workflow_versions_closure_cel_profiles", "workflow_versions", ["closure_cel_profiles"], postgresql_using="gin"
    )
    for stmt in STATEMENTS:
        op.execute(stmt)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS workflow_versions_immutable ON workflow_versions")
    op.execute("DROP FUNCTION IF EXISTS workflow_versions_immutable()")
    op.execute("ALTER TABLE workflows DROP CONSTRAINT IF EXISTS workflows_active_version_fk")
    op.drop_table("workflow_versions")
    op.drop_table("workflows")
    op.drop_table("cel_profiles")
    op.drop_table("node_type_versions")
    op.drop_table("plugin_manifests")
```

- [ ] **Step 4: Write the ORM models**

`backend/src/dewpoint/core/models/plugins.py`:

```python
# SPDX-License-Identifier: Apache-2.0
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from dewpoint.core.models.base import Base


class PluginManifest(Base):
    __tablename__ = "plugin_manifests"
    name: Mapped[str] = mapped_column(String(41), primary_key=True)
    version: Mapped[str] = mapped_column(String(64))
    sdk_version: Mapped[str] = mapped_column(String(32))
    manifest: Mapped[dict[str, Any]] = mapped_column(JSONB)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class NodeTypeVersion(Base):
    __tablename__ = "node_type_versions"
    type: Mapped[str] = mapped_column(String(120), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    plugin: Mapped[str] = mapped_column(String(41), ForeignKey("plugin_manifests.name"))
    kind: Mapped[str] = mapped_column(String(16))
    manifest: Mapped[dict[str, Any]] = mapped_column(JSONB)
    contract_hash: Mapped[str] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(16), default="active")  # active | deprecated | retired
    state_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    @property
    def ref(self) -> str:
        return f"{self.type}@{self.version}"


class CelProfile(Base):
    __tablename__ = "cel_profiles"
    profile: Mapped[str] = mapped_column(String(120), primary_key=True)
    state: Mapped[str] = mapped_column(String(16), default="active")
    state_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```

`backend/src/dewpoint/core/models/workflows.py`:

```python
# SPDX-License-Identifier: Apache-2.0
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from dewpoint.core.models.base import Base, Timestamps, UUIDPk


class Workflow(UUIDPk, Timestamps, Base):
    __tablename__ = "workflows"
    __table_args__ = (UniqueConstraint("tenant_id", "name"),)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(100))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    active_version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    draft: Mapped[dict[str, Any]] = mapped_column(JSONB)
    draft_revision: Mapped[int] = mapped_column(Integer, default=1)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )


class WorkflowVersion(UUIDPk, Base):
    """Immutable (a trigger rejects UPDATE and DELETE). Insert once, at publish."""

    __tablename__ = "workflow_versions"
    __table_args__ = (UniqueConstraint("workflow_id", "number"),)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"))
    workflow_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("workflows.id"))
    number: Mapped[int] = mapped_column(Integer)
    graph: Mapped[dict[str, Any]] = mapped_column(JSONB)
    node_refs: Mapped[list[str]] = mapped_column(ARRAY(Text))
    engine_abi: Mapped[int] = mapped_column(Integer)
    cel_profile: Mapped[str] = mapped_column(String(120), ForeignKey("cel_profiles.profile"))
    connection_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID(as_uuid=True)), default=list)
    subflow_version_ids: Mapped[dict[str, str]] = mapped_column(JSONB, default=dict)
    failure_handler_version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    input_schema: Mapped[dict[str, Any]] = mapped_column(JSONB)
    output_schema: Mapped[dict[str, Any]] = mapped_column(JSONB)
    vars_schema: Mapped[dict[str, Any]] = mapped_column(JSONB)
    expressions: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    closure_version_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID(as_uuid=True)))
    closure_workflow_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID(as_uuid=True)))
    closure_node_refs: Mapped[list[str]] = mapped_column(ARRAY(Text))
    closure_cel_profiles: Mapped[list[str]] = mapped_column(ARRAY(Text))
    closure_depth: Mapped[int] = mapped_column(Integer)
    graph_hash: Mapped[str] = mapped_column(String(64))
    version_hash: Mapped[str] = mapped_column(String(64))
    published_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```

Replace the contents of `backend/src/dewpoint/core/models/__init__.py` with:

```python
# SPDX-License-Identifier: Apache-2.0
from dewpoint.core.models import audit, connections, identity, keys, plugins, tenancy, workflows
from dewpoint.core.models.base import Base

__all__ = ["Base", "audit", "connections", "identity", "keys", "plugins", "tenancy", "workflows"]
```

- [ ] **Step 5: Run the migration round trip and the tests**

Run: `uv run pytest tests/core/workflows -q`
Expected: 5 passed. The session fixture migrates a fresh container to head.

Also verify the downgrade on a scratch database:
```bash
docker run -d --rm --name dp-mig -e POSTGRES_PASSWORD=pw -p 55432:5432 postgres:16-alpine && sleep 3 && \
DEWPOINT_DATABASE_URL=postgresql+asyncpg://postgres:pw@localhost:55432/postgres uv run alembic upgrade head && \
DEWPOINT_DATABASE_URL=postgresql+asyncpg://postgres:pw@localhost:55432/postgres uv run alembic downgrade 0006 && \
DEWPOINT_DATABASE_URL=postgresql+asyncpg://postgres:pw@localhost:55432/postgres uv run alembic upgrade head; \
docker stop dp-mig
```
Expected: all three alembic commands exit 0.

- [ ] **Step 6: Commit**

```bash
uv run ruff format . && uv run ruff check . && uv run mypy src && uv run lint-imports && uv run pytest tests/core -q && \
git add migrations/versions/0007_workflows.py src/dewpoint/core/models tests/core/workflows tests/support/workflows.py && \
git commit -m "feat(core): workflows, immutable versions, registry and lifecycle tables with RLS

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Plugin registration, the lifecycle service, and CLI commands

**Files:**
- Create: `backend/src/dewpoint/core/plugins/__init__.py`, `backend/src/dewpoint/core/plugins/registry.py`, `backend/src/dewpoint/core/plugins/lifecycle.py`
- Create: `backend/src/dewpoint/apps/plugin_loader.py`
- Modify: `backend/src/dewpoint/apps/cli/main.py`
- Create: `backend/tests/support/registry.py`
- Test: `backend/tests/core/plugins/__init__.py`, `backend/tests/core/plugins/test_registry.py`, `backend/tests/core/plugins/test_lifecycle.py`, `backend/tests/apps/cli/test_plugins_cli.py`

**Interfaces:**
- Consumes: the models (Task 7); `validate_plugin_manifest`, `contract_hash` and `CURRENT_CEL_PROFILE` (Task 3); the SDK (Task 1); `core.audit.service.record`; `core.db.tenant_scope`.
- Produces from `core.plugins.registry`:
  - `NodeTypeRow(type, version, kind, manifest, contract_hash)` with `.ref`, and `SyncReport(added, unchanged)`.
  - Errors: `ContractChangedError(refs)`, `MissingNodeTypeError(refs)`.
  - A re-sync may change only display metadata; that is stored in place. Any contract change is refused.
  - Functions: `split_ref(ref) -> (type, version)`, `sync_plugins(s, [(manifest, rows)]) -> SyncReport`, `ensure_cel_profile(s, profile)`, `load_node_types(s, refs) -> list[NodeTypeVersion]`, `list_node_types(s, states=("active", "deprecated"))`.
- Produces from `core.plugins.lifecycle`:
  - `Entry(kind: "node" | "cel", key)` with `.lock_key` and `__str__`; `entries_for(node_refs, cel_profiles) -> list[Entry]` (sorted).
  - Locks and states: `IsolationError`, `assert_read_committed(s)`, `lock_shared(s, entries)`, `lock_exclusive(s, entry)`, `states(s, entries) -> dict[Entry, str]` (`active|deprecated|retired|missing`), `not_executable(states) -> list[Entry]`.
  - Retirement: `ActiveRef(tenant_id, workflow_id, workflow_name, version_id, version_number)`, `RetirePreview(entry, state, active_refs, affected_versions, applied)`, `ReferencedError(preview)`, `UnknownEntryError`, `deprecate(s, entry, *, actor_id) -> str`, `retire(s, entry, *, force=False, confirm=False, actor_id=None) -> RetirePreview`.
- Produces from `apps.plugin_loader`: `GROUP = "dewpoint.plugins"`, `PluginLoadError(problems)`, `installed_plugins() -> list[Plugin]`, `prepare(plugins) -> list[(manifest, rows)]`, `sync_installed(s, plugins) -> SyncReport`.
- CLI (run with the `dewpoint_admin` database URL):
  - `dewpoint plugins sync` (exit 2 on invalid manifests, contract changes or missing live types);
  - `dewpoint plugins list`;
  - `dewpoint lifecycle deprecate (--node-type REF | --cel-profile P)`;
  - `dewpoint lifecycle retire (--node-type REF | --cel-profile P) [--force] [--confirm]`. Exits: 0 retired, 2 bad input or unknown entry, 3 forced preview not applied, 4 still referenced.
- Test helper `tests.support.registry.sync_test_plugins(sessionmaker)` syncs `flow` and `testkit`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/core/plugins/__init__.py`:

```python
# SPDX-License-Identifier: Apache-2.0
```

`backend/tests/support/registry.py`:

```python
# SPDX-License-Identifier: Apache-2.0
from typing import Any

from dewpoint.apps.plugin_loader import sync_installed
from dewpoint.plugins.flow import PLUGIN
from tests.support.plugins.testkit import TESTKIT


async def sync_test_plugins(sessionmaker: Any) -> None:
    """Register flow + testkit (and this build's CEL profile), as `dewpoint plugins sync` would."""
    async with sessionmaker() as s, s.begin():
        await sync_installed(s, [PLUGIN, TESTKIT])
```

`backend/tests/core/plugins/test_registry.py`:

```python
# SPDX-License-Identifier: Apache-2.0
from dataclasses import replace
from typing import Any

import pytest
from sqlalchemy import select, text, update
from sqlalchemy.exc import DBAPIError

from dewpoint.apps.plugin_loader import PluginLoadError, prepare, sync_installed
from dewpoint.core.models.plugins import CelProfile, NodeTypeVersion
from dewpoint.core.plugins import registry
from dewpoint.engine.cel.profile import CURRENT_CEL_PROFILE
from dewpoint.engine.registry.catalog import contract_hash
from dewpoint.plugins.flow import PLUGIN
from dewpoint.sdk import Node, NodeKind, Plugin
from tests.support.plugins.testkit import TESTKIT


async def test_sync_registers_and_is_idempotent(admin_sessionmaker) -> None:
    async with admin_sessionmaker() as s, s.begin():
        report = await sync_installed(s, [PLUGIN, TESTKIT])
    assert len(report.added) == 16 and report.unchanged == []
    async with admin_sessionmaker() as s, s.begin():
        report = await sync_installed(s, [PLUGIN, TESTKIT])
    assert report.added == [] and len(report.unchanged) == 16
    async with admin_sessionmaker() as s:
        refs = {r.ref for r in await registry.list_node_types(s)}
        state = (await s.execute(select(CelProfile.state).where(CelProfile.profile == CURRENT_CEL_PROFILE))).scalar_one()
    assert {"flow.if@1", "testkit.echo@1"} <= refs and state == "active"


async def test_behaviour_changes_are_refused_but_display_changes_are_stored(admin_sessionmaker) -> None:
    async with admin_sessionmaker() as s, s.begin():
        await sync_installed(s, [PLUGIN, TESTKIT])
    flow, (manifest, rows) = prepare([PLUGIN, TESTKIT])

    def with_echo(field: str, value: Any) -> list[Any]:
        node = {**rows[0].manifest, field: value}
        return [flow, (manifest, [replace(rows[0], manifest=node, contract_hash=contract_hash(node)), *rows[1:]])]

    for field, value in (("timeout_s", 1.0), ("retry", {**rows[0].manifest["retry"], "max_attempts": 9})):
        with pytest.raises(registry.ContractChangedError) as e:
            async with admin_sessionmaker() as s, s.begin():
                await registry.sync_plugins(s, with_echo(field, value))
        assert e.value.refs == ["testkit.echo@1"], field
    async with admin_sessionmaker() as s, s.begin():
        await registry.sync_plugins(s, with_echo("title", "Echo (renamed)"))
    async with admin_sessionmaker() as s:
        stored = await s.get(NodeTypeVersion, ("testkit.echo", 1))
        assert stored is not None and stored.manifest["title"] == "Echo (renamed)"


async def test_a_build_cannot_drop_live_node_types(admin_sessionmaker) -> None:
    async with admin_sessionmaker() as s, s.begin():
        await sync_installed(s, [PLUGIN, TESTKIT])
    with pytest.raises(registry.MissingNodeTypeError) as e:
        async with admin_sessionmaker() as s, s.begin():
            await sync_installed(s, [PLUGIN])
    assert "testkit.echo@1" in e.value.refs
    async with admin_sessionmaker() as s, s.begin():  # once retired, a build may drop them
        await s.execute(update(NodeTypeVersion).where(NodeTypeVersion.plugin == "testkit").values(state="retired"))
        await sync_installed(s, [PLUGIN])


async def test_api_role_cannot_write_the_registry(admin_sessionmaker, api_sessionmaker) -> None:
    async with admin_sessionmaker() as s, s.begin():
        await sync_installed(s, [PLUGIN])
    with pytest.raises(DBAPIError, match="permission denied"):
        async with api_sessionmaker() as s, s.begin():
            await s.execute(text("update node_type_versions set state = 'retired'"))


def test_prepare_rejects_manifests_the_engine_refuses() -> None:
    class Rogue(Node):
        type = "demo.rogue"
        version = 1
        title = "Rogue"
        kind = NodeKind.CONTROL  # only engine control types may be control nodes

    with pytest.raises(PluginLoadError) as e:
        prepare([Plugin(name="demo", version="1", nodes=(Rogue,))])
    assert any("only engine control types" in p for p in e.value.problems)
```

`backend/tests/core/plugins/test_lifecycle.py`:

```python
# SPDX-License-Identifier: Apache-2.0
import pytest
from sqlalchemy import text

from dewpoint.core.plugins import lifecycle
from dewpoint.core.plugins.lifecycle import Entry
from dewpoint.engine.cel.profile import CURRENT_CEL_PROFILE
from tests.support.registry import sync_test_plugins
from tests.support.workflows import seed_workflow

ECHO = Entry("node", "testkit.echo@1")


async def test_states_and_entries(admin_sessionmaker) -> None:
    await sync_test_plugins(admin_sessionmaker)
    missing, profile = Entry("node", "testkit.nope@1"), Entry("cel", CURRENT_CEL_PROFILE)
    async with admin_sessionmaker() as s:
        assert await lifecycle.states(s, [ECHO, missing, profile]) == {
            ECHO: "active",
            missing: "missing",
            profile: "active",
        }
    assert lifecycle.entries_for(["b@1", "a@1", "a@1"], ["p"]) == [
        Entry("cel", "p"),
        Entry("node", "a@1"),
        Entry("node", "b@1"),
    ]


async def test_deprecate_then_retire_when_unused(admin_sessionmaker, owner_sessionmaker) -> None:
    await sync_test_plugins(admin_sessionmaker)
    async with admin_sessionmaker() as s, s.begin():
        assert await lifecycle.deprecate(s, ECHO, actor_id=None) == "deprecated"
    async with admin_sessionmaker() as s, s.begin():
        preview = await lifecycle.retire(s, ECHO)
    assert preview.applied and preview.active_refs == ()
    async with owner_sessionmaker() as s:
        actions = (
            await s.execute(text("select action from audit_log where target_id = 'testkit.echo@1' order by created_at"))
        ).scalars().all()
    assert actions == ["lifecycle.deprecate", "lifecycle.retire"]


async def test_active_workflows_block_normal_retirement(admin_sessionmaker, owner_sessionmaker) -> None:
    await sync_test_plugins(admin_sessionmaker)
    _, wf, _ = await seed_workflow(owner_sessionmaker)
    with pytest.raises(lifecycle.ReferencedError) as e:
        async with admin_sessionmaker() as s, s.begin():
            await lifecycle.retire(s, ECHO)
    assert [r.workflow_id for r in e.value.preview.active_refs] == [wf]


async def test_disabled_and_superseded_workflows_do_not_block(admin_sessionmaker, owner_sessionmaker) -> None:
    await sync_test_plugins(admin_sessionmaker)
    await seed_workflow(owner_sessionmaker, enabled=False)
    await seed_workflow(owner_sessionmaker, active=False)
    async with admin_sessionmaker() as s, s.begin():
        preview = await lifecycle.retire(s, ECHO)
    assert preview.applied and preview.affected_versions == 2


async def test_forced_retirement_previews_then_applies(admin_sessionmaker, owner_sessionmaker) -> None:
    await sync_test_plugins(admin_sessionmaker)
    tenant, wf, _ = await seed_workflow(owner_sessionmaker)
    async with admin_sessionmaker() as s, s.begin():
        preview = await lifecycle.retire(s, ECHO, force=True)
    assert not preview.applied and [r.workflow_id for r in preview.active_refs] == [wf]
    async with admin_sessionmaker() as s:
        assert (await lifecycle.states(s, [ECHO]))[ECHO] == "active"
    async with admin_sessionmaker() as s, s.begin():
        preview = await lifecycle.retire(s, ECHO, force=True, confirm=True)
    assert preview.applied
    async with owner_sessionmaker() as s:
        rows = (
            await s.execute(
                text("select tenant_id, details from audit_log where action = 'lifecycle.retire' order by created_at")
            )
        ).all()
    assert [r.tenant_id for r in rows] == [None, tenant]
    assert rows[1].details == {"forced": True, "workflows": [str(wf)]}


async def test_retirement_requires_read_committed(admin_sessionmaker) -> None:
    async with admin_sessionmaker() as s:
        await s.connection(execution_options={"isolation_level": "REPEATABLE READ"})
        with pytest.raises(lifecycle.IsolationError):
            await lifecycle.retire(s, Entry("cel", CURRENT_CEL_PROFILE))
        await s.rollback()
```

`backend/tests/apps/cli/test_plugins_cli.py`:

```python
# SPDX-License-Identifier: Apache-2.0
import base64
import os

import pytest
from typer.testing import CliRunner

from dewpoint.apps.cli.main import app
from dewpoint.apps.plugin_loader import installed_plugins
from dewpoint.core.config import get_settings


@pytest.fixture
def cli_env(pg_url, monkeypatch):  # type: ignore[no-untyped-def]
    monkeypatch.setenv("DEWPOINT_DATABASE_URL", pg_url)
    monkeypatch.setenv("DEWPOINT_KEK_B64", base64.b64encode(os.urandom(32)).decode())
    monkeypatch.setenv("DEWPOINT_PUBLIC_ORIGIN", "https://dewpoint.test")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_entry_points_expose_the_flow_plugin() -> None:
    assert [p.name for p in installed_plugins()] == ["flow"]


def test_plugins_sync_is_idempotent(cli_env) -> None:  # type: ignore[no-untyped-def]
    runner = CliRunner()
    first = runner.invoke(app, ["plugins", "sync"])
    assert first.exit_code == 0, first.output
    assert "added 11, unchanged 0" in first.output
    second = runner.invoke(app, ["plugins", "sync"])
    assert second.exit_code == 0 and "added 0, unchanged 11" in second.output
    listed = runner.invoke(app, ["plugins", "list"])
    assert "flow.if@1 active" in listed.output


def test_lifecycle_commands(cli_env) -> None:  # type: ignore[no-untyped-def]
    runner = CliRunner()
    assert runner.invoke(app, ["plugins", "sync"]).exit_code == 0
    r = runner.invoke(app, ["lifecycle", "deprecate", "--node-type", "flow.wait_until@1"])
    assert r.exit_code == 0 and "deprecated" in r.output
    r = runner.invoke(app, ["lifecycle", "retire", "--node-type", "flow.wait_until@1"])
    assert r.exit_code == 0 and "retired" in r.output
    assert runner.invoke(app, ["plugins", "sync"]).exit_code == 0  # a retired type may stay installed
    assert runner.invoke(app, ["lifecycle", "retire", "--node-type", "flow.nope@1"]).exit_code == 2
    assert runner.invoke(app, ["lifecycle", "retire"]).exit_code == 2
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/core/plugins tests/apps/cli/test_plugins_cli.py -q`
Expected: FAIL: `ModuleNotFoundError: No module named 'dewpoint.apps.plugin_loader'`.

- [ ] **Step 3: Implement the registry storage**

`backend/src/dewpoint/core/plugins/__init__.py`:

```python
# SPDX-License-Identifier: Apache-2.0
```

`backend/src/dewpoint/core/plugins/registry.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""Storage for plugin manifests and node type versions. Manifests are validated before they get here."""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select, tuple_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from dewpoint.core.models.plugins import CelProfile, NodeTypeVersion, PluginManifest


@dataclass(frozen=True)
class NodeTypeRow:
    type: str
    version: int
    kind: str
    manifest: dict[str, Any]
    contract_hash: str

    @property
    def ref(self) -> str:
        return f"{self.type}@{self.version}"


@dataclass(frozen=True)
class SyncReport:
    added: list[str]
    unchanged: list[str]


class ContractChangedError(ValueError):
    """A registered node type version changed its contract (anything but display metadata). Ship a new version."""

    def __init__(self, refs: list[str]) -> None:
        super().__init__(", ".join(refs))
        self.refs = refs


class MissingNodeTypeError(ValueError):
    """This build lacks node types that aren't retired. Published versions may still need them."""

    def __init__(self, refs: list[str]) -> None:
        super().__init__(", ".join(refs))
        self.refs = refs


def split_ref(ref: str) -> tuple[str, int]:
    type_, _, version = ref.rpartition("@")
    return type_, int(version)


async def sync_plugins(s: AsyncSession, plugins: Sequence[tuple[dict[str, Any], list[NodeTypeRow]]]) -> SyncReport:
    """Register every installed plugin in one transaction. Refuses contract changes, and refuses a build that
    lacks a node type that isn't retired (spec §4.5: code is removed only after retirement)."""
    added: list[str] = []
    unchanged: list[str] = []
    changed: list[str] = []
    installed: set[str] = set()
    for manifest, rows in plugins:
        await s.execute(
            insert(PluginManifest)
            .values(
                name=manifest["name"],
                version=manifest["version"],
                sdk_version=manifest["sdk_version"],
                manifest=manifest,
            )
            .on_conflict_do_update(
                index_elements=["name"],
                set_={
                    "version": manifest["version"],
                    "sdk_version": manifest["sdk_version"],
                    "manifest": manifest,
                    "synced_at": func.now(),
                },
            )
        )
        for row in rows:
            installed.add(row.ref)
            existing = await s.get(NodeTypeVersion, (row.type, row.version), with_for_update=True)
            if existing is None:
                s.add(
                    NodeTypeVersion(
                        type=row.type,
                        version=row.version,
                        plugin=manifest["name"],
                        kind=row.kind,
                        manifest=row.manifest,
                        contract_hash=row.contract_hash,
                        state="active",
                    )
                )
                added.append(row.ref)
            elif existing.contract_hash != row.contract_hash:
                changed.append(row.ref)
            else:
                existing.manifest = row.manifest  # equal contract hashes: only display metadata differs
                unchanged.append(row.ref)
    if changed:
        raise ContractChangedError(sorted(changed))
    await s.flush()
    live = await s.execute(
        select(NodeTypeVersion.type, NodeTypeVersion.version).where(NodeTypeVersion.state != "retired")
    )
    missing = sorted(f"{t}@{v}" for t, v in live if f"{t}@{v}" not in installed)
    if missing:
        raise MissingNodeTypeError(missing)
    return SyncReport(added=sorted(added), unchanged=sorted(unchanged))


async def ensure_cel_profile(s: AsyncSession, profile: str) -> None:
    await s.execute(insert(CelProfile).values(profile=profile, state="active").on_conflict_do_nothing())


async def load_node_types(s: AsyncSession, refs: Iterable[str]) -> list[NodeTypeVersion]:
    pairs = sorted({split_ref(r) for r in refs})
    if not pairs:
        return []
    rows = await s.execute(select(NodeTypeVersion).where(tuple_(NodeTypeVersion.type, NodeTypeVersion.version).in_(pairs)))
    return list(rows.scalars())


async def list_node_types(s: AsyncSession, states: Iterable[str] = ("active", "deprecated")) -> list[NodeTypeVersion]:
    rows = await s.execute(
        select(NodeTypeVersion)
        .where(NodeTypeVersion.state.in_(list(states)))
        .order_by(NodeTypeVersion.type, NodeTypeVersion.version)
    )
    return list(rows.scalars())
```

- [ ] **Step 4: Implement the lifecycle service**

`backend/src/dewpoint/core/plugins/lifecycle.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""Lifecycle of node type versions and CEL profiles (spec §4.5).

Every transaction that creates or uses a reference takes a *shared* lock on each lifecycle entry in the version's
closure, then re-reads the entries' states. Retirement takes the *exclusive* lock first, and only then counts
references. The locks are transaction-scoped advisory locks keyed by entry. They give FOR SHARE / FOR UPDATE
semantics without granting the API role UPDATE on the registry tables, which Postgres requires for row locks.
Both sides run at READ COMMITTED, so statements issued after a lock see what the other side committed."""

import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from typing import Literal

from sqlalchemy import any_, func, literal, select, text, tuple_, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from dewpoint.core.audit.service import record
from dewpoint.core.db import tenant_scope
from dewpoint.core.models.plugins import CelProfile, NodeTypeVersion
from dewpoint.core.models.workflows import Workflow, WorkflowVersion
from dewpoint.core.plugins.registry import split_ref

Kind = Literal["node", "cel"]


@dataclass(frozen=True, order=True)
class Entry:
    kind: Kind
    key: str

    @property
    def lock_key(self) -> str:
        return f"dewpoint:lifecycle:{self.kind}:{self.key}"

    def __str__(self) -> str:
        return f"{'node type' if self.kind == 'node' else 'CEL profile'} {self.key}"


def entries_for(node_refs: Iterable[str], cel_profiles: Iterable[str]) -> list[Entry]:
    return sorted({*(Entry("node", r) for r in node_refs), *(Entry("cel", p) for p in cel_profiles)})


class IsolationError(RuntimeError):
    pass


class UnknownEntryError(LookupError):
    pass


async def assert_read_committed(s: AsyncSession) -> None:
    level: str = (await s.execute(text("show transaction_isolation"))).scalar_one()
    if level != "read committed":
        raise IsolationError(f"lifecycle checks need READ COMMITTED, not {level}")


async def lock_shared(s: AsyncSession, entries: Iterable[Entry]) -> None:
    await assert_read_committed(s)
    for entry in sorted(set(entries)):
        await s.execute(text("select pg_advisory_xact_lock_shared(hashtextextended(:k, 0))"), {"k": entry.lock_key})


async def lock_exclusive(s: AsyncSession, entry: Entry) -> None:
    await assert_read_committed(s)
    await s.execute(text("select pg_advisory_xact_lock(hashtextextended(:k, 0))"), {"k": entry.lock_key})


async def states(s: AsyncSession, entries: Iterable[Entry]) -> dict[Entry, str]:
    """Current state of each entry: active, deprecated, retired, or missing (never registered)."""
    wanted = set(entries)
    out = dict.fromkeys(wanted, "missing")
    refs = [split_ref(e.key) for e in wanted if e.kind == "node"]
    if refs:
        rows = await s.execute(
            select(NodeTypeVersion.type, NodeTypeVersion.version, NodeTypeVersion.state).where(
                tuple_(NodeTypeVersion.type, NodeTypeVersion.version).in_(refs)
            )
        )
        for t, v, state in rows:
            out[Entry("node", f"{t}@{v}")] = state
    profiles = [e.key for e in wanted if e.kind == "cel"]
    if profiles:
        profile_rows = await s.execute(
            select(CelProfile.profile, CelProfile.state).where(CelProfile.profile.in_(profiles))
        )
        for profile, state in profile_rows:
            out[Entry("cel", profile)] = state
    return out


def not_executable(current: Mapping[Entry, str]) -> list[Entry]:
    return sorted(e for e, state in current.items() if state in ("retired", "missing"))


@dataclass(frozen=True)
class ActiveRef:
    tenant_id: uuid.UUID
    workflow_id: uuid.UUID
    workflow_name: str
    version_id: uuid.UUID
    version_number: int


@dataclass(frozen=True)
class RetirePreview:
    entry: Entry
    state: str
    active_refs: tuple[ActiveRef, ...]  # enabled workflows whose active closure uses the entry
    affected_versions: int  # every version whose closure uses it
    applied: bool = False
    # Sub-project 2b adds the queued run requests a forced retirement would cancel.


class ReferencedError(RuntimeError):
    def __init__(self, preview: RetirePreview) -> None:
        super().__init__(f"{preview.entry} is used by {len(preview.active_refs)} active workflow(s)")
        self.preview = preview


def _closure(entry: Entry) -> InstrumentedAttribute[list[str]]:
    return WorkflowVersion.closure_node_refs if entry.kind == "node" else WorkflowVersion.closure_cel_profiles


async def _preview(s: AsyncSession, entry: Entry, state: str) -> RetirePreview:
    uses = literal(entry.key) == any_(_closure(entry))
    rows = await s.execute(
        select(Workflow.tenant_id, Workflow.id, Workflow.name, WorkflowVersion.id, WorkflowVersion.number)
        .join(WorkflowVersion, WorkflowVersion.id == Workflow.active_version_id)
        .where(Workflow.enabled.is_(True), uses)
        .order_by(Workflow.tenant_id, Workflow.name)
    )
    refs = tuple(ActiveRef(*row) for row in rows)
    affected = (await s.execute(select(func.count()).select_from(WorkflowVersion).where(uses))).scalar_one()
    return RetirePreview(entry=entry, state=state, active_refs=refs, affected_versions=int(affected))


async def _set_state(s: AsyncSession, entry: Entry, state: str) -> None:
    if entry.kind == "node":
        t, v = split_ref(entry.key)
        stmt = update(NodeTypeVersion).where(NodeTypeVersion.type == t, NodeTypeVersion.version == v)
        await s.execute(stmt.values(state=state, state_changed_at=func.now()))
    else:
        stmt2 = update(CelProfile).where(CelProfile.profile == entry.key)
        await s.execute(stmt2.values(state=state, state_changed_at=func.now()))


async def deprecate(s: AsyncSession, entry: Entry, *, actor_id: uuid.UUID | None) -> str:
    await lock_exclusive(s, entry)
    current = (await states(s, [entry]))[entry]
    if current == "missing":
        raise UnknownEntryError(str(entry))
    if current != "active":
        return current
    await _set_state(s, entry, "deprecated")
    await record(
        s, tenant_id=None, actor_id=actor_id, action="lifecycle.deprecate", target_type=entry.kind, target_id=entry.key
    )
    return "deprecated"


async def retire(
    s: AsyncSession, entry: Entry, *, force: bool = False, confirm: bool = False, actor_id: uuid.UUID | None = None
) -> RetirePreview:
    """Normal path: refuse while an enabled workflow's active closure uses the entry. Forced path: return the
    preview unless `confirm`; with `confirm`, affected workflows stop being startable and each tenant gets an audit
    entry. Runs inside the caller's transaction (READ COMMITTED); the caller commits."""
    await lock_exclusive(s, entry)  # first: every statement below sees references committed before the lock
    current = (await states(s, [entry]))[entry]
    if current == "missing":
        raise UnknownEntryError(str(entry))
    preview = await _preview(s, entry, current)
    if current == "retired":
        return replace(preview, applied=True)
    if preview.active_refs and not force:
        raise ReferencedError(preview)
    if preview.active_refs and not confirm:
        return preview
    await _set_state(s, entry, "retired")
    await record(
        s,
        tenant_id=None,
        actor_id=actor_id,
        action="lifecycle.retire",
        target_type=entry.kind,
        target_id=entry.key,
        details={"forced": bool(preview.active_refs), "active_workflows": len(preview.active_refs)},
    )
    by_tenant: dict[uuid.UUID, list[str]] = {}
    for ref in preview.active_refs:
        by_tenant.setdefault(ref.tenant_id, []).append(str(ref.workflow_id))
    for tenant_id, workflow_ids in sorted(by_tenant.items()):
        await tenant_scope(s, tenant_id)  # tenant audit entries need the tenant context; nothing reads after this
        await record(
            s,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="lifecycle.retire",
            target_type=entry.kind,
            target_id=entry.key,
            details={"forced": True, "workflows": workflow_ids},
        )
    return replace(preview, applied=True)
```

- [ ] **Step 5: Implement the plugin loader**

`backend/src/dewpoint/apps/plugin_loader.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""Discovers installed plugins (entry point group `dewpoint.plugins`) and registers them."""

from collections.abc import Sequence
from importlib.metadata import entry_points
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from dewpoint.core.plugins.registry import NodeTypeRow, SyncReport, ensure_cel_profile, sync_plugins
from dewpoint.engine.cel.profile import CURRENT_CEL_PROFILE
from dewpoint.engine.registry.catalog import contract_hash, validate_plugin_manifest
from dewpoint.sdk import Plugin

GROUP = "dewpoint.plugins"


class PluginLoadError(RuntimeError):
    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


def installed_plugins() -> list[Plugin]:
    plugins: list[Plugin] = []
    for ep in sorted(entry_points(group=GROUP), key=lambda e: e.name):
        obj = ep.load()
        if not isinstance(obj, Plugin):
            raise PluginLoadError([f"entry point {ep.name} is not a dewpoint.sdk.Plugin"])
        plugins.append(obj)
    return plugins


def prepare(plugins: Sequence[Plugin]) -> list[tuple[dict[str, Any], list[NodeTypeRow]]]:
    out: list[tuple[dict[str, Any], list[NodeTypeRow]]] = []
    problems: list[str] = []
    for plugin in plugins:
        manifest = plugin.manifest()  # raises ManifestError for class-level problems
        found = validate_plugin_manifest(manifest)
        problems += found
        if found:
            continue  # never hash a manifest that failed validation: it may hold values canonical JSON rejects
        rows = [
            NodeTypeRow(type=n["type"], version=n["version"], kind=n["kind"], manifest=n, contract_hash=contract_hash(n))
            for n in manifest["nodes"]
        ]
        out.append((manifest, rows))
    if problems:
        raise PluginLoadError(problems)
    return out


async def sync_installed(s: AsyncSession, plugins: Sequence[Plugin]) -> SyncReport:
    report = await sync_plugins(s, prepare(plugins))
    await ensure_cel_profile(s, CURRENT_CEL_PROFILE)
    return report
```

- [ ] **Step 6: Add the CLI commands**

In `backend/src/dewpoint/apps/cli/main.py`, add these imports next to the existing ones. Afterwards, `uv run ruff check --fix src/dewpoint/apps/cli/main.py` puts them in sorted order:

```python
from dewpoint.apps.plugin_loader import PluginLoadError, installed_plugins, prepare
from dewpoint.core.plugins import lifecycle
from dewpoint.core.plugins.lifecycle import Entry
from dewpoint.core.plugins.registry import (
    ContractChangedError,
    MissingNodeTypeError,
    ensure_cel_profile,
    list_node_types,
    sync_plugins,
)
from dewpoint.engine.cel.profile import CURRENT_CEL_PROFILE
from dewpoint.sdk import ManifestError
```

After the existing `keys = typer.Typer(...)` / `app.add_typer(keys, name="keys")` lines, add:

```python
plugins_cli = typer.Typer(no_args_is_help=True)
app.add_typer(plugins_cli, name="plugins")
lifecycle_cli = typer.Typer(no_args_is_help=True)
app.add_typer(lifecycle_cli, name="lifecycle")
```

At the end of the file, append:

```python
@plugins_cli.command("sync")
def plugins_sync() -> None:
    """Register installed plugins and this build's CEL profile. Run as dewpoint_admin on every deploy."""
    try:
        prepared = prepare(installed_plugins())
    except (PluginLoadError, ManifestError) as e:
        for problem in e.problems:
            typer.echo(f"ERROR: {problem}")
        raise typer.Exit(2) from None

    async def _run(s: AsyncSession) -> tuple[int, int]:
        async with s.begin():
            report = await sync_plugins(s, prepared)
            await ensure_cel_profile(s, CURRENT_CEL_PROFILE)
            return len(report.added), len(report.unchanged)

    try:
        added, unchanged = asyncio.run(_in_session(_run))
    except ContractChangedError as e:
        typer.echo(f"ERROR: the contract of {', '.join(e.refs)} changed; publish a new node type version instead")
        raise typer.Exit(2) from None
    except MissingNodeTypeError as e:
        typer.echo(f"ERROR: this build lacks {', '.join(e.refs)}, which are not retired; retire them first")
        raise typer.Exit(2) from None
    typer.echo(f"added {added}, unchanged {unchanged}")


@plugins_cli.command("list")
def plugins_list() -> None:
    """Node type versions that can still be used (active or deprecated)."""

    async def _run(s: AsyncSession) -> list[str]:
        return [f"{row.ref} {row.state}" for row in await list_node_types(s)]

    for line in asyncio.run(_in_session(_run)):
        typer.echo(line)


def _entry(node_type: str | None, cel_profile: str | None) -> Entry:
    if bool(node_type) == bool(cel_profile):
        typer.echo("pass exactly one of --node-type or --cel-profile")
        raise typer.Exit(2)
    return Entry("node", node_type) if node_type else Entry("cel", str(cel_profile))


def _print_preview(preview: lifecycle.RetirePreview) -> None:
    for ref in preview.active_refs:
        typer.echo(f"  tenant {ref.tenant_id}  workflow {ref.workflow_name} ({ref.workflow_id})  v{ref.version_number}")
    typer.echo(f"versions whose closure uses it: {preview.affected_versions}")


@lifecycle_cli.command("deprecate")
def lifecycle_deprecate(
    node_type: str | None = typer.Option(None, help="type@version"),
    cel_profile: str | None = typer.Option(None),
) -> None:
    """Stop new versions from using a node type or CEL profile. Existing ones keep running."""
    entry = _entry(node_type, cel_profile)

    async def _run(s: AsyncSession) -> str:
        async with s.begin():
            return await lifecycle.deprecate(s, entry, actor_id=None)

    try:
        state = asyncio.run(_in_session(_run))
    except lifecycle.UnknownEntryError:
        typer.echo(f"unknown {entry}")
        raise typer.Exit(2) from None
    typer.echo(f"{entry}: {state}")


@lifecycle_cli.command("retire")
def lifecycle_retire(
    node_type: str | None = typer.Option(None, help="type@version"),
    cel_profile: str | None = typer.Option(None),
    force: bool = typer.Option(False, help="Retire even though active workflows use it (they stop being startable)."),
    confirm: bool = typer.Option(False, help="Apply a forced retirement after reviewing its preview."),
) -> None:
    """Retire a node type or CEL profile (spec §4.5). New builds may drop it afterwards."""
    entry = _entry(node_type, cel_profile)

    async def _run(s: AsyncSession) -> lifecycle.RetirePreview:
        async with s.begin():
            return await lifecycle.retire(s, entry, force=force, confirm=confirm)

    try:
        preview = asyncio.run(_in_session(_run))
    except lifecycle.UnknownEntryError:
        typer.echo(f"unknown {entry}")
        raise typer.Exit(2) from None
    except lifecycle.ReferencedError as e:
        _print_preview(e.preview)
        typer.echo("refusing: still used by active workflows. Migrate them, or use --force.")
        raise typer.Exit(4) from None
    _print_preview(preview)
    if not preview.applied:
        typer.echo("forced retirement NOT applied: review the list above, then re-run with --confirm")
        raise typer.Exit(3)
    typer.echo(f"{entry}: retired")
```

- [ ] **Step 7: Run the tests**

Run: `uv run pytest tests/core/plugins tests/apps/cli -q`
Expected: all passed.

- [ ] **Step 8: Commit**

```bash
uv run ruff format . && uv run ruff check . && uv run mypy src && uv run lint-imports && uv run pytest tests/core tests/apps/cli -q && \
git add src/dewpoint/core/plugins src/dewpoint/apps/plugin_loader.py src/dewpoint/apps/cli/main.py tests/core/plugins tests/apps/cli/test_plugins_cli.py tests/support/registry.py && \
git commit -m "feat(core): plugin registration, lifecycle locks and retirement, and their CLI

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: Workflow storage, and the publish and activate orchestration with lifecycle locking

**Files:**
- Create: `backend/src/dewpoint/core/workflows/__init__.py`, `backend/src/dewpoint/core/workflows/service.py`
- Create: `backend/src/dewpoint/apps/workflow_ops.py`
- Modify: `backend/src/dewpoint/core/config.py` (add `max_run_duration_days`)
- Test: `backend/tests/apps/test_workflow_ops.py`, `backend/tests/apps/test_lifecycle_races.py`

**Interfaces:**
- Consumes: Tasks 3–8.
- Produces from `core.workflows.service`:
  - `DraftConflictError(current_revision)`.
  - Workflows: `create_workflow(s, ctx, *, name, draft) -> Workflow`, `get_workflow(s, tenant_id, workflow_id, *, for_update=False)`, `list_workflows(s, tenant_id)`, `save_draft(s, wf, *, expected_revision, draft) -> int`, `update_workflow(s, ctx, wf, *, name, enabled) -> Workflow`.
  - Versions: `NewVersion(...)`, `insert_version(s, ctx, wf, new) -> WorkflowVersion` (sets it active), `set_active(s, ctx, wf, version)`, `get_version(s, workflow_id, version_id)`, `list_versions(s, workflow_id)`, `active_versions(s, tenant_id, workflow_ids) -> {workflow_id: WorkflowVersion}`, `blocked_by(s, version) -> list[str]`.
- Produces from `apps.workflow_ops`:
  - `Checked(graph, diagnostics, pins, result)` and `check_draft(s, tenant_id, draft, settings) -> Checked`.
  - `Published(version, errors, warnings)` and `publish(s, ctx, wf, *, expected_revision, settings) -> Published`. `wf` is locked FOR UPDATE by the caller.
  - `NotActivatableError(errors)` and `activate(s, ctx, wf, version) -> list[Diagnostic]` (warnings).
  - `_lifecycle_locked()`: an async no-op hook that runs right after the lifecycle locks are held; the race tests patch it.
- Settings: `max_run_duration_days: int = 30`.
- Diagnostic codes introduced: `subflow.cycle`, `subflow.too_deep`. It also reuses `lifecycle.retired` and `lifecycle.deprecated`; a `missing` entry reports as `lifecycle.retired`.
- Audit actions: `workflow.create`, `workflow.update`, `workflow.publish`, `workflow.activate`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/apps/test_workflow_ops.py`:

```python
# SPDX-License-Identifier: Apache-2.0
import uuid
from typing import Any

import pytest
from sqlalchemy import text

from dewpoint.apps import workflow_ops
from dewpoint.core.auth.users import create_user
from dewpoint.core.db import tenant_scope
from dewpoint.core.http import TenantContext
from dewpoint.core.plugins import lifecycle
from dewpoint.core.plugins.lifecycle import Entry
from dewpoint.core.workflows import service
from dewpoint.engine.cel.profile import CURRENT_CEL_PROFILE
from tests.apps.api.helpers import PW
from tests.support.graphs import G, nid, ref
from tests.support.registry import sync_test_plugins

ECHO = Entry("node", "testkit.echo@1")
ECHO_GRAPH = G().node("a", "testkit.echo@1", {"value": 1}).data()
SENSITIVE_GRAPH = G().node("s", "testkit.sensitive@1").data()


def runs(workflow_id: uuid.UUID) -> dict[str, Any]:
    return G().node("r", "flow.run_workflow@1", {"workflow_id": str(workflow_id)}).data()


async def actor(owner_sessionmaker: Any) -> TenantContext:
    tenant = uuid.uuid4()
    async with owner_sessionmaker() as s, s.begin():
        user = await create_user(s, email=f"{uuid.uuid4().hex[:8]}@corp.test", password=PW)
        await s.execute(
            text("insert into tenants(id,name,slug) values (:t,'T',:slug)"), {"t": tenant, "slug": tenant.hex[:12]}
        )
    return TenantContext(tenant_id=tenant, user=user, role="editor", session=None)  # type: ignore[arg-type]


async def create(api_sessionmaker: Any, ctx: TenantContext, draft: dict[str, Any], name: str = "W") -> uuid.UUID:
    async with api_sessionmaker() as s, s.begin():
        await tenant_scope(s, ctx.tenant_id)
        return (await service.create_workflow(s, ctx, name=name, draft=draft)).id


async def save(api_sessionmaker: Any, ctx: TenantContext, wf_id: uuid.UUID, draft: dict[str, Any]) -> int:
    async with api_sessionmaker() as s, s.begin():
        await tenant_scope(s, ctx.tenant_id)
        wf = await service.get_workflow(s, ctx.tenant_id, wf_id, for_update=True)
        assert wf is not None
        return await service.save_draft(s, wf, expected_revision=wf.draft_revision, draft=draft)


async def publish(api_sessionmaker: Any, ctx: TenantContext, wf_id: uuid.UUID, settings: Any) -> workflow_ops.Published:
    async with api_sessionmaker() as s, s.begin():
        await tenant_scope(s, ctx.tenant_id)
        wf = await service.get_workflow(s, ctx.tenant_id, wf_id, for_update=True)
        assert wf is not None
        return await workflow_ops.publish(s, ctx, wf, expected_revision=wf.draft_revision, settings=settings)


async def activate(api_sessionmaker: Any, ctx: TenantContext, wf_id: uuid.UUID, version_id: uuid.UUID) -> list[Any]:
    async with api_sessionmaker() as s, s.begin():
        await tenant_scope(s, ctx.tenant_id)
        wf = await service.get_workflow(s, ctx.tenant_id, wf_id, for_update=True)
        version = await service.get_version(s, wf_id, version_id)
        assert wf is not None and version is not None
        return await workflow_ops.activate(s, ctx, wf, version)


async def test_publish_creates_an_active_version_with_its_closure(
    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings
) -> None:
    await sync_test_plugins(admin_sessionmaker)
    ctx = await actor(owner_sessionmaker)
    wf_id = await create(api_sessionmaker, ctx, ECHO_GRAPH)
    out = await publish(api_sessionmaker, ctx, wf_id, api_settings)
    v = out.version
    assert out.errors == [] and v is not None
    assert v.number == 1 and v.node_refs == ["testkit.echo@1"] and v.cel_profile == CURRENT_CEL_PROFILE
    assert v.closure_version_ids == [v.id] and v.closure_workflow_ids == [wf_id] and v.closure_depth == 0
    assert v.closure_node_refs == ["testkit.echo@1"] and v.closure_cel_profiles == [CURRENT_CEL_PROFILE]
    async with api_sessionmaker() as s, s.begin():
        await tenant_scope(s, ctx.tenant_id)
        wf = await service.get_workflow(s, ctx.tenant_id, wf_id)
        assert wf is not None and wf.active_version_id == v.id


async def test_publish_refuses_invalid_graphs_and_stale_revisions(
    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings
) -> None:
    await sync_test_plugins(admin_sessionmaker)
    ctx = await actor(owner_sessionmaker)
    wf_id = await create(api_sessionmaker, ctx, G().node("a", "testkit.echo@1", {"value": ref("steps.nope.output")}).data())
    out = await publish(api_sessionmaker, ctx, wf_id, api_settings)
    assert out.version is None and [d.code for d in out.errors] == ["ref.unknown_step"]
    with pytest.raises(service.DraftConflictError):
        async with api_sessionmaker() as s, s.begin():
            await tenant_scope(s, ctx.tenant_id)
            wf = await service.get_workflow(s, ctx.tenant_id, wf_id, for_update=True)
            assert wf is not None
            await workflow_ops.publish(s, ctx, wf, expected_revision=wf.draft_revision + 1, settings=api_settings)


async def test_subflows_are_pinned_into_the_closure(
    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings
) -> None:
    await sync_test_plugins(admin_sessionmaker)
    ctx = await actor(owner_sessionmaker)
    child = await create(api_sessionmaker, ctx, ECHO_GRAPH, name="child")
    child_v = (await publish(api_sessionmaker, ctx, child, api_settings)).version
    parent = await create(api_sessionmaker, ctx, runs(child), name="parent")
    v = (await publish(api_sessionmaker, ctx, parent, api_settings)).version
    assert child_v is not None and v is not None
    assert v.subflow_version_ids == {str(nid("r")): str(child_v.id)}
    assert set(v.closure_version_ids) == {v.id, child_v.id} and v.closure_depth == 1
    assert v.closure_node_refs == ["flow.run_workflow@1", "testkit.echo@1"]


async def test_version_hash_changes_when_a_pinned_subflow_changes(
    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings
) -> None:
    await sync_test_plugins(admin_sessionmaker)
    ctx = await actor(owner_sessionmaker)
    child = await create(api_sessionmaker, ctx, ECHO_GRAPH, name="child")
    await publish(api_sessionmaker, ctx, child, api_settings)
    parent = await create(api_sessionmaker, ctx, runs(child), name="parent")
    first = (await publish(api_sessionmaker, ctx, parent, api_settings)).version
    await save(api_sessionmaker, ctx, child, SENSITIVE_GRAPH)
    await publish(api_sessionmaker, ctx, child, api_settings)  # the child's active version changes
    second = (await publish(api_sessionmaker, ctx, parent, api_settings)).version  # same parent graph
    assert first is not None and second is not None
    assert second.graph_hash == first.graph_hash and second.version_hash != first.version_hash
    assert second.subflow_version_ids != first.subflow_version_ids


async def test_cycles_through_subflows_are_refused(
    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings
) -> None:
    await sync_test_plugins(admin_sessionmaker)
    ctx = await actor(owner_sessionmaker)
    a = await create(api_sessionmaker, ctx, ECHO_GRAPH, name="a")
    await publish(api_sessionmaker, ctx, a, api_settings)
    b = await create(api_sessionmaker, ctx, runs(a), name="b")
    await publish(api_sessionmaker, ctx, b, api_settings)
    await save(api_sessionmaker, ctx, a, runs(b))  # a would run b, which runs a
    out = await publish(api_sessionmaker, ctx, a, api_settings)
    assert out.version is None and [d.code for d in out.errors] == ["subflow.cycle"]


async def test_deprecated_types_block_publish_even_through_subflows(
    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings
) -> None:
    await sync_test_plugins(admin_sessionmaker)
    ctx = await actor(owner_sessionmaker)
    child = await create(api_sessionmaker, ctx, ECHO_GRAPH, name="child")
    await publish(api_sessionmaker, ctx, child, api_settings)
    parent = await create(api_sessionmaker, ctx, runs(child), name="parent")
    async with admin_sessionmaker() as s, s.begin():
        await lifecycle.deprecate(s, ECHO, actor_id=None)
    out = await publish(api_sessionmaker, ctx, parent, api_settings)
    assert out.version is None and [d.code for d in out.errors] == ["lifecycle.deprecated"]


async def test_rollback_to_a_superseded_version(
    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings
) -> None:
    await sync_test_plugins(admin_sessionmaker)
    ctx = await actor(owner_sessionmaker)
    wf = await create(api_sessionmaker, ctx, ECHO_GRAPH)
    v1 = (await publish(api_sessionmaker, ctx, wf, api_settings)).version
    await save(api_sessionmaker, ctx, wf, SENSITIVE_GRAPH)
    v2 = (await publish(api_sessionmaker, ctx, wf, api_settings)).version
    assert v1 is not None and v2 is not None and v2.number == 2
    assert await activate(api_sessionmaker, ctx, wf, v1.id) == []  # superseded, still activatable
    async with admin_sessionmaker() as s, s.begin():
        await lifecycle.retire(s, ECHO, force=True, confirm=True)
    assert await activate(api_sessionmaker, ctx, wf, v2.id) == []
    with pytest.raises(workflow_ops.NotActivatableError) as e:
        await activate(api_sessionmaker, ctx, wf, v1.id)
    assert [d.code for d in e.value.errors] == ["lifecycle.retired"]


async def test_retiring_a_subflow_type_blocks_its_parents(
    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings
) -> None:
    await sync_test_plugins(admin_sessionmaker)
    ctx = await actor(owner_sessionmaker)
    child = await create(api_sessionmaker, ctx, ECHO_GRAPH, name="child")
    await publish(api_sessionmaker, ctx, child, api_settings)
    parent = await create(api_sessionmaker, ctx, runs(child), name="parent")
    await publish(api_sessionmaker, ctx, parent, api_settings)
    async with admin_sessionmaker() as s, s.begin():
        preview = await lifecycle.retire(s, ECHO, force=True)
    assert {r.workflow_id for r in preview.active_refs} == {child, parent}  # parent reaches echo only via child
    async with admin_sessionmaker() as s, s.begin():
        await lifecycle.retire(s, ECHO, force=True, confirm=True)
    async with api_sessionmaker() as s, s.begin():
        await tenant_scope(s, ctx.tenant_id)
        wf = await service.get_workflow(s, ctx.tenant_id, parent)
        assert wf is not None and wf.active_version_id is not None
        version = await service.get_version(s, parent, wf.active_version_id)
        assert version is not None and await service.blocked_by(s, version) == ["testkit.echo@1"]
```

`backend/tests/apps/test_lifecycle_races.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""Publish and activate serialize with retirement through the lifecycle locks (spec §4.5), in either order."""

import asyncio
from typing import Any

import pytest
from sqlalchemy import text

from dewpoint.apps import workflow_ops
from dewpoint.core.plugins import lifecycle
from dewpoint.core.plugins.lifecycle import Entry
from tests.apps.test_workflow_ops import ECHO_GRAPH, SENSITIVE_GRAPH, activate, actor, create, publish, save
from tests.support.registry import sync_test_plugins

ECHO = Entry("node", "testkit.echo@1")


async def until_someone_waits_for_a_lifecycle_lock(owner_sessionmaker: Any) -> None:
    for _ in range(200):
        async with owner_sessionmaker() as s:
            waiting = (
                await s.execute(text("select count(*) from pg_locks where locktype = 'advisory' and not granted"))
            ).scalar_one()
        if waiting:
            return
        await asyncio.sleep(0.05)
    raise AssertionError("nobody is waiting for a lifecycle lock")


@pytest.fixture
def pause_after_lock(monkeypatch):  # type: ignore[no-untyped-def]
    reached, release = asyncio.Event(), asyncio.Event()

    async def paused() -> None:
        reached.set()
        await release.wait()

    monkeypatch.setattr(workflow_ops, "_lifecycle_locked", paused)
    return reached, release


async def test_retirement_first_makes_publish_refuse(
    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings
) -> None:
    await sync_test_plugins(admin_sessionmaker)
    ctx = await actor(owner_sessionmaker)
    wf = await create(api_sessionmaker, ctx, ECHO_GRAPH)
    async with admin_sessionmaker() as a:
        async with a.begin():
            await lifecycle.lock_exclusive(a, ECHO)
            publishing = asyncio.create_task(publish(api_sessionmaker, ctx, wf, api_settings))
            await until_someone_waits_for_a_lifecycle_lock(owner_sessionmaker)
            assert (await lifecycle.retire(a, ECHO)).applied
    out = await asyncio.wait_for(publishing, 10)
    assert out.version is None and [d.code for d in out.errors] == ["lifecycle.retired"]


async def test_publish_first_blocks_normal_retirement(
    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings, pause_after_lock
) -> None:
    reached, release = pause_after_lock
    await sync_test_plugins(admin_sessionmaker)
    ctx = await actor(owner_sessionmaker)
    wf = await create(api_sessionmaker, ctx, ECHO_GRAPH)
    publishing = asyncio.create_task(publish(api_sessionmaker, ctx, wf, api_settings))
    await asyncio.wait_for(reached.wait(), 10)

    async def retire() -> lifecycle.RetirePreview:
        async with admin_sessionmaker() as a, a.begin():
            return await lifecycle.retire(a, ECHO)

    retiring = asyncio.create_task(retire())
    await until_someone_waits_for_a_lifecycle_lock(owner_sessionmaker)
    release.set()
    assert (await asyncio.wait_for(publishing, 10)).version is not None
    with pytest.raises(lifecycle.ReferencedError) as e:
        await asyncio.wait_for(retiring, 10)
    assert [r.workflow_id for r in e.value.preview.active_refs] == [wf]


async def test_publish_first_is_included_in_a_forced_retirement(
    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings, pause_after_lock
) -> None:
    reached, release = pause_after_lock
    await sync_test_plugins(admin_sessionmaker)
    ctx = await actor(owner_sessionmaker)
    wf = await create(api_sessionmaker, ctx, ECHO_GRAPH)
    publishing = asyncio.create_task(publish(api_sessionmaker, ctx, wf, api_settings))
    await asyncio.wait_for(reached.wait(), 10)

    async def retire() -> lifecycle.RetirePreview:
        async with admin_sessionmaker() as a, a.begin():
            return await lifecycle.retire(a, ECHO, force=True, confirm=True)

    retiring = asyncio.create_task(retire())
    await until_someone_waits_for_a_lifecycle_lock(owner_sessionmaker)
    release.set()
    assert (await asyncio.wait_for(publishing, 10)).version is not None
    preview = await asyncio.wait_for(retiring, 10)
    assert preview.applied and [r.workflow_id for r in preview.active_refs] == [wf]
    async with owner_sessionmaker() as s:
        tenants = (
            await s.execute(text("select tenant_id from audit_log where action = 'lifecycle.retire' and tenant_id is not null"))
        ).scalars().all()
    assert tenants == [ctx.tenant_id]


async def test_retirement_first_makes_activate_refuse(
    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings
) -> None:
    await sync_test_plugins(admin_sessionmaker)
    ctx = await actor(owner_sessionmaker)
    wf = await create(api_sessionmaker, ctx, ECHO_GRAPH)
    v1 = (await publish(api_sessionmaker, ctx, wf, api_settings)).version
    await save(api_sessionmaker, ctx, wf, SENSITIVE_GRAPH)
    await publish(api_sessionmaker, ctx, wf, api_settings)  # v2 is active and doesn't use echo
    assert v1 is not None
    async with admin_sessionmaker() as a:
        async with a.begin():
            await lifecycle.lock_exclusive(a, ECHO)
            activating = asyncio.create_task(activate(api_sessionmaker, ctx, wf, v1.id))
            await until_someone_waits_for_a_lifecycle_lock(owner_sessionmaker)
            assert (await lifecycle.retire(a, ECHO)).applied  # nothing active uses echo: normal path
    with pytest.raises(workflow_ops.NotActivatableError):
        await asyncio.wait_for(activating, 10)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/apps/test_workflow_ops.py tests/apps/test_lifecycle_races.py -q`
Expected: FAIL: `ImportError: cannot import name 'workflow_ops'`.

- [ ] **Step 3: Add the setting**

In `backend/src/dewpoint/core/config.py`, add this field to `Settings`, after `webauthn_challenges_max`:

```python
    max_run_duration_days: int = 30  # spec §6: whole logical run, including continue-as-new and waits
```

- [ ] **Step 4: Implement workflow storage**

`backend/src/dewpoint/core/workflows/__init__.py`:

```python
# SPDX-License-Identifier: Apache-2.0
```

`backend/src/dewpoint/core/workflows/service.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""Storage for workflows and their immutable versions. Graph validation is in the engine; apps wires the two."""

import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from dewpoint.core.audit.service import record
from dewpoint.core.http import TenantContext
from dewpoint.core.models.workflows import Workflow, WorkflowVersion
from dewpoint.core.plugins import lifecycle


class DraftConflictError(Exception):
    def __init__(self, current_revision: int) -> None:
        super().__init__(f"draft is at revision {current_revision}")
        self.current_revision = current_revision


async def create_workflow(s: AsyncSession, ctx: TenantContext, *, name: str, draft: dict[str, Any]) -> Workflow:
    wf = Workflow(
        id=uuid.uuid4(),
        tenant_id=ctx.tenant_id,
        name=name,
        enabled=True,
        draft=draft,
        draft_revision=1,
        created_by=ctx.user.id,
    )
    s.add(wf)
    await s.flush()
    await s.refresh(wf)
    await record(
        s,
        tenant_id=ctx.tenant_id,
        actor_id=ctx.user.id,
        action="workflow.create",
        target_type="workflow",
        target_id=str(wf.id),
        details={"name": name},
    )
    return wf


async def get_workflow(
    s: AsyncSession, tenant_id: uuid.UUID, workflow_id: uuid.UUID, *, for_update: bool = False
) -> Workflow | None:
    q = select(Workflow).where(Workflow.id == workflow_id, Workflow.tenant_id == tenant_id)
    if for_update:
        q = q.with_for_update()
    return (await s.execute(q)).scalar_one_or_none()


async def list_workflows(s: AsyncSession, tenant_id: uuid.UUID) -> list[Workflow]:
    rows = await s.execute(select(Workflow).where(Workflow.tenant_id == tenant_id).order_by(Workflow.name))
    return list(rows.scalars())


async def save_draft(s: AsyncSession, wf: Workflow, *, expected_revision: int, draft: dict[str, Any]) -> int:
    """Compare-and-swap on draft_revision: a stale editor gets DraftConflictError instead of overwriting."""
    revision = (
        await s.execute(
            update(Workflow)
            .where(Workflow.id == wf.id, Workflow.draft_revision == expected_revision)
            .values(draft=draft, draft_revision=Workflow.draft_revision + 1, updated_at=func.now())
            .returning(Workflow.draft_revision)
            .execution_options(synchronize_session=False)
        )
    ).scalar_one_or_none()
    if revision is None:
        current = (await s.execute(select(Workflow.draft_revision).where(Workflow.id == wf.id))).scalar_one()
        raise DraftConflictError(int(current))
    return int(revision)


async def update_workflow(
    s: AsyncSession, ctx: TenantContext, wf: Workflow, *, name: str | None, enabled: bool | None
) -> Workflow:
    changes: dict[str, object] = {}
    if name is not None and name != wf.name:
        wf.name = name
        changes["name"] = name
    if enabled is not None and enabled != wf.enabled:
        wf.enabled = enabled
        changes["enabled"] = enabled
    if changes:
        await s.flush()
        await s.refresh(wf)
        await record(
            s,
            tenant_id=wf.tenant_id,
            actor_id=ctx.user.id,
            action="workflow.update",
            target_type="workflow",
            target_id=str(wf.id),
            details=changes,
        )
    return wf


@dataclass(frozen=True)
class NewVersion:
    id: uuid.UUID
    graph: dict[str, Any]
    node_refs: list[str]
    engine_abi: int
    cel_profile: str
    subflow_version_ids: dict[str, str]
    failure_handler_version_id: uuid.UUID | None
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    vars_schema: dict[str, Any]
    closure_version_ids: list[uuid.UUID]
    closure_workflow_ids: list[uuid.UUID]
    closure_node_refs: list[str]
    closure_cel_profiles: list[str]
    closure_depth: int
    graph_hash: str
    version_hash: str
    expressions: list[Any] = field(default_factory=list)
    connection_ids: list[uuid.UUID] = field(default_factory=list)


async def insert_version(s: AsyncSession, ctx: TenantContext, wf: Workflow, new: NewVersion) -> WorkflowVersion:
    """Insert the next version and make it active. The caller holds the workflow row lock."""
    latest = await s.execute(
        select(func.coalesce(func.max(WorkflowVersion.number), 0)).where(WorkflowVersion.workflow_id == wf.id)
    )
    number = int(latest.scalar_one()) + 1
    version = WorkflowVersion(
        id=new.id,
        tenant_id=wf.tenant_id,
        workflow_id=wf.id,
        number=number,
        graph=new.graph,
        node_refs=new.node_refs,
        engine_abi=new.engine_abi,
        cel_profile=new.cel_profile,
        connection_ids=new.connection_ids,
        subflow_version_ids=new.subflow_version_ids,
        failure_handler_version_id=new.failure_handler_version_id,
        input_schema=new.input_schema,
        output_schema=new.output_schema,
        vars_schema=new.vars_schema,
        expressions=new.expressions,
        closure_version_ids=new.closure_version_ids,
        closure_workflow_ids=new.closure_workflow_ids,
        closure_node_refs=new.closure_node_refs,
        closure_cel_profiles=new.closure_cel_profiles,
        closure_depth=new.closure_depth,
        graph_hash=new.graph_hash,
        version_hash=new.version_hash,
        published_by=ctx.user.id,
    )
    s.add(version)
    await s.flush()
    await s.refresh(version)
    wf.active_version_id = version.id
    await s.flush()
    await record(
        s,
        tenant_id=wf.tenant_id,
        actor_id=ctx.user.id,
        action="workflow.publish",
        target_type="workflow",
        target_id=str(wf.id),
        details={
            "version": number,
            "version_id": str(version.id),
            "graph_hash": new.graph_hash,
            "version_hash": new.version_hash,
            "closure_depth": new.closure_depth,
        },
    )
    return version


async def set_active(s: AsyncSession, ctx: TenantContext, wf: Workflow, version: WorkflowVersion) -> None:
    wf.active_version_id = version.id
    await s.flush()
    await record(
        s,
        tenant_id=wf.tenant_id,
        actor_id=ctx.user.id,
        action="workflow.activate",
        target_type="workflow",
        target_id=str(wf.id),
        details={"version": version.number, "version_id": str(version.id)},
    )


async def get_version(s: AsyncSession, workflow_id: uuid.UUID, version_id: uuid.UUID) -> WorkflowVersion | None:
    q = select(WorkflowVersion).where(WorkflowVersion.id == version_id, WorkflowVersion.workflow_id == workflow_id)
    return (await s.execute(q)).scalar_one_or_none()


async def list_versions(s: AsyncSession, workflow_id: uuid.UUID) -> list[WorkflowVersion]:
    q = select(WorkflowVersion).where(WorkflowVersion.workflow_id == workflow_id).order_by(WorkflowVersion.number.desc())
    return list((await s.execute(q)).scalars())


async def active_versions(
    s: AsyncSession, tenant_id: uuid.UUID, workflow_ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, WorkflowVersion]:
    ids = sorted(set(workflow_ids), key=str)
    if not ids:
        return {}
    rows = await s.execute(
        select(Workflow.id, WorkflowVersion)
        .join(WorkflowVersion, WorkflowVersion.id == Workflow.active_version_id)
        .where(Workflow.tenant_id == tenant_id, Workflow.id.in_(ids))
    )
    return {workflow_id: version for workflow_id, version in rows}


async def blocked_by(s: AsyncSession, version: WorkflowVersion) -> list[str]:
    """Lifecycle entries in the version's closure that stop it from running (retired or missing)."""
    current = await lifecycle.states(
        s, lifecycle.entries_for(version.closure_node_refs, version.closure_cel_profiles)
    )
    return [e.key for e in lifecycle.not_executable(current)]
```

- [ ] **Step 5: Implement the orchestration**

`backend/src/dewpoint/apps/workflow_ops.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""Validate, publish and activate workflows: wires core storage to the engine validator (spec §4.4–4.5)."""

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from dewpoint.core.config import Settings
from dewpoint.core.http import TenantContext
from dewpoint.core.models.workflows import Workflow, WorkflowVersion
from dewpoint.core.plugins import lifecycle, registry
from dewpoint.core.workflows import service
from dewpoint.engine import ENGINE_ABI
from dewpoint.engine.cel.profile import CURRENT_CEL_PROFILE
from dewpoint.engine.graph.diagnostics import Diagnostic
from dewpoint.engine.graph.model import Graph, GraphFormatError, graph_hash, graph_json, parse_graph, version_hash
from dewpoint.engine.graph.validate import (
    MAX_SUBFLOW_DEPTH,
    SubflowInfo,
    ValidationContext,
    ValidationResult,
    referenced_workflows,
    validate,
)
from dewpoint.engine.registry.catalog import Catalog, spec_from_manifest


async def _lifecycle_locked() -> None:
    """Hook that runs right after the lifecycle locks are held. A no-op; the race tests pause here."""


@dataclass(frozen=True)
class Checked:
    graph: Graph | None
    diagnostics: list[Diagnostic]
    pins: dict[uuid.UUID, WorkflowVersion]  # pinned workflow id -> its active version
    result: ValidationResult | None


async def check_draft(s: AsyncSession, tenant_id: uuid.UUID, draft: Any, settings: Settings) -> Checked:
    try:
        graph = parse_graph(draft)
    except GraphFormatError as e:
        return Checked(None, list(e.diagnostics), {}, None)
    rows = await registry.load_node_types(s, {n.type for n in graph.nodes})
    catalog = Catalog(spec_from_manifest(r.manifest, r.state) for r in rows)
    pins = await service.active_versions(s, tenant_id, referenced_workflows(graph))
    ctx = ValidationContext(
        catalog=catalog,
        subflows={wid: SubflowInfo(wid, v.id, v.input_schema, v.output_schema) for wid, v in pins.items()},
        max_run_duration=timedelta(days=settings.max_run_duration_days),
    )
    result = validate(graph, ctx)
    return Checked(graph, list(result.diagnostics), pins, result)


@dataclass(frozen=True)
class Published:
    version: WorkflowVersion | None
    errors: list[Diagnostic]
    warnings: list[Diagnostic]


class NotActivatableError(Exception):
    def __init__(self, errors: list[Diagnostic]) -> None:
        super().__init__("; ".join(d.message for d in errors))
        self.errors = errors


def _depth(pins: Mapping[uuid.UUID, WorkflowVersion]) -> int:
    return 1 + max(v.closure_depth for v in pins.values()) if pins else 0


def _pin_errors(workflow_id: uuid.UUID, pins: Mapping[uuid.UUID, WorkflowVersion]) -> list[Diagnostic]:
    out: list[Diagnostic] = []
    if any(wid == workflow_id or workflow_id in v.closure_workflow_ids for wid, v in pins.items()):
        out.append(
            Diagnostic(
                code="subflow.cycle",
                message="This workflow would end up running itself.",
                fix="Remove the step that runs it, directly or through another workflow.",
            )
        )
    depth = _depth(pins)
    if depth > MAX_SUBFLOW_DEPTH:
        out.append(
            Diagnostic(
                code="subflow.too_deep",
                message=f"Sub-flows can be nested at most {MAX_SUBFLOW_DEPTH} deep; this would be {depth}.",
            )
        )
    return out


def _lifecycle_errors(current: Mapping[lifecycle.Entry, str], *, refuse_deprecated: bool) -> list[Diagnostic]:
    out: list[Diagnostic] = []
    for entry, state in sorted(current.items()):
        if state in ("retired", "missing"):
            out.append(
                Diagnostic(code="lifecycle.retired", message=f"{entry} has been retired.", fix="Replace what uses it.")
            )
        elif state == "deprecated" and refuse_deprecated:
            out.append(
                Diagnostic(
                    code="lifecycle.deprecated",
                    message=f"{entry} is deprecated; new versions can't use it.",
                    fix="Migrate to its newer version.",
                )
            )
    return out


async def publish(
    s: AsyncSession, ctx: TenantContext, wf: Workflow, *, expected_revision: int, settings: Settings
) -> Published:
    """Validate the draft and insert it as the new active version. `wf` must be locked FOR UPDATE."""
    if wf.draft_revision != expected_revision:
        raise service.DraftConflictError(wf.draft_revision)
    checked = await check_draft(s, ctx.tenant_id, wf.draft, settings)
    errors = [d for d in checked.diagnostics if d.severity == "error"]
    warnings = [d for d in checked.diagnostics if d.severity == "warning"]
    if checked.graph is None or checked.result is None or errors:
        return Published(None, errors, warnings)
    errors = _pin_errors(wf.id, checked.pins)
    if errors:
        return Published(None, errors, warnings)
    pins = list(checked.pins.values())
    closure_node_refs = sorted({*checked.result.node_refs, *(r for v in pins for r in v.closure_node_refs)})
    closure_cel_profiles = sorted({CURRENT_CEL_PROFILE, *(p for v in pins for p in v.closure_cel_profiles)})
    entries = lifecycle.entries_for(closure_node_refs, closure_cel_profiles)
    await lifecycle.lock_shared(s, entries)
    await _lifecycle_locked()
    errors = _lifecycle_errors(await lifecycle.states(s, entries), refuse_deprecated=True)
    if errors:
        return Published(None, errors, warnings)
    version_id = uuid.uuid4()
    graph_settings = checked.graph.settings
    authored = graph_hash(checked.graph)
    fh = checked.result.failure_handler_version_id
    version = await service.insert_version(
        s,
        ctx,
        wf,
        service.NewVersion(
            id=version_id,
            graph=graph_json(checked.graph),
            node_refs=list(checked.result.node_refs),
            engine_abi=ENGINE_ABI,
            cel_profile=CURRENT_CEL_PROFILE,
            subflow_version_ids=dict(checked.result.subflow_pins),
            failure_handler_version_id=checked.result.failure_handler_version_id,
            input_schema=dict(graph_settings.input_schema),
            output_schema=dict(checked.result.output_schema),
            vars_schema=dict(graph_settings.vars_schema),
            closure_version_ids=[version_id, *sorted({i for v in pins for i in v.closure_version_ids}, key=str)],
            closure_workflow_ids=[wf.id, *sorted({i for v in pins for i in v.closure_workflow_ids}, key=str)],
            closure_node_refs=closure_node_refs,
            closure_cel_profiles=closure_cel_profiles,
            closure_depth=_depth(checked.pins),
            graph_hash=authored,
            version_hash=version_hash(
                graph_hash=authored,
                subflow_pins=checked.result.subflow_pins,
                failure_handler_version_id=str(fh) if fh else None,
                cel_profile=CURRENT_CEL_PROFILE,
                engine_abi=ENGINE_ABI,
            ),
        ),
    )
    return Published(version, [], warnings)


async def activate(s: AsyncSession, ctx: TenantContext, wf: Workflow, version: WorkflowVersion) -> list[Diagnostic]:
    """Make an existing version active (rollback). Any executable version qualifies, superseded or not.
    `wf` must be locked FOR UPDATE. Returns warnings; raises NotActivatableError if the version can't run."""
    entries = lifecycle.entries_for(version.closure_node_refs, version.closure_cel_profiles)
    await lifecycle.lock_shared(s, entries)
    await _lifecycle_locked()
    current = await lifecycle.states(s, entries)
    errors = _lifecycle_errors(current, refuse_deprecated=False)
    if errors:
        raise NotActivatableError(errors)
    await service.set_active(s, ctx, wf, version)
    return [
        Diagnostic(
            code="lifecycle.deprecated",
            severity="warning",
            message=f"{entry} is deprecated.",
            fix="Publish a new version that migrates it.",
        )
        for entry, state in sorted(current.items())
        if state == "deprecated"
    ]
```

- [ ] **Step 6: Run the tests**

Run: `uv run pytest tests/apps/test_workflow_ops.py tests/apps/test_lifecycle_races.py -q`
Expected: 12 passed.

- [ ] **Step 7: Commit**

```bash
uv run ruff format . && uv run ruff check . && uv run mypy src && uv run lint-imports && uv run pytest tests/apps tests/core -q && \
git add src/dewpoint/core/config.py src/dewpoint/core/workflows src/dewpoint/apps/workflow_ops.py tests/apps/test_workflow_ops.py tests/apps/test_lifecycle_races.py && \
git commit -m "feat(workflows): publish and activate with pinned closures and lifecycle locking

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: Workflow and node-type API routes

**Files:**
- Create: `backend/src/dewpoint/apps/api/routes/workflows.py`, `backend/src/dewpoint/apps/api/routes/node_types.py`
- Modify: `backend/src/dewpoint/apps/api/main.py`
- Test: `backend/tests/apps/api/test_workflows.py`

**Interfaces:**
- Consumes: `workflow_ops` and `service` (Task 9); `registry.list_node_types` (Task 8); `require`, `get_db`, `active_session` and `get_settings_dep` from `core.http`.
- Produces these routes, all under `/api/v1`:
  - `GET /node-types` (any signed-in user): the active and deprecated types, with their schemas.
  - `GET /t/{tenant_id}/workflows` (`workflow.view`).
  - `POST /t/{tenant_id}/workflows` (`workflow.edit`), body `{name, draft?}`: returns 201 with the summary and `draft`, or 409 `name_taken`.
  - `GET /t/{tenant_id}/workflows/{id}` (`workflow.view`): the summary plus `draft`.
  - `PUT /t/{tenant_id}/workflows/{id}/draft` (`workflow.edit`, `If-Match: <revision>`): returns `{draft_revision}`. Errors: 428 `revision_required`, 409 `{error: draft_conflict, draft_revision}`, 422 `{error: invalid, diagnostics}` for a malformed graph, 413 `too_large` above 1 MiB.
  - `PATCH /t/{tenant_id}/workflows/{id}` (`workflow.publish`), body `{name?, enabled?}`.
  - `POST /t/{tenant_id}/workflows/{id}/validate` (`workflow.edit`): returns `{draft_revision, valid, diagnostics}`.
  - `POST /t/{tenant_id}/workflows/{id}/publish` (`workflow.publish`, `If-Match`): returns 201 `{version_id, number, warnings}`; otherwise 422 `{error: invalid, diagnostics}` or 409 `draft_conflict`.
  - `GET /t/{tenant_id}/workflows/{id}/versions` (`workflow.view`): `[{id, number, published_at, published_by, graph_hash, version_hash, cel_profile, node_refs, active, executable, blocked_by}]`.
  - `POST /t/{tenant_id}/workflows/{id}/activate` (`workflow.publish`), body `{version_id}`: returns `{active_version_id, number, warnings}`; otherwise 404, or 422 `{error: not_activatable, diagnostics}`.
- The workflow summary is `{id, name, enabled, draft_revision, active_version_id, active_version_number, executable (null when unpublished), blocked_by, created_at, updated_at}`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/apps/api/test_workflows.py`:

```python
# SPDX-License-Identifier: Apache-2.0
import uuid

import pytest

from dewpoint.core.plugins import lifecycle
from dewpoint.core.plugins.lifecycle import Entry
from tests.apps.api.helpers import member_client, session_client
from tests.support.graphs import G, ref
from tests.support.registry import sync_test_plugins

GRAPH = G().node("a", "testkit.echo@1", {"value": 1}).data()


@pytest.fixture(autouse=True)
async def synced(admin_sessionmaker) -> None:
    await sync_test_plugins(admin_sessionmaker)


async def test_draft_edit_validate_publish_flow(app, owner_sessionmaker, api_settings) -> None:
    c, tid = await session_client(app, owner_sessionmaker, api_settings, "admin")
    async with c:
        r = await c.post(f"/api/v1/t/{tid}/workflows", json={"name": "Nightly"})
        assert r.status_code == 201, r.text
        wf = r.json()
        base = f"/api/v1/t/{tid}/workflows/{wf['id']}"
        assert wf["draft_revision"] == 1 and wf["active_version_id"] is None and wf["executable"] is None
        assert (await c.put(f"{base}/draft", json=GRAPH)).status_code == 428
        stale = await c.put(f"{base}/draft", json=GRAPH, headers={"If-Match": "7"})
        assert stale.status_code == 409 and stale.json() == {"error": "draft_conflict", "draft_revision": 1}
        saved = await c.put(f"{base}/draft", json=GRAPH, headers={"If-Match": "1"})
        assert saved.status_code == 200 and saved.json() == {"draft_revision": 2}
        checked = (await c.post(f"{base}/validate")).json()
        assert checked["valid"] is True and checked["diagnostics"] == []
        published = await c.post(f"{base}/publish", headers={"If-Match": '"2"'})
        assert published.status_code == 201, published.text
        assert published.json()["number"] == 1
        got = (await c.get(base)).json()
        assert got["active_version_number"] == 1 and got["executable"] is True
        assert got["draft"]["nodes"][0]["key"] == "a"
        versions = (await c.get(f"{base}/versions")).json()
        assert [(v["number"], v["active"], v["executable"]) for v in versions] == [(1, True, True)]
        actions = [e["action"] for e in (await c.get(f"/api/v1/t/{tid}/audit")).json()]
    assert actions[:2] == ["workflow.publish", "workflow.create"]


async def test_publish_and_draft_report_diagnostics(app, owner_sessionmaker, api_settings) -> None:
    c, tid = await session_client(app, owner_sessionmaker, api_settings, "editor")
    async with c:
        bad = G().node("a", "testkit.echo@1", {"value": ref("steps.nope.output")}).data()
        wf = (await c.post(f"/api/v1/t/{tid}/workflows", json={"name": "Bad", "draft": bad})).json()
        base = f"/api/v1/t/{tid}/workflows/{wf['id']}"
        r = await c.post(f"{base}/publish", headers={"If-Match": "1"})
        assert r.status_code == 422
        assert r.json()["error"] == "invalid" and [d["code"] for d in r.json()["diagnostics"]] == ["ref.unknown_step"]
        malformed = await c.put(f"{base}/draft", json={"nodes": [{"key": "Bad Key"}]}, headers={"If-Match": "1"})
        assert malformed.status_code == 422 and malformed.json()["diagnostics"][0]["code"] == "graph.format"


async def test_activate_rolls_back(app, owner_sessionmaker, api_settings) -> None:
    c, tid = await session_client(app, owner_sessionmaker, api_settings, "editor")
    async with c:
        wf = (await c.post(f"/api/v1/t/{tid}/workflows", json={"name": "W", "draft": GRAPH})).json()
        base = f"/api/v1/t/{tid}/workflows/{wf['id']}"
        v1 = (await c.post(f"{base}/publish", headers={"If-Match": "1"})).json()
        other = G().node("s", "testkit.sensitive@1").data()
        assert (await c.put(f"{base}/draft", json=other, headers={"If-Match": "1"})).status_code == 200
        v2 = (await c.post(f"{base}/publish", headers={"If-Match": "2"})).json()
        assert v2["number"] == 2
        r = await c.post(f"{base}/activate", json={"version_id": v1["version_id"]})
        assert r.status_code == 200 and r.json()["number"] == 1
        assert (await c.get(base)).json()["active_version_number"] == 1
        missing = await c.post(f"{base}/activate", json={"version_id": str(uuid.uuid4())})
        assert missing.status_code == 404


async def test_permission_matrix(app, owner_sessionmaker, api_settings) -> None:
    editor, tid = await session_client(app, owner_sessionmaker, api_settings, "editor")
    async with editor:
        wf = (await editor.post(f"/api/v1/t/{tid}/workflows", json={"name": "W", "draft": GRAPH})).json()
    base = f"/api/v1/t/{tid}/workflows/{wf['id']}"
    for role in ("viewer", "operator"):
        c, _ = await member_client(app, owner_sessionmaker, api_settings, tid, role)
        async with c:
            assert (await c.get(base)).status_code == 200
            assert (await c.get(f"{base}/versions")).status_code == 200
            assert (await c.post(f"/api/v1/t/{tid}/workflows", json={"name": role})).status_code == 403
            assert (await c.put(f"{base}/draft", json=GRAPH, headers={"If-Match": "1"})).status_code == 403
            assert (await c.post(f"{base}/validate")).status_code == 403
            assert (await c.post(f"{base}/publish", headers={"If-Match": "1"})).status_code == 403
            assert (await c.patch(base, json={"enabled": False})).status_code == 403
    stranger, other_tenant = await session_client(app, owner_sessionmaker, api_settings, "owner")
    async with stranger:
        assert (await stranger.get(f"/api/v1/t/{other_tenant}/workflows/{wf['id']}")).status_code == 404
        assert (await stranger.get(base)).status_code == 404


async def test_disable_and_rename(app, owner_sessionmaker, api_settings) -> None:
    c, tid = await session_client(app, owner_sessionmaker, api_settings, "editor")
    async with c:
        a = (await c.post(f"/api/v1/t/{tid}/workflows", json={"name": "A"})).json()
        await c.post(f"/api/v1/t/{tid}/workflows", json={"name": "B"})
        r = await c.patch(f"/api/v1/t/{tid}/workflows/{a['id']}", json={"enabled": False, "name": "Renamed"})
        assert r.status_code == 200 and r.json()["enabled"] is False and r.json()["name"] == "Renamed"
        taken = await c.patch(f"/api/v1/t/{tid}/workflows/{a['id']}", json={"name": "B"})
        assert taken.status_code == 409 and taken.json() == {"error": "name_taken"}


async def test_oversized_draft_is_rejected(app, owner_sessionmaker, api_settings) -> None:
    c, tid = await session_client(app, owner_sessionmaker, api_settings, "editor")
    async with c:
        wf = (await c.post(f"/api/v1/t/{tid}/workflows", json={"name": "W"})).json()
        huge = {"graph_format": 1, "settings": {"outputs": {"x": "a" * (1024 * 1024)}}}
        r = await c.put(f"/api/v1/t/{tid}/workflows/{wf['id']}/draft", json=huge, headers={"If-Match": "1"})
        assert r.status_code == 413 and r.json() == {"error": "too_large"}


async def test_node_types_catalog(app, owner_sessionmaker, api_settings, admin_sessionmaker) -> None:
    async with admin_sessionmaker() as s, s.begin():
        await lifecycle.deprecate(s, Entry("node", "testkit.slow@1"), actor_id=None)
        await lifecycle.retire(s, Entry("node", "testkit.fail_n@1"))
    c, _ = await session_client(app, owner_sessionmaker, api_settings, "viewer")
    async with c:
        types = {t["ref"]: t for t in (await c.get("/api/v1/node-types")).json()}
    assert types["flow.if@1"]["ports"] == ["true", "false"] and types["testkit.echo@1"]["state"] == "active"
    assert types["testkit.slow@1"]["state"] == "deprecated" and "testkit.fail_n@1" not in types
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/apps/api/test_workflows.py -q`
Expected: FAIL; the routes don't exist, so the first request returns 404.

- [ ] **Step 3: Implement the routes**

`backend/src/dewpoint/apps/api/routes/node_types.py`:

```python
# SPDX-License-Identifier: Apache-2.0
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from dewpoint.core.http import active_session, get_db
from dewpoint.core.plugins import registry

router = APIRouter(prefix="/api/v1", tags=["node-types"])


@router.get("/node-types", dependencies=[Depends(active_session)])
async def node_types(db: AsyncSession = Depends(get_db, scope="function")) -> list[dict[str, object]]:
    """The editor's palette: node types that new versions may use (active) or still carry (deprecated)."""
    return [
        {
            "ref": row.ref,
            "type": row.type,
            "version": row.version,
            "kind": row.kind,
            "state": row.state,
            "title": row.manifest.get("title"),
            "description": row.manifest.get("description", ""),
            "ports": row.manifest.get("ports", []),
            "dynamic_ports": row.manifest.get("dynamic_ports"),
            "config_schema": row.manifest.get("config_schema"),
            "output_schema": row.manifest.get("output_schema"),
        }
        for row in await registry.list_node_types(db)
    ]
```

`backend/src/dewpoint/apps/api/routes/workflows.py`:

```python
# SPDX-License-Identifier: Apache-2.0
import uuid
from typing import Any

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from dewpoint.apps import workflow_ops
from dewpoint.core.authz.permissions import P
from dewpoint.core.config import Settings
from dewpoint.core.http import TenantContext, get_db, get_settings_dep, require
from dewpoint.core.models.workflows import Workflow, WorkflowVersion
from dewpoint.core.workflows import service
from dewpoint.engine.graph.model import GraphFormatError, parse_graph

router = APIRouter(prefix="/api/v1", tags=["workflows"])
MAX_DRAFT_BYTES = 1024 * 1024
EMPTY_DRAFT: dict[str, Any] = {"graph_format": 1, "nodes": [], "edges": []}


class CreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    draft: dict[str, Any] | None = None


class PatchIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    enabled: bool | None = None


class ActivateIn(BaseModel):
    version_id: uuid.UUID


def _size_guard(request: Request) -> None:
    length = request.headers.get("content-length", "")
    if length.isdigit() and int(length) > MAX_DRAFT_BYTES:
        raise HTTPException(413, detail={"error": "too_large"})


def _revision(if_match: str | None) -> int:
    if if_match is None:
        raise HTTPException(428, detail={"error": "revision_required"})
    try:
        return int(if_match.strip().strip('"'))
    except ValueError:
        raise HTTPException(400, detail={"error": "bad_revision"}) from None


def _check_format(draft: Any) -> None:
    try:
        parse_graph(draft)
    except GraphFormatError as e:
        raise HTTPException(
            422, detail={"error": "invalid", "diagnostics": [d.to_json() for d in e.diagnostics]}
        ) from None


async def _get(db: AsyncSession, ctx: TenantContext, workflow_id: uuid.UUID, *, for_update: bool = False) -> Workflow:
    wf = await service.get_workflow(db, ctx.tenant_id, workflow_id, for_update=for_update)
    if wf is None:
        raise HTTPException(404, detail={"error": "not_found"})
    return wf


async def _summary(db: AsyncSession, wf: Workflow) -> dict[str, object]:
    await db.refresh(wf)
    active = await service.get_version(db, wf.id, wf.active_version_id) if wf.active_version_id else None
    blocked = await service.blocked_by(db, active) if active else []
    return {
        "id": str(wf.id),
        "name": wf.name,
        "enabled": wf.enabled,
        "draft_revision": wf.draft_revision,
        "active_version_id": str(active.id) if active else None,
        "active_version_number": active.number if active else None,
        "executable": (not blocked) if active else None,
        "blocked_by": blocked,
        "created_at": wf.created_at.isoformat(),
        "updated_at": wf.updated_at.isoformat(),
    }


def _version_out(v: WorkflowVersion, active_id: uuid.UUID | None, blocked: list[str]) -> dict[str, object]:
    return {
        "id": str(v.id),
        "number": v.number,
        "published_at": v.published_at.isoformat(),
        "published_by": str(v.published_by) if v.published_by else None,
        "graph_hash": v.graph_hash,
        "version_hash": v.version_hash,
        "cel_profile": v.cel_profile,
        "node_refs": v.node_refs,
        "active": v.id == active_id,
        "executable": not blocked,
        "blocked_by": blocked,
    }


@router.get("/t/{tenant_id}/workflows")
async def list_workflows(
    ctx: TenantContext = Depends(require(P.WORKFLOW_VIEW)), db: AsyncSession = Depends(get_db, scope="function")
) -> list[dict[str, object]]:
    return [await _summary(db, wf) for wf in await service.list_workflows(db, ctx.tenant_id)]


@router.post("/t/{tenant_id}/workflows", status_code=201, dependencies=[Depends(_size_guard)])
async def create(
    body: CreateIn,
    ctx: TenantContext = Depends(require(P.WORKFLOW_EDIT)),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> dict[str, object]:
    draft = body.draft if body.draft is not None else EMPTY_DRAFT
    _check_format(draft)
    try:
        wf = await service.create_workflow(db, ctx, name=body.name, draft=draft)
    except IntegrityError:
        raise HTTPException(409, detail={"error": "name_taken"}) from None
    return {**await _summary(db, wf), "draft": wf.draft}


@router.get("/t/{tenant_id}/workflows/{workflow_id}")
async def get_one(
    workflow_id: uuid.UUID,
    ctx: TenantContext = Depends(require(P.WORKFLOW_VIEW)),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> dict[str, object]:
    wf = await _get(db, ctx, workflow_id)
    return {**await _summary(db, wf), "draft": wf.draft}


@router.put("/t/{tenant_id}/workflows/{workflow_id}/draft", dependencies=[Depends(_size_guard)])
async def put_draft(
    workflow_id: uuid.UUID,
    draft: dict[str, Any] = Body(...),
    if_match: str | None = Header(default=None, alias="If-Match"),
    ctx: TenantContext = Depends(require(P.WORKFLOW_EDIT)),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> dict[str, object]:
    expected = _revision(if_match)
    _check_format(draft)
    wf = await _get(db, ctx, workflow_id)
    try:
        revision = await service.save_draft(db, wf, expected_revision=expected, draft=draft)
    except service.DraftConflictError as e:
        raise HTTPException(409, detail={"error": "draft_conflict", "draft_revision": e.current_revision}) from None
    return {"draft_revision": revision}


@router.patch("/t/{tenant_id}/workflows/{workflow_id}")
async def patch(
    workflow_id: uuid.UUID,
    body: PatchIn,
    ctx: TenantContext = Depends(require(P.WORKFLOW_PUBLISH)),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> dict[str, object]:
    wf = await _get(db, ctx, workflow_id, for_update=True)
    try:
        wf = await service.update_workflow(db, ctx, wf, name=body.name, enabled=body.enabled)
    except IntegrityError:
        raise HTTPException(409, detail={"error": "name_taken"}) from None
    return await _summary(db, wf)


@router.post("/t/{tenant_id}/workflows/{workflow_id}/validate")
async def validate_draft(
    workflow_id: uuid.UUID,
    ctx: TenantContext = Depends(require(P.WORKFLOW_EDIT)),
    db: AsyncSession = Depends(get_db, scope="function"),
    settings: Settings = Depends(get_settings_dep),
) -> dict[str, object]:
    wf = await _get(db, ctx, workflow_id)
    checked = await workflow_ops.check_draft(db, ctx.tenant_id, wf.draft, settings)
    return {
        "draft_revision": wf.draft_revision,
        "valid": not any(d.severity == "error" for d in checked.diagnostics),
        "diagnostics": [d.to_json() for d in checked.diagnostics],
    }


@router.post("/t/{tenant_id}/workflows/{workflow_id}/publish", status_code=201)
async def publish(
    workflow_id: uuid.UUID,
    if_match: str | None = Header(default=None, alias="If-Match"),
    ctx: TenantContext = Depends(require(P.WORKFLOW_PUBLISH)),
    db: AsyncSession = Depends(get_db, scope="function"),
    settings: Settings = Depends(get_settings_dep),
) -> dict[str, object]:
    expected = _revision(if_match)
    wf = await _get(db, ctx, workflow_id, for_update=True)
    try:
        out = await workflow_ops.publish(db, ctx, wf, expected_revision=expected, settings=settings)
    except service.DraftConflictError as e:
        raise HTTPException(409, detail={"error": "draft_conflict", "draft_revision": e.current_revision}) from None
    if out.version is None:
        diagnostics = [d.to_json() for d in [*out.errors, *out.warnings]]
        raise HTTPException(422, detail={"error": "invalid", "diagnostics": diagnostics})
    return {
        "version_id": str(out.version.id),
        "number": out.version.number,
        "warnings": [d.to_json() for d in out.warnings],
    }


@router.get("/t/{tenant_id}/workflows/{workflow_id}/versions")
async def versions(
    workflow_id: uuid.UUID,
    ctx: TenantContext = Depends(require(P.WORKFLOW_VIEW)),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> list[dict[str, object]]:
    wf = await _get(db, ctx, workflow_id)
    return [
        _version_out(v, wf.active_version_id, await service.blocked_by(db, v))
        for v in await service.list_versions(db, wf.id)
    ]


@router.post("/t/{tenant_id}/workflows/{workflow_id}/activate")
async def activate(
    workflow_id: uuid.UUID,
    body: ActivateIn,
    ctx: TenantContext = Depends(require(P.WORKFLOW_PUBLISH)),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> dict[str, object]:
    wf = await _get(db, ctx, workflow_id, for_update=True)
    version = await service.get_version(db, wf.id, body.version_id)
    if version is None:
        raise HTTPException(404, detail={"error": "not_found"})
    try:
        warnings = await workflow_ops.activate(db, ctx, wf, version)
    except workflow_ops.NotActivatableError as e:
        diagnostics = [d.to_json() for d in e.errors]
        raise HTTPException(422, detail={"error": "not_activatable", "diagnostics": diagnostics}) from None
    return {"active_version_id": str(version.id), "number": version.number, "warnings": [w.to_json() for w in warnings]}
```

In `backend/src/dewpoint/apps/api/main.py`, change the routes import to:

```python
from dewpoint.apps.api.routes import (
    admin_users,
    audit,
    auth,
    connections,
    health,
    members,
    mfa,
    node_types,
    passkeys,
    tenants,
    workflows,
)
```

Then append `node_types.router,` and `workflows.router,` to the router tuple, after `connections.router,`.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/apps/api/test_workflows.py -q`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
uv run ruff format . && uv run ruff check . && uv run mypy src && uv run lint-imports && uv run pytest tests/apps -q && \
git add src/dewpoint/apps/api tests/apps/api/test_workflows.py && \
git commit -m "feat(api): workflow drafts, validation, publish, versions, activation and the node-type catalog

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 11: Operator runbook and full verification

**Files:**
- Create: `docs/operations/plugin-lifecycle.md`
- Modify: `README.md` (one link under the operations docs)

**Interfaces:**
- Consumes: the CLI (Task 8) and the API (Task 10).
- Produces: a runbook covering registration, deprecation, retirement (normal and forced) and code removal.

- [ ] **Step 1: Write the runbook**

`docs/operations/plugin-lifecycle.md`:

````markdown
# Node types and CEL profiles: registration and lifecycle

Spec: `docs/superpowers/specs/2026-09-25-engine-core-design.md` §4.5.

## Register on every deploy

Run `plugins sync` with the `dewpoint_admin` database credentials, before the new API or worker build serves traffic:

```bash
DEWPOINT_DATABASE_URL=postgresql+asyncpg://dewpoint_admin_login:...@postgres/dewpoint dewpoint plugins sync
```

It registers every node type version the build contains, and this build's CEL profile. It refuses to proceed (exit 2) when:

- **a registered version's contract changed.** Anything other than its title, description or schema annotations (`title`, `description`, `examples`, `x-widget`, `x-group`) differs from what was registered: schemas, ports, kind, side effect, credentials, capabilities, retry policy or timeout. Ship the change as a new version (`type@N+1`) with a config migration. Display-only changes are stored in place.
- **the build lacks a node type that isn't retired.** Published versions may still need it. Retire it first (below).

## Deprecate, migrate, retire

1. `dewpoint lifecycle deprecate --node-type mist.object.update@1`
   - New versions can no longer use it; the editor offers the migration.
   - Everything already active keeps running.
2. Tenants republish their workflows on the newer version.
3. `dewpoint lifecycle retire --node-type mist.object.update@1`
   - **Succeeds (exit 0)** when no enabled workflow's active version uses it, directly or through a pinned sub-flow.
   - **Refuses (exit 4)** otherwise, and lists the workflows that still use it.
4. **Forced retirement.** Only when you accept that those workflows stop being startable.
   - `... retire --node-type X --force` prints the preview and changes nothing (exit 3).
   - `... retire --node-type X --force --confirm` applies it.
   - Each affected tenant gets an audit entry, and the workflows show `executable: false` with `blocked_by`.
5. After retirement, a later build may drop the code.
   - Runs already in progress are unaffected: they stay on the worker build they started on, which still has the code, until Temporal reports that build drained. (The engine plan 2a-3 covers this.)

CEL profiles follow the same commands with `--cel-profile <profile>`. A profile's evaluator must keep running until no
run that is still in progress uses the profile.

## Why the locks matter

Publishing, activation and (from sub-project 2b) run admission take a shared lock on every node type and CEL profile
their version uses, then re-check its state. Retirement takes the exclusive lock first. Either retirement sees the new
reference, or the new reference sees the retirement; a request is never admitted against code that is being removed.
````

In `README.md`, add a line next to the existing link to `docs/operations/key-rotation.md`:

```markdown
- [Node types and CEL profiles: registration and lifecycle](docs/operations/plugin-lifecycle.md)
```

- [ ] **Step 2: Run the whole suite and every CI check**

Run (from `backend/`): `uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run lint-imports && uv run pytest -q && uv run pip-licenses --fail-on="GPL;AGPL;LGPL;SSPL;BUSL" --partial-match`
Expected: exit 0. The 101 foundations tests still pass, alongside the new ones.

- [ ] **Step 3: Commit**

```bash
cd .. && git add docs/operations/plugin-lifecycle.md README.md && \
git commit -m "docs(operations): node type and CEL profile lifecycle runbook

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Spec coverage (2a-1 scope)

| Spec | Requirement | Task |
|---|---|---|
| §2 | Package boundaries; engine pure; testkit under `tests/`; import-linter contracts | 1, 2 |
| §3 | SDK: Node contract, StepContext, errors, `x-sensitive`, semver'd SDK | 1 |
| §4.1 | `workflows`, insert-only `workflow_versions` with classification slot (`expressions`) and closure, registry + lifecycle tables | 7 |
| §4.2 | Graph format 1, ports, acyclic, loop regions (properly nested, crossing rejected, depth ≤ 3) | 4 |
| §4.2 | Per-run iteration cap | Declared here (`item_cap` and the region rules); enforcing the logical-run counter and grants is 2a-3 |
| §4.3 | Value model, scope roots, path availability, conditional refs need defaults, variable writers | 5, 6 |
| §4.4 | API: create, draft CAS (`If-Match`), validate, publish, versions, activate (rollback); audited with `graph_hash` + `version_hash` | 4, 9, 10 |
| §4.1 | A registered node type version's contract (everything except display metadata) never changes; only resolvable local `$ref`s in manifests and settings | 3, 6, 8 |
| §4.5 | Closure stored at publish; activatable / admissible / dispatchable; startable references; forced preview; lifecycle locking (both orders); READ COMMITTED asserted | 7, 8, 9 |
| §4.5 | Queued-request cancellation; admission and dispatch locking | 2b (`run_requests` doesn't exist yet); `RetirePreview` marks where they go |
| §5.2 | 16,384-character limit on expressions | 5 |
| §5 (rest) | CEL | 2a-2 (this plan emits `cel.unavailable`) |
| §6–§9 | Interpreter, versioning, projection, `start_run` | 2a-3 |
| §10 | Unit, property-based (liveness soundness), API and RLS tests for this scope | 4–10 |
