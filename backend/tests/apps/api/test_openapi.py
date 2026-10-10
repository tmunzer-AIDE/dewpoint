# SPDX-License-Identifier: Apache-2.0
"""The API's OpenAPI schema, from which the web client is generated (sub-project 4, B1)."""

import json

import pytest
from typer.testing import CliRunner

from dewpoint.apps.api.main import create_app
from dewpoint.apps.api.openapi import schema
from dewpoint.apps.cli.main import app as cli


def test_the_dumped_schema_is_the_one_the_api_serves(api_settings) -> None:
    assert schema() == create_app(api_settings).openapi()


def test_the_cli_prints_it_without_a_server_or_settings() -> None:
    result = CliRunner().invoke(cli, ["api", "openapi"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == schema()


def test_every_component_has_its_own_name() -> None:
    """FastAPI falls back to a module path (`dewpoint__apps__…__CreateIn`) when two models share a name."""
    assert [n for n in schema()["components"]["schemas"] if "__" in n] == []


# What the web client calls in slice 4a: each answers a named model, so the generated client knows its shape.
SLICE_4A = [
    ("post", "/api/v1/auth/login"),
    ("get", "/api/v1/auth/session"),
    ("post", "/api/v1/auth/password"),
    ("post", "/api/v1/auth/mfa/totp"),
    ("post", "/api/v1/auth/mfa/recovery"),
    ("post", "/api/v1/auth/mfa/totp/enroll"),
    ("post", "/api/v1/auth/mfa/totp/reauth"),
    ("post", "/api/v1/auth/mfa/totp/confirm"),
    ("get", "/api/v1/auth/passkeys"),
    ("post", "/api/v1/auth/passkeys/register/options"),
    ("post", "/api/v1/auth/passkeys/register/verify"),
    ("post", "/api/v1/auth/passkeys/login/options"),
    ("post", "/api/v1/auth/passkeys/login/verify"),
    ("post", "/api/v1/auth/passkeys/mfa/options"),
    ("post", "/api/v1/auth/passkeys/mfa/verify"),
    ("post", "/api/v1/auth/passkeys/stepup/options"),
    ("post", "/api/v1/auth/passkeys/stepup/verify"),
    ("get", "/api/v1/tenants"),
    ("post", "/api/v1/tenants"),
    ("get", "/api/v1/t/{tenant_id}"),
    ("patch", "/api/v1/t/{tenant_id}"),
    ("get", "/api/v1/t/{tenant_id}/members"),
    ("post", "/api/v1/t/{tenant_id}/members"),
    ("patch", "/api/v1/t/{tenant_id}/members/{user_id}"),
    ("get", "/api/v1/connection-types"),
    ("get", "/api/v1/t/{tenant_id}/connections"),
    ("post", "/api/v1/t/{tenant_id}/connections"),
    ("get", "/api/v1/t/{tenant_id}/connections/{connection_id}"),
    ("patch", "/api/v1/t/{tenant_id}/connections/{connection_id}"),
    ("post", "/api/v1/t/{tenant_id}/connections/{connection_id}/verify"),
    ("get", "/api/v1/platform/status"),
]


@pytest.mark.parametrize("method,path", SLICE_4A)
def test_slice_4a_routes_name_their_answer(method: str, path: str) -> None:
    responses = schema()["paths"][path][method]["responses"]
    ok = next(code for code in responses if code.startswith("2"))
    body = responses[ok]["content"]["application/json"]["schema"]
    assert "$ref" in body or "$ref" in body.get("items", {}), body


# What the web client calls in slice 4b: each answers a named model.
SLICE_4B = [
    ("get", "/api/v1/node-types"),
    ("get", "/api/v1/t/{tenant_id}/workflows"),
    ("post", "/api/v1/t/{tenant_id}/workflows"),
    ("get", "/api/v1/t/{tenant_id}/workflows/{workflow_id}"),
    ("patch", "/api/v1/t/{tenant_id}/workflows/{workflow_id}"),
    ("put", "/api/v1/t/{tenant_id}/workflows/{workflow_id}/draft"),
    ("post", "/api/v1/t/{tenant_id}/workflows/{workflow_id}/validate"),
    ("post", "/api/v1/t/{tenant_id}/workflows/{workflow_id}/publish"),
    ("get", "/api/v1/t/{tenant_id}/workflows/{workflow_id}/versions"),
    ("get", "/api/v1/t/{tenant_id}/workflows/{workflow_id}/versions/{version_id}"),
    ("post", "/api/v1/t/{tenant_id}/workflows/{workflow_id}/activate"),
    ("get", "/api/v1/t/{tenant_id}/workflows/{workflow_id}/export"),
    ("post", "/api/v1/t/{tenant_id}/workflows/import"),
]


@pytest.mark.parametrize("method,path", SLICE_4B)
def test_slice_4b_routes_name_their_answer(method: str, path: str) -> None:
    responses = schema()["paths"][path][method]["responses"]
    ok = next(code for code in responses if code.startswith("2"))
    body = responses[ok]["content"]["application/json"]["schema"]
    assert "$ref" in body or "$ref" in body.get("items", {}), body


GRAPH = {"$ref": "#/components/schemas/Graph"}


def test_the_draft_put_documents_its_body_as_a_graph() -> None:
    """The route parses a plain object itself, for its `graph.format` diagnostics (ledger ruling 47, 4b ruling 8)."""
    body = schema()["paths"]["/api/v1/t/{tenant_id}/workflows/{workflow_id}/draft"]["put"]["requestBody"]
    assert body["content"]["application/json"]["schema"] == GRAPH


def test_a_workflow_answer_documents_its_draft_as_a_graph() -> None:
    assert schema()["components"]["schemas"]["WorkflowDetailOut"]["properties"]["draft"] == GRAPH


def test_a_versions_graph_is_documented_as_a_graph() -> None:
    assert schema()["components"]["schemas"]["VersionDetailOut"]["properties"]["graph"] == GRAPH


def test_a_files_graph_is_documented_as_a_graph() -> None:
    assert schema()["components"]["schemas"]["WorkflowDocument"]["properties"]["graph"] == GRAPH


def test_publishs_body_is_optional() -> None:
    """Verified against FastAPI 0.141.1: an optional body model is documented as itself or null, not required."""
    body = schema()["paths"]["/api/v1/t/{tenant_id}/workflows/{workflow_id}/publish"]["post"]["requestBody"]
    assert "required" not in body
    assert body["content"]["application/json"]["schema"]["anyOf"] == [
        {"$ref": "#/components/schemas/PublishIn"},
        {"type": "null"},
    ]


def test_the_graph_components_are_the_models_own() -> None:
    """No other component shares a name with one of the graph's models (a clash would mix two shapes)."""
    from dewpoint.engine.graph.model import Graph

    own = Graph.model_json_schema(mode="validation", ref_template="#/components/schemas/{model}")
    components = schema()["components"]["schemas"]
    for name, sub in own.pop("$defs").items():
        assert components[name] == sub, name
    assert components["Graph"] == own


def test_options_answer_a_named_model() -> None:
    """Plugin-call options (plugins-3 D3, D19), which the editor's slice 4f calls, answer `OptionsOut`."""
    paths = schema()["paths"]
    for path in (
        "/api/v1/t/{tenant_id}/node-types/{ref}/options",
        "/api/v1/t/{tenant_id}/workflows/{workflow_id}/input-options",
    ):
        answer = paths[path]["post"]["responses"]["200"]["content"]["application/json"]["schema"]
        assert answer == {"$ref": "#/components/schemas/OptionsOut"}


# What the web client calls in slice 4c-2: each answers a named model.
SLICE_4C = [
    ("get", "/api/v1/t/{tenant_id}/workflows/{workflow_id}/draft/scope"),
]


@pytest.mark.parametrize("method,path", SLICE_4C)
def test_slice_4c_routes_name_their_answer(method: str, path: str) -> None:
    responses = schema()["paths"][path][method]["responses"]
    ok = next(code for code in responses if code.startswith("2"))
    body = responses[ok]["content"]["application/json"]["schema"]
    assert "$ref" in body or "$ref" in body.get("items", {}), body
