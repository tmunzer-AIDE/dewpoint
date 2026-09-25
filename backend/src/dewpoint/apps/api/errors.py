# SPDX-License-Identifier: Apache-2.0
import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = structlog.get_logger(__name__)

_STATUS_CODES = {
    400: "bad_request",
    401: "unauthenticated",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    422: "invalid",
    429: "rate_limited",
}


def install_error_handlers(app: FastAPI) -> None:
    """Every error response body is {"error": <code>, ...}. Routes raise HTTPException(detail={"error": ...})."""

    @app.exception_handler(StarletteHTTPException)  # also catches fastapi.HTTPException (subclass)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        if isinstance(exc.detail, dict) and "error" in exc.detail:
            body = exc.detail
        else:
            body = {"error": _STATUS_CODES.get(exc.status_code, "http_error")}
        return JSONResponse(status_code=exc.status_code, content=body, headers=getattr(exc, "headers", None))

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        fields = [".".join(str(p) for p in e["loc"] if p != "body") for e in exc.errors()]
        return JSONResponse(status_code=422, content={"error": "invalid", "fields": fields})

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        log.error("unhandled_error", path=request.url.path, exc_info=exc)
        return JSONResponse(status_code=500, content={"error": "internal_error"})
