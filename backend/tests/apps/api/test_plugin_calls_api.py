# SPDX-License-Identifier: Apache-2.0
"""The API asks the worker (plugins-3 D3): a node's options for the editor, and a connection's verification. The API
runs no plugin code and sends nothing itself: it records a call, waits up to its deadline for a worker's answer, then
deletes the call. A verification is applied only to the revision it verified."""

import asyncio
import ipaddress
import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
from sqlalchemy import text

from dewpoint.apps.codec import KeyringKeys
from dewpoint.apps.plugin_loader import sync_installed
from dewpoint.apps.worker.network import DbConnections, Network
from dewpoint.apps.worker.plugin_calls import PluginCallServer
from dewpoint.core.crypto.kek import KekSet
from dewpoint.core.crypto.keyring import Keyring
from dewpoint.core.egress.addresses import AllowEntry
from dewpoint.core.plugins import asking
from dewpoint.plugins.flow import PLUGIN as FLOW
from dewpoint.plugins.mist import PLUGIN as MIST
from tests.apps.api.helpers import session_client
from tests.support.connections import types_for_testkit
from tests.support.netfakes import Request, Server, guard, serve, tls
from tests.support.plugins.testkit import TESTKIT

NAMES = ("dewpoint.test",)
SITES = [{"id": "s1", "name": "Site 1"}]


class Fake:
    """The connection's service: `/sites` lists sites, `/verify` answers once `release` is set."""

    def __init__(self) -> None:
        self.started, self.release = asyncio.Event(), asyncio.Event()
        self.release.set()

    async def __call__(self, request: Request, writer: asyncio.StreamWriter) -> None:
        if request.target == "/verify":
            self.started.set()
            await self.release.wait()
            body = b"{}"
        else:
            body = json.dumps(SITES).encode()
        writer.write(f"HTTP/1.1 200 X\r\ncontent-length: {len(body)}\r\n\r\n".encode() + body)
        await writer.drain()


@pytest.fixture
async def fake() -> AsyncIterator[tuple[Fake, Server]]:
    handler = Fake()
    async with serve(handler, tls_names=NAMES) as server:
        yield handler, server
        handler.release.set()


@pytest.fixture
async def worker(
    worker_sessionmaker: Any, owner_sessionmaker: Any, api_settings: Any
) -> AsyncIterator[PluginCallServer]:
    """A worker serving plugin calls for every tenant, with the API's keyring, reaching only the local fake."""
    async with owner_sessionmaker() as s, s.begin():
        await sync_installed(s, [FLOW, TESTKIT, MIST])
    network = Network(
        guard=guard({"dewpoint.test": ["127.0.0.1"]}, [AllowEntry(ipaddress.ip_network("127.0.0.1/32"), None, None)]),
        connections=DbConnections(worker_sessionmaker),
        sessionmaker=worker_sessionmaker,
        keys=KeyringKeys(worker_sessionmaker, Keyring(KekSet.from_settings(api_settings))),
        ssl_context=tls(NAMES).client_context(),
        types=types_for_testkit(),
    )
    server = PluginCallServer(worker_sessionmaker, network, [TESTKIT], poll_s=0.05)
    running = asyncio.create_task(server.run())
    yield server
    server.stop()
    await asyncio.wait_for(running, 10)


