# SPDX-License-Identifier: Apache-2.0
"""Read-only mappings. Rows are written only by the audit_append() SQL function."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, LargeBinary, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from dewpoint.core.models.base import Base


class AuditEntry(Base):
    __tablename__ = "audit_log"
    seq: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    scope: Mapped[str] = mapped_column(Text)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    action: Mapped[str] = mapped_column(Text)
    target_type: Mapped[str] = mapped_column(Text)
    target_id: Mapped[str] = mapped_column(Text)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    prev_hash: Mapped[bytes] = mapped_column(LargeBinary)
    hash: Mapped[bytes] = mapped_column(LargeBinary)


class AuditAnchor(Base):
    __tablename__ = "audit_anchors"
    __table_args__ = (UniqueConstraint("scope", "seq", name="audit_anchors_scope_seq_key"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    scope: Mapped[str] = mapped_column(Text)
    seq: Mapped[int] = mapped_column(BigInteger)
    hash: Mapped[bytes] = mapped_column(LargeBinary)
    anchored_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    sink: Mapped[str] = mapped_column(Text)
    sink_ref: Mapped[str] = mapped_column(Text)


class AuditCheckpoint(Base):
    """A pruned scope's checkpoint (engine 2b spec §10.2): the last entry pruned, anchored off the database first. The
    verifier starts the scope's chain from its latest one, and the scope's next entry chains to it when none is left."""

    __tablename__ = "audit_checkpoints"
    scope: Mapped[str] = mapped_column(Text, primary_key=True)
    seq: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    hash: Mapped[bytes] = mapped_column(LargeBinary)
    sink: Mapped[str] = mapped_column(Text)
    sink_ref: Mapped[str] = mapped_column(Text)
    anchored_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
