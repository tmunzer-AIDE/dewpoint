# SPDX-License-Identifier: Apache-2.0
"""Webhook endpoints, bindings and events through the API (engine 2b spec §8.3; the owner's ruling 10 on the 2b-3b
outline): `trigger.manage` writes endpoints and bindings and `workflow.view` reads them; an endpoint's secret (a bearer
token, or an HMAC secret sealed under the ingress key with the endpoint's id as context) is shown once, when it's made
or rotated, and never again; filters and the binding cap are checked when written. Events' metadata is read with
`workflow.view`, never a payload; dead events are listed, and pending or dead ones cancelled, with `tenant.manage`
(admins), audited, their pending counters released."""

import hashlib
import hmac
import json
import time
import uuid
from typing import Any

import pytest
from sqlalchemy import event, text
from sqlalchemy.engine import Engine

from dewpoint.apps.ingress.main import create_app
from dewpoint.core.crypto import events
from dewpoint.core.crypto.ingress import DEDUPE_KEY, HMAC_SECRET
from dewpoint.core.ingress.identity import canonical
from tests.apps.api.test_run_requests_api import as_role
from tests.apps.dispatcher.inbound import keypair
from tests.apps.ingress.support import KEY
from tests.apps.ingress.support import client as ingress_client
from tests.apps.ingress.support import settings as ingress_settings
from tests.apps.test_admission import KEYS, OPEN_GRAPH, published
from tests.core.ingress.support import record

pytestmark = pytest.mark.usefixtures("development_deployment")
MIB = 1024 * 1024
CANARY = "canary-payload-7f3a"


@pytest.fixture
def keyed_app(app: Any) -> Any:
    app.state.keys = KEYS
    app.state.ingress_key = KEY
    return app


@pytest.fixture
async def tenant(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings) -> Any:
    ctx, wf = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings, OPEN_GRAPH)
    await keypair(owner_sessionmaker, ctx.tenant_id)
    return ctx, wf


def url(ctx: Any, path: str = "") -> str:
    return f"/api/v1/t/{ctx.tenant_id}{path}"


async def row(owner: Any, table: str, row_id: Any) -> dict[str, Any]:
    async with owner() as s:
        found = await s.execute(text(f"select * from {table} where id = :i"), {"i": row_id})  # noqa: S608
        return dict(found.mappings().one())


async def audited(owner: Any, action: str) -> list[dict[str, Any]]:
    async with owner() as s:
        found = await s.execute(text("select target_id, details from audit_log where action = :a order by seq"),
                                {"a": action})  # fmt: skip
        return [dict(r) for r in found.mappings()]


async def made(keyed_app: Any, owner: Any, settings: Any, ctx: Any, **body: Any) -> dict[str, Any]:
    editor = await as_role(keyed_app, owner, settings, ctx, "editor")
    answer = await editor.post(url(ctx, "/webhook-endpoints"), json={"name": "alarms"} | body)
    assert answer.status_code == 201, answer.text
    return dict(answer.json())


async def test_an_editor_makes_a_bearer_endpoint_whose_token_is_shown_once(
    keyed_app, tenant, owner_sessionmaker, api_settings
) -> None:
    ctx, _ = tenant
    body = await made(keyed_app, owner_sessionmaker, api_settings, ctx)
    token = body.pop("secret")
    assert token.startswith("dwp_") and len(token) > 40
    assert {k: body[k] for k in ("name", "enabled", "auth", "id_source", "body_limit", "path")} == {
        "name": "alarms", "enabled": True, "auth": "bearer", "id_source": "none", "body_limit": MIB,
        "path": f"/hooks/{body['id']}",
    }  # fmt: skip
    stored = await row(owner_sessionmaker, "webhook_endpoints", body["id"])
    assert stored["bearer_digest"] == hashlib.sha256(token.encode()).digest() and stored["hmac_secret"] is None
    assert KEY.open(DEDUPE_KEY, body["id"], stored["dedupe_key"])  # sealed under the ingress key, its id the context
    viewer = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "viewer")
    listed = (await viewer.get(url(ctx, "/webhook-endpoints"))).json()["endpoints"]
    shown = (await viewer.get(url(ctx, f"/webhook-endpoints/{body['id']}"))).json()
    assert [e["id"] for e in listed] == [body["id"]] and shown["id"] == body["id"]
    for seen in (listed, shown):
        assert token not in json.dumps(seen) and "secret" not in json.dumps(seen) and "digest" not in json.dumps(seen)
    [entry] = await audited(owner_sessionmaker, "webhook_endpoint.create")
    assert entry["target_id"] == body["id"] and token not in json.dumps(entry["details"])


