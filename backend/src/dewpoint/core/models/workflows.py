# SPDX-License-Identifier: Apache-2.0
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from dewpoint.core.models.base import Base, Timestamps, UUIDPk


class Workflow(UUIDPk, Timestamps, Base):
    __tablename__ = "workflows"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name"),
        UniqueConstraint("id", "tenant_id", name="workflows_tenant"),  # what a row of its tenant names (#35)
        # A version of this workflow (and so of its tenant). The two tables name each other: altered in after both.
        ForeignKeyConstraint(
            ["active_version_id", "id", "tenant_id"],
            ["workflow_versions.id", "workflow_versions.workflow_id", "workflow_versions.tenant_id"],
            name="workflows_active_version_fk",
            use_alter=True,
        ),
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(100))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    active_version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    draft: Mapped[dict[str, Any]] = mapped_column(JSONB)
    draft_revision: Mapped[int] = mapped_column(Integer, default=1)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )


class WorkflowVersion(UUIDPk, Base):
    """Immutable (a trigger rejects UPDATE and DELETE). Insert once, at publish."""

    __tablename__ = "workflow_versions"
    __table_args__ = (
        UniqueConstraint("workflow_id", "number"),
        UniqueConstraint("id", "workflow_id", name="workflow_versions_id_workflow"),
        UniqueConstraint("id", "workflow_id", "tenant_id", name="workflow_versions_tenant"),  # #35's version keys
        ForeignKeyConstraint(
            ["workflow_id", "tenant_id"], ["workflows.id", "workflows.tenant_id"], name="workflow_versions_workflow"
        ),
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"))
    workflow_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    number: Mapped[int] = mapped_column(Integer)
    graph: Mapped[dict[str, Any]] = mapped_column(JSONB)
    node_refs: Mapped[list[str]] = mapped_column(ARRAY(Text))
    engine_abi: Mapped[int] = mapped_column(Integer)
    cel_profile: Mapped[str] = mapped_column(String(120), ForeignKey("cel_profiles.profile"))
    connection_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID(as_uuid=True)), default=list)
    subflow_version_ids: Mapped[dict[str, str]] = mapped_column(JSONB, default=dict)
    failure_handler_version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    input_schema: Mapped[dict[str, Any]] = mapped_column(JSONB)
    output_schema: Mapped[dict[str, Any]] = mapped_column(JSONB)
    vars_schema: Mapped[dict[str, Any]] = mapped_column(JSONB)
    expressions: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    tainted_sites: Mapped[list[Any]] = mapped_column(JSONB, default=list)  # [{node, field}] (2b spec §4.1)
    output_taint: Mapped[dict[str, Any] | None] = mapped_column(JSONB)  # each output's taint; None: unknown
    open_scopes_cap: Mapped[int | None] = mapped_column(Integer)  # computed at publish, pinned (2b spec §5.3)
    loop_depth: Mapped[int | None] = mapped_column(Integer)  # its deepest loop nesting, D
    closure_version_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID(as_uuid=True)))
    closure_workflow_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID(as_uuid=True)))
    closure_node_refs: Mapped[list[str]] = mapped_column(ARRAY(Text))
    closure_cel_profiles: Mapped[list[str]] = mapped_column(ARRAY(Text))
    closure_depth: Mapped[int] = mapped_column(Integer)
    graph_hash: Mapped[str] = mapped_column(String(64))
    version_hash: Mapped[str] = mapped_column(String(64))
    published_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
