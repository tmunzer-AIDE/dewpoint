# SPDX-License-Identifier: Apache-2.0
"""A connection's stream (plugins-3 D4, D9, D10, D26), against a local wss server only: it opens only its type's
declared URL, with the credentials the runtime applies; each opening takes a token from the stream's quota scopes, and
a 429's `Retry-After` blocks them for every run; a simulated step and a plugin call open none; a message counts as a
send unless the node marks it a probe; and the attempt closes its streams."""

import dataclasses
import ipaddress
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import text
from websockets.asyncio.server import ServerConnection, serve
from websockets.datastructures import Headers
from websockets.http11 import Request, Response

from dewpoint.apps.worker import network as network_module
from dewpoint.apps.worker.network import DbConnections, Network, worker_types
from dewpoint.apps.worker.plugin_calls import CallNetwork
from dewpoint.apps.worker.store import DbRunStore
from dewpoint.core.db import tenant_scope
from dewpoint.core.egress import ws as core_ws
from dewpoint.core.egress.addresses import AllowEntry
from dewpoint.core.plugins import calls
from dewpoint.core.ratelimit.buckets import current_cooldowns
from dewpoint.sdk import (
    Cooldown,
    HandshakeRejected,
    InvalidRequest,
    ReadOnly,
    SimulationSendsNothing,
    StreamLost,
)
from tests.support.connections import add_connection, seed_step
from tests.support.keys import FixtureKeys
from tests.support.netfakes import guard, tls
from tests.support.plugins.streamkit import (
    STREAM_HOST,
    STREAMKIT,
    AmbiguousStreamCall,
    StreamCall,
)

TOKEN = "s3cr3t-stream-token"


@dataclass
class Seen:
    headers: list[Headers] = field(default_factory=list)
    paths: list[str] = field(default_factory=list)
    received: list[str] = field(default_factory=list)


async def echo(ws: ServerConnection, seen: Seen) -> None:
    async for message in ws:
        seen.received.append(str(message))
        await ws.send(f"echo:{message!s}")


@asynccontextmanager
async def stream_server(
    monkeypatch: pytest.MonkeyPatch, *, status: Response | None = None, session: Any = echo
) -> AsyncIterator[Seen]:
    """A wss server for the stream host; the vetted address's port 443 is redirected to it in this test only."""
    seen = Seen()

    def process_request(conn: ServerConnection, request: Request) -> Response | None:
        seen.headers.append(request.headers)
        seen.paths.append(request.path)
        return status

    async def handler(ws: ServerConnection) -> None:
        try:
            await session(ws, seen)
        except Exception:  # noqa: BLE001, S110 - a client gone mid-session
            pass

    async with serve(handler, "127.0.0.1", 0, ssl=tls((STREAM_HOST,)).server_context(),
                     process_request=process_request) as server:  # fmt: skip
        port = next(iter(server.sockets)).getsockname()[1]
        dial = core_ws._dial

        async def redirected(address: str, to: int, timeout_s: float) -> Any:
            return await dial(address, port if (address, to) == ("127.0.0.1", 443) else to, timeout_s)

        monkeypatch.setattr(core_ws, "_dial", redirected)
        yield seen


def network(worker: Any, tenant: uuid.UUID, *, scope_capacity: float | None = None) -> Network:
    plugin = STREAMKIT
    if scope_capacity is not None:
        kind = plugin.connection_types[0]
        assert kind.stream is not None
        scope = dataclasses.replace(kind.stream.rate_scopes[0], capacity=scope_capacity, refill_per_s=0.001)
        stream = dataclasses.replace(kind.stream, rate_scopes=(scope,))
        plugin = dataclasses.replace(plugin, connection_types=(dataclasses.replace(kind, stream=stream),
                                                                plugin.connection_types[1]))  # fmt: skip
    loopback = AllowEntry(ipaddress.ip_network("127.0.0.1/32"), None, tenant)
    return Network(
        guard=guard({STREAM_HOST: ["127.0.0.1"]}, [loopback]),
        connections=DbConnections(worker),
        sessionmaker=worker,
        keys=FixtureKeys(),
        ssl_context=tls((STREAM_HOST,)).client_context(),
        types=worker_types([plugin]),
    )


