# SPDX-License-Identifier: Apache-2.0
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, LargeBinary, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from dewpoint.core.models.base import Base, UUIDPk


class _WrappedKey(UUIDPk):
    version: Mapped[int] = mapped_column(Integer)
    wrapped_key: Mapped[bytes] = mapped_column(LargeBinary)
    kek_id: Mapped[str] = mapped_column(String(64))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DataKey(_WrappedKey, Base):
    """A tenant's wrapped data-encryption keys. RLS-scoped to the tenant (FORCE); key admins see all."""

    __tablename__ = "data_keys"
    __table_args__ = (UniqueConstraint("tenant_id", "version"),)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))


class PlatformKey(_WrappedKey, Base):
    """The platform scope's wrapped data keys (user TOTP secrets). Granted to api and admin roles only."""

    __tablename__ = "platform_keys"
    __table_args__ = (UniqueConstraint("version"),)
