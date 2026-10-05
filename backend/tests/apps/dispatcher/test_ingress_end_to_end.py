# SPDX-License-Identifier: Apache-2.0
"""2b-3b's proof on Temporal's CLI dev server (engine 2b spec §8.3, §12): a webhook becomes a run end to end with the
keyring's real keys everywhere. The API makes an HMAC endpoint and a bearer one (their secrets shown once) and a
binding; ingress records a signed event carrying a canary in a sensitive field, sealed to the tenant's keypair; a
match whose transaction fails before its commit leaves it pending; the matcher then admits it once; the dispatcher
starts it on a versioned engine worker, and it succeeds. The event's canary, the HMAC secret and the bearer token
appear in no execution's whole raw history, no projection, no stored row in plain, no log line and no audit entry. A
replay outside the tolerance is refused.

The limits, the quotas and the retained cap are proven through ingress's own app (`tests/apps/ingress`); the gate
off, on events recorded before (`test_matching.py`): ingress itself records nothing in a production deployment."""

import hashlib
import hmac
import json
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
import structlog
from sqlalchemy import text
from temporalio.client import Client
from temporalio.testing import WorkflowEnvironment

from dewpoint.apps.codec import data_converter
from dewpoint.apps.dispatcher import dispatch, matching
from dewpoint.apps.ingress.main import create_app as create_ingress
from dewpoint.apps.worker.store import DbRunStore
from dewpoint.core.crypto.kek import KekSet
from dewpoint.core.crypto.keyring import Keyring
from dewpoint.core.crypto.keys import KeyringKeys
from dewpoint.core.tenancy.service import ensure_tenant_keys
from tests.apps.api.helpers import member_client
from tests.apps.dispatcher.support import BUILD, workers
from tests.apps.dispatcher.test_dev_server import until_ended
from tests.apps.dispatcher.test_triggers_end_to_end import decrypted_input, raw_histories
from tests.apps.ingress.support import KEY
from tests.apps.ingress.support import client as ingress_client
from tests.apps.ingress.support import settings as ingress_settings
from tests.apps.test_admission import current, published
from tests.apps.worker.test_real_server import serving
from tests.support.graphs import G, ref
from tests.support.keys import FIXTURE_CONVERTER

pytestmark = pytest.mark.usefixtures("development_deployment")
CANARY = "Hook-c4n4ry-W8q"
EVENT_SCHEMA = {  # an event as a sender sends it: its id, a sensitive field, and the rest
    "type": "object",
    "properties": {
        "id": {"type": "string"},
        "token": {"type": "string", "x-sensitive": True},
        "site": {"type": "string"},
    },
    "required": ["id", "token"],
    "additionalProperties": False,
}
ECHO_GRAPH = G().node("a", "testkit.echo@1", {"value": ref("trigger.token")}).data() | {
    "settings": {"input_schema": EVENT_SCHEMA}
}


@pytest.fixture(scope="module")
async def server() -> AsyncIterator[WorkflowEnvironment]:
    async with await WorkflowEnvironment.start_local(data_converter=FIXTURE_CONVERTER) as environment:
        yield environment


async def plain_rows(owner: Any) -> str:
    """Every row 2b-3b writes or a run it starts writes, as text (their ciphertexts included, which must hold no
    canary or secret in plain)."""
    tables = (
        "webhook_endpoints",
        "trigger_bindings",
        "inbound_events",
        "tenant_event_counters",
        "tenant_event_keys",
        "run_requests",
        "runs",
        "run_steps",
        "audit_log",
        "run_inputs",
        "step_outputs",
        "run_secret_index",
    )
    async with owner() as s:
        return "\n".join([str((await s.execute(text(f"select * from {t}"))).all()) for t in tables])  # noqa: S608


def signed(secret: str, body: bytes, stamp: int) -> dict[str, str]:
    signature = hmac.new(secret.encode(), str(stamp).encode() + b"." + body, hashlib.sha256).hexdigest()
    return {"x-dewpoint-timestamp": str(stamp), "x-dewpoint-signature": signature}


