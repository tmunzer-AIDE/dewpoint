# Dewpoint — Engine Core Design (sub-project 2a)

- **Status:** Draft for review, 2026-09-25
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
    runtime/           # RunGraph workflow code, execution tokens, snapshots, activity interfaces
    registry/          # manifest generation + validation (no storage)
  core/
    workflows/         # drafts (CAS), publish storage, immutable versions
    runs/              # runs, run_steps projection storage
    plugins/           # plugin_manifests / node_type_versions storage + reference tracking
  plugins/flow/        # manifests for control nodes; the transform node
  apps/
    api/routes/        # workflows.py (draft/validate/publish), runs.py (read)
    worker/            # Temporal worker: RunGraph + activity implementations (core-backed and plugin)
    cli/               # `plugins sync`, `dev run`
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
- An output field marked `x-sensitive: true` never reaches `run_steps`, previews or samples.
- The SDK has its own semver. First-party plugins pin a major version.

## 4. Workflows, versions and the graph model

### 4.1 Tables

Tenant-scoped tables use FORCE RLS with the foundations policy pattern.
- **`workflows`:** id, tenant_id, name, `draft` (JSONB), `draft_revision` (int, compare-and-swap), `vars_schema`, timestamps.
- **`workflow_versions`:** id, tenant_id, workflow_id, number, graph, `node_refs` (`type@version`), `engine_abi`,
  `cel_profile`, `connection_ids`, `subflow_version_ids`, `input_schema`, `vars_schema`, `content_hash`,
  `published_by`, `published_at`.
  - It also stores the **classification of every expression** (§5.5) and its static bounds, so the runtime never re-derives them.
  - Rows are insert-only: a trigger rejects UPDATE and DELETE.
- **`plugin_manifests`, `node_type_versions`:** global. They hold the manifest JSON, schema hashes and `retired_at`.
  A reference view counts published versions and non-terminal runs per `type@version`. Retirement is refused while
  that count is above zero.

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
  - The region may not have edges that leave it. It ends implicitly when every token in the iteration scope is
    finished (completed or dead).
  - `done` continues after all iterations.
  - The validator rejects overlapping regions, edges into a region from outside it (other than from the `body`
    port), and refs from outside a region to steps inside it.
  - The loop's `collect` value is evaluated at the end of each iteration and becomes `steps.<loop>.output.items[i]`.

### 4.3 Values, scope and availability

- **Every config field is one of:**
  - `literal`;
  - `ref {path, default?}`;
  - `template {parts: [text | ref]}`;
  - `cel {expr}`.
- **Scope:**
  - `trigger.*`
  - `steps.<key>.output.*`
  - `steps.<key>.error`: `{code, message, attempt}`; only for steps with `on_error` ≠ `fail`.
  - `vars.*`: typed by `vars_schema`.
  - `loop.item`, `loop.index`
  - `run.id`, `run.started_at`, `run.now`: workflow time from `workflow.now()`, never the host clock.
- **Path availability** (parent §6.4) uses dominators over the graph after regions are resolved.
  - A ref is *always available* if its producer dominates the consumer in the same or an enclosing scope. Otherwise it is *conditional*.
  - Conditional refs, and schema-optional fields, need a `default` (ref, template) or a `has()` guard (CEL).
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

Publish is audited: version number, content hash, classification summary.

## 5. CEL subsystem

### 5.1 Decision status

- The runtime is **`cel-expr-python==0.1.3` (Google cel-cpp), chosen provisionally.**
- It sits behind a small `CelRuntime` adapter with four operations: compile with a typed environment, get the
  checked AST, evaluate, and classify errors. The rest of the engine never imports the library directly.
- `cel_profile = "cel-cpp-0.1.3/fn-1"` (runtime pin plus Dewpoint function-library version) is stored on each version.
  - Workers load the profile of the version they execute.
  - A new runtime or library version is a new profile. It ships only after the §5.9 gates pass.
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
- **This encoding goes beyond what the spike validated.** Before anything relies on it, the implementation plan's
  first CEL task must prove, with tests, how it behaves in cel-cpp 0.1.3:
  - qualified-name resolution;
  - interaction with `has()`;
  - binding of both the root and the qualified identifier.
  If it fails, `asList()` (§5.4) becomes the only way to use a list-valued `dyn` range.
