# SPDX-License-Identifier: Apache-2.0
"""The activities `RunGraph` names (engine/runtime/activities.py), over a `RunStore`: the database in production, a
dict in tests.

A plugin step's activity runs **one attempt** of its node and writes nothing (spec §3, parent §6.6). `RunGraph`
schedules each attempt itself, decides whether to retry, and projects every attempt's rows, so a row write can
never repeat an effect, and a timeout after an ambiguous send is never retried. The attempt:
- validates the config before `run()` and the output after; a mismatch is fatal (`config_invalid`,
  `output_schema_violation`);
- calls `simulate()` in a simulated run, and records `simulated`;
- maps `RetryableError` to retryable, `FatalError` to fatal, and `OutcomeUnknownError` to `outcome_unknown`, never
  retried;
- maps any other exception to `unexpected_error`, retryable, except from an `ambiguous` node, where the request may
  have been sent: `outcome_unknown`;
- maps a check that fails with something other than a validation error (a validator's bug) like a failed check,
  never retried: after `run()`, the effect happened;
- for a `reconcilable` node on attempt 2 or later, calls `reconcile()` first and keeps what it finds.

Every failure it raises is marked `MAPPED`; `RunGraph` trusts no other failure as the node's. The projection is
tenant-readable, so a message never quotes input: a validation error names each field and its rule's code, and an
unexpected exception names only its type. Its text goes to the worker's log."""

import asyncio
import uuid
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import replace
from typing import Any, Protocol, get_args

import structlog
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import BaseModel, ValidationError
from pydantic_core import PydanticSerializationError
from pydantic_core.core_schema import ErrorType
from temporalio import activity
from temporalio.converter import DataConverter
from temporalio.exceptions import ApplicationError

from dewpoint.apps.cel_client import EvaluatorUnavailable, evaluate_remote
from dewpoint.apps.worker import logs
from dewpoint.apps.worker.claims import (
    UNAVAILABLE,
    UNREADABLE,
    ClaimStore,
    Evaluate,
    StoreUnavailableError,
    answering,
    child_input,
    claim_output,
    config_secrets,
    derive,
    evaluate_claimed,
    filter_claimed,
    grant,
    join_claimed,
    message,
    resolved_config,
    secrets_of,
    spill,
    unforged,
)
from dewpoint.apps.worker.context import context
from dewpoint.apps.worker.network import AttemptNetwork, Network
from dewpoint.core.claims.secret_index import SECRET_INDEX_LIMIT, SECRET_INDEX_UNAVAILABLE, SecretIndexLimitError
from dewpoint.core.claims.service import CLAIM_UNAVAILABLE
from dewpoint.engine import ENGINE_ABI
from dewpoint.engine.cel import ipc
from dewpoint.engine.handles import contains_marker
from dewpoint.engine.matcher import Matcher, masked
from dewpoint.engine.runtime import size
from dewpoint.engine.runtime.activities import (
    APPLIED,
    CEL_EVALUATE,
    CLAIMS_CHILD_INPUT,
    CLAIMS_DERIVE,
    CLAIMS_GRANT,
    CLAIMS_MESSAGE,
    CLAIMS_SPILL,
    LOAD_VERSION,
    MAPPED,
    OUTCOME_UNKNOWN,
    PROJECT,
    SIMULATE,
    SIMULATED,
    CelInput,
    CelResult,
    ChildInput,
    ChildInputResult,
    DeriveInput,
    DeriveResult,
    GrantInput,
    LoadVersionInput,
    MessageInput,
    MessageResult,
    ProjectInput,
    SpillInput,
    StepInput,
    StepResult,
    VersionData,
    step_activity,
)
from dewpoint.engine.runtime.execution import INTERNAL_ERROR, VERSION_UNUSABLE
from dewpoint.engine.runtime.ids import tenant_of
from dewpoint.engine.runtime.projection import REDACTED, location
from dewpoint.sdk import (
    AuthUnavailable,
    ConnectionUnavailable,
    Cooldown,
    EgressRefused,
    FatalError,
    HandshakeRejected,
    InvalidRequest,
    MailRefused,
    MaybeSent,
    Node,
    NodeError,
    NodeKind,
    NotSent,
    OutcomeUnknownError,
    Plugin,
    RateLimited,
    RedirectRefused,
    ResponseTooLarge,
    ResponseUnreadable,
    RetryableError,
    SideEffect,
    SimulationSendsNothing,
    StreamLost,
    TlsUnavailable,
    TlsVerificationFailed,
    TransportError,
    dump_output,
    node_manifest,
)
from dewpoint.sdk.declared import ERROR as DECLARED_ERROR

