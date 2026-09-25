# SPDX-License-Identifier: Apache-2.0
"""Storage for workflows and their immutable versions. Graph validation is in the engine; apps wires the two."""

import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func, select, update
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


async def get_workflow(
    s: AsyncSession, tenant_id: uuid.UUID, workflow_id: uuid.UUID, *, for_update: bool = False
) -> Workflow | None:
    q = select(Workflow).where(Workflow.id == workflow_id, Workflow.tenant_id == tenant_id)
    if for_update:
        q = q.with_for_update()
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


async def blocked_by(s: AsyncSession, version: WorkflowVersion) -> list[str]:
    """Lifecycle entries in the version's closure that stop it from running (retired or missing)."""
    current = await lifecycle.states(s, lifecycle.entries_for(version.closure_node_refs, version.closure_cel_profiles))
    return [e.key for e in lifecycle.not_executable(current)]
