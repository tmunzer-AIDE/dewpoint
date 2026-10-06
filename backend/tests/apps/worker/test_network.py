# SPDX-License-Identifier: Apache-2.0
"""A step attempt's network (plugins-3 D4, D5, D7, D9, D10), against local servers only: a step opens only the
connections its own node names in its run's version, of a type the node declares; the runtime decrypts the secret per
call, indexes it before anything is sent, and applies it; credentials and origin can't be changed by the plugin; the
quota scopes give tokens or a cooldown; a provider's `Retry-After` is honoured per the node's side effect."""

import asyncio
import ipaddress
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import text

from dewpoint.apps.worker.network import DbConnections, Network
from dewpoint.apps.worker.store import DbRunStore
from dewpoint.core.connections.types import CONNECTION_TYPES
from dewpoint.core.db import tenant_scope
from dewpoint.core.egress.addresses import AllowEntry
from dewpoint.core.ratelimit.buckets import current_cooldowns
from dewpoint.sdk import (
    ConnectionUnavailable,
    Cooldown,
    InvalidRequest,
    RateLimited,
    SimulationSendsNothing,
)
from tests.support.connections import TESTKIT_TYPE, add_connection, seal, seed_step
from tests.support.keys import FixtureKeys
from tests.support.netfakes import Request, guard, respond, serve, tls
from tests.support.plugins.testkit import AmbiguousCall, HttpCall

NAMES = ("dewpoint.test",)


