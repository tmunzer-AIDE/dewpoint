# SPDX-License-Identifier: Apache-2.0
"""3b-2's proof (plugins-3 D26, D27), end to end: a published workflow of Mist device utilities runs through admission,
the dispatcher and RunGraph against local fakes standing in for `api.eu.mist.com` and its stream host
`api-ws.eu.mist.com` (each vetted, pinned and TLS-checked by the guard; their port 443 redirected in the test's socket
layer only):

- a ping checks its site and its device, subscribes to the device's command channel with the runtime's token, POSTs,
  and returns the session's output once it goes quiet, another session's discarded;
- a bounce-port checks the same, only POSTs, and reports the command accepted, its completion unknown, opening no
  stream;
- simulated, the same workflow sends nothing and opens no stream."""

import asyncio
import ipaddress
import json
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import httpcore
import pytest
from sqlalchemy import text
from temporalio.testing import WorkflowEnvironment
from websockets.asyncio.server import ServerConnection, serve
from websockets.datastructures import Headers
from websockets.http11 import Request as WsRequest
from websockets.http11 import Response as WsResponse

from dewpoint.apps import dev_run
from dewpoint.apps.dispatcher.dispatch import dispatch_once
from dewpoint.apps.plugin_loader import sync_installed
from dewpoint.apps.worker.network import DbConnections, Network, worker_types
from dewpoint.apps.worker.store import DbRunStore
from dewpoint.core.db import tenant_scope
from dewpoint.core.egress import ws as core_ws
from dewpoint.core.egress.addresses import AllowEntry
from dewpoint.plugins.flow import PLUGIN as FLOW
from dewpoint.plugins.mist import PLUGIN as MIST
from dewpoint.plugins.mist import stream
from tests.apps.dispatcher.support import BUILD
from tests.apps.dispatcher.support import workers as ready_workers
from tests.apps.test_admission import KEYS, current
from tests.apps.test_workflow_ops import actor, create, publish
from tests.apps.worker.harness import workers
from tests.support.connections import add_connection
from tests.support.graphs import G, ref
from tests.support.netfakes import Request, Server, guard, tls
from tests.support.netfakes import serve as serve_http

pytestmark = pytest.mark.usefixtures("development_deployment")
HOST, WS_HOST = "api.eu.mist.com", "api-ws.eu.mist.com"
NAMES = (HOST, WS_HOST)
ORG, SITE = str(uuid.uuid4()), str(uuid.uuid4())
SWITCH = "00000000-0000-0000-1000-5c5b350e0060"
CHANNEL = f"/sites/{SITE}/devices/{SWITCH}/cmd"
SESSION = str(uuid.uuid4())
TOKEN = "tok_" + "w" * 36
OUTPUT = ["64 bytes from 8.8.8.8: seq=1 ttl=58 time=12.3 ms", "64 bytes from 8.8.8.8: seq=2 ttl=58 time=12.1 ms"]


@dataclass
class Fakes:
    rest: Server
    handshakes: list[Headers] = field(default_factory=list)
    paths: list[str] = field(default_factory=list)
    received: list[str] = field(default_factory=list)
    subscribed: list[ServerConnection] = field(default_factory=list)


def answer(writer: asyncio.StreamWriter, status: int, body: Any = None) -> None:
    raw = json.dumps(body).encode() if body is not None else b""
    writer.write(f"HTTP/1.1 {status} X\r\ncontent-type: application/json\r\ncontent-length: {len(raw)}\r\n\r\n"
                 .encode() + raw)  # fmt: skip


async def _output(ws: ServerConnection) -> None:
    """What the device sends once Mist accepted the ping: its lines, and another command's, on the same channel."""
    await asyncio.sleep(0.05)
    for session, raw in [*((SESSION, line) for line in OUTPUT), ("other", "not ours")]:
        await ws.send(
            json.dumps({"event": "data", "channel": CHANNEL, "data": {"session": session, "raw": raw + "\n"}})
        )


