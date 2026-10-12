# SPDX-License-Identifier: Apache-2.0
"""Dispatch (engine 2b spec §7.3, §7.8, §2.3–2.5; engine-core §4.5): the transaction that marks one request `starting`.

It takes the production gate's lock and the request's tenant's lock, both shared (disabling the gate and erasing a
tenant take them exclusively, §2.4, §6.5), then locks the request itself with SKIP LOCKED: another dispatcher holding
it is passed by. In it, every critical condition is checked again (§2.3): the gate, the tenant, the current build's
live workers and their capabilities, the frozen version executable and of the current build's ABI, a free slot, and
the tenant's key, which seals the start. A condition that doesn't hold leaves the request queued, no attempt counted:
waiting isn't failing (§2.5). A version the current build can't run (`engine_abi_changed`), or whose closure was
retired (the defensive check, which should never fire), cancels the request explicitly, audited. Otherwise the slot is
reserved, the run's row written (or an earlier attempt's reused) and the request marked `starting`, together; the start
itself is sent after the commit, with no lock held across the call to Temporal."""

import dataclasses
import time
import uuid
from collections import Counter
from collections.abc import Awaitable, Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

import structlog
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from google.protobuf.message import DecodeError
from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from temporalio.api.common.v1 import WorkflowExecution
from temporalio.api.enums.v1 import EventType
from temporalio.api.errordetails.v1 import PermissionDeniedFailure
from temporalio.api.workflowservice.v1 import DescribeWorkflowExecutionRequest
from temporalio.client import Client
from temporalio.common import WorkflowIDReusePolicy
from temporalio.converter import DataConverter, WorkflowSerializationContext
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.service import RPCError, RPCStatusCode

from dewpoint.apps.cancels import USER_CANCELLED
from dewpoint.apps.codec import CodecRefusedError
from dewpoint.apps.dispatcher import budget, failures, recovery, start_call
from dewpoint.apps.dispatcher.observe import REQUIRED, Build
from dewpoint.core import blockers
from dewpoint.core.audit import service as audit
from dewpoint.core.claims import service as claims
from dewpoint.core.claims.cipher import ClaimCipher
from dewpoint.core.config import Settings
from dewpoint.core.crypto.keys import KeySource, key_unreadable
from dewpoint.core.db import tenant_scope
from dewpoint.core.models.platform import PlatformSettings
from dewpoint.core.models.requests import RunRequest, RunSlot, TenantRunLimits
from dewpoint.core.models.runs import ExecutionEvidence
from dewpoint.core.models.tenancy import Tenant
from dewpoint.core.models.workflows import WorkflowVersion
from dewpoint.core.platform.service import PRODUCTION, workers_ready
from dewpoint.core.plugins import lifecycle
from dewpoint.core.retention import slo as retention_slo
from dewpoint.core.runs import service as runs
from dewpoint.core.workflows.service import other_abi
from dewpoint.engine.runtime.activities import ENGINE_QUEUE, RunInput
from dewpoint.engine.runtime.ids import run_workflow_id
from dewpoint.engine.runtime.workflow import RunGraph

log = structlog.get_logger("dewpoint.dispatcher")
GATE_LOCK = "dewpoint:production-gate"
START_DEADLINE = timedelta(seconds=10)  # a start's own deadline: the reconciler's grace period is longer (§7.6)
MAX_ATTEMPTS = 10  # confirmed refusals before a request is dead (§7.4)
CANDIDATES = 50  # tenants picked per cycle, each its oldest due request
AGAIN_S = 1.0  # a pass takes further rounds while it has run less than this (2b-4b M3, the owner's ruling 1)
START_REFUSED = "start_refused"
ID_COLLISION = "id_collision"
START_FAILED = "start_failed"
ENVELOPE_UNREADABLE = "envelope_unreadable"
RUN_ENDED = "run_ended"
SEND_CAP = "send_cap"  # its start sends, or its refusals, are spent (`_spent`): never sent again
# D12's start check denies with one of two fixed reasons, in the error's `PermissionDeniedFailure` (revision 17)
NOT_PERMITTED, CHECK_UNAVAILABLE = "dewpoint:start-not-permitted", "dewpoint:start-check-unavailable"
START_CHECK_UNAVAILABLE = "start_check_unavailable"  # every send spent, none created anything: infrastructure
START_THROTTLED = "start_throttled"  # every send spent, Temporal throttled or refused each: none created anything
RETIRING = "retiring"  # a retirement holds the closure's lifecycle lock: back next cycle
KEY_UNUSABLE = "key_unusable"
RETENTION_UNHEALTHY = "retention_unhealthy"  # no recent successful sweep, or it left data a day past its cutoff
ENVELOPE_MESSAGE = (
    "The request's trigger envelope doesn't open or isn't JSON; repairing a key never reopens it (engine 2b spec §7.1)."
)
REFUSED_MESSAGE = "Temporal refused the run's start 10 times (engine 2b spec §7.4)."
UNAVAILABLE_MESSAGE = (
    "The run's 10 start sends are spent and none created anything: the start check couldn't be "
    "made for some of them, an infrastructure failure, not a refusal."
)
THROTTLED_MESSAGE = "The run's 10 start sends are spent and none created anything: Temporal throttled or refused each."
NOT_PERMITTED_MESSAGE = (
    "The start check refused the run's start: its request wasn't eligible when it was sent. An integrity failure, "
    "alerted (the upgrade barrier, revision 17)."
)
COLLISION_MESSAGE = "Another execution holds this run's workflow id (engine 2b spec §7.4)."
# A status Temporal answers with when it certainly refused the start (2a's rule, `apps.runs`).
REFUSED = {
    RPCStatusCode.INVALID_ARGUMENT, RPCStatusCode.NOT_FOUND, RPCStatusCode.PERMISSION_DENIED,
    RPCStatusCode.UNAUTHENTICATED, RPCStatusCode.FAILED_PRECONDITION, RPCStatusCode.OUT_OF_RANGE,
    RPCStatusCode.UNIMPLEMENTED,
}  # fmt: skip


