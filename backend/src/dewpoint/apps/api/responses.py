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
    id: str  # its page's (editor 4e-1; the runs design §4.5)
    status: Literal["running", "succeeded", "failed", "cancelled", "deadline_exceeded"]
    at: str  # when it ended, else started, else was queued


class RunCountOut(_Answer):
    live: int
    simulate: int


class TriggersOut(_Answer):
    """What starts a workflow besides a person (4c-3a ruling 3): by hand is always possible once it's published."""

    schedules: int  # its live schedules: a deleted one's tombstone left out
    schedules_enabled: int
    webhook_bindings: int
    csv: bool  # its active version takes a CSV file: it's started by hand, with one


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
    triggers: TriggersOut
    needs_attention: list[Literal["last_run_failed", "not_executable", "schedule_sync_failed"]]


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


class ScheduleBreakOut(_Answer):
    """A live schedule the draft, published, would make fail at every firing (4c-3a ruling 7): why, by its stored
    input's shape, in the draft's own words; never what the input holds."""

    schedule_id: str
    reasons: list[str]  # at most 5, each of 300 characters at most
    more: bool  # the check stopped at its budget with more to say about this one


class ValidationOut(_Answer):
    """The saved draft's diagnostics, at the revision they were computed for: an editor shows an answer for an older
    revision as stale, never as current (D17; 4b ruling 24)."""

    draft_revision: int
    valid: bool
    diagnostics: list[DiagnosticOut]
    expressions: list[ExpressionOut]
    taint: TaintOut
    conditional_steps: list[str]  # the steps that may not run, by id (4c-2a ruling 3; ledger ruling 70's badge)
    schedule_breaks: list[ScheduleBreakOut]  # the live schedules it would break, published, the oldest first


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


class SampleConnectionOut(_Answer):
    connection_id: str
    type: str
    name: str  # its name now, or as recorded when it's gone
    revision: int  # as the attempt used it
    current_revision: int | None
    state: Literal["unchanged", "changed", "deleted"]
    context: dict[str, Any]  # its non-secret config, as it was


class SampleConnectionsOut(_Answer):
    """What the sample's attempt used: `recorded` (each one, as it was and as it is now), `none` (the step names
    none), `simulated` (a simulation opens none) or `unknown` (it names one, but the run predates records)."""

    state: Literal["recorded", "none", "simulated", "unknown"]
    items: list[SampleConnectionOut]


class SampleOut(_Answer):
    run_id: str
    run_kind: Literal["run", "subflow", "failure_handler"]
    mode: Literal["live", "simulate"]
    version_id: str
    version_number: int
    iteration_key: str
    attempt: int
    captured_at: str | None
    type: str | None  # the step's type@version in that version
    same_type: bool
    same_config: bool
    output: Any  # the stored preview, `[redacted]` and `[truncated]` where they were (D20)
    connections: SampleConnectionsOut
    stale: bool  # its type, config or a connection differs from the draft's now


class SamplesOut(_Answer):
    """A step's newest sample (B7), against the saved draft at this revision."""

    draft_revision: int
    node: str
    sample: SampleOut | None
    searched_runs: int  # the ended runs looked in: no sample means none there, not "never" (4c-2a ruling 9)
    search_limit: int


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


class UncountedOut(_Answer):
    """A span of a schedule's life whose missed firings aren't counted (D3f): possibly missed, unknown, or pending
    until its count is read. `from` and `class` are Python keywords, so the fields are aliased to them."""

    from_: str = Field(alias="from")
    to: str | None  # null while it's open
    class_: Literal["possibly_missed", "unknown", "pending"] = Field(alias="class")
    reason: str


class ScheduleOut(_Answer):
    """A schedule (engine 2b spec §8.2), never its input; its sync's state and its missed-firing accounting (D3f)."""

    id: str
    workflow_id: str
    cron: str | None  # a cron, or
    every_s: int | None  # an interval, with its offset
    offset_s: int
    time_zone: str  # a cron's; an interval has none
    catchup_window_s: int
    mode: Literal["live", "simulate"]
    enabled: bool
    generation: int  # raised by every change
    synced_generation: int  # the last the sync confirmed; 0 before its first
    misses: int
    missed_while_created: int
    misses_read_at: str | None
    accounting_complete: bool
    uncounted_intervals: list[UncountedOut]
    sync_error: str | None  # `temporal_refused` or `sync_failed`: its last sync failed, retried after a minute
    sync_error_at: str | None  # when (4c-3a ruling 6)
    never_unpaused: bool  # nothing ever unpaused it: it never fired (4c-3a ruling 6)
    created_at: str
    updated_at: str