@pytest.fixture
async def fakes(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Fakes]:
    monkeypatch.setattr(stream, "IDLE_S", 0.5)  # the collection ends half a second after the last line
    state: Fakes | None = None

    async def mist(request: Request, writer: asyncio.StreamWriter) -> None:
        assert state is not None
        path = request.target.split("?", 1)[0]
        if request.headers.get("authorization") != f"Token {TOKEN}":
            answer(writer, 401, {"detail": "unauthorized"})
        elif (request.method, path) == ("GET", f"/api/v1/sites/{SITE}"):
            answer(writer, 200, {"id": SITE, "org_id": ORG, "name": "Paris"})
        elif (request.method, path) == ("GET", f"/api/v1/sites/{SITE}/devices/{SWITCH}"):
            answer(writer, 200, {"id": SWITCH, "site_id": SITE, "type": "switch", "name": "sw-1"})
        elif (request.method, path) == ("POST", f"/api/v1/sites/{SITE}/devices/{SWITCH}/ping"):
            for ws in state.subscribed:
                asyncio.get_running_loop().create_task(_output(ws))
            answer(writer, 200, {"session": SESSION})
        elif (request.method, path) == ("POST", f"/api/v1/sites/{SITE}/devices/{SWITCH}/bounce_port"):
            answer(writer, 200)
        else:
            answer(writer, 404, {"detail": "not found"})
        await writer.drain()

    def handshake(conn: ServerConnection, request: WsRequest) -> WsResponse | None:
        assert state is not None
        state.handshakes.append(request.headers)
        state.paths.append(request.path)
        if request.headers.get("Authorization") != f"Token {TOKEN}":
            return WsResponse(401, "Unauthorized", Headers(), b"")
        return None

    async def channel(ws: ServerConnection) -> None:
        assert state is not None
        async for message in ws:
            state.received.append(str(message))
            if json.loads(message) == {"subscribe": CHANNEL}:
                await ws.send(json.dumps({"event": "channel_subscribed", "channel": CHANNEL}))
                state.subscribed.append(ws)

    async with serve_http(mist, tls_names=NAMES) as rest, serve(
        channel, "127.0.0.1", 0, ssl=tls(NAMES).server_context(), process_request=handshake
    ) as ws_server:  # fmt: skip
        state = Fakes(rest)
        ws_port = next(iter(ws_server.sockets)).getsockname()[1]
        connect_tcp, dial = httpcore.AnyIOBackend.connect_tcp, core_ws._dial

        async def rest_redirected(self: Any, host: str, port: int, *args: Any, **kwargs: Any) -> Any:
            return await connect_tcp(self, host, rest.port if (host, port) == ("127.0.0.1", 443) else port, *args,
                                     **kwargs)  # fmt: skip

        async def ws_redirected(address: str, port: int, timeout_s: float) -> Any:
            return await dial(address, ws_port if (address, port) == ("127.0.0.1", 443) else port, timeout_s)

        monkeypatch.setattr(httpcore.AnyIOBackend, "connect_tcp", rest_redirected)
        monkeypatch.setattr(core_ws, "_dial", ws_redirected)
        yield state


async def _published(owner: Any, api: Any, admin: Any, dispatch: Any, settings: Any) -> tuple[Any, uuid.UUID]:
    async with admin() as s, s.begin():
        await sync_installed(s, [FLOW, MIST])
    ctx = await actor(owner)
    cid = str(await add_connection(owner, ctx.tenant_id, type_key="mist", config={"cloud": "emea_01", "org_id": ORG},
                                   secret={"api_token": TOKEN}))  # fmt: skip
    device = {"connection": cid, "site_id": SITE, "device_id": SWITCH}
    g = G()
    ping = {**device, "body": {"host": "8.8.8.8", "count": 2}, "max_duration_s": 30}
    g.node("ping", "mist.site_devices.ping@1", ping)
    g.node("bounce", "mist.site_devices.bounce_port@1", {**device, "body": {"ports": ["ge-0/0/1"]}})
    g.edge("ping", "bounce")
    g.settings = {"outputs": {"lines": ref("steps.ping.output.lines"), "ended_by": ref("steps.ping.output.ended_by"),
                              "accepted": ref("steps.bounce.output.accepted"),
                              "known": ref("steps.bounce.output.completion_known")}}  # fmt: skip
    wf = await create(api, ctx, g.data())
    published = await publish(api, ctx, wf, settings)
    assert published.version is not None, published
    await current(dispatch)
    await ready_workers(owner)
    return ctx, wf


