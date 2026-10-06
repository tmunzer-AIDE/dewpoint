# SPDX-License-Identifier: Apache-2.0
"""Ingress's app (engine 2b spec §8.3). `POST /hooks/<endpoint_id>` checks, in this order: the requests in flight (503,
before the body is read); the address's failures (429, before any database call); the body against the global cap
(413) and its deadline (408); then the endpoint, the address against its allowlist and the authentication, every
failure the same bodiless 401. Failures before authentication count against the address. An authenticated attempt is
split, identified and sealed, and recorded or refused, all or nothing, by `record_inbound_events`, whose committed
outcome is the response. It refuses to start unless the recorded environment is `development`: a gated prototype until
2b-4 (the owner's rulings 8 and 13), and refuses to be made with a key-encryption key in its environment."""

import asyncio
import base64
import os
import time
import uuid
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from contextlib import asynccontextmanager

import structlog
from cryptography.exceptions import InvalidTag
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.datastructures import Headers
from starlette.requests import ClientDisconnect

from dewpoint.apps.ingress.addresses import Address, Network, client_address, limiter_key, parse_proxies
from dewpoint.apps.ingress.auth import authenticate
from dewpoint.apps.ingress.batch import prepare
from dewpoint.apps.ingress.config import IngressSettings
from dewpoint.apps.ingress.endpoints import Endpoint, resolve
from dewpoint.apps.ingress.limits import FailureLimiter, InFlight
from dewpoint.apps.ingress.recording import UNKNOWN, record, respond
from dewpoint.core import logs
from dewpoint.core.crypto.ingress import DEDUPE_KEY, IngressKey, UnknownIngressKeyError
from dewpoint.core.db import make_engine, make_sessionmaker, unavailable
from dewpoint.core.ingress.parsing import MalformedError
from dewpoint.core.platform.service import DEVELOPMENT

log = structlog.get_logger("dewpoint.ingress")


class IngressRefusedError(RuntimeError):
    """Ingress refuses to start; the message says why."""


class BodyTooLargeError(Exception):
    pass


KEK_VARIABLES = ("DEWPOINT_KEK_B64", "DEWPOINT_KEK_PREVIOUS_B64")


def refuse_key_encryption_key(environ: Mapping[str, str]) -> None:
    """Ingress never holds a tenant's data key (engine 2b spec §8.3): a key-encryption key in its environment refuses
    its start, whichever way it's started. The message names the variable, never its value."""
    present = [name for name in KEK_VARIABLES if environ.get(name)]
    if present:
        raise IngressRefusedError(
            f"refusing to start: {', '.join(present)} is set. Ingress never holds a tenant's data key: remove the "
            "key-encryption key from its environment."
        )


async def require_development(sessions: async_sessionmaker[AsyncSession]) -> None:
    async with sessions() as s:
        environment = (await s.execute(text("select ingress_environment()"))).scalar_one_or_none()
    if environment != DEVELOPMENT:
        raise IngressRefusedError(
            f"refusing to start: ingress serves only a development deployment until engine 2b-4 (recorded: "
            f"{environment or 'none'})"
        )


def declared_over(declared: str, cap: int) -> bool:
    """Whether a declared Content-Length says more than `cap`, compared by its digits before any conversion: one too
    long for `int()` is still past the cap (the owner's M2 review). Anything but ASCII digits isn't a length; the
    bytes are counted as they arrive."""
    if not (declared.isascii() and declared.isdigit()):
        return False
    digits = declared.lstrip("0")
    return len(digits) > len(str(cap)) or int(digits or "0") > cap


async def read_body(request: Request, cap: int, deadline_s: float) -> bytes:
    """The whole body, refused one byte past `cap` as it arrives (a chunked body declares no length), and within
    `deadline_s`; raises BodyTooLargeError or TimeoutError."""
    if declared_over(request.headers.get("content-length", ""), cap):
        raise BodyTooLargeError
    chunks, size = [], 0
    async with asyncio.timeout(deadline_s):
        async for chunk in request.stream():
            size += len(chunk)
            if size > cap:
                raise BodyTooLargeError
            chunks.append(chunk)
    return b"".join(chunks)


def _error(status: int, code: str, retry_after: int | None = None) -> Response:
    headers = {"retry-after": str(retry_after)} if retry_after is not None else None
    return JSONResponse({"error": code}, status_code=status, headers=headers)


def _allowed(address: Address | None, allowlist: Sequence[Network]) -> bool:
    return not allowlist or (address is not None and any(address in network for network in allowlist))