@pytest.fixture
async def unserved(owner_sessionmaker: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """The plugins are synced but no worker serves calls: a call the API should have refused would time out."""
    monkeypatch.setattr(asking, "WAIT_S", 0.3)
    async with owner_sessionmaker() as s, s.begin():
        await sync_installed(s, [FLOW, TESTKIT, MIST])


async def _connection(c: Any, tid: Any, port: int, name: str = "Kit") -> str:
    body = {"type": "testkit", "name": name, "config": {"base_url": f"https://dewpoint.test:{port}"},
            "secret": {"token": "s3cr3t-token-value"}}  # fmt: skip
    r = await c.post(f"/api/v1/t/{tid}/connections", json=body)
    assert r.status_code == 201, r.text
    return str(r.json()["id"])


async def _calls_left(owner: Any) -> int:
    async with owner() as s:
        return int((await s.execute(text("select count(*) from plugin_calls"))).scalar_one())


def _options(tid: Any, ref: str = "testkit.pick@1") -> str:
    return f"/api/v1/t/{tid}/node-types/{ref}/options"


async def test_an_editor_gets_a_nodes_options_through_the_worker(
    app, owner_sessionmaker, api_settings, worker, fake
) -> None:
    c, tid = await session_client(app, owner_sessionmaker, api_settings, "admin")
    async with c:
        cid = await _connection(c, tid, fake[1].port)
        async with owner_sessionmaker() as s, s.begin():  # the same person, now an editor
            await s.execute(text("update memberships set role = 'editor' where tenant_id = :t"), {"t": tid})
        r = await c.post(_options(tid), json={"field": "site_id", "connection_id": cid, "query": "si"})
    assert r.status_code == 200, r.text
    assert r.json() == {"options": [{"value": "s1", "label": "Site 1"}]}
    assert fake[1].requests[0].target == "/sites?q=si"
    assert await _calls_left(owner_sessionmaker) == 0


async def test_the_palette_shows_icons_and_options_fields(app, owner_sessionmaker, api_settings, worker) -> None:
    c, _ = await session_client(app, owner_sessionmaker, api_settings, "viewer")
    async with c:
        listed = {n["ref"]: n for n in (await c.get("/api/v1/node-types")).json()}
    assert (listed["testkit.pick@1"]["icon"], listed["testkit.pick@1"]["options"]) == ("map-pin", ["site_id"])
    assert (listed["testkit.http_call@1"]["icon"], listed["testkit.http_call@1"]["options"]) == (None, [])


async def test_an_operator_may_not_ask_for_options(app, owner_sessionmaker, api_settings, unserved) -> None:
    c, tid = await session_client(app, owner_sessionmaker, api_settings, "operator")
    async with c:
        r = await c.post(_options(tid), json={"field": "site_id", "connection_id": None, "query": ""})
    assert r.status_code == 403


@pytest.mark.parametrize(
    ("ref", "field", "status", "error"),
    [
        ("testkit.nothing@1", "site_id", 404, "unknown_node_type"),
        ("testkit.pick@1", "note", 422, "not_an_options_field"),
    ],
)
async def test_options_only_for_a_known_nodes_options_field(
    app, owner_sessionmaker, api_settings, unserved, ref: str, field: str, status: int, error: str
) -> None:
    c, tid = await session_client(app, owner_sessionmaker, api_settings, "editor")
    async with c:
        r = await c.post(_options(tid, ref), json={"field": field, "connection_id": None, "query": ""})
    assert (r.status_code, r.json()) == (status, {"error": error})
    assert await _calls_left(owner_sessionmaker) == 0


async def test_options_only_through_a_connection_the_node_may_use(
    app, owner_sessionmaker, api_settings, unserved
) -> None:
    c, tid = await session_client(app, owner_sessionmaker, api_settings, "admin")
    async with c:
        mist = {"type": "mist", "name": "M", "config": {"cloud": "emea_01", "org_id": str(uuid.uuid4())},
                "secret": {"api_token": "tok_" + "a" * 36}}  # fmt: skip
        mist_id = (await c.post(f"/api/v1/t/{tid}/connections", json=mist)).json()["id"]
        other_type = await c.post(_options(tid), json={"field": "site_id", "connection_id": mist_id, "query": ""})
        missing = await c.post(
            _options(tid), json={"field": "site_id", "connection_id": str(uuid.uuid4()), "query": ""}
        )
    for r in (other_type, missing):
        assert (r.status_code, r.json()) == (422, {"error": "connection_unavailable"})
    assert await _calls_left(owner_sessionmaker) == 0


async def test_a_failed_call_shows_its_code(app, owner_sessionmaker, api_settings, worker, fake) -> None:
    c, tid = await session_client(app, owner_sessionmaker, api_settings, "admin")
    async with c:
        cid = await _connection(c, tid, fake[1].port)
        r = await c.post(_options(tid), json={"field": "site_id", "connection_id": cid, "query": "post"})
    assert (r.status_code, r.json()) == (502, {"error": "read_only"})
    assert fake[1].requests == []


async def test_no_answer_in_time_is_a_timeout_and_the_call_is_gone(
    app, owner_sessionmaker, api_settings, unserved, fake
) -> None:
    c, tid = await session_client(app, owner_sessionmaker, api_settings, "admin")
    async with c:
        cid = await _connection(c, tid, fake[1].port)
        r = await c.post(_options(tid), json={"field": "site_id", "connection_id": cid, "query": ""})
    assert (r.status_code, r.json()) == (504, {"error": "plugin_call_timeout"})
    assert await _calls_left(owner_sessionmaker) == 0


async def test_verify_goes_through_the_worker(app, owner_sessionmaker, api_settings, worker, fake) -> None:
    c, tid = await session_client(app, owner_sessionmaker, api_settings, "admin")
    async with c:
        cid = await _connection(c, tid, fake[1].port)
        r = await c.post(f"/api/v1/t/{tid}/connections/{cid}/verify")
        actions = [e["action"] for e in (await c.get(f"/api/v1/t/{tid}/audit")).json()]
    assert r.status_code == 200 and (r.json()["status"], r.json()["status_detail"]) == ("ok", "ok")
    assert [(q.method, q.target) for q in fake[1].requests] == [("GET", "/verify")]
    assert actions[:2] == ["connection.verify", "connection.create"]
    assert await _calls_left(owner_sessionmaker) == 0


async def test_an_unanswered_verification_changes_nothing(
    app, owner_sessionmaker, api_settings, unserved, fake
) -> None:
    c, tid = await session_client(app, owner_sessionmaker, api_settings, "admin")
    async with c:
        cid = await _connection(c, tid, fake[1].port)
        r = await c.post(f"/api/v1/t/{tid}/connections/{cid}/verify")
        after = (await c.get(f"/api/v1/t/{tid}/connections/{cid}")).json()
    assert (r.status_code, r.json()) == (504, {"error": "plugin_call_timeout"})
    assert after["status"] == "unverified"


async def _held_verify(c: Any, tid: Any, cid: str, fake: tuple[Fake, Server], during: Any) -> tuple[Any, Any]:
    handler = fake[0]
    handler.release.clear()
    verify = asyncio.create_task(c.post(f"/api/v1/t/{tid}/connections/{cid}/verify"))
    try:
        await asyncio.wait_for(handler.started.wait(), 10)  # the worker loaded revision 1 and is asking the service
        done = await during()
    finally:
        handler.release.set()  # never leave the held request hanging
        r = await asyncio.wait_for(verify, 15)
    return r, done


async def test_verification_does_not_certify_credentials_edited_in_flight(
    app, owner_sessionmaker, api_settings, worker, fake
) -> None:
    c, tid = await session_client(app, owner_sessionmaker, api_settings, "admin")
    async with c:
        cid = await _connection(c, tid, fake[1].port)
        r, edited = await _held_verify(c, tid, cid, fake, lambda: c.patch(
            f"/api/v1/t/{tid}/connections/{cid}", json={"secret": {"token": "an-0ther-token-value"}}))  # fmt: skip
        after = (await c.get(f"/api/v1/t/{tid}/connections/{cid}")).json()
        actions = [e["action"] for e in (await c.get(f"/api/v1/t/{tid}/audit")).json()]
    assert edited.status_code == 200 and edited.json()["revision"] == 2
    assert r.status_code == 409 and r.json() == {"error": "changed_during_verification"}
    assert after["status"] == "unverified" and after["revision"] == 2
    assert actions[0] == "connection.verify_discarded"


async def test_rename_during_verification_keeps_the_result(app, owner_sessionmaker, api_settings, worker, fake) -> None:
    c, tid = await session_client(app, owner_sessionmaker, api_settings, "admin")
    async with c:
        cid = await _connection(c, tid, fake[1].port)
        r, _ = await _held_verify(c, tid, cid, fake, lambda: c.patch(
            f"/api/v1/t/{tid}/connections/{cid}", json={"name": "Renamed"}))  # fmt: skip
    assert r.status_code == 200 and r.json()["status"] == "ok" and r.json()["name"] == "Renamed"


async def test_delete_during_verification_is_not_found(app, owner_sessionmaker, api_settings, worker, fake) -> None:
    c, tid = await session_client(app, owner_sessionmaker, api_settings, "admin")
    async with c:
        cid = await _connection(c, tid, fake[1].port)
        r, deleted = await _held_verify(c, tid, cid, fake, lambda: c.delete(f"/api/v1/t/{tid}/connections/{cid}"))
        actions = [e["action"] for e in (await c.get(f"/api/v1/t/{tid}/audit")).json()]
    assert deleted.status_code == 204
    assert r.status_code == 404 and r.json() == {"error": "not_found"}
    assert actions[0] == "connection.verify_discarded"


async def test_a_verification_whose_call_vanished_records_nothing(
    app, owner_sessionmaker, api_settings, worker, fake
) -> None:
    c, tid = await session_client(app, owner_sessionmaker, api_settings, "admin")

    async def vanish() -> None:
        async with owner_sessionmaker() as s, s.begin():
            await s.execute(text("delete from plugin_calls"))

    async with c:
        cid = await _connection(c, tid, fake[1].port)
        r, _ = await _held_verify(c, tid, cid, fake, vanish)
        after = (await c.get(f"/api/v1/t/{tid}/connections/{cid}")).json()
    assert r.status_code == 409 and r.json() == {"error": "changed_during_verification"}
    assert after["status"] == "unverified"
