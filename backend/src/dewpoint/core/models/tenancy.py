# SPDX-License-Identifier: Apache-2.0
import uuid
from typing import Literal

from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from dewpoint.core.models.base import Base, Timestamps, UUIDPk

Role = Literal["owner", "admin", "editor", "operator", "viewer"]
ROLES: tuple[Role, ...] = ("owner", "admin", "editor", "operator", "viewer")


class Tenant(UUIDPk, Timestamps, Base):
    __tablename__ = "tenants"
    name: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(63), unique=True)
    require_passkey: Mapped[bool] = mapped_column(Boolean, default=False)


class Membership(UUIDPk, Timestamps, Base):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("tenant_id", "user_id"),)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String(20))
