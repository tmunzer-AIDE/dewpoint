# SPDX-License-Identifier: Apache-2.0
"""Writes must be committed before the response starts; otherwise a client that gets 201 and immediately
reads can miss its own write (seen in CI e2e), and a failing commit would follow a success response."""

import json
import uuid

from sqlalchemy import text

from dewpoint.core.auth.sessions import SESSION_COOKIE
from tests.apps.api.helpers import session_client


async def test_created_row_is_committed_when_the_response_starts(app, owner_sessionmaker, api_settings) -> None:
    c, _ = await session_client(app, owner_sessionmaker, api_settings, None, platform_admin=True)
    token, csrf = c.cookies.get(SESSION_COOKIE), c.headers["X-CSRF-Token"]
    await c.aclose()
    slug = f"t-{uuid.uuid4().hex[:10]}"
    body = json.dumps({"name": "Committed", "slug": slug}).encode()
    visible_at_response_start: list[bool] = []

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message: dict[str, object]) -> None:
        if message["type"] == "http.response.start":  # check from another connection, right now
            async with owner_sessionmaker() as s:
                row = await s.execute(text("select 1 from tenants where slug = :s"), {"s": slug})
                visible_at_response_start.append(row.first() is not None)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "https",
        "path": "/api/v1/tenants",
        "raw_path": b"/api/v1/tenants",
        "root_path": "",
        "query_string": b"",
        "server": ("testserver", 443),
        "client": ("127.0.0.1", 50000),
        "headers": [
            (b"host", b"testserver"),
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode()),
            (b"x-dewpoint-client", b"web"),
            (b"x-csrf-token", csrf.encode()),
            (b"cookie", f"{SESSION_COOKIE}={token}".encode()),
        ],
    }
    await app(scope, receive, send)
    assert visible_at_response_start == [True]


def test_db_dependency_is_always_function_scoped() -> None:
    """Guard: a bare Depends(get_db) would reintroduce commit-after-response (and a second session)."""
    import re
    from pathlib import Path

    src = Path(__file__).resolve().parents[3] / "src"
    offenders = [
        f"{p.relative_to(src)}:{n}"
        for p in src.rglob("*.py")
        for n, line in enumerate(p.read_text().splitlines(), 1)
        if re.search(r"Depends\(get_db\s*\)", line)
    ]
    assert offenders == []
