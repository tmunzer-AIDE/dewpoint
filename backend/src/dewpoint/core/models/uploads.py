# SPDX-License-Identifier: Apache-2.0
"""A CSV staged for a start (engine 2b spec §8.1): its headers and cells encrypted, its uploader, its workflow, and
when it expires. A start consumes it by clearing its cells; only retention deletes the row (§10.3)."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, ForeignKeyConstraint, Integer, LargeBinary, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from dewpoint.core.models.base import Base


class CsvUpload(Base):
    __tablename__ = "csv_uploads"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workflow_id", "tenant_id"], ["workflows.id", "workflows.tenant_id"], name="csv_uploads_workflow"
        ),
    )  # of its own tenant (#35)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"))
    owner_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    workflow_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    staged: Mapped[bytes | None] = mapped_column(LargeBinary)
    file_digest: Mapped[bytes] = mapped_column(LargeBinary)
    digest_key_version: Mapped[int] = mapped_column(Integer)
    size_bytes: Mapped[int] = mapped_column(Integer)
    row_count: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CsvMapping(Base):
    """A workflow's saved default mapping (§8.1): sealed, with the version it was saved against; `stale_at` once an
    upload found it no longer fits the active version's declaration, until a new one is saved."""

    __tablename__ = "csv_mappings"
    __table_args__ = (  # a workflow of its own tenant, and a version of that workflow (#35)
        ForeignKeyConstraint(
            ["workflow_id", "tenant_id"], ["workflows.id", "workflows.tenant_id"], name="csv_mappings_workflow"
        ),
        ForeignKeyConstraint(
            ["saved_against", "workflow_id", "tenant_id"],
            ["workflow_versions.id", "workflow_versions.workflow_id", "workflow_versions.tenant_id"],
            name="csv_mappings_version",
        ),
    )
    workflow_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"))
    mapping: Mapped[bytes] = mapped_column(LargeBinary)
    saved_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    saved_against: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    saved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    stale_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