async def _run(env: Any, ctx: Any, wf: Any, dispatch: Any, worker: Any, settings: Any, *, simulate: bool) -> Any:
    loopback = AllowEntry(ipaddress.ip_network("127.0.0.1/32"), None, ctx.tenant_id)
    network = Network(
        guard=guard({HOST: ["127.0.0.1"], WS_HOST: ["127.0.0.1"]}, [loopback]),
        connections=DbConnections(worker),
        sessionmaker=worker,
        keys=KEYS,
        ssl_context=tls(NAMES).client_context(),
        types=worker_types([MIST]),
    )
    request = await dev_run.admit(dispatch, KEYS, tenant_id=ctx.tenant_id, workflow_id=wf, input={},
                                  simulate=simulate, idempotency_key=f"u-{simulate}")  # fmt: skip
    async with workers(env.client, DbRunStore(worker, KEYS), plugins=(MIST,), network=network):
        assert await dispatch_once(dispatch, env.client, KEYS, settings, BUILD) == {"started": 1}
        return request, await dev_run.wait_for_end(dispatch, ctx.tenant_id, request.id, within=90, poll=0.1)


async def test_a_ping_streams_its_output_and_a_bounce_is_accepted(
    env: WorkflowEnvironment, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker,
    worker_sessionmaker, api_settings, fakes,
) -> None:  # fmt: skip
    ctx, wf = await _published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker,
                               api_settings)  # fmt: skip
    request, ended = await _run(env, ctx, wf, dispatch_sessionmaker, worker_sessionmaker, api_settings, simulate=False)
    assert ended == dev_run.Ended("run", "succeeded", None, None), ended
    sent = [(r.method, r.target.split("?", 1)[0]) for r in fakes.rest.requests]
    device = f"/api/v1/sites/{SITE}/devices/{SWITCH}"
    assert sent == [
        ("GET", f"/api/v1/sites/{SITE}"), ("GET", device), ("POST", f"{device}/ping"),
        ("GET", f"/api/v1/sites/{SITE}"), ("GET", device), ("POST", f"{device}/bounce_port"),
    ]  # fmt: skip
    assert json.loads(fakes.rest.requests[2].body) == {"host": "8.8.8.8", "count": 2}
    assert json.loads(fakes.rest.requests[5].body) == {"ports": ["ge-0/0/1"]}
    assert fakes.paths == ["/api-ws/v1/stream"]  # one stream: the bounce opens none
    assert fakes.handshakes[0]["Authorization"] == f"Token {TOKEN}"
    assert fakes.received == [json.dumps({"subscribe": CHANNEL})]
    async with worker_sessionmaker() as s, s.begin():
        await tenant_scope(s, ctx.tenant_id)
        rows = (await s.execute(text("select node_key, output_preview::text, status from run_steps"))).all()
        scopes = [k for (k,) in (await s.execute(text("select scope from rate_buckets"))).all()]
    assert sorted((r[0], r[2]) for r in rows) == [("bounce", "succeeded"), ("ping", "succeeded")]
    assert all(TOKEN not in (r[1] or "") for r in rows)
    previews = {r[0]: json.loads(r[1]) for r in rows}
    assert previews["ping"] == {"accepted": True, "session": SESSION, "lines": OUTPUT, "received": 2,
                                "ended_by": "idle", "completion_known": False, "truncated": False}  # fmt: skip
    assert previews["bounce"] == {"accepted": True, "completion_known": False}
    assert sum(1 for k in scopes if k.startswith("mist.stream:")) == 1  # the opening charged the token's stream scope


async def test_a_simulated_utility_workflow_sends_nothing_and_opens_no_stream(
    env: WorkflowEnvironment, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker,
    worker_sessionmaker, api_settings, fakes,
) -> None:  # fmt: skip
    ctx, wf = await _published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker,
                               api_settings)  # fmt: skip
    _, ended = await _run(env, ctx, wf, dispatch_sessionmaker, worker_sessionmaker, api_settings, simulate=True)
    assert ended is not None and ended.status == "succeeded", ended
    assert fakes.rest.requests == [] and fakes.handshakes == []
