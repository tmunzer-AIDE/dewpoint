# SPDX-License-Identifier: Apache-2.0
from typing import Any


async def test_a_client_that_disconnects_mid_body_gets_no_server_error(app) -> None:  # type: ignore[no-untyped-def]
    inbound: list[dict[str, Any]] = [
        {"type": "http.request", "body": b"{", "more_body": True},
        {"type": "http.disconnect"},
    ]
    sent: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        return inbound.pop(0) if inbound else {"type": "http.disconnect"}

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    path = "/api/v1/t/00000000-0000-0000-0000-000000000000/workflows/00000000-0000-0000-0000-000000000000/draft"
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "PUT",
        "scheme": "https",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [(b"host", b"testserver"), (b"x-dewpoint-client", b"web"), (b"content-type", b"application/json")],
        "client": ("127.0.0.1", 50000),
        "server": ("testserver", 443),
    }
    await app(scope, receive, send)  # must not raise: an aborted upload is the client's doing, not a server error
    start = next(m for m in sent if m["type"] == "http.response.start")
    assert start["status"] == 400
