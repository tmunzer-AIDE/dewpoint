# SPDX-License-Identifier: Apache-2.0
"""Claims (engine 2b spec §3): one value each, stored encrypted under row-level security. Temporal history holds only
handles to them. A claim is written once and never changed."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, LargeBinary, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from dewpoint.core.models.base import Base


class _Claim:
    """The value, encrypted under the purpose `claim` with the claim's id as context, and its authoritative metadata
    (§3.1). The owner is the run that produced it (§3.4); the root run id serves retention and the secret index,
    never authorization."""

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"))
    owner_run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    root_run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    sensitive_pointers: Mapped[Any] = mapped_column(JSONB)  # the tainted pointers inside the value ("" is all of it)
    content_hash: Mapped[bytes] = mapped_column(LargeBinary)
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class InputClaim(_Claim, Base):
    """A claim made before its run starts: a trigger's claimed parts, a sub-flow's input (§3.5). Or, with the role
    `envelope`, a request's trigger envelope (revision 7, §7.1): not a claim, never read or granted as one."""

    __tablename__ = "run_inputs"
    role: Mapped[str] = mapped_column(String(16), default="claim")
    pointer: Mapped[str | None] = mapped_column(
        Text
    )  # where in the run's input it was claimed from; none for an envelope


class OutputClaim(_Claim, Base):
    """A claim made during a run: a plugin output, a CEL result, a derived claim, a filter's kept items, a spill or a
    segment."""

    __tablename__ = "step_outputs"
    kind: Mapped[str] = mapped_column(String(16))
    step_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    iteration_key: Mapped[str | None] = mapped_column(Text)
    attempt: Mapped[int | None] = mapped_column(Integer)


class ClaimGrant(Base):
    """A handle crossing to another run: parent to child, or child to parent (§3.4). Siblings get nothing."""

    __tablename__ = "claim_grants"
    claim_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"))
    granted_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    root_run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SecretIndex(Base):
    """Every string of 4 characters or more found in a tainted claim of one run tree, encrypted (§3.7). Its version
    changes with every extension, so a boundary can tell a stale copy."""

    __tablename__ = "run_secret_index"
    root_run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"))
    version: Mapped[int] = mapped_column(Integer)
    string_count: Mapped[int] = mapped_column(Integer)
    byte_count: Mapped[int] = mapped_column(Integer)
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
