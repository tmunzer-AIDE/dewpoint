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
class RetirePreview:
    entry: Entry
    state: str
    active_refs: tuple[ActiveRef, ...]  # enabled workflows whose active closure uses the entry
    affected_versions: int  # every version whose closure uses it
    applied: bool = False
    # Sub-project 2b adds the queued run requests a forced retirement would cancel.


class ReferencedError(RuntimeError):
    def __init__(self, preview: RetirePreview) -> None:
        super().__init__(f"{preview.entry} is used by {len(preview.active_refs)} active workflow(s)")
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
    affected = (await s.execute(select(func.count()).select_from(WorkflowVersion).where(uses))).scalar_one()
    return RetirePreview(entry=entry, state=state, active_refs=refs, affected_versions=int(affected))


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
    """Normal path: refuse while an enabled workflow's active closure uses the entry. Forced path: return the
    preview unless `confirm`; with `confirm`, affected workflows stop being startable and each tenant gets an audit
    entry. Runs inside the caller's transaction (READ COMMITTED); the caller commits."""
    await lock_exclusive(s, entry)  # first: every statement below sees references committed before the lock
    current = (await states(s, [entry]))[entry]
    if current == "missing":
        raise UnknownEntryError(str(entry))
    preview = await _preview(s, entry, current)
    if current == "retired":
        return replace(preview, applied=True)
    if preview.active_refs and not force:
        raise ReferencedError(preview)
    if preview.active_refs and not confirm:
        return preview
    await _set_state(s, entry, "retired")
    await record(
        s,
        tenant_id=None,
        actor_id=actor_id,
        action="lifecycle.retire",
        target_type=entry.kind,
        target_id=entry.key,
        details={"forced": bool(preview.active_refs), "active_workflows": len(preview.active_refs)},
    )
    by_tenant: dict[uuid.UUID, list[str]] = {}
    for ref in preview.active_refs:
        by_tenant.setdefault(ref.tenant_id, []).append(str(ref.workflow_id))
    for tenant_id, workflow_ids in sorted(by_tenant.items()):
        await tenant_scope(s, tenant_id)  # tenant audit entries need the tenant context; nothing reads after this
        await record(
            s,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="lifecycle.retire",
            target_type=entry.kind,
            target_id=entry.key,
            details={"forced": True, "workflows": workflow_ids},
        )
    return replace(preview, applied=True)