async def test_an_hmac_endpoints_secret_is_the_one_ingress_authenticates_with(
    keyed_app, tenant, owner_sessionmaker, api_settings, pg_url
) -> None:
    ctx, _ = tenant
    body = await made(keyed_app, owner_sessionmaker, api_settings, ctx, auth="hmac", id_source="pointer",
                      id_pointer="/id")  # fmt: skip
    secret = body["secret"]
    assert (body["signature_header"], body["timestamp_header"]) == ("x-dewpoint-signature", "x-dewpoint-timestamp")
    stored = await row(owner_sessionmaker, "webhook_endpoints", body["id"])
    assert KEY.open(HMAC_SECRET, body["id"], stored["hmac_secret"]) == secret.encode()
    ingress = create_app(ingress_settings(pg_url))
    event = json.dumps({"id": "e-1", "note": CANARY}).encode()
    stamp = str(int(time.time()))
    signed = hmac.new(secret.encode(), stamp.encode() + b"." + event, hashlib.sha256).hexdigest()
    async with ingress_client(ingress) as c:
        answer = await c.post(body["path"], content=event,
                              headers={"x-dewpoint-timestamp": stamp, "x-dewpoint-signature": signed})  # fmt: skip
    await ingress.state.engine.dispose()
    assert (answer.status_code, answer.json()) == (200, {"accepted": 1, "duplicates": 0})


@pytest.mark.parametrize(
    ("given", "problem"),
    [
        ({"id_source": "pointer"}, "id_pointer"),
        ({"id_source": "header"}, "id_header"),
        ({"id_source": "pointer", "id_pointer": "id"}, "id_pointer"),
        ({"events_pointer": "events"}, "events_pointer"),
        ({"allowlist": ["10.0.0.1/8"]}, "allowlist"),
        ({"allowlist": ["not-an-address"]}, "allowlist"),
        ({"auth": "hmac", "signature_header": "authorization"}, "signature_header"),
        ({"auth": "hmac", "timestamp_header": "bad header"}, "timestamp_header"),
        ({"id_source": "header", "id_header": "x-forwarded-for"}, "id_header"),
        ({"auth": "bearer", "signature_header": "x-sig"}, "signature_header"),
    ],
)
async def test_an_endpoint_that_isnt_one_is_refused_with_what_to_change(
    keyed_app, tenant, owner_sessionmaker, api_settings, given, problem
) -> None:
    ctx, _ = tenant
    editor = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "editor")
    answer = await editor.post(url(ctx, "/webhook-endpoints"), json={"name": "x"} | given)
    assert answer.status_code == 422, answer.text
    assert answer.json()["error"] == "endpoint_invalid"
    assert problem in answer.json()["fields"]


async def test_a_large_body_limit_gets_the_burst_that_covers_it(keyed_app, tenant, owner_sessionmaker,
                                                                api_settings) -> None:  # fmt: skip
    ctx, _ = tenant
    body = await made(keyed_app, owner_sessionmaker, api_settings, ctx, body_limit=5 * MIB)
    stored = await row(owner_sessionmaker, "webhook_endpoints", body["id"])
    assert stored["byte_burst"] >= 5 * 5 * MIB + 64_000 and stored["byte_tokens"] >= 0
    editor = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "editor")
    assert (await editor.post(url(ctx, "/webhook-endpoints"), json={"name": "x", "body_limit": 5 * MIB + 1})
            ).status_code == 422  # fmt: skip


async def test_writing_an_endpoint_needs_trigger_manage_and_the_ingress_key(
    keyed_app, tenant, owner_sessionmaker, api_settings
) -> None:
    ctx, _ = tenant
    for role in ("viewer", "operator"):
        client = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, role)
        assert (await client.post(url(ctx, "/webhook-endpoints"), json={"name": "x"})).status_code == 403
    keyed_app.state.ingress_key = None
    editor = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "editor")
    answer = await editor.post(url(ctx, "/webhook-endpoints"), json={"name": "x"})
    assert (answer.status_code, answer.json()) == (503, {"error": "ingress_key_missing"})


