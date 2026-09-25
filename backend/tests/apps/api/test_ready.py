# SPDX-License-Identifier: Apache-2.0
import httpx

from dewpoint.apps.api.main import create_app
from dewpoint.core.config import Settings


async def test_ready_ok(client) -> None:
    r = await client.get("/health/ready")
    assert r.status_code == 200 and r.json() == {"status": "ready"}


async def test_ready_unavailable() -> None:
    app = create_app(
        Settings(
            database_url="postgresql+asyncpg://u:p@127.0.0.1:1/x",
            kek_b64="A" * 43 + "=",
            public_origin="https://testserver",
        )
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://testserver") as c:
        r = await c.get("/health/ready")
    assert r.status_code == 503 and r.json() == {"status": "unavailable"}
