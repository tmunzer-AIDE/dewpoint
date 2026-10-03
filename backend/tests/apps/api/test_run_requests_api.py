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

from dewpoint.core.claims import service as claims
from dewpoint.core.claims.cipher import ClaimCipher
from dewpoint.core.db import tenant_scope
from dewpoint.core.runs import service as runs
from dewpoint.engine.handles import StoredClaim, resolve_value
from tests.apps.api.helpers import member_client
from tests.apps.test_admission import KEYS, TOKEN, admit, count, current, published
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


# --- cancel and re-run (§7.7) -----------------------------------------------------------------------------------------


async def started_request(client: Any, ctx: Any, wf: uuid.UUID, key: str = "k1") -> dict[str, Any]:
    answer = await client.post(runs_url(ctx, wf), json=BODY, headers={"Idempotency-Key": key})
    assert answer.status_code == 202, answer.text
    return answer.json()  # type: ignore[no-any-return]


async def envelope_of(api: Any, ctx: Any, request_id: str) -> Any:
    async with api() as s, s.begin():
        await tenant_scope(s, ctx.tenant_id)
        return await claims.read_envelope(s, ClaimCipher(KEYS), ctx.tenant_id, request_id=uuid.UUID(request_id))


async def test_an_operator_cancels_a_queued_request_at_once(keyed_app, ready, owner_sessionmaker, api_settings) -> None:
    ctx, wf = ready
    client = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx)
    request = await started_request(client, ctx, wf)
    answer = await client.post(f"/api/v1/t/{ctx.tenant_id}/runs/{request['id']}/cancel")
    assert answer.status_code == 200, answer.text
    assert answer.json()["cancel"] == "cancelled"
    assert (answer.json()["request"]["status"], answer.json()["request"]["reason"]) == ("cancelled", "user_cancelled")
    again = await client.post(f"/api/v1/t/{ctx.tenant_id}/runs/{request['id']}/cancel")
    assert (again.status_code, again.json()["error"]) == (409, "run_ended")


async def test_a_starting_requests_cancel_is_recorded_for_the_dispatcher(
    keyed_app, ready, owner_sessionmaker, dispatch_sessionmaker, api_settings
) -> None:
    from tests.apps.dispatcher.support import begin, workers

    ctx, wf = ready
    client = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx)
    request = await started_request(client, ctx, wf)
    await workers(owner_sessionmaker)
    async with owner_sessionmaker() as s:
        row = (await s.execute(text("select * from run_requests where id = :i"), {"i": request["id"]})).one()
    assert (await begin(dispatch_sessionmaker, row, api_settings)).__class__.__name__ == "Starting"
    answer = await client.post(f"/api/v1/t/{ctx.tenant_id}/runs/{request['id']}/cancel")
    assert (answer.status_code, answer.json()["cancel"], answer.json()["request"]["status"]) == (
        202, "requested", "starting",
    )  # fmt: skip


async def test_a_viewer_cant_cancel_and_an_unknown_request_isnt_found(
    keyed_app, ready, owner_sessionmaker, api_settings
) -> None:
    ctx, wf = ready
    operator = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx)
    request = await started_request(operator, ctx, wf)
    viewer = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "viewer")
    assert (await viewer.post(f"/api/v1/t/{ctx.tenant_id}/runs/{request['id']}/cancel")).status_code == 403
    unknown = await operator.post(f"/api/v1/t/{ctx.tenant_id}/runs/{uuid.uuid4()}/cancel")
    assert (unknown.status_code, unknown.json()["error"]) == (404, "not_found")