async def _setup(owner: Any, node: type = StreamCall, type_key: str = "streamkit") -> tuple[Any, uuid.UUID]:
    tenant = uuid.uuid4()
    await seed_step(owner, named=[None], tenant=tenant)
    cid = await add_connection(owner, tenant, type_key=type_key, config={"region": "local"}, secret={"token": TOKEN})
    return await seed_step(owner, named=[cid], tenant=tenant, node_type=f"{node.type}@1"), cid


def attempt(
    worker: Any, seeded: Any, node: type = StreamCall, simulated: bool = False, beat: Any = None, **kw: Any
) -> Any:
    store = DbRunStore(worker, FixtureKeys())
    return network(worker, seeded.tenant, **kw).attempt(
        tenant_id=seeded.tenant, run_id=seeded.run, step_id=seeded.step, root_run_id=seeded.run, node=node,
        simulated=simulated, remember=store.remember, beat=beat or (lambda: None),
    )  # fmt: skip


async def test_the_stream_is_the_types_url_with_the_runtimes_credentials(
    owner_sessionmaker, worker_sessionmaker, monkeypatch
) -> None:
    async with stream_server(monkeypatch) as seen:
        seeded, cid = await _setup(owner_sessionmaker)
        a = attempt(worker_sessionmaker, seeded)
        try:
            stream = await (await a.connection(cid)).ws.connect()
            await stream.send('{"subscribe": "/x"}', probe=True)
            assert await stream.receive(5) == 'echo:{"subscribe": "/x"}'
        finally:
            await a.aclose()
    assert seen.paths == ["/v1/stream"]
    assert seen.headers[0]["Authorization"] == f"Bearer {TOKEN}"
    assert seen.headers[0]["Host"] == STREAM_HOST


async def test_each_opening_takes_a_stream_token_or_cools_down_having_connected_nowhere(
    owner_sessionmaker, worker_sessionmaker, monkeypatch
) -> None:
    async with stream_server(monkeypatch) as seen:
        seeded, cid = await _setup(owner_sessionmaker)
        a = attempt(worker_sessionmaker, seeded, scope_capacity=1)
        try:
            conn = await a.connection(cid)
            await conn.ws.connect()
            with pytest.raises(Cooldown):
                await conn.ws.connect()
        finally:
            await a.aclose()
    assert len(seen.paths) == 1


async def test_a_429_blocks_the_stream_scope_for_every_run(
    owner_sessionmaker, worker_sessionmaker, monkeypatch
) -> None:
    limited = Response(429, "Too Many", Headers([("Retry-After", "120")]), b"")
    async with stream_server(monkeypatch, status=limited) as seen:
        seeded, cid = await _setup(owner_sessionmaker)
        a = attempt(worker_sessionmaker, seeded)
        try:
            with pytest.raises(HandshakeRejected) as raised:
                await (await a.connection(cid)).ws.connect()
        finally:
            await a.aclose()
        b = attempt(worker_sessionmaker, seeded)
        try:
            with pytest.raises(Cooldown):
                await (await b.connection(cid)).ws.connect()
        finally:
            await b.aclose()
    assert raised.value.status == 429
    assert len(seen.paths) == 1
    async with worker_sessionmaker() as s, s.begin():
        await tenant_scope(s, seeded.tenant)
        keys = [k for (k,) in (await s.execute(text("select scope from rate_buckets"))).all()]
        found = await current_cooldowns(s, seeded.tenant, keys)
    assert [k.split(":", 1)[0] for k in found] == ["streamkit.stream"]
    until = next(iter(found.values()))
    assert timedelta(seconds=100) < until - datetime.now(UTC) <= timedelta(seconds=125)


@pytest.mark.parametrize("status", [401, 403, 503])
async def test_a_refused_handshake_names_its_status(
    owner_sessionmaker, worker_sessionmaker, monkeypatch, status: int
) -> None:
    async with stream_server(monkeypatch, status=Response(status, "No", Headers(), b"")):
        seeded, cid = await _setup(owner_sessionmaker)
        a = attempt(worker_sessionmaker, seeded)
        try:
            with pytest.raises(HandshakeRejected) as raised:
                await (await a.connection(cid)).ws.connect()
        finally:
            await a.aclose()
    assert raised.value.status == status
    assert not a.may_have_sent


async def test_a_type_without_a_stream_opens_none(owner_sessionmaker, worker_sessionmaker, monkeypatch) -> None:
    async with stream_server(monkeypatch) as seen:
        seeded, cid = await _setup(owner_sessionmaker, type_key="streamkit.plain")
        a = attempt(worker_sessionmaker, seeded)
        try:
            with pytest.raises(InvalidRequest):
                await (await a.connection(cid)).ws.connect()
        finally:
            await a.aclose()
    assert seen.paths == []