class SchedulesOut(_Answer):
    schedules: list[ScheduleOut]


class EndpointOut(_Answer):
    """A webhook endpoint (engine 2b spec §8.3), never its secret, its digest or its dedupe key. `path` is relative:
    its URL is this path on the deployment's webhook address."""

    id: str
    name: str
    enabled: bool
    auth: Literal["bearer", "hmac"]
    signature_header: str | None
    timestamp_header: str | None
    tolerance_s: int
    allowlist: list[str]
    body_limit: int
    id_source: Literal["pointer", "header", "none"]
    id_pointer: str | None
    id_header: str | None
    events_pointer: str | None
    trigger: str | None  # the trigger type it was made for; null: another sender (4c-3a ruling 1)
    path: str
    pending_events: int
    pending_bytes: int
    retained_events: int
    retained_bytes: int
    created_at: str | None


class EndpointCreatedOut(EndpointOut):
    secret: str  # shown this once


class EndpointsOut(_Answer):
    endpoints: list[EndpointOut]


class SecretOut(_Answer):
    id: str
    secret: str  # shown this once


class FilterClauseOut(_Answer):
    pointer: str
    value: str | int | bool | None  # typed: `1`, `true` and `"1"` are three values


class WebhookBindingOut(_Answer):
    id: str
    endpoint_id: str
    workflow_id: str
    filter: list[FilterClauseOut]  # all must hold; none: every event
    enabled: bool


class WebhookBindingsOut(_Answer):
    bindings: list[WebhookBindingOut]


class BindingEndpointOut(_Answer):
    """What a workflow's Triggers panel shows of a binding's endpoint (B13; 4c-3a ruling 2)."""

    id: str
    name: str
    enabled: bool
    auth: Literal["bearer", "hmac"]
    path: str
    trigger: str | None


class WorkflowBindingOut(WebhookBindingOut):
    endpoint: BindingEndpointOut


class WorkflowBindingsOut(_Answer):
    bindings: list[WorkflowBindingOut]


class PickerListOut(_Answer):
    """The list a picker's choices come from, in words (the 4f-3 design §4.4): "Mist", "Org sites", "sites"."""

    plugin: str
    title: str
    noun: str


class PickerOut(_Answer):
    """A start form's picker (plugins-3 D19): its node's options field through a connection, and the list's words
    (null when this server doesn't hold the node type)."""

    node: str
    field: str
    connection: str
    list: PickerListOut | None


class StartFieldOut(_Answer):
    """A start form's field (engine 2b spec §7.7). A key it doesn't have is left out of the answer (the route excludes
    what's unset): a sensitive field's default and enum are masked, never sent."""

    name: str
    type: Any  # its schema's `type`: a name, a list of names, or none
    required: bool
    sensitive: bool
    title: str | None = None
    description: str | None = None
    enum: list[Any] | None = None
    default: Any = None
    default_masked: bool | None = None
    enum_masked: bool | None = None
    picker: PickerOut | None = None


class CsvColumnFormOut(_Answer):
    header: str
    name: str
    type: str
    required: bool
    sensitive: bool
    default: Any = None  # left out unless declared
    values: list[str] | None = None  # a choice's; left out otherwise


class CsvFormOut(_Answer):
    max_rows: int
    max_bytes: int
    columns: list[CsvColumnFormOut]


class StartFormOut(_Answer):
    """The active version's input, as a form: what a schedule's input is entered on (4c-3a ruling 5), and the run
    form's (the run form design §4.2): the version it names, and who published it, null once they're gone."""

    workflow_id: str
    version_id: str
    version_number: int
    published_at: str
    published_by: str | None
    fields: list[StartFieldOut]
    csv: CsvFormOut | None


