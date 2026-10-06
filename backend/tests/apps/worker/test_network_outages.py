# SPDX-License-Identifier: Apache-2.0
"""What a step attempt's network says when something fails before or around a send (plugins-3 D7, D10; the 3a-1
self-review): a database outage before the request is sent is `NotSent` (the wrapper still makes an ambiguous node's
failure `outcome_unknown` once an earlier request of its attempt may have been sent); recording a provider's block is
best effort, never changing the step's outcome; and a reconcilable node never resends inside its attempt, so its
policy checks for the effect first."""

import asyncio
import ipaddress
import uuid
from typing import Any

import pytest

from dewpoint.apps.worker.network import DbConnections, Network
from dewpoint.apps.worker.store import DbRunStore
from dewpoint.core.egress.addresses import AllowEntry
from dewpoint.sdk import NotSent, RateLimited
from tests.support.connections import add_connection, seed_step, types_for_testkit
from tests.support.keys import FixtureKeys
from tests.support.netfakes import Request, guard, respond, serve, tls
from tests.support.plugins.testkit import AmbiguousCall, ReconcilableCall

NAMES = ("dewpoint.test",)


class _Down:
    """A sessionmaker whose database doesn't answer."""

    def __call__(self) -> Any:
        raise ConnectionRefusedError("database down")


class _DownSource(DbConnections):
    async def load(self, tenant_id: uuid.UUID, connection_id: uuid.UUID) -> Any:
        raise ConnectionRefusedError("database down")


async def _setup(owner: Any, port: int, node: type) -> tuple[Any, uuid.UUID]:
    tenant = uuid.uuid4()
    await seed_step(owner, named=[None], tenant=tenant)
    cid = await add_connection(owner, tenant, config={"base_url": f"https://dewpoint.test:{port}"})
    return await seed_step(owner, named=[cid], tenant=tenant, node_type=f"{node.type}@{node.version}"), cid


def _attempt(worker: Any, seeded: Any, node: type, *, connections: Any = None, buckets: Any = None) -> Any:
    network = Network(
        guard=guard(
            {"dewpoint.test": ["127.0.0.1"]}, [AllowEntry(ipaddress.ip_network("127.0.0.1/32"), None, seeded.tenant)]
        ),  # fmt: skip
        connections=connections or DbConnections(worker),
        sessionmaker=buckets or worker,
        keys=FixtureKeys(),
        ssl_context=tls(NAMES).client_context(),
        types=types_for_testkit(),
    )
    return network.attempt(
        tenant_id=seeded.tenant, run_id=seeded.run, step_id=seeded.step, root_run_id=seeded.run, node=node,
        simulated=False, remember=DbRunStore(worker, FixtureKeys()).remember, beat=lambda: None,
    )  # fmt: skip


async def test_a_database_outage_loading_the_connection_sent_nothing(owner_sessionmaker, worker_sessionmaker) -> None:
    seeded, cid = await _setup(owner_sessionmaker, 9, AmbiguousCall)
    a = _attempt(worker_sessionmaker, seeded, AmbiguousCall, connections=_DownSource(worker_sessionmaker))
    try:
        with pytest.raises(NotSent):
            await a.connection(cid)
    finally:
        await a.aclose()


async def test_a_database_outage_taking_a_token_sent_nothing(owner_sessionmaker, worker_sessionmaker) -> None:
    async with serve(respond(), tls_names=NAMES) as server:
        seeded, cid = await _setup(owner_sessionmaker, server.port, AmbiguousCall)
        a = _attempt(worker_sessionmaker, seeded, AmbiguousCall, buckets=_Down())
        try:
            conn = await a.connection(cid)
            with pytest.raises(NotSent):
                await conn.http.request("POST", "/", content=b"once")
        finally:
            await a.aclose()
    assert server.requests == []


def _limited_once(retry_after: str) -> Any:
    seen: list[int] = []

    async def handler(request: Request, writer: asyncio.StreamWriter) -> None:
        seen.append(1)
        if len(seen) == 1:
            await respond(429, b"slow down", [("retry-after", retry_after)])(request, writer)
        else:
            await respond(200, b"ok")(request, writer)

    return handler


async def test_a_reconcilable_node_never_resends_inside_its_attempt(owner_sessionmaker, worker_sessionmaker) -> None:
    async with serve(_limited_once("1"), tls_names=NAMES) as server:
        seeded, cid = await _setup(owner_sessionmaker, server.port, ReconcilableCall)
        a = _attempt(worker_sessionmaker, seeded, ReconcilableCall)
        try:
            with pytest.raises(RateLimited):
                await (await a.connection(cid)).http.request("POST", "/", content=b"create")
        finally:
            await a.aclose()
    assert len(server.requests) == 1


class _FailingBlocks:
    """Takes tokens from the real database, but fails once the server has the request: recording the block."""

    def __init__(self, worker: Any, server: Any) -> None:
        self.worker, self.server = worker, server

    def __call__(self) -> Any:
        if self.server.requests:
            raise ConnectionRefusedError("database down")
        return self.worker()


async def test_a_block_that_cant_be_recorded_changes_nothing(owner_sessionmaker, worker_sessionmaker) -> None:
    async with serve(_limited_once("1"), tls_names=NAMES) as server:
        seeded, cid = await _setup(owner_sessionmaker, server.port, AmbiguousCall)
        a = _attempt(worker_sessionmaker, seeded, AmbiguousCall, buckets=_FailingBlocks(worker_sessionmaker, server))
        try:
            with pytest.raises(RateLimited):
                await (await a.connection(cid)).http.request("POST", "/", content=b"once")
        finally:
            await a.aclose()
    assert len(server.requests) == 1
