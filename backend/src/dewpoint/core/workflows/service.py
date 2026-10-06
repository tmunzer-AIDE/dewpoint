# SPDX-License-Identifier: Apache-2.0
"""Storage for workflows and their immutable versions. Graph validation is in the engine; apps wires the two."""

import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from dewpoint.core.audit.service import record
from dewpoint.core.http import TenantContext
from dewpoint.core.models.workflows import Workflow, WorkflowVersion
from dewpoint.core.plugins import lifecycle


class DraftConflictError(Exception):
    def __init__(self, current_revision: int) -> None:
        super().__init__(f"draft is at revision {current_revision}")
        self.current_revision = current_revision


async def create_workflow(s: AsyncSession, ctx: TenantContext, *, name: str, draft: dict[str, Any]) -> Workflow:
    wf = Workflow(
        id=uuid.uuid4(),
        tenant_id=ctx.tenant_id,
        name=name,
        enabled=True,
        draft=draft,
        draft_revision=1,
        created_by=ctx.user.id,
    )
    s.add(wf)
    await s.flush()
    await s.refresh(wf)
    await record(
        s,
        tenant_id=ctx.tenant_id,
        actor_id=ctx.user.id,
        action="workflow.create",
        target_type="workflow",
        target_id=str(wf.id),
        details={"name": name},
    )
    return wf


def _admission_key(workflow_id: uuid.UUID) -> str:
    return f"dewpoint:workflow:{workflow_id}"


@dataclass(frozen=True)
class AdmissionState:
    """What admission checks of a workflow, as the database has it."""

    enabled: bool
    active_version_id: uuid.UUID | None


async def lock_for_admission(s: AsyncSession, tenant_id: uuid.UUID, workflow_id: uuid.UUID) -> AdmissionState | None:
    """Take the workflow's admission lock, then read what admission checks, which holds until this transaction ends
    (spec §4.5). None if the tenant has no such workflow.

    Admission takes the lock *shared*, and keeps it until the run is inserted. Every change to a workflow takes it
    *exclusively* first (`get_workflow` with `for_update`). So a change either commits before admission reads, or
    waits until the run exists. Like the lifecycle locks, it is a transaction-scoped advisory lock: a row lock would
    need UPDATE on `workflows`, which the dispatch role must not have.

    The fields are read as columns, never through a `Workflow` the session already holds: the ORM would return that
    object as it was loaded, from before the change this lock waited for."""
    await lifecycle.assert_read_committed(s)  # the read after the lock must see what a change committed
    await s.execute(
        text("select pg_advisory_xact_lock_shared(hashtextextended(:k, 0))"), {"k": _admission_key(workflow_id)}
    )
    row = (
        await s.execute(
            select(Workflow.enabled, Workflow.active_version_id).where(
                Workflow.id == workflow_id, Workflow.tenant_id == tenant_id
            )
        )
    ).one_or_none()
    return None if row is None else AdmissionState(enabled=row.enabled, active_version_id=row.active_version_id)


async def get_workflow(
    s: AsyncSession, tenant_id: uuid.UUID, workflow_id: uuid.UUID, *, for_update: bool = False
) -> Workflow | None:
    """With `for_update`, take the workflow's admission lock exclusively (`lock_for_admission`), then its row lock.
    Both are held until the change commits, so a run is admitted either before the change or after it. The admission
    lock comes first: a change waiting for an admission holds nothing that admission's insert could need. The locked
    row overwrites any `Workflow` the session already holds, so the writer acts on what's committed."""
    q = select(Workflow).where(Workflow.id == workflow_id, Workflow.tenant_id == tenant_id)
    if for_update:
        await s.execute(
            text("select pg_advisory_xact_lock(hashtextextended(:k, 0))"), {"k": _admission_key(workflow_id)}
        )
        q = q.with_for_update().execution_options(populate_existing=True)
    return (await s.execute(q)).scalar_one_or_none()


async def list_workflows(s: AsyncSession, tenant_id: uuid.UUID) -> list[Workflow]:
    rows = await s.execute(select(Workflow).where(Workflow.tenant_id == tenant_id).order_by(Workflow.name))
    return list(rows.scalars())