- **Binding checks.** Before evaluation, every bound value is checked against its declared kind (list, map, string,
  int, double, bool). A mismatch fails the evaluation with `type_mismatch` before any CEL runs. This makes the
  classifier's type facts hold at runtime, even if a producer violated its schema.
- **Time.** `datetime` isn't accepted as an input variable (spike). `run.now` and `run.started_at` are bound as
  RFC 3339 UTC strings, used as `timestamp(run.now)`. The activity evaluator receives them from the workflow; it never reads its own clock.

### 5.4 Function library `fn-1`

| Function | Purpose | Cost | Output bound |
|---|---|---|---|
| `sortedKeys(map<string, dyn>) → list<string>` | the only way to iterate a map (code-point order) | O(n log n), n ≤ map size | ≤ input |
| `asList(dyn) → list<dyn>` | proves a `dyn` range is a list; `type_mismatch` error otherwise (a map is never accepted) | O(1) | = input |
| `ipInCidr(string, string) → bool`, `cidrContains(string, string) → bool` | IP/CIDR tests (IPv4/IPv6) | O(1) | bool |
| `macNormalize(string) → string`, `macOui(string) → string` | MAC formats | O(1) | ≤ 17 code points |

- Also available: the CEL standard library, **minus** extension libraries and `cel.bind`, which aren't enabled.
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
   - Local requires ≤ 10,000 iterations, so the budget can never fire locally, and ≤ 1 MiB for the largest intermediate value.
   - The bounds are stored with the version.

**Activity.** Valid expressions that are not local run in the isolated `cel.evaluate` activity (§5.7), and the
result is recorded in history. This is the parent's `eval` activity (§6.5).

### 5.6 Runtime routing and in-workflow work

