# SPDX-License-Identifier: Apache-2.0
from fastapi import FastAPI

from dewpoint.apps.api.errors import install_error_handlers
from dewpoint.apps.api.middleware import SecurityHeadersMiddleware
from dewpoint.apps.api.routes import health
from dewpoint.core.config import Settings, get_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(title="Dewpoint API", docs_url=None, redoc_url=None, openapi_url="/api/v1/openapi.json")
    app.state.settings = settings
    app.add_middleware(SecurityHeadersMiddleware)
    install_error_handlers(app)
    app.include_router(health.router)
    return app
