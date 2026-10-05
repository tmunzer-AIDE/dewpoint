# SPDX-License-Identifier: Apache-2.0
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, func, text
from sqlalchemy.dialects.postgresql import CIDR, UUID
from sqlalchemy.orm import Mapped, mapped_column

from dewpoint.core.models.base import Base


class EgressAllowEntry(Base):
    """A platform admin's exception to the outbound guard (plugins-3 D8); tenant NULL means every tenant."""

    __tablename__ = "egress_allowlist"
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    network: Mapped[str] = mapped_column(CIDR)
    port_low: Mapped[int | None] = mapped_column(Integer)
    port_high: Mapped[int | None] = mapped_column(Integer)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE")
    )
    note: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RateBucket(Base):
    """One provider quota scope's budget for a tenant (plugins-3 D9)."""

    __tablename__ = "rate_buckets"
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"), primary_key=True)
    scope: Mapped[str] = mapped_column(String(200), primary_key=True)
    capacity: Mapped[float] = mapped_column(Float)
    refill_per_s: Mapped[float] = mapped_column(Float)
    tokens: Mapped[float] = mapped_column(Float)
    refilled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    blocked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
