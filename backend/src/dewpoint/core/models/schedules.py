# SPDX-License-Identifier: Apache-2.0
"""A schedule (engine 2b spec §8.2): the wanted state the API writes, the generation it raises with every change, the
one the dispatcher's sync last completed, and the tombstone a deletion leaves."""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, LargeBinary, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from dewpoint.core.models.base import Base


class Schedule(Base):
    __tablename__ = "schedules"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"))
    workflow_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("workflows.id"))
    cron: Mapped[str | None] = mapped_column(Text)
    every_s: Mapped[int | None] = mapped_column(Integer)
    offset_s: Mapped[int] = mapped_column(Integer, default=0)
    time_zone: Mapped[str] = mapped_column(Text, default="UTC")
    catchup_window_s: Mapped[int] = mapped_column(Integer, default=600)
    mode: Mapped[str] = mapped_column(String(16))
    input: Mapped[bytes | None] = mapped_column(LargeBinary)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    generation: Mapped[int] = mapped_column(BigInteger, default=1)
    synced_generation: Mapped[int] = mapped_column(BigInteger, default=0)
    misses: Mapped[int] = mapped_column(BigInteger, default=0)
    misses_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sync_error: Mapped[str | None] = mapped_column(String(64))
    sync_error_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
