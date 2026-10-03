# SPDX-License-Identifier: Apache-2.0
"""A CSV staged for a start (engine 2b spec §8.1): its headers and cells encrypted, its uploader, its workflow, and
when it expires. A start consumes it by clearing its cells; only retention deletes the row (§10.3)."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, LargeBinary, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from dewpoint.core.models.base import Base


class CsvUpload(Base):
    __tablename__ = "csv_uploads"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"))
    owner_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    workflow_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("workflows.id"))
    staged: Mapped[bytes | None] = mapped_column(LargeBinary)
    file_digest: Mapped[bytes] = mapped_column(LargeBinary)
    digest_key_version: Mapped[int] = mapped_column(Integer)
    size_bytes: Mapped[int] = mapped_column(Integer)
    row_count: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
