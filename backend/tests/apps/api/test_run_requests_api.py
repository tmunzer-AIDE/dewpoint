# SPDX-License-Identifier: Apache-2.0
"""Starting a run through the API (engine 2b spec §7.7): `POST /t/{tid}/workflows/{wid}/runs` admits a request in the
API's own transaction (`run.start`, an `Idempotency-Key`), answers 202 with it, and leaves the start to the dispatcher;
the API has no Temporal client. An exact retry returns the same request; another body under the key is a 409. A
refusal says why, with a code and fixed messages that never quote a value. `GET .../start-form` describes the active
version's input, masking what's sensitive."""

import uuid
from typing import Any

import pytest
from sqlalchemy import text

from tests.apps.api.helpers import member_client
from tests.apps.test_admission import KEYS, TOKEN, count, current, published
from tests.apps.test_workflow_ops import update
from tests.support.graphs import G

pytestmark = pytest.mark.usefixtures("development_deployment")
BODY = {"input": {"token": TOKEN, "site": "a"}, "mode": "live"}


@pytest.fixture
def keyed_app(app: Any) -> Any:
    """The API with fixture keys: its tenants here have no keyring keys, and the dispatcher's tests read with these."""
    app.state.keys = KEYS
    return app


@pytest.fixture
async def ready(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings) -> Any:
    ctx, wf = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings)
    await current(dispatch_sessionmaker)
    return ctx, wf


async def as_role(app: Any, owner: Any, settings: Any, ctx: Any, role: str = "operator") -> Any:
    client, _ = await member_client(app, owner, settings, ctx.tenant_id, role)
    return client


def runs_url(ctx: Any, wf: uuid.UUID) -> str:
    return f"/api/v1/t/{ctx.tenant_id}/workflows/{wf}/runs"


async def test_an_operator_starts_a_run_and_gets_its_queued_request(
    keyed_app, ready, owner_sessionmaker, api_settings
) -> None:
    ctx, wf = ready
    client = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx)
    answer = await client.post(runs_url(ctx, wf), json=BODY, headers={"Idempotency-Key": "k1"})
    assert answer.status_code == 202, answer.text
    body = answer.json()
    assert {k: body[k] for k in ("status", "workflow_id", "mode", "source")} == {
        "status": "queued", "workflow_id": str(wf), "mode": "live", "source": "manual",
    }  # fmt: skip
    assert body["version_id"] and body["queued_at"] and body["reason"] is None
    assert TOKEN not in answer.text
    async with owner_sessionmaker() as s:
        status = (await s.execute(text("select status from run_requests where id = :i"), {"i": body["id"]})).scalar()
    assert status == "queued"


async def test_an_exact_retry_returns_the_same_request_and_another_body_is_a_conflict(
    keyed_app, ready, owner_sessionmaker, api_settings
) -> None:
    ctx, wf = ready
    client = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx)
    first = await client.post(runs_url(ctx, wf), json=BODY, headers={"Idempotency-Key": "k1"})
    again = await client.post(runs_url(ctx, wf), json=BODY, headers={"Idempotency-Key": "k1"})
    assert (again.status_code, again.json()["id"]) == (202, first.json()["id"])
    other = {**BODY, "input": {"token": TOKEN, "site": "b"}}
    conflict = await client.post(runs_url(ctx, wf), json=other, headers={"Idempotency-Key": "k1"})
    assert (conflict.status_code, conflict.json()["error"]) == (409, "idempotency_conflict")
    assert await count(owner_sessionmaker, "run_requests") == 1


async def test_a_start_without_an_idempotency_key_is_refused(
    keyed_app, ready, owner_sessionmaker, api_settings
) -> None:
    ctx, wf = ready
    client = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx)
    answer = await client.post(runs_url(ctx, wf), json=BODY)
    assert (answer.status_code, answer.json()) == (428, {"error": "idempotency_key_required"})


async def test_an_input_that_doesnt_match_its_schema_is_422_with_its_places_never_its_values(
    keyed_app, ready, owner_sessionmaker, api_settings
) -> None:
    ctx, wf = ready
    client = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx)
    answer = await client.post(
        runs_url(ctx, wf), json={"input": {"site": "x" * 5, "extra": TOKEN}, "mode": "live"},
        headers={"Idempotency-Key": "k1"},
    )  # fmt: skip
    assert answer.status_code == 422 and answer.json()["error"] == "input_invalid"
    assert answer.json()["messages"] and TOKEN not in answer.text
    assert await count(owner_sessionmaker, "run_requests") == 0  # an interactive refusal records nothing