async def save_draft(s: AsyncSession, wf: Workflow, *, expected_revision: int, draft: dict[str, Any]) -> int:
    """Compare-and-swap on draft_revision: a stale editor gets DraftConflictError instead of overwriting."""
    revision = (
        await s.execute(
            update(Workflow)
            .where(Workflow.id == wf.id, Workflow.draft_revision == expected_revision)
            .values(draft=draft, draft_revision=Workflow.draft_revision + 1, updated_at=func.now())
            .returning(Workflow.draft_revision)
            .execution_options(synchronize_session=False)
        )
    ).scalar_one_or_none()
    if revision is None:
        current = (await s.execute(select(Workflow.draft_revision).where(Workflow.id == wf.id))).scalar_one()
        raise DraftConflictError(int(current))
    return int(revision)


async def locked_active_version(s: AsyncSession, workflow_id: uuid.UUID) -> WorkflowVersion | None:
    """The workflow's active version, read after this transaction updated its row (`save_draft`): the row lock it holds
    until commit keeps an activation from changing it before the answer is sent. A `Workflow` read before the update
    may name an older one (`save_draft` updates with `synchronize_session=False`)."""
    q = (
        select(WorkflowVersion)
        .join(Workflow, Workflow.active_version_id == WorkflowVersion.id)
        .where(Workflow.id == workflow_id)
    )
    return (await s.execute(q)).scalar_one_or_none()


async def update_workflow(
    s: AsyncSession, ctx: TenantContext, wf: Workflow, *, name: str | None, enabled: bool | None
) -> Workflow:
    changes: dict[str, object] = {}
    if name is not None and name != wf.name:
        wf.name = name
        changes["name"] = name
    if enabled is not None and enabled != wf.enabled:
        wf.enabled = enabled
        changes["enabled"] = enabled
    if changes:
        await s.flush()
        await s.refresh(wf)
        await record(
            s,
            tenant_id=wf.tenant_id,
            actor_id=ctx.user.id,
            action="workflow.update",
            target_type="workflow",
            target_id=str(wf.id),
            details=changes,
        )
    return wf


@dataclass(frozen=True)
class NewVersion:
    id: uuid.UUID
    graph: dict[str, Any]
    node_refs: list[str]
    engine_abi: int
    cel_profile: str
    subflow_version_ids: dict[str, str]
    failure_handler_version_id: uuid.UUID | None
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    vars_schema: dict[str, Any]
    closure_version_ids: list[uuid.UUID]
    closure_workflow_ids: list[uuid.UUID]
    closure_node_refs: list[str]
    closure_cel_profiles: list[str]
    closure_depth: int
    graph_hash: str
    version_hash: str
    expressions: list[Any] = field(default_factory=list)
    connection_ids: list[uuid.UUID] = field(default_factory=list)
    tainted_sites: list[Any] = field(default_factory=list)
    output_taint: dict[str, Any] | None = None
    declassified: list[dict[str, str]] = field(default_factory=list)  # for the audit entry only (§4.3)
    open_scopes_cap: int | None = None  # computed at publish, pinned (2b spec §5.3)
    loop_depth: int | None = None


async def insert_version(s: AsyncSession, ctx: TenantContext, wf: Workflow, new: NewVersion) -> WorkflowVersion:
    """Insert the next version and make it active. The caller holds the workflow row lock."""
    latest = await s.execute(
        select(func.coalesce(func.max(WorkflowVersion.number), 0)).where(WorkflowVersion.workflow_id == wf.id)
    )
    number = int(latest.scalar_one()) + 1
    version = WorkflowVersion(
        id=new.id,
        tenant_id=wf.tenant_id,
        workflow_id=wf.id,
        number=number,
        graph=new.graph,
        node_refs=new.node_refs,
        engine_abi=new.engine_abi,
        cel_profile=new.cel_profile,
        connection_ids=new.connection_ids,
        subflow_version_ids=new.subflow_version_ids,
        failure_handler_version_id=new.failure_handler_version_id,
        input_schema=new.input_schema,
        output_schema=new.output_schema,
        vars_schema=new.vars_schema,
        expressions=new.expressions,
        tainted_sites=new.tainted_sites,
        output_taint=new.output_taint,
        open_scopes_cap=new.open_scopes_cap,
        loop_depth=new.loop_depth,
        closure_version_ids=new.closure_version_ids,
        closure_workflow_ids=new.closure_workflow_ids,
        closure_node_refs=new.closure_node_refs,
        closure_cel_profiles=new.closure_cel_profiles,
        closure_depth=new.closure_depth,
        graph_hash=new.graph_hash,
        version_hash=new.version_hash,
        published_by=ctx.user.id,
    )
    s.add(version)
    await s.flush()
    await s.refresh(version)
    wf.active_version_id = version.id
    await s.flush()
    await record(
        s,
        tenant_id=wf.tenant_id,
        actor_id=ctx.user.id,
        action="workflow.publish",
        target_type="workflow",
        target_id=str(wf.id),
        details={
            "version": number,
            "version_id": str(version.id),
            "graph_hash": new.graph_hash,
            "version_hash": new.version_hash,
            "closure_depth": new.closure_depth,
            **({"declassify": new.declassified} if new.declassified else {}),
        },
    )
    return version


