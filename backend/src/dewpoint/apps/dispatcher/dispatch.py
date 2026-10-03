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

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime

import structlog
from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from temporalio.converter import DataConverter, WorkflowSerializationContext

from dewpoint.apps.dispatcher.observe import REQUIRED, Build
from dewpoint.core.audit import service as audit
from dewpoint.core.claims import service as claims
from dewpoint.core.claims.cipher import ClaimCipher
from dewpoint.core.config import Settings
from dewpoint.core.crypto.keys import KeySource
from dewpoint.core.db import tenant_scope
from dewpoint.core.models.platform import PlatformSettings
from dewpoint.core.models.requests import RunRequest, RunSlot, TenantRunLimits
from dewpoint.core.models.tenancy import Tenant
from dewpoint.core.models.workflows import WorkflowVersion
from dewpoint.core.platform.service import PRODUCTION, workers_ready
from dewpoint.core.plugins import lifecycle
from dewpoint.core.runs import service as runs
from dewpoint.core.workflows.service import other_abi
from dewpoint.engine.runtime.activities import RunInput
from dewpoint.engine.runtime.ids import run_workflow_id

log = structlog.get_logger("dewpoint.dispatcher")
GATE_LOCK = "dewpoint:production-gate"


def tenant_lock(tenant_id: uuid.UUID) -> str:
    return f"dewpoint:tenant:{tenant_id}"


@dataclass(frozen=True)
class Starting:
    """A request marked `starting`: what its start sends."""

    request_id: uuid.UUID
    tenant_id: uuid.UUID
    start: RunInput


@dataclass(frozen=True)
class Waiting:
    """A request left queued, no attempt counted: `gate_off`, `environment_not_recorded`, `tenant_erasing`,
    `workers_not_ready`, `no_slot` or `key_unusable`."""

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
) -> Starting | Waiting | Cancelled | None:
    """One due request's starting transaction. None: no longer due, or another dispatcher holds it."""
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
) -> Starting | Waiting | Cancelled | None:
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
    platform = await s.get(PlatformSettings, 1, populate_existing=True)
    if platform is None:
        return Waiting("environment_not_recorded")
    if platform.environment == PRODUCTION and not platform.production_runs:
        return Waiting("gate_off")
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
    await lifecycle.lock_shared(s, entries)
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
    try:  # the tenant's key opens the envelope and seals the start: one that doesn't work stops it (§2.3)
        envelope = await claims.read_envelope(s, ClaimCipher(keys), tenant_id, request_id=request.id)
        start = RunInput(
            tenant_id=str(tenant_id),
            run_id=str(request.id),
            version_id=str(version.id),
            trigger=envelope,
            mode=request.mode,
            max_run_duration_s=settings.max_run_duration_days * 86_400,
            cel_schedule_to_start_s=settings.cel_schedule_to_start_s,
        )
        await seal(start)
    except claims.EnvelopeUnavailableError:
        raise  # the request's foreign key keeps its envelope: a bug, never a key's fault
    except Exception as e:
        log.warning("dispatch_waiting", reason="key_unusable", error=type(e).__name__)
        return Waiting("key_unusable")
    s.add(RunSlot(run_id=request.id, tenant_id=tenant_id))
    await runs.precreate_run(
        s, run_id=request.id, tenant_id=tenant_id, workflow_id=request.workflow_id, version_id=version.id,
        mode=request.mode, started_by=request.actor_id, queued_at=request.queued_at,
    )  # fmt: skip
    request.status = "starting"
    await s.flush()
    return Starting(request.id, tenant_id, start)


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