async def test_rotating_a_secret_shows_the_new_one_once_and_keeps_deduplication(
    keyed_app, tenant, owner_sessionmaker, api_settings
) -> None:
    ctx, _ = tenant
    body = await made(keyed_app, owner_sessionmaker, api_settings, ctx)
    before = await row(owner_sessionmaker, "webhook_endpoints", body["id"])
    editor = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "editor")
    rotated = await editor.post(url(ctx, f"/webhook-endpoints/{body['id']}/secret"))
    assert rotated.status_code == 200, rotated.text
    new = rotated.json()["secret"]
    after = await row(owner_sessionmaker, "webhook_endpoints", body["id"])
    assert new != body["secret"] and after["bearer_digest"] == hashlib.sha256(new.encode()).digest()
    assert after["dedupe_key"] == before["dedupe_key"]
    assert [e["target_id"] for e in await audited(owner_sessionmaker, "webhook_endpoint.rotate_secret")] == [body["id"]]


async def test_an_endpoint_is_updated_and_disabled_but_never_its_identity(
    keyed_app, tenant, owner_sessionmaker, api_settings
) -> None:
    ctx, _ = tenant
    body = await made(keyed_app, owner_sessionmaker, api_settings, ctx)
    editor = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "editor")
    patched = await editor.patch(
        url(ctx, f"/webhook-endpoints/{body['id']}"),
        json={"name": "renamed", "enabled": False, "allowlist": ["203.0.113.0/24"]},
    )
    assert patched.status_code == 200, patched.text
    assert {k: patched.json()[k] for k in ("name", "enabled", "allowlist")} == {
        "name": "renamed", "enabled": False, "allowlist": ["203.0.113.0/24"],
    }  # fmt: skip
    for refused in ({"id_source": "pointer", "id_pointer": "/id"}, {"auth": "hmac"}, {"name": None},
                    {"events_pointer": "/events"}, {"events_pointer": None}):  # fmt: skip
        assert (await editor.patch(url(ctx, f"/webhook-endpoints/{body['id']}"), json=refused)).status_code == 422
    other = uuid.uuid4()
    assert (await editor.patch(url(ctx, f"/webhook-endpoints/{other}"), json={"name": "x"})).status_code == 404


@pytest.mark.parametrize("ids", [{"id_source": "pointer", "id_pointer": "/id"},
                                 {"id_source": "header", "id_header": "x-event-id"}])  # fmt: skip
async def test_every_field_a_patch_supports_and_a_rotation_are_written_as_the_apis_role(
    keyed_app, tenant, owner_sessionmaker, api_settings, ids: dict[str, str]
) -> None:
    """The owner's docs review: the API's role has no grant to change where an endpoint's ids are, and still writes
    every field a PATCH supports, the byte burst a larger body limit needs, and a rotated HMAC secret, for an endpoint
    whose ids are at a pointer or in a header (a PATCH of one was refused, its ids checked as if it gave them)."""
    ctx, _ = tenant
    body = await made(keyed_app, owner_sessionmaker, api_settings, ctx, auth="hmac", **ids)
    editor = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "editor")
    changes = {"name": "renamed", "enabled": False, "signature_header": "x-sig", "timestamp_header": "x-ts",
               "tolerance_s": 600, "allowlist": ["203.0.113.0/24"], "body_limit": 5 * MIB}  # fmt: skip
    patched = await editor.patch(url(ctx, f"/webhook-endpoints/{body['id']}"), json=changes)
    assert patched.status_code == 200, patched.text
    assert {k: patched.json()[k] for k in changes} == changes
    before = await row(owner_sessionmaker, "webhook_endpoints", body["id"])
    rotated = await editor.post(url(ctx, f"/webhook-endpoints/{body['id']}/secret"))
    assert rotated.status_code == 200, rotated.text
    after = await row(owner_sessionmaker, "webhook_endpoints", body["id"])
    assert after["hmac_secret"] != before["hmac_secret"] and after["byte_burst"] >= 5 * 5 * MIB + 64_000
    assert {k: after[k] for k in ids} == ids and after["dedupe_key"] == before["dedupe_key"]


