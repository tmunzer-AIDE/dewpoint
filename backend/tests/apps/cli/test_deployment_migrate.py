# SPDX-License-Identifier: Apache-2.0
"""`dewpoint deployment migrate` (2b-4b M4 recovery, task 7; the plan's ruling 7): the prescribed path for a schema
change. Its intent is recorded off the database host first, then `alembic upgrade head` runs, then its outcome. It
refuses to run in production without the administration sink. It claims nothing about an administrator who runs
Alembic directly: that's the trusted exception, seen only as persistent drift by the monitor. Alembic itself is a
stand-in here; the suite's database is already at head."""

import asyncio
import json
from typing import Any

import pytest
from typer.testing import CliRunner

from dewpoint.apps.cli import main as cli
from dewpoint.apps.cli import recovery
from dewpoint.apps.cli.main import app
from dewpoint.core.audit.administration import AdministrationSink
from dewpoint.core.db import make_engine, make_sessionmaker
from tests.apps.cli.test_audit_cli import _env
from tests.core.audit.fake_s3 import FakeS3

PREFIX = "dewpoint/database-administration/"


async def _revision(pg_url: str) -> str:
    from sqlalchemy import text

    engine = make_engine(pg_url)
    try:
        async with make_sessionmaker(engine)() as s:
            return str((await s.execute(text("select version_num from alembic_version"))).scalar_one())
    finally:
        await engine.dispose()


def _records(bucket: FakeS3) -> list[dict[str, Any]]:
    return [json.loads(v.body) for v in bucket.versions if v.body]


@pytest.fixture
def sink(monkeypatch: pytest.MonkeyPatch) -> FakeS3:
    bucket = FakeS3()
    monkeypatch.setattr(recovery, "administration_sink",
                        lambda settings: AdministrationSink(bucket, "audit-anchors", PREFIX))  # fmt: skip
    return bucket


def _alembic(monkeypatch: pytest.MonkeyPatch, bucket: FakeS3 | None, code: int = 0) -> list[int]:
    """Alembic's stand-in: how many records were written when it ran, its exit code `code`."""
    ran: list[int] = []

    def upgrade() -> int:
        ran.append(len(bucket.versions) if bucket is not None else 0)
        return code

    monkeypatch.setattr(cli, "_alembic_upgrade", upgrade)
    return ran


def test_migrate_records_its_intent_runs_alembic_then_records_its_outcome(
    pg_url: str, monkeypatch: pytest.MonkeyPatch, sink: FakeS3
) -> None:
    _env(monkeypatch, pg_url, DEWPOINT_ENVIRONMENT="production")
    ran = _alembic(monkeypatch, sink)
    result = CliRunner().invoke(app, ["deployment", "migrate"])
    assert result.exit_code == 0, result.output
    assert ran == [1]  # after its intent, before its outcome
    head = asyncio.run(_revision(pg_url))
    intent, outcome = _records(sink)
    assert (intent["action"], intent["phase"], intent["from"], intent["target"]) == (
        "migration",
        "intent",
        head,
        "head",
    )
    assert (outcome["phase"], outcome["status"], outcome["to"], outcome["exit"]) == ("outcome", "succeeded", head, 0)
    assert intent["action_id"] == outcome["action_id"]


def test_migrate_refuses_in_production_without_the_sink_and_runs_nothing(
    pg_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _env(monkeypatch, pg_url, DEWPOINT_ENVIRONMENT="production")
    monkeypatch.setattr(recovery, "administration_sink", lambda settings: None)
    ran = _alembic(monkeypatch, None)
    result = CliRunner().invoke(app, ["deployment", "migrate"])
    assert result.exit_code == 2 and "administration" in result.output, result.output
    assert ran == []


def test_a_failed_intent_runs_nothing(pg_url: str, monkeypatch: pytest.MonkeyPatch, sink: FakeS3) -> None:
    _env(monkeypatch, pg_url, DEWPOINT_ENVIRONMENT="production")
    monkeypatch.setattr(AdministrationSink, "write", lambda self, record: (_ for _ in ()).throw(OSError("refused")))
    ran = _alembic(monkeypatch, sink)
    result = CliRunner().invoke(app, ["deployment", "migrate"])
    assert result.exit_code != 0 and ran == []


def test_a_failed_migration_is_recorded_and_its_code_returned(
    pg_url: str, monkeypatch: pytest.MonkeyPatch, sink: FakeS3
) -> None:
    _env(monkeypatch, pg_url, DEWPOINT_ENVIRONMENT="production")
    _alembic(monkeypatch, sink, code=3)
    result = CliRunner().invoke(app, ["deployment", "migrate"])
    assert result.exit_code == 3, result.output
    [_, outcome] = _records(sink)
    assert (outcome["status"], outcome["exit"]) == ("failed", 3)


def test_development_migrates_without_the_sink_and_says_so(pg_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    _env(monkeypatch, pg_url, DEWPOINT_ENVIRONMENT="development")
    monkeypatch.setattr(recovery, "administration_sink", lambda settings: None)
    ran = _alembic(monkeypatch, None)
    result = CliRunner().invoke(app, ["deployment", "migrate"])
    assert result.exit_code == 0 and ran == [0] and "no off-host record" in result.output, result.output
