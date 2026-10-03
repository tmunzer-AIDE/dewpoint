# SPDX-License-Identifier: Apache-2.0
"""The gate-off race (engine 2b spec §2.4): disabling takes `dewpoint:production-gate` exclusively, so it waits for
any starting transaction holding it shared, and once it commits no request becomes `starting`. The command then waits
for the starts already made to settle, up to the dispatcher's start deadline; one still unsettled is reported
unresolved, and the gate stays off. Disabling is audited; the admin role can disable and nothing else."""

import asyncio
import base64
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from typer.testing import CliRunner

from dewpoint.apps.cli import main as cli
from dewpoint.apps.dispatcher import dispatch, gate
from dewpoint.core.config import get_settings
from tests.apps.dispatcher.support import begin, state
from tests.apps.test_lifecycle_races import until_someone_waits_for_a_lock
from tests.conftest import _url_for


@pytest.fixture
async def production_on(development_deployment, owner_sessionmaker) -> None:
    """The recorded deployment made production, its gate on: the dispatcher's every start depends on it."""
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(text("alter table platform_settings disable trigger user"))
        await s.execute(text("update platform_settings set environment = 'production', production_runs = true"))
        await s.execute(text("alter table platform_settings enable trigger user"))


async def gate_on(owner: Any) -> bool:
    async with owner() as s:
        return bool((await s.execute(text("select production_runs from platform_settings"))).scalar())


async def disable(admin: Any) -> bool:
    async with admin() as s, s.begin():
        return await gate.disable_production_runs(s, actor_id=None)


@pytest.mark.usefixtures("production_on")
async def test_disabling_waits_for_a_starting_transaction_and_nothing_starts_after(
    queued, owner_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings
) -> None:
    _, _, request = queued
    async with dispatch_sessionmaker() as held, held.begin():  # a starting transaction, under the shared lock
        await held.execute(
            text("select pg_advisory_xact_lock_shared(hashtextextended(:k, 0))"), {"k": dispatch.GATE_LOCK}
        )
        disabling = asyncio.create_task(disable(admin_sessionmaker))
        await until_someone_waits_for_a_lock(owner_sessionmaker)
        assert not disabling.done() and await gate_on(owner_sessionmaker)
    assert await disabling is True  # it was on
    assert not await gate_on(owner_sessionmaker)
    assert await begin(dispatch_sessionmaker, request, api_settings) == dispatch.Waiting("gate_off")
    async with owner_sessionmaker() as s:
        details = (await s.execute(text(
            "select details from audit_log where action = 'platform.production_runs.disable'"
        ))).scalar_one()  # fmt: skip
    assert details == {"was_on": True}


@pytest.mark.usefixtures("production_on")
async def test_a_start_that_doesnt_settle_in_time_is_reported_unresolved(
    queued, owner_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings
) -> None:
    _, _, request = queued
    assert isinstance(await begin(dispatch_sessionmaker, request, api_settings), dispatch.Starting)
    left = await gate.disable_and_wait(admin_sessionmaker, deadline=timedelta(milliseconds=300))
    assert left == [request.id]
    assert not await gate_on(owner_sessionmaker)  # off either way


@pytest.mark.usefixtures("production_on")
async def test_disabling_waits_for_the_starts_already_made_to_settle(
    queued, owner_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings
) -> None:
    _, _, request = queued
    starting = await begin(dispatch_sessionmaker, request, api_settings)
    assert isinstance(starting, dispatch.Starting)

    async def refused_soon() -> None:
        await asyncio.sleep(0.3)
        await dispatch.settle(dispatch_sessionmaker, starting, dispatch.Outcome("refused"))

    left, _ = await asyncio.gather(
        gate.disable_and_wait(admin_sessionmaker, deadline=timedelta(seconds=5)), refused_soon()
    )
    assert left == []
    assert (await state(owner_sessionmaker, request.id))["request"][0] == "queued"


@pytest.mark.usefixtures("production_on")
async def test_the_admin_role_can_disable_the_gate_and_nothing_else(admin_sessionmaker) -> None:
    with pytest.raises(DBAPIError, match="permission denied"):
        async with admin_sessionmaker() as s, s.begin():
            await s.execute(text("update platform_settings set production_runs = true"))


@pytest.fixture
def admin_cli(monkeypatch: pytest.MonkeyPatch, pg_url: str, admin_sessionmaker: Any) -> Any:
    """The CLI, run as `dewpoint_admin` (as the operations docs say), in a thread: it runs its own event loop."""
    monkeypatch.setenv("DEWPOINT_DATABASE_URL", _url_for(pg_url, "dewpoint_admin"))
    monkeypatch.setenv("DEWPOINT_KEK_B64", base64.b64encode(b"k" * 32).decode())
    monkeypatch.setenv("DEWPOINT_PUBLIC_ORIGIN", "https://dewpoint.test")
    get_settings.cache_clear()

    async def invoke(*args: str) -> Any:
        return await asyncio.to_thread(CliRunner().invoke, cli.app, list(args))

    yield invoke
    get_settings.cache_clear()


@pytest.mark.usefixtures("production_on")
async def test_the_command_says_whether_a_start_is_left_unresolved(
    queued, admin_cli, dispatch_sessionmaker, api_settings
) -> None:
    _, _, request = queued
    starting = await begin(dispatch_sessionmaker, request, api_settings)
    assert isinstance(starting, dispatch.Starting)
    unresolved = await admin_cli("platform", "disable-production-runs", "--wait", "0")
    assert (unresolved.exit_code, unresolved.output) == (
        3, f"production runs are off; 1 start is still unresolved: {request.id}\n",
    )  # fmt: skip
    await dispatch.settle(dispatch_sessionmaker, starting, dispatch.Outcome("refused"))
    settled = await admin_cli("platform", "disable-production-runs", "--wait", "0")
    assert (settled.exit_code, settled.output) == (0, "production runs are off; no start is left unresolved\n")