async def test_bindings_are_checked_capped_and_unique(keyed_app, tenant, owner_sessionmaker, api_settings,
                                                      api_sessionmaker, admin_sessionmaker) -> None:  # fmt: skip
    ctx, wf = tenant
    endpoint = await made(keyed_app, owner_sessionmaker, api_settings, ctx)
    editor = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "editor")
    bindings = url(ctx, f"/webhook-endpoints/{endpoint['id']}/bindings")
    created = await editor.post(bindings, json={"workflow_id": str(wf),
                                                "filter": [{"pointer": "/type", "value": "ap_down"}]})  # fmt: skip
    assert created.status_code == 201, created.text
    assert created.json()["filter"] == [{"pointer": "/type", "value": "ap_down"}]
    assert (await editor.post(bindings, json={"workflow_id": str(wf)})).status_code == 409  # one per workflow
    bad = await editor.post(bindings, json={"workflow_id": str(wf), "filter": [{"pointer": "/a", "value": 1.5}]})
    assert (bad.status_code, bad.json()["error"]) == (422, "filter_invalid")
    theirs, their_wf = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings,
                                       OPEN_GRAPH)  # fmt: skip
    assert (await editor.post(bindings, json={"workflow_id": str(their_wf)})).status_code == 404
    async with owner_sessionmaker() as s, s.begin():
        for n in range(20):
            await s.execute(
                text("insert into workflows (id, tenant_id, name, enabled, draft) values (:w, :t, :n, true, '{}')"),
                {"w": uuid.uuid4(), "t": ctx.tenant_id, "n": f"extra-{n}"},
            )
        extra = (await s.execute(text("select id from workflows where tenant_id = :t and name like 'extra-%' "
                                      "order by name"), {"t": ctx.tenant_id})).scalars().all()  # fmt: skip
    for workflow_id in extra[:19]:
        assert (await editor.post(bindings, json={"workflow_id": str(workflow_id)})).status_code == 201
    capped = await editor.post(bindings, json={"workflow_id": str(extra[19])})
    assert (capped.status_code, capped.json()["error"]) == (409, "binding_cap")
    viewer = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "viewer")
    assert len((await viewer.get(bindings)).json()["bindings"]) == 20
    binding = created.json()["id"]
    patched = await editor.patch(url(ctx, f"/webhook-bindings/{binding}"), json={"enabled": False, "filter": []})
    assert {k: patched.json()[k] for k in ("enabled", "filter")} == {"enabled": False, "filter": []}
    assert (await editor.delete(url(ctx, f"/webhook-bindings/{binding}"))).status_code == 204
    assert (await viewer.post(bindings, json={"workflow_id": str(wf)})).status_code == 403
    assert len(await audited(owner_sessionmaker, "webhook_binding.create")) == 20


async def _events(ingress: Any, ctx: Any, endpoint_id: str, n: int) -> list[uuid.UUID]:
    """`n` events recorded through ingress's function, sealed to the tenant's key, carrying the canary."""
    async with ingress() as s:
        public = (await s.execute(text("select public_key from resolve_webhook_endpoint(:e)"),
                                  {"e": endpoint_id})).scalar_one()  # fmt: skip
    ids = [uuid.uuid4() for _ in range(n)]
    sealed = [(None, None, events.seal(public, 1, tenant_id=ctx.tenant_id, endpoint_id=uuid.UUID(endpoint_id),
                                       event_id=i, plaintext=canonical({"note": CANARY, "n": k})))
              for k, i in enumerate(ids)]  # fmt: skip
    assert (await record(ingress, uuid.UUID(endpoint_id), sealed, ids=ids))["outcome"] == "recorded"
    return ids


async def pending(owner: Any, ctx: Any, endpoint_id: str) -> tuple[int, int]:
    async with owner() as s:
        e = (await s.execute(text("select pending_events from webhook_endpoints where id = :e"),
                             {"e": endpoint_id})).scalar_one()  # fmt: skip
        t = (await s.execute(text("select pending_events from tenant_event_counters where tenant_id = :t"),
                             {"t": ctx.tenant_id})).scalar_one()  # fmt: skip
    return e, t


async def test_events_are_listed_as_metadata_only(keyed_app, tenant, owner_sessionmaker, api_settings,
                                                  ingress_sessionmaker) -> None:  # fmt: skip
    ctx, _ = tenant
    endpoint = await made(keyed_app, owner_sessionmaker, api_settings, ctx)
    ids = await _events(ingress_sessionmaker, ctx, endpoint["id"], 2)
    viewer = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "viewer")
    answer = await viewer.get(url(ctx, f"/webhook-endpoints/{endpoint['id']}/events"))
    assert answer.status_code == 200, answer.text
    listed = answer.json()["events"]
    assert sorted(e["id"] for e in listed) == sorted(str(i) for i in ids)
    assert set(listed[0]) == {"id", "endpoint_id", "status", "reason", "attempts", "next_attempt_at",
                              "request_count", "size_bytes", "key_version", "received_at", "ended_at"}  # fmt: skip
    assert CANARY not in answer.text
    matched = await viewer.get(url(ctx, f"/webhook-endpoints/{endpoint['id']}/events?status=matched"))
    assert matched.json()["events"] == []
    usage = (await viewer.get(url(ctx, "/inbound-usage"))).json()
    assert {k: usage[k] for k in ("pending_events", "retained_events")} == {"pending_events": 2, "retained_events": 2}
    assert usage["pending_events_max"] == 50_000 and usage["retained_bytes"] > 0


