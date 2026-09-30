# SPDX-License-Identifier: Apache-2.0
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, SmallInteger, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column

from dewpoint.core.models.base import Base


class PlatformSettings(Base):
    """The one row that says what this deployment is (engine 2b spec §2): production or development, recorded once
    with the Temporal namespace it uses, and whether production runs are on (off until the gate lifts)."""

    __tablename__ = "platform_settings"
    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, default=1)
    environment: Mapped[str] = mapped_column(String(16))
    temporal_namespace: Mapped[str] = mapped_column(Text)
    production_runs: Mapped[bool] = mapped_column(Boolean, default=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WorkerInstance(Base):
    """An engine worker instance: its build, the capabilities compiled into it, and whether its last self-check passed
    (engine 2b spec §2.7). One that hasn't checked lately isn't live."""

    __tablename__ = "worker_instances"
    instance_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    build_id: Mapped[str] = mapped_column(Text)
    capabilities: Mapped[list[str]] = mapped_column(ARRAY(Text))
    healthy: Mapped[bool] = mapped_column(Boolean)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
