# SPDX-License-Identifier: Apache-2.0
"""ServiceNow (plugins-3 3d-2, D22): incidents through the Table API.

The connection names the instance, `https://` and its host (its `service-now.com` name or a custom URL), and holds a
REST API key, which the runtime sends as the `x-sn-apikey` header: the plugin never holds it. ServiceNow calls basic
auth legacy and restricts it on new instances; its OAuth client credentials are off by default. The key's user's roles
decide what a node may do (itil creates and resolves incidents). Requests go to `/api/now/v2/table/incident`: version
2 answers a query matching nothing with 200 and an empty list. One quota scope a key on an instance: bursts of 10,
then 2 a second; an instance's own hourly rules answer 429 with a `Retry-After`. Verify reads one incident."""

import re
import uuid
from datetime import timedelta
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator

from dewpoint.sdk import (
    CallContext,
    Connection,
    ConnectionType,
    FatalError,
    HeaderAuth,
    HttpResponse,
    Node,
    Plugin,
    RateScope,
    RetryableError,
    RetryDefaults,
    SideEffect,
    StepContext,
    TransportError,
    UrlField,
    VerifyResult,
    connection_field,
)
from dewpoint.sdk.connections import HOST_RE
from dewpoint.sdk.messages import MARK, Message, Severity

TABLE = "/api/now/v2/table/incident"
JSON = {"Accept": "application/json"}
FIELDS = "sys_id,number,correlation_id"  # what an answer carries back
KEY_TEXT = re.compile(r"[\x21-\x7e]{16,1024}")  # a key's format isn't documented: printable ASCII, no space
SYS_ID = re.compile(r"[0-9a-f]{32}")  # the form every documented example shows; no page states it
NUMBER = re.compile(r"[\x21-\x7e]{1,40}")
STATE = re.compile(r"[0-9]{1,4}")  # a state's raw value: the instance's choice list numbers them
CORRELATION = re.compile(r"[A-Za-z0-9._:-]{1,100}")  # no query syntax: escaping a value isn't documented
# What a one-line value turns into a space: CR LF, a line break of any kind, any other control character.
CONTROLS = re.compile(r"\r\n|[\x00-\x1f\x7f-\x9f\u2028\u2029]")
SHORT_MAX, LONG_MAX = 160, 4000  # the task fields' documented lengths (the Case API): short_description, description
LEVELS = {Severity.CRITICAL: "1", Severity.WARNING: "2", Severity.INFO: "3", Severity.SUCCESS: "3"}
RETRY = RetryDefaults(max_attempts=4, initial_interval=timedelta(seconds=5), backoff=2.0,
                      max_interval=timedelta(seconds=20))  # fmt: skip
SIMULATED_ID, SIMULATED_NUMBER = "0" * 32, "INC0000000"  # a simulation's fixture: nothing was created
REFUSALS = {
    400: ("servicenow.invalid_request", "ServiceNow refused the request as invalid."),
    401: ("servicenow.unauthorized", "ServiceNow refused the API key."),
    403: ("servicenow.forbidden", "The key's user may not do this: an ACL, a business rule or a data policy."),
    404: ("servicenow.not_found", "ServiceNow has no such record, or the key's user can't see it."),
}


class ServiceNowConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    instance_url: str = Field(max_length=261, title="Instance URL",
                              description="https:// and its host, e.g. https://acme.service-now.com")  # fmt: skip

    @field_validator("instance_url")
    @classmethod
    def _instance(cls, value: str) -> str:
        scheme, _, host = value.partition("://")
        if scheme != "https" or not HOST_RE.fullmatch(host) or _numeric(host):
            raise ValueError("https:// and a lowercase host name, no port, no path")
        return value


def _numeric(host: str) -> bool:
    """An IPv4 address passes the host pattern: an instance has a name."""
    return all(label.isdigit() for label in host.split("."))


class ServiceNowSecret(BaseModel):
    model_config = ConfigDict(extra="forbid")
    api_key: SecretStr = Field(title="REST API key", description="The token of a REST API Key record.")

    @field_validator("api_key")
    @classmethod
    def _key(cls, value: SecretStr) -> SecretStr:
        if not KEY_TEXT.fullmatch(value.get_secret_value()):
            raise ValueError("16 to 1,024 printable ASCII characters, no space")
        return value


