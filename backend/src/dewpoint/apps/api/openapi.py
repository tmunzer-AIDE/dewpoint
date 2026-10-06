# SPDX-License-Identifier: Apache-2.0
"""The API's routes and its OpenAPI schema, built without settings, a database or a server, so `dewpoint api openapi`
can print exactly what the API serves (sub-project 4, B1: the web client is generated from it)."""

from typing import Any

from fastapi import APIRouter, FastAPI

from dewpoint.apps.api.routes import (
    admin_users,
    audit,
    auth,
    connections,
    csv_uploads,
    health,
    members,
    mfa,
    node_types,
    passkeys,
    platform,
    run_requests,
    runs,
    schedules,
    tenants,
    webhooks,
    workflows,
)

TITLE = "Dewpoint API"
OPENAPI_URL = "/api/v1/openapi.json"

ROUTERS: tuple[APIRouter, ...] = (
    health.router,
    auth.router,
    mfa.router,
    passkeys.router,
    tenants.router,
    members.router,
    admin_users.router,
    audit.router,
    connections.router,
    node_types.router,
    platform.router,
    workflows.router,
    run_requests.router,
    csv_uploads.router,
    runs.router,
    schedules.router,
    webhooks.router,
)


def schema() -> dict[str, Any]:
    """The schema the API serves at OPENAPI_URL: the same title and routes, in the same order."""
    app = FastAPI(title=TITLE, docs_url=None, redoc_url=None, openapi_url=OPENAPI_URL)
    for router in ROUTERS:
        app.include_router(router)
    return app.openapi()
