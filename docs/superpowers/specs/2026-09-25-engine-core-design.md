# Dewpoint — Engine Core Design (sub-project 2a)

- **Status:** Accepted as the basis for implementation, revision 5.3 (2026-09-26).
  - Revision 2 addressed join scopes, the local-CEL switch, evaluator isolation, profile routing and retirement.
  - Revision 3 addresses the version lifecycle (activation, queued requests, closure), nested loops, evaluator
    aggregate memory, and Temporal membership.
  - Revision 4 addresses lifecycle locking at admission, continue-as-new at a quiescent checkpoint only, the
    logical-run iteration counter, and the scope of the two-build test.
  - Revision 5 replaces fixed child allowances with on-demand grants (an exact cap) and makes the drain-headroom test a measurement.
  - Revision 5.1 folds in the refinements from planning 2a-1:
    - advisory-lock implementation of the lifecycle locks;
    - liveness conditions for path availability;
    - `loops.<key>` refs and template defaults;
    - workflow-level data in `graph.settings`.
  - Revision 5.2 adds the contract hash (everything except display metadata), local-only schema references, and the
    two hashes per version (`graph_hash`, `version_hash`). It also states the lifecycle-lock rule directly as advisory locks.
  - Revision 5.3 folds in plan 2a-2 (CEL) and its review:
    - the typed-path proof and its conditions;
    - `item`/`index` in place of the reserved `loop`;
    - the step-presence contract, and `has()` guards for schema-declared optional fields;
    - an exact output contract: every serialized field required, dumps by alias, no model serializers;
    - the work bound and the measured iteration limit, map caps and root projection;
    - batched evaluator requests;
    - the new diagnostic and outcome codes;
    - the evaluator's Kubernetes transport, deferred to the Helm chart.
- **Parent spec:** `2026-09-24-dewpoint-architecture-design.md` (§3 boundaries, §6 execution engine, §7 SDK).
  This spec **narrows parent §6.4** (where CEL runs) and resolves the CEL item in parent §15.
- **Evidence:** CEL spike, branch `spike/cel-evaluation`, commits `d6a8162` and `13a62e1`. See
  `spikes/cel/FINDINGS.md` and its addendum. The spike branch stays **unmerged**. Its suites are ported, not merged (§5.9).
- **Scope:** everything needed to author, validate, version and deterministically execute a workflow graph on
  Temporal, with the flow-control nodes and a test plugin. Admission, triggers, payload encryption and real
  integrations come later (§12).

## 1. Goals and non-goals

**Goals**
- A stable public plugin SDK, so new node types never require engine or UI changes.
- Immutable, validated workflow versions with typed data references.
- A deterministic `RunGraph` interpreter, replay-safe across processes and deployments.
- CEL for conditions and computed values, under the restrictions approved after the spike (§5).
- A per-step run projection for the UI; Temporal history is never exposed.

**Non-goals (later sub-projects)**
- **2b:**
  - run admission: `run_requests`, outbox, dispatcher, tenant slots;
  - triggers: manual input forms and CSV, schedules, webhook ingress;
  - PayloadCodec, claim check (`step_outputs`), retention.
- **3:** Mist, messaging and ITSM plugins; `ctx.connection()`; `ctx.http`.
- **4:** editor UI.
- **5:** AI nodes.

**Hard rule until 2b ships:** `RunGraph` handles only test and development data. The PayloadCodec and claim check
that keep secrets and large values out of Temporal history arrive in 2b. So does the only production path that
starts runs (the dispatcher).

## 2. Packages and boundaries

This follows the parent's import rules (§3.2). `engine` depends only on `sdk`, `core` depends on neither, and only
`apps` wires them together.

```
backend/src/dewpoint/
  sdk/                 # public, semver'd plugin API; no internal imports
  engine/              # pure: no DB, no network
    graph/             # graph model, (de)serialization, validator
    cel/               # runtime adapter, environment, fn library, classifier, bound estimator, evaluators
    runtime/           # RunGraph workflow code, scopes/edge states, snapshots, activity interfaces
    registry/          # manifest generation + validation (no storage)
  core/
    workflows/         # drafts (CAS), publish storage, immutable versions
    runs/              # runs, run_steps projection storage
    plugins/           # plugin_manifests / node_type_versions / cel_profiles storage, lifecycle, references
  plugins/flow/        # manifests for control nodes; the transform node
  apps/
    api/routes/        # workflows.py (draft/validate/publish), runs.py (read)
    worker/            # Temporal worker: RunGraph + activity implementations (core-backed and plugin)
    cel_evaluator/     # isolated, secretless CEL evaluation service (§5.7)
    cli/               # `plugins sync`, `plugins deprecate|retire`, `dev run`
backend/tests/support/plugins/testkit/   # echo, fail-n-times, slow, sensitive-output, ambiguous-send
```

- `engine.runtime` names its activities through typed interfaces: dataclass inputs and outputs, and string activity
  names. `apps/worker` supplies the implementations, and those that touch the DB delegate to `core`.
- Workflow code imports nothing that touches the DB, the network, the clock or randomness. An import-linter
  contract enforces this for `engine.runtime`, and it also runs under the Temporal sandbox.
- **`testkit` lives under `tests/`,** so it is never packaged. The production worker registers only packaged plugins.
- Publishing a version: the API route loads the draft (`core`), validates it (`engine`, using manifests from
  `core`) and inserts the version (`core`), all in one transaction.

## 3. Plugin SDK (`dewpoint.sdk`)

```python
class Node(Protocol):
    type: ClassVar[str]                  # "flow.transform", later "mist.object.update"
    version: ClassVar[int]               # activity name: f"{type}.v{version}"
    Config: ClassVar[type[BaseModel]]    # → JSON Schema (+ x-widget, x-group, x-sensitive)
    Output: ClassVar[type[BaseModel]]    # → output schema: pills, typed refs, CEL environment
    credentials: ClassVar[tuple[str, ...]] = ()
    capabilities: ClassVar[frozenset[str]] = frozenset()
    side_effect: ClassVar[SideEffect]    # NONE | IDEMPOTENT | KEYED | RECONCILABLE | AMBIGUOUS
    retry: ClassVar[RetryDefaults]       # attempts, backoff, non-retryable error types
    timeout: ClassVar[timedelta]

    async def run(self, ctx: StepContext, config: Config) -> Output: ...
    async def simulate(self, ctx: StepContext, config: Config) -> Output: ...            # fixture-based
    async def reconcile(self, ctx: StepContext, config: Config) -> Output | None: ...    # RECONCILABLE only
```

**`StepContext` (2a):**
- `tenant_id`, `run_id`, `step_id`, `iteration_key`, `attempt`;
- `idempotency_key()`, derived from `(run_id, step_id, iteration_key)`;
- a redacting logger, `heartbeat()`, `cancelled`.
- `ctx.connection()`, `ctx.http` and `options()` arrive in sub-project 3.

**Errors:**
- `RetryableError`, `FatalError`.
- `OutcomeUnknownError`: the request may have been sent. It is never retried automatically, and the step records `outcome_unknown`.

**Other rules:**
- The activity wrapper validates `Config` before `run()` and `Output` after it. Output that doesn't match its schema is a `FatalError` (`output_schema_violation`).
- **The output contract.** The output schema is `Output`'s serialization schema, closed, by alias:
  - it lists as required every field serialization emits, including fields with defaults and computed fields; only
    `TypedDict` keys that aren't required, and fields with `exclude_if`, may be absent;
  - outputs become JSON only through `dewpoint.sdk.dump_output`: `model_dump(mode="json", by_alias=True)`, with no
    `exclude_*` option;
  - a `@model_serializer` on the output, or on any model, dataclass or `TypedDict` inside it, is refused at
    registration: its JSON can drop or rename promised fields.
  - a field serializer must declare its return type, which becomes the field's schema. One without (an unannotated
    `@field_serializer`, a `PlainSerializer` or `WrapSerializer` without `return_type`) is refused: the schema would
    keep the field's own type whatever it emits. Pydantic's serializers for its own types are trusted.
