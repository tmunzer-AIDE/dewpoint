# SPDX-License-Identifier: Apache-2.0
"""The answers of the routes the web client uses, as models: they name each shape in the OpenAPI schema the client is
generated from (sub-project 4, B1). Each forbids extra keys, so an answer that drifts from its model fails its tests
instead of silently losing a field. A route whose answer omits a key (a tenant's `role`, a connection type's
`clouds`) uses `response_model_exclude_unset`, so the JSON stays exactly what it was."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

SessionState = Literal["mfa_pending", "enroll_required", "active"]
Role = Literal["owner", "admin", "editor", "operator", "viewer"]


class _Answer(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StateOut(_Answer):
    state: SessionState
    csrf_token: str


class CsrfOut(_Answer):
    csrf_token: str


class SessionUserOut(_Answer):
    id: str
    email: str
    is_platform_admin: bool


class SessionOut(_Answer):
    user: SessionUserOut
    state: SessionState
    auth_methods: list[str]
    csrf_token: str


class TotpEnrollOut(_Answer):
    otpauth_uri: str


class RecoveryCodesOut(_Answer):
    recovery_codes: list[str]
    state: SessionState
    csrf_token: str


class PasskeyOut(_Answer):
    id: str
    name: str
    created_at: str
    last_used_at: str | None


class PasskeyOptionsOut(_Answer):
    options: dict[str, Any]  # WebAuthn's own options, passed to the browser as they are
    challenge_id: str


class TenantOut(_Answer):
    id: str
    name: str
    slug: str
    require_passkey: bool
    role: Role | None = None  # absent where the caller holds no role


class MemberOut(_Answer):
    user_id: str
    email: str
    role: Role


class MemberRoleOut(_Answer):
    user_id: str
    role: Role


class ConnectionTypeOut(_Answer):
    key: str
    label: str
    config_schema: dict[str, Any]
    secret_fields: list[str]
    clouds: dict[str, str] | None = None  # Mist's clouds, by key; absent for other types


class ConnectionOut(_Answer):
    id: str
    type: str
    name: str
    revision: int
    config: dict[str, Any]
    secret_set: bool
    status: Literal["unverified", "ok", "error"]
    status_detail: str
    privilege: str | None
    last_verified_at: str | None


class CooldownOut(_Answer):
    scope: str
    until: str


class ConnectionDetailOut(ConnectionOut):
    """One connection, with each of its quota scopes now cooling down (plugins-3 D10); null when they can't be
    computed (an unreadable secret)."""

    cooldowns: list[CooldownOut] | None


class PlatformStatusOut(_Answer):
    environment: Literal["production", "development"] | None
    production_runs: bool


SideEffect = Literal["none", "idempotent", "keyed", "reconcilable", "ambiguous"]


class RetryOut(_Answer):
    max_attempts: int
    initial_interval_s: float
    backoff: float
    max_interval_s: float
    non_retryable: list[str]


class NodeTypeOut(_Answer):
    """A node type the editor may place (active) or still draws (deprecated), and how a step of it runs (B5): what it
    may change, the connection types it takes, what it may reach, and its retry and timeout defaults."""

    ref: str
    type: str
    version: int
    kind: Literal["action", "control"]
    state: Literal["active", "deprecated"]
    title: str
    description: str
    icon: str | None  # a first-party icon's name (plugins-3), never a URL or markup
    ports: list[str]
    dynamic_ports: str | None  # a config field whose entries each declare a `port` (flow.switch's "cases")
    config_schema: dict[str, Any]
    output_schema: dict[str, Any]
    options: list[str]  # the config fields whose choices the node's options() lists (plugins-3 D3)
    side_effect: SideEffect
    credentials: list[str]
    capabilities: list[str]
    retry: RetryOut
    timeout_s: float


class DiagnosticOut(_Answer):
    """A problem with a graph: `node` is a node's id, or null for the workflow; `field` is a JSON pointer inside the
    node's config, `/settings/...` for the workflow's, or into the whole document for `graph.format`."""

    code: str
    message: str
    node: str | None
    field: str | None
    fix: str | None
    severity: Literal["error", "warning"]


class LastRunOut(_Answer):
    status: Literal["running", "succeeded", "failed", "cancelled", "deadline_exceeded"]
    at: str  # when it ended, else started, else was queued


class RunCountOut(_Answer):
    live: int
    simulate: int


class WorkflowOut(_Answer):
    id: str
    name: str
    enabled: bool
    draft_revision: int
    active_version_id: str | None
    active_version_number: int | None
    executable: bool | None  # null when nothing is published
    blocked_by: list[str]  # the lifecycle entries that keep the active version from running
    created_at: str
    updated_at: str
    unpublished_changes: bool  # the draft differs from the active version (true when nothing is published)
    draft_graph_hash: str | None  # the draft's graph hash as publish would record it; null when it doesn't parse
    last_run: LastRunOut | None  # its last live root run: what attention follows
    last_simulation: LastRunOut | None  # its last simulated root run, shown apart, never attention
    runs_24h: RunCountOut  # its root runs queued in the last 24 hours, live and simulated apart
    needs_attention: list[Literal["last_run_failed", "not_executable"]]


class WorkflowDetailOut(WorkflowOut):
    draft: dict[str, Any]  # verbatim, as saved; the schema documents it as a Graph (openapi.refine)


class WorkflowUpdatedOut(WorkflowOut):
    warnings: list[DiagnosticOut]


class DraftSavedOut(_Answer):
    draft_revision: int
    unpublished_changes: bool  # against `active_version_*`, the version active when the save landed
    graph_hash: str | None  # the saved draft's, as publish would record it
    active_version_id: str | None
    active_version_number: int | None


class ExpressionOut(_Answer):
    """How one CEL value runs (engine-core §5.10): "local" inline, "activity" as a separate step, with why."""

    node: str | None  # null for a workflow output
    field: str
    mode: Literal["local", "activity"]
    reason: str | None


class TaintSiteOut(_Answer):
    node: str | None  # null for a workflow output
    field: str


class DeclassifiedOut(_Answer):
    node: str
    field: str
    reveals: str


class TaintOut(_Answer):
    sites: list[TaintSiteOut]
    declassified: list[DeclassifiedOut]


class ValidationOut(_Answer):
    """The saved draft's diagnostics, at the revision they were computed for: an editor shows an answer for an older
    revision as stale, never as current (D17; 4b ruling 24)."""

    draft_revision: int
    valid: bool
    diagnostics: list[DiagnosticOut]
    expressions: list[ExpressionOut]
    taint: TaintOut
    conditional_steps: list[str]  # the steps that may not run, by id (4c-2a ruling 3; ledger ruling 70's badge)


class GuardOut(_Answer):
    """A test a formula makes before it reads a path (4c-2a ruling 6). `size`, for `min_size`: the list's size must
    exceed it."""

    kind: Literal["present", "not_null", "is_map", "is_list", "min_size"]
    path: str
    size: int | None


class FormulaUseOut(_Answer):
    guards: list[GuardOut]
    sensitive: bool  # a formula reading it, with its guards, reads sensitive data (4c-2a ruling 7)
    null_test: bool  # "is there" also tests `!= null`: it may be null, is untyped, or is only null (ruling 6)


class ScopeEntryOut(_Answer):
    path: str
    parent: str | None
    name: str
    root: Literal["trigger", "steps", "vars", "item", "index", "loops", "run"]
    step: str | None
    types: list[Literal["string", "integer", "number", "boolean", "array", "object", "null"]]  # none: any value
    format: str | None
    missing: bool
    nullable: bool
    sensitive: bool
    nameable: bool  # false: a key a reference can't name, shown disabled
    children: bool
    formula: FormulaUseOut | None  # null: CEL can't select one of its fields, or `problem` refuses the read
    problem: DiagnosticOut | None  # why reading it here is refused, as validation says it (`vars.unassigned`)


class ScopeOut(_Answer):
    """What one field of the saved draft's step can read (B6), at the revision it was computed for: an editor drops an
    answer for an older revision (D17)."""

    draft_revision: int
    node: str
    field: str
    state: Literal["ok", "unavailable"]
    reason: str | None
    entries: list[ScopeEntryOut]
    more: bool
    problem: DiagnosticOut | None


class PublishedOut(_Answer):
    version_id: str
    number: int
    warnings: list[DiagnosticOut]


class VersionOut(_Answer):
    id: str
    number: int
    published_at: str
    published_by: str | None
    graph_hash: str
    version_hash: str
    cel_profile: str
    engine_abi: int
    node_refs: list[str]
    active: bool
    executable: bool
    blocked_by: list[str]


class VersionDetailOut(VersionOut):
    """One version whole (B4a): its graph, verbatim as published (documented as a Graph), and how each of its
    expressions runs."""

    graph: dict[str, Any]
    expressions: list[ExpressionOut]


BINDING_ID = r"^[a-z][a-z0-9_]{0,31}$"
# Far above anything an export makes (500 steps, a config's top-level properties), and a bound on an import's work
# beside the 1 MiB body cap.
MAX_BINDINGS = 10_000


class BindingSite(_Answer):
    node: str | None = Field(max_length=64)  # a step's id; null for the workflow's settings
    field: str = Field(min_length=2, max_length=200)  # `/<property>`, or `/settings/failure_handler`


class Binding(_Answer):
    """One id of the exporting tenant's (a connection, a workflow), as a placeholder an import binds or leaves."""

    id: str = Field(pattern=BINDING_ID)
    kind: Literal["connection", "workflow"]
    type: str | None = Field(max_length=100)  # the connection type it takes; null for a workflow
    label: str = Field(max_length=200)
    sites: list[BindingSite] = Field(min_length=1, max_length=MAX_BINDINGS)


class WorkflowDocument(_Answer):
    """A workflow as a file (B12): its graph without the tenant's ids (documented as a Graph), and their bindings."""

    format: Literal["dewpoint.workflow"]
    format_version: Literal[1]
    name: str = Field(max_length=100)
    graph: dict[str, Any]
    bindings: list[Binding] = Field(max_length=MAX_BINDINGS)


class ActivatedOut(_Answer):
    active_version_id: str
    number: int
    warnings: list[DiagnosticOut]


class OptionOut(_Answer):
    value: str
    label: str


class OptionsOut(_Answer):
    """A node's options, from its `options()` on a worker (plugins-3 D3), for the editor or a start form's picker."""

    options: list[OptionOut]


class TriggerEndpointOut(_Answer):
    auth: Literal["bearer", "hmac"]
    events_pointer: str | None
    id_source: Literal["none"]


class TriggerTypeOut(_Answer):
    """A trigger a synced plugin declares (plugins-3 D17): how its webhook endpoint is set up, where an event names its
    topic, and each topic's event schema, which types a workflow's trigger."""

    plugin: str
    key: str
    label: str
    endpoint: TriggerEndpointOut
    topic_pointer: str
    topics: dict[str, dict[str, Any]]
