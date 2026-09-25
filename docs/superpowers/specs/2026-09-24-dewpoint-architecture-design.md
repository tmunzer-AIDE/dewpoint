# Dewpoint — Architecture Design

- **Status:** Approved design (brainstorming), 2026-09-24
- **Scope:** Umbrella architecture for v1 and delivery decomposition. Each delivery sub-project (§14) gets its own implementation plan, and a narrower spec where needed.
- **Mockups:** https://claude.ai/artifact/KcgxkombxiH1bvYV7zS4Ld (editor, data picker, simulate vs. live run)

## 1. Purpose

Dewpoint is a self-hosted, multi-tenant, no-code automation platform for Juniper Mist and adjacent systems. Users build workflows on a visual canvas. Workflows are triggered by webhooks, schedules or manual starts, and they:

- read and write Mist objects via the Mist OpenAPI Specification (OAS), extensible to other vendors;
- use flow control: delay, loops, if/switch, variables and sub-flows;
- notify and integrate: outbound webhooks, Slack, Microsoft Teams, Google Chat, email, syslog/CEF, ServiceNow, PagerDuty;
- run AI agents backed by configurable LLMs, with tools and external MCP servers.

An in-app AI builder drafts workflows from a description. The project is intended for public release (Apache-2.0) so customers and partners can deploy it.

### 1.1 Relationship to mist_automation

Dewpoint is a clean break from `mist_automation`. There is no data import. Backup, digital twin, telemetry and impact analysis stay in `mist_automation`.

`mist_automation` declares a proprietary license, so it is a **design reference only**. Code is written fresh from this spec. Copying any extracted code requires prior confirmation of ownership and dependency provenance.

### 1.2 Goals

- A modular core: a new integration is a new plugin package, with no edits to core, engine or UI code for ordinary nodes.
- Secure by construction for multi-tenant MSP use.
- A modern, simple configuration UX, fixing the current editor's step-configuration pane.
- Durable execution: long delays, retries and crash recovery via Temporal.

### 1.3 Non-goals for v1

- Arbitrary code or "script" nodes. They are removed. CEL and the transform node cover expressions.
- Third-party plugin *execution*. Only the contract is defined; the sandbox worker ships post-v1.
- The external MCP server. The internal tool layer is built so it can be exposed later.
- Agent memory. The data model reserves the field.
- A provider (MSP) administrative level above tenants (§4.1).
- A declarative OpenAPI connector. The plugin contract keeps room for it.
- Upgrading pinned runs on continue-as-new (Temporal Public Preview feature).

## 2. Decisions summary

| Topic | Decision |
|---|---|
| Tenancy | Multi-tenant. Flat tenants plus user memberships. |
| Authentication | Local accounts: argon2id passwords, TOTP, WebAuthn passkeys, recovery codes. No Mist SSO. |
| Mist access | Per-tenant *connections* (cloud host + org + API token). Several per tenant. Every step binds one explicitly. |
| Backend | Python 3.12+, FastAPI, Pydantic v2, SQLAlchemy 2 (async) + asyncpg, Alembic |
| Execution | Temporal: a generic `RunGraph` interpreter workflow; plugin calls run as versioned activities |
| Database | PostgreSQL. Separate `app` and `temporal` databases. RLS as defence in depth. |
| Queues/cache | No Redis. Add it only on a measured need. |
| Frontend | React 19, Vite, TypeScript, React Flow, Radix primitives + Tailwind with custom tokens, TanStack Router/Query |
| Extensibility | Python plugin packages with static manifests. Room left for a declarative OpenAPI connector. |
| Expressions | Typed values (literal, ref, template, cel). CEL for conditions and computed values. No Jinja. |
| License / distribution | Apache-2.0. Docker Compose and a Helm chart. |

## 3. Runtime architecture and trust boundaries

### 3.1 Processes

| Process | Responsibility | Permissions |
|---|---|---|
| `web` | Static SPA served by nginx | none |
| `api` | Users, tenants, workflows, connections, runs, approvals, the AI builder. The only user-facing service. | DB role `app_api` (RLS-bound). Temporal client limited to signals and queries. **Imports no plugin code.** |
| `ingress` | `POST /hooks/{endpoint_id}` and `/health` only | DB role `app_ingress`: may call `resolve_webhook_endpoint()` and insert `inbound_events` and `outbox`. No Temporal client. |
| `dispatcher` | Drains the outbox, matches subscriptions, admits runs, starts workflows | DB role `app_dispatch`, Temporal client |
| `worker-core` | `RunGraph` and `AgentLoop` workflows, plus first-party plugin activities | DB role `app_worker`, Temporal worker |
| `worker-sandbox` | *Post-v1.* Third-party plugin activities. | No DB or Temporal-admin credentials. Non-root, read-only filesystem, seccomp, NetworkPolicy egress limited to the plugin's declared domains, optional gVisor. Receives credentials only through a broker. |
| `postgres`, `temporal` | Persistence and orchestration | — |

