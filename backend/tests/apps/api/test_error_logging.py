# SPDX-License-Identifier: Apache-2.0
"""An unhandled error is logged by its type and where it was raised, never by a value: not a frame's local variables
(a password a route read from its body), not the exception's text. structlog's defaults render a rich traceback with
every frame's locals."""

import json

import httpx
from fastapi import APIRouter, Request

from dewpoint.apps.api.main import create_app
from dewpoint.core.config import Settings
from tests.support.logs import rendered

PASSWORD = "hunter2-plaintext-6c1f"


def _settings() -> Settings:
    return Settings(
        database_url="postgresql+asyncpg://u:p@localhost/x",
        kek_b64="A" * 43 + "=",
        public_origin="https://dewpoint.test",
    )


def _verify(password: str, message: str) -> None:
    attempt = {"email": "ann@corp.test", "password": password}
    if attempt["password"]:
        raise RuntimeError(message)


async def _login(path: str, message: str) -> list[str]:
    """POST a password to a route that reads it, then fails: the lines the API's process logged."""
    with rendered() as lines:
        app = create_app(_settings())
        router = APIRouter()

        @router.post(path)
        async def login(request: Request) -> None:
            password = (await request.json())["password"]
            _verify(password, message.format(password=password))

        app.include_router(router)
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="https://testserver") as c:
            r = await c.post(path, json={"email": "ann@corp.test", "password": PASSWORD})
        await app.state.engine.dispose()
    assert r.status_code == 500 and r.json() == {"error": "internal_error"}
    return lines()


async def test_an_unhandled_error_never_logs_a_frames_locals() -> None:
    lines = await _login("/login", "the login backend is down")
    assert PASSWORD not in "\n".join(lines)
    [record] = [json.loads(line) for line in lines]
    assert record["event"] == "unhandled_error" and record["path"] == "/login"
    assert record["error_type"] == "RuntimeError"
    assert record["where"][-1].startswith("test_error_logging.py:_verify:")


async def test_an_unhandled_error_never_logs_its_text() -> None:
    lines = await _login("/login-text", "no account accepts {password}")
    assert PASSWORD not in "\n".join(lines)
    [record] = [json.loads(line) for line in lines]
    assert record["error_type"] == "RuntimeError"