CONFIG_INVALID = "config_invalid"
OUTPUT_SCHEMA_VIOLATION = "output_schema_violation"
SIMULATION_UNAVAILABLE = "simulation_unavailable"
UNEXPECTED_ERROR = "unexpected_error"
INVALID_REQUEST = "invalid_request"
OUTPUT_UNCLAIMED = "The step's output couldn't be stored as claims, so it isn't used (engine 2b spec §3.6)."
STORE_UNAVAILABLE = "The claim store didn't answer before the step ran, so nothing was sent: the attempt is retried."
NODE_FAILED = "node_failed"  # a node's failure whose own code isn't a safe identifier its code declares
MESSAGE_WITHHELD = "The node's message isn't shown: it was computed, and only text written in the node's code is."
_log = structlog.get_logger("dewpoint.worker")
_PYDANTIC_CODES = frozenset(get_args(ErrorType))  # every built-in validation error type
# The JSON Schema 2020-12 keywords a declared model's error may name (`dewpoint.sdk.declared`).
SCHEMA_KEYWORDS = frozenset(
    {
        "type", "enum", "const", "multipleOf", "maximum", "exclusiveMaximum", "minimum", "exclusiveMinimum",
        "maxLength", "minLength", "pattern", "maxItems", "minItems", "uniqueItems", "maxContains", "minContains",
        "maxProperties", "minProperties", "required", "dependentRequired", "format", "additionalProperties",
        "properties", "patternProperties", "propertyNames", "items", "prefixItems", "contains", "unevaluatedItems",
        "unevaluatedProperties", "allOf", "anyOf", "oneOf", "not", "if", "then", "else", "dependentSchemas", "$ref",
        "false",
    }
)  # fmt: skip
# The `format`s an emitted output is checked for: those whose checks agree with what pydantic emits, and need no
# optional library. `date-time` and `time` aren't: RFC 3339 wants an offset, which pydantic's naive values lack, and
# without the optional library `time` is checked as `HH:MM:SS`, refusing fractions and zones. Listing them keeps the
# check from changing when an optional format library happens to be installed.
CHECKED_FORMATS = ("date", "uuid", "email", "ipv4", "ipv6", "regex")


JSON = DataConverter.default.payload_converter  # what the SDK encodes a result with, before the codec


class RunStore(ClaimStore, Protocol):
    async def version(self, tenant_id: str, version_id: str) -> VersionData: ...
    async def project(self, data: ProjectInput) -> None: ...


class _StepFailed(Exception):
    def __init__(self, code: str, message: str, *, retryable: bool, outcome: str | None = None) -> None:
        super().__init__(message)
        self.code, self.message, self.retryable, self.outcome = code, message, retryable, outcome

    def mapped(self, secrets: Matcher | None = None) -> ApplicationError:
        """The failure as the workflow gets it: its message masked against the run's secrets (engine 2b spec §3.7)."""
        details = {"outcome": self.outcome, MAPPED: True}
        message = secrets.mask(self.message, REDACTED) if secrets is not None else self.message
        return ApplicationError(message, details, type=self.code, non_retryable=not self.retryable)


def _bug(what: str, step: StepInput, e: Exception, node: type[Node]) -> None:
    """A bug's log line: its type and where it was raised, never text that isn't proven safe (engine 2b spec §6.7,
    §12). A secret the node made and never returned is in no index, so masking proves nothing here."""
    _log.warning(
        what,
        run_id=step.run_id,
        step_id=step.step_id,
        iteration_key=step.iteration_key,
        attempt=step.attempt,
        **logs.bug(e, logs.literals(node.__module__)),
    )


