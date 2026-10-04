# SPDX-License-Identifier: Apache-2.0
"""Webhook ingress (engine 2b spec §8.3): a tenant's inbound keypairs, its endpoints, counters, bindings and events."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Integer, LargeBinary, String, Text, func, true
from sqlalchemy.dialects.postgresql import ARRAY, CIDR, JSONB, UUID
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


class WebhookEndpoint(Base):
    """An endpoint (`/hooks/<id>`): its authentication, its limits, where its events' ids are, its rate buckets, its
    pending and retained counters and their quotas. Its secrets are sealed under the ingress key, never a tenant's."""

    __tablename__ = "webhook_endpoints"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"))
    name: Mapped[str] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, server_default=true())
    auth_kind: Mapped[str] = mapped_column(String(16))
    bearer_digest: Mapped[bytes | None] = mapped_column(LargeBinary)
    hmac_secret: Mapped[bytes | None] = mapped_column(LargeBinary)
    signature_header: Mapped[str | None] = mapped_column(Text)
    timestamp_header: Mapped[str | None] = mapped_column(Text)
    tolerance_s: Mapped[int] = mapped_column(Integer, server_default="300")
    allowlist: Mapped[list[Any]] = mapped_column(ARRAY(CIDR), server_default="{}")
    body_limit: Mapped[int] = mapped_column(Integer, server_default=str(1024 * 1024))
    id_source: Mapped[str] = mapped_column(String(16), server_default="none")
    id_pointer: Mapped[str | None] = mapped_column(Text)
    id_header: Mapped[str | None] = mapped_column(Text)
    events_pointer: Mapped[str | None] = mapped_column(Text)
    dedupe_key: Mapped[bytes] = mapped_column(LargeBinary)
    request_per_s: Mapped[float] = mapped_column(Float, server_default="20")
    request_burst: Mapped[int] = mapped_column(BigInteger, server_default="100")
    event_per_s: Mapped[float] = mapped_column(Float, server_default="10")
    event_burst: Mapped[int] = mapped_column(BigInteger, server_default="1000")
    byte_per_s: Mapped[float] = mapped_column(Float, server_default=str(2 * 1024 * 1024))
    byte_burst: Mapped[int] = mapped_column(BigInteger, server_default=str(10 * 1024 * 1024))
    request_tokens: Mapped[float] = mapped_column(Float, server_default="100")
    event_tokens: Mapped[float] = mapped_column(Float, server_default="1000")
    byte_tokens: Mapped[float] = mapped_column(Float, server_default=str(10 * 1024 * 1024))
    refilled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    pending_events: Mapped[int] = mapped_column(BigInteger, server_default="0")
    pending_bytes: Mapped[int] = mapped_column(BigInteger, server_default="0")
    retained_events: Mapped[int] = mapped_column(BigInteger, server_default="0")
    retained_bytes: Mapped[int] = mapped_column(BigInteger, server_default="0")
    pending_events_max: Mapped[int] = mapped_column(BigInteger, server_default="10000")
    pending_bytes_max: Mapped[int] = mapped_column(BigInteger, server_default=str(64 * 1024 * 1024))
    retained_events_max: Mapped[int] = mapped_column(BigInteger, server_default="100000")
    retained_bytes_max: Mapped[int] = mapped_column(BigInteger, server_default=str(512 * 1024 * 1024))
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TenantEventCounters(Base):
    """A tenant's event and byte buckets, its pending and retained counters and their quotas, across its endpoints."""

    __tablename__ = "tenant_event_counters"
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"), primary_key=True)
    pending_events: Mapped[int] = mapped_column(BigInteger, server_default="0")
    pending_bytes: Mapped[int] = mapped_column(BigInteger, server_default="0")
    retained_events: Mapped[int] = mapped_column(BigInteger, server_default="0")
    retained_bytes: Mapped[int] = mapped_column(BigInteger, server_default="0")
    pending_events_max: Mapped[int] = mapped_column(BigInteger, server_default="50000")
    pending_bytes_max: Mapped[int] = mapped_column(BigInteger, server_default=str(256 * 1024 * 1024))
    retained_events_max: Mapped[int] = mapped_column(BigInteger, server_default="250000")
    retained_bytes_max: Mapped[int] = mapped_column(BigInteger, server_default=str(1024 * 1024 * 1024))
    recounted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TriggerBinding(Base):
    """An endpoint's events to a workflow of the same tenant, when every typed JSON-pointer equality of its filter
    holds (at most 8; none: every event)."""

    __tablename__ = "trigger_bindings"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    endpoint_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    workflow_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    filter: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, server_default="[]")
    enabled: Mapped[bool] = mapped_column(Boolean, server_default=true())
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class InboundEvent(Base):
    """An event as ingress recorded it, sealed to its tenant's keypair `key_version`, and what became of it."""

    __tablename__ = "inbound_events"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    endpoint_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    dedupe_key: Mapped[bytes | None] = mapped_column(LargeBinary)
    content_digest: Mapped[bytes | None] = mapped_column(LargeBinary)
    key_version: Mapped[int] = mapped_column(Integer)
    sealed: Mapped[bytes] = mapped_column(LargeBinary)
    size_bytes: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), server_default="pending")
    reason: Mapped[str | None] = mapped_column(String(64))
    attempts: Mapped[int] = mapped_column(Integer, server_default="0")
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    request_count: Mapped[int | None] = mapped_column(Integer)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