async def set_active(s: AsyncSession, ctx: TenantContext, wf: Workflow, version: WorkflowVersion) -> None:
    wf.active_version_id = version.id
    await s.flush()
    await record(
        s,
        tenant_id=wf.tenant_id,
        actor_id=ctx.user.id,
        action="workflow.activate",
        target_type="workflow",
        target_id=str(wf.id),
        details={"version": version.number, "version_id": str(version.id)},
    )


async def get_version(s: AsyncSession, workflow_id: uuid.UUID, version_id: uuid.UUID) -> WorkflowVersion | None:
    q = select(WorkflowVersion).where(WorkflowVersion.id == version_id, WorkflowVersion.workflow_id == workflow_id)
    return (await s.execute(q)).scalar_one_or_none()


async def list_versions(s: AsyncSession, workflow_id: uuid.UUID) -> list[WorkflowVersion]:
    q = (
        select(WorkflowVersion)
        .where(WorkflowVersion.workflow_id == workflow_id)
        .order_by(WorkflowVersion.number.desc())
    )
    return list((await s.execute(q)).scalars())


async def active_versions(
    s: AsyncSession, tenant_id: uuid.UUID, workflow_ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, WorkflowVersion]:
    ids = sorted(set(workflow_ids), key=str)
    if not ids:
        return {}
    rows = await s.execute(
        select(Workflow.id, WorkflowVersion)
        .join(WorkflowVersion, WorkflowVersion.id == Workflow.active_version_id)
        .where(Workflow.tenant_id == tenant_id, Workflow.id.in_(ids))
    )
    return {workflow_id: version for workflow_id, version in rows}


async def other_abi(s: AsyncSession, version_ids: Iterable[uuid.UUID], abi: int) -> list[tuple[uuid.UUID, int]]:
    """The versions among `version_ids` published for an engine ABI other than `abi`, each with its own. A version
    runs only on a build of its ABI (spec §7)."""
    ids = sorted(set(version_ids), key=str)
    if not ids:
        return []
    rows = await s.execute(
        select(WorkflowVersion.id, WorkflowVersion.engine_abi)
        .where(WorkflowVersion.id.in_(ids), WorkflowVersion.engine_abi != abi)
        .order_by(WorkflowVersion.id)
    )
    return [(version_id, version_abi) for version_id, version_abi in rows]


async def blocked_by_many(s: AsyncSession, versions: Iterable[WorkflowVersion]) -> dict[uuid.UUID, list[str]]:
    """Each version's lifecycle entries that stop it from running (retired or missing), in one read of the states of
    every entry any of them uses."""
    entries = {v.id: lifecycle.entries_for(v.closure_node_refs, v.closure_cel_profiles) for v in versions}
    current = await lifecycle.states(s, {e for used in entries.values() for e in used})
    return {
        version_id: [e.key for e in lifecycle.not_executable({e: current[e] for e in used})]
        for version_id, used in entries.items()
    }


async def blocked_by(s: AsyncSession, version: WorkflowVersion) -> list[str]:
    """Lifecycle entries in the version's closure that stop it from running (retired or missing)."""
    return (await blocked_by_many(s, [version]))[version.id]
