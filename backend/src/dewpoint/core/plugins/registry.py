# SPDX-License-Identifier: Apache-2.0
"""Storage for plugin manifests and node type versions. Manifests are validated before they get here."""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select, tuple_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from dewpoint.core.models.plugins import CelProfile, NodeTypeVersion, PluginManifest


@dataclass(frozen=True)
class NodeTypeRow:
    type: str
    version: int
    kind: str
    manifest: dict[str, Any]
    contract_hash: str

    @property
    def ref(self) -> str:
        return f"{self.type}@{self.version}"


@dataclass(frozen=True)
class SyncReport:
    added: list[str]
    unchanged: list[str]


class ContractChangedError(ValueError):
    """A registered node type version changed its contract (anything but display metadata). Ship a new version."""

    def __init__(self, refs: list[str]) -> None:
        super().__init__(", ".join(refs))
        self.refs = refs


class MissingNodeTypeError(ValueError):
    """This build lacks node types that aren't retired. Published versions may still need them."""

    def __init__(self, refs: list[str]) -> None:
        super().__init__(", ".join(refs))
        self.refs = refs


def split_ref(ref: str) -> tuple[str, int]:
    type_, _, version = ref.rpartition("@")
    return type_, int(version)


async def sync_plugins(s: AsyncSession, plugins: Sequence[tuple[dict[str, Any], list[NodeTypeRow]]]) -> SyncReport:
    """Register every installed plugin in one transaction. Refuses contract changes, and refuses a build that
    lacks a node type that isn't retired (spec §4.5: code is removed only after retirement)."""
    added: list[str] = []
    unchanged: list[str] = []
    changed: list[str] = []
    installed: set[str] = set()
    for manifest, rows in plugins:
        await s.execute(
            insert(PluginManifest)
            .values(
                name=manifest["name"],
                version=manifest["version"],
                sdk_version=manifest["sdk_version"],
                manifest=manifest,
            )
            .on_conflict_do_update(
                index_elements=["name"],
                set_={
                    "version": manifest["version"],
                    "sdk_version": manifest["sdk_version"],
                    "manifest": manifest,
                    "synced_at": func.now(),
                },
            )
        )
        for row in rows:
            installed.add(row.ref)
            existing = await s.get(NodeTypeVersion, (row.type, row.version), with_for_update=True)
            if existing is None:
                s.add(
                    NodeTypeVersion(
                        type=row.type,
                        version=row.version,
                        plugin=manifest["name"],
                        kind=row.kind,
                        manifest=row.manifest,
                        contract_hash=row.contract_hash,
                        state="active",
                    )
                )
                added.append(row.ref)
            elif existing.contract_hash != row.contract_hash:
                changed.append(row.ref)
            else:
                existing.manifest = row.manifest  # equal contract hashes: only display metadata differs
                unchanged.append(row.ref)
    if changed:
        raise ContractChangedError(sorted(changed))
    await s.flush()
    live = await s.execute(
        select(NodeTypeVersion.type, NodeTypeVersion.version).where(NodeTypeVersion.state != "retired")
    )
    missing = sorted(f"{t}@{v}" for t, v in live if f"{t}@{v}" not in installed)
    if missing:
        raise MissingNodeTypeError(missing)
    return SyncReport(added=sorted(added), unchanged=sorted(unchanged))


async def ensure_cel_profile(s: AsyncSession, profile: str) -> None:
    await s.execute(insert(CelProfile).values(profile=profile, state="active").on_conflict_do_nothing())


async def load_node_types(s: AsyncSession, refs: Iterable[str]) -> list[NodeTypeVersion]:
    pairs = sorted({split_ref(r) for r in refs})
    if not pairs:
        return []
    rows = await s.execute(
        select(NodeTypeVersion).where(tuple_(NodeTypeVersion.type, NodeTypeVersion.version).in_(pairs))
    )
    return list(rows.scalars())


async def list_node_types(s: AsyncSession, states: Iterable[str] = ("active", "deprecated")) -> list[NodeTypeVersion]:
    rows = await s.execute(
        select(NodeTypeVersion)
        .where(NodeTypeVersion.state.in_(list(states)))
        .order_by(NodeTypeVersion.type, NodeTypeVersion.version)
    )
    return list(rows.scalars())
