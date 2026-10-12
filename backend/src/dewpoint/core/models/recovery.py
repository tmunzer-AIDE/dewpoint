# SPDX-License-Identifier: Apache-2.0
"""Bounded retry and recovery (D10(1); the owner's rulings on the 2b-4b M3 design, rev 2; migration 0050): an item's
consecutive unexpected failures for one kind of work, an item a pass can't settle and why, and what an operator asked
done about one."""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
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
    hold_id: Mapped[int | None] = mapped_column(BigInteger)  # the hold's token, set with `held_at` (0057's trigger)


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
        UniqueConstraint("tenant_id", "id", name="operator_commands_tenant_key"),  # 0057: the snapshot's key
        Index("operator_commands_pending", "tenant_id", "kind", "item_id", unique=True,
              postgresql_where=text("status = 'pending'")),
    )  # fmt: skip
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(32))
    item_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))  # a bulk release names none (0057)
    reason: Mapped[str | None] = mapped_column(String(32))  # the recorded reason it was asked on; a release's none
    incident_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # that reason's `since`
    actor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    idempotency_key: Mapped[str] = mapped_column(String(100))
    evidence: Mapped[str] = mapped_column(String(4000), server_default="")  # an abandonment's, structured (0059)
    status: Mapped[str] = mapped_column(String(16), server_default="pending")
    outcome: Mapped[str | None] = mapped_column(String(64))  # a fixed code, never text
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # A release's own (0057): the held work's kind, and a bulk one's bounds
    work_kind: Mapped[str | None] = mapped_column(Text)
    held_before: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    max_holds: Mapped[int | None] = mapped_column(Integer)


class RecoveryOperator(Base):
    """A recovery login, mapped to the platform user it is (0056): provisioned and revoked by the database administrator
    alone, its name never reused."""

    __tablename__ = "recovery_operators"
    login: Mapped[str] = mapped_column(Text, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    provisioned_by: Mapped[str] = mapped_column(Text)
    provisioned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_by: Mapped[str | None] = mapped_column(Text)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OperatorConfirmation(Base):
    """A command's confirmation by its operator's own login, of the digest it was shown (0056)."""

    __tablename__ = "operator_confirmations"
    command_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("operator_commands.id", ondelete="CASCADE"), primary_key=True
    )
    login: Mapped[str] = mapped_column(Text)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    digest: Mapped[bytes] = mapped_column(LargeBinary)
    confirmed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class OperatorCommandHold(Base):
    """A hold a release command showed, with its token (0057): recorded once, before its confirmation."""

    __tablename__ = "operator_command_holds"
    __table_args__ = (
        PrimaryKeyConstraint("command_id", "tenant_id", "item_id", "kind", name="operator_command_holds_pkey"),
        ForeignKeyConstraint(["tenant_id", "command_id"], ["operator_commands.tenant_id", "operator_commands.id"],
                             ondelete="CASCADE", name="operator_command_holds_command"),
    )  # fmt: skip
    command_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(Text)
    item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    hold_id: Mapped[int] = mapped_column(BigInteger)
