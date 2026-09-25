# SPDX-License-Identifier: Apache-2.0
import base64
import os

from sqlalchemy import select
from typer.testing import CliRunner

from dewpoint.apps.cli.main import app
from dewpoint.core.config import get_settings
from dewpoint.core.models.identity import User


def _env(pg_url: str) -> dict[str, str]:
    return {
        "DEWPOINT_DATABASE_URL": pg_url,
        "DEWPOINT_KEK_B64": base64.b64encode(os.urandom(32)).decode(),
        "DEWPOINT_PUBLIC_ORIGIN": "https://dewpoint.test",
        "DEWPOINT_INIT_PASSWORD": "violet-otter-canyon-42",
    }


def test_admin_init_creates_platform_admin_once(pg_url, monkeypatch) -> None:
    for k, v in _env(pg_url).items():
        monkeypatch.setenv(k, v)
    get_settings.cache_clear()
    runner = CliRunner()
    first = runner.invoke(app, ["admin", "init", "--email", "root@corp.test"])
    assert first.exit_code == 0, first.output
    second = runner.invoke(app, ["admin", "init", "--email", "other@corp.test"])
    assert second.exit_code == 1
    assert "already initialized" in second.output


async def test_admin_row(owner_sessionmaker, pg_url, monkeypatch) -> None:
    for k, v in _env(pg_url).items():
        monkeypatch.setenv(k, v)
    get_settings.cache_clear()
    import asyncio

    await asyncio.to_thread(CliRunner().invoke, app, ["admin", "init", "--email", "root@corp.test"])
    async with owner_sessionmaker() as s:
        u = (await s.execute(select(User))).scalar_one()
    assert u.is_platform_admin and u.email == "root@corp.test"