class SimulationOut(_Answer):
    """A draft simulation's request (B8; the simulation design §6.3): frozen on its draft snapshot, at the revision it
    was admitted at, with the step it runs alone (S2) and what admission reported without refusing. Never its input."""

    id: str
    workflow_id: str
    version_id: None
    draft_snapshot_id: str
    draft_revision: int
    target_step_id: str | None
    mode: Literal["simulate"]
    source: str
    status: Literal["queued", "starting", "started", "cancelled", "refused", "dead"]
    reason: str | None
    queued_at: str | None
    ended_at: str | None
    admission_checks: list[DiagnosticOut]


class DraftSnapshotOut(_Answer):
    """A draft simulation's snapshot whole (B8; the simulation design §6.5): what B4a's version read is for a version,
    its graph verbatim as frozen (documented as a Graph), and how each of its expressions runs."""

    id: str
    workflow_id: str
    draft_revision: int
    created_at: str
    graph_hash: str
    version_hash: str
    cel_profile: str
    engine_abi: int
    node_refs: list[str]
    graph: dict[str, Any]
    expressions: list[ExpressionOut]


class SimulationRunOut(_Answer):
    """A draft simulation's run, once dispatch wrote it (B8): its own state."""

    status: Literal["running", "succeeded", "failed", "cancelled", "deadline_exceeded"]
    queued_at: str | None
    started_at: str | None
    ended_at: str | None
    error: dict[str, Any] | None  # {code, message}
    iterations: int


class SimulationStateOut(_Answer):
    """A draft simulation where it is (B8; the simulation design §6.6): its request, its run once there is one,
    whether a cancel was requested, and what it ran with, read back from its own request, redacted (`[redacted]` in
    place of what its envelope holds as claims), never recomputed from the draft as it is now: its `input`, or a step
    test's `seeds` (S2)."""

    request: SimulationOut
    run: SimulationRunOut | None
    cancel_requested: bool
    read_back: Literal["kept", "absent", "unreadable"]  # unreadable: there, but it doesn't open (never shown as absent)
    input: dict[str, Any] | None
    seeds: dict[str, Any] | None


class StepSummaryOut(_Answer):
    """A step of the draft a simulation ran (B8; the simulation design §6.6): its instances' final attempts counted by
    status and by the port they took, a single instance's final attempt, and where its data came from (§7.4)."""

    step_id: str
    key: str
    type: str
    origin: Literal[
        "evaluated", "evaluated_not_waited", "fixture_not_sent", "skipped", "not_started", "cancelled", "didnt_run",
        "not_recorded", "not_reached_yet",
    ]  # fmt: skip
    instances: int
    statuses: dict[str, int]
    ports: dict[str, int]
    final: dict[str, Any] | None  # the run API's step: a single instance's final attempt


class SimulationStepsOut(_Answer):
    """A draft simulation's steps in run order (§6.6), and what the values a person gave were (§7.4): the workflow's
    input, or a step test's seeds. A step test lists its target alone: the other steps are outside the test."""

    given: Literal["input", "seeded"]
    steps: list[StepSummaryOut]


class StepInstancesOut(_Answer):
    """A step's instances in a draft simulation, one per iteration, each its final attempt (the run API's step), in
    iteration order (§6.6): a page of them, and their total."""

    total: int
    items: list[dict[str, Any]]


class DraftStartFormOut(_Answer):
    """The draft's input as a form, at its revision (B8; the simulation design §7.1): `start-form`'s fields and CSV
    declaration, for a draft that may never have been published. A draft declaring a CSV can't be simulated whole."""

    workflow_id: str
    draft_revision: int
    fields: list[StartFieldOut]
    csv: CsvFormOut | None


class SeedPrefillOut(_Answer):
    """A seed's value from its step's own sample (D-s2), or why the person types it."""

    state: Literal["prefilled", "typed"]
    value: Any  # the sample's, when prefilled (null may be one)
    reason: Literal["sensitive", "not_step_output", "no_sample", "not_faithful", "not_in_sample", "doesnt_fit"] | None


class SeedEntryOut(_Answer):
    """One value the step reads (§5.2): its pointer, the JSON types it may have (none listed: any value), whether it's
    required (else it may be absent), whether null is taken, and whether it's sensitive (typed and masked)."""

    pointer: str
    types: list[str]
    required: bool
    nullable: bool
    sensitive: bool
    prefill: SeedPrefillOut


class SeedContractOut(_Answer):
    """A step's seed contract at the draft's revision (§5.2, §6.6), or why the step can't run alone."""

    draft_revision: int
    step_id: str
    refused: str | None
    entries: list[SeedEntryOut]