async def test_a_rerun_admits_the_complete_original_input_as_a_new_request_with_new_claims(
    keyed_app, ready, owner_sessionmaker, api_sessionmaker, api_settings
) -> None:
    ctx, wf = ready
    client = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx)
    old = await started_request(client, ctx, wf)
    answer = await client.post(f"/api/v1/t/{ctx.tenant_id}/runs/{old['id']}/rerun", headers={"Idempotency-Key": "r1"})
    assert answer.status_code == 202, answer.text
    new = answer.json()
    assert new["id"] != old["id"] and (new["source"], new["status"], new["mode"]) == ("rerun", "queued", "live")
    assert TOKEN not in answer.text
    before, after = (
        await envelope_of(api_sessionmaker, ctx, old["id"]),
        await envelope_of(api_sessionmaker, ctx, new["id"]),
    )
    assert after["site"] == "a" and after["token"] != before["token"]  # claimed again: no old handle is reused
    async with api_sessionmaker() as s, s.begin():
        await tenant_scope(s, ctx.tenant_id)
        token = await resolve_value(after["token"], fetcher(s, ctx, uuid.UUID(new["id"])))
    assert token.value == TOKEN


def fetcher(s: Any, ctx: Any, run_id: uuid.UUID) -> Any:
    async def fetch(claim_id: str) -> StoredClaim:
        stored = await claims.fetch(s, ClaimCipher(KEYS), ctx.tenant_id, run_id=run_id, claim_id=uuid.UUID(claim_id))
        return StoredClaim(stored.value, stored.sensitive_pointers)

    return fetch


@pytest.mark.parametrize("gone", ["pre_2b2_run", "refused", "claim_removed"])
async def test_a_rerun_whose_input_isnt_retained_is_410(
    keyed_app, ready, owner_sessionmaker, api_sessionmaker, dispatch_sessionmaker, api_settings, gone
) -> None:
    ctx, wf = ready
    client = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx)
    if gone == "pre_2b2_run":  # a run 2a's start_run wrote: no request, no envelope
        async with owner_sessionmaker() as s:
            version = (
                await s.execute(text("select active_version_id from workflows where id = :w"), {"w": wf})
            ).scalar()
        async with dispatch_sessionmaker() as s, s.begin():
            await tenant_scope(s, ctx.tenant_id)
            run = await runs.insert_run(s, run_id=uuid.uuid4(), tenant_id=ctx.tenant_id, workflow_id=wf,
                                        version_id=version, mode="live")  # fmt: skip
        target = str(run.id)
    elif gone == "refused":  # a durable source's refusal keeps a request with no envelope
        await update(api_sessionmaker, ctx, wf, enabled=False)
        target = str((await admit(api_sessionmaker, ctx, wf, source="schedule")).request.id)
        await update(api_sessionmaker, ctx, wf, enabled=True)
    else:  # retention removed one of its claims
        target = (await started_request(client, ctx, wf))["id"]
        async with owner_sessionmaker() as s, s.begin():
            await s.execute(text("delete from run_inputs where owner_run_id = :i and role = 'claim'"), {"i": target})
    answer = await client.post(f"/api/v1/t/{ctx.tenant_id}/runs/{target}/rerun", headers={"Idempotency-Key": "r1"})
    assert (answer.status_code, answer.json()["error"]) == (410, "input_not_retained")


async def test_a_rerun_needs_an_idempotency_key_and_an_existing_request(
    keyed_app, ready, owner_sessionmaker, api_settings
) -> None:
    ctx, wf = ready
    client = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx)
    old = await started_request(client, ctx, wf)
    assert (await client.post(f"/api/v1/t/{ctx.tenant_id}/runs/{old['id']}/rerun")).status_code == 428
    unknown = await client.post(
        f"/api/v1/t/{ctx.tenant_id}/runs/{uuid.uuid4()}/rerun", headers={"Idempotency-Key": "r"}
    )
    assert (unknown.status_code, unknown.json()["error"]) == (404, "not_found")


async def test_a_tenant_whose_key_cant_be_read_answers_503(keyed_app, ready, owner_sessionmaker, api_settings) -> None:
    from tests.support.keys import FixtureKeys

    ctx, wf = ready
    keyed_app.state.keys = FixtureKeys(missing={str(ctx.tenant_id)})
    client = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx)
    answer = await client.post(runs_url(ctx, wf), json=BODY, headers={"Idempotency-Key": "k1"})
    assert (answer.status_code, answer.json()) == (503, {"error": "key_unusable"})
