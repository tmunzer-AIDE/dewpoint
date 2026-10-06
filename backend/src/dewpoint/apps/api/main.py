# SPDX-License-Identifier: Apache-2.0
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from dewpoint.apps.api.errors import install_error_handlers
from dewpoint.apps.api.middleware import BodyLimitMiddleware, ClientHeaderMiddleware, SecurityHeadersMiddleware
from dewpoint.apps.api.openapi import OPENAPI_URL, ROUTERS, TITLE
from dewpoint.apps.api.routes import csv_uploads
from dewpoint.core import logs
from dewpoint.core.config import Settings, get_settings
from dewpoint.core.crypto.ingress import IngressKey
from dewpoint.core.crypto.kek import KekSet
from dewpoint.core.crypto.keyring import Keyring
from dewpoint.core.crypto.keys import KeyringKeys
from dewpoint.core.db import make_engine, make_sessionmaker
from dewpoint.engine.graph.csv import MAX_BYTES as CSV_MAX_BYTES


def create_app(settings: Settings | None = None) -> FastAPI:
    logs.configure()  # uvicorn's factory: the API's process starts here
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        yield
        await app.state.http.aclose()
        await app.state.engine.dispose()

    app = FastAPI(title=TITLE, docs_url=None, redoc_url=None, openapi_url=OPENAPI_URL, lifespan=lifespan)
    app.state.settings = settings
    app.state.engine = make_engine(settings.database_url)
    app.state.sessionmaker = make_sessionmaker(app.state.engine)
    app.state.keyring = Keyring(KekSet.from_settings(settings))
    app.state.keys = KeyringKeys(app.state.sessionmaker, app.state.keyring)  # admission's: claims, envelopes, digests
    # Webhook endpoints' secrets (engine 2b spec §8.3): without the ingress key, nothing that seals one is written.
    app.state.ingress_key = IngressKey.from_settings(settings) if settings.ingress_key_b64 else None
    # Created eagerly (not in the lifespan) so ASGI test transports, which skip lifespan, get it too.
    app.state.http = httpx.AsyncClient(timeout=10, follow_redirects=False)
    app.add_middleware(
        BodyLimitMiddleware,
        max_bytes=settings.max_request_body_bytes,
        streamed=csv_uploads.STREAMED,  # a CSV upload reads its own body, to its declaration's cap
        streamed_max=CSV_MAX_BYTES,
    )  # innermost: its 413 gets security headers
    app.add_middleware(ClientHeaderMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(logs.LifespanFailures)  # a startup or shutdown failure, by its type: never its traceback
    install_error_handlers(app)
    for router in ROUTERS:
        app.include_router(router)
    return app