- An output field marked `x-sensitive: true` never reaches `run_steps`, previews or samples.
- The SDK has its own semver. First-party plugins pin a major version.

## 4. Workflows, versions and the graph model

### 4.1 Tables

Tenant-scoped tables use FORCE RLS with the foundations policy pattern.
- **`workflows`:** id, tenant_id, name, `enabled`, `active_version_id`, `draft` (JSONB), `draft_revision` (int,
  compare-and-swap), timestamps.
  - Workflow-level data lives in the draft's `graph.settings`, so the draft compare-and-swap covers it too:
    - `input_schema`;
    - `vars_schema`, where every variable declares a `default`;
    - `outputs`: values evaluated when the run succeeds, which define the version's `output_schema`;
    - `failure_handler`: a workflow id.
  - **Tenant-authored schemas** (`input_schema`, `vars_schema`) may use only `$ref`s of the form `#/$defs/<name>` that
    resolve.
    - `$id`, anchors and dynamic references are rejected.
    - So is any cycle that recurses without descending into the data.
    - These are publish diagnostics, so validation never raises on a schema. The same rule applies to plugin manifest schemas.
    - Only schema positions are inspected. A `default`, `const`, `enum` or `examples` value that contains `$ref` or `$id` is data, not a reference.
- **`workflow_versions`:** id, tenant_id, workflow_id, number, graph, `node_refs` (`type@version`), `engine_abi`,
  `cel_profile`, `connection_ids`, `subflow_version_ids`, `input_schema`, `vars_schema`, `graph_hash`,
  `version_hash`, `published_by`, `published_at`.
  - **`graph_hash`** identifies the authored graph only.
  - **`version_hash`** identifies the executable version: the graph hash plus the resolved sub-flow and failure-handler
    pins, `cel_profile` and `engine_abi`. Pinned versions are immutable, so the pins determine the whole closure.
  - Audit and integrity checks use `version_hash`. Republishing an unchanged graph after a sub-flow's active version
    changed gives the same `graph_hash` but a new `version_hash`.
  - It also stores the **classification of every expression** (§5.5) and its static bounds, so the runtime never re-derives them.
  - It stores its **pinned closure** (§4.5) too: `closure_version_ids`, `closure_node_refs` and `closure_cel_profiles`.
  - Rows are insert-only: a trigger rejects UPDATE and DELETE.
- **`plugin_manifests`, `node_type_versions`:** global. They hold the manifest JSON, a **contract hash** and a
  lifecycle state: `active`, `deprecated` or `retired` (§4.5).
  - The contract is every manifest field except display metadata: schemas, ports, kind, side effect, credentials,
    capabilities, retry policy, timeout and engine markers.
  - Display metadata is the manifest's `title` and `description`, plus the schema annotations `title`, `description`,
    `examples`, `x-widget` and `x-group`.
  - Annotations are ignored only on schema objects, reached through schema-valued keywords. Data counts in full,
    verbatim: `default`, `const`, `enum`, `required`, `dependentRequired` and vendor keys.
  - A registered `type@version` may change only its display metadata. Registration refuses any contract change; ship it as a new version.
- **`cel_profiles`:** global, with the same lifecycle states (§4.5, §5.1).

### 4.2 Graph JSON (`graph_format: 1`)

- **`nodes[]`:**
  - `id` (UUID) and `key` (a slug, unique per workflow; used in refs);
  - `type@version`, `config`, `position`;
  - `options`: timeout, retries, `on_error`.
- **`edges[]`:** `{from: {node, port}, to: {node}}`.
  - Ports come from the manifest (static) or from config, for example switch cases.
  - The graph must be acyclic. Repetition is expressed only with `loop`.
- **Loop regions (parent §6.2: `body` and `done` ports):**
  - A loop's **body region** is the set of nodes reachable from its `body` port.
  - The region may not have edges that leave it. An iteration ends when every node of the region has settled in
    that iteration's scope (§6).
  - `done` continues after all iterations.
  - `on_item_error` sets what an unhandled failure inside an iteration does: `stop` (the default, which fails the
    loop node and then applies its own `on_error`) or `continue`, which records the failure in `output.failures`
    (parent §6.8).
  - **Regions nest properly or not at all.** Any two regions are either disjoint, or one contains the other
    entirely, including the inner loop node. The validator rejects:
    - **crossing regions**, for example a node reachable from the bodies of two loops that aren't nested;
    - edges into a region from outside it, other than from that region's own `body` port;
    - refs from outside a region to steps inside it. A region's results leave only through `collect`.
  - **Nesting depth ≤ 3.** Scopes nest the same way, for example `loop2:7/loop5:3`.
  - **Per-run iteration cap.** All loop iterations and filter items across the whole *logical* run share one cap,
    initially 100,000, so nested item caps don't multiply. That includes child batches, sub-flows and every
    continue-as-new. Past the cap, the loop fails with `iteration_cap_exceeded`. §6 explains how the count is kept.
  - The loop's `collect` value is evaluated at the end of each iteration and becomes `steps.<loop>.output.items[i]`.

### 4.3 Values, scope and availability

- **Every config field is one of:**
  - `literal`;
  - `ref {path, default?}`;
  - `template {parts: [text | ref {path, default?}]}`;
  - `cel {expr}`.
- **Scope:**
  - `trigger.*`
  - `steps.<key>.output.*`
  - `steps.<key>.error`: `{code, message, attempt}`; only for steps with `on_error` ≠ `fail`.
  - `vars.*`: typed by `vars_schema`.
  - `item`, `index`: the innermost loop's item and position; inside a `filter` predicate, the filter's item. (CEL
    reserves `loop` as a word, so references and CEL use the same names.)
  - `loops.<loop_key>.item`, `loops.<loop_key>.index`: any enclosing loop, from inside nested loops.
  - `run.id`, `run.started_at`, `run.now`: workflow time from `workflow.now()`, never the host clock.
- **Path availability** (parent §6.4) uses *liveness conditions*, computed per region after regions are resolved.
  - A liveness condition is a DNF formula over branch decisions: which port each `if`, `switch` or error-routing step took.
  - A ref is *always available* when the producer is upstream of the consumer and the consumer's condition implies
    that the producer succeeded, in the same or an enclosing scope. Otherwise it is *conditional*.
  - This reduces to dominance for exclusive branches, and it also accepts refs after a parallel fan-out/join, which
    dominators would wrongly reject. A property test checks it against simulated executions.
  - Conditional refs, and schema-optional fields, need a `default` (ref, template) or a `has()` guard (CEL). A
    `default` replaces a missing *or* null value.
  - In CEL:
    - a step that may not have run is guarded with `has(steps.<key>.output)` (or `has(steps.<key>.error)`);
    - a field the schema declares but doesn't require, and every such ancestor, is guarded with `has()` on that field,
      e.g. `has(trigger.a) && has(trigger.a.b) && trigger.a.b.c == 1`;
    - data the schema doesn't declare (open objects, schemaless bodies) needs no guard. If it's missing at run time,
      the evaluation fails with `evaluation_error` and the step's error policy applies. (§5.10 `cel.conditional_ref`)
- **Names.** `in`, `true`, `false` and `null` can't be step keys or variable names: CEL can't select them as fields.
- **Variables:**
  - `set_variables` writes only declared `vars`.
  - The validator rejects two writers of the same variable on branches that can run concurrently.
  - Inside a loop body, outer `vars` are read-only. Per-iteration results leave through `collect`, so concurrent iterations never race.

### 4.4 API

Tenant routes with the foundations session, CSRF and permission model (`workflow.edit`, `workflow.publish`):
- `POST /workflows`
- `PUT /workflows/{id}/draft` (`If-Match: <draft_revision>`, 409 on conflict)
- `POST /workflows/{id}/validate` returns diagnostics: `{node, field, code, message, fix?}`.
- `POST /workflows/{id}/publish` validates, then inserts; it returns 422 with diagnostics on failure.
- `GET /workflows/{id}/versions`