def tenant_lock(tenant_id: uuid.UUID) -> str:
    return f"dewpoint:tenant:{tenant_id}"


@dataclass(frozen=True)
class Starting:
    """A request marked `starting`: what its start sends."""

    request_id: uuid.UUID
    tenant_id: uuid.UUID
    start: RunInput
    start_request_id: uuid.UUID | None = None  # every start of the request carries it (the start-check slice)
    attempt: int | None = None  # its send, counted and recorded in the starting transaction (0054); none to verify


# Why a request is left queued, no attempt counted: waiting isn't failing, nor a success that clears its failures
WAITING = frozenset({"environment_not_recorded", "gate_off", RETENTION_UNHEALTHY, "tenant_erasing", "workers_not_ready",
                     RETIRING, "no_slot", KEY_UNUSABLE})  # fmt: skip


@dataclass(frozen=True)
class Waiting:
    """A request left queued, no attempt counted: `gate_off`, `environment_not_recorded`, `retention_unhealthy` (a
    production deployment's, §10.3), `tenant_erasing`, `workers_not_ready`, `retiring`, `no_slot` or `key_unusable`
    (`WAITING`)."""

    reason: str

    def __post_init__(self) -> None:
        if self.reason not in WAITING:
            raise ValueError(self.reason)


class Target(Protocol):
    """A request a start's outcome is applied to."""

    @property
    def request_id(self) -> uuid.UUID: ...

    @property
    def tenant_id(self) -> uuid.UUID: ...


@dataclass(frozen=True)
class Ref:
    """A request, by id: what the reconciler settles when it has no start of its own (§7.6)."""

    request_id: uuid.UUID
    tenant_id: uuid.UUID


@dataclass(frozen=True)
class Dead:
    """The request can never start (a broken envelope): `dead`, audited, an earlier attempt's run row failed. Terminal:
    repairing a key later (a wrong key fails as a tampered envelope does) never reopens it; a re-run is a new one."""

    reason: str


@dataclass(frozen=True)
class Held:
    """Never started: its run's row already records an end (an end write that landed after an absence requeued it).
    Back to `starting`, without a slot, with an alert, for the reconciler to verify or leave for an operator."""

    reason: str


@dataclass(frozen=True)
class Cancelled:
    """A request cancelled at dispatch: `engine_abi_changed`, `node_type_retired` or `cel_profile_retired`."""

    reason: str


Seal = Callable[[RunInput], Awaitable[None]]


def sealer(converter: DataConverter, namespace: str) -> Seal:
    """Encrypts a start as its client will, with its tenant's key (§6.2): a key that doesn't work stops the start
    before anything is written (§2.3). Raises whatever the codec raises."""

    async def seal(start: RunInput) -> None:
        context = WorkflowSerializationContext(
            namespace=namespace, workflow_id=run_workflow_id(start.tenant_id, start.run_id)
        )
        await converter.with_context(context).encode([start])

    return seal


class KeyUnusableError(Exception):
    """A tenant's key that couldn't be read (`key_unreadable`): no such key, one that doesn't unwrap, or the keyring
    didn't answer. Its cause says which."""


class KeyFailures:
    """A `KeySource` whose expected failures (`key_unreadable`) say they're the key's, as KeyUnusableError: only the
    key's read is wrapped, so an envelope that doesn't open is never taken for a key outage, and a bug in reading the
    key raises as it is (the owner's M2 review)."""

    def __init__(self, keys: KeySource) -> None:
        self._keys = keys

    async def active(self, tenant_id: str) -> tuple[int, AESGCM]:
        try:
            return await self._keys.active(tenant_id)
        except Exception as e:
            if not key_unreadable(e):
                raise
            raise KeyUnusableError("The tenant's active key can't be read.") from e

    async def get(self, tenant_id: str, version: int) -> AESGCM:
        try:
            return await self._keys.get(tenant_id, version)
        except Exception as e:
            if not key_unreadable(e):
                raise
            raise KeyUnusableError("A tenant's key can't be read.") from e

    async def digest_key(self, tenant_id: str, version: int | None) -> tuple[int, bytes]:
        try:
            return await self._keys.digest_key(tenant_id, version)
        except Exception as e:
            if not key_unreadable(e):
                raise
            raise KeyUnusableError("A tenant's digest key can't be read.") from e


async def _after_lifecycle_lock() -> None:
    """Runs right after the starting transaction takes its lifecycle locks. A no-op; the race tests pause here."""


async def _after_starting_commit(request_id: uuid.UUID) -> None:
    """Runs once the starting transaction has committed, before the start is sent. A no-op; the start-check proof
    pauses here (the upgrade barrier's revision 17.1)."""


async def _after_start_call(request_id: uuid.UUID) -> None:
    """Runs once the start's call has returned, before its outcome is settled. A no-op; the start-check proof pauses
    here (revision 17.2's lock variant)."""


async def _lock(s: AsyncSession, key: str) -> None:
    await s.execute(text("select pg_advisory_xact_lock_shared(hashtextextended(:k, 0))"), {"k": key})


async def begin(
    sessionmaker: async_sessionmaker[AsyncSession],
    seal: Seal,
    settings: Settings,
    keys: KeySource | None = None,
    *,
    tenant_id: uuid.UUID,
    request_id: uuid.UUID,
    build: Build,
) -> Starting | Waiting | Cancelled | Dead | Held | None:
    """One due request's starting transaction. None: no longer due, or another dispatcher holds it. Anything it
    can't classify (a bug, an envelope its foreign key should have kept, an outage) raises; nothing it wrote stays."""
    async with sessionmaker() as s, s.begin():
        outcome = await _begin(s, seal, settings, keys, tenant_id, request_id, build)
        if isinstance(outcome, Waiting):
            await s.rollback()  # nothing it wrote stays: the request waits as it was
        return outcome


