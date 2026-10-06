# SPDX-License-Identifier: Apache-2.0
"""The API's process as its image runs it, `uvicorn ... --factory`: uvicorn configures logging, then calls the
factory, which configures the process. An exception in a request or in the lifespan is logged by its type and where
it was raised, never by its text nor its cause's: Starlette re-raises a request's exception after the 500, for
uvicorn's own logger to print, and sends uvicorn a lifespan failure's formatted traceback as text."""

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any

import httpx
import pytest
import uvicorn
from fastapi import FastAPI

from dewpoint.apps.api.main import create_app
from dewpoint.core.config import Settings
from tests.support.logs import records, rendered, stdlib_restored
from tests.support.server import failed_start, serving

SECRET = "pw-plaintext-0d4e7a"
STARTUP_FAILURE = 3  # uvicorn's exit code


def _settings() -> Settings:
    return Settings(
        database_url="postgresql+asyncpg://u:p@localhost/x",
        kek_b64="A" * 43 + "=",
        public_origin="https://dewpoint.test",
    )


def _raises() -> None:
    try:
        raise KeyError(SECRET)
    except KeyError as e:
        raise RuntimeError(f"no account accepts {SECRET}") from e


class _Unclosable:
    async def aclose(self) -> None:
        _raises()


def _factory(made: list[FastAPI], change: Callable[[FastAPI], None]) -> Callable[[], FastAPI]:
    """The API's factory, its app changed by the test before uvicorn serves it."""

    def factory() -> FastAPI:
        app = create_app(_settings())
        made.append(app)
        change(app)
        return app

    return factory


def _routed(app: FastAPI) -> None:
    @app.get("/fails")
    async def fails() -> None:
        _raises()


def _refused(app: FastAPI) -> None:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        _raises()
        yield

    app.router.lifespan_context = lifespan


def _unclosable(app: FastAPI) -> None:
    app.state.client, app.state.http = app.state.http, _Unclosable()  # its lifespan's shutdown closes it


def _logged(err: str, lines: list[str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """uvicorn's records (stderr) and structlog's lines, each a JSON object, none quoting the secret."""
    assert SECRET not in err + "\n".join(lines)
    return records(err.splitlines()), records(lines)


async def test_a_request_error_reaches_uvicorns_log_by_its_type_only(capsys: pytest.CaptureFixture[str]) -> None:
    made: list[FastAPI] = []
    with rendered() as lines, stdlib_restored():
        async with serving(uvicorn.Config(_factory(made, _routed), factory=True)) as url:
            async with httpx.AsyncClient(base_url=url) as c:
                r = await c.get("/fails")
    assert (r.status_code, r.json()) == (500, {"error": "internal_error"})
    server, _ = _logged(capsys.readouterr().err, lines())
    [failure] = [record for record in server if "error_type" in record]
    assert (failure["logger"], failure["error_type"]) == ("uvicorn.error", "RuntimeError")
    assert failure["where"][-1].startswith("test_uvicorn_logging.py:_raises:")


async def test_a_failed_startup_is_logged_by_its_type_only_and_still_stops_the_server(
    capsys: pytest.CaptureFixture[str],
) -> None:
    made: list[FastAPI] = []
    with rendered() as lines, stdlib_restored():
        code = await failed_start(uvicorn.Config(_factory(made, _refused), factory=True))
    for app in made:
        await app.state.http.aclose()
    server, structlog_lines = _logged(capsys.readouterr().err, lines())
    assert code == STARTUP_FAILURE
    assert "Application startup failed. Exiting." in [record["event"] for record in server]
    [failure] = [record for record in structlog_lines if record["event"] == "lifespan_failed"]
    assert (failure["phase"], failure["error_type"]) == ("startup", "RuntimeError")
    assert failure["where"][-1].startswith("test_uvicorn_logging.py:_raises:")


async def test_a_failed_shutdown_is_logged_by_its_type_only_and_still_reported(
    capsys: pytest.CaptureFixture[str],
) -> None:
    made: list[FastAPI] = []
    with rendered() as lines, stdlib_restored():
        async with serving(uvicorn.Config(_factory(made, _unclosable), factory=True)):
            pass
    for app in made:
        await app.state.client.aclose()
        await app.state.engine.dispose()
    server, structlog_lines = _logged(capsys.readouterr().err, lines())
    assert "Application shutdown failed. Exiting." in [record["event"] for record in server]
    [failure] = [record for record in structlog_lines if record["event"] == "lifespan_failed"]
    assert (failure["phase"], failure["error_type"]) == ("shutdown", "RuntimeError")
    assert failure["where"][-1].startswith("test_uvicorn_logging.py:_raises:")
