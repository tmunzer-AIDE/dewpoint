# SPDX-License-Identifier: Apache-2.0
from fastapi import FastAPI

from dewpoint.apps.api.errors import install_error_handlers
from dewpoint.apps.api.middleware import ClientHeaderMiddleware, SecurityHeadersMiddleware
from dewpoint.apps.api.routes import health
from dewpoint.core.config import Settings, get_settings
from dewpoint.core.db import make_engine, make_sessionmaker


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(title="Dewpoint API", docs_url=None, redoc_url=None, openapi_url="/api/v1/openapi.json")
    app.state.settings = settings
    app.state.engine = make_engine(settings.database_url)
    app.state.sessionmaker = make_sessionmaker(app.state.engine)
    app.add_middleware(ClientHeaderMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    install_error_handlers(app)
    app.include_router(health.router)
    return app