def _fields(error: ValidationError, schema: Mapping[str, Any]) -> str:
    """Each failing field and its rule's stable code (`int_parsing`, `value_error`), nothing else: pydantic's
    messages quote the input, and so does a validator's own prose, whatever `include_input` says. A location shows
    only what the schema declares at each place (`projection.location`): a map key is data, even a numeric one. A
    code shows only if pydantic defines it: a custom error's type is whatever its validator made it. Each is said once:
    keys breaking one rule show as one `*`."""
    problems = error.errors(include_url=False, include_context=True, include_input=False)
    return "; ".join(dict.fromkeys(f"{location(e['loc'], schema)} ({_code(e)})" for e in problems)) + "."


def _code(error: Any) -> str:
    """A built-in error's type; a declared model's schema keyword (`schema_maxLength`), a fixed vocabulary; else
    `custom_error`. Nothing else of its context is read."""
    kind = error.get("type")
    if kind == DECLARED_ERROR:
        rule = (error.get("ctx") or {}).get("rule")
        return f"schema_{rule}" if rule in SCHEMA_KEYWORDS else "custom_error"
    return kind if kind in _PYDANTIC_CODES else "custom_error"


def _declared(e: NodeError, node: type[Node]) -> tuple[str, str]:
    """A node's failure as its step shows it (engine 2b spec §3.7, §6.7): its code only when it's a safe identifier its
    plugin's code declares, its message only when it's a constant of that code, a generic one otherwise. A secret the
    node made and quoted is in no index yet, so masking proves nothing about computed text; the message is still
    masked when it leaves (a constant can repeat a secret the run knows)."""
    known = logs.literals(node.__module__)
    code = e.code if logs.safe_code(e.code) and logs.proven(e.code, known) else NODE_FAILED
    return code, (e.message if logs.proven(e.message, known) else MESSAGE_WITHHELD)


# The SDK's transport failures (plugins-3 D7, D10), each shown with its own fixed code and message. Those after which
# the request may have arrived end an ambiguous node `outcome_unknown`; a node whose requests may repeat retries
# `MaybeSent` and `RateLimited` and fails on the others. Nothing was sent after the rest: `NotSent` and `Cooldown`
# are retried, the others fail.
# A stream (D26): a refused handshake sent nothing a node answers for, retried only when the provider asked to wait or
# failed (429, 5xx); a lost stream may have carried a message the node sent, as `MaybeSent`.
# Mail (D20): a mail server's refusal delivered nothing, retried when it's transient (4yz); no TLS or no usable
# sign-in fails, having sent nothing.
_SENT_MAYBE = (MaybeSent, RateLimited, RedirectRefused, ResponseTooLarge, ResponseUnreadable, StreamLost)
_RETRIED = (NotSent, Cooldown, MaybeSent, RateLimited, StreamLost)
_TRANSPORT = (
    EgressRefused, TlsVerificationFailed, InvalidRequest, ConnectionUnavailable, SimulationSendsNothing, NotSent,
    Cooldown, MaybeSent, RateLimited, RedirectRefused, ResponseTooLarge, ResponseUnreadable, HandshakeRejected,
    StreamLost, MailRefused, TlsUnavailable, AuthUnavailable,
)  # fmt: skip


def _after_send(failure: _StepFailed, node: type[Node], network: AttemptNetwork | None) -> _StepFailed:
    """Once a request of the attempt may have left, or is still under way (the reviews' finding 1), an ambiguous node's
    failure is never retried and its outcome is unknown, whatever ended the attempt, the node's own `FatalError`
    included: a later failure can't establish what an earlier request did."""
    sent = network is not None and network.uncertain
    if sent and node.side_effect == SideEffect.AMBIGUOUS and failure.outcome != OUTCOME_UNKNOWN:
        return _StepFailed(failure.code, failure.message, retryable=False, outcome=OUTCOME_UNKNOWN)
    return failure


