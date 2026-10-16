# SPDX-License-Identifier: Apache-2.0
import asyncio
import base64
import os
import signal
import uuid

from typer.testing import CliRunner

from dewpoint.apps import stopping
from dewpoint.apps.cli.main import app
from dewpoint.core.audit.service import record
from dewpoint.core.config import get_settings
from dewpoint.core.db import make_engine, make_sessionmaker, tenant_scope
from tests.conftest import _url_for


async def _seed(url: str) -> None:
    engine = make_engine(url)  # own engine: this runs on its own event loop via asyncio.run
    try:
        async with make_sessionmaker(engine)() as s, s.begin():
            t = uuid.uuid4()
            await tenant_scope(s, t)
            await record(s, tenant_id=t, actor_id=None, action="member.add")
    finally:
        await engine.dispose()


def _env(monkeypatch, url: str, **extra: str) -> None:  # type: ignore[no-untyped-def]
    base = {
        "DEWPOINT_DATABASE_URL": url,
        "DEWPOINT_KEK_B64": base64.b64encode(os.urandom(32)).decode(),
        "DEWPOINT_PUBLIC_ORIGIN": "https://dewpoint.test",
    }
    for k, v in {**base, **extra}.items():
        monkeypatch.setenv(k, v)
    for k in ("DEWPOINT_AUDIT_SIGNING_KEY_B64", "DEWPOINT_AUDIT_ANCHOR_PATH"):
        if k not in extra:
            monkeypatch.delenv(k, raising=False)
    get_settings.cache_clear()


def test_anchor_then_verify_as_auditor(pg_url, _test_users, tmp_path, monkeypatch) -> None:
    asyncio.run(_seed(_url_for(pg_url, "dewpoint_api")))
    runner = CliRunner()
    auditor = _url_for(pg_url, "dewpoint_auditor")
    signing = {
        "DEWPOINT_AUDIT_SIGNING_KEY_B64": base64.b64encode(os.urandom(32)).decode(),
        "DEWPOINT_AUDIT_ANCHOR_PATH": str(tmp_path / "anchors.jsonl"),
    }
    _env(monkeypatch, auditor, **signing)
    empty = runner.invoke(app, ["audit", "verify"])
    assert empty.exit_code == 1 and "no external anchors found" in empty.output

    anchored = runner.invoke(app, ["audit", "anchor"])
    assert anchored.exit_code == 0 and "anchored 1 scope head(s)" in anchored.output
    verified = runner.invoke(app, ["audit", "verify"])
    assert verified.exit_code == 0, verified.output

    fresh = runner.invoke(app, ["audit", "freshness", "--max-age-minutes", "0"])
    assert fresh.exit_code == 0 and "anchors are fresh" in fresh.output
    asyncio.run(_seed(_url_for(pg_url, "dewpoint_api")))  # a new, unanchored row
    stale = runner.invoke(app, ["audit", "freshness", "--max-age-minutes", "0"])
    assert stale.exit_code == 1 and "no anchor" in stale.output

    _env(monkeypatch, auditor)  # misconfigured: no key / path
    assert runner.invoke(app, ["audit", "anchor"]).exit_code == 2
    assert runner.invoke(app, ["audit", "anchor", "--every", "900"]).exit_code == 2  # its settings, at its first run


def test_the_anchor_job_anchors_each_interval_until_sigterm_then_exits_0(
    pg_url, _test_users, tmp_path, monkeypatch
) -> None:
    """Compose's audit-anchor: each run is the one-shot's (the second finds the head anchored); Compose's SIGTERM,
    during a wait, ends it at once with exit 0, and what it wrote verifies."""
    asyncio.run(_seed(_url_for(pg_url, "dewpoint_api")))
    _env(monkeypatch, _url_for(pg_url, "dewpoint_auditor"), **_signing(tmp_path))
    waits: list[float] = []

    async def pause(requested: asyncio.Event, seconds: float) -> None:
        waits.append(seconds)
        if len(waits) == 2:
            os.kill(os.getpid(), signal.SIGTERM)  # Compose's stop, during the second wait
            await asyncio.wait_for(requested.wait(), 10)

    monkeypatch.setattr(stopping, "pause", pause)
    result = CliRunner().invoke(app, ["audit", "anchor", "--every", "900"])
    assert result.exit_code == 0, result.output  # leave(0)
    assert waits == [900, 900]
    assert [line for line in result.output.splitlines() if line.startswith("anchored")] == [
        "anchored 1 scope head(s)", "anchored 0 scope head(s)"]  # fmt: skip
    assert CliRunner().invoke(app, ["audit", "verify"]).exit_code == 0