async def _begin(
    s: AsyncSession,
    seal: Seal,
    settings: Settings,
    keys: KeySource | None,
    tenant_id: uuid.UUID,
    request_id: uuid.UUID,
    build: Build,
) -> Starting | Waiting | Cancelled | Dead | Held | None:
    await lifecycle.assert_read_committed(s)
    await tenant_scope(s, tenant_id)
    await _lock(s, GATE_LOCK)
    await _lock(s, tenant_lock(tenant_id))
    request = (
        await s.execute(
            select(RunRequest)
            .where(
                RunRequest.id == request_id,
                RunRequest.status == "queued",
                RunRequest.next_attempt_at <= func.statement_timestamp(),
            )
            .with_for_update(skip_locked=True)
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if request is None or request.workflow_version_id is None:
        return None
    ran = (await s.execute(text("select status from runs where id = :i for update"), {"i": request.id})).scalar()
    if ran is not None and ran != "running":  # an earlier attempt's execution ran to its end: never a second start
        log.error("start_after_end", request_id=str(request.id))
        await _held(s)
        request.status, request.starting_at = "starting", func.statement_timestamp()
        await s.flush()
        await recovery.noted(s, request.tenant_id, recovery.START_AFTER_END, request.id)  # for an operator (2b-4b M3)
        return Held(RUN_ENDED)
    if _spent(request):  # settling never queues a spent request again: a bug, or a hand's edit
        log.error("start_send_cap", request_id=str(request.id))
        await _held(s)
        request.status, request.starting_at = "starting", func.statement_timestamp()
        await s.flush()
        await recovery.noted(s, request.tenant_id, recovery.START_UNRESOLVED, request.id)  # the reconciler observes it
        return Held(SEND_CAP)
    platform = await s.get(PlatformSettings, 1, populate_existing=True)
    if platform is None:
        return Waiting("environment_not_recorded")
    if platform.environment == PRODUCTION and not platform.production_runs:
        return Waiting("gate_off")
    if platform.environment == PRODUCTION and not await retention_slo.healthy(s):
        log.warning("dispatch_waiting", reason=RETENTION_UNHEALTHY)
        return Waiting(RETENTION_UNHEALTHY)
    tenant = await s.get(Tenant, tenant_id, populate_existing=True)
    if tenant is None or tenant.status != "active":
        return Waiting("tenant_erasing")
    problems = await workers_ready(s, build.build_id, REQUIRED)
    if problems:
        log.warning("dispatch_waiting", reason="workers_not_ready", problems=problems)
        return Waiting("workers_not_ready")
    version = await s.get(WorkflowVersion, request.workflow_version_id)
    if version is None:
        raise RuntimeError("A request frozen on a version that isn't there.")
    entries = lifecycle.entries_for(version.closure_node_refs, version.closure_cel_profiles)
    # Never waited for: this transaction holds the request's row, which a retirement holding these locks cancels.
    if not await lifecycle.try_lock_shared(s, entries):
        return Waiting(RETIRING)
    await _after_lifecycle_lock()
    blocked = lifecycle.not_executable(await lifecycle.states(s, entries))
    if blocked:  # the defensive check: admission's locks make this impossible, but for a request that came back
        reason = "node_type_retired" if any(e.kind == "node" for e in blocked) else "cel_profile_retired"
        log.warning("dispatch_defensive_cancel", request_id=str(request.id), reason=reason)
        return await _cancel(s, request, reason, {"reason": reason})
    stale = await other_abi(s, version.closure_version_ids, build.engine_abi)
    if stale:
        details: dict[str, object] = {"reason": "engine_abi_changed", "version_abi": version.engine_abi,
                                      "build_abi": build.engine_abi}  # fmt: skip
        return await _cancel(s, request, "engine_abi_changed", details)
    if not await _slot_free(s, tenant_id, platform):
        return Waiting("no_slot")
    if keys is None:
        raise RuntimeError("Dispatch reads envelopes with the tenants' keys.")
    # The tenant's key opens the envelope and seals the start: one that can't be read waits (§2.3). Each failure is
    # told apart where it happens, so a broken envelope or a bug never reads as a key outage (the owner's M2 review).
    try:
        envelope = await claims.read_envelope(s, ClaimCipher(KeyFailures(keys)), tenant_id, request_id=request.id)
    except KeyUnusableError as e:
        log.warning("dispatch_waiting", reason=KEY_UNUSABLE, error=type(e.__cause__).__name__)
        return Waiting(KEY_UNUSABLE)
    except claims.EnvelopeUnreadableError:  # broken for good: no retry mends it
        log.error("dispatch_envelope_unreadable", request_id=str(request.id))
        await _dead(s, request, ENVELOPE_UNREADABLE, ENVELOPE_MESSAGE)
        await s.flush()
        return Dead(ENVELOPE_UNREADABLE)
    start = run_input(request, version.id, envelope, settings)
    try:
        await seal(start)
    except CodecRefusedError as e:  # the codec wraps whatever stopped it: only a key that can't be read waits
        if not key_unreadable(e.__cause__):
            raise
        log.warning("dispatch_waiting", reason=KEY_UNUSABLE, error=type(e.__cause__).__name__)
        return Waiting(KEY_UNUSABLE)
    s.add(RunSlot(run_id=request.id, tenant_id=tenant_id))
    await runs.precreate_run(
        s, run_id=request.id, tenant_id=tenant_id, workflow_id=request.workflow_id, version_id=version.id,
        mode=request.mode, started_by=request.actor_id, queued_at=request.queued_at,
    )  # fmt: skip
    await runs.record_attempt(s, tenant_id, request.id)  # its execution's evidence, before Temporal is asked
    if request.start_request_id is None:  # recorded once: every start of it carries it (the start-check slice)
        request.start_request_id = uuid.uuid4()
    request.sends += 1  # counted before the send, in the same commit that makes it `starting`
    request.status = "starting"
    request.starting_at = func.statement_timestamp()  # the reconciler's grace runs from here, slot or not (§7.6)
    await s.flush()
    # Its intent, recorded with the count in the same transaction (0054): the fence lets nothing else commit
    workflow_id = run_workflow_id(str(tenant_id), str(request.id))
    await blockers.intend(s, request.id, tenant_id, workflow_id, request.start_request_id, request.sends)
    return Starting(request.id, tenant_id, start, request.start_request_id, request.sends)


async def _held(s: AsyncSession) -> None:
    """A hold back to `starting` with nothing sent (`Held`), said in its own transaction: the fence (0054) lets it
    commit without a recorded send, and never lets it count one."""
    await s.execute(text("select set_config('dewpoint.start_held', 'on', true)"))


def run_input(request: RunRequest, version_id: uuid.UUID, envelope: Any, settings: Settings) -> RunInput:
    """A request's start: its frozen version and its envelope, with the deployment's run bounds."""
    return RunInput(
        tenant_id=str(request.tenant_id),
        run_id=str(request.id),
        version_id=str(version_id),
        trigger=envelope,
        mode=request.mode,
        max_run_duration_s=settings.max_run_duration_days * 86_400,
        cel_schedule_to_start_s=settings.cel_schedule_to_start_s,
    )


async def _slot_free(s: AsyncSession, tenant_id: uuid.UUID, platform: PlatformSettings) -> bool:
    """Whether the tenant runs fewer root runs than its limit, under its limits row's lock (§7.5)."""
    await s.execute(insert(TenantRunLimits).values(tenant_id=tenant_id).on_conflict_do_nothing())
    limits = (
        await s.execute(select(TenantRunLimits).where(TenantRunLimits.tenant_id == tenant_id).with_for_update())
    ).scalar_one()
    held = (await s.execute(select(func.count()).select_from(RunSlot).where(RunSlot.tenant_id == tenant_id))).scalar()
    return int(held or 0) < (limits.max_concurrent or platform.max_concurrent_runs)


async def _cancel(s: AsyncSession, request: RunRequest, reason: str, details: dict[str, object]) -> Cancelled:
    """`queued` → `cancelled`, explicit and audited; the run's row an earlier attempt wrote becomes terminal (§7.8)."""
    request.status, request.reason, request.ended_at = "cancelled", reason, datetime.now(UTC)
    await runs.finish_run(s, request.id, status="cancelled", ended_at=datetime.now(UTC), error_code=reason,
                          if_running=True)  # fmt: skip

    await audit.record(s, tenant_id=request.tenant_id, actor_id=None, action="run.request.cancel",
                       target_type="run_request", target_id=str(request.id), details=details)  # fmt: skip
    await s.flush()
    return Cancelled(reason)


# --- the start, and what its outcome does (§7.4, §7.8) -------------------------------------------------------------


@dataclass(frozen=True)
class Outcome:
    """What a start's answer means: `started` (accepted, or a verified duplicate, at `at` when Temporal says),
    `refused` (an attempt), `throttled` (certainly not started, no attempt), `collision` or `uncertain`. Apart from it,
    the call's own definitive answer (`answer`: `already_started` whatever `verify()` then found; None when uncertain)
    and, for `started`, the run it created (`run_id`, its first execution's)."""

    kind: str
    at: datetime | None = None
    detail: str = ""
    answer: str | None = None
    run_id: str | None = None
    identified: str | None = None  # the first run, shown carrying the recorded start request id (`started_by`)


@dataclass(frozen=True)
class Sent:
    """One send's own direct result: built only by the dispatcher, right after its own call (ruling 9)."""

    attempt: int
    answer: str | None  # answer_of(outcome); None when the call's result was uncertain
    run_id: str | None  # the call's first_execution_run_id, for `started`


def answer_of(outcome: Outcome) -> str | None:
    """The call's own definitive answer (ruling 3: `already_started` when Temporal said so, whatever `verify()` found),
    or None when it was uncertain."""
    return outcome.answer


def backoff(attempts: int) -> timedelta:
    """The wait before the next attempt after `attempts` confirmed refusals: 5 s, doubling, capped at 10 min."""
    return timedelta(seconds=min(5 * 2 ** (attempts - 1), 600))


def deny_reason(e: RPCError) -> str | None:
    """The reason a denial carries in its `PermissionDeniedFailure` details, read from the response itself; None when it
    carries none, or none that can be read (its attempt is then uncertain). Never the message: it's only words."""
    try:
        for detail in e.grpc_status.details:
            failure = PermissionDeniedFailure()
            if detail.Unpack(failure):
                return failure.reason
    except DecodeError:
        return None
    return None


async def start(client: Client, starting: Starting, *, reasons: bool = False) -> Outcome:
    """One start, `REJECT_DUPLICATE` under the run's server-built id (§6.1), with its own deadline, carrying the
    request's recorded start request id as one RPC attempt (`start_call`). Its answer is classified, never acted on
    here: no transaction is open across the call."""
    if starting.start_request_id is None:
        raise ValueError("A start is sent only with its request's recorded start request id.")
    workflow_id = run_workflow_id(starting.start.tenant_id, starting.start.run_id)
    try:
        with start_call.sending(starting.start_request_id):
            handle = await client.start_workflow(
                RunGraph.run, starting.start, id=workflow_id, task_queue=ENGINE_QUEUE,
                id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE, rpc_timeout=START_DEADLINE,
            )  # fmt: skip
        return Outcome("started", answer="started", run_id=getattr(handle, "first_execution_run_id", None) or "")
    except WorkflowAlreadyStartedError:  # the call's answer; what `verify()` finds is apart from it (ruling 3)
        return dataclasses.replace(await verify(client, starting), answer="already_started", run_id=None)
    except CodecRefusedError:  # the client seals the start again, and failed: it was never sent
        return Outcome("throttled", detail="unsealed", answer="throttled")
    except RPCError as e:
        if e.status == RPCStatusCode.PERMISSION_DENIED:  # told apart only by D12's own reasons, once confirmed
            reason = deny_reason(e) if reasons else None
            if reason == NOT_PERMITTED:
                return Outcome("not_permitted", answer="not_permitted")
            if reason == CHECK_UNAVAILABLE:
                return Outcome("check_unavailable", answer="check_unavailable")
            return Outcome("uncertain", detail=e.status.name)  # unconfirmed, unknown or missing: conservative
        if e.status in REFUSED:
            return Outcome("refused", detail=e.status.name, answer="refused")
        if e.status == RPCStatusCode.RESOURCE_EXHAUSTED:  # throttled before anything was created
            return Outcome("throttled", detail=e.status.name, answer="throttled")
        return Outcome("uncertain", detail=e.status.name)
    except Exception as e:  # a lost connection or a timeout: it may have been accepted
        return Outcome("uncertain", detail=type(e).__name__)


async def started_by(client: Client, workflow_id: str, request_id: uuid.UUID) -> Any | None:
    """The chain's first run (its `workflow_execution_info`) when its started event carries `request_id`, else None.
    Temporal attaches a start's request id to the execution with its started event, and describe returns it: identity
    without any key. A later run, or the id attached to any other event, is never taken for it."""
    latest = await client.workflow_service.describe_workflow_execution(
        DescribeWorkflowExecutionRequest(
            namespace=client.namespace, execution=WorkflowExecution(workflow_id=workflow_id)
        ),
        timeout=START_DEADLINE,
    )
    first = latest.workflow_execution_info.first_run_id or latest.workflow_execution_info.execution.run_id
    described = latest
    if first != latest.workflow_execution_info.execution.run_id:
        described = await client.workflow_service.describe_workflow_execution(
            DescribeWorkflowExecutionRequest(
                namespace=client.namespace, execution=WorkflowExecution(workflow_id=workflow_id, run_id=first)
            ),
            timeout=START_DEADLINE,
        )
    info = described.workflow_extended_info.request_id_infos.get(str(request_id))
    if info is None or info.event_type != EventType.EVENT_TYPE_WORKFLOW_EXECUTION_STARTED:
        return None
    return described.workflow_execution_info


async def verify(client: Client, starting: Starting) -> Outcome:
    """ "Already started" counts only once the execution is shown to be this request's. A request with a recorded start
    request id: only by that id, on its chain's first run's started event (`started_by`); anything else, a describe
    that fails included, is uncertain (the upgrade barrier's revision 17; the start-check slice's plan). A request
    without one (`starting` from before 0052): its started event's input, decoded with the tenant's key, has the
    request's tenant, run id, frozen version, mode and envelope (§7.4); anything else is an id collision, which the
    server-built ids make impossible. A history that can't be read leaves the start uncertain, for the reconciler."""
    workflow_id = run_workflow_id(starting.start.tenant_id, starting.start.run_id)
    if starting.start_request_id is not None:
        try:
            first_run = await started_by(client, workflow_id, starting.start_request_id)
        except Exception as e:
            return Outcome("uncertain", detail=f"unidentified ({type(e).__name__})")
        if first_run is None:
            return Outcome("uncertain", detail="unidentified")
        return Outcome("started", at=first_run.start_time.ToDatetime(tzinfo=UTC), identified=first_run.execution.run_id)
    try:
        first: Any = None
        async for event in client.get_workflow_handle(workflow_id).fetch_history_events(rpc_timeout=START_DEADLINE):
            first = event
            break
        attributes = first.workflow_execution_started_event_attributes
        context = WorkflowSerializationContext(namespace=client.namespace, workflow_id=workflow_id)
        [found] = await client.data_converter.with_context(context).decode(attributes.input.payloads, [RunInput])
    except Exception as e:
        return Outcome("uncertain", detail=f"unverified ({type(e).__name__})")
    ours, theirs = starting.start, found
    same = (theirs.tenant_id, theirs.run_id, theirs.version_id, theirs.mode, theirs.trigger) == (
        ours.tenant_id, ours.run_id, ours.version_id, ours.mode, ours.trigger,
    )  # fmt: skip
    if not same:
        return Outcome("collision")
    return Outcome("started", at=first.event_time.ToDatetime(tzinfo=UTC))


async def settle(
    sessionmaker: async_sessionmaker[AsyncSession], starting: Target, outcome: Outcome, *, audited: bool = False,
    sent: Sent | None = None, live: bool = False,
) -> str:  # fmt: skip
    """The outcome applied to the request, its slot and its run's row in one transaction (§7.8); what happened, for
    the cycle's report. A request no longer `starting` (the other of the dispatcher and the reconciler settled it) is
    left as it is. `audited`: the reconciler's settlements are audited (§2.4), a dead one as every dead one is. `sent`:
    the dispatcher's own send's direct result, which alone answers its row and moves its blocker (rulings 8, 9); the
    reconciler's settlements pass none. `live`: the reconciler's late sighting showed its execution live, so a
    `started` reserves the owed slot in this same transaction (`_owed`): stopped between them, neither stays."""
    async with sessionmaker() as s, s.begin():
        happened = await _settle(s, starting, outcome, sent, live)
        if audited and happened in ("started", "absent"):
            await audit.record(s, tenant_id=starting.tenant_id, actor_id=None, action="run.request.reconciled",
                               target_type="run_request", target_id=str(starting.request_id),
                               details={"outcome": happened})  # fmt: skip
        return happened


async def _settle(
    s: AsyncSession, starting: Target, outcome: Outcome, sent: Sent | None = None, live: bool = False
) -> str:
    await tenant_scope(s, starting.tenant_id)
    matched = False
    if sent is not None:  # the send's own answer first, on its own row, before the request is read (ruling 8)
        matched = await blockers.answered(s, starting.request_id, sent.attempt, sent.answer, sent.run_id)
        if not matched:
            log.warning("start_send_unmatched", request_id=str(starting.request_id), attempt=sent.attempt)
    request = (
        await s.execute(
            select(RunRequest)
            .where(RunRequest.id == starting.request_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    if request.status != "starting":
        if sent is not None and matched and sent.answer in ("started", None):  # a late `started`, or an uncertain one
            await blockers.unresolved(s, request.id)  # never `identified` from the reply alone (ruling 8)
        await _identified(s, request.id, outcome)
        return "moved"
    happened = await _settled(s, request, outcome)
    if happened == "started" and live:
        await _owed(s, request.tenant_id, request.id)
    if sent is not None and matched:
        await _blocker(s, request.id, outcome, sent, happened)
    elif sent is None and (outcome.kind == "collision" or happened == "absent"):  # the reconciler's: never removed
        await blockers.unresolved(s, request.id)
    await _identified(s, request.id, outcome)
    return happened


async def _identified(s: AsyncSession, request_id: uuid.UUID, outcome: Outcome) -> None:
    """The blocker identified, only where `verify` showed the recorded start request id on the first run's started
    event (`Outcome.identified`, from `started_by`): never from a reply, a sighting or a describe alone."""
    if outcome.identified is not None:
        await blockers.identified(s, request_id, outcome.identified)


async def _blocker(s: AsyncSession, request_id: uuid.UUID, outcome: Outcome, sent: Sent, happened: str) -> None:
    """The blocker's rule once a send settled its request (rulings 1 and 3): `unresolved` on an uncertain answer, a
    collision, or `already_started` with no own `started`; removed only where `removable` says; else as it is."""
    if sent.answer is None or outcome.kind == "collision" or sent.answer == "already_started":
        await blockers.unresolved(s, request_id)
        return
    if await blockers.removable(s, request_id, settling_started=happened == "started"):
        await blockers.remove(s, request_id)


async def _settled(s: AsyncSession, request: RunRequest, outcome: Outcome) -> str:
    """The outcome applied to a request still `starting`: what happened."""
    if outcome.kind == "started":
        await confirm(s, request, outcome.at)
        return "started"
    if outcome.kind == "uncertain":
        log.warning("start_uncertain", request_id=str(request.id), detail=outcome.detail)
        return "uncertain"  # starting, its slot held, for the reconciler (§7.6)
    if outcome.kind == "absent":
        # Its end write ran (its row records an end, or its slot was released): a start did happen, and only its
        # history is gone. Never queued or started again; left as it is for an operator (the owner's M3 reviews). A
        # spent request holds no slot (`_at_end`, `Held(SEND_CAP)`): its run's row alone says so (final review I1).
        if not (await _running(s, request.id) if _spent(request) else await _unstarted(s, request.id)):
            return "history_missing"
    await release(s, request.id)
    certain = ("refused", "throttled", "not_permitted", "check_unavailable")  # this attempt created nothing
    if outcome.kind in certain:  # its evidence goes, unless an earlier attempt is unproven: that one stays unproven
        await runs.settle_attempt(s, request.tenant_id, request.id, "refused")
    elif outcome.kind in ("absent", "collision"):  # an absence seen once fences nothing; a collision's exists
        await runs.settle_attempt(s, request.tenant_id, request.id, "unproven")
    if outcome.kind == "check_unavailable":
        request.unavailable_sends += 1
    if outcome.kind == "not_permitted":
        request.not_permitted_sends += 1
        if request.cancel_requested_at is None:  # a cancelled request's denial is expected
            log.warning("start_not_permitted", request_id=str(request.id))
    if outcome.kind in (*certain, "absent") and request.cancel_requested_at is not None:
        # A cancel recorded while it was starting, applied now that it didn't start (§7.8). A 10th refusal is
        # cancelled too: the user asked first.
        await _cancel(s, request, USER_CANCELLED, {"reason": USER_CANCELLED})
        return "cancelled"
    if outcome.kind == "collision":
        log.error("start_id_collision", request_id=str(request.id))
        await _dead(s, request, ID_COLLISION, COLLISION_MESSAGE)
        return "dead"
    if outcome.kind in ("refused", "not_permitted"):
        request.attempts += 1
    if _spent(request):  # its sends, or its refusals, are spent: never queued again
        return await _at_end(s, request)
    if outcome.kind == "check_unavailable":  # infrastructure: backs off, no refusal counted
        request.status = "queued"
        request.next_attempt_at = datetime.now(UTC) + backoff(request.unavailable_sends)
        return "check_unavailable"
    if outcome.kind == "throttled":
        request.status, request.next_attempt_at = "queued", datetime.now(UTC) + backoff(1)
        return "throttled"
    if outcome.kind == "absent":  # a trustworthy absence (§7.6): back in the queue, due at once, no attempt
        log.warning("start_absent", request_id=str(request.id))
        # by the clock `begin` reads, the database's: this process's may run ahead of it
        request.status, request.next_attempt_at = "queued", func.statement_timestamp()
        return "absent"
    request.status, request.next_attempt_at = "queued", datetime.now(UTC) + backoff(request.attempts)
    return "refused"


async def _owed(s: AsyncSession, tenant_id: uuid.UUID, run_id: uuid.UUID) -> None:
    """In a late `started`'s settling transaction, its execution seen live, its request without its slot (spent, it
    released it): the owed slot reserved again, even over the tenant's limit, under the run's row lock then the slot's
    (the end write's order: one in flight is waited for, then seen; an ended row is owed nothing). Over the limit:
    alerted, `start_over_limit` recorded (2b-4b M4 recovery, the owner's ruling 2 on the design)."""
    status = (await s.execute(text("select status from runs where id = :i for update"), {"i": run_id})).scalar()
    if status != "running":
        return
    # the limits row's lock, as `_slot_free` takes it: the slots are counted under it
    await s.execute(
        text("insert into tenant_run_limits (tenant_id) values (:t) on conflict do nothing"), {"t": tenant_id}
    )
    own = await s.execute(text("select max_concurrent from tenant_run_limits where tenant_id = :t for update"),
                          {"t": tenant_id})  # fmt: skip
    platform = await s.execute(text("select max_concurrent_runs from platform_settings where id = 1"))
    allowed = own.scalar() or platform.scalar()
    reserved = await s.execute(
        text("insert into run_slots (run_id, tenant_id) values (:i, :t) on conflict do nothing returning run_id"),
        {"i": run_id, "t": tenant_id},
    )
    if reserved.first() is None:  # it held its slot
        return
    held = (await s.execute(text("select count(*) from run_slots where tenant_id = :t"), {"t": tenant_id})).scalar()
    if allowed is not None and int(held or 0) > int(allowed):
        log.error("start_over_limit", request_id=str(run_id), held=int(held or 0), limit=int(allowed))
        await recovery.noted(s, tenant_id, recovery.START_OVER_LIMIT, run_id)


def _spent(request: RunRequest) -> bool:
    """Its sends are spent (`start_call.CAP`), or its confirmed refusals (MAX_ATTEMPTS: refusals counted before 0052
    counted sends can reach it first): it's never sent again."""
    return request.sends >= start_call.CAP or request.attempts >= MAX_ATTEMPTS


async def _at_end(s: AsyncSession, request: RunRequest) -> str:
    """A spent request (`_spent`): with any attempt unproven, left `starting`, without a slot, for the reconciler to
    observe and an operator to see: never ended for an uncertainty, whichever limit came first (the final review's M6).
    Otherwise ended, its reason saying which: refused (its refusals spent, or the start check refused some: an
    integrity failure), then an unavailable check (infrastructure), else Temporal's throttling."""
    unproven = await s.scalar(
        select(ExecutionEvidence.unproven).where(
            ExecutionEvidence.workflow_id == run_workflow_id(str(request.tenant_id), str(request.id)),
            ExecutionEvidence.run_id.is_(None),
        )
    )
    if unproven:
        log.error("start_unresolved_at_end", request_id=str(request.id))
        await recovery.noted(s, request.tenant_id, recovery.START_UNRESOLVED, request.id)
        return "unresolved"
    if request.attempts >= MAX_ATTEMPTS or request.not_permitted_sends > 0:  # refused for good; the check's: integrity
        await _refused(s, request)
    elif request.unavailable_sends > 0:
        log.error("start_check_unavailable", request_id=str(request.id))
        await _dead(s, request, START_CHECK_UNAVAILABLE, UNAVAILABLE_MESSAGE)
    else:
        await _dead(s, request, START_THROTTLED, THROTTLED_MESSAGE)
    return "dead"


async def _refused(s: AsyncSession, request: RunRequest) -> None:
    """Refused for good: `dead`, `start_refused`. When the start check refused any of its sends, and it wasn't
    cancelled (which `_settle` applies first), an integrity failure: alerted, its message naming the check, never
    Temporal (revision 17, section 2)."""
    if request.not_permitted_sends > 0:
        log.error("start_integrity_failure", request_id=str(request.id), reason=START_REFUSED)
        await _dead(s, request, START_REFUSED, NOT_PERMITTED_MESSAGE)
    else:
        await _dead(s, request, START_REFUSED, REFUSED_MESSAGE)


async def _running(s: AsyncSession, run_id: uuid.UUID) -> bool:
    """Its run's row still `running`, read under its lock: an end write in flight is waited for, then seen."""
    status = (await s.execute(text("select status from runs where id = :i for update"), {"i": run_id})).scalar()
    return bool(status == "running")


async def _unstarted(s: AsyncSession, run_id: uuid.UUID) -> bool:
    """An absence's evidence that no start happened: the run's pre-created row still `running` and the slot reserved at
    dispatch still held, which only the root's end write releases while a request is `starting`. Read under those rows'
    locks, taken in the end write's own order (row, then slot): an end write in flight is waited for and then seen. The
    slot is released here when it was held."""
    if not await _running(s, run_id):
        return False
    held = await s.execute(text("delete from run_slots where run_id = :i returning run_id"), {"i": run_id})
    return held.first() is not None


async def confirm(s: AsyncSession, request: RunRequest, at: datetime | None) -> None:
    """`starting` → `started`, idempotent and late-safe (§7.8): the run's `started_at` is set only if it has none, a
    terminal status is never overwritten, and no slot is reserved again (the root's end write releases it)."""
    request.status = "started"
    await s.execute(
        text("update runs set started_at = coalesce(started_at, :at) where id = :i"),
        {"at": at or datetime.now(UTC), "i": request.id},
    )


async def release(s: AsyncSession, run_id: uuid.UUID) -> None:
    await s.execute(text("delete from run_slots where run_id = :i"), {"i": run_id})


async def _dead(s: AsyncSession, request: RunRequest, reason: str, message: str) -> None:
    """`starting` → `dead`: terminal, its run failed with `start_failed`, its slot released (§7.8). Admins see it; a
    retry is a re-run."""
    request.status, request.reason, request.ended_at = "dead", reason, datetime.now(UTC)
    await runs.finish_run(s, request.id, status="failed", ended_at=datetime.now(UTC), error_code=START_FAILED,
                          error_message=message, if_running=True)  # fmt: skip

    await audit.record(s, tenant_id=request.tenant_id, actor_id=None, action="run.request.dead",
                       target_type="run_request", target_id=str(request.id), details={"reason": reason})  # fmt: skip


@dataclass
class Rotation:
    """Where the last cycle's pick of due tenants ended: the next cycle goes on from there, and wraps around once a
    pick comes back short. So a full pick of tenants that can't start (at their limit, waiting on a key) never keeps
    the others from being picked: every due tenant is reached within ⌈due tenants / CANDIDATES⌉ cycles (the
    whole-branch review)."""

    after: tuple[datetime, uuid.UUID] | None = None


async def dispatch_once(
    sessionmaker: async_sessionmaker[AsyncSession], client: Client, keys: KeySource, settings: Settings, build: Build,
    rotation: Rotation | None = None,
) -> dict[str, int]:  # fmt: skip
    """One cycle: each tenant's oldest due request, picked through `dispatch_candidates` (queue-selection metadata
    only) on from where `rotation` says the last pick ended, begun, started and settled in turn. Then, round after
    round while the pass has run less than `AGAIN_S` and its budget lasts, each tenant that has just started one, its
    next due request (`dispatch_next`), oldest first: each round takes every such tenant once, every request is begun
    alone, and a tenant that waits (its slots, say) or fails takes no more this cycle (the owner's ruling 1 on 2b-4b's
    M3 checkpoint: the per-tenant start path, about 0.9 starts a second at one a cycle). What happened, counted, for the
    report."""
    rotation = rotation if rotation is not None else Rotation()
    seal = sealer(client.data_converter, client.namespace)
    after_queued, after_request = rotation.after if rotation.after is not None else (None, None)
    async with sessionmaker() as s:
        picked = (
            await s.execute(
                text("select tenant_id, request_id, queued_at from dispatch_candidates(:n, :after_queued, :after_id)"),
                {"n": CANDIDATES, "after_queued": after_queued, "after_id": after_request},
            )
        ).all()
    rotation.after = (picked[-1].queued_at, picked[-1].request_id) if len(picked) == CANDIDATES else None
    counts: Counter[str] = Counter()
    done: list[tuple[uuid.UUID, uuid.UUID]] = []
    taken = _Taken(sessionmaker, client, seal, keys, settings, build, counts, done)
    with budget.passing("dispatch") as admitted:
        going = await taken.round(admitted(picked))
        if admitted.deferred:
            rotation.after = taken.last  # the next cycle goes on from the last it took
        while going and not admitted.deferred and time.monotonic() - admitted.started < AGAIN_S:
            async with sessionmaker() as s:
                following = (
                    await s.execute(
                        text("select tenant_id, request_id, queued_at from dispatch_next(:tenants)"), {"tenants": going}
                    )
                ).all()
            going = await taken.round(admitted(following))
    await failures.cleared(sessionmaker, [failures.DISPATCH], done)
    admitted.reported(counts, full=len(picked) >= CANDIDATES)
    return dict(counts)


@dataclass
class _Taken:
    """A pass's candidates, taken a round at a time: what happened, counted, and those with an outcome (`done`: their
    dispatch failures cleared; one left waiting, or that another dispatcher had, neither counts nor clears: the fresh
    M3 review 2's I1). A request is taken once a pass: one found again (still queued, whatever its start said) ends its
    tenant's rounds."""

    sessionmaker: async_sessionmaker[AsyncSession]
    client: Client
    seal: Seal
    keys: KeySource
    settings: Settings
    build: Build
    counts: Counter[str]
    done: list[tuple[uuid.UUID, uuid.UUID]]
    last: tuple[datetime, uuid.UUID] | None = None
    seen: set[uuid.UUID] = field(default_factory=set)

    async def round(self, candidates: Iterable[Sequence[Any]]) -> list[uuid.UUID]:
        """Each candidate begun, started and settled in turn: the tenants that started theirs."""
        started: list[uuid.UUID] = []
        for tenant_id, request_id, queued_at in candidates:
            if request_id in self.seen:
                continue
            self.seen.add(request_id)
            self.last = (queued_at, request_id)
            try:
                happened = await _dispatch(self.sessionmaker, self.client, self.seal, self.keys, self.settings,
                                           self.build, tenant_id, request_id)  # fmt: skip
            except Exception as e:  # a bug or an outage: the request stays as it was, and the cycle goes on (M2 review)
                log.error(
                    "dispatch_failed", tenant_id=str(tenant_id), request_id=str(request_id), error=type(e).__name__
                )
                self.counts["error"] += 1
                await failures.failed(self.sessionmaker, tenant_id, failures.DISPATCH, request_id, e)  # bounded (D10)
                continue
            if happened is not None:
                self.counts[happened] += 1
                if happened not in WAITING:
                    self.done.append((tenant_id, request_id))
            if happened == "started":
                started.append(tenant_id)
        return started


async def _dispatch(
    sessionmaker: async_sessionmaker[AsyncSession], client: Client, seal: Seal, keys: KeySource, settings: Settings,
    build: Build, tenant_id: uuid.UUID, request_id: uuid.UUID,
) -> str | None:  # fmt: skip
    """One candidate begun, started and settled: what happened to it; None when another dispatcher had it."""
    outcome = await begin(sessionmaker, seal, settings, keys, tenant_id=tenant_id, request_id=request_id, build=build)
    if isinstance(outcome, Starting):
        await _after_starting_commit(outcome.request_id)
        answered = await start(client, outcome, reasons=settings.start_check_reasons_confirmed)
        await _after_start_call(outcome.request_id)
        if outcome.attempt is None:
            raise RuntimeError("A start is sent only once its send is counted and recorded.")
        answer = answer_of(answered)
        sent = Sent(outcome.attempt, answer, answered.run_id if answer == "started" else None)
        return await settle(sessionmaker, outcome, answered, sent=sent)
    return outcome.reason if outcome is not None else None
