# SPDX-License-Identifier: Apache-2.0
"""Webhook ingress (engine 2b spec §8.3): a tenant's inbound keypairs."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, LargeBinary, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from dewpoint.core.models.base import Base


class TenantEventKey(Base):
    """A version of a tenant's X25519 keypair: ingress seals events to its public key; its private key is sealed with
    the tenant's data key (purpose `event.private`, its version the context)."""

    __tablename__ = "tenant_event_keys"
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    public_key: Mapped[bytes] = mapped_column(LargeBinary)
    private_sealed: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
