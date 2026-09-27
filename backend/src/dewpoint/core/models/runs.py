# SPDX-License-Identifier: Apache-2.0
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from dewpoint.core.models.base import Base

RUN_STATUSES = ("running", "succeeded", "failed", "cancelled", "deadline_exceeded")


class Run(Base):
    """One run of a pinned workflow version. Its id is the Temporal workflow id."""

    __tablename__ = "runs"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"))
    workflow_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    workflow_version_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    mode: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(32))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(Text)  # a plugin's code: nothing bounds it, sanitize() does
    error_message: Mapped[str | None] = mapped_column(Text)
    iterations: Mapped[int] = mapped_column(Integer, default=0)
    started_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))


class RunStep(Base):
    """One attempt of one step in one scope: what the UI shows, never Temporal history (spec §8)."""

    __tablename__ = "run_steps"
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"))
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("runs.id", ondelete="CASCADE"), primary_key=True
    )
    step_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    iteration_key: Mapped[str] = mapped_column(Text, primary_key=True)  # unbounded: loops nest without a limit
    attempt: Mapped[int] = mapped_column(Integer, primary_key=True)
    node_key: Mapped[str] = mapped_column(String(63))
    status: Mapped[str] = mapped_column(String(16))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    input_preview: Mapped[Any] = mapped_column(JSONB)
    output_preview: Mapped[Any] = mapped_column(JSONB)
    error_code: Mapped[str | None] = mapped_column(Text)  # a plugin's code: nothing bounds it, sanitize() does
    error_message: Mapped[str | None] = mapped_column(Text)
    outcome: Mapped[str | None] = mapped_column(String(16))
    cel_mode: Mapped[str | None] = mapped_column(String(16))
