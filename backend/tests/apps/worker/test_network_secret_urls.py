# SPDX-License-Identifier: Apache-2.0
"""A connection whose base URL is its secret (plugins-3 D4's `url` auth, an incoming webhook), against a local server
only: a request goes to that URL exactly, its path and query untouched, with no credentials header and nothing of the
node's (no other path, query or absolute URL); a URL of another shape is unavailable; its parts join the secret index;
its quota scope is keyed by the part the type names (a space), so two webhooks of one space share it."""

import ipaddress
import uuid
from typing import Any

import pytest

from dewpoint.apps.worker.network import DbConnections, Network, worker_types
from dewpoint.apps.worker.store import DbRunStore
from dewpoint.core.egress.addresses import AllowEntry
from dewpoint.sdk import ConnectionUnavailable, Cooldown, InvalidRequest
from tests.support.connections import add_connection, seed_step
from tests.support.keys import FixtureKeys
from tests.support.netfakes import guard, respond, serve, tls
from tests.support.plugins.hookkit import HOOKKIT, HookPost

NAMES = ("hooks.test",)
KEY = "kkkkkkkkkkkkkkkkkkk"


def url(port: int, space: str = "space1") -> str:
    return f"https://hooks.test:{port}/v1/spaces/{space}/messages?key={KEY}"


def network(worker: Any, tenant: uuid.UUID) -> Network:
    loopback = AllowEntry(ipaddress.ip_network("127.0.0.1/32"), None, tenant)
    return Network(
        guard=guard({"hooks.test": ["127.0.0.1"]}, [loopback]), connections=DbConnections(worker),
        sessionmaker=worker, keys=FixtureKeys(), ssl_context=tls(NAMES).client_context(),
        types=worker_types([HOOKKIT]),
    )  # fmt: skip


async def _setup(owner: Any, webhook_url: str, tenant: uuid.UUID | None = None) -> tuple[Any, uuid.UUID]:
    tenant = tenant or uuid.uuid4()
    await seed_step(owner, named=[None], tenant=tenant)
    cid = await add_connection(owner, tenant, type_key="hookkit", config={}, secret={"webhook_url": webhook_url})
    return await seed_step(owner, named=[cid], tenant=tenant, node_type="hookkit.post@1"), cid


def attempt(worker: Any, seeded: Any) -> Any:
    store = DbRunStore(worker, FixtureKeys())
    return network(worker, seeded.tenant).attempt(
        tenant_id=seeded.tenant, run_id=seeded.run, step_id=seeded.step, root_run_id=seeded.run, node=HookPost,
        simulated=False, remember=store.remember, beat=lambda: None,
    )  # fmt: skip


async def test_a_request_goes_to_the_secret_url_exactly(owner_sessionmaker, worker_sessionmaker) -> None:
    async with serve(respond(200, b"ok"), tls_names=NAMES) as server:
        seeded, cid = await _setup(owner_sessionmaker, url(server.port))
        a = attempt(worker_sessionmaker, seeded)
        try:
            answer = await (await a.connection(cid)).http.request("POST", "", json={"text": "hi"})
        finally:
            await a.aclose()
    assert answer.status_code == 200
    assert server.requests[0].target == f"/v1/spaces/space1/messages?key={KEY}"
    assert "authorization" not in server.requests[0].headers


@pytest.mark.parametrize(
    ("target", "kwargs"),
    [
        ("/v1/spaces/other/messages", {}),  # another path
        ("?key=mine", {}),  # another query
        ("https://elsewhere.test/hook", {}),  # another origin
        ("", {"params": {"threadKey": "x"}}),  # a query of the node's
        ("", {"headers": {"Authorization": "Bearer x"}}),
    ],
)
async def test_the_node_can_add_nothing_to_the_url(
    owner_sessionmaker, worker_sessionmaker, target: str, kwargs: dict[str, Any]
) -> None:
    async with serve(respond(), tls_names=NAMES) as server:
        seeded, cid = await _setup(owner_sessionmaker, url(server.port))
        a = attempt(worker_sessionmaker, seeded)
        try:
            with pytest.raises(InvalidRequest):
                await (await a.connection(cid)).http.request("POST", target, json={"text": "x"}, **kwargs)
        finally:
            await a.aclose()
    assert server.requests == []


@pytest.mark.parametrize(
    "stored",
    [
        "https://evil.test/v1/spaces/space1/messages?key=kkkkkkkkkkkkkkkkkkk",
        "http://hooks.test/v1/spaces/space1/messages?key=kkkkkkkkkkkkkkkkkkk",
        "https://hooks.test/v1/spaces/space1/messages?key=kkkkkkkkkkkkkkkkkkk\n",
        "https://hooks.test/v1/spaces/space1/messages?key=kkkkkkkkkkkkkkkkkkk&extra=1",
    ],
)
async def test_a_url_of_another_shape_is_unavailable(owner_sessionmaker, worker_sessionmaker, stored: str) -> None:
    seeded, cid = await _setup(owner_sessionmaker, stored)
    a = attempt(worker_sessionmaker, seeded)
    try:
        with pytest.raises(ConnectionUnavailable):
            await a.connection(cid)
    finally:
        await a.aclose()


async def test_the_urls_parts_join_the_secret_index(owner_sessionmaker, worker_sessionmaker) -> None:
    seeded, cid = await _setup(owner_sessionmaker, url(4443))
    a = attempt(worker_sessionmaker, seeded)
    try:
        await a.connection(cid)
    finally:
        await a.aclose()
    index = await DbRunStore(worker_sessionmaker, FixtureKeys()).index(str(seeded.tenant), str(seeded.run))
    assert url(4443) in index.strings and KEY in index.strings


async def test_two_webhooks_of_one_space_share_its_scope(owner_sessionmaker, worker_sessionmaker) -> None:
    async with serve(respond(), tls_names=NAMES) as server:
        tenant = uuid.uuid4()
        first, a_id = await _setup(owner_sessionmaker, url(server.port), tenant)
        second, b_id = await _setup(owner_sessionmaker, url(server.port).replace(KEY, "an0therkey00"), tenant)
        other, c_id = await _setup(owner_sessionmaker, url(server.port, "space2"), tenant)
        for seeded, cid, expect in ((first, a_id, None), (second, b_id, Cooldown), (other, c_id, None)):
            a = attempt(worker_sessionmaker, seeded)
            try:
                conn = await a.connection(cid)
                if expect is None:
                    await conn.http.request("POST", "", json={"text": "x"})
                else:
                    with pytest.raises(expect):
                        await conn.http.request("POST", "", json={"text": "x"})
            finally:
                await a.aclose()
    assert len(server.requests) == 2
