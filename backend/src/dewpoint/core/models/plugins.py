# SPDX-License-Identifier: Apache-2.0
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, ForeignKeyConstraint, Integer, LargeBinary, String, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from dewpoint.core.models.base import Base


class PluginManifest(Base):
    __tablename__ = "plugin_manifests"
    name: Mapped[str] = mapped_column(String(41), primary_key=True)
    version: Mapped[str] = mapped_column(String(64))
    sdk_version: Mapped[str] = mapped_column(String(32))
    manifest: Mapped[dict[str, Any]] = mapped_column(JSONB)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class NodeTypeVersion(Base):
    __tablename__ = "node_type_versions"
    type: Mapped[str] = mapped_column(String(120), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    plugin: Mapped[str] = mapped_column(String(41), ForeignKey("plugin_manifests.name"))
    kind: Mapped[str] = mapped_column(String(16))
    manifest: Mapped[dict[str, Any]] = mapped_column(JSONB)
    contract_hash: Mapped[str] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(16), default="active")  # active | deprecated | retired
    state_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    @property
    def ref(self) -> str:
        return f"{self.type}@{self.version}"


class CelProfile(Base):
    __tablename__ = "cel_profiles"
    profile: Mapped[str] = mapped_column(String(120), primary_key=True)
    state: Mapped[str] = mapped_column(String(16), default="active")
    state_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PluginCall(Base):
    """Plugin code a worker runs for the API, outside any run (plugins-3a-2, migration 0042): a node's options or a
    connection type's verify. Its answer is sealed under the tenant's data key (purpose `plugin.call`, its id as
    context); a call names only its own tenant's connection."""

    __tablename__ = "plugin_calls"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "connection_id"], ["connections.tenant_id", "connections.id"], ondelete="CASCADE"
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(16))  # options | verify
    node_ref: Mapped[str | None] = mapped_column(String(140))
    field: Mapped[str | None] = mapped_column(String(64))
    connection_type: Mapped[str | None] = mapped_column(String(83))
    connection_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    connection_revision: Mapped[int | None] = mapped_column(Integer)
    type_hash: Mapped[str | None] = mapped_column(String(64))
    query: Mapped[str] = mapped_column(String(200), server_default="")
    state: Mapped[str] = mapped_column(String(16), server_default="pending")  # pending | claimed | done | failed
    claim_token: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    result_ct: Mapped[bytes | None] = mapped_column(LargeBinary)
    error: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
