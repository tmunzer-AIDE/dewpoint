# SPDX-License-Identifier: Apache-2.0
import re

from starlette.datastructures import Headers
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; "
    "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'; object-src 'none'"
)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = CSP
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
        response.headers["Cache-Control"] = "no-store"
        return response


class ClientHeaderMiddleware(BaseHTTPMiddleware):
    """Unsafe /api requests must carry X-Dewpoint-Client: web. The custom header forces a CORS preflight,
    blocking cross-site form posts even on unauthenticated endpoints such as login."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.url.path.startswith("/api/") and request.method not in {"GET", "HEAD", "OPTIONS"}:
            if request.headers.get("X-Dewpoint-Client") != "web":
                return JSONResponse({"error": "forbidden"}, status_code=403)
        return await call_next(request)


class BodyLimitMiddleware:
    """Caps request bodies by the bytes actually received. Content-Length can't be relied on: chunked requests have
    none, and FastAPI parses a body before any route dependency could object. The body is buffered up to the limit
    before the app runs; one byte more answers 413 without reading the rest.

    A `streamed` route (a POST whose path it matches whole) reads its own body as it arrives, to a cap it knows only
    once it has authorized the caller (a CSV upload's, engine 2b spec §8.1): it's passed through unread, refused here
    only when it declares more than `streamed_max`, which its own cap never passes."""

    def __init__(
        self, app: ASGIApp, max_bytes: int, streamed: re.Pattern[str] | None = None, streamed_max: int = 0
    ) -> None:
        self.app = app
        self.max_bytes = max_bytes
        self.streamed, self.streamed_max = streamed, streamed_max

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        declared = Headers(scope=scope).get("content-length", "")
        if self.streamed is not None and scope["method"] == "POST" and self.streamed.fullmatch(scope["path"]):
            if declared.isdigit() and int(declared) > self.streamed_max:
                await JSONResponse({"error": "too_large"}, status_code=413)(scope, receive, send)
                return
            await self.app(scope, receive, send)
            return
        if declared.isdigit() and int(declared) > self.max_bytes:
            await JSONResponse({"error": "too_large"}, status_code=413)(scope, receive, send)
            return
        chunks: list[bytes] = []
        size = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                # The client is gone and won't read this; answering keeps the middleware chain from reporting a
                # missing response as a server error.
                await JSONResponse({"error": "bad_request"}, status_code=400)(scope, receive, send)
                return
            chunk = message.get("body", b"")
            size += len(chunk)
            if size > self.max_bytes:
                await JSONResponse({"error": "too_large"}, status_code=413)(scope, receive, send)
                return
            chunks.append(chunk)
            if not message.get("more_body", False):
                break
        replayed = False

        async def replay() -> Message:
            nonlocal replayed
            if replayed:
                return await receive()  # after the body: disconnect notifications
            replayed = True
            return {"type": "http.request", "body": b"".join(chunks), "more_body": False}

        await self.app(scope, replay, send)
