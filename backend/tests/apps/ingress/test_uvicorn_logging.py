# SPDX-License-Identifier: Apache-2.0
"""Ingress's process as `dewpoint ingress` runs it: the command configures the process, then hands its app to
uvicorn with the arguments it chose. An exception in a request or in the lifespan is logged by its type and where it
was raised, never by its text nor its cause's: uvicorn's own logging configuration would replace the process's, and
Starlette sends uvicorn a lifespan failure's formatted traceback as text."""

import asyncio
import base64
import os
from typing import Any

import httpx
import pytest
import uvicorn
from fastapi import FastAPI
from typer.testing import CliRunner

from dewpoint.apps.cli import main as cli
from tests.support.logs import records, rendered, stdlib_restored
from tests.support.server import failed_start, serving

SECRET = "hook-secret-5b2f90"
STARTUP_FAILURE = 3  # uvicorn's exit code


def _raises() -> None:
    try:
        raise KeyError(SECRET)
    except KeyError as e:
        raise RuntimeError(f"refused {SECRET}") from e


async def _developed(sessionmaker: object) -> None:
    pass


async def _refused(sessionmaker: object) -> None:
    _raises()


class _Undisposable:
    async def dispose(self) -> None:
        _raises()


def _served(monkeypatch: pytest.MonkeyPatch) -> tuple[FastAPI, dict[str, Any]]:
    """The app `dewpoint ingress` serves, and the arguments it gives uvicorn: in a development deployment."""
    calls: list[tuple[FastAPI, dict[str, Any]]] = []
    monkeypatch.setattr("uvicorn.run", lambda app, **kwargs: calls.append((app, kwargs)))
    monkeypatch.setattr("dewpoint.apps.ingress.main.require_development", _developed)
    monkeypatch.setenv("DEWPOINT_DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/x")
    monkeypatch.setenv("DEWPOINT_INGRESS_KEY_B64", base64.b64encode(os.urandom(32)).decode())
    for name in ("DEWPOINT_KEK_B64", "DEWPOINT_KEK_PREVIOUS_B64"):
        monkeypatch.delenv(name, raising=False)
    result = CliRunner().invoke(cli.app, ["ingress"])
    assert result.exit_code == 0, result.output
    [served] = calls
    return served


def _logged(err: str, lines: list[str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """uvicorn's records (stderr) and structlog's lines, each a JSON object, none quoting the secret."""
    assert SECRET not in err + "\n".join(lines)
    return records(err.splitlines()), records(lines)


def test_a_request_error_reaches_uvicorns_log_by_its_type_only(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    async def request(app: FastAPI, kwargs: dict[str, Any]) -> httpx.Response:
        async with serving(uvicorn.Config(app, **kwargs)) as url, httpx.AsyncClient(base_url=url) as c:
            return await c.get("/fails")

    with rendered() as lines, stdlib_restored():
        app, kwargs = _served(monkeypatch)

        @app.get("/fails")
        async def fails() -> None:
            _raises()

        r = asyncio.run(request(app, kwargs))
    assert r.status_code == 500
    server, _ = _logged(capsys.readouterr().err, lines())
    [failure] = [record for record in server if "error_type" in record]
    assert (failure["logger"], failure["error_type"]) == ("uvicorn.error", "RuntimeError")
    assert failure["where"][-1].startswith("test_uvicorn_logging.py:_raises:")


def test_a_failed_startup_is_logged_by_its_type_only_and_still_stops_the_server(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    with rendered() as lines, stdlib_restored():
        app, kwargs = _served(monkeypatch)
        monkeypatch.setattr("dewpoint.apps.ingress.main.require_development", _refused)  # its lifespan's check
        code = asyncio.run(failed_start(uvicorn.Config(app, **kwargs)))
    server, structlog_lines = _logged(capsys.readouterr().err, lines())
    assert code == STARTUP_FAILURE
    assert "Application startup failed. Exiting." in [record["event"] for record in server]
    [failure] = [record for record in structlog_lines if record["event"] == "lifespan_failed"]
    assert (failure["phase"], failure["error_type"]) == ("startup", "RuntimeError")
    assert failure["where"][-1].startswith("test_uvicorn_logging.py:_raises:")


def test_a_failed_shutdown_is_logged_by_its_type_only_and_still_reported(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    async def serve(app: FastAPI, kwargs: dict[str, Any]) -> None:
        async with serving(uvicorn.Config(app, **kwargs)):
            pass

    with rendered() as lines, stdlib_restored():
        app, kwargs = _served(monkeypatch)
        engine, app.state.engine = app.state.engine, _Undisposable()  # its lifespan's shutdown disposes it
        asyncio.run(serve(app, kwargs))
        asyncio.run(engine.dispose())
    server, structlog_lines = _logged(capsys.readouterr().err, lines())
    assert "Application shutdown failed. Exiting." in [record["event"] for record in server]
    [failure] = [record for record in structlog_lines if record["event"] == "lifespan_failed"]
    assert (failure["phase"], failure["error_type"]) == ("shutdown", "RuntimeError")
    assert failure["where"][-1].startswith("test_uvicorn_logging.py:_raises:")
