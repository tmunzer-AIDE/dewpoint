# SPDX-License-Identifier: Apache-2.0
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, LargeBinary, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from dewpoint.core.models.base import Base, UUIDPk


class DataKey(UUIDPk, Base):
    """Wrapped data-encryption keys. Not RLS-scoped: only reachable through Keyring."""

    __tablename__ = "data_keys"
    __table_args__ = (UniqueConstraint("scope_key", "version"),)
    scope_key: Mapped[str] = mapped_column(String(64))  # "platform" or tenant uuid
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    version: Mapped[int] = mapped_column(Integer)
    wrapped_key: Mapped[bytes] = mapped_column(LargeBinary)
    kek_id: Mapped[str] = mapped_column(String(64))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