async def test_an_admin_lists_dead_events_and_cancels_pending_or_dead_ones(
    keyed_app, tenant, owner_sessionmaker, api_settings, ingress_sessionmaker
) -> None:
    ctx, _ = tenant
    endpoint = await made(keyed_app, owner_sessionmaker, api_settings, ctx)
    dead, waiting, done = await _events(ingress_sessionmaker, ctx, endpoint["id"], 3)
    async with owner_sessionmaker() as s, s.begin():  # one dead (its counters released), one matched
        await s.execute(text("update inbound_events set status = 'dead', reason = 'event_unreadable', ended_at = now() "
                             "where id = :e"), {"e": dead})  # fmt: skip
        await s.execute(text("update inbound_events set status = 'matched', request_count = 0, ended_at = now() "
                             "where id = :e"), {"e": done})  # fmt: skip
        for table, where in (("webhook_endpoints", "id = :i"), ("tenant_event_counters", "tenant_id = :t")):
            await s.execute(text(f"update {table} set pending_events = 1 where {where}"),  # noqa: S608
                            {"i": endpoint["id"], "t": ctx.tenant_id})  # fmt: skip
    editor = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "editor")
    assert (await editor.get(url(ctx, "/inbound-events/dead"))).status_code == 403
    assert (await editor.post(url(ctx, f"/inbound-events/{waiting}/cancel"))).status_code == 403
    admin = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "admin")
    listed = (await admin.get(url(ctx, "/inbound-events/dead"))).json()["events"]
    assert [e["id"] for e in listed] == [str(dead)] and CANARY not in json.dumps(listed)
    for event_id in (dead, waiting):
        answer = await admin.post(url(ctx, f"/inbound-events/{event_id}/cancel"))
        assert (answer.status_code, answer.json()["status"]) == (200, "cancelled"), answer.text
    assert await pending(owner_sessionmaker, ctx, endpoint["id"]) == (0, 0)  # the dead one had released its own
    assert (await admin.post(url(ctx, f"/inbound-events/{done}/cancel"))).json()["error"] == "not_cancellable"
    assert (await admin.post(url(ctx, f"/inbound-events/{uuid.uuid4()}/cancel"))).status_code == 404
    assert sorted(e["target_id"] for e in await audited(owner_sessionmaker, "inbound_event.cancel")) == sorted(
        [str(dead), str(waiting)]
    )


async def test_an_admin_cancels_an_endpoints_pending_events_at_once(
    keyed_app, tenant, owner_sessionmaker, api_settings, ingress_sessionmaker
) -> None:
    ctx, _ = tenant
    endpoint = await made(keyed_app, owner_sessionmaker, api_settings, ctx)
    await _events(ingress_sessionmaker, ctx, endpoint["id"], 3)
    admin = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "admin")
    answer = await admin.post(url(ctx, f"/webhook-endpoints/{endpoint['id']}/cancel-pending"))
    assert (answer.status_code, answer.json()) == (200, {"cancelled": 3})
    assert await pending(owner_sessionmaker, ctx, endpoint["id"]) == (0, 0)
    async with owner_sessionmaker() as s:
        bytes_left = (await s.execute(text("select pending_bytes from webhook_endpoints where id = :e"),
                                      {"e": endpoint["id"]})).scalar_one()  # fmt: skip
    assert bytes_left == 0
    [entry] = await audited(owner_sessionmaker, "webhook_endpoint.cancel_pending")
    assert entry["details"]["cancelled"] == 3