@pytest.fixture(autouse=True)
def testkit_type(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(CONNECTION_TYPES, "testkit", TESTKIT_TYPE)


def network(worker: Any, tenant: uuid.UUID, keys: FixtureKeys | None = None) -> Network:
    loopback = AllowEntry(ipaddress.ip_network("127.0.0.1/32"), None, tenant)
    return Network(
        guard=guard({"dewpoint.test": ["127.0.0.1"]}, [loopback]),
        connections=DbConnections(worker),
        sessionmaker=worker,
        keys=keys or FixtureKeys(),
        ssl_context=tls(NAMES).client_context(),
    )


def attempt(
    worker: Any, seeded: Any, node: type = HttpCall, simulated: bool = False, keys: FixtureKeys | None = None
) -> Any:
    store = DbRunStore(worker, FixtureKeys())
    return network(worker, seeded.tenant, keys).attempt(
        tenant_id=seeded.tenant, run_id=seeded.run, step_id=seeded.step, root_run_id=seeded.run, node=node,
        simulated=simulated, remember=store.remember, beat=lambda: None,
    )  # fmt: skip


async def _setup(owner: Any, port: int, node_type: str = "testkit.http_call@1", **config: Any) -> tuple[Any, uuid.UUID]:
    tenant = uuid.uuid4()
    await seed_step(owner, named=[None], tenant=tenant)  # creates the tenant
    cid = await add_connection(owner, tenant, config={"base_url": f"https://dewpoint.test:{port}", **config})
    return await seed_step(owner, named=[cid], tenant=tenant, node_type=node_type), cid


async def test_the_runtime_applies_the_connections_auth(owner_sessionmaker, worker_sessionmaker) -> None:
    async with serve(respond(200, b"hi"), tls_names=NAMES) as server:
        seeded, cid = await _setup(owner_sessionmaker, server.port)
        a = attempt(worker_sessionmaker, seeded)
        try:
            answer = await (await a.connection(cid)).http.request("GET", "/api/v1/self")
        finally:
            await a.aclose()
    assert (answer.status_code, answer.content) == (200, b"hi")
    assert server.requests[0].headers["authorization"] == "Bearer s3cr3t-token-value"
    assert server.requests[0].target == "/api/v1/self"


async def test_the_secret_is_indexed_before_anything_is_sent(owner_sessionmaker, worker_sessionmaker) -> None:
    seeded, cid = await _setup(owner_sessionmaker, 9)
    a = attempt(worker_sessionmaker, seeded)
    try:
        await a.connection(cid)
    finally:
        await a.aclose()
    index = await DbRunStore(worker_sessionmaker, FixtureKeys()).index(str(seeded.tenant), str(seeded.run))
    assert "s3cr3t-token-value" in index.strings


async def test_only_the_connections_this_step_names(owner_sessionmaker, worker_sessionmaker) -> None:
    tenant = uuid.uuid4()
    await seed_step(owner_sessionmaker, named=[None], tenant=tenant)
    mine = await add_connection(owner_sessionmaker, tenant, config={"base_url": "https://dewpoint.test:9"})
    sibling = await add_connection(owner_sessionmaker, tenant, config={"base_url": "https://dewpoint.test:9"})
    seeded = await seed_step(owner_sessionmaker, named=[mine, sibling], tenant=tenant)
    a = attempt(worker_sessionmaker, seeded)
    try:
        await a.connection(mine)
        for other in (sibling, uuid.uuid4()):
            with pytest.raises(ConnectionUnavailable):
                await a.connection(other)
    finally:
        await a.aclose()


async def test_a_name_the_version_didnt_record_is_refused(owner_sessionmaker, worker_sessionmaker) -> None:
    tenant = uuid.uuid4()
    await seed_step(owner_sessionmaker, named=[None], tenant=tenant)
    cid = await add_connection(owner_sessionmaker, tenant, config={"base_url": "https://dewpoint.test:9"})
    seeded = await seed_step(owner_sessionmaker, named=[cid], recorded=[], tenant=tenant)
    a = attempt(worker_sessionmaker, seeded)
    try:
        with pytest.raises(ConnectionUnavailable):
            await a.connection(cid)
    finally:
        await a.aclose()


async def test_a_type_the_node_doesnt_declare_is_refused(owner_sessionmaker, worker_sessionmaker) -> None:
    tenant = uuid.uuid4()
    await seed_step(owner_sessionmaker, named=[None], tenant=tenant)
    cid = await add_connection(owner_sessionmaker, tenant, type_key="mist", config={})
    seeded = await seed_step(owner_sessionmaker, named=[cid], tenant=tenant)
    a = attempt(worker_sessionmaker, seeded)
    try:
        with pytest.raises(ConnectionUnavailable):
            await a.connection(cid)
    finally:
        await a.aclose()


async def test_another_tenants_connection_is_invisible(owner_sessionmaker, worker_sessionmaker) -> None:
    other = uuid.uuid4()
    await seed_step(owner_sessionmaker, named=[None], tenant=other)
    theirs = await add_connection(owner_sessionmaker, other, config={"base_url": "https://dewpoint.test:9"})
    seeded = await seed_step(owner_sessionmaker, named=[theirs])  # a graph naming it, in another tenant
    a = attempt(worker_sessionmaker, seeded)
    try:
        with pytest.raises(ConnectionUnavailable):
            await a.connection(theirs)
    finally:
        await a.aclose()


async def test_a_simulated_step_sends_nothing(owner_sessionmaker, worker_sessionmaker) -> None:
    seeded, cid = await _setup(owner_sessionmaker, 9)
    a = attempt(worker_sessionmaker, seeded, simulated=True)
    try:
        with pytest.raises(SimulationSendsNothing):
            await a.connection(cid)
        with pytest.raises(SimulationSendsNothing):
            await a.http.request("GET", "https://dewpoint.test:9/")
        with pytest.raises(SimulationSendsNothing):
            await a.net.send_udp("dewpoint.test", 514, b"x")
    finally:
        await a.aclose()


async def test_the_plugin_can_change_neither_the_origin_nor_the_credentials(
    owner_sessionmaker, worker_sessionmaker
) -> None:
    async with serve(respond(), tls_names=NAMES) as server:
        seeded, cid = await _setup(owner_sessionmaker, server.port)
        a = attempt(worker_sessionmaker, seeded)
        try:
            conn = await a.connection(cid)
            with pytest.raises(InvalidRequest):
                await conn.http.request("GET", "https://elsewhere.test/steal")
            with pytest.raises(InvalidRequest):
                await conn.http.request("GET", f"http://dewpoint.test:{server.port}/downgrade")
            with pytest.raises(InvalidRequest):
                await conn.http.request("GET", "/", headers={"Authorization": "Bearer mine"})
        finally:
            await a.aclose()
    assert server.requests == []


async def test_an_empty_scope_is_a_cooldown_and_nothing_is_sent(owner_sessionmaker, worker_sessionmaker) -> None:
    async with serve(respond(), tls_names=NAMES) as server:
        seeded, cid = await _setup(owner_sessionmaker, server.port, capacity=1, refill_per_s=0.001)
        a = attempt(worker_sessionmaker, seeded)
        try:
            conn = await a.connection(cid)
            await conn.http.request("GET", "/")
            with pytest.raises(Cooldown):
                await conn.http.request("GET", "/")
        finally:
            await a.aclose()
    assert len(server.requests) == 1


def _limited_once(retry_after: str) -> Any:
    seen: list[int] = []

    async def handler(request: Request, writer: asyncio.StreamWriter) -> None:
        seen.append(1)
        if len(seen) == 1:
            await respond(429, b"slow down", [("retry-after", retry_after)])(request, writer)
        else:
            await respond(200, b"ok")(request, writer)

    return handler


async def test_a_short_retry_after_is_waited_out_by_a_retry_safe_node(owner_sessionmaker, worker_sessionmaker) -> None:
    async with serve(_limited_once("1"), tls_names=NAMES) as server:
        seeded, cid = await _setup(owner_sessionmaker, server.port)
        a = attempt(worker_sessionmaker, seeded)
        try:
            answer = await (await a.connection(cid)).http.request("GET", "/")
        finally:
            await a.aclose()
    assert answer.status_code == 200 and len(server.requests) == 2


async def test_an_ambiguous_node_never_resends_after_a_429(owner_sessionmaker, worker_sessionmaker) -> None:
    async with serve(_limited_once("1"), tls_names=NAMES) as server:
        seeded, cid = await _setup(owner_sessionmaker, server.port, node_type="testkit.ambiguous_call@1")
        a = attempt(worker_sessionmaker, seeded, node=AmbiguousCall)
        try:
            with pytest.raises(RateLimited):
                await (await a.connection(cid)).http.request("POST", "/", content=b"once")
        finally:
            await a.aclose()
    assert len(server.requests) == 1


async def test_a_long_retry_after_blocks_the_scope_for_every_run(owner_sessionmaker, worker_sessionmaker) -> None:
    async with serve(_limited_once("120"), tls_names=NAMES) as server:
        seeded, cid = await _setup(owner_sessionmaker, server.port)
        a = attempt(worker_sessionmaker, seeded)
        try:
            with pytest.raises(RateLimited):
                await (await a.connection(cid)).http.request("GET", "/")
        finally:
            await a.aclose()
        b = attempt(worker_sessionmaker, seeded)  # the next attempt sends nothing while the block lasts
        try:
            with pytest.raises(Cooldown):
                await (await b.connection(cid)).http.request("GET", "/")
        finally:
            await b.aclose()
    assert len(server.requests) == 1
    async with worker_sessionmaker() as s, s.begin():
        await tenant_scope(s, seeded.tenant)
        keys = [k for (k,) in (await s.execute(text("select scope from rate_buckets"))).all()]
        found = await current_cooldowns(s, seeded.tenant, keys)
    assert len(found) == 1
    until = next(iter(found.values()))
    assert timedelta(seconds=100) < until - datetime.now(UTC) <= timedelta(seconds=125)


async def test_the_secret_is_read_on_every_call(owner_sessionmaker, worker_sessionmaker) -> None:
    async with serve(respond(), tls_names=NAMES) as server:
        seeded, cid = await _setup(owner_sessionmaker, server.port)
        a = attempt(worker_sessionmaker, seeded)
        try:
            await (await a.connection(cid)).http.request("GET", "/")
            blob = await seal(seeded.tenant, cid, {"token": "r0tated-token-value"})
            async with owner_sessionmaker() as s, s.begin():
                await s.execute(text("update connections set secret_ct = :b where id = :i"), {"b": blob, "i": cid})
            await (await a.connection(cid)).http.request("GET", "/")
        finally:
            await a.aclose()
    assert [r.headers["authorization"] for r in server.requests] == [
        "Bearer s3cr3t-token-value",
        "Bearer r0tated-token-value",
    ]


def _always_429(retry_after: str) -> Any:
    async def handler(request: Request, writer: asyncio.StreamWriter) -> None:
        await respond(429, b"slow down", [("retry-after", retry_after)])(request, writer)

    return handler


async def test_retry_after_zero_doesnt_loop(owner_sessionmaker, worker_sessionmaker) -> None:
    """The review's finding 3: a wait of 0 still counts, and the in-attempt retries are few."""
    async with serve(_always_429("0"), tls_names=NAMES) as server:
        seeded, cid = await _setup(owner_sessionmaker, server.port)
        a = attempt(worker_sessionmaker, seeded)
        try:
            with pytest.raises(RateLimited):
                await (await a.connection(cid)).http.request("GET", "/")
        finally:
            await a.aclose()
    assert 1 < len(server.requests) <= 4


@pytest.mark.parametrize("value", ["²", "9" * 400, "9" * 5000, "999999999999", "Thu, 01 Jan 1970 00:00:00 GMT", "x"])
async def test_a_strange_retry_after_is_read_safely(owner_sessionmaker, worker_sessionmaker, value: str) -> None:
    """The review's finding 4: no value raises after the request was sent; a block is at most an hour."""
    async with serve(_always_429(value), tls_names=NAMES) as server:
        seeded, cid = await _setup(owner_sessionmaker, server.port)
        a = attempt(worker_sessionmaker, seeded)
        try:
            with pytest.raises(RateLimited):
                await (await a.connection(cid)).http.request("GET", "/")
        finally:
            await a.aclose()
    async with worker_sessionmaker() as s, s.begin():
        await tenant_scope(s, seeded.tenant)
        untils = (await s.execute(text("select blocked_until from rate_buckets"))).scalars().all()
    assert all(u is None or u - datetime.now(UTC) <= timedelta(hours=1, seconds=5) for u in untils)


async def test_quota_identity_survives_a_data_key_rotation(owner_sessionmaker, worker_sessionmaker) -> None:
    """The second review's ruling 7: workers holding different data-key versions (a cache lasts 300 s) charge and honour
    the same token scope."""
    async with serve(_limited_once("120"), tls_names=NAMES) as server:
        seeded, cid = await _setup(owner_sessionmaker, server.port)
        before = attempt(worker_sessionmaker, seeded, keys=FixtureKeys(version=1))
        try:
            with pytest.raises(RateLimited):
                await (await before.connection(cid)).http.request("GET", "/")
        finally:
            await before.aclose()
        after = attempt(worker_sessionmaker, seeded, keys=FixtureKeys(version=2))
        try:
            with pytest.raises(Cooldown):
                await (await after.connection(cid)).http.request("GET", "/")
        finally:
            await after.aclose()
    assert len(server.requests) == 1
    async with worker_sessionmaker() as s, s.begin():
        await tenant_scope(s, seeded.tenant)
        scopes = (await s.execute(text("select scope from rate_buckets where scope like 'testkit.token:%'"))).all()
    assert len(scopes) == 1