async def test_a_signed_webhook_becomes_a_run_end_to_end_with_the_keyrings_real_keys_leaking_nothing(
    server, app, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, worker_sessionmaker,
    api_settings, pg_url, monkeypatch,
) -> None:  # fmt: skip
    ctx, wf = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings, ECHO_GRAPH)
    await current(dispatch_sessionmaker)
    await workers(owner_sessionmaker)
    keyring = Keyring(KekSet.from_settings(api_settings))
    async with admin_sessionmaker() as s, s.begin():
        assert ctx.tenant_id in await ensure_tenant_keys(s, keyring)  # a real data key, wrapped by the KEK
    app.state.ingress_key = KEY  # the API seals endpoint secrets under the key ingress opens them with
    dispatch_keys, worker_keys = KeyringKeys(dispatch_sessionmaker, keyring), KeyringKeys(worker_sessionmaker, keyring)
    target, namespace = server.client.service_client.config.target_host, server.client.namespace
    dispatcher = await Client.connect(target, namespace=namespace, data_converter=data_converter(dispatch_keys))
    worker = await Client.connect(target, namespace=namespace, data_converter=data_converter(worker_keys))
    editor, _ = await member_client(app, owner_sessionmaker, api_settings, ctx.tenant_id, "editor")
    base = f"/api/v1/t/{ctx.tenant_id}"
    ingress = create_ingress(ingress_settings(pg_url))
    with structlog.testing.capture_logs() as logs:
        made = await editor.post(
            f"{base}/webhook-endpoints",
            json={"name": "alarms", "auth": "hmac", "id_source": "pointer", "id_pointer": "/id"},
        )
        assert made.status_code == 201, made.text
        endpoint, secret = made.json(), made.json()["secret"]
        bearer = await editor.post(f"{base}/webhook-endpoints", json={"name": "other"})
        token = bearer.json()["secret"]
        bound = await editor.post(f"{base}/webhook-endpoints/{endpoint['id']}/bindings", json={"workflow_id": str(wf)})
        assert bound.status_code == 201, bound.text
        body = json.dumps({"id": "evt-1", "token": CANARY, "site": "lyon"}).encode()
        now = int(time.time())
        async with ingress_client(ingress) as hooks:
            replayed = await hooks.post(endpoint["path"], content=body, headers=signed(secret, body, now - 301))
            assert (replayed.status_code, replayed.content) == (401, b"")  # outside the tolerance
            recorded = await hooks.post(endpoint["path"], content=body, headers=signed(secret, body, now))
            assert (recorded.status_code, recorded.json()) == (200, {"accepted": 1, "duplicates": 0})
            other = await hooks.post(bearer.json()["path"], content=b'{"n": 1}',
                                     headers={"authorization": f"Bearer {token}"})  # fmt: skip
            assert other.status_code == 200
        [event_id] = await owner_rows(owner_sessionmaker, endpoint["id"])

        async def crash() -> None:
            raise RuntimeError("the dispatcher dies before its commit")

        monkeypatch.setattr(matching, "_before_commit", crash)
        assert (await matching.match_once(dispatch_sessionmaker, dispatch_keys, matching.Verified())).get("error")
        assert await status_of(owner_sessionmaker, event_id) == ("pending", None)  # nothing it decided stayed
        monkeypatch.undo()
        counts = await matching.match_once(dispatch_sessionmaker, dispatch_keys, matching.Verified())
        assert counts.get("matched") == 1, counts
        assert await status_of(owner_sessionmaker, event_id) == ("matched", 1)
        request_id = await request_of(owner_sessionmaker, event_id, wf)
        async with serving(worker, DbRunStore(worker_sessionmaker, worker_keys)):  # type: ignore[arg-type]
            for _ in range(20):
                if not await dispatch.dispatch_once(dispatch_sessionmaker, dispatcher, dispatch_keys, api_settings,
                                                    BUILD):  # fmt: skip
                    break
            run = await until_ended(editor, f"{base}/runs/{request_id}")
        audited = (await editor.get(f"{base}/runs/{request_id}")).json()
    await ingress.state.engine.dispose()
    assert (run["status"], run["request"]["source"], run["request"]["reason"]) == ("succeeded", "webhook", None)
    # The canary was in the data: the request's input, decrypted with the real keys, is the event.
    assert (await decrypted_input(dispatch_sessionmaker, dispatch_keys, ctx.tenant_id, request_id))["token"] == CANARY
    secrets = (CANARY, secret, token)
    raws = await raw_histories(server.client)
    assert raws and all(str(ctx.tenant_id).encode() in raw for raw in raws)  # this tenant's real histories, whole
    assert not [c for c in secrets for raw in raws if c.encode() in raw]
    rows = await plain_rows(owner_sessionmaker)
    assert not [c for c in secrets if c in rows]
    assert not [c for c in secrets for entry in logs if c in str(entry)]
    assert not [c for c in secrets if c in json.dumps(audited)]
    steps = audited["steps"]
    assert steps and CANARY not in str(steps)


async def owner_rows(owner: Any, endpoint_id: str) -> list[uuid.UUID]:
    async with owner() as s:
        return list((await s.execute(text("select id from inbound_events where endpoint_id = :e"),
                                     {"e": endpoint_id})).scalars())  # fmt: skip


async def status_of(owner: Any, event_id: uuid.UUID) -> tuple[str, int | None]:
    async with owner() as s:
        row = (await s.execute(text("select status, request_count from inbound_events where id = :e"),
                               {"e": event_id})).one()  # fmt: skip
    return row[0], row[1]


async def request_of(owner: Any, event_id: uuid.UUID, workflow_id: uuid.UUID) -> str:
    async with owner() as s:
        return str((await s.execute(text("select id from run_requests where idempotency_key = :k"),
                                    {"k": f"evt:{event_id}:{workflow_id}"})).scalar_one())  # fmt: skip