RunStatus = Literal[
    "queued", "starting", "running", "succeeded", "failed", "cancelled", "deadline_exceeded", "refused", "dead"
]
Source = Literal["manual", "rerun", "schedule", "webhook", "dev"]


class RunErrorOut(_Answer):
    code: str
    message: str | None


class RunRequestStateOut(_Answer):
    """A run's request where it is (engine 2b spec §7.3): started, or why it isn't."""

    status: Literal["queued", "starting", "started", "cancelled", "refused", "dead"]
    source: Source
    reason: str | None


class ScheduleTimingOut(_Answer):
    """A schedule's timing as it is now, which the UI words as the Triggers panel does (4c-3b)."""

    cron: str | None
    every_s: int | None
    offset_s: int
    time_zone: str


class RunTriggerOut(_Answer):
    """Where a run's request came from (editor 4e-1; the runs design §4.2): its source, and the schedule or webhook
    endpoint, or the run a re-run repeats. Null where the request predates migration 0073, or the schedule or endpoint
    was deleted."""

    source: Source
    schedule: ScheduleTimingOut | None
    endpoint: str | None  # the webhook endpoint's name
    rerun_of: str | None


class RunItemOut(_Answer):
    """An item of the runs list (engine 2b spec §7.7; editor 4e-1, B10): a top-level run, or a request that hasn't
    started, as its request. `status` is the run's once its request started, else the request's."""

    id: str
    workflow_id: str
    workflow_name: str | None
    version_id: str | None
    draft_snapshot_id: str | None  # a draft simulation's (B8): no version
    target_step_id: str | None
    mode: Literal["live", "simulate"]
    status: RunStatus
    queued_at: str | None
    started_at: str | None
    ended_at: str | None
    error: RunErrorOut | None
    iterations: int
    kind: str
    parent_run_id: str | None
    request: RunRequestStateOut | None  # null for a run from before 2b-2, which had no request
    started_by: str | None  # the email of the person who asked: by hand, or a re-run
    cancel_requested_at: str | None
    trigger: RunTriggerOut | None


class RunStepOut(_Answer):
    """One attempt of a step instance (engine spec §8; B4b): where it ran (its iteration), how it ended, its previews
    (redacted and cut as the projection stores them: `[redacted]`, `[truncated]`), its error, its side effect's outcome,
    a control step's port or assignments, and the sub-run it started, when it did."""

    step_id: str
    key: str
    iteration_key: str
    attempt: int
    status: Literal["running", "succeeded", "failed", "cancelled", "skipped", "not_started"]
    started_at: str | None
    ended_at: str | None
    input: Any
    output: Any
    error: RunErrorOut | None
    outcome: Literal["applied", "simulated", "outcome_unknown"] | None
    cel_mode: str | None
    effect: Any
    child_run_id: str | None = None


class RunStepSummaryOut(_Answer):
    """A step of the graph a run ran (the runs design §4.4): its instances' final attempts counted by status and by the
    port they took, a single instance's final attempt, and where its data came from: in a live run, `sent` or
    `may_have_been_sent` for a plugin step's request, null when there's nothing to say."""

    step_id: str
    key: str
    type: str
    origin: Literal[
        "sent", "may_have_been_sent", "evaluated", "evaluated_not_waited", "fixture_not_sent", "skipped",
        "not_started", "cancelled", "didnt_run", "not_recorded", "not_reached_yet",
    ] | None  # fmt: skip
    instances: int
    statuses: dict[str, int]
    ports: dict[str, int]
    final: RunStepOut | None


class RunStepsOut(_Answer):
    """A run's steps in run order (§4.4), and what the values a person gave were: the workflow's input, or a step
    test's seeds. A step test lists its target alone."""

    given: Literal["input", "seeded"]
    steps: list[RunStepSummaryOut]


class RunInstancesOut(_Answer):
    """A step's instances in a run, one per iteration, each its final attempt, in iteration order: a page, and their
    total."""

    total: int
    items: list[RunStepOut]


class RunAttemptsOut(_Answer):
    """One step instance's attempts, first to last."""

    items: list[RunStepOut]


class CsvSkippedOut(_Answer):
    row: int  # the record's number: 1 is the first after the header
    code: str  # the first rule it broke


