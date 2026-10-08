# SPDX-License-Identifier: Apache-2.0
"""Bounded retry and recovery (D10(1); the owner's rulings on the 2b-4b M3 design, rev 2; migration 0050): an item's
consecutive unexpected failures for one kind of work, an item a pass can't settle and why, and what an operator asked
done about one."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, PrimaryKeyConstraint, String, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from dewpoint.core.models.base import Base


class WorkFailure(Base):
    __tablename__ = "work_failures"
    __table_args__ = (PrimaryKeyConstraint("tenant_id", "item_id", "kind", name="work_failures_pkey"),)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(32))
    item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    errors: Mapped[int] = mapped_column(Integer)
    last_error: Mapped[str] = mapped_column(String(100))  # its type, never its text
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    held_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RecoveryItem(Base):
    __tablename__ = "recovery_items"
    __table_args__ = (PrimaryKeyConstraint("tenant_id", "item_id", "reason", name="recovery_items_pkey"),)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"))
    reason: Mapped[str] = mapped_column(String(32))
    item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    since: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class OperatorCommand(Base):
    __tablename__ = "operator_commands"
    __table_args__ = (
        UniqueConstraint("tenant_id", "actor_id", "idempotency_key", name="operator_commands_idempotency"),
        Index("operator_commands_pending", "tenant_id", "kind", "item_id", unique=True,
              postgresql_where=text("status = 'pending'")),
    )  # fmt: skip
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(32))
    item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    reason: Mapped[str] = mapped_column(String(32))  # the recorded reason it was asked on
    incident_since: Mapped[datetime] = mapped_column(DateTime(timezone=True))  # that reason's `since`
    actor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    idempotency_key: Mapped[str] = mapped_column(String(100))
    evidence: Mapped[str] = mapped_column(String(500), server_default="")
    status: Mapped[str] = mapped_column(String(16), server_default="pending")
    outcome: Mapped[str | None] = mapped_column(String(64))  # a fixed code, never text
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