async def test_a_body_with_unknown_fields_is_refused(keyed_app, ready, owner_sessionmaker, api_settings) -> None:
    """CSV starts are 2b-3's: a `csv` field isn't accepted yet."""
    ctx, wf = ready
    client = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx)
    answer = await client.post(runs_url(ctx, wf), json={**BODY, "csv": "u1"}, headers={"Idempotency-Key": "k1"})
    assert (answer.status_code, answer.json()["error"]) == (422, "invalid")


async def test_production_runs_off_answers_503(keyed_app, ready, owner_sessionmaker, api_settings) -> None:
    ctx, wf = ready
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(text("alter table platform_settings disable trigger user"))
        await s.execute(text("update platform_settings set environment = 'production', production_runs = false"))
        await s.execute(text("alter table platform_settings enable trigger user"))
    client = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx)
    answer = await client.post(runs_url(ctx, wf), json=BODY, headers={"Idempotency-Key": "k1"})
    assert (answer.status_code, answer.json()["error"]) == (503, "production_runs_disabled")


async def test_a_disabled_workflow_answers_409_with_its_reason(
    keyed_app, ready, owner_sessionmaker, api_sessionmaker, api_settings
) -> None:
    ctx, wf = ready
    await update(api_sessionmaker, ctx, wf, enabled=False)
    client = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx)
    answer = await client.post(runs_url(ctx, wf), json=BODY, headers={"Idempotency-Key": "k1"})
    assert (answer.status_code, answer.json()["error"]) == (409, "workflow_disabled")


async def test_a_viewer_cant_start_a_run(keyed_app, ready, owner_sessionmaker, api_settings) -> None:
    ctx, wf = ready
    client = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "viewer")
    answer = await client.post(runs_url(ctx, wf), json=BODY, headers={"Idempotency-Key": "k1"})
    assert answer.status_code == 403


async def test_another_tenants_workflow_isnt_found(
    keyed_app, ready, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings
) -> None:
    ctx, wf = ready
    other, _ = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings)
    client = await as_role(keyed_app, owner_sessionmaker, api_settings, other)
    answer = await client.post(runs_url(other, wf), json=BODY, headers={"Idempotency-Key": "k1"})
    assert (answer.status_code, answer.json()["error"]) == (404, "not_found")


FORM_SCHEMA = {
    "type": "object",
    "properties": {
        "token": {"type": "string", "x-sensitive": True, "title": "API token"},
        "site": {"type": "string", "enum": ["a", "b"], "default": "a", "x-dewpoint-picker": {"kind": "site"}},
        "count": {"type": "integer", "description": "How many"},
    },
    "required": ["token", "site"],
    "additionalProperties": False,
}


async def test_the_start_form_describes_the_active_versions_input(
    keyed_app, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings
) -> None:
    graph = G().node("a", "testkit.echo@1", {"value": 1}).data() | {"settings": {"input_schema": FORM_SCHEMA}}
    ctx, wf = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings, graph)
    client = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx)
    answer = await client.get(f"/api/v1/t/{ctx.tenant_id}/workflows/{wf}/start-form")
    assert answer.status_code == 200, answer.text
    form = answer.json()
    assert form["workflow_id"] == str(wf) and form["version_id"] and form["csv"] is None
    assert {f["name"]: f for f in form["fields"]} == {
        "token": {"name": "token", "type": "string", "required": True, "sensitive": True, "title": "API token"},
        "site": {"name": "site", "type": "string", "required": True, "sensitive": False, "enum": ["a", "b"],
                 "default": "a", "picker": {"kind": "site"}},
        "count": {"name": "count", "type": "integer", "required": False, "sensitive": False,
                  "description": "How many"},
    }  # fmt: skip


async def test_a_workflow_without_an_active_version_has_no_start_form(
    keyed_app, owner_sessionmaker, api_sessionmaker, api_settings
) -> None:
    from tests.apps.test_workflow_ops import actor, create

    ctx = await actor(owner_sessionmaker)
    wf = await create(api_sessionmaker, ctx, G().node("a", "testkit.echo@1", {"value": 1}).data())
    client = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx)
    answer = await client.get(f"/api/v1/t/{ctx.tenant_id}/workflows/{wf}/start-form")
    assert (answer.status_code, answer.json()["error"]) == (409, "not_active")