class CsvErrorOut(_Answer):
    row: int
    column: str | None  # the declared column's name; null for the record as a whole
    code: str


class CsvProblemOut(_Answer):
    column: str  # the declared column's name
    code: str  # what keeps the mapping from building rows


class CsvPreviewRowOut(_Answer):
    row: int
    cells: dict[str, str]  # the file's cells as written, under the mapping; never a sensitive column's


class CsvErrorGroupOut(_Answer):
    column: str | None  # null for the record as a whole
    code: str
    count: int
    rows: list[int]  # the first five records that broke it


class CsvPreviewOut(_Answer):
    """A staged CSV described under a mapping, against the active version's declaration (engine 2b spec §8.1; the run
    form design §4.3, §4.4): what keeps the mapping from building rows, the first records' cells, the first 100 errors
    in detail, and every error counted by column and code."""

    version_id: str  # the version whose declaration it was checked against
    mapping: dict[str, str]
    problems: list[CsvProblemOut]
    masked_columns: list[str]
    preview: list[CsvPreviewRowOut]
    errors: list[CsvErrorOut]
    error_count: int
    error_groups: list[CsvErrorGroupOut]
    rows_with_errors: int


class CsvDefaultMappingOut(_Answer):
    status: Literal["none", "applied", "stale"]
    problems: list[CsvProblemOut] | None = None  # a stale one's, left out otherwise


class CsvUploadOut(CsvPreviewOut):
    """A staged upload (engine 2b spec §8.1): its id and hour, the file's headers and records, the mapping proposed
    (the saved default, else the exact matches), and the file described under it."""

    upload_id: str
    expires_at: str
    headers: list[str]
    row_count: int
    default_mapping: CsvDefaultMappingOut


class CsvMappingOut(_Answer):
    """A workflow's saved default mapping, and the version it was checked against."""

    mapping: dict[str, str]
    version_id: str


class CsvRecordOut(_Answer):
    """A CSV start's file as admission read it (engine 2b spec §8.1): the mapping from declared columns to its headers,
    the rows run, every skipped row, and the first errors in detail with their count."""

    mapping: dict[str, str]
    headers: list[str]
    row_count: int
    skipped: list[CsvSkippedOut]
    errors: list[CsvErrorOut]
    error_count: int


class RunParentOut(_Answer):
    """The run a sub-run's step started it from (its sub-flow or failure handler)."""

    run_id: str
    step_id: str | None
    iteration_key: str | None


class RunOut(RunItemOut):
    """A run, or a request that hasn't started, as itself (editor 4e-1; the runs design §4.3, §4.5): the list item's
    facts, the draft revision a draft simulation ran, whether every step instance's end is recorded (its graph's engine
    ABI is B4b's or later), the run that started a sub-run, and a CSV start's file. Its steps are read apart, summarized
    and paged (§4.4)."""

    draft_revision: int | None
    outcomes_recorded: bool
    parent: RunParentOut | None
    csv: CsvRecordOut | None


class RequestOut(_Answer):
    """A run's request as the API shows it (engine 2b spec §7.2): its state and its frozen version, never its input."""

    id: str
    workflow_id: str
    version_id: str | None
    draft_snapshot_id: str | None
    target_step_id: str | None
    mode: Literal["live", "simulate"]
    source: Source
    status: Literal["queued", "starting", "started", "cancelled", "refused", "dead"]
    reason: str | None
    queued_at: str | None
    ended_at: str | None


class CancelOut(_Answer):
    """A cancel (engine 2b spec §7.4): `cancelled` (200), the request hadn't started; `requested` (202), recorded for
    the dispatcher to apply."""

    cancel: Literal["cancelled", "requested"]
    request: RequestOut


class RunInputOut(_Answer):
    """What a run was admitted with, read back from its request's own envelope, redacted (the runs design §4.3): its
    `input`, or a step test's `seeds`. `absent`: the request kept none (a refusal admission never froze, or a run from
    before 2b-2); `unreadable`: there, but it doesn't open (a broken ciphertext, or the tenant's key gone during an
    erasure). A CSV start's rows are its CSV record's, never repeated here."""

    read_back: Literal["kept", "absent", "unreadable"]
    input: dict[str, Any] | None
    seeds: dict[str, Any] | None
