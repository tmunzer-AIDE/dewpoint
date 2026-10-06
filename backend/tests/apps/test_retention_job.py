# SPDX-License-Identifier: Apache-2.0
"""`dewpoint retention` (engine 2b spec §10.3): its own process, as the retention login, sweeping every interval; a
sweep that fails is logged and the next one tried. Its settings come from its environment only and hold no key."""

import asyncio
from typing import Any

import pytest
import structlog
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

    async def sleep(seconds: float) -> None:
        calls.append(f"sleep {seconds:g}")
        if calls.count("sweep") == 2:
            raise Stop

    monkeypatch.setattr(retention, "sweep_all", failing_then_fine)
    monkeypatch.setattr(asyncio, "sleep", sleep)
    settings = retention.RetentionSettings(database_url=_url_for(pg_url, "dewpoint_retention"), retention_interval_s=90,
                                           erasure_interval_s=90)  # fmt: skip
    with pytest.raises(Stop):
        await retention.run(settings)
    assert calls == ["sweep", "sleep 90", "sweep", "sleep 90"]


class Stop(Exception):
    pass


async def test_each_interval_carries_erasures_on_and_each_sweep_reconciles_completed_ones(
    monkeypatch, pg_url, _test_users, development_deployment
) -> None:
    """2b-4a M4: an erasure pass every `erasure_interval_s`; the reconciliation after completion with every sweep."""
    calls: list[str] = []

    async def swept(_: Any, *, batch: int) -> sweep.Sweep:
        calls.append("sweep")
        return sweep.Sweep(1, True, 0, 0.0)

    async def reconciled(_: Any, client: Any) -> dict[str, int]:
        calls.append(f"reconcile {client}")
        return {}

    async def erased(_: Any, client: Any) -> dict[str, int]:
        calls.append(f"erase {client}")
        return {}

    async def connected(settings: Any) -> str:
        return f"temporal@{settings.temporal_address}"

    async def sleep(seconds: float) -> None:
        calls.append(f"sleep {seconds:g}")
        if calls.count("sweep") == 2:
            raise Stop

    for name, fake in (("sweep_all", swept), ("reconcile_erased", reconciled), ("erase_pass", erased),
                       ("connect", connected)):  # fmt: skip
        monkeypatch.setattr(retention, name, fake)
    monkeypatch.setattr(asyncio, "sleep", sleep)
    settings = retention.RetentionSettings(
        database_url=_url_for(pg_url, "dewpoint_retention"),
        retention_interval_s=120,
        erasure_interval_s=60,
        temporal_address="temporal:7233",
    )
    with pytest.raises(Stop):
        await retention.run(settings)
    t = "temporal@temporal:7233"
    assert calls == ["sweep", f"reconcile {t}", f"erase {t}", "sleep 60", f"erase {t}", "sleep 60",
                     "sweep", f"reconcile {t}", f"erase {t}", "sleep 60"]  # fmt: skip


async def test_without_temporal_an_erasure_under_way_alerts_every_interval(
    monkeypatch, pg_url, _test_users, owner_sessionmaker
) -> None:
    import uuid

    import structlog

    from tests.core.retention.support import sql

    ctx = await tenant(owner_sessionmaker)
    await sql(owner_sessionmaker, "update tenants set status = 'erasing' where id = :t", t=ctx["t"])
    await sql(owner_sessionmaker, "insert into tenant_erasures (tenant_id, requested_by) values (:t, :u)", t=ctx["t"],
              u=uuid.uuid4())  # fmt: skip

    async def sleep(seconds: float) -> None:
        raise Stop

    monkeypatch.setattr(asyncio, "sleep", sleep)
    settings = retention.RetentionSettings(database_url=_url_for(pg_url, "dewpoint_retention"))
    with structlog.testing.capture_logs() as logs, pytest.raises(Stop):
        await retention.run(settings)
    assert [(e["event"], e.get("erasures")) for e in logs if e["log_level"] == "error"] == [("erasures_unattended", 1)]


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


@pytest.mark.parametrize(("recorded", "alert"), [("another", "erasure_namespace_mismatch"),
                                                 (None, "erasure_environment_unrecorded")])  # fmt: skip
async def test_no_erasure_work_reaches_temporal_unless_its_namespace_is_the_deployments(
    monkeypatch, pg_url, _test_users, owner_sessionmaker, recorded: str | None, alert: str
) -> None:
    """2b-4a M4 (the owner's ruling, a blocker): erasure pauses and deletes Temporal resources, so the retention process
    compares its namespace with the one the deployment recorded (engine 2b spec §2.1) before it connects; on a mismatch
    (or none recorded) it makes no Temporal call, alerts every interval, and keeps sweeping."""
    from dewpoint.core.platform.service import DEVELOPMENT, record_environment

    if recorded is not None:
        async with owner_sessionmaker() as s, s.begin():
            await record_environment(s, environment=DEVELOPMENT, namespace=recorded)
    calls: list[str] = []

    async def swept(_: Any, *, batch: int) -> sweep.Sweep:
        calls.append("sweep")
        return sweep.Sweep(1, True, 0, 0.0)

    async def connected(_: Any) -> Any:
        raise AssertionError("connected to Temporal")

    async def sleep(seconds: float) -> None:
        calls.append("sleep")
        if calls.count("sleep") == 2:
            raise Stop

    monkeypatch.setattr(retention, "sweep_all", swept)
    monkeypatch.setattr(retention, "connect", connected)
    monkeypatch.setattr(asyncio, "sleep", sleep)
    settings = retention.RetentionSettings(
        database_url=_url_for(pg_url, "dewpoint_retention"),
        retention_interval_s=60,
        erasure_interval_s=60,
        temporal_address="temporal:7233",
        temporal_namespace="default",
    )
    with structlog.testing.capture_logs() as logs, pytest.raises(Stop):
        await retention.run(settings)
    assert calls == ["sweep", "sleep", "sweep", "sleep"]  # sweeping goes on
    assert [e["event"] for e in logs if e["log_level"] == "error"] == [alert, alert]
