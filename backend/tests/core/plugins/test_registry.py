# SPDX-License-Identifier: Apache-2.0
from dataclasses import replace
from typing import Any

import pytest
from sqlalchemy import select, text, update
from sqlalchemy.exc import DBAPIError

from dewpoint.apps.plugin_loader import PluginLoadError, prepare, sync_installed
from dewpoint.core.models.plugins import CelProfile, NodeTypeVersion
from dewpoint.core.plugins import registry
from dewpoint.engine.cel.profile import CURRENT_CEL_PROFILE
from dewpoint.engine.registry.catalog import contract_hash
from dewpoint.plugins.flow import PLUGIN
from dewpoint.sdk import Node, NodeKind, Plugin
from tests.support.plugins.testkit import TESTKIT


async def test_sync_registers_and_is_idempotent(admin_sessionmaker) -> None:
    async with admin_sessionmaker() as s, s.begin():
        report = await sync_installed(s, [PLUGIN, TESTKIT])
    assert len(report.added) == 16 and report.unchanged == []
    async with admin_sessionmaker() as s, s.begin():
        report = await sync_installed(s, [PLUGIN, TESTKIT])
    assert report.added == [] and len(report.unchanged) == 16
    async with admin_sessionmaker() as s:
        refs = {r.ref for r in await registry.list_node_types(s)}
        state = (
            await s.execute(select(CelProfile.state).where(CelProfile.profile == CURRENT_CEL_PROFILE))
        ).scalar_one()
    assert {"flow.if@1", "testkit.echo@1"} <= refs and state == "active"


async def test_behaviour_changes_are_refused_but_display_changes_are_stored(admin_sessionmaker) -> None:
    async with admin_sessionmaker() as s, s.begin():
        await sync_installed(s, [PLUGIN, TESTKIT])
    flow, (manifest, rows) = prepare([PLUGIN, TESTKIT])

    def with_echo(field: str, value: Any) -> list[Any]:
        node = {**rows[0].manifest, field: value}
        return [flow, (manifest, [replace(rows[0], manifest=node, contract_hash=contract_hash(node)), *rows[1:]])]

    for field, value in (("timeout_s", 1.0), ("retry", {**rows[0].manifest["retry"], "max_attempts": 9})):
        with pytest.raises(registry.ContractChangedError) as e:
            async with admin_sessionmaker() as s, s.begin():
                await registry.sync_plugins(s, with_echo(field, value))
        assert e.value.refs == ["testkit.echo@1"], field
    async with admin_sessionmaker() as s, s.begin():
        await registry.sync_plugins(s, with_echo("title", "Echo (renamed)"))
    async with admin_sessionmaker() as s:
        stored = await s.get(NodeTypeVersion, ("testkit.echo", 1))
        assert stored is not None and stored.manifest["title"] == "Echo (renamed)"


async def test_a_build_cannot_drop_live_node_types(admin_sessionmaker) -> None:
    async with admin_sessionmaker() as s, s.begin():
        await sync_installed(s, [PLUGIN, TESTKIT])
    with pytest.raises(registry.MissingNodeTypeError) as e:
        async with admin_sessionmaker() as s, s.begin():
            await sync_installed(s, [PLUGIN])
    assert "testkit.echo@1" in e.value.refs
    async with admin_sessionmaker() as s, s.begin():  # once retired, a build may drop them
        await s.execute(update(NodeTypeVersion).where(NodeTypeVersion.plugin == "testkit").values(state="retired"))
        await sync_installed(s, [PLUGIN])


async def test_api_role_cannot_write_the_registry(admin_sessionmaker, api_sessionmaker) -> None:
    async with admin_sessionmaker() as s, s.begin():
        await sync_installed(s, [PLUGIN])
    with pytest.raises(DBAPIError, match="permission denied"):
        async with api_sessionmaker() as s, s.begin():
            await s.execute(text("update node_type_versions set state = 'retired'"))


def test_prepare_rejects_manifests_the_engine_refuses() -> None:
    class Rogue(Node):
        type = "demo.rogue"
        version = 1
        title = "Rogue"
        kind = NodeKind.CONTROL  # only engine control types may be control nodes

    with pytest.raises(PluginLoadError) as e:
        prepare([Plugin(name="demo", version="1", nodes=(Rogue,))])
    assert any("only engine control types" in p for p in e.value.problems)