Publish is audited: version number, `graph_hash`, `version_hash`, classification summary.

- Publishing sets `active_version_id` to the new version.
- `POST /workflows/{id}/activate {version_id}` rolls back to an earlier version. It requires `workflow.publish`
  and is audited. It is refused only if the version isn't **activatable** (§4.5). Being superseded is not a reason
  to refuse: rolling back exists precisely to reactivate a superseded version.

### 4.5 Version lifecycle and retirement

Rows in `workflow_versions` are never deleted. Whether a version exists is therefore separate from three other questions:
- can it be activated?
- can a new request be admitted for it?
- can an admitted request start?

**Closure.**
- A version's closure is the version itself plus every version it pins, transitively: its sub-flows and its failure handler, at most 5 levels deep.
- Pins are immutable, so the closure is computed once at publish and stored with the version (§4.1).
- **Every rule below applies to the whole closure.** A parent is never more runnable than the least runnable version it pins.

**Executable.** A version is executable if nothing in its closure is `retired`: no node type and no CEL profile.
`deprecated` entries are still executable.

| Question | Rule | Checked |
|---|---|---|
| **Activatable:** may `activate` select it? | It belongs to the workflow and is executable. `deprecated` entries produce a warning, not a refusal. (Publishing a *new* version is stricter: see `deprecated` below.) | `activate` |
| **Admissible:** may a new run request be admitted? | The workflow is enabled, and the request targets the workflow's **active** version, which is executable | When the request is frozen (2b dispatcher, 2a `start_run`) |
| **Dispatchable:** may an admitted request start? | Its **frozen** version is still executable. Whether that version is still active doesn't matter | At dispatch, in the transaction that marks the request `starting` |

- **Queued requests keep their version.** Publishing a newer version does not affect requests already frozen on the old one: they are dispatched on it.
- **Superseded versions.** A version that isn't active can't take new admissions, but it can still be activated,
  and it still executes the requests already frozen on it.
- **Re-runs** (parent §10.5) are new admissions, so they use the active version. The UI says so when that differs from the original run's version.
- **Sub-flow versions** only ever run as children, inside a run their parent already admitted.
- **Disabling a workflow** stops new admissions only. Its queued requests still dispatch unless a user cancels them, which is explicit and audited.

**References and what they block:**

| Reference | Held by | What it blocks |
|---|---|---|
| Active | the closure of each enabled workflow's active version | normal retirement |
| Queued | the closure of each `run_requests` row that hasn't started | normal retirement |
| Running | the closure of each non-terminal run | **Node types:** only their own build's retirement, since the pinned build already contains the code. **CEL profiles:** shutting down the profile's evaluator, which lives outside the build |

Retirement never breaks a run that has started. Its build keeps the code, and its profile's evaluator keeps running
until no non-terminal run uses that profile.

**Lifecycle of a `type@version` or a `cel_profile`:**
1. **`deprecated`:**
   - Publish refuses versions whose closure uses it.
   - For node types, the editor offers the manifest's config migration (vN → vN+1).
   - Activation shows a warning.
   - Everything already active, queued or running continues.
2. **`retired`:**
   - **Normal path.** Allowed only when there are no active and no queued references (see *Lifecycle locking* below).
   - **Forced path** (platform admin). A preview comes first. Per tenant, it lists:
     - the affected versions;
     - every **entry workflow** whose active closure reaches them, including parents that reach them only through a pinned sub-flow;
     - every queued request that would be cancelled.

     On confirmation, in one transaction:
     - the entry becomes `retired`;
     - affected workflows show the reason;
     - every affected queued request is **cancelled explicitly** (status `cancelled`, reason `node_type_retired` or
       `cel_profile_retired`), audited and shown in the run list.

     No queued request silently turns into a failure later.
   - Both paths are audited.
3. **Removed:**
   - A node type: once it is `retired`, a new build may stop registering it. Older builds drain normally.
   - A CEL profile: once it is `retired` **and** no non-terminal run uses it, its evaluator may be shut down.

**Lifecycle locking.** The rule: every transaction that creates or uses a reference takes a **shared lifecycle lock** on
each entry of the version's closure, in sorted key order. It then re-reads those entries' states.
- A lifecycle lock is a transaction-scoped Postgres advisory lock keyed `dewpoint:lifecycle:<node|cel>:<key>`.
- Advisory locks, not row locks, because row locks would require UPDATE privilege on the registry tables, which the API role must not have.

The rule applies to:
- **publish** (the new version's closure);
- **activate**;
- **enabling a workflow**, which makes its active version's closure an active reference again;
- **admission:** freezing a new `run_requests` row, or `start_run` in 2a;
- **dispatch.**

The executable check and the insert or update happen in that same transaction.

**Retirement** takes its entry's **exclusive lifecycle lock** as its first statement. Only then does it count references
and build the cancellation set, in later statements of the same transaction, at READ COMMITTED (the Postgres default).
Shared and exclusive locks conflict, so the two sides serialize:
- **Admission commits first.** Retirement's lock waits for that commit, so its later statements see the new
  request. Normal retirement is then blocked, or forced retirement cancels the request.
- **Retirement locks first.** Admission's lock waits, then re-reads `retired` and refuses the request.
  Nothing is admitted.

Under REPEATABLE READ, the snapshot would predate the wait, so these transactions must not use it. A test asserts
the isolation level.

**Defensive check at dispatch.** If dispatch still finds a frozen version that isn't executable (the forced path
should make this impossible), it cancels the request with the same explicit, audited reason. It never fails the
request as superseded. Because admission locks as above, this check should never fire. A metric counts it, and
the race tests assert that it stays at zero. 2a implements these rules in `start_run`, and 2b's dispatcher reuses them.

## 5. CEL subsystem

### 5.1 Decision status

- The runtime is **`cel-expr-python==0.1.3` (Google cel-cpp), chosen provisionally.**
- It sits behind a small `CelRuntime` adapter with four operations: compile with a typed environment, get the
  checked AST, evaluate, and classify errors. The rest of the engine never imports the library directly.
- **`cel_profile`** names the three things that decide an expression's meaning and class. For example,
  `cel-cpp-0.1.3/fn-1/cls-1` combines:
  - the runtime pin;
  - the Dewpoint function library version;
  - the classifier and estimator rules version.

  Each version stores its profile, and changing any of the three creates a new profile. A new profile ships only
  after the §5.9 gates pass, and it follows the lifecycle in §4.5.
- **Publish** always uses the API build's single current profile. Deploy order: first the evaluators and workers
  that serve a profile, then the API that publishes with it.
- **Where evaluation runs:**
  - locally, only when the version's profile equals the worker build's `LOCAL_CEL_PROFILE` (§5.9);
  - otherwise on that profile's evaluator (§5.7).
  - It never falls back to a different profile.
- **Reconsider the choice if:**
  - the 0.x package is abandoned, or can't be upgraded for a security fix;
  - a gate fails on a pin we can't avoid;
  - the typed-path encoding in §5.3 can't be made to work.
- The fallback candidate is `cel-python`, restricted to **activity-only** evaluation, because it is slow and yields to the event loop.

### 5.2 Fixed limits

- **Iterations:** 10,000 per evaluation, fixed by the runtime and shared by every comprehension in the expression.
  - It is a **hard per-evaluation constraint.** Dewpoint exposes no setting to raise it.
  - **It is not a complete cost or memory limit.** Work and memory are bounded separately (§5.5, §5.6, §5.7).
  - Large collections go through engine `loop` and `filter` nodes. They evaluate once per item, each time with a fresh budget. We never raise the CEL budget.
- **Parse:** recursion limit 32. Expressions over 16,384 code points are rejected.
- **Output:** 256 KiB of canonical JSON (§5.8).

### 5.3 Typed environment and binding

- The validator compiles each expression in an environment built from the schemas in scope at that node: the
  trigger input schema, upstream `Output` schemas, `vars_schema`, `loop.*` and `run.*`.
