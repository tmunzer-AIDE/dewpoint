# SPDX-License-Identifier: Apache-2.0
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, SmallInteger, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
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
    max_concurrent_runs: Mapped[int] = mapped_column(SmallInteger, default=5)  # per tenant, unless its limits row says
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


class DispatcherReport(Base):
    """A dispatcher instance's last report (engine 2b spec §10.6): what it did and when, as health evidence 2b-4's
    readiness checks read. It claims nothing by itself."""

    __tablename__ = "dispatcher_reports"
    instance_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    kind: Mapped[str] = mapped_column(String(16))  # dispatcher | reconciler
    build_id: Mapped[str] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    reported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    details: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)


class RunDurationLimit(Base):
    """A maximum run duration the dispatcher has set deadlines with (engine 2b spec §6.4): the longest is the payload
    floor's."""

    __tablename__ = "run_duration_limits"
    days: Mapped[int] = mapped_column(Integer, primary_key=True)
    first_recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