`api`, `ingress` and `dispatcher` may share one image, but they run as distinct processes with distinct routes, credentials and DB roles.

### 3.2 Repository layout

```
dewpoint/
  backend/
    core/        # domain: tenants, users, auth, connections, workflows, runs, audit (no plugin knowledge)
    engine/      # graph model, validator, CEL, RunGraph interpreter, admission
    sdk/         # dewpoint-sdk: public plugin API (published package)
    plugins/{flow,mist,messaging,itsm,ai}/
    apps/        # thin entrypoints: api, ingress, dispatcher, worker, cli
  frontend/
  deploy/{compose,helm}/
  docs/
```

Import rules are enforced in CI with import-linter:
- `sdk` has no internal dependencies.
- `plugins/*` depend only on `sdk`.
- `engine` depends on `sdk`.
- `core` depends on neither `engine` nor any plugin.
- Only `apps` wires the packages together.

### 3.3 Plugin trust model

- **First-party plugins** are trusted deployment code. They are imported only by `worker-core`. The SDK `ctx` object is an *API*, not a sandbox: first-party code runs with the worker's privileges.
- **Third-party plugins** get isolation (no DB access, only brokered credentials) only once `worker-sandbox` and the credential broker ship. Until then, installing third-party plugin code is unsupported.
- A plugin ships a **static manifest**: node types, credential and connection types, triggers, JSON Schemas, output schemas, capabilities, side-effect policies, widget hints and icons. `dewpoint plugins sync` validates it and stores it in `plugin_manifests` and `node_type_versions`. `api` reads only this data.
- **Dynamic options** (for example listing a connection's sites) run as short `options` activities on the plugin's worker. The API never executes plugin code.
- **UI widgets:** schemas may reference named first-party widgets through `x-widget`, for example `mist.api-operation`, `pill-text`, `cel`, `connection`, `message-blocks`, `nested-update`. The widget contract receives value, schema, upstream variable schema and an options-loader handle. Third-party plugins can use only built-in widgets; there is no third-party JavaScript in v1.

## 4. Tenancy, identity and authorization

### 4.1 Tenancy

- Tenants are flat. Users are global (unique email) and hold **memberships** in one or more tenants with a role. This is how MSP staff work across customer tenants.
- Provider-wide administration, shared provider templates and cross-tenant dashboards are **post-v1**. Sharing in v1 is by export and import of workflow templates.
- Platform operators carry a `platform_admin` flag. Every cross-tenant operator action uses a separate DB role and is audited.

### 4.2 Authentication

- Passwords are hashed with argon2id. TOTP and WebAuthn passkeys are supported, with recovery codes. MFA is required by platform policy, and a tenant may require passkeys.
- Sessions are server-side in Postgres: an opaque HttpOnly, Secure, SameSite cookie plus a CSRF token. No JWTs in the browser.
- Idle and absolute timeouts apply. A password or MFA change revokes all of that user's sessions. Switching to a tenant with a stricter policy triggers step-up authentication.
- Login and MFA attempts are rate-limited and locked out using Postgres-backed counters.
- `api_tokens` (hashed) is reserved for the future external MCP server and API.

### 4.3 Roles and permissions

- Per-tenant roles: `owner`, `admin`, `editor`, `operator`, `viewer`.
- Roles are bundles of permission strings, for example `connection.use`, `connection.manage`, `workflow.edit`, `workflow.publish`, `run.start`, `run.view`, `approval.decide`, `agent.grant`.
- Editors can *use* connections but never read their secrets.

### 4.4 Authority and RLS

- **Authoritative scope checks:**
  - `api`: the membership and permission check on every request; the tenant is taken from the route `/api/v1/t/{tenant_id}/…`.
  - Workers: loading the persisted `run_requests` and `runs` rows by ID.
  - `dispatcher`: the persisted event or request row.
- **RLS is defence in depth.** Every tenant table has `tenant_id`, `ENABLE` and `FORCE ROW LEVEL SECURITY`, and the policy `tenant_id = current_setting('app.tenant_id', true)::uuid`. A missing setting yields no rows (fail closed). Services connect as non-owner roles and `SET LOCAL app.tenant_id` per transaction, only after the authoritative check.
- RLS does not defend against a compromised service role, which can set any tenant ID. That is why the checks above are authoritative.
- `ingress` resolves an endpoint before it knows the tenant, through the `SECURITY DEFINER` function `resolve_webhook_endpoint(endpoint_id)`. It returns only `tenant_id`, the verification mode and the verification material. Endpoint IDs are random 128-bit values.
- Tests cover missing tenant context, mismatched tenant rows, and a role × endpoint permission matrix.

## 5. Data model (PostgreSQL `app` database)

| Area | Tables |
|---|---|
| Identity | `tenants`, `users`, `user_mfa`, `webauthn_credentials`, `recovery_codes`, `sessions`, `memberships`, `api_tokens` |
| Secrets | `tenant_keys` (wrapped data key, version), `connections` |
| Design | `workflows` (draft graph, draft revision), `workflow_versions` (immutable), `agents`, `agent_versions`, `builder_sessions`, `builder_proposals` |
| Grants | `service_grants` (tenant-admin grants for unattended agent tool/connection use) |
| Triggers | `webhook_endpoints`, `trigger_bindings`, `schedules` |
| Admission | `inbound_events`, `outbox`, `run_requests`, `tenant_run_slots` |
| Execution | `runs`, `run_inputs` (manual form values and parsed CSV rows, encrypted), `run_steps`, `step_outputs` (claim check), `llm_calls`, `approvals` |
| Platform | `plugin_manifests`, `node_type_versions` (global, with reference tracking), `egress_allowlist` |
| Audit | `audit_log` (append-only, hash chain), `audit_anchors` |

**Connections are generic.** Each has a manifest-defined type (`mist`, `slack`, `teams`, `gchat`, `smtp`, `servicenow`, `pagerduty`, `webhook`, `syslog`, `llm.*`, `mcp.http`), a non-secret config validated by its schema (for example Mist cloud host and org ID), and a secret blob encrypted with the tenant data key.

**`workflow_versions` is immutable.** It stores:
- the graph;
- exact node-type references (`mist.object.update@2`);
- `engine_abi` and `cel_profile`;
- the declared `connection_ids`;
- pinned sub-flow version IDs;
- a content hash;
- the publisher and publish time.

## 6. Execution engine

### 6.1 Admission (one path for every trigger)

Every run starts as a durable `run_requests` row, unique on `(tenant_id, idempotency_key)`. The row is written in the same transaction as an `outbox` row.

- **Webhook:**
  - `ingress` verifies the request: HMAC or token, optional IP allowlist, size limit and rate limit. The tenant comes from the endpoint, **never from the payload's `org_id`**.
  - It splits multi-event payloads, and **in one transaction** inserts each `inbound_events` row (unique `(tenant_id, dedupe_key)`, payload encrypted) and its `outbox` row. It returns 2xx only after commit.
  - `dispatcher` claims rows with `FOR UPDATE SKIP LOCKED`, and **in one transaction** matches `trigger_bindings` and freezes one `run_requests` row per `(event_id, workflow_id)`, pinned to the `workflow_version_id` published at match time. Retries see only these frozen rows.
- **Manual:** `api` inserts a `run_requests` row with the client-supplied idempotency key. The manual trigger declares an **input form** (§6.8), which can include a CSV file.
- **Schedule:** a Temporal Schedule fires the `ScheduleTick` workflow. Its single activity inserts a `run_requests` row keyed `sched:{schedule_id}:{scheduled_time}`. Schedules never start `RunGraph` directly.
- **Admission:** `dispatcher` is the only component that starts `RunGraph`.
  - It reserves a per-tenant concurrency slot (`tenant_run_slots`, row lock). The request stays queued, FIFO per tenant, while the tenant is at its limit.
  - It starts the run with workflow ID `run:{run_request_id}`, which makes the start idempotent.
  - The run releases its slot in a final activity. A reconciler compares slots against Temporal state to recover leaks.
  - Sub-flow child workflows and agent loops run inside the parent's slot.
- Failure handling: backoff, then a dead-letter state visible to admins.

### 6.2 `RunGraph` interpreter

- Loads a pinned `workflow_versions` row and walks the graph deterministically.
- **Control nodes run in the interpreter:** `if`, `switch`, `loop` (for-each over a list; `body` and `done` ports; concurrency and item caps), `delay` / `wait until` (durable timers), `set variables`, `stop` / `fail`, `run workflow` (a child workflow pinned to the sub-flow version recorded at publish; depth ≤ 5; cycle check at publish).
- **Side-effecting nodes run as versioned activities** named `<type>.v<version>`.
- **Execution scopes:** join and skip bookkeeping is tracked per execution scope (the root, or one loop iteration), not per node. Branch decisions resolve outgoing edges as live or dead; they don't create scopes. A node with several incoming edges waits until every incoming edge in its scope is resolved, runs if any is live, and is otherwise eliminated (dead-path elimination). Details: engine-core spec §6.
- **Large loops** run as batches of child workflows. Long histories use continue-as-new with a versioned state snapshot.
- **`run_steps` projection:** activity wrappers and a batched `project` activity upsert redacted, size-capped rows keyed `(run_id, step_id, iteration_key, attempt)`. The UI reads only this projection, never Temporal history.

### 6.3 Versioning and upgrades

- `RunGraph` and `AgentLoop` use **Temporal Worker Versioning with pinned behaviour**. A run completes on the build it started on, including across continue-as-new; v1 does **not** use upgrade-on-continue-as-new.
- **`max_run_duration` (default 30 days)** is enforced across the whole logical run: continue-as-new, child workflows, waits, delays and approvals. The validator rejects graphs whose static waits exceed it, and the run fails with a timeout when the deadline is reached.
- Deployments keep every previous worker build running until Temporal reports it **drained**. Only then is it retired. The Helm chart and runbook implement this.
- **Plugin activity versions** stay registered in new builds until retired. Retirement is blocked by the pinned closures of active versions and of queued run requests; forced retirement cancels those requests explicitly, with an audit entry. Non-terminal runs keep only their own pinned build (or CEL profile evaluator) alive (engine-core spec §4.5). Manifests may ship config migrations (vN→vN+1), which are applied when a user edits a draft. Published versions are never rewritten.
- `workflow.patched()` is reserved for emergency fixes.
- CEL library version and custom functions are part of the build, identified by `cel_profile`.

### 6.4 Data, variables and expressions

- Every config field holds one of:
  - `literal`
  - `ref`: for example `steps.get_site.output.name`, optionally with a `default`
  - `template`: text with embedded refs
  - `cel`
- **Scope:** `trigger.*`, `steps.<key>.output.*`, `steps.<key>.error`, `vars.*`, `loop.item`, `loop.index`, `run.*`.
- Output schemas come from manifests. For Mist, they come from OAS responses.
- **Publish-time validation:**
  - type checks every ref;
  - runs **path availability analysis** (dominators): a ref is *always* available if its producer dominates the consumer, otherwise *conditional*;
  - requires conditional refs, and manifest- or OAS-optional outputs, to carry a `default` or a `has()` guard.
- **CEL** uses workflow time (`run.now`) and a pinned custom function library (CIDR/IP, MAC, `sortedKeys`), with a fixed per-evaluation iteration budget and an output size cap. The transform node is bounded the same way.
- **Decided after the spike** (engine-core spec §5): Google's `cel-expr-python` (cel-cpp), provisionally. Only a proven restricted subset with statically bounded work runs inside the interpreter. Every other valid expression runs in an isolated, resource-limited activity whose result is recorded in history. Publish rejects any route from unordered map iteration to an order-dependent value.

### 6.5 Secrets and sensitive data in Temporal

- Activity inputs carry only IDs (`tenant_id`, `run_id`, `step_id`, `connection_id`) plus non-secret config.
- A **credential resolver** inside the activity checks that the run's version declares the `connection_id` (and, for unattended agent tools, that a `service_grants` row exists). It then decrypts the secret in memory. There is no cross-tenant caching and **no tenant-default connection fallback**.
- A **Temporal PayloadCodec** envelope-encrypts every payload with a per-tenant data key, wrapped by a key-encryption key from an environment secret, Vault or KMS. The Temporal Web UI is not exposed, or is restricted to platform operators through an authenticated codec server.
- **Claim check:** outputs above a size threshold, and fields a manifest marks `sensitive`, are stored encrypted in `step_outputs`; only a handle enters history.
  - A CEL expression that needs claimed data is evaluated in an `eval` activity that returns only the reduced result.
  - A result derived from a sensitive field stays claimed.
- **Retention:**
  - Temporal: one shared namespace with a single platform-wide closed-history retention period (operator setting, for example 7 days).
  - Tenant-specific retention applies to app-side data: `runs`, `run_steps`, `step_outputs`, `inbound_events`, `llm_calls`.

### 6.6 Errors, retries and side effects

- Per node: timeout, retry policy (defaults from the manifest), and `on error` = fail run (default), continue, or route to an `error` port.
- The SDK has typed errors: `RetryableError` and `FatalError`. For Mist, 4xx is fatal; 429 and 5xx are retryable, honouring `Retry-After`.
- **Side-effect policy** is declared in the manifest for every side-effecting node:
  - `idempotent`: retries are safe.
  - `keyed`: the plugin sends an idempotency key derived from `(run_id, step_id, iteration_key)`, for example the PagerDuty `dedup_key` or a ServiceNow correlation ID.
  - `reconcilable`: after an ambiguous failure, `reconcile()` checks for the effect before retrying, for example finding a created Mist object by a run marker.
  - `ambiguous`: email, syslog, incoming webhooks. Never retried automatically once the request may have been sent. The step becomes `outcome_unknown` and follows its error policy.
- Each workflow has an optional failure handler (notify, or run a sub-flow).
- **Limits:**
  - Per-tenant run concurrency (§6.1).
  - Per-connection Mist rate-limit token buckets in Postgres.
  - Per-tenant LLM budgets.

### 6.7 Outbound network capability

- Outbound HTTP is a granted capability.
- The SSRF guard resolves DNS and checks **every** resolved address and **every** redirect hop. It pins the vetted IP for the connection, and disallows cross-host redirects unless the destination is also permitted.
- Private or local destinations (for example a local LLM or an internal MCP server) are allowed only if listed in the platform-admin `egress_allowlist`. This is checked at connection creation **and on every request**.

### 6.8 Manual trigger inputs and CSV upload

- A manual trigger declares an input form: typed fields (text, number, boolean, select, connection-scoped pickers such as Mist site) and, optionally, **one CSV input**.
- **Column schema:** the CSV input declares its columns: header name, variable name (a valid identifier), type (`string`, `integer`, `number`, `boolean`, `mac`, `ip`, `cidr`, `enum`), required, and default.
  - At run time the user maps the file's headers to the declared columns. Headers that match exactly are auto-mapped, and the mapping can be saved as the trigger's default.
- **Validation on upload, in `api`, before any run is admitted:**
  - UTF-8 (BOM tolerated); delimiter detected among `,`, `;` and tab.
  - Size and row caps (platform defaults 5 MB and 10,000 rows; a tenant may lower them).
  - Every row is type-checked. A per-row error report is shown, and the user fixes the file or chooses **skip invalid rows** (skipped rows are recorded in the run).
  - The file is parsed as data only. There is no formula evaluation.
  - Values starting with `=`, `+`, `-` or `@` are escaped whenever Dewpoint later exports them.
- **Storage:** parsed rows are stored encrypted as a claim-checked `run_inputs` row (tenant retention applies), and only its handle enters Temporal history. The original file isn't kept unless the tenant enables it for audit.
- **In the graph:**
  - `trigger.rows` is a typed list of objects keyed by variable name, and `trigger.row_count` is also available. Pills and validation use the declared column types.
  - A **loop** over `trigger.rows` exposes `loop.item.<column>` (for example `loop.item.site_name`), plus `loop.index`.
  - The loop loads rows in pages through an activity, in child-workflow batches (§6.2). Loop concurrency and error policy per iteration (stop, or continue and collect failures) are set on the loop node.
  - The run summary lists the outcome for each row.
- **UI:** "Run workflow" opens the input form with a file drop zone, a column-mapping step, a preview of the first rows with validation errors highlighted, and the row count. The start button states the row count ("Start run for 248 rows"). Write-capable workflows also show the confirmation rules from §10.4.

## 7. Plugin SDK (`dewpoint-sdk`)

```python
class UpdateObject(Node):
    type = "mist.object.update"; version = 2
    Config = UpdateObjectConfig          # Pydantic → JSON Schema (+ x-widget, x-group hints)
    Output = MistObjectOutput            # → output schema
    credentials = ["mist"]
    capabilities = {"mist.write"}
    side_effect = SideEffect.IDEMPOTENT
    async def run(self, ctx, config) -> Output: ...
    async def simulate(self, ctx, config) -> Output: ...      # fixture-based dry run
    async def options(self, ctx, field, query) -> list[Option]: ...
    async def reconcile(self, ctx, config) -> Output | None: ...  # when side_effect=RECONCILABLE
```

`ctx` provides:
- `ctx.connection(id)`: an authorized client; the raw secret is not exposed through the API;
- `ctx.http`: the SSRF-guarded client;
- a redacting logger, heartbeat and cancellation;
- idempotency-key helpers.

Manifests are generated from these classes at build time and validated by `dewpoint plugins sync`.

## 8. First-party plugins (v1)

- **flow:** control nodes (§6.2) plus `transform` (CEL-based mapping).
- **mist:**
  - A **curated resource/action map**, kept as data in the plugin, over the Mist OAS: resources such as Site, Site settings, Device, WLAN, Network template, with actions get / list / create / update / delete and device actions.
  - "Any endpoint" is an advanced node, still validated on the server against the OAS, capabilities and connection scope.
  - **Nested update node:** per-field Keep / Set / Null semantics. For objects the API replaces wholesale, the mode is **Merge with current (read first; default)** or **Replace with only these**. The node shows a request preview and a race-window warning for merge.
  - Also: the Mist webhook trigger (topic filters), dynamic options, and OAS-example fixtures for `simulate()`.
- **messaging:** outbound webhook (HTTP), Slack, Teams, Google Chat through a **single message model** (title, text with refs, fields, buttons, severity) mapped to Block Kit, Adaptive Cards and Chat cards. Also email (SMTP) and syslog (RFC 5424 / CEF, UDP/TCP/TLS).
- **itsm:** ServiceNow (incident create/update, correlation ID) and PagerDuty Events v2 (`dedup_key`).
- **ai:** §9.

## 9. AI

### 9.1 LLM connections

- Types: `llm.openai`, `llm.anthropic`, `llm.azure_openai`, `llm.bedrock`, `llm.openai_compatible` (Ollama, vLLM, LM Studio).
- A thin internal `ChatModel` adapter is built on official provider SDKs, not a large aggregator, with hash-pinned dependencies.
- Private endpoints are subject to §6.7.

### 9.2 Agent library

An `agent_versions` row is immutable and holds:
- the model connection and instructions;
- input and output JSON Schemas (structured output, which becomes pills downstream);
- **tools**: catalog node types bound to named connections, and `mcp.http` servers (streamable HTTP only, **no stdio**) with an explicit tool allowlist;
- **limits**: iterations, tool calls, tokens, wall time, cost;
- a **write policy** per tool: `never`, `requires_approval` (the default for write tools), or `autonomous` (requires `agent.grant`);
- a reserved `memory` field (`none` in v1).

Built-in agent templates ship as plugin data, and tenants clone them.

### 9.3 Unattended authority

At publish time, every agent tool and connection pair used by a workflow version needs an explicit **`service_grants`** row created by a tenant admin. The publisher's own permissions are never used. Every call checks that the grant still exists and fails closed if it doesn't.

### 9.4 `AgentLoop` runtime

- A child workflow. Each LLM call and each tool call has a stable **`call_id`**. Results and usage are persisted (`llm_calls`, claim-checked transcript) **before** the loop advances.
- **Budgets:** checked before each call using the worst case (input tokens + `max_tokens`), then settled with reported usage.
- **LLM timeouts:** a timed-out call counts as spent. It is retried only if the remaining budget covers the worst case again.
- Structured output is validated against the pinned schema, with one repair attempt, then failure.
- **Enforcement outside the model on every call:** tool allowlist, argument JSON Schema, connection scope, write policy, grants and limits. Prompt fencing of untrusted data (trigger payloads, tool results, MCP responses) is presentation only, not a security control.
- **MCP pinning:** an agent version pins the MCP connection identity (URL, TLS identity, server info) **and** each allowed tool's definition hash. If a live definition doesn't match or can't be verified, the tool is unavailable (fail closed). Drift is flagged for re-approval.

### 9.5 Approvals

- An approval record covers **one exact invocation**: `run_id`, `step_id`, `call_id`, `tool@version`, `connection_id`, argument hash, redacted arguments, requester, approver, decision, `expires_at`.
- The approval signal must match `call_id` and the argument hash. Different arguments require a new approval.
- Immediately before execution, grants, drift and connection identity are checked again.
- Expiry defaults to 24 hours and is capped by the run's remaining `max_run_duration`. On expiry the call is **denied**, and the step follows its error policy.
- The UI has an Approvals inbox, with optional Slack or Teams notification that links back to the app (no approve-in-chat in v1).

### 9.6 In-app AI builder

- An interactive loop in `api`, streamed over SSE. Each session has time, turn and token limits, and each user is rate-limited. It runs with **the signed-in user's permissions**.
- It uses the internal **tool layer** (`core/tools`), which the external MCP server will later wrap:
  - `search_node_types`, `get_node_type`
  - `find_mist_operation`, `find_mist_setting`
  - `list_connections` (IDs and names only)
  - `get_draft`
  - `propose_changes`, `revise_proposal`
  - `validate_proposal`, `simulate_proposal`
- **It cannot** publish, run anything live, read secrets, or read run data unless the user attaches a sample explicitly.
- **Proposals are separate from the draft.** A `builder_proposals` row is versioned and based on a known draft revision.
  - On acceptance, whole or per-step, the selected changes are applied with compare-and-swap on the draft revision, then the resulting graph is revalidated.
  - A selection that would leave dangling edges or references is rejected with an explanation.
  - The canvas shows proposals as ghost nodes and edges.

## 10. UI/UX

### 10.1 Stack and principles

- **Stack:** React 19, Vite, TypeScript, React Flow, Radix primitives with Tailwind driven by our own design tokens, TanStack Router and Query, and an API client generated from FastAPI's OpenAPI. Our own JSON-Schema form renderer maps `x-widget` to components. The target is WCAG 2.2 AA and a fully keyboard-operable canvas.
- **Visual language:** a precise operations tool, not an AI demo.
  - No gradient washes, glow, glassmorphism, sparkle icons or emoji.
  - Not the default Inter/shadcn look; custom type and colour tokens.
  - AI features use plain verbs ("Describe it", "Propose changes").
  - Colour is used only for meaning: live (orange), simulated (neutral hatched slate; the violet in the mockups is to be replaced), conditional (amber), error.
  - A Claude Design pass defines the tokens before frontend implementation.

### 10.2 Structure

- **Navigation:** tenant switcher, ⌘K palette, and a left rail: Home, Workflows, Runs, Agents, Approvals, Connections, Settings.
- **New workflow:** Describe it (AI builder), From template, or Blank. The trigger is chosen first.
- **Editor:** a free canvas with auto-layout, a minimap and node status badges. Steps are added from **"+" on ports and edges**, and also from a keyboard-accessible **Add step** command (`A`).

### 10.3 Step drawer

- Tabs: **Setup** (required fields only, in schema groups, with defaults), **Options** (advanced), **Test**, plus an error-handling chip.
- **Pill inputs:** press `/` or use **+ Data** to open a searchable upstream tree with types, *always* vs. *conditional* markers, and sample values.
  - Pill details open on keyboard focus + Enter, never on hover alone. They show type, availability, a redacted sample, its source run and connection, the capture timestamp, and a staleness indicator. Sensitive fields are never stored as samples.
- Visual condition builder that generates CEL. A formula mode is available but hidden by default.
- **Mist picker:** Resource → Action from the curated map. Path parameters become labelled fields with live options that also accept pills. The nested-update widget follows §8. "Find a setting" search covers OAS schemas.
- **Message composer:** a single model with live Slack, Teams and Google Chat previews. The JSON view is opt-in.

### 10.4 Test semantics (never ambiguous)

- **Simulate workflow** (top bar) and **Simulate step:** fixture-based.
  - The UI labels it everywhere: "nothing was sent", "results don't prove the live call will succeed".
  - Each step is tagged by data origin: real input / evaluated / fixture / not sent / skipped.
  - Real server-side checks (schema, capabilities, connection scope, references) are listed separately.
- **Run step against Mist…** (live) shows a dialog with the connection, cloud, org and target, where the target was resolved from (with an explicit override), the operation, the retry behaviour, a current → after diff and the exact request body.
  - Single-object writes require a checkbox and typing the target name. Writes to many objects or the whole org require the count plus typing the org name.
  - Results are labelled **Live**.
- **Rule:** "Any endpoint" and editable JSON never bypass server-side capability, scope or schema validation.

### 10.5 Runs

A filterable list. The run detail replays the run on the canvas from `run_steps`, with per-step redacted input and output, attempts, timing and side-effect outcome. **Re-run** starts a new run with the same trigger input; there's no mid-run reset in v1.

## 11. Security operations

- Repository: `SECURITY.md` (private disclosure), a STRIDE threat model per boundary, and CODEOWNERS on `sdk/`, `engine/`, auth and crypto.
- **Supply chain:**
  - Hash-locked uv and pnpm dependencies, Renovate.
  - CodeQL, Semgrep, gitleaks, Trivy, and a license allowlist (Apache-2.0 compatible).
  - CycloneDX SBOM, cosign-signed images with SLSA provenance, distroless non-root images.
- **Web:** a strict CSP with no inline scripts, CSRF protection, security headers, and login and MFA rate limits (§4.2).
- **Keys:** the key-encryption key comes from an environment secret, Vault or a cloud KMS. A rotation job re-wraps tenant data keys.
- **Audit:**
  - `audit_log` is append-only, with a per-scope hash chain.
  - A **same-database chain does not resist a privileged database rewrite**. For tamper evidence, a periodic job anchors the chain head outside the database: a configurable sink (object storage with object lock, a syslog/SIEM, or a signed file export), with anchors recorded in `audit_anchors`.
  - A verification CLI checks the chain against its anchors.
- **Observability:** OpenTelemetry traces and metrics, logs with redaction, and per-tenant usage (runs, Mist calls, LLM tokens and cost).

## 12. Testing strategy

- Engine unit tests use Temporal's time-skipping environment. Property-based tests cover joins, dead-path elimination, execution scopes and reference availability.
- **Replay gate:** each stored history is replayed against **the build it is assigned to**; pinned runs never move builds. Separately, where an upgrade path is explicitly supported (continue-as-new snapshot N−1 → N), snapshot-compatibility tests run.
- RLS tests (missing and mismatched tenant context) and a role × endpoint authorization matrix.
- Plugin contract tests: manifest validation, schema round-trips, `simulate()`, side-effect policy behaviour, `reconcile()`.
- CEL fuzzing against the cost limits, ingress load tests, SSRF tests (DNS rebinding, redirects), and Playwright end-to-end tests.
- Deployment test: an N−1 build drains while N serves new runs (Compose).

## 13. Packaging

- Images: `web`, `app` (entrypoints `api`, `ingress`, `dispatcher`, `cli`) and `worker`.
- **Compose:** a single host with Postgres and Temporal.
- **Helm:** NetworkPolicies, the restricted PodSecurity profile, separate DB roles and secrets per process, worker-build retention until drained, and optional external Temporal (their own cluster or Temporal Cloud).
- Bootstrap: `dewpoint admin init` creates the first platform admin.
- Docs: operator guide, plugin author guide, CONTRIBUTING (DCO), license headers.

## 14. Delivery sub-projects

1. **Foundations:** monorepo, CI and security pipeline, `core` identity (users, local auth, TOTP, passkeys, sessions, CSRF), tenants and memberships, roles and permissions, RLS and DB roles, envelope encryption and `tenant_keys`, generic `connections` (Mist connection type with a verify call), audit log and anchoring, a minimal React shell (login, MFA, tenant switcher, connections page), and Compose.
2. **Engine:** SDK, manifest registry, graph model and validator (including path availability), CEL, the `RunGraph` interpreter, admission (`run_requests`, outbox, dispatcher, slots), triggers (manual with input forms and CSV upload, schedule, webhook ingress), `run_steps` projection, PayloadCodec, claim check, replay tests.
3. **First-party plugins:** flow, Mist (curated map + OAS, nested update), messaging, ITSM.
4. **Editor UI:** design-token pass (Claude Design), canvas, step drawer, pills, simulate vs. live, runs view, Helm.
5. **AI:** LLM connections, agent library, `AgentLoop`, service grants, approvals inbox, MCP client with pinning, the tool layer and the in-app builder.

After v1: the external MCP server (wrapping `core/tools` with `api_tokens`), agent memory, `worker-sandbox` with a credential broker for third-party plugins, the declarative OpenAPI connector, and a provider (MSP) level.

## 15. Open items to resolve during sub-project planning

- ~~CEL implementation choice (spike in sub-project 2).~~ Resolved: engine-core spec §5.
- Default values for the Temporal namespace retention period, per-tenant concurrency and the Mist rate buckets.
- Destinations for the audit anchor sink shipped in v1 (at least one, in sub-project 1).
- The curated Mist resource/action map: an initial resource list, agreed in sub-project 3.
