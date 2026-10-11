# SPDX-License-Identifier: Apache-2.0
"""A tenant's erasure (engine 2b spec §6.5; migration 0040): its record, kept for good, identifiers only; the items a
stage with an effect outside PostgreSQL works through, each found, requested, then verified by a read-back; and every
Temporal id it found, which the retention process describes on every pass after completion."""

import uuid
from datetime import datetime, timedelta
from enum import IntEnum
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Interval,
    SmallInteger,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from dewpoint.core.models.base import Base


class Stage(IntEnum):
    """An erasure's stages, in order (the outline's steps: 3 is 31 to 33). Step 1, marking the tenant `erasing`,
    creates the record at the first."""

    RECONCILE = 20  # every `starting` request started or confirmed absent, by the reconciler
    PAUSE = 31  # every schedule verified paused
    INVENTORY = 32  # every firing found, before any schedule is deleted
    UNSCHEDULE = 33  # every schedule verified deleted
    CANCEL = 40  # queued requests and pending events cancelled, their counters released
    END_RUNS = 50  # every running run verified ended
    EXECUTIONS = 60  # every execution found deleted and read back; the insert fence holds from here
    KEYS = 70  # every data key and event keypair deleted
    SWEEP = 80  # every row of the tenant deleted, its tombstone anonymized
    BOUND = 90  # the retention bound, then the final check
    COMPLETE = 100


FENCED_AT = Stage.EXECUTIONS


class TenantErasure(Base):
    __tablename__ = "tenant_erasures"
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"), primary_key=True)
    requested_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    step: Mapped[int] = mapped_column(SmallInteger, server_default=text("20"))
    step_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())  # entered it
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    stopped_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    attempts: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    failure: Mapped[str | None] = mapped_column(Text)
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    fenced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # entered stage 60: never cleared
    paused_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    latest_close: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    check_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    boundary: Mapped[str | None] = mapped_column(Text)
    counts: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reopened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    incidents: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    # 2b-4b M4 recovery (0060): every execution found was verified gone by then (never a bound); the unresolved count,
    # for display only; a completion from before the current standard, qualified and kept
    verified_close: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    absence_unresolved: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    qualification: Mapped[str | None] = mapped_column(Text)  # legacy_completion_unproven
    legacy_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TenantErasureItem(Base):
    __tablename__ = "tenant_erasure_items"
    __table_args__ = (
        Index(
            "tenant_erasure_items_one", "tenant_id", "step", "workflow_id", text("coalesce(run_id, '')"), unique=True
        ),  # fmt: skip
        Index("tenant_erasure_items_open", "tenant_id", "step", "id", postgresql_where=text("state <> 'verified'")),
    )
    id: Mapped[int] = mapped_column(BigInteger, Identity(always=False), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenant_erasures.tenant_id"))
    step: Mapped[int] = mapped_column(SmallInteger)
    kind: Mapped[str] = mapped_column(Text)  # request, schedule, run, execution
    workflow_id: Mapped[str] = mapped_column(Text)
    run_id: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text)  # where it was found
    state: Mapped[str] = mapped_column(Text, server_default="found")  # found, requested, verified, absent (0061)
    attempts: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    failure: Mapped[str | None] = mapped_column(Text)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TenantErasureKnown(Base):
    __tablename__ = "tenant_erasure_known"
    __table_args__ = (
        Index(
            "tenant_erasure_known_one", "tenant_id", "kind", "workflow_id", text("coalesce(run_id, '')"), unique=True
        ),  # fmt: skip
    )
    id: Mapped[int] = mapped_column(BigInteger, Identity(always=False), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenant_erasures.tenant_id"))
    kind: Mapped[str] = mapped_column(Text)  # schedule, execution
    workflow_id: Mapped[str] = mapped_column(Text)
    run_id: Mapped[str | None] = mapped_column(Text)
    # An execution's (0060): gone, run_not_found, absent, retained_out, never_created or legacy; a schedule's none
    provenance: Mapped[str | None] = mapped_column(Text)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # Temporal's close (task 15)
    closed_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    qualified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class NamespaceBoundary(Base):
    """A namespace-change boundary verified for the deployment's Temporal (D3g), which step 9's bound relies on."""

    __tablename__ = "namespace_boundaries"
    id: Mapped[int] = mapped_column(BigInteger, Identity(always=False), primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    lost_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # what it rests on (0051, 2b-4b M4): null on a row from before
    namespace: Mapped[str | None] = mapped_column(Text)
    namespace_id: Mapped[str | None] = mapped_column(Text)  # Temporal's id for the namespace
    server_build: Mapped[str | None] = mapped_column(Text)  # sha256:<hex> of the server binary
    proof_digest: Mapped[str | None] = mapped_column(Text)  # sha256:<hex> of the D12 proof record
    attestation: Mapped[str | None] = mapped_column(Text)
    recorded_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))  # the platform admin


class TargetNamespaceRegistration(Base):
    """When a namespace was registered, as the persistent-target qualification established it (0063): where its
    intervals must begin. No application role writes it."""

    __tablename__ = "target_namespace_registrations"
    namespace: Mapped[str] = mapped_column(Text, primary_key=True)
    registered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    evidence: Mapped[str] = mapped_column(Text)


class TargetQualificationInterval(Base):
    """An interval over which the qualified target enforced its limits for a namespace (0063): `retained_out` rests on
    them. NULL: not established, which never qualifies anything. No application role writes it."""

    __tablename__ = "target_qualification_intervals"
    __table_args__ = (
        CheckConstraint("valid_from < valid_to", name="target_qualification_intervals_span"),
        Index("target_qualification_intervals_namespace", "namespace", "valid_from"),
    )
    id: Mapped[int] = mapped_column(BigInteger, Identity(always=False), primary_key=True)
    namespace: Mapped[str] = mapped_column(Text)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    valid_to: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    retention_max: Mapped[timedelta | None] = mapped_column(Interval)  # the most retention any update could set
    archival_off: Mapped[bool | None] = mapped_column(Boolean)  # history and visibility archival enforced off
    jitter_max: Mapped[timedelta | None] = mapped_column(Interval)  # history.retentionTimerJitterDuration, at most
    clock_skew_max: Mapped[timedelta | None] = mapped_column(Interval)  # Temporal's clock against the database's
    evidence: Mapped[str] = mapped_column(Text)
