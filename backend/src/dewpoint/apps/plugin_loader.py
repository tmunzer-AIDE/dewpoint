# SPDX-License-Identifier: Apache-2.0
"""Discovers installed plugins (entry point group `dewpoint.plugins`) and registers them."""

from collections.abc import Sequence
from importlib.metadata import entry_points
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from dewpoint.core.plugins.registry import NodeTypeRow, SyncReport, ensure_cel_profile, sync_plugins
from dewpoint.engine.cel.profile import CURRENT_CEL_PROFILE
from dewpoint.engine.registry.catalog import contract_hash, validate_plugin_manifest
from dewpoint.sdk import Plugin

GROUP = "dewpoint.plugins"


class PluginLoadError(RuntimeError):
    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


def installed_plugins() -> list[Plugin]:
    plugins: list[Plugin] = []
    for ep in sorted(entry_points(group=GROUP), key=lambda e: e.name):
        obj = ep.load()
        if not isinstance(obj, Plugin):
            raise PluginLoadError([f"entry point {ep.name} is not a dewpoint.sdk.Plugin"])
        plugins.append(obj)
    return plugins


def prepare(plugins: Sequence[Plugin]) -> list[tuple[dict[str, Any], list[NodeTypeRow]]]:
    out: list[tuple[dict[str, Any], list[NodeTypeRow]]] = []
    problems: list[str] = []
    for plugin in plugins:
        manifest = plugin.manifest()  # raises ManifestError for class-level problems
        found = validate_plugin_manifest(manifest)
        problems += found
        if found:
            continue  # never hash a manifest that failed validation: it may hold values canonical JSON rejects
        rows = [
            NodeTypeRow(
                type=n["type"], version=n["version"], kind=n["kind"], manifest=n, contract_hash=contract_hash(n)
            )
            for n in manifest["nodes"]
        ]
        out.append((manifest, rows))
    if problems:
        raise PluginLoadError(problems)
    return out


async def sync_installed(s: AsyncSession, plugins: Sequence[Plugin]) -> SyncReport:
    report = await sync_plugins(s, prepare(plugins))
    await ensure_cel_profile(s, CURRENT_CEL_PROFILE)
    return report
