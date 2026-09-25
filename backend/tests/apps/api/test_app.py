# SPDX-License-Identifier: Apache-2.0
import httpx
from fastapi import APIRouter

from dewpoint.apps.api.main import create_app
from dewpoint.core.config import Settings


def _settings() -> Settings:
    return Settings(
        database_url="postgresql+asyncpg://u:p@localhost/x",
        kek_b64="A" * 43 + "=",
        public_origin="https://dewpoint.test",
    )


async def test_health_ok_and_security_headers() -> None:
    app = create_app(_settings())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://testserver") as c:
        r = await c.get("/health/live")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
    csp = r.headers["content-security-policy"]
    assert (
        "default-src 'self'" in csp
        and "script-src 'self'" in csp
        and "'unsafe-inline'" not in csp.split("script-src")[1].split(";")[0]
    )
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["referrer-policy"] == "no-referrer"
    assert r.headers["strict-transport-security"].startswith("max-age=")


async def test_unhandled_error_is_sanitized() -> None:
    app = create_app(_settings())
    router = APIRouter()

    @router.get("/boom")
    async def boom() -> None:
        raise RuntimeError("secret internal detail")

    app.include_router(router)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url="https://testserver"
    ) as c:
        r = await c.get("/boom")
    assert r.status_code == 500
    assert "secret internal detail" not in r.text
    assert r.json() == {"error": "internal_error"}


async def test_error_envelope_is_flat() -> None:
    from fastapi import HTTPException
    from pydantic import BaseModel

    app = create_app(_settings())
    router = APIRouter()

    class In(BaseModel):
        password: str
        n: int

    @router.get("/denied")
    async def denied() -> None:
        raise HTTPException(403, detail={"error": "step_up_required"})

    @router.post("/typed")
    async def typed(body: In) -> None:
        return None

    app.include_router(router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://testserver") as c:
        assert (await c.get("/denied")).json() == {"error": "step_up_required"}
        assert (await c.get("/missing")).json() == {"error": "not_found"}
        r = await c.post("/typed", json={"password": "hunter2-secret", "n": "x"})
    assert r.status_code == 422 and r.json() == {"error": "invalid", "fields": ["n"]}
    assert "hunter2-secret" not in r.text