def test_a_stop_during_an_anchor_run_lets_it_record_its_anchors(pg_url, _test_users, tmp_path, monkeypatch) -> None:
    """SIGTERM while a run writes: the run ends, its anchors recorded (fresh), and no other begins. The real wait, an
    hour long, ends at once; bounded, so a regression fails in 10 s instead of hanging."""
    import dewpoint.apps.cli.main as cli

    asyncio.run(_seed(_url_for(pg_url, "dewpoint_api")))
    _env(monkeypatch, _url_for(pg_url, "dewpoint_auditor"), **_signing(tmp_path))
    real_anchor, real_pause = cli.anchor_all, stopping.pause

    async def signalled(s, sink):  # type: ignore[no-untyped-def]
        os.kill(os.getpid(), signal.SIGTERM)
        return await real_anchor(s, sink)

    async def bounded(requested: asyncio.Event, seconds: float) -> None:
        await asyncio.wait_for(real_pause(requested, seconds), 10)

    monkeypatch.setattr(cli, "anchor_all", signalled)
    monkeypatch.setattr(stopping, "pause", bounded)
    result = CliRunner().invoke(app, ["audit", "anchor", "--every", "3600"])
    assert result.exit_code == 0 and result.output.count("anchored 1 scope head(s)") == 1, result.output
    assert CliRunner().invoke(app, ["audit", "freshness", "--max-age-minutes", "0"]).exit_code == 0


def test_a_failed_run_ends_the_anchor_job_with_exit_1(tmp_path, monkeypatch) -> None:
    """Nothing listens there: the first run fails, and the job ends rather than retry (restart: "no")."""
    _env(monkeypatch, "postgresql+asyncpg://dewpoint_auditor_login:x@127.0.0.1:1/dewpoint", **_signing(tmp_path))
    result = CliRunner().invoke(app, ["audit", "anchor", "--every", "900"])
    assert result.exit_code == 1 and "anchored" not in result.output


async def _deployment(url: str, environment: str) -> None:
    from dewpoint.core.platform.service import record_environment

    engine = make_engine(url)
    try:
        async with make_sessionmaker(engine)() as s, s.begin():
            await record_environment(s, environment=environment, namespace="default")
    finally:
        await engine.dispose()


def _signing(tmp_path) -> dict[str, str]:  # type: ignore[no-untyped-def]
    return {
        "DEWPOINT_AUDIT_SIGNING_KEY_B64": base64.b64encode(os.urandom(32)).decode(),
        "DEWPOINT_AUDIT_ANCHOR_PATH": str(tmp_path / "anchors.jsonl"),
    }


def test_prune_is_refused_in_production_until_an_off_host_sink(pg_url, _test_users, tmp_path, monkeypatch) -> None:
    """Engine 2b-4 ruling D5: pruning is disabled in production until #3's sink is configured."""
    asyncio.run(_deployment(pg_url, "production"))
    _env(monkeypatch, _url_for(pg_url, "dewpoint_auditor"), **_signing(tmp_path))
    refused = CliRunner().invoke(app, ["audit", "prune"])
    assert refused.exit_code == 2 and "disabled" in refused.output and "off-host" in refused.output


def test_prune_in_development_says_what_it_pruned(pg_url, _test_users, tmp_path, monkeypatch) -> None:
    asyncio.run(_deployment(pg_url, "development"))
    asyncio.run(_seed(_url_for(pg_url, "dewpoint_api")))  # a new entry: within any retention
    _env(monkeypatch, _url_for(pg_url, "dewpoint_auditor"), DEWPOINT_AUDIT_RETENTION_DAYS="30", **_signing(tmp_path))
    pruned = CliRunner().invoke(app, ["audit", "prune"])
    assert pruned.exit_code == 0 and "pruned 0 entries in 0 scope(s)" in pruned.output, pruned.output