async def test_reading_or_cancelling_events_never_loads_their_ciphertexts(
    keyed_app, tenant, owner_sessionmaker, api_settings, ingress_sessionmaker
) -> None:
    """The final review: listing an endpoint's events (any viewer may), the dead ones, and cancelling one or an
    endpoint's pending ones read metadata only. An event's sealed payload, up to 4.5 times its body limit, never leaves
    Postgres for the API: only the matcher opens it."""
    ctx, _ = tenant
    endpoint = await made(keyed_app, owner_sessionmaker, api_settings, ctx)
    one, *_ = await _events(ingress_sessionmaker, ctx, endpoint["id"], 3)
    admin = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "admin")
    statements: list[str] = []

    def seen(conn: Any, cursor: Any, statement: str, parameters: Any, context: Any, executemany: bool) -> None:
        statements.append(statement)

    event.listen(Engine, "before_cursor_execute", seen)
    try:
        for path in (f"/webhook-endpoints/{endpoint['id']}/events", "/inbound-events/dead"):
            assert (await admin.get(url(ctx, path))).status_code == 200
        assert (await admin.post(url(ctx, f"/inbound-events/{one}/cancel"))).status_code == 200
        cancelled = await admin.post(url(ctx, f"/webhook-endpoints/{endpoint['id']}/cancel-pending"))
        assert cancelled.json() == {"cancelled": 2}
    finally:
        event.remove(Engine, "before_cursor_execute", seen)
    read = [statement for statement in statements if "inbound_events" in statement]
    assert read and [statement for statement in read if "sealed" in statement] == []


async def test_two_bindings_made_at_once_never_pass_the_cap_together(
    keyed_app, tenant, owner_sessionmaker, api_settings
) -> None:
    """The cap is counted under the endpoint's row lock: two writers at 19 bindings are serialized, one refused."""
    import asyncio

    ctx, wf = tenant
    endpoint = await made(keyed_app, owner_sessionmaker, api_settings, ctx)
    editor = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "editor")
    bindings = url(ctx, f"/webhook-endpoints/{endpoint['id']}/bindings")
    async with owner_sessionmaker() as s, s.begin():
        for n in range(20):
            await s.execute(
                text("insert into workflows (id, tenant_id, name, enabled, draft) values (:w, :t, :n, true, '{}')"),
                {"w": uuid.uuid4(), "t": ctx.tenant_id, "n": f"extra-{n:02}"},
            )
        extra = (await s.execute(text("select id from workflows where tenant_id = :t and name like 'extra-%' "
                                      "order by name"), {"t": ctx.tenant_id})).scalars().all()  # fmt: skip
    assert (await editor.post(bindings, json={"workflow_id": str(wf)})).status_code == 201
    for workflow_id in extra[:18]:
        assert (await editor.post(bindings, json={"workflow_id": str(workflow_id)})).status_code == 201
    async with owner_sessionmaker() as s, s.begin():  # both writers wait on the endpoint's row, then go one by one
        await s.execute(text("select 1 from webhook_endpoints where id = :e for update"), {"e": endpoint["id"]})
        racing = [asyncio.create_task(editor.post(bindings, json={"workflow_id": str(w)})) for w in extra[18:]]
        await asyncio.sleep(0.3)
    answers = sorted([(await r).status_code for r in racing])
    assert answers == [201, 409]
    async with owner_sessionmaker() as s:
        assert (await s.execute(text("select count(*) from trigger_bindings where endpoint_id = :e"),
                                {"e": endpoint["id"]})).scalar_one() == 20  # fmt: skip


async def test_an_endpoints_event_list_shows_dead_events_to_admins_only(
    keyed_app, tenant, owner_sessionmaker, api_settings, ingress_sessionmaker
) -> None:
    """The owner's M3 review: dead events are listed with `tenant.manage` only, so an endpoint's event list (read with
    `workflow.view`) leaves them out for anyone else, filtered or not."""
    ctx, _ = tenant
    endpoint = await made(keyed_app, owner_sessionmaker, api_settings, ctx)
    dead, alive = await _events(ingress_sessionmaker, ctx, endpoint["id"], 2)
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(text("update inbound_events set status = 'dead', reason = 'event_unreadable', ended_at = now() "
                             "where id = :e"), {"e": dead})  # fmt: skip
    events = url(ctx, f"/webhook-endpoints/{endpoint['id']}/events")
    for role in ("viewer", "operator", "editor"):
        client = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, role)
        assert [e["id"] for e in (await client.get(events)).json()["events"]] == [str(alive)], role
        assert (await client.get(f"{events}?status=dead")).json()["events"] == [], role
    admin = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "admin")
    assert sorted(e["id"] for e in (await admin.get(events)).json()["events"]) == sorted([str(dead), str(alive)])
    assert [e["id"] for e in (await admin.get(f"{events}?status=dead")).json()["events"]] == [str(dead)]
