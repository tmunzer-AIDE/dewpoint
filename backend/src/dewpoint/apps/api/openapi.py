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
from dewpoint.engine.graph.model import Graph

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


GRAPH_REF = "#/components/schemas/Graph"
# Bodies a route parses itself, so it can answer `graph.format` diagnostics and its admission checks (non-finite
# numbers, depth, value count) that a body model would turn into `{"error": "invalid", "fields": [...]}`.
GRAPH_BODIES: tuple[tuple[str, str], ...] = (("/api/v1/t/{tenant_id}/workflows/{workflow_id}/draft", "put"),)
# Answers that carry a graph verbatim, as saved, rather than re-serialized with defaults its author never wrote.
GRAPH_PROPERTIES: tuple[tuple[str, str], ...] = (("WorkflowDetailOut", "draft"), ("VersionDetailOut", "graph"))


def refine(spec: dict[str, Any]) -> dict[str, Any]:
    """Document as `Graph` what travels as a plain object (ledger ruling 47; 4b ruling 8). FastAPI ignores
    `WithJsonSchema` on a body and merges `openapi_extra` into the object schema it generates, so the schema is
    refined here, once, for the API and `dewpoint api openapi` alike."""
    schemas = spec.setdefault("components", {}).setdefault("schemas", {})
    graph = Graph.model_json_schema(mode="validation", ref_template="#/components/schemas/{model}")
    for name, sub in graph.pop("$defs", {}).items():
        schemas.setdefault(name, sub)
    schemas.setdefault("Graph", graph)
    for path, method in GRAPH_BODIES:
        spec["paths"][path][method]["requestBody"]["content"]["application/json"]["schema"] = {"$ref": GRAPH_REF}
    for model, prop in GRAPH_PROPERTIES:
        schemas[model]["properties"][prop] = {"$ref": GRAPH_REF}
    return spec


def serve_refined(app: FastAPI) -> None:
    """Make `app` serve the refined schema at OPENAPI_URL."""
    generate = app.openapi

    def openapi() -> dict[str, Any]:
        if app.openapi_schema is None:
            app.openapi_schema = refine(generate())
        return app.openapi_schema

    app.openapi = openapi  # type: ignore[method-assign]


def schema() -> dict[str, Any]:
    """The schema the API serves at OPENAPI_URL: the same title and routes, in the same order, refined alike."""
    app = FastAPI(title=TITLE, docs_url=None, redoc_url=None, openapi_url=OPENAPI_URL)
    for router in ROUTERS:
        app.include_router(router)
    serve_refined(app)
    return app.openapi()