def _transport_failed(e: TransportError, node: type[Node]) -> _StepFailed:
    """The SDK class's own constants, never an instance's: a plugin's subclass can't change what's shown."""
    ambiguous = node.side_effect == SideEffect.AMBIGUOUS
    kind = next((k for k in _TRANSPORT if isinstance(e, k)), None)
    if kind is None:  # as any unexpected exception: an ambiguous node's request may have been sent
        message = "The node raised a network failure Dewpoint doesn't know."
        if ambiguous:
            return _StepFailed(OUTCOME_UNKNOWN, message, retryable=False, outcome=OUTCOME_UNKNOWN)
        return _StepFailed(UNEXPECTED_ERROR, message, retryable=True)
    if isinstance(e, _SENT_MAYBE) and ambiguous:
        return _StepFailed(kind.code, kind.message, retryable=False, outcome=OUTCOME_UNKNOWN)
    if isinstance(e, HandshakeRejected):
        status = e.status if type(e.status) is int else 0  # a plugin's subclass can't make it retryable otherwise
        return _StepFailed(kind.code, kind.message, retryable=status == 429 or 500 <= status < 600)
    if isinstance(e, MailRefused):
        reply = e.reply if type(e.reply) is int else 0  # a plugin's subclass can't make it retryable otherwise
        return _StepFailed(kind.code, kind.message, retryable=400 <= reply < 500)
    return _StepFailed(kind.code, kind.message, retryable=isinstance(e, _RETRIED))


async def _call(
    node: type[Node], step: StepInput, schema: Mapping[str, Any], network: AttemptNetwork | None = None
) -> tuple[BaseModel, str]:
    try:
        config = node.Config.model_validate(step.config)
    except ValidationError as e:
        message = f"The config doesn't match `{step.ref}`: {_fields(e, schema)}"
        raise _StepFailed(CONFIG_INVALID, message, retryable=False) from None
    except Exception as e:  # a validator's bug: it raised something pydantic doesn't turn into a validation error
        _bug("step_config_check_failed", step, e, node)
        message = f"The config doesn't match `{step.ref}`: checking it raised {logs.error_class(e)}."
        raise _StepFailed(CONFIG_INVALID, message, retryable=False) from None
    try:
        known = logs.literals(node.__module__)  # what its log may hold (engine 2b spec §6.7)
        ctx = context(step.tenant_id, step.run_id, step.step_id, step.iteration_key, step.attempt, known, network)
        instance = node()
        if step.mode == SIMULATE:
            return await instance.simulate(ctx, config), SIMULATED
        if node.side_effect == SideEffect.RECONCILABLE and step.attempt > 1:
            found = await instance.reconcile(ctx, config)
            if found is not None:
                return found, APPLIED
        return await instance.run(ctx, config), APPLIED
    except OutcomeUnknownError as e:
        raise _StepFailed(*_declared(e, node), retryable=False, outcome=OUTCOME_UNKNOWN) from None
    except FatalError as e:
        raise _after_send(_StepFailed(*_declared(e, node), retryable=False), node, network) from None
    except RetryableError as e:
        raise _after_send(_StepFailed(*_declared(e, node), retryable=True), node, network) from None
    except TransportError as e:
        raise _after_send(_transport_failed(e, node), node, network) from None
    except SecretIndexLimitError as e:  # a connection's secret couldn't join the index: nothing was sent (D5)
        raise _after_send(_StepFailed(SECRET_INDEX_LIMIT, str(e), retryable=False), node, network) from None
    except StoreUnavailableError as e:
        _bug("step_store_unavailable", step, e.__cause__ if isinstance(e.__cause__, Exception) else e, node)
        failure = _StepFailed(SECRET_INDEX_UNAVAILABLE, STORE_UNAVAILABLE, retryable=True)
        raise _after_send(failure, node, network) from None
    except asyncio.CancelledError:
        raise
    except Exception as e:
        if isinstance(e, NotImplementedError) and step.mode == SIMULATE:
            raise _StepFailed(SIMULATION_UNAVAILABLE, f"`{step.ref}` can't be simulated.", retryable=False) from None
        _bug("step_unexpected_error", step, e, node)
        message = f"The node raised {logs.error_class(e)}."
        if node.side_effect == SideEffect.AMBIGUOUS:
            raise _StepFailed(OUTCOME_UNKNOWN, message, retryable=False, outcome=OUTCOME_UNKNOWN) from None
        raise _StepFailed(UNEXPECTED_ERROR, message, retryable=True) from None


def _same_tenant(tenant_id: str) -> None:
    """The input's tenant is the one this activity's server-built workflow id names (engine 2b spec §6.1): the store
    scopes every read and write by it. Only a bug, or a workflow started outside Dewpoint, gets here; the failure isn't
    the node's (`MAPPED`), so `RunGraph` doesn't take it for one."""
    if tenant_of(activity.info().workflow_id or "") != tenant_id:
        raise ApplicationError(
            "This activity's input doesn't name its workflow's tenant.", type=INTERNAL_ERROR, non_retryable=True
        )