- **Typed paths.** CEL's checker only proves a range is a list if it sees the type.
  - Roots (`trigger`, `steps`, `vars`, `loop`, `run`) are declared as `map<string, dyn>`, so `has()` guards work.
  - Every schema path that holds an array is also declared as a qualified identifier with its element type, for
    example `steps.get_devices.output.devices : list<map<string, dyn>>`. CEL resolves the longest declared
    qualified name, so that path type-checks as a list.
  - Only always-available paths get a typed declaration. Conditional paths stay reachable only through the `dyn` roots behind `has()`.
  - Fields with no schema (for example raw webhook bodies) remain `dyn`.
- **Proven for cel-cpp 0.1.3** (plan 2a-2; `tests/engine/cel/test_typed_paths.py` pins every behaviour below):
  - the checker resolves the longest declared qualified name, so the range types as a list; undeclared paths,
    `x["key"]` index syntax and lists nested inside elements stay `dyn` (use `asList()`);
  - comprehension variables shadow roots in the checker and the runtime alike;
  - binding both the root and the qualified identifier works; the qualified binding is what the expression reads;
  - the runtime converts every bound value against its declared type, deeply;
  - `has()` works on roots and on prefixes of typed paths. On a declared typed path itself, the checker collapses
    `has(p)` into `p`: publish rejects that form (`cel.has_on_typed_path`), and a `has()` test alone never declares
    the path;
  - `loop` is a reserved identifier, and `in`, `true`, `false`, `null` can't be selected as fields (§4.3 names);
  - the runtime's own AST serialization isn't deterministic (protobuf maps); nothing stores or hashes it.
- **Declarations are per expression.** Roots always; `item` (`dyn`, or a typed list) and `index` (`int`) where they
  exist; and, for each select chain in the expression, every prefix that is an always-available, non-null array.
  Element types: objects `map<string, dyn>`, strings `string`, booleans `bool`, arrays `list<dyn>`, anything else
  `dyn` (numbers stay `dyn`: the runtime would convert an int in a `double` slot, or refuse `3.0` in an `int` one).
- **Projection.** A root is bound as the part the expression's chains can observe: maps keep only keys on a chain,
  a chain's end keeps its whole value, a `has()` test keeps only the key. Measurement (§5.6) and requests (§5.7) see
  that projection, never the whole workflow state.
- **Step presence.** `steps` holds every step visible from the scope: `{"output": …}` once it succeeded,
  `{"error": …}` once it failed with a handled error, `{}` before either. So `has(steps.x.output)` is the guard.
- **Binding checks.** Before evaluation, every bound value is checked against its declared type, deeply, and must be
  plain JSON: text map keys, finite numbers, integers within int64. A mismatch fails the evaluation with
  `type_mismatch` before any CEL runs. This makes the classifier's type facts hold at runtime, even if a producer
  violated its schema.
- **Time.** `datetime` isn't accepted as an input variable (spike). `run.now` and `run.started_at` are bound as
  RFC 3339 UTC strings, used as `timestamp(run.now)`. The activity evaluator receives them from the workflow; it never reads its own clock.

### 5.4 Function library `fn-1`

