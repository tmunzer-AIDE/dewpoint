# SPDX-License-Identifier: Apache-2.0
"""`dewpoint ingress` serves webhook ingress (engine 2b spec §8.3): from its own settings, never with a key-encryption
key in its environment, only in a development deployment, and with the server's own proxy-header handling off (ingress
reads X-Forwarded-For itself, from configured proxies only)."""

import asyncio
import base64
import os

import pytest
from typer.testing import CliRunner

from dewpoint.apps.cli.main import app
from dewpoint.core.db import make_engine, make_sessionmaker
from dewpoint.core.platform.service import DEVELOPMENT, PRODUCTION, record_environment
from tests.conftest import _url_for


def _record(pg_url: str, environment: str) -> None:
    async def run() -> None:
        engine = make_engine(pg_url)
        async with make_sessionmaker(engine)() as s, s.begin():
            await record_environment(s, environment=environment, namespace="default")
        await engine.dispose()

    asyncio.run(run())


@pytest.fixture
def served(monkeypatch, pg_url, _test_users):  # type: ignore[no-untyped-def]
    calls = []
    monkeypatch.setattr("uvicorn.run", lambda app, **kwargs: calls.append(kwargs))
    monkeypatch.setenv("DEWPOINT_DATABASE_URL", _url_for(pg_url, "dewpoint_ingress"))
    monkeypatch.setenv("DEWPOINT_INGRESS_KEY_B64", base64.b64encode(os.urandom(32)).decode())
    for name in ("DEWPOINT_KEK_B64", "DEWPOINT_KEK_PREVIOUS_B64"):
        monkeypatch.delenv(name, raising=False)
    return calls


def test_in_development_it_serves_without_the_servers_proxy_headers(served, pg_url) -> None:
    _record(pg_url, DEVELOPMENT)
    result = CliRunner().invoke(app, ["ingress", "--port", "8100"])
    assert result.exit_code == 0, result.output
    # uvicorn's own logging configuration stays off: it would replace the process's
    assert served == [
        {
            "host": "127.0.0.1",
            "port": 8100,
            "proxy_headers": False,
            "server_header": False,
            "log_config": None,
            "log_level": "info",
        }
    ]


def test_outside_development_it_refuses_to_start(served, pg_url) -> None:
    result = CliRunner().invoke(app, ["ingress"])
    assert (result.exit_code, served) == (2, [])
    assert "development deployment" in result.output
    _record(pg_url, PRODUCTION)
    result = CliRunner().invoke(app, ["ingress"])
    assert (result.exit_code, served) == (2, [])


@pytest.mark.parametrize("name", ["DEWPOINT_KEK_B64", "DEWPOINT_KEK_PREVIOUS_B64"])
def test_a_key_encryption_key_in_its_environment_refuses_the_start(served, monkeypatch, name) -> None:
    monkeypatch.setenv(name, base64.b64encode(b"k" * 32).decode())
    result = CliRunner().invoke(app, ["ingress"])
    assert (result.exit_code, served) == (2, [])
    assert name in result.output
    assert base64.b64encode(b"k" * 32).decode() not in result.output
