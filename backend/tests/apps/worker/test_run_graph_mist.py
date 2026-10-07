# SPDX-License-Identifier: Apache-2.0
"""3b-1's proof (plugins-3 D1, D14-D17, D23, D28), end to end:

- a published workflow of generated Mist nodes runs through admission, the dispatcher and RunGraph against a local
  Mist fake standing in for `api.eu.mist.com` (vetted, pinned and TLS-checked by the guard; its port 443 redirected in
  the test's socket layer only): a site's devices listed once the site is checked to be the connection's org's, then a
  WLAN merge-updated (read, then the touched structure sent whole); the token is the runtime's, in no preview;
- simulated, the same workflow sends nothing;
- a Mist webhook envelope recorded by ingress's own function is matched by its binding's `/topic` filter and runs a
  workflow whose trigger the topic's schema types; another topic's envelope matches nothing."""

import asyncio
import ipaddress
import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpcore
import pytest
from sqlalchemy import text
from temporalio.testing import WorkflowEnvironment

from dewpoint.apps import dev_run
from dewpoint.apps.dispatcher import matching
from dewpoint.apps.dispatcher.dispatch import dispatch_once
from dewpoint.apps.plugin_loader import sync_installed
from dewpoint.apps.worker.network import DbConnections, Network, worker_types
from dewpoint.apps.worker.store import DbRunStore
from dewpoint.core.db import tenant_scope
from dewpoint.core.egress.addresses import AllowEntry
from dewpoint.plugins.flow import PLUGIN as FLOW
from dewpoint.plugins.mist import PLUGIN as MIST
from dewpoint.plugins.mist.webhook import WEBHOOK
from tests.apps.dispatcher.inbound import bind, inbound, send
from tests.apps.dispatcher.support import BUILD
from tests.apps.dispatcher.support import workers as ready_workers
from tests.apps.test_admission import KEYS, current
from tests.apps.test_workflow_ops import actor, create, publish
from tests.apps.worker.harness import workers
from tests.support.connections import add_connection
from tests.support.graphs import G, ref
from tests.support.netfakes import Request, Server, guard, serve, tls
from tests.support.plugins.testkit import TESTKIT

pytestmark = pytest.mark.usefixtures("development_deployment")
HOST = "api.eu.mist.com"
ORG, SITE, WLAN = (str(uuid.uuid4()) for _ in range(3))
TOKEN = "tok_" + "q" * 36
PASSPHRASE = "old-passphrase-value"
DEVICES = [{"id": str(uuid.uuid4()), "name": "ap-1", "type": "ap", "mac": "aabbccddeeff", "site_id": SITE}]
CURRENT = {"id": WLAN, "org_id": ORG, "ssid": "corp", "vlan_id": 10,
           "auth": {"type": "psk", "psk": PASSPHRASE, "pairwise": ["wpa2-ccmp"]}}  # fmt: skip


def answer(writer: asyncio.StreamWriter, status: int, body: Any, headers: str = "") -> None:
    raw = json.dumps(body).encode()
    writer.write(f"HTTP/1.1 {status} X\r\ncontent-type: application/json\r\ncontent-length: {len(raw)}\r\n{headers}\r\n"
                 .encode() + raw)  # fmt: skip


async def mist(request: Request, writer: asyncio.StreamWriter) -> None:
    """Mist as far as this proof needs it, for this token only."""
    path = request.target.split("?", 1)[0]
    if request.headers.get("authorization") != f"Token {TOKEN}":
        answer(writer, 401, {"detail": "unauthorized"})
    elif (request.method, path) == ("GET", f"/api/v1/sites/{SITE}"):
        answer(writer, 200, {"id": SITE, "org_id": ORG, "name": "Paris"})
    elif (request.method, path) == ("GET", f"/api/v1/sites/{SITE}/devices"):
        answer(writer, 200, DEVICES, "X-Page-Limit: 100\r\nX-Page-Page: 1\r\nX-Page-Total: 1\r\n")
    elif (request.method, path) == ("GET", f"/api/v1/orgs/{ORG}/wlans/{WLAN}"):
        answer(writer, 200, CURRENT)
    elif (request.method, path) == ("PUT", f"/api/v1/orgs/{ORG}/wlans/{WLAN}"):
        answer(writer, 200, {**CURRENT, **json.loads(request.body)})
    else:
        answer(writer, 404, {"detail": "not found"})
    await writer.drain()


