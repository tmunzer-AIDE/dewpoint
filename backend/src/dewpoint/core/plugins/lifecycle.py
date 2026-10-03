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
from dewpoint.core.models.requests import RunRequest
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
class AffectedVersion:
    """A version whose closure uses the entry. After retirement it can no longer run, be activated or be enabled."""

    tenant_id: uuid.UUID
    workflow_id: uuid.UUID
    workflow_name: str
    version_id: uuid.UUID
    version_number: int
    active: bool  # it is its workflow's active version
    enabled: bool  # its workflow is enabled


@dataclass(frozen=True)
class QueuedRef:
    """A run request that hasn't started, frozen on a version whose closure uses the entry: a `queued` one, which a
    forced retirement cancels, or a `starting` one, which may still reach Temporal and is left to start or come back."""

    tenant_id: uuid.UUID
    request_id: uuid.UUID
    workflow_id: uuid.UUID
    version_id: uuid.UUID
    status: str


@dataclass(frozen=True)
class RetirePreview:
    entry: Entry
    state: str
    active_refs: tuple[ActiveRef, ...]  # enabled workflows whose active closure uses the entry
    affected: tuple[AffectedVersion, ...]  # every version whose closure uses it, per tenant (spec §4.5 preview)
    applied: bool = False
    queued: tuple[QueuedRef, ...] = ()  # requests that haven't started: a forced retirement cancels the queued ones


class ReferencedError(RuntimeError):
    def __init__(self, preview: RetirePreview) -> None:
        super().__init__(
            f"{preview.entry} is used by {len(preview.active_refs)} active workflow(s) and "
            f"{len(preview.queued)} run request(s) that haven't started"
        )
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
    affected = await s.execute(
        select(
            Workflow.tenant_id,
            Workflow.id,
            Workflow.name,
            WorkflowVersion.id,
            WorkflowVersion.number,
            Workflow.active_version_id.is_not_distinct_from(WorkflowVersion.id),  # never NULL
            Workflow.enabled,
        )
        .join(Workflow, Workflow.id == WorkflowVersion.workflow_id)
        .where(uses)
        .order_by(Workflow.tenant_id, Workflow.name, WorkflowVersion.number)
    )
    versions = tuple(AffectedVersion(*row) for row in affected)
    unstarted = await s.execute(
        select(RunRequest.tenant_id, RunRequest.id, RunRequest.workflow_id, WorkflowVersion.id, RunRequest.status)
        .join(WorkflowVersion, WorkflowVersion.id == RunRequest.workflow_version_id)
        .where(uses, RunRequest.status.in_(("queued", "starting")))
        .order_by(RunRequest.tenant_id, RunRequest.queued_at, RunRequest.id)
    )
    queued = tuple(QueuedRef(*row) for row in unstarted)
    return RetirePreview(entry=entry, state=state, active_refs=refs, affected=versions, queued=queued)


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
    """Normal path: refuse while an enabled workflow's active closure, or a request that hasn't started, uses the
    entry. Forced path: return the preview unless `confirm`; with `confirm`, affected workflows stop being startable,
    every queued request on them is cancelled explicitly (`node_type_retired`, `cel_profile_retired`), and each tenant
    gets an audit entry. A `starting` request is left alone: it either starts, and a started run is never broken, or
    comes back to the queue, where dispatch's defensive check cancels it. Runs inside the caller's transaction (READ
    COMMITTED); the caller commits."""
    await lock_exclusive(s, entry)  # first: every statement below sees references committed before the lock
    current = (await states(s, [entry]))[entry]
    if current == "missing":
        raise UnknownEntryError(str(entry))
    preview = await _preview(s, entry, current)
    if current == "retired":
        return replace(preview, applied=True)
    referenced = bool(preview.active_refs or preview.queued)
    if referenced and not force:
        raise ReferencedError(preview)
    if referenced and not confirm:
        return preview
    await _set_state(s, entry, "retired")
    cancelled = [q for q in preview.queued if q.status == "queued"]
    if cancelled:
        reason = "node_type_retired" if entry.kind == "node" else "cel_profile_retired"
        await s.execute(
            update(RunRequest)
            .where(RunRequest.id.in_([q.request_id for q in cancelled]), RunRequest.status == "queued")
            .values(status="cancelled", reason=reason, ended_at=func.now())
        )
    await record(
        s,
        tenant_id=None,
        actor_id=actor_id,
        action="lifecycle.retire",
        target_type=entry.kind,
        target_id=entry.key,
        details={"forced": referenced, "active_workflows": len(preview.active_refs), "requests": len(cancelled)},
    )
    workflows: dict[uuid.UUID, list[str]] = {}
    requests: dict[uuid.UUID, list[str]] = {}
    for ref in preview.active_refs:
        workflows.setdefault(ref.tenant_id, []).append(str(ref.workflow_id))
    for q in cancelled:
        requests.setdefault(q.tenant_id, []).append(str(q.request_id))
    for tenant_id in sorted(workflows.keys() | requests.keys()):
        await tenant_scope(s, tenant_id)  # tenant audit entries need the tenant context; nothing reads after this
        await record(
            s,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="lifecycle.retire",
            target_type=entry.kind,
            target_id=entry.key,
            details={
                "forced": True,
                "workflows": workflows.get(tenant_id, []),
                "requests": requests.get(tenant_id, []),
            },
        )
    return replace(preview, applied=True)
