# SPDX-License-Identifier: Apache-2.0
"""`dewpoint retention` (engine 2b spec §10.3): its own process, as the retention login, sweeping every interval; a
sweep that fails is logged and the next one tried. Its settings come from its environment only and hold no key."""

import asyncio
from typing import Any

import pytest
from typer.testing import CliRunner

from dewpoint.apps import retention
from dewpoint.apps.cli.main import app
from dewpoint.core.retention import sweep
from tests.conftest import _url_for
from tests.core.retention.support import OLD, TREE_ROWS, count, tenant, tree


async def test_one_sweep_deletes_what_passed_its_cutoff(pg_url, _test_users, owner_sessionmaker) -> None:
    ctx = await tenant(owner_sessionmaker)
    old = await tree(owner_sessionmaker, ctx, OLD)
    settings = retention.RetentionSettings(database_url=_url_for(pg_url, "dewpoint_retention"))
    done = await retention.run(settings, once=True)
    assert done is not None and done.succeeded
    assert await count(owner_sessionmaker, TREE_ROWS, r=old["root"]) == 0


async def test_a_failed_sweep_is_logged_and_the_next_one_tried(monkeypatch, pg_url, _test_users) -> None:
    calls: list[str] = []

    async def failing_then_fine(sessionmaker: Any, *, batch: int) -> sweep.Sweep:
        calls.append("sweep")
        if len(calls) == 1:
            raise ConnectionError("the database went away")
        return sweep.Sweep(1, True, 0, 0.0)

    class Stop(Exception):
        pass

    async def sleep(seconds: float) -> None:
        calls.append(f"sleep {seconds:g}")
        if calls.count("sweep") == 2:
            raise Stop

    monkeypatch.setattr(retention, "sweep_all", failing_then_fine)
    monkeypatch.setattr(asyncio, "sleep", sleep)
    settings = retention.RetentionSettings(database_url=_url_for(pg_url, "dewpoint_retention"), retention_interval_s=90)
    with pytest.raises(Stop):
        await retention.run(settings)
    assert calls == ["sweep", "sleep 90", "sweep", "sleep 90"]


def test_its_settings_hold_no_key_and_bound_the_interval(monkeypatch) -> None:
    monkeypatch.setenv("DEWPOINT_DATABASE_URL", "postgresql+asyncpg://r@h/d")
    monkeypatch.setenv("DEWPOINT_KEK_B64", "k" * 44)
    settings = retention.RetentionSettings()
    assert not [name for name in settings.model_dump() if "kek" in name]
    assert settings.retention_interval_s == 3600
    for wrong in ("59", str(6 * 3600 + 1)):
        monkeypatch.setenv("DEWPOINT_RETENTION_INTERVAL_S", wrong)
        with pytest.raises(ValueError, match="retention_interval_s"):
            retention.RetentionSettings()


def test_the_command_sweeps_once_and_says_whether_it_succeeded(monkeypatch, pg_url, _test_users) -> None:
    monkeypatch.setenv("DEWPOINT_DATABASE_URL", _url_for(pg_url, "dewpoint_retention"))
    answer = CliRunner().invoke(app, ["retention", "--once"])
    assert answer.exit_code == 0, answer.output
    assert "retention sweep" in answer.output and "succeeded" in answer.output


def test_the_command_says_when_another_sweep_is_running(monkeypatch, pg_url, _test_users) -> None:
    async def busy(sessionmaker: Any, *, batch: int) -> None:
        return None

    monkeypatch.setattr(retention, "sweep_all", busy)
    monkeypatch.setenv("DEWPOINT_DATABASE_URL", _url_for(pg_url, "dewpoint_retention"))
    answer = CliRunner().invoke(app, ["retention", "--once"])
    assert answer.exit_code == 1 and "another retention sweep is running" in answer.output, answer.output
