# SPDX-License-Identifier: Apache-2.0
"""A process that talks to Temporal refuses to start unless its namespace is the one this deployment recorded (engine
2b spec §2.1): the worker, and the CLI's Temporal commands."""

import base64

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from typer.testing import CliRunner

from dewpoint.apps.cli import main as cli
from dewpoint.apps.worker.main import run
from dewpoint.core.config import Settings, get_settings
from dewpoint.core.platform.service import (
    DEVELOPMENT,
    EnvironmentMismatchError,
    EnvironmentNotRecordedError,
    record_environment,
)
from tests.conftest import _url_for


def worker_settings(pg_url: str, namespace: str = "default") -> Settings:
    return Settings(
        database_url=_url_for(pg_url, "dewpoint_worker"),
        kek_b64=base64.b64encode(b"k" * 32).decode(),
        public_origin="https://dewpoint.test",
        temporal_address="127.0.0.1:1",  # never reached: the check comes first
        temporal_namespace=namespace,
    )


@pytest.mark.usefixtures("_test_users")
async def test_a_worker_wont_start_before_the_environment_is_recorded(pg_url: str) -> None:
    with pytest.raises(EnvironmentNotRecordedError):
        await run(worker_settings(pg_url))


@pytest.mark.usefixtures("_test_users")
async def test_a_worker_wont_serve_another_namespace(
    pg_url: str, owner_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    async with owner_sessionmaker() as s, s.begin():
        await record_environment(s, environment=DEVELOPMENT, namespace="dewpoint-dev")
    with pytest.raises(EnvironmentMismatchError, match="configured for `default`"):
        await run(worker_settings(pg_url))


def test_the_clis_temporal_commands_wont_connect_before_the_record(
    monkeypatch: pytest.MonkeyPatch, pg_url: str, _test_users: None
) -> None:
    monkeypatch.setenv("DEWPOINT_DATABASE_URL", _url_for(pg_url, "dewpoint_dispatch"))
    monkeypatch.setenv("DEWPOINT_KEK_B64", base64.b64encode(b"k" * 32).decode())
    monkeypatch.setenv("DEWPOINT_PUBLIC_ORIGIN", "https://dewpoint.test")
    get_settings.cache_clear()
    result = CliRunner().invoke(cli.app, ["deployment", "status"])
    assert result.exit_code == 2
    assert "isn't recorded" in result.output