async def test_a_simulated_step_opens_no_stream(owner_sessionmaker, worker_sessionmaker) -> None:
    seeded, cid = await _setup(owner_sessionmaker)
    a = attempt(worker_sessionmaker, seeded, simulated=True)
    try:
        with pytest.raises(SimulationSendsNothing):
            await a.connection(cid)
    finally:
        await a.aclose()


async def test_a_plugin_call_opens_no_stream(owner_sessionmaker, worker_sessionmaker, monkeypatch) -> None:
    async with stream_server(monkeypatch) as seen:
        seeded, cid = await _setup(owner_sessionmaker)
        now = datetime.now(UTC)
        stored = await DbConnections(worker_sessionmaker).load(seeded.tenant, cid)
        assert stored is not None
        claimed = calls.Claimed(uuid.uuid4(), seeded.tenant, "options", None, None, "streamkit", cid, stored.revision,
                                "", uuid.uuid4(), now + timedelta(minutes=1), now + timedelta(minutes=1))  # fmt: skip
        net = CallNetwork(network(worker_sessionmaker, seeded.tenant), claimed, frozenset({"streamkit"}))
        try:
            with pytest.raises(ReadOnly):
                await (await net.connection(cid)).ws.connect()
        finally:
            await net.aclose()
    assert seen.paths == []


async def test_a_probe_leaves_the_attempt_as_it_was_and_a_message_marks_it(
    owner_sessionmaker, worker_sessionmaker, monkeypatch
) -> None:
    async with stream_server(monkeypatch):
        seeded, cid = await _setup(owner_sessionmaker, node=AmbiguousStreamCall)
        a = attempt(worker_sessionmaker, seeded, node=AmbiguousStreamCall)
        try:
            stream = await (await a.connection(cid)).ws.connect()
            assert not a.may_have_sent  # opening sends nothing a node answers for
            await stream.send("subscribe", probe=True)
            assert await stream.receive(5) == "echo:subscribe"
            assert not a.may_have_sent
            await stream.send("act")
            assert a.may_have_sent
        finally:
            await a.aclose()


async def test_a_message_lost_with_its_stream_may_have_been_sent(
    owner_sessionmaker, worker_sessionmaker, monkeypatch
) -> None:
    async def closing(ws: ServerConnection, seen: Seen) -> None:
        await ws.recv()
        await ws.close()

    async with stream_server(monkeypatch, session=closing):
        seeded, cid = await _setup(owner_sessionmaker, node=AmbiguousStreamCall)
        a = attempt(worker_sessionmaker, seeded, node=AmbiguousStreamCall)
        try:
            stream = await (await a.connection(cid)).ws.connect()
            await stream.send("first", probe=True)
            with pytest.raises(StreamLost):
                await stream.receive(5)
            assert not a.may_have_sent
            with pytest.raises(StreamLost):
                await stream.send("act")
            assert a.may_have_sent
        finally:
            await a.aclose()


async def test_the_attempt_closes_its_streams(owner_sessionmaker, worker_sessionmaker, monkeypatch) -> None:
    async with stream_server(monkeypatch):
        seeded, cid = await _setup(owner_sessionmaker)
        a = attempt(worker_sessionmaker, seeded)
        stream = await (await a.connection(cid)).ws.connect()
        await a.aclose()
        with pytest.raises(StreamLost):
            await stream.receive(1)


async def test_a_long_receive_heartbeats_while_it_waits(owner_sessionmaker, worker_sessionmaker, monkeypatch) -> None:
    """Review L7 (D26: the attempt heartbeats while it reads): a receive waits in slices, beating between them, so a
    cancel reaches a node however long it asked to wait."""
    monkeypatch.setattr(network_module, "RECEIVE_BEAT_S", 0.1)
    beats: list[int] = []
    async with stream_server(monkeypatch):
        seeded, cid = await _setup(owner_sessionmaker)
        a = attempt(worker_sessionmaker, seeded, beat=lambda: beats.append(1))
        try:
            stream = await (await a.connection(cid)).ws.connect()
            beats.clear()  # the opening's own
            assert await stream.receive(0.45) is None
            with pytest.raises(InvalidRequest):
                await stream.receive("5")  # type: ignore[arg-type]
        finally:
            await a.aclose()
    assert len(beats) >= 3
