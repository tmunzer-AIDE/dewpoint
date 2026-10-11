# SPDX-License-Identifier: Apache-2.0
"""The blocker store (2b-4b M4 recovery, migration 0054): a request whose start sends might still create an execution,
and each counted send with its own call's answer. Platform-scoped, outliving the erasure and retention
(`dewpoint.core.blockers`)."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, SmallInteger, Text, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import UserDefinedType

from dewpoint.core.models.base import Base


class Xid8(UserDefinedType[int]):
    """PostgreSQL's `xid8`: a transaction's id (`pg_current_xact_id()`)."""

    cache_ok = True

    def get_col_spec(self, **kw: object) -> str:
        return "xid8"


class UnresolvedSend(Base):
    __tablename__ = "unresolved_sends"
    request_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    workflow_id: Mapped[str] = mapped_column(Text)  # the root's Temporal workflow id
    start_request_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    legacy_unknown: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    state: Mapped[str] = mapped_column(Text)  # pending, unresolved, identified, deleted_open
    identified_run_id: Mapped[str | None] = mapped_column(Text)
    first_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.statement_timestamp())
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.statement_timestamp())
    late_start: Mapped[str | None] = mapped_column(Text)  # matched, unmatched (0055): the late start's own record
    late_start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class StartSend(Base):
    __tablename__ = "start_sends"
    request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("unresolved_sends.request_id", ondelete="CASCADE"), primary_key=True
    )
    attempt: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    intent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.statement_timestamp())
    intent_xid: Mapped[int] = mapped_column(Xid8, server_default=text("pg_current_xact_id()"))
    answer: Mapped[str | None] = mapped_column(Text)
    run_id: Mapped[str | None] = mapped_column(Text)
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