def _masked(data: ProjectInput, secrets: Matcher) -> ProjectInput:
    """A projection with every secret in its previews and messages replaced."""

    def text(message: str | None) -> str | None:
        return secrets.mask(message, REDACTED) if message is not None else None

    steps = [
        replace(
            r,
            input_preview=masked(r.input_preview, secrets, REDACTED),
            output_preview=masked(r.output_preview, secrets, REDACTED),
            error_message=text(r.error_message),
        )
        for r in data.steps
    ]
    run = replace(data.run, error_message=text(data.run.error_message)) if data.run is not None else None
    return replace(data, steps=steps, run=run)


def step_activity_for(
    node: type[Node], store: ClaimStore, network: Network | None = None
) -> Callable[[StepInput], Awaitable[StepResult]]:
    ref = f"{node.type}@{node.version}"
    config_schema = node.Config.model_json_schema(mode="validation")
    output_schema = node_manifest(node)["output_schema"]  # what the node promises to emit: serialized and closed
    emitted = Draft202012Validator(output_schema, format_checker=FormatChecker(formats=CHECKED_FORMATS))

    def violation(detail: str, outcome: str | None = None) -> _StepFailed:
        message = f"The output doesn't match `{ref}`: {detail}"
        return _StepFailed(OUTPUT_SCHEMA_VIOLATION, message, retryable=False, outcome=outcome)

    def output_of(result: Any) -> Any:
        if not isinstance(result, BaseModel):
            return dump_output(node.Output.model_validate(result))
        # pydantic trusts instances it didn't build (`model_construct`, assignment): check what the instance emits
        # against the declared output schema, not against the model's input types (a field serializer may change them)
        data = result.model_dump(mode="json", by_alias=True, warnings=False)
        problems = sorted(emitted.iter_errors(data), key=lambda e: [str(p) for p in e.absolute_path])
        if problems:
            # each place and rule said once: jsonschema reports `required` once per missing property, and keys
            # breaking one rule show as one `*`
            said = dict.fromkeys(f"{location(list(e.absolute_path), output_schema)} ({e.validator})" for e in problems)
            raise violation("; ".join(said) + ".")
        return data

    @activity.defn(name=step_activity(ref))
    async def run_step(step: StepInput) -> StepResult:
        """One attempt, across the boundary (engine 2b spec §3.6): its input's handles resolved here, its output split
        before it leaves, every message masked against the run's secret index."""
        _same_tenant(step.tenant_id)
        root = step.root_run_id or step.run_id
        held = Matcher(())  # the index read before the attempt; until then, every message is the boundary's own text

        async def secrets() -> Matcher:
            """The index at the boundary: another activity may have extended it (§3.7). When the store doesn't
            answer again, the one held masks: the failure stays what it was, never one of unknown outcome."""
            try:
                return (await secrets_of(store, step.tenant_id, root)).matcher
            except Exception:
                return held

        try:
            try:  # before the node runs: nothing is sent, so a store that doesn't answer fails the attempt retryable
                answered = answering(store)  # its outages told from a bug in this work
                held = (await secrets_of(answered, step.tenant_id, root)).matcher  # the index's cached automaton
                config = await resolved_config(step.config, answered)
                marked = config_secrets(config, config_schema)  # only the config marks them: indexed before the attempt
                if marked:
                    await answered.remember(step.tenant_id, root, marked)
            except UNREADABLE:
                raise _StepFailed(CLAIM_UNAVAILABLE, UNAVAILABLE, retryable=False) from None
            except SecretIndexLimitError as e:
                raise _StepFailed(SECRET_INDEX_LIMIT, str(e), retryable=False) from None
            except StoreUnavailableError as e:
                _bug("step_store_unavailable", step, e.__cause__ if isinstance(e.__cause__, Exception) else e, node)
                raise _StepFailed(SECRET_INDEX_UNAVAILABLE, STORE_UNAVAILABLE, retryable=True) from None
            except Exception as e:  # a bug in this work, no outage: nothing was sent, and retrying won't mend it
                _bug("step_input_unprepared", step, e, node)
                message = f"Preparing the step raised {logs.error_class(e)}; the worker's log says where."
                raise _StepFailed(INTERNAL_ERROR, message, retryable=False) from None
            attempt = (
                network.attempt(
                    tenant_id=uuid.UUID(step.tenant_id), run_id=uuid.UUID(step.run_id),
                    step_id=uuid.UUID(step.step_id), root_run_id=uuid.UUID(root), node=node,
                    simulated=step.mode == SIMULATE, remember=answered.remember, beat=activity.heartbeat,
                )
                if network is not None
                else None
            )  # fmt: skip
            try:
                result, outcome = await _call(node, replace(step, config=config), config_schema, attempt)
            finally:
                if attempt is not None:
                    await attempt.aclose()
        except _StepFailed as f:
            raise f.mapped(await secrets()) from None
        try:  # the node ran: whatever fails from here, its effect happened, so nothing is retried
            data = output_of(result)
            if contains_marker(data):  # a forged handle never crosses into a run (§3.2)
                raise violation("it holds the reserved key `$claim`.")
            try:
                envelope = await claim_output(data, output_schema, step, store)
            except SecretIndexLimitError as e:
                raise _StepFailed(SECRET_INDEX_LIMIT, str(e), retryable=False, outcome=outcome) from None
            except Exception as e:  # the claim store failed after the node ran: never a plain output instead
                _bug("step_output_unclaimed", step, e, node)
                raise _StepFailed(CLAIM_UNAVAILABLE, OUTPUT_UNCLAIMED, retryable=False, outcome=outcome) from None
            done = StepResult(envelope, outcome)
            if not size.fits(done, JSON):  # Temporal would refuse to record it (engine 2b spec §5.2)
                raise _StepFailed(size.PAYLOAD_TOO_LARGE, size.STEP_OUTPUT_TOO_LARGE, retryable=False, outcome=outcome)
            return done
        except _StepFailed as f:  # after the node ran, a failure says its effect happened (the 3b-1 review's L6)
            if f.outcome is None:
                f.outcome = outcome
            raise f.mapped(await secrets()) from None
        except PydanticSerializationError:
            raise violation("it can't be written as JSON.", outcome).mapped() from None
        except ValidationError as e:
            raise violation(_fields(e, output_schema), outcome).mapped() from None
        except Exception as e:  # a validator's bug: it raised something pydantic doesn't turn into a validation error
            _bug("step_output_check_failed", step, e, node)
            raise violation(f"checking it raised {logs.error_class(e)}.", outcome).mapped() from None

    return run_step


