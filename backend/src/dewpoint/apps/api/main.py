# SPDX-License-Identifier: Apache-2.0
from fastapi import FastAPI

from dewpoint.apps.api.errors import install_error_handlers
from dewpoint.apps.api.middleware import ClientHeaderMiddleware, SecurityHeadersMiddleware
from dewpoint.apps.api.routes import admin_users, audit, auth, health, members, mfa, passkeys, tenants
from dewpoint.core.config import Settings, get_settings
from dewpoint.core.crypto.kek import KekSet
from dewpoint.core.crypto.keyring import Keyring
from dewpoint.core.db import make_engine, make_sessionmaker


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(title="Dewpoint API", docs_url=None, redoc_url=None, openapi_url="/api/v1/openapi.json")
    app.state.settings = settings
    app.state.engine = make_engine(settings.database_url)
    app.state.sessionmaker = make_sessionmaker(app.state.engine)
    app.state.keyring = Keyring(KekSet.from_settings(settings))
    app.add_middleware(ClientHeaderMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    install_error_handlers(app)
    for router in (
        health.router,
        auth.router,
        mfa.router,
        passkeys.router,
        tenants.router,
        members.router,
        admin_users.router,
        audit.router,
    ):
        app.include_router(router)
    return app