| Function | Purpose | Cost | Output bound |
|---|---|---|---|
| `sortedKeys(map<string, dyn>) → list<string>` | the only way to iterate a map (code-point order) | O(n log n), n ≤ map size | ≤ input |
| `asList(list<dyn>) → list<dyn>` | proves a `dyn` range is a list: the runtime dispatches only lists to it, anything else is `type_mismatch` (a map is never accepted) | O(n) conversion | = input |
| `ipInCidr(string, string) → bool`, `cidrContains(string, string) → bool` | IP/CIDR tests (IPv4/IPv6) | O(1) | bool |
| `macNormalize(string) → string`, `macOui(string) → string` | MAC formats: 12 lowercase hex digits (Mist's form) from `aa:bb:…`, `aa-bb-…`, `aabb.ccdd.eeff` or bare hex; the first 6 | O(1) | 12 / 6 code points |

- Also available: the CEL standard library, **minus** extension libraries and `cel.bind`, which aren't enabled.
- IP, CIDR and MAC arguments longer than 64 code points are errors, not work. A function's error is a CEL error
  value, so `||` and `&&` can absorb it.
- **Every function declares** that it is deterministic (no time, randomness, I/O or locale), its cost class, its
  output bound, and whether it takes a map.
- **A function that takes a map must not expose the map's iteration order.** `sortedKeys` does this by sorting.
- Before a function is relied on, it needs unit tests, cross-process determinism tests and hostile-input tests (§5.9).
- `sortedKeys` and the classifier passed these tests in the spike; they are re-run as gates in the product. `asList`, `ipInCidr` and the MAC functions are new and must pass the same gates.

### 5.5 Classification at publish time

The classifier walks the **checked** AST (`CheckedExpr` inside `google.protobuf.Any`, decoded with the vendored
cel-spec protos, Apache-2.0, pinned commit). It assigns exactly one class.

**Reject.** Publish fails, and the error names the rule and the fix.
- Parse or type errors, and text over 16,384 code points.
- **Any comprehension whose range is not proven a list**: a map, `dyn`, or anything else.
  - This covers **every** macro (`map`, `filter`, `all`, `exists`, `exists_one`) at any depth.
  - The spike showed the boolean macros *return* the same value in any order. But which element's error surfaces,
    and how much of the budget is spent before a short-circuit, both depend on order, and both can reach workflow
    state (`steps.<key>.error`, `iteration_budget_exceeded`).
  - This leaves one route from a map to an iteration: `sortedKeys(m).…` (or `asList` for `dyn` lists).
  - Map lookups, `in`, `size()` and map equality don't expose order and remain allowed. The semantics gate covers them across processes.
- Functions outside the standard library and `fn-1`.

**Local** (evaluated inside `RunGraph`). Every condition must hold. Together they are the **proven restricted subset**:
1. **Allow-list, not deny-list.** Every AST node kind, operator and function is on the local allow-list, and each
   entry records its rule for size and work.
   - Excluded: regex `matches` with a non-literal pattern or a pattern over 256 code points; time-zone accessors with
     a named zone (they depend on tzdata; UTC and fixed offsets are allowed); anything added to the standard library
     after the pin.
2. **At most one comprehension level.** The only list growth inside a comprehension body is the macro's own accumulator.
3. **≤ 4,096 code points.**
4. **Bounded intermediate work, proven statically.** The **bound estimator** computes worst-case iterations and the
   largest intermediate value in bytes. It assumes every referenced input is at the runtime caps (§5.6) and uses
   each allow-list entry's rule; for example, concatenation adds its operands' bounds, and a comprehension
   multiplies its body's bound by the range's list-length cap.
   - Local requires ≤ 9,999 iterations (the runtime's budget of 10,000 lets 9,999 pass), so the budget can never
     fire locally, and ≤ 1 MiB for the largest intermediate value.
   - Sizes use a model close to the runtime's memory: 16 bytes per scalar and per container, plus text bytes. A
     value's model size is at most 8 × its canonical JSON size + 8, so the referenced inputs together are at most
     524,296 model bytes. Distinct input references share that mass (`a.x + a.y` is one input's worth); overlapping
     ones count again (`s + s`). Inside a comprehension, a bound may grow with the current element, whose sizes sum to
     the range's (`l.map(e, e.name)` stays near `l`); `m[k]` over `sortedKeys(m)` sums to `m`.
   - **Work.** Iterations alone don't bound CPU: a body can call Python-implemented functions hundreds of times per
     element. The estimator also bounds *work*: one unit per node evaluation, 15 per `fn-1` call, one per 64 bytes a
     regular expression scans. Local requires ≤ 2,000,000 units (about 0.2 s on the gate machine).
   - The bounds are stored with the version.

**Activity.** Valid expressions that are not local run in the isolated `cel.evaluate` activity (§5.7), and the
result is recorded in history. This is the parent's `eval` activity (§6.5).

### 5.6 Runtime routing and in-workflow work

- Before a local evaluation, `RunGraph` measures the values the expression references (identifiers from the checked AST's reference map). Those values are already in workflow state, so measuring is deterministic.
- **Caps (the estimator's assumptions):**
  - each referenced value ≤ 64 KiB of canonical JSON, and ≤ 64 KiB in total;
  - every list ≤ 1,000 elements, every map ≤ 1,000 entries;
  - every string ≤ 16 KiB.
- If any cap is exceeded, the same expression runs in `cel.evaluate` instead. Routing depends only on recorded values, so a replay routes the same way.
- **Workflow-task time.** Since its last await, the scheduler sums the **stored static bounds** of the local
  evaluations it has run: their iterations and intermediate bytes. Before an evaluation that would push the sum past the yield
  threshold, it awaits a 1 ms durable timer, which creates a yield point. It also yields after 200 evaluations,
  whatever their bounds.
  - Initial thresholds: 20,000 iterations, 8 MiB or 4,000,000 work units (§5.5).
  - The decision uses only stored bounds and a count, so it replays identically. The timer events count toward the continue-as-new threshold.
  - **This is a policy to measure, not a proven CPU bound.** A p99 latency says nothing about the worst case.
    Before local evaluation is enabled, the plan must run an adversarial test: expressions that max out the
    estimator's bounds, on inputs at the caps, evaluated back to back up to the threshold. The measured worst-case
    CPU per workflow task must stay within a target of 1 s, against Temporal's 10 s workflow-task timeout. The thresholds are tuned from that measurement.

### 5.7 Isolated evaluation (`cel.evaluate` activity + `cel-evaluator` service)

Resource limits aren't privilege isolation. Evaluation therefore happens in a **dedicated, low-privilege service**,
not inside a worker that holds credentials.

**Division of work:**
- The `cel.evaluate` **activity** runs in a Dewpoint worker. It holds Temporal credentials and, from 2b, resolves
  claim-check handles. It builds one bounded request and forwards it to the evaluator. It evaluates nothing itself.
- The **`cel-evaluator`** is its own process and container, with the entrypoint `apps/cel_evaluator`. It contains
  only the runtime, the function library, the classifier and the IPC server.

**`cel-evaluator` privileges:**
- **No secrets.** No database, Temporal, KEK or tenant-key credentials. Its environment is built from an explicit
  allow-list of its own settings, and a startup check refuses to run if anything else is present.
- **No egress.**
  - In Compose: `network_mode: none`, with a Unix socket on a volume shared only with the CEL activity worker.
  - **Kubernetes: deferred to the Helm chart (§12).** A Unix socket can't cross pods. A sidecar in the worker's pod
    would share the worker's network namespace and egress, so it can't be the answer. Before the chart ships CEL
    evaluation, a network transport must be designed and approved:
    - authenticated: mTLS or equivalent, with a credential that grants only evaluator calls;
    - the evaluator in its own Deployment, with a NetworkPolicy that admits only the CEL activity worker's pods and
      denies all egress;
    - no Kubernetes API access: no service-account token, no injected service variables.

    Until then, Kubernetes deployments can't run activity-class CEL.
- **Minimal process rights.** Its own non-root UID, distinct from the worker's. Read-only root filesystem, all
  capabilities dropped, `no-new-privileges`, and the runtime's default seccomp profile.
- **Tenant data** enters only as the values one evaluation references, and it leaves only as that evaluation's
  result. The evaluator keeps no state between requests.

**Inside the evaluator:**
- **Zygote.** A single-threaded zygote imports the runtime once, then forks one child per evaluation.
- **Child limits.** Each child sets:
  - `RLIMIT_AS` = 256 MiB;
  - `RLIMIT_CPU` = 5 s;
  - `RLIMIT_NOFILE` = 16;
  - `RLIMIT_FSIZE` = 0;
  - `RLIMIT_CORE` = 0.

  It closes every descriptor except its result pipe, evaluates once and exits. The zygote kills it after 5 s of wall-clock time.
- **Linux only.** The evaluator refuses to start if it can't apply these limits.

**IPC limits:**
- **Framing.** Length-prefixed frames of canonical JSON, schema `cel.evaluate.v1`. A request holds the profile, the
  expression, its declarations and 1 to 1,000 binding sets; each set is its own evaluation with its own budget (the
  `filter` batches of §6). The evaluator re-checks the declared types and the order rule before evaluating.
- **Request size ≤ 4 MiB.** The activity checks the size before sending. A larger request is the evaluation outcome `input_too_large`.
- **Responses ≤ 256 KiB** plus the envelope. A malformed or oversized frame closes the connection.
- **Aggregate limits.** The evaluator container has cgroup limits: memory (Compose `mem_limit`; initially 2 GiB),
  CPU, and pids.
  - At startup it reads its own limits (`memory.max`, `cpu.max`) and derives the concurrency *N*:
    - each slot is charged 256 MiB for its child, plus 8.25 MiB of buffers (one in-flight request, one queued request, one response);
    - a fixed 256 MiB reserve covers the zygote and the IPC server;
    - *N* = min(CPU quota, ⌊(memory limit − 256 MiB) / 264.25 MiB⌋). That is 6 at 2 GiB.
  - **It refuses to start** if there is no memory limit or *N* < 1. Configuration may lower *N*, never raise it.
    The pids limit is *N* + 8.
  - **Why this is enough.** `RLIMIT_AS` caps a child's virtual address space, which is always at least its resident
    memory. So *N* children plus the reserve can't exceed the cgroup limit.
  - An OOM kill of the whole container is still treated as an infrastructure failure and retried.
- **Concurrency.** At most *N* children run at once, with a wait queue of *N*. Anything beyond that gets `busy`.
  - The CEL activity worker sets `max_concurrent_activities` = *N*, so `busy` shouldn't happen.
  - If it does, it counts as an infrastructure error.

**Profile routing (fail closed):**
- **One task queue per profile:** `RunGraph` schedules `cel.evaluate` on `dewpoint-cel.<profile>`, using the
  **version's** profile. It never relies on the workflow's build to choose the runtime.
- **Identity check at startup.** The evaluator computes its identity from its installed runtime distribution
  (`importlib.metadata`), its function library version and its classifier version. The activity worker polls a
  profile's queue only if the evaluator's identity equals that profile.
- **Identity check per request.** Every request carries the profile. The evaluator refuses a mismatch with
  `profile_mismatch`, and the step fails with `cel_profile_unavailable`.
- **No evaluator for a profile.** A schedule-to-start timeout (initially 10 minutes) fails the step with
  `cel_profile_unavailable`. Either way, the step follows its error policy. **No other profile ever evaluates the expression.**
- **Keeping evaluators alive.** A profile's evaluator must keep running while any active, queued or running reference uses that profile (§4.5).

**Results:**
- The outcome is a value: `{ok: value}` or `{error: code, message}`.
- `input_too_large`, `memory_limit`, `cpu_limit`, `timeout`, `iteration_budget_exceeded` and `output_too_large`
  are evaluation outcomes, as are `type_mismatch`, `evaluation_error` (any other CEL runtime error),
  `non_json_value` (§5.8) and `evaluation_crashed` (the child died by another signal). They are **recorded and not
  retried**. A child killed by SIGXCPU, or by SIGKILL at the hard CPU limit, is `cpu_limit`.
- Temporal retries (3 attempts, backoff) cover only infrastructure failures: the evaluator is unreachable, the zygote died, or the answer is `busy`.

### 5.8 Output canonicalization

Every CEL result, local or activity, is converted to canonical JSON before it enters workflow state:
- map keys are sorted recursively;
- timestamps become RFC 3339 UTC and durations become `"<seconds>s"`;
- `bytes` values are rejected (`non_json_value`), and so are non-finite doubles.

Map iteration order can't reach workflow state, history or `run_steps` by any path.

### 5.9 Gates and rollout

The spike's suites are **ported** into `backend/tests/engine/cel/` (the spike branch stays unmerged as the record)
and run in a Linux container job. They run on every change to the runtime pin, the vendored protos, the function
library, the classifier or the estimator:
1. **Semantics:** the spike's 77 cases, plus map `in`/`size`/equality and every `fn-1` function.
2. **Hostile input:**
   - The spike's probes: deep nesting, long chains, iteration blow-ups, string growth, allocation bombs.
   - Every local-class probe must end in a value or an error, in-process, with no crash, panic or hang.
   - Every activity-class probe must be contained by the child, and the parent must survive.
3. **Determinism:** 8 processes with different `PYTHONHASHSEED` values produce one result. This includes `sortedKeys` over maps built in different insertion orders.
4. **Temporal replay:** a sandboxed workflow that evaluates the corpus, replayed in 5 fresh processes. It covers `sortedKeys` and canonical outputs.
5. **Classifier:** a table of reject, local and activity expressions, including every reject route in §5.5 and the typed-path encoding in §5.3.
6. **Estimator soundness:** fuzzed local-class expressions (Hypothesis, over the allow-list) evaluated on inputs at the caps.
   - Measured iterations and result sizes never exceed the stored bounds.
   - Peak RSS growth stays under 1.5 × the 1 MiB bound.
7. **Local cost:**
   - p99 and maximum latency per local evaluation at the caps;
   - the adversarial workflow-task test from §5.6.

   The results are recorded per profile and tune the initial thresholds.

**Rollout: local evaluation is a build property, never a runtime setting.**
- Each worker build has a constant, `LOCAL_CEL_PROFILE`: the one profile it evaluates in-process, or none.
  - The constant is part of `engine_abi`, so changing it produces a new build ID.
  - Builds ship with none until gates 1–7 pass for that profile. Plan 2a-2 ports gates 1, 2, 3, 5, 6 and the
    in-process half of 7; gate 4 (Temporal replay) and the workflow-task half of gate 7 need `RunGraph` and run in
    2a-3, which is also where `LOCAL_CEL_PROFILE` can first be set.
- **Routing is a pure function of three things:**
  - the build's `LOCAL_CEL_PROFILE`;
  - the version's profile, classes and bounds, loaded once by a local activity and so recorded;
  - the recorded input sizes.

  No setting, environment variable, feature flag or database read takes part. `engine.runtime` imports no
  configuration, and an import-linter contract enforces this.
- **Enabling local evaluation** therefore changes only runs that start on the new build. An open run keeps its
  build, and with it its command sequence.
- **Architecture.** Worker and evaluator images are built for one CPU architecture per build ID. Publishing
  another architecture requires running the gates on it.

### 5.10 Editor and error messages

- Every CEL field shows its class: **Runs inline** or **Runs as a separate step**. It also shows the reason, for example "more than one nested loop" or "input may exceed 64 KiB at run time".
- Diagnostics use stable codes, and the editor documentation lists every code with its fix:

| Code | Message and fix |
|---|---|
| `cel.map_iteration` | "Iterates over a map, so the order isn't guaranteed. Use `sortedKeys(m).map(k, …)`." |
| `cel.unproven_list` | "The type of this value is unknown, so it can't be iterated. Wrap it: `asList(x)`." |
| `cel.iteration_budget` | "An expression can iterate at most 10,000 times. For large lists, use a Loop or Filter node." |
| `cel.too_long` | "Expressions are limited to 16,384 characters." |
| `cel.unknown_function` | "`f` isn't available. Available functions: …" |
| `cel.conditional_ref` | "`steps.x` may not have run on every path, so `steps.x.output` may be missing. Guard it with `has(steps.x.output)`." Or: "`trigger.a` is optional in its schema, so it may be missing. Guard it with `has(trigger.a)`." |
| `cel.invalid` | "This expression isn't valid: …" (the checker's message, with line and column) |
| `cel.unknown_name` | "`x` isn't defined here. Expressions start with trigger, steps, vars, item, index, loops or run." |
| `cel.bad_path` | "`steps.a.outputs`: after `steps.<key>` comes `output` or `error`." (the reference grammar's message) |
| `cel.has_on_typed_path` | "`p` always exists here, and `has()` on it gives the list, not true. Remove the `has()` test." |
| `cel.type_mismatch` | "This expression gives integer, but this field expects boolean." |
| `cel.non_json_result` | "This expression gives a value JSON can't hold (bytes or a type)." |
| `graph.reserved_key` | "`in` can't be a step key: expressions couldn't refer to it." |
- `cel.iteration_budget` is a warning: nested loops, or a bound over 9,999, may stop at the budget with large inputs.

- Run errors (`steps.<key>.error.code`) use the same documented codes for the runtime outcomes:
  `iteration_budget_exceeded`, `memory_limit`, `cpu_limit`, `timeout`, `type_mismatch`, `input_too_large`,
  `output_too_large`, `cel_profile_unavailable`, `evaluation_error`, `non_json_value`, `evaluation_crashed`.

## 6. `RunGraph` interpreter

**Inputs:**
- `run_id`, `workflow_version_id`, the trigger payload (a handle from 2b);
- `deadline` = `started_at` + `max_run_duration` (default 30 days; parent §6.3).

The version (graph, classifications, bounds) is loaded by one local activity and is immutable for the run.

**Scopes, edge states and joins:**
- **A scope is one execution of a region:** the run's root scope, or one loop iteration (`loop2:7`, or
  `loop2:7/loop5:3` when nested). **Branch decisions are not part of a scope.** A branch only decides which
  outgoing edges are live. Paths that split at an `if` or `switch` therefore meet again in the **same** scope.
- **Edge and node states.** In a scope, each edge of the region is `pending`, `live` or `dead`, and each node is
  `waiting`, `running`, `done`, `failed` or `dead`.
- **Resolution.** When a node settles, every outgoing edge is resolved exactly once:
  - `if`: edges from the taken port are live; all others are dead.
  - `switch`: edges from the first matching case, or from `default`, are live; all others are dead.
  - `on_error: port`: on success the `error` port's edges are dead. On failure the normal edges are dead and the `error` edges are live.
  - `on_error: continue`: the normal edges are live.
  - A **dead** node resolves all of its outgoing edges as dead (dead-path elimination).
- **Readiness.** A node becomes ready once every incoming edge in its scope is resolved.
  - It runs if at least one incoming edge is live, and becomes dead otherwise.
  - Edges resolve once per scope and the graph is acyclic, so each node runs or dies **exactly once per scope**,
    and a join can neither run twice nor wait forever.
- **Example:** `if → A | B → C`. With `true`, A runs and B is dead, so A→C is live and B→C is dead. C runs once,
  in the same scope. Refs from C to A or B are conditional (§4.3).
- **Loops.** The `body` port opens one child scope per item. An iteration has settled when every node of the
  region in its scope is `done`, `failed` (handled by `on_item_error`) or `dead`. When all iterations have settled,
  the loop's `done` edges resolve in the parent scope. Region nodes read outer values from enclosing scopes.
- **`stop` and `fail`** end the run, as succeeded or failed. They cancel the run's in-flight work first.
- **Scheduler.** A single loop owns a ready queue ordered by `(scope, topological index)`. It starts activities and
  child workflows as futures and awaits them. Nothing else in the workflow creates concurrency.
  - **In-flight cap.** At most 100 activities and child workflows are outstanding per workflow execution (an initial limit).
  - This bounds how much history in-flight work can still add, which the continue-as-new headroom depends on.

**Node kinds:**

| Kind | Nodes | Execution |
|---|---|---|
| Control | `if`, `switch` (cases in declared order, first match), `set_variables`, `stop`, `fail` | values via §5 (local or `cel.evaluate`) |
| Time | `delay`, `wait_until` | durable timers. Static waits beyond `max_run_duration` are rejected at publish. Dynamic waits past the deadline end the run with `deadline_exceeded` when the deadline is reached |
| Loop | `loop` (`items`: a list value; `concurrency` 1–10, default 1; item cap default 10,000) | ≤ 100 items run inline; more run as child workflows in batches of 100 within the parent's concurrency |
| Filter | `filter` (`items`, per-item predicate) | ≤ 1,000 items: predicate per item, inline (local class) or batched `cel.evaluate` calls; each item is its own evaluation with its own 10,000 budget. Larger lists are batched through `cel.evaluate` in chunks of 1,000 |
| Transform | `flow.transform` | each output field is a separate value (§4.3) with its own class |
| Sub-flow | `run_workflow` | a child workflow pinned to `subflow_version_id`; depth ≤ 5; cycles rejected at publish; shares the deadline |
| Side effect | plugin nodes | activity `type.vN`; retry and timeout from the manifest, overridable per node |

**Errors (parent §6.6):**
- `on_error` is one of:
  - `fail` (default);
  - `continue`: the output is `null` and `steps.<key>.error` is set;
  - `port`: follow the `error` port.
- `OutcomeUnknownError` is never retried.
- An optional workflow failure handler (a pinned sub-flow) runs once with the error summary.

**Continue-as-new only at a quiescent checkpoint.** Temporal doesn't carry child workflows into the continued run.
Closing the run would also apply the children's parent-close policy. So continue-as-new **never** cancels,
abandons or restarts an activity or a child workflow.
- **Quiescent** means: no activity and no child workflow is outstanding. Pending timers don't count: a timer has no
  side effect, so its absolute wake time goes into the snapshot and the continued run re-arms it.
- **Opportunistic checkpoint.** Once history passes 2,000 events, the scheduler continues-as-new at the next point
  that is already quiescent, for example between loop batches.
- **Drain mode.** The scheduler enters drain mode at 4,000 events, or when Temporal suggests continue-as-new, whichever comes first.
  - It starts no new activity or child workflow. Ready nodes stay queued in the snapshot.
  - Local work (control nodes, local CEL) continues.
  - When the last outstanding activity or child settles, it continues-as-new.
- **Headroom.** With the in-flight cap of 100, and a bounded number of events per activity or child completion,
  draining adds at most about 1,000 events. That keeps runs far below Temporal's 10,240-event warning and
  51,200-event limit. The draining run itself adds almost no history while it waits.
- **Cost.** A long child, for example a sub-flow in a long `delay`, holds the checkpoint back, and parallel branches
  wait until it settles. That only delays them; it never changes the result. The validator warns when a graph can
  run a long wait in parallel with other work.
- **Snapshot** (`snapshot_format: 1`):
  - variables;
  - completed outputs (values now, handles after 2b);
  - edge and node states per open scope, and loop cursors;
  - the ready queue and timer wake times;
  - the yield accumulator, the iteration counter (below) and the deadline.
- **Pinning.** A run never changes build, even across continue-as-new (parent §6.3, §7).
- **Threshold tests.** Drain mode is entered while loop-batch children, a sub-flow, activities and a timer are
  outstanding. No child is terminated or restarted, each activity completes once, the timer fires at its original
  wake time, and the continued run's state equals the snapshot.

**One iteration counter per logical run.**
- **Where it lives.** The root `RunGraph` execution owns the counter for the whole logical run. The snapshot
  carries the used and reserved totals through every continue-as-new, so a continued run never gets a fresh cap.
- **What counts.** An inline iteration or filter item is debited when it starts.
- **Children draw grants on demand.** The cap is exact: no child is ever refused while budget is unused elsewhere.
  - **Initial grant.** When a child starts (a loop batch or a sub-flow), the parent reserves an initial grant from
    its unreserved budget: the batch's own item count, or 1,000 for a sub-flow. The grant is recorded in the child's input.
  - **More on demand.** When a child has used up its grant, it asks its parent for more: a signal to the parent,
    answered by a signal back, in chunks of 1,000.
    - The parent grants from its unreserved budget, in the order the requests appear in its history.
    - A child's own children ask it the same way, and it asks up the chain when its budget runs short.
    - Drain mode still answers grant requests, because answering one isn't new work.
  - **Waiting, not refusing.** If the unreserved budget can't cover a request, the request waits while any other
    outstanding child still holds an unused grant. That child returns it when it settles.
  - **The cap.** Only when the budget is exhausted **and** no outstanding child holds anything unused has the run
    truly reached its cap. The waiting requests then fail with `iteration_cap_exceeded`, "This run reached its limit
    of 100,000 loop iterations", and the loop's error policy applies.
  - **Continue-as-new.** An outstanding grant request counts as outstanding work, so it never spans a continue-as-new.
    A parent only continues-as-new with no children outstanding, so grant signals always reach the run that issued the grant.
- **Settlement.**
  - A completed child returns `iterations_used`; the parent debits that amount and releases the rest.
  - A failed or cancelled child reports its usage in its failure details.
  - A child that ends without reporting (terminated) is debited its whole grant. That's conservative, and it happens only on abnormal termination.
- **Why it's deterministic.** Grants, requests, answers, results and totals are all recorded workflow data.
- The run summary shows the iterations used.

**Workflow-code rules:**
- No wall clock, randomness or I/O. `workflow.now()` and `workflow.uuid4()` are the only sources.
- No iteration over sets.
- Every dict that reaches a command or the state is built in a deterministic order.
- A lint check and the Temporal sandbox enforce these rules.

## 7. Versioning, deployment and replay

- **Worker Versioning, pinned** (parent §6.3). This follows Temporal's
  [inheritance semantics](https://docs.temporal.io/worker-versioning#inheritance-semantics).
  - **Deployment.** One Worker Deployment, `dewpoint-engine`. Each build is a Deployment Version with build ID
    `dewpoint-<version>+abi<engine_abi>`, and `engine_abi` covers `LOCAL_CEL_PROFILE`.
  - **Its versioned task queue**, also `dewpoint-engine`, carries:
    - `RunGraph`;
    - its child workflow types: loop batches and sub-flows;
    - the version-loading local activity;
    - the projection activities;
    - every plugin activity.

    Only workers of the matching build poll it for that version.
  - **Pinned, explicitly.** `RunGraph` and every child workflow type declare `VersioningBehavior.PINNED`. Children
    are started on `dewpoint-engine`, a queue that belongs to the parent's version, so they inherit that version.
    Because they are also declared Pinned, they stay on it.
  - **Activities** that a pinned workflow schedules on a queue belonging to its version run on that version.
  - **Continue-as-new** stays on `dewpoint-engine` without upgrade-on-continue-as-new, so it inherits the version.
  - **CEL queues** (`dewpoint-cel.<profile>`) are deliberately **not** part of the engine deployment. They're served
    by the CEL activity workers whatever the engine build. Correctness comes from profile routing (§5.7), not from
    inheritance.
    - The request schema is versioned (`cel.evaluate.v1`).
    - A CEL worker serves every schema version that any undrained engine build uses.
  - A build registers every `type@version` that isn't `retired` (§4.5). Old builds run until Temporal reports them drained.
  - **Two-build deployment test (required).** N-1 drains while N serves new runs, and N lacks a node type retired
    in between. The N-1 runs exercise child sub-flows, loop batches, plugin activities and continue-as-new.
    - Their histories must show that every **engine** task of an N-1 run executed on N-1: workflow tasks and
      `dewpoint-engine` activities, in the run itself, its children and its continued runs.
    - `cel.evaluate` is deliberately excluded. Instead, the test asserts that each CEL task ran on a worker serving the version's profile (§5.7).
- **Compose (2a):** adds `temporal`, `worker` and `cel-evaluator` (§5.7). The worker waits for a healthy evaluator
  before it polls a CEL queue.
- **Golden histories:** every build adds recorded histories to `tests/engine/replay/<build>/`. They cover:
  - branches, joins, dead paths and switch;
  - inline and batched loops, filter and transform;
  - sub-flows and every error policy;
  - the deadline and continue-as-new;
  - local and activity CEL, including the routing on runtime caps;
  - the yield-point timer.
- **Replay gate:** CI replays each history against **its own** build.
- **Upgrade paths:** snapshot-compatibility tests (N-1 → N) run only where an upgrade path is declared.
- **`engine_abi`:** increments on any change that can alter the command sequence. A change that doesn't increment it must pass the previous build's golden replays.

## 8. Run and step projection

- **`runs`:** id, tenant_id, workflow_version_id, status (`running`, `succeeded`, `failed`, `cancelled`,
  `deadline_exceeded`), started_at, ended_at, error summary.
- **`run_steps`:** run_id, step_id, `iteration_key`, `attempt`, status, timestamps, redacted input and output
  previews (≤ 8 KiB each), error code and sanitized message, `outcome` (`applied`, `simulated`, `outcome_unknown`),
  and the CEL mode used (`local`, `activity`).
- **Writes:**
  - Activity wrappers and a batched `project` activity upsert rows keyed `(run_id, step_id, iteration_key, attempt)`.
  - Control nodes are projected at each scheduler await.
  - The worker writes through the worker DB role inside `tenant_scope`.
- **Redaction:** `x-sensitive` fields become `"[redacted]"`, and oversize previews become `"[truncated]"`.
- **Read API:** `GET /runs` and `GET /runs/{id}` (with steps). The UI never reads Temporal history.

## 9. Starting runs in 2a

- **Internal only:** `engine` defines the start request. `apps` provides `start_run(version_id, payload, *, mode)` for tests, the dev CLI (`dewpoint dev run <version> --input file.json`) and, later, 2b's dispatcher.
- **No public run API in 2a.** Admission, idempotency keys and tenant slots arrive in 2b.

## 10. Testing strategy

- **Unit:**
  - graph model round-trips;
  - validator: structure, regions, types, path availability, variable writers, waits;
  - value model and templates.
- **Property-based (Hypothesis), liveness soundness:** on random DAGs with branches and parallel joins, whenever the
  validator treats a reference as always available, the producer ran in every simulated execution in which the consumer ran.
- **Property-based (Hypothesis), on random DAGs with if/switch/joins/error ports/loops:**
  - every node runs or dies exactly once per scope;
  - dead paths never execute;
  - branches that reconverge meet in the same scope;
  - no edge is left `pending` when a run ends, so nothing deadlocks.
- **Interpreter:** time-skipping tests for:
  - every node kind and every error policy, including `on_item_error`;
  - the deadline, batching, sub-flows and continue-as-new;
  - yield points.
- **Replay:** golden histories per build (§7).
- **CEL:** the gates in §5.9.
- **Evaluator isolation:**
  - the environment holds only allow-listed keys, and no credentials are present;
  - outbound connections fail (Compose `network_mode: none`);
  - oversized and malformed frames are refused;
  - `busy` appears above *N*;
  - a profile mismatch fails closed;
  - a missing profile times out to `cel_profile_unavailable`.
- **Lifecycle:**
  - activating a superseded version (rollback);
  - a queued request dispatches on its frozen version after a newer publish;
  - closure propagation: a parent becomes non-executable through a retired node type in a pinned sub-flow;
  - the forced-retirement preview lists parents that reach an entry only through a sub-flow;
  - the explicit, audited cancellation of queued requests;
  - races between retirement (normal and forced, both orders) and each of admission, dispatch, publish and activate.
    In every order, a request is either refused at admission, or blocks normal retirement, or is in the forced
    retirement's cancellation set. The defensive dispatch check never fires;
  - node types removed from a build while an N-1 run finishes on N-1.
- **Graph regions:** properly nested loops are accepted; crossing regions are rejected; the depth limit.
- **Iteration counter:**
  - one cap across inline loops, batch children, sub-flows and continue-as-new (parent and child);
  - **no premature rejection:** with 10 child slots and one busy child, that child can use nearly the whole budget;
  - requests wait while other children hold unused grants, and are refused only at the exact cap;
  - grants in drain mode;
  - settlement of failed and terminated children;
  - no fresh cap after continue-as-new.
- **Continue-as-new:**
  - the quiescent-checkpoint tests in §6;
  - a **measured** headroom test: drain with the in-flight cap saturated (100 activities and children), including
    activity retries, failures, heartbeats and grant traffic. It records the actual events and bytes added while
    draining, and asserts they stay within the stated headroom. The initial numbers are adjusted from this result.
- **Evaluator limits:** *N* derived from the cgroup limits; refusal to start without a memory limit.
- **Projection:** idempotent upserts under retries, redaction, and RLS (missing or mismatched tenant).
- **API:** draft CAS conflicts, publish diagnostics, activation, and the permission matrix for the new routes.

## 11. Decisions for review

1. **CEL placement.**
   - Every comprehension over a range not proven to be a list is rejected, including the boolean macros. This is stricter than the spike's validator.
   - Local evaluation requires the allow-listed subset, static bounds (≤ 10,000 iterations, ≤ 1 MiB intermediate) and runtime caps.
   - Everything else goes to the isolated evaluator.
2. **Numbers are initial limits to measure, not guarantees:**
   - caps of 64 KiB per value and in total, 1,000 list elements and 16 KiB per string;
   - loops: 100 items inline; filter: 1,000 items inline;
   - yield thresholds of 20,000 iterations, 8 MiB or 200 evaluations;
   - continue-as-new: opportunistic checkpoints from 2,000 events, drain mode from 4,000, in-flight cap of 100;
   - evaluator: 256 MiB / 5 s / 4 MiB requests;
   - schedule-to-start timeout of 10 minutes.

   The yield policy in particular is tuned by the adversarial test in §5.6.
3. **Local evaluation is a build constant** (`LOCAL_CEL_PROFILE`, part of `engine_abi`), set to none until all
   seven CEL gates pass. Enabling it never changes an open run.
4. **CEL runs in a separate, secretless evaluator** with no egress, reached over bounded IPC. It is routed by the
   version's `cel_profile` and fails closed. Its concurrency comes from its cgroup memory and CPU limits.
5. **Scopes are the root or loop iterations only.** Branches resolve edges as live or dead, and joins wait for every incoming edge to resolve.
6. **Version lifecycle.** Three questions are kept separate:
   - **Activatable:** executable. This allows rollback.
   - **Admissible:** the active version.
   - **Dispatchable:** the frozen version is still executable. Queued requests keep their version.

   Every check covers the pinned closure. Retirement is blocked by active and queued references; forcing it
   cancels queued requests explicitly, with an audit entry. A running run holds only its build (node types) or its
   profile's evaluator (CEL).
7. **Typed-path encoding** (§5.3): proven in plan 2a-2, with the conditions listed there. `asList()` remains the
   way to iterate `dyn` and nested lists.
8. **Package boundaries** follow the parent rules: `engine` is pure, storage lives in `core`, and wiring lives in `apps`. `testkit` stays under `tests/`.
9. **Nested loops** are allowed when properly nested (depth ≤ 3, per-run cap of 100,000 iterations). Crossing regions are rejected.
10. **Execution boundaries.**
    - Every transaction that creates or uses a reference takes a shared lifecycle lock on each entry of the closure. Retirement takes the exclusive lock first. Both are advisory locks.
    - Continue-as-new happens only at a quiescent checkpoint, with drain mode and an in-flight cap of 100.
    - One iteration counter per logical run, carried through continue-as-new. Children receive grants on demand, so the cap is exact.
11. **Temporal membership.** One engine deployment whose versioned queue carries workflows, children and plugin activities, all explicitly Pinned. CEL queues sit outside it, routed by profile.
12. **New `filter` node** (not in the parent's control-node list), so large collections never need a larger CEL budget.
13. **No public run API until 2b.**

## 12. Follow-up sub-projects

- **2b:**
  - admission: run_requests, outbox, dispatcher, slots;
  - triggers: manual forms and CSV, schedules, webhook ingress;
  - PayloadCodec and claim check, including `cel.evaluate` inputs by handle, and results derived from sensitive data staying claimed;
  - retention.
- **3:** flow plugin completion, and the Mist, messaging and ITSM plugins, with `ctx.connection()` and `ctx.http`.
- **4:** editor UI: CEL class badges, and the diagnostics from §5.10. With the Helm chart: the evaluator's network
  transport (§5.7).
  - It must be designed and approved before the chart runs activity-class CEL.
  - The Compose socket design doesn't carry over: a Unix socket can't cross pods, and a sidecar in the worker's pod
    would share the worker's egress.
- **5:** AI.