def engine_activities(
    store: RunStore, plugins: Iterable[Plugin], *, abi: int = ENGINE_ABI, network: Network | None = None
) -> list[Callable[..., Any]]:
    """Everything the engine queue serves: the version loader, the projection, and one activity per action node.
    `abi` is the engine ABI this build runs (another build's in the two-build tests): a version runs only on a build
    of its ABI (spec §7). Admission already compares with the current build's; the loader refuses any other too, for
    a run that reached this build anyway (a promotion that raced its start), a sub-flow or a failure handler."""
    logs.withhold_activity_errors()  # Temporal's records of failed attempts keep no error text (engine 2b spec §12)

    @activity.defn(name=LOAD_VERSION)
    async def load_version(data: LoadVersionInput) -> VersionData:
        _same_tenant(data.tenant_id)
        version = await store.version(data.tenant_id, data.version_id)
        if version.engine_abi != abi:  # the run fails `version_unusable`, with this message
            remedy = (
                f"start the run again once a build of ABI {version.engine_abi} is current"
                if version.engine_abi is not None and version.engine_abi > abi
                else f"publish the workflow again with a build of ABI {abi}"
            )
            raise ApplicationError(
                f"This version was published for engine ABI {version.engine_abi}, and this build runs ABI {abi}: "
                f"{remedy}.",
                type=VERSION_UNUSABLE,
                non_retryable=True,
            )
        if not size.fits(version, JSON):  # its result would pass Temporal's payload limit (engine 2b spec §5.2)
            raise ApplicationError(size.VERSION_TOO_LARGE, type=VERSION_UNUSABLE, non_retryable=True)
        return version

    @activity.defn(name=PROJECT)
    async def project(data: ProjectInput) -> None:
        """Every row masked against the run tree's secret index before it's written (engine 2b spec §3.7)."""
        _same_tenant(data.tenant_id)
        root = data.root_run_id or (data.run.run_id if data.run is not None else "")
        secrets = (await secrets_of(store, data.tenant_id, root)).matcher if root else Matcher(())
        await store.project(_masked(data, secrets) if secrets.strings else data)

    @activity.defn(name=CLAIMS_DERIVE)
    async def claims_derive(data: DeriveInput) -> DeriveResult:
        return await derive(data, store)

    @activity.defn(name=CLAIMS_CHILD_INPUT)
    async def claims_child_input(data: ChildInput) -> ChildInputResult:
        return await child_input(data, store)

    @activity.defn(name=CLAIMS_GRANT)
    async def claims_grant(data: GrantInput) -> None:
        await grant(data, store)

    @activity.defn(name=CLAIMS_MESSAGE)
    async def claims_message(data: MessageInput) -> MessageResult:
        return await message(data, store)

    @activity.defn(name=CLAIMS_SPILL)
    async def claims_spill(data: SpillInput) -> None:
        await spill(data, store)

    steps = [
        step_activity_for(node, store, network)
        for plugin in plugins
        for node in plugin.nodes
        if node.kind == NodeKind.ACTION
    ]
    return [
        load_version,
        project,
        claims_derive,
        claims_child_input,
        claims_grant,
        claims_message,
        claims_spill,
        *steps,
    ]


