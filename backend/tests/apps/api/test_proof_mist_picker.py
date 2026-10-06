# SPDX-License-Identifier: Apache-2.0
"""3a-2's proof (plugins-3 D3, D11, D19), end to end against a local Mist fake: a Mist connection created through the
API from the synced `mist` plugin's declaration; verified by the mist plugin's `verify()` on a worker; a node's site
picker and a start form's picker listing the org's sites through it. The API sends nothing itself; the worker reaches
`api.eu.mist.com` through the guard (vetted, pinned, TLS checked against that name), the fake standing in for it on
loopback, its port 443 redirected in the test's socket layer only."""

import asyncio
import ipaddress
import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpcore
import pytest
from sqlalchemy import text

from dewpoint.apps.codec import KeyringKeys
from dewpoint.apps.plugin_loader import sync_installed
from dewpoint.apps.worker.network import DbConnections, Network, worker_types
from dewpoint.apps.worker.plugin_calls import PluginCallServer
from dewpoint.core.crypto.kek import KekSet
from dewpoint.core.crypto.keyring import Keyring
from dewpoint.core.egress.addresses import AllowEntry
from dewpoint.plugins.flow import PLUGIN as FLOW
from dewpoint.plugins.mist import PLUGIN as MIST
from tests.apps.api.helpers import session_client
from tests.support.graphs import G
from tests.support.netfakes import Request, Server, guard, serve, tls
from tests.support.plugins.testkit import TESTKIT

HOST = "api.eu.mist.com"
ORG = str(uuid.uuid4())
TOKEN = "tok_" + "m" * 36
SITES = [{"id": str(uuid.uuid4()), "name": "Paris"}, {"id": str(uuid.uuid4()), "name": "Lyon"}]


async def mist(request: Request, writer: asyncio.StreamWriter) -> None:
    """Mist as far as this proof needs it: `/self` and the org's sites, for this token only."""
    if request.headers.get("authorization") != f"Token {TOKEN}":
        status, body = 401, {"detail": "unauthorized"}
    elif request.target == "/api/v1/self":
        status, body = 200, {"privileges": [{"scope": "org", "org_id": ORG, "role": "admin"}]}
    elif request.target.startswith(f"/api/v1/orgs/{ORG}/sites"):
        status, body = 200, SITES
    else:
        status, body = 404, {"detail": "not found"}
    raw = json.dumps(body).encode()
    writer.write(f"HTTP/1.1 {status} X\r\ncontent-type: application/json\r\ncontent-length: {len(raw)}\r\n\r\n".encode()
                 + raw)  # fmt: skip
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


@pytest.fixture
async def worker(worker_sessionmaker: Any, owner_sessionmaker: Any, api_settings: Any) -> AsyncIterator[None]:
    async with owner_sessionmaker() as s, s.begin():
        await sync_installed(s, [FLOW, TESTKIT, MIST])
    network = Network(
        guard=guard({HOST: ["127.0.0.1"]}, [AllowEntry(ipaddress.ip_network("127.0.0.1/32"), None, None)]),
        connections=DbConnections(worker_sessionmaker),
        sessionmaker=worker_sessionmaker,
        keys=KeyringKeys(worker_sessionmaker, Keyring(KekSet.from_settings(api_settings))),
        ssl_context=tls((HOST,)).client_context(),
        types=worker_types([MIST]),
    )
    server = PluginCallServer(worker_sessionmaker, network, [TESTKIT], poll_s=0.05)
    running = asyncio.create_task(server.run())
    yield
    server.stop()
    await asyncio.wait_for(running, 10)


async def test_a_mist_connection_is_verified_and_lists_its_sites_end_to_end(
    app, owner_sessionmaker, api_settings, worker, fake_mist
) -> None:
    c, tid = await session_client(app, owner_sessionmaker, api_settings, "admin")
    async with c:
        body = {"type": "mist", "name": "Acme", "config": {"cloud": "emea_01", "org_id": ORG},
                "secret": {"api_token": TOKEN}}  # fmt: skip
        made = await c.post(f"/api/v1/t/{tid}/connections", json=body)
        assert made.status_code == 201, made.text
        cid = made.json()["id"]
        verified = await c.post(f"/api/v1/t/{tid}/connections/{cid}/verify")
        options = await c.post(f"/api/v1/t/{tid}/node-types/testkit.mist_sites@1/options",
                               json={"field": "site_id", "connection_id": cid, "query": "par"})  # fmt: skip

        g = G().node("e", "testkit.echo@1")
        picker = {"node": "testkit.mist_sites@1", "field": "site_id", "connection": cid}
        site = {"type": "string", "x-dewpoint-picker": picker}
        g.settings = {"input_schema": {"type": "object", "properties": {"site": site}}}
        wf = await c.post(f"/api/v1/t/{tid}/workflows", json={"name": "Site report", "draft": g.data()})
        published = await c.post(f"/api/v1/t/{tid}/workflows/{wf.json()['id']}/publish",
                                 headers={"If-Match": str(wf.json()["draft_revision"])})  # fmt: skip
        assert published.status_code == 201, published.text
        start_form = await c.post(f"/api/v1/t/{tid}/workflows/{wf.json()['id']}/input-options",
                                  json={"field": "site", "query": ""})  # fmt: skip
    assert verified.status_code == 200
    assert (verified.json()["status"], verified.json()["privilege"]) == ("ok", "admin")
    assert options.json() == {"options": [{"value": SITES[0]["id"], "label": "Paris"}]}
    assert start_form.json() == {"options": [{"value": s["id"], "label": s["name"]} for s in SITES]}
    assert [r.target.split("?")[0] for r in fake_mist.requests] == [
        "/api/v1/self",
        f"/api/v1/orgs/{ORG}/sites",
        f"/api/v1/orgs/{ORG}/sites",
    ]
    async with owner_sessionmaker() as s:
        assert (await s.execute(text("select count(*) from plugin_calls"))).scalar_one() == 0
