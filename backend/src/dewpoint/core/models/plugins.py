# SPDX-License-Identifier: Apache-2.0
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
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