def remote_evaluator(socket_path: str, profile: str) -> Evaluate:
    """Evaluate through the cel-evaluator on `socket_path` (spec §5.7)."""

    async def evaluate(request: dict[str, Any]) -> list[dict[str, Any]]:
        try:
            parsed = ipc.parse_request(request)
        except ipc.FrameError as e:  # a request no retry can fix
            raise ApplicationError(f"not an evaluate request: {e}", type=INVALID_REQUEST, non_retryable=True) from None
        if not isinstance(parsed, ipc.EvaluateRequest):
            raise ApplicationError("not an evaluate request", type=INVALID_REQUEST, non_retryable=True)
        outcomes = await evaluate_remote(socket_path, parsed, served_profile=profile)
        return [o.to_json() for o in outcomes]

    return evaluate


def cel_activity(evaluate: Evaluate, store: ClaimStore | None = None) -> Callable[[CelInput], Awaitable[CelResult]]:
    """`cel.evaluate`: outcomes are recorded; an unavailable evaluator is retried by Temporal (3 attempts). A request
    with `claims` resolves its handles through `store` and claims what read sensitive data (engine 2b spec §4.2)."""
    logs.withhold_activity_errors()  # Temporal's records of failed attempts keep no error text (engine 2b spec §12)

    @activity.defn(name=CEL_EVALUATE)
    async def cel_evaluate(data: CelInput) -> CelResult:
        try:
            if data.claims is None:
                if any(contains_marker(b) for b in data.request.get("bindings", ())):  # never evaluated as data
                    raise ApplicationError(
                        "A request whose bindings hold handles came without claims.", type=INTERNAL_ERROR,
                        non_retryable=True,
                    )  # fmt: skip
                return CelResult(unforged(await evaluate(data.request)))
            if store is None:
                raise ApplicationError("This CEL worker reads no claims.", type=INTERNAL_ERROR, non_retryable=True)
            if data.template is not None:
                return CelResult([await join_claimed(data.template, data.claims, store)])
            if data.filter is not None:
                return CelResult([await filter_claimed(data.request, data.filter, data.claims, store, evaluate)])
            return CelResult(await evaluate_claimed(data.request, data.claims, store, evaluate))
        except EvaluatorUnavailable as e:
            raise ApplicationError(str(e), type="evaluator_unavailable") from None

    return cel_evaluate


__all__ = [
    "CHECKED_FORMATS",
    "CONFIG_INVALID",
    "INVALID_REQUEST",
    "OUTPUT_SCHEMA_VIOLATION",
    "SIMULATION_UNAVAILABLE",
    "UNEXPECTED_ERROR",
    "Evaluate",
    "RunStore",
    "cel_activity",
    "engine_activities",
    "remote_evaluator",
    "step_activity_for",
]