def create_app(settings: IngressSettings | None = None, *, clock: Callable[[], float] = time.time) -> FastAPI:
    refuse_key_encryption_key(os.environ)
    settings = settings or IngressSettings()  # read from the environment
    trusted = parse_proxies(settings.ingress_trusted_proxies)
    key = IngressKey(settings.ingress_key_id, base64.b64decode(settings.ingress_key_b64))

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        await require_development(app.state.sessionmaker)
        yield
        await app.state.engine.dispose()

    app = FastAPI(title="Dewpoint ingress", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.add_middleware(logs.LifespanFailures)  # a startup or shutdown failure, by its type: never its traceback
    app.state.engine = make_engine(settings.database_url)
    app.state.sessionmaker = make_sessionmaker(app.state.engine)
    limiter = FailureLimiter(settings.ingress_address_failures, window_s=60)
    in_flight = InFlight(settings.ingress_max_in_flight)

    @app.get("/health/live")
    async def live() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready")
    async def ready() -> Response:
        try:
            async with app.state.engine.connect() as conn:
                await conn.execute(text("select ingress_environment()"))
        except Exception:  # any failure means not ready; never leak details
            return JSONResponse({"status": "unavailable"}, status_code=503)
        return JSONResponse({"status": "ready"})

    async def _resolve(sessions: async_sessionmaker[AsyncSession], raw_id: str) -> Endpoint | None:
        try:
            endpoint_id = uuid.UUID(raw_id)
        except ValueError:
            return None
        async with sessions() as s:
            return await resolve(s, endpoint_id)

    async def _serve(raw_id: str, request: Request) -> Response:
        address = client_address(
            request.client.host if request.client else None, request.headers.getlist("x-forwarded-for"), trusted
        )
        who = limiter_key(address)
        wait = limiter.blocked(who, clock())
        if wait is not None:
            return _error(429, "rate_limited", retry_after=wait)
        try:
            body = await read_body(request, settings.ingress_body_cap, settings.ingress_body_deadline_s)
        except BodyTooLargeError:
            limiter.fail(who, clock())
            return _error(413, "too_large")
        except TimeoutError:
            limiter.fail(who, clock())
            return Response(status_code=408, headers={"connection": "close"})
        except ClientDisconnect:
            return Response(status_code=400)  # nobody reads it
        try:
            endpoint = await _resolve(request.app.state.sessionmaker, raw_id)
        except Exception as e:
            if not unavailable(e):
                raise
            log.warning("ingress_database_unavailable", error=type(e).__name__)
            return _error(503, "unavailable", retry_after=5)
        if (
            endpoint is None
            or not endpoint.enabled
            or not endpoint.tenant_active
            or not _allowed(address, endpoint.allowlist)
            or not authenticate(endpoint, request.headers, body, clock(), key)
        ):
            limiter.fail(who, clock())
            return Response(status_code=401)
        return await _attempt(request.app.state.sessionmaker, endpoint, request.headers, body, who)

    async def _attempt(
        sessions: async_sessionmaker[AsyncSession], endpoint: Endpoint, headers: Headers, body: bytes, who: str
    ) -> Response:
        """An authenticated attempt, recorded or refused by the recording function, which also charges a refusal."""
        if endpoint.public_key is None or endpoint.key_version is None:  # fail closed (the owner's ruling 8)
            log.warning("ingress_no_inbound_key", tenant_id=str(endpoint.tenant_id))
            return _error(503, "unavailable")
        refusal, batch = None, None
        if len(body) > endpoint.body_limit:
            refusal = "too_large"
        else:
            try:
                secret = (
                    key.open(DEDUPE_KEY, str(endpoint.id), endpoint.dedupe_key)
                    if endpoint.id_source != "none"
                    else None
                )
            except (UnknownIngressKeyError, InvalidTag, ValueError) as e:
                log.warning("ingress_secret_unopenable", endpoint_id=str(endpoint.id), error=type(e).__name__)
                return _error(503, "unavailable")
            try:
                batch = prepare(endpoint, body, headers.get(endpoint.id_header) if endpoint.id_header else None, secret)
            except MalformedError:
                refusal = "malformed"
        try:
            outcome = await record(sessions, endpoint.id, read=len(body), batch=batch, refusal=refusal)
        except Exception as e:
            if not unavailable(e):
                raise
            log.warning("ingress_database_unavailable", error=type(e).__name__)
            return _error(503, "unavailable", retry_after=5)
        if outcome["outcome"] == UNKNOWN:  # it stopped serving since it was resolved
            limiter.fail(who, clock())
            return Response(status_code=401)
        return respond(outcome)

    @app.post("/hooks/{endpoint_id}")
    async def hook(endpoint_id: str, request: Request) -> Response:
        if not in_flight.try_acquire():
            return _error(503, "busy", retry_after=1)
        try:
            return await _serve(endpoint_id, request)
        finally:
            in_flight.release()

    return app