async def verify(ctx: CallContext, connection: Connection) -> VerifyResult:
    """Reads one incident: the key opens the Table API and its user may read incidents."""
    try:
        answer = await connection.http.request("GET", TABLE, params={"sysparm_limit": "1", "sysparm_fields": "sys_id"})
    except TransportError:
        return VerifyResult(False, "unreachable")
    if answer.status_code == 200:
        return VerifyResult(True, "ok")
    if answer.status_code == 401:
        return VerifyResult(False, "invalid_key")
    if answer.status_code == 403:
        return VerifyResult(False, "no_table_access")
    return VerifyResult(False, "unexpected_status")


SCOPE = RateScope("servicenow.key", config=("instance_url",), secret="api_key", capacity=10, refill_per_s=2)  # noqa: S106 - a field


SERVICENOW = ConnectionType(
    key="servicenow",
    label="ServiceNow",
    Config=ServiceNowConfig,
    Secret=ServiceNowSecret,
    auth=HeaderAuth("x-sn-apikey", "{api_key}"),
    host=UrlField("instance_url"),
    rate_scopes=(SCOPE,),
    verify=verify,
)


def _units(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def cut16(text: str, limit: int) -> tuple[str, bool]:
    """`text` within `limit` UTF-16 units (Java's count, never more than the characters'), ending with `MARK` when it
    had to be cut; whether it was."""
    if _units(text) <= limit:
        return text, False
    budget, size, kept = limit - _units(MARK), 0, []
    for char in text:
        size += _units(char)
        if size > budget:
            break
        kept.append(char)
    return "".join(kept) + MARK, True


def _sys_id(value: str | None) -> str | None:
    if value is not None and not SYS_ID.fullmatch(value):
        raise ValueError("a sys_id: 32 lowercase hex characters")
    return value


def _line(value: str | None) -> str | None:
    if value is not None and CONTROLS.search(value):
        raise ValueError("one line")
    return value


def _answered(answer: HttpResponse, expected: int) -> None:
    status = answer.status_code
    if status == expected:
        return
    if status in REFUSALS:
        raise FatalError(*REFUSALS[status])
    if status in (408, 425) or status >= 500:  # a timeout or a too-early request is transient (RFC 9110, RFC 8470)
        raise RetryableError("servicenow.unavailable", f"ServiceNow didn't take the request (HTTP {status}).")
    if 400 <= status < 500:
        raise FatalError("servicenow.refused", f"ServiceNow refused the request (HTTP {status}).")
    raise RetryableError("servicenow.unexpected", f"ServiceNow answered HTTP {status}, not {expected}.")


def _unreadable() -> RetryableError:
    return RetryableError("servicenow.unexpected", "ServiceNow's answer isn't the record it should be.")


def _result(answer: HttpResponse) -> Any:
    try:
        body = answer.json()
    except ValueError:
        raise _unreadable() from None
    return body.get("result") if isinstance(body, dict) else None


def _ids(record: Any) -> tuple[str, str]:
    """A record's sys_id and number, or `servicenow.unexpected`: it may exist, and a retry looks again."""
    sys_id = record.get("sys_id") if isinstance(record, dict) else None
    number = record.get("number") if isinstance(record, dict) else None
    if not isinstance(sys_id, str) or not SYS_ID.fullmatch(sys_id) or not isinstance(number, str):
        raise _unreadable()
    if not NUMBER.fullmatch(number):
        raise _unreadable()
    return sys_id, number


Level = Literal["1", "2", "3"]
LEVEL_HELP = "1 High, 2 Medium, 3 Low; the severity's when not set."


class CreateConfig(Message):
    connection: uuid.UUID = connection_field("servicenow")
    urgency: Level | None = Field(None, title="Urgency", description=LEVEL_HELP)
    impact: Level | None = Field(None, title="Impact", description=LEVEL_HELP)
    caller_id: str | None = Field(None, title="Caller", description="A user's sys_id.")
    assignment_group: str | None = Field(None, title="Assignment group", description="A group's sys_id.")
    category: str | None = Field(None, min_length=1, max_length=100, title="Category")
    subcategory: str | None = Field(None, min_length=1, max_length=100, title="Subcategory")
    contact_type: str | None = Field(None, min_length=1, max_length=100, title="Channel",
                                     description="A contact_type value, e.g. monitoring.")  # fmt: skip
    correlation_id: str | None = Field(None, title="Correlation ID",
                                       description="Names the incident; the step's own key when not set.")  # fmt: skip
    correlation_display: str = Field("Dewpoint", min_length=1, max_length=100, title="Correlation display")

    @field_validator("caller_id", "assignment_group")
    @classmethod
    def _reference(cls, value: str | None) -> str | None:
        return _sys_id(value)

    @field_validator("category", "subcategory", "contact_type", "correlation_display")
    @classmethod
    def _one_line(cls, value: str | None) -> str | None:
        return _line(value)

    @field_validator("correlation_id")
    @classmethod
    def _correlation(cls, value: str | None) -> str | None:
        if value is not None and not CORRELATION.fullmatch(value):
            raise ValueError("1 to 100 of A-Z a-z 0-9 . _ : -")
        return value


def render_incident(config: CreateConfig, key: str) -> tuple[dict[str, Any], list[str]]:
    """The incident's fields, raw values (`sysparm_input_display_value` false), its `correlation_id` the config's, else
    `key` (the step's), and the names of what it cut. A title cut to fit is reported; a short description made from the
    text isn't (the text is in the description)."""
    truncated: list[str] = []
    short, short_cut = cut16(CONTROLS.sub(" ", config.title or config.text), SHORT_MAX)
    if short_cut and config.title:
        truncated.append("title")
    blocks = [config.text]
    if config.fields:
        blocks.append("\n".join(f"{f.label}: {f.value}" for f in config.fields))
    if config.links:
        blocks.append("\n".join(f"{link.label}: {link.url}" for link in config.links))
    description, description_cut = cut16("\n\n".join(blocks), LONG_MAX)
    if description_cut:
        truncated.append("description")
    level = LEVELS[config.severity]
    body: dict[str, Any] = {"short_description": short, "description": description,
                            "urgency": config.urgency or level, "impact": config.impact or level}  # fmt: skip
    for name in ("caller_id", "assignment_group", "category", "subcategory", "contact_type"):
        value = getattr(config, name)
        if value is not None:
            body[name] = value
    body["correlation_id"] = config.correlation_id or key
    body["correlation_display"] = config.correlation_display
    return body, truncated


class CreateOutput(BaseModel):
    sys_id: str
    number: str
    correlation_id: str
    truncated: list[str]


class CreateIncident(Node):
    """Opens a ServiceNow incident."""

    type = "servicenow.create_incident"
    version = 1
    title = "Create a ServiceNow incident"
    description = (
        "Opens an incident from a message. A retry looks for the incident first, by its correlation ID, the step's "
        "own unless set: an incident is opened once."
    )
    Config = CreateConfig
    Output = CreateOutput
    credentials = ("servicenow",)
    side_effect = SideEffect.RECONCILABLE
    retry = RETRY

    async def simulate(self, ctx: StepContext, config: CreateConfig) -> CreateOutput:
        key = config.correlation_id or ctx.idempotency_key()
        _, truncated = render_incident(config, key)
        return CreateOutput(sys_id=SIMULATED_ID, number=SIMULATED_NUMBER, correlation_id=key, truncated=truncated)

    async def run(self, ctx: StepContext, config: CreateConfig) -> CreateOutput:
        key = config.correlation_id or ctx.idempotency_key()
        body, truncated = render_incident(config, key)
        connection = await ctx.connection(config.connection)
        params = {"sysparm_fields": FIELDS, "sysparm_exclude_reference_link": "true"}
        answer = await connection.http.request("POST", TABLE, params=params, headers=JSON, json=body)
        _answered(answer, 201)
        sys_id, number = _ids(_result(answer))
        return CreateOutput(sys_id=sys_id, number=number, correlation_id=key, truncated=truncated)

    async def reconcile(self, ctx: StepContext, config: CreateConfig) -> CreateOutput | None:
        """The step's incident, if an earlier attempt opened it: a record whose `correlation_id` is the step's (the
        Table API ignores a query part it can't read, so every record is checked); none, and the create didn't
        land."""
        key = config.correlation_id or ctx.idempotency_key()
        connection = await ctx.connection(config.connection)
        params = {"sysparm_query": f"correlation_id={key}^ORDERBYsys_created_on", "sysparm_fields": FIELDS,
                  "sysparm_limit": "10"}  # fmt: skip
        answer = await connection.http.request("GET", TABLE, params=params, headers=JSON)
        _answered(answer, 200)
        records = _result(answer)
        if not isinstance(records, list):
            raise _unreadable()
        for record in records:
            if isinstance(record, dict) and record.get("correlation_id") == key:
                sys_id, number = _ids(record)
                _, truncated = render_incident(config, key)
                return CreateOutput(sys_id=sys_id, number=number, correlation_id=key, truncated=truncated)
        return None


class RecordConfig(BaseModel):
    """An incident named by its sys_id, as the create step's output gives it."""

    model_config = ConfigDict(extra="forbid")
    connection: uuid.UUID = connection_field("servicenow")
    sys_id: str = Field(title="Incident sys_id", description="The incident's, as the create step returned it.")

    @field_validator("sys_id")
    @classmethod
    def _record(cls, value: str) -> str:
        return _sys_id(value) or value


async def _patch(ctx: StepContext, config: RecordConfig, body: dict[str, Any], fields: str) -> dict[str, Any]:
    """PATCHes the incident and returns the answer's record, which must be that incident's."""
    connection = await ctx.connection(config.connection)
    answer = await connection.http.request("PATCH", f"{TABLE}/{config.sys_id}", params={"sysparm_fields": fields},
                                           headers=JSON, json=body)  # fmt: skip
    _answered(answer, 200)
    record = _result(answer)
    sys_id, _ = _ids(record)
    if sys_id != config.sys_id:
        raise _unreadable()
    return dict(record)


class UpdateConfig(RecordConfig):
    short_description: str | None = Field(None, min_length=1, max_length=1000, title="Short description")
    description: str | None = Field(None, min_length=1, max_length=40_000, title="Description")
    urgency: Level | None = Field(None, title="Urgency", description="1 High, 2 Medium, 3 Low.")
    impact: Level | None = Field(None, title="Impact", description="1 High, 2 Medium, 3 Low.")
    state: str | None = Field(None, title="State", description="The instance's raw value, e.g. 2 for In Progress.")
    assignment_group: str | None = Field(None, title="Assignment group", description="A group's sys_id.")
    category: str | None = Field(None, min_length=1, max_length=100, title="Category")
    subcategory: str | None = Field(None, min_length=1, max_length=100, title="Subcategory")

    @field_validator("assignment_group")
    @classmethod
    def _reference(cls, value: str | None) -> str | None:
        return _sys_id(value)

    @field_validator("category", "subcategory")
    @classmethod
    def _one_line(cls, value: str | None) -> str | None:
        return _line(value)

    @field_validator("state")
    @classmethod
    def _state(cls, value: str | None) -> str | None:
        if value is not None and not STATE.fullmatch(value):
            raise ValueError("a state's raw value: 1 to 4 digits")
        return value

    @model_validator(mode="after")
    def _something(self) -> "UpdateConfig":
        if all(getattr(self, name) is None for name in CHANGES):
            raise ValueError("set at least one field")
        return self


CHANGES = ("short_description", "description", "urgency", "impact", "state", "assignment_group", "category",
           "subcategory")  # fmt: skip


class ChangeOutput(BaseModel):
    sys_id: str
    number: str
    truncated: list[str]


def render_update(config: UpdateConfig) -> tuple[dict[str, Any], list[str]]:
    """The fields it sets, each only when given; long texts cut and reported."""
    body: dict[str, Any] = {}
    truncated: list[str] = []
    for name in CHANGES:
        value = getattr(config, name)
        if value is None:
            continue
        if name == "short_description":
            value, was_cut = cut16(CONTROLS.sub(" ", value), SHORT_MAX)
        elif name == "description":
            value, was_cut = cut16(value, LONG_MAX)
        else:
            was_cut = False
        if was_cut:
            truncated.append(name)
        body[name] = value
    return body, truncated


class UpdateIncident(Node):
    """Changes an incident's fields."""

    type = "servicenow.update_incident"
    version = 1
    title = "Update a ServiceNow incident"
    description = "Sets the fields given on an incident, named by its sys_id. A repeat sets the same values."
    Config = UpdateConfig
    Output = ChangeOutput
    credentials = ("servicenow",)
    side_effect = SideEffect.IDEMPOTENT
    retry = RETRY

    async def simulate(self, ctx: StepContext, config: UpdateConfig) -> ChangeOutput:
        _, truncated = render_update(config)
        return ChangeOutput(sys_id=config.sys_id, number=SIMULATED_NUMBER, truncated=truncated)

    async def run(self, ctx: StepContext, config: UpdateConfig) -> ChangeOutput:
        body, truncated = render_update(config)
        record = await _patch(ctx, config, body, "sys_id,number")
        return ChangeOutput(sys_id=config.sys_id, number=record["number"], truncated=truncated)


class ResolveConfig(RecordConfig):
    close_code: str = Field(min_length=1, max_length=100, title="Resolution code",
                            description="One of the instance's resolution codes, e.g. Solution provided.")  # fmt: skip
    close_notes: str = Field(min_length=1, max_length=40_000, title="Resolution notes")
    resolved_state: str = Field("6", title="Resolved state", description="Resolved's raw value: 6 unless changed.")

    @field_validator("close_code")
    @classmethod
    def _one_line(cls, value: str) -> str:
        return _line(value) or value

    @field_validator("resolved_state")
    @classmethod
    def _state(cls, value: str) -> str:
        if not STATE.fullmatch(value):
            raise ValueError("a state's raw value: 1 to 4 digits")
        return value


class ResolveOutput(ChangeOutput):
    state: str


class ResolveIncident(Node):
    """Resolves an incident."""

    type = "servicenow.resolve_incident"
    version = 1
    title = "Resolve a ServiceNow incident"
    description = (
        "Sets an incident's state to Resolved with a resolution code and notes, then checks ServiceNow kept it. A "
        "repeat sets the same values."
    )
    Config = ResolveConfig
    Output = ResolveOutput
    credentials = ("servicenow",)
    side_effect = SideEffect.IDEMPOTENT
    retry = RETRY

    async def simulate(self, ctx: StepContext, config: ResolveConfig) -> ResolveOutput:
        _, truncated = cut16(config.close_notes, LONG_MAX)
        return ResolveOutput(sys_id=config.sys_id, number=SIMULATED_NUMBER, state=config.resolved_state,
                             truncated=["close_notes"] if truncated else [])  # fmt: skip

    async def run(self, ctx: StepContext, config: ResolveConfig) -> ResolveOutput:
        notes, notes_cut = cut16(config.close_notes, LONG_MAX)
        body = {"state": config.resolved_state, "close_code": config.close_code, "close_notes": notes}
        record = await _patch(ctx, config, body, "sys_id,number,state")
        if record.get("state") != config.resolved_state:  # a business rule, or the instance numbers Resolved otherwise
            raise FatalError("servicenow.not_resolved", "ServiceNow kept the incident in another state.")
        return ResolveOutput(sys_id=config.sys_id, number=record["number"], state=config.resolved_state,
                             truncated=["close_notes"] if notes_cut else [])  # fmt: skip


class NoteConfig(RecordConfig):
    text: str = Field(min_length=1, max_length=40_000, title="Note")
    visibility: Literal["work_notes", "comments"] = Field(
        "work_notes", title="Visibility", description="work_notes: internal; comments: the caller sees it."
    )


class AddWorkNote(Node):
    """Adds a work note or a comment to an incident."""

    type = "servicenow.add_work_note"
    version = 1
    title = "Add a note to a ServiceNow incident"
    description = (
        "Appends a work note (internal) or a comment (the caller sees it) to an incident. Each send appends one: a "
        "send that may have arrived is never repeated."
    )
    Config = NoteConfig
    Output = ChangeOutput
    credentials = ("servicenow",)
    side_effect = SideEffect.AMBIGUOUS
    retry = RETRY

    async def simulate(self, ctx: StepContext, config: NoteConfig) -> ChangeOutput:
        _, was_cut = cut16(config.text, LONG_MAX)
        return ChangeOutput(sys_id=config.sys_id, number=SIMULATED_NUMBER, truncated=["text"] if was_cut else [])

    async def run(self, ctx: StepContext, config: NoteConfig) -> ChangeOutput:
        text, was_cut = cut16(config.text, LONG_MAX)
        record = await _patch(ctx, config, {config.visibility: text}, "sys_id,number")
        return ChangeOutput(sys_id=config.sys_id, number=record["number"], truncated=["text"] if was_cut else [])


PLUGIN = Plugin(name="servicenow", version="1.0.0",
                nodes=(CreateIncident, UpdateIncident, ResolveIncident, AddWorkNote),
                connection_types=(SERVICENOW,))  # fmt: skip