@pytest.fixture
async def fake_mist(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Server]:
    async with serve(mist, tls_names=(HOST,)) as server:
        dial = httpcore.AnyIOBackend.connect_tcp

        async def redirected(self: Any, host: str, port: int, *args: Any, **kwargs: Any) -> Any:
            if (host, port) == ("127.0.0.1", 443):  # the vetted address, Mist's port: the fake's
                port = server.port
            return await dial(self, host, port, *args, **kwargs)

        monkeypatch.setattr(httpcore.AnyIOBackend, "connect_tcp", redirected)
        yield server


async def _published(owner: Any, api: Any, admin: Any, dispatch: Any, settings: Any) -> tuple[Any, uuid.UUID]:
    async with admin() as s, s.begin():
        await sync_installed(s, [FLOW, TESTKIT, MIST])
    ctx = await actor(owner)
    cid = str(await add_connection(owner, ctx.tenant_id, type_key="mist", config={"cloud": "emea_01", "org_id": ORG},
                                   secret={"api_token": TOKEN}))  # fmt: skip
    g = G()
    g.node("devices", "mist.site_devices.list@1", {"connection": cid, "site_id": SITE})
    g.node("wlan", "mist.org_wlans.update@1",
           {"connection": cid, "wlan_id": WLAN, "body": {"auth": {"pairwise": ["wpa2-ccmp", "wpa3"]}}})  # fmt: skip
    g.edge("devices", "wlan")
    g.settings = {"outputs": {"truncated": ref("steps.devices.output.truncated")}}
    wf = await create(api, ctx, g.data())
    published = await publish(api, ctx, wf, settings)
    assert published.version is not None, published
    await current(dispatch)
    await ready_workers(owner)
    return ctx, wf


async def _run(env: Any, ctx: Any, wf: Any, dispatch: Any, worker: Any, settings: Any, *, simulate: bool) -> Any:
    network = Network(
        guard=guard({HOST: ["127.0.0.1"]}, [AllowEntry(ipaddress.ip_network("127.0.0.1/32"), None, ctx.tenant_id)]),
        connections=DbConnections(worker),
        sessionmaker=worker,
        keys=KEYS,
        ssl_context=tls((HOST,)).client_context(),
        types=worker_types([MIST]),
    )
    request = await dev_run.admit(dispatch, KEYS, tenant_id=ctx.tenant_id, workflow_id=wf, input={},
                                  simulate=simulate, idempotency_key=f"m-{simulate}")  # fmt: skip
    async with workers(env.client, DbRunStore(worker, KEYS), plugins=(TESTKIT, MIST), network=network):
        assert await dispatch_once(dispatch, env.client, KEYS, settings, BUILD) == {"started": 1}
        return request, await dev_run.wait_for_end(dispatch, ctx.tenant_id, request.id, within=60, poll=0.1)


async def test_a_mist_workflow_lists_devices_and_merge_updates_a_wlan(
    env: WorkflowEnvironment, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker,
    worker_sessionmaker, api_settings, fake_mist,
) -> None:  # fmt: skip
    ctx, wf = await _published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker,
                               api_settings)  # fmt: skip
    request, ended = await _run(env, ctx, wf, dispatch_sessionmaker, worker_sessionmaker, api_settings, simulate=False)
    assert ended == dev_run.Ended("run", "succeeded", None, None), ended
    sent = [(r.method, r.target.split("?", 1)[0]) for r in fake_mist.requests]
    assert sent == [
        ("GET", f"/api/v1/sites/{SITE}"), ("GET", f"/api/v1/sites/{SITE}/devices"),
        ("GET", f"/api/v1/orgs/{ORG}/wlans/{WLAN}"), ("PUT", f"/api/v1/orgs/{ORG}/wlans/{WLAN}"),
    ]  # fmt: skip
    assert json.loads(fake_mist.requests[3].body) == {
        "auth": {"type": "psk", "psk": PASSPHRASE, "pairwise": ["wpa2-ccmp", "wpa3"]}
    }
    assert {r.headers["authorization"] for r in fake_mist.requests} == {f"Token {TOKEN}"}
    async with worker_sessionmaker() as s, s.begin():
        await tenant_scope(s, ctx.tenant_id)
        rows = (await s.execute(text("select input_preview::text, output_preview::text, status from run_steps"))).all()
    assert sorted(r[2] for r in rows) == ["succeeded", "succeeded"]
    assert all(TOKEN not in (p or "") and PASSPHRASE not in (p or "") for r in rows for p in r[:2])
    index = await DbRunStore(worker_sessionmaker, KEYS).index(str(ctx.tenant_id), str(request.id))
    assert TOKEN in index.strings


