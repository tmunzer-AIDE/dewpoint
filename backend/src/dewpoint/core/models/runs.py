# SPDX-License-Identifier: Apache-2.0
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    false,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from dewpoint.core.models.base import Base

RUN_STATUSES = ("running", "succeeded", "failed", "cancelled", "deadline_exceeded")
RUN_KINDS = ("run", "subflow", "failure_handler")  # a sub-flow's or failure handler's run points at its parent


class Run(Base):
    """One run of a pinned workflow version. Its id is the Temporal workflow id. A sub-run (a sub-flow's, a failure
    handler's) points at the run and step that started it."""

    __tablename__ = "runs"
    __table_args__ = (  # its version, its parent and its root, all of its own tenant (#35, engine 2b spec §10.1)
        UniqueConstraint("id", "tenant_id", name="runs_tenant"),
        ForeignKeyConstraint(
            ["workflow_version_id", "workflow_id", "tenant_id"],
            ["workflow_versions.id", "workflow_versions.workflow_id", "workflow_versions.tenant_id"],
            name="runs_version_fk",
        ),
        ForeignKeyConstraint(["parent_run_id", "tenant_id"], ["runs.id", "runs.tenant_id"], name="runs_parent_run"),
        ForeignKeyConstraint(["root_run_id", "tenant_id"], ["runs.id", "runs.tenant_id"], name="runs_root_run"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"))
    workflow_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    workflow_version_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    mode: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(32))
    # A root run's row is written at dispatch, before Temporal answers (engine 2b spec §7.3): queued then, started
    # once the start is confirmed. A run from before 2b-2 was queued when it started.
    queued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(Text)  # a plugin's code: nothing bounds it, sanitize() does
    error_message: Mapped[str | None] = mapped_column(Text)
    iterations: Mapped[int] = mapped_column(Integer, default=0)
    started_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    kind: Mapped[str] = mapped_column(String(32), default="run")
    parent_run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    # The tree's root, set by the database on insert (a root run's own id, a sub-run's parent's root), never changed:
    # retention counts a tree's cutoff from its root (engine 2b spec §10.1).
    root_run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # a sub-run its root's end left (M5)
    parent_step_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    parent_iteration_key: Mapped[str | None] = mapped_column(Text)


class RunStep(Base):
    """One attempt of one step in one scope: what the UI shows, never Temporal history (spec §8)."""

    __tablename__ = "run_steps"
    __table_args__ = (
        ForeignKeyConstraint(
            ["run_id", "tenant_id"], ["runs.id", "runs.tenant_id"], name="run_steps_run", ondelete="CASCADE"
        ),
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"))
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
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


class ExecutionEvidence(Base):
    """What Temporal may still hold of a run execution (the owner's M3 rulings), kept until Temporal shows it gone,
    whatever retention deletes from `runs`. A root's is written with each start attempt, before Temporal is asked
    (`run_id` none: its chain not yet read); an attempt Temporal may have taken leaves it `unproven`. The dispatcher's
    leader records each run of its chain and each child it started, from their histories (`read_at`). One whose
    history went before it was read is `lost_at`: what it started is unknown."""

    __tablename__ = "execution_evidence"
    __table_args__ = (
        Index("execution_evidence_root", "workflow_id", unique=True, postgresql_where=text("run_id IS NULL")),
        Index(
            "execution_evidence_run", "workflow_id", "run_id", unique=True, postgresql_where=text("run_id IS NOT NULL")
        ),  # fmt: skip
        Index("execution_evidence_due", "next_check_at", postgresql_where=text("lost_at IS NULL")),
        Index("execution_evidence_tenant", "tenant_id", "started_at"),
    )
    id: Mapped[int] = mapped_column(BigInteger, Identity(always=False), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"))
    workflow_id: Mapped[str] = mapped_column(Text)
    run_id: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # Temporal first showed it
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # Temporal last asked about it
    unproven: Mapped[bool] = mapped_column(Boolean, server_default=false())  # an attempt Temporal may have taken
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lost_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_check_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