- Before a local evaluation, `RunGraph` measures the values the expression references (identifiers from the checked AST's reference map). Those values are already in workflow state, so measuring is deterministic.
- **Caps (the estimator's assumptions):**
  - each referenced value ≤ 64 KiB of canonical JSON, and ≤ 64 KiB in total;
  - every list ≤ 1,000 elements;
  - every string ≤ 16 KiB.
- If any cap is exceeded, the same expression runs in `cel.evaluate` instead. Routing depends only on recorded values, so a replay routes the same way.
- **Workflow-task time.** The scheduler counts local evaluations since its last await. At 200, it awaits a 1 ms durable timer, which creates a yield point.
  - This bounds the CPU spent in one workflow task to 200 × the latency gate's p99, and the count is replay-deterministic.
  - The timer events count toward the continue-as-new threshold.

### 5.7 Isolated evaluation (`cel.evaluate` activity)

- **Zygote.** At worker startup, before the Temporal SDK starts its threads, the worker spawns a single-threaded zygote process that imports the runtime.
- **One child per evaluation.** The zygote forks a child for each evaluation. The child:
  - sets `RLIMIT_AS` = 256 MiB and `RLIMIT_CPU` = 5 s;
  - inherits only its result pipe;
  - evaluates once and exits.
  The parent enforces a 5 s wall-clock timeout and kills the child when it expires.
- **Linux only.** The worker refuses to register the activity if it can't set these limits.
- **Inputs.** The expression's checked form and the values it references. In 2b they arrive as claim-check handles and are read inside the activity.
- **Results.**
  - The outcome is a value: `{ok: value}` or `{error: code, message}`.
  - `memory_limit`, `cpu_limit`, `timeout`, `iteration_budget_exceeded` and `output_too_large` are evaluation outcomes. They are **recorded and not retried**.
  - Temporal retries (3 attempts) cover only infrastructure failures: the zygote is gone or the worker is lost.
- **Task queue.** Its own queue, `dewpoint-cel`, so evaluation capacity scales separately from graph execution.

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
7. **Local latency:** p99 ≤ 5 ms per local evaluation at the caps on the CI runner.

**Rollout order.**
- Until gates 1–7 pass in CI, the runtime treats every expression as activity class, whatever the classifier says. A single setting, off by default, enables local evaluation.
- Worker images are built for one CPU architecture per build ID. Publishing another architecture requires running the gates on it.

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
| `cel.conditional_ref` | "`steps.x` may not have run on every path. Guard it with `has(steps.x)`." |

- The same codes appear in run errors (`steps.<key>.error.code`) for the runtime outcomes: `iteration_budget_exceeded`, `memory_limit`, `timeout`, `type_mismatch`, `output_too_large`.

## 6. `RunGraph` interpreter

**Inputs:**
- `run_id`, `workflow_version_id`, the trigger payload (a handle from 2b);
- `deadline` = `started_at` + `max_run_duration` (default 30 days; parent §6.3).

The version (graph, classifications, bounds) is loaded by one local activity and is immutable for the run.

**Execution tokens:**
- A token is `(node_id, scope)`. `scope` is the chain of branch decisions and loop iteration keys, for example `if1:true/loop2:7`.
- A single scheduler loop owns a ready queue ordered by `(topological index, scope)`. It starts activities and child workflows as futures and awaits them. Nothing else in the workflow creates concurrency.
- **Joins:** a node with several incoming edges fires in a scope once every incoming edge in that scope is either
  satisfied or proven dead. If all incoming edges are dead, the node is dead too and propagates dead tokens (dead-path elimination).

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

**Continue-as-new:**
- It happens at 8,000 history events, or at a loop batch boundary when the count is over 4,000.
- It carries a versioned snapshot (`snapshot_format: 1`): variables, completed outputs (values now, handles after
  2b), pending tokens, loop cursors and the deadline.
- Runs are pinned: a run never changes build, even across continue-as-new (parent §6.3).

**Workflow-code rules:**
- No wall clock, randomness or I/O. `workflow.now()` and `workflow.uuid4()` are the only sources.
- No iteration over sets.
- Every dict that reaches a command or the state is built in a deterministic order.
- A lint check and the Temporal sandbox enforce these rules.

## 7. Versioning, deployment and replay

- **Worker Versioning, pinned** (parent §6.3):
  - The build ID is `dewpoint-<version>+abi<engine_abi>`.
  - A build registers every plugin activity version that published versions or non-terminal runs still reference.
  - Old builds run until Temporal reports them drained.
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
- **Property-based (Hypothesis), on random DAGs with if/switch/joins/loops:**
  - every reachable node runs exactly once per scope;
  - dead paths never execute;
  - each join fires once.
- **Interpreter:** time-skipping tests for every node kind, every error policy, the deadline, batching, sub-flows, continue-as-new and yield points.
- **Replay:** golden histories per build (§7).
- **CEL:** the gates in §5.9.
- **Projection:** idempotent upserts under retries, redaction, and RLS (missing or mismatched tenant).
- **API:** draft CAS conflicts, publish diagnostics, and the permission matrix for the new routes.

## 11. Decisions for review

1. **CEL placement.**
   - Every comprehension over a range not proven to be a list is rejected, including the boolean macros. This is stricter than the spike's validator.
   - Local evaluation requires the allow-listed subset, static bounds (≤ 10,000 iterations, ≤ 1 MiB intermediate) and runtime caps.
   - Everything else goes to the isolated activity.
2. **Numbers.**
   - Caps: 64 KiB per value and in total, 1,000 list elements, 16 KiB per string.
   - Loops: 100 items inline; filter: 1,000 items inline.
   - Yield point after 200 local evaluations.
   - Continue-as-new at 8,000 events.
   - Isolated evaluation: 256 MiB / 5 s.
3. **Local evaluation is off by default** until all seven CEL gates pass in CI.
4. **Typed-path encoding** (§5.3) is the first CEL item to prove. `asList()` is the fallback.
5. **Package boundaries** follow the parent rules: `engine` is pure, storage lives in `core`, and wiring lives in `apps`. `testkit` stays under `tests/`.
6. **New `filter` node** (not in the parent's control-node list), so large collections never need a larger CEL budget.
7. **No public run API until 2b.**

## 12. Follow-up sub-projects

- **2b:**
  - admission: run_requests, outbox, dispatcher, slots;
  - triggers: manual forms and CSV, schedules, webhook ingress;
  - PayloadCodec and claim check, including `cel.evaluate` inputs by handle, and results derived from sensitive data staying claimed;
  - retention.
- **3:** flow plugin completion, and the Mist, messaging and ITSM plugins, with `ctx.connection()` and `ctx.http`.
- **4:** editor UI: CEL class badges, and the diagnostics from §5.10.
- **5:** AI.
