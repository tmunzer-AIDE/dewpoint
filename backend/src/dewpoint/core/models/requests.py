# SPDX-License-Identifier: Apache-2.0
"""Admission's queue (engine 2b spec §7): one row per run request, the intent itself, under row-level security; the
slots a tenant's running root runs hold; its limits row; and the current build as the dispatcher last read it."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, LargeBinary, SmallInteger, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from dewpoint.core.models.base import Base

SOURCES = ("manual", "rerun", "schedule", "webhook", "dev")
STATUSES = ("queued", "starting", "started", "cancelled", "refused", "dead")
TERMINAL = ("cancelled", "refused", "dead")  # a started request's run carries on: its own status says when it ends


class RunRequest(Base):
    """A request to run a workflow, frozen on its version (§7.1). Its id is the run's once it starts. The trigger isn't
    here: it's an envelope in `run_inputs`, encrypted, beside the claims it holds handles to (revision 7)."""

    __tablename__ = "run_requests"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"))
    workflow_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("workflows.id"))
    workflow_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflow_versions.id")
    )
    source: Mapped[str] = mapped_column(String(16))
    actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    mode: Mapped[str] = mapped_column(String(16))
    idempotency_key: Mapped[str] = mapped_column(String(255))
    digest: Mapped[bytes] = mapped_column(LargeBinary)
    digest_key_version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16))
    reason: Mapped[str | None] = mapped_column(String(64))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    queued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    starting_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # when it last became starting
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # the reconciler's last look
    envelope_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))


class TenantRunLimits(Base):
    """A tenant's limits row: its lock serializes the tenant's slot reservations (§7.5)."""

    __tablename__ = "tenant_run_limits"
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"), primary_key=True)
    max_concurrent: Mapped[int | None] = mapped_column(SmallInteger)  # none: the platform's default


class RunSlot(Base):
    """One running root run's slot (§7.5): reserved at dispatch, released by the run's end write."""

    __tablename__ = "run_slots"
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"))
    reserved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CurrentBuild(Base):
    """The deployment's current build as the dispatcher last read it from Temporal, and when (the owner's ruling):
    admission's ABI check, which fails closed when it's missing or stale."""

    __tablename__ = "current_build"
    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, default=1)
    build_id: Mapped[str] = mapped_column(Text)
    engine_abi: Mapped[int] = mapped_column(Integer)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