async def test_a_simulated_mist_workflow_sends_nothing(
    env: WorkflowEnvironment, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker,
    worker_sessionmaker, api_settings, fake_mist,
) -> None:  # fmt: skip
    ctx, wf = await _published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker,
                               api_settings)  # fmt: skip
    _, ended = await _run(env, ctx, wf, dispatch_sessionmaker, worker_sessionmaker, api_settings, simulate=True)
    assert ended is not None and ended.status == "succeeded", ended
    assert fake_mist.requests == []


ALARM = {"id": str(uuid.uuid4()), "org_id": ORG, "site_id": SITE, "timestamp": 1760000000, "type": "ap_down",
         "severity": "critical", "aps": ["aabbccddeeff"]}  # fmt: skip


async def test_a_mist_webhook_envelope_runs_the_workflow_its_topic_binds(
    env: WorkflowEnvironment, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker,
    ingress_sessionmaker, worker_sessionmaker, api_settings,
) -> None:  # fmt: skip
    g = G().node("echo", "testkit.echo@1", {"value": ref("trigger.events")})
    g.settings = {"input_schema": WEBHOOK.topics["alarms"], "outputs": {"events": ref("steps.echo.output.value")}}
    ready = await inbound(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker,
                          api_settings, g.data())  # fmt: skip
    await bind(owner_sessionmaker, ready, filter=[{"pointer": "/topic", "value": "alarms"}])
    await ready_workers(owner_sessionmaker)
    alarms, updowns, malformed = await send(
        ingress_sessionmaker, ready, {"topic": "alarms", "events": [ALARM]},
        {"topic": "device-updowns", "events": [{"type": "AP_DISCONNECTED"}]},
        {"topic": "alarms", "events": "not a list"},
    )  # fmt: skip
    verified = matching.Verified()
    outcomes = [
        await matching.match_event(
            dispatch_sessionmaker, KEYS, verified, tenant_id=ready.tenant_id, event_id=e, endpoint_id=ready.endpoint_id
        )  # fmt: skip
        for e in (alarms, updowns, malformed)
    ]
    assert outcomes == ["matched", "unmatched", "matched"]
    async with owner_sessionmaker() as s:
        found = await s.execute(text("select idempotency_key, id, status, reason from run_requests"))
        requests = {key.split(":")[1]: (rid, status, reason) for key, rid, status, reason in found.all()}
    assert requests[str(alarms)][1:] == ("queued", None)
    assert requests[str(malformed)][1:] == ("refused", "input_invalid")  # the topic's schema refuses it
    request_id = requests[str(alarms)][0]
    async with workers(env.client, DbRunStore(worker_sessionmaker, KEYS)):
        assert await dispatch_once(dispatch_sessionmaker, env.client, KEYS, api_settings, BUILD) == {"started": 1}
        ended = await dev_run.wait_for_end(dispatch_sessionmaker, ready.tenant_id, request_id, within=30, poll=0.1)
    assert ended is not None and ended.status == "succeeded", ended
    async with owner_sessionmaker() as s:
        steps = (await s.execute(text("select node_key, status from run_steps"))).all()
    assert [tuple(r) for r in steps] == [("echo", "succeeded")]
