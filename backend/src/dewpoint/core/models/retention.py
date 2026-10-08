# SPDX-License-Identifier: Apache-2.0
"""Retention (engine 2b spec §10.1, §10.3): a tenant's retention, when its admins have set one, and each sweep."""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Identity, Integer, false, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from dewpoint.core.models.base import Base


class TenantRetention(Base):
    __tablename__ = "tenant_retention"
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"), primary_key=True)
    runs_days: Mapped[int] = mapped_column(Integer, default=30)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RetentionSweep(Base):
    """One sweep: when it started and ended, whether every tenant's was done, and its lag, how far past its cutoff the
    oldest data still stored is at its end."""

    __tablename__ = "retention_sweeps"
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    succeeded: Mapped[bool | None] = mapped_column(Boolean)
    tenants: Mapped[int | None] = mapped_column(Integer)
    lag_s: Mapped[float | None] = mapped_column(Float)


class RetentionSweepTenant(Base):
    """A sweep's counts for one tenant, kept by the batches that deleted, and when its audit entry was written."""

    __tablename__ = "retention_sweep_tenants"
    sweep_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("retention_sweeps.id", ondelete="CASCADE"), primary_key=True
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    runs: Mapped[int] = mapped_column(BigInteger, server_default="0")
    requests: Mapped[int] = mapped_column(BigInteger, server_default="0")
    events: Mapped[int] = mapped_column(BigInteger, server_default="0")
    csv_uploads: Mapped[int] = mapped_column(BigInteger, server_default="0")
    schedules: Mapped[int] = mapped_column(BigInteger, server_default="0")
    lag_s: Mapped[float | None] = mapped_column(Float)
    failed: Mapped[bool] = mapped_column(Boolean, server_default=false())  # kept: a resumed sweep stays unsuccessful
    audited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
