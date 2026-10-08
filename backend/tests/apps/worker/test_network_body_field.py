# SPDX-License-Identifier: Apache-2.0
"""A connection whose credentials are a JSON body field (plugins-3 D4's `body_field`), against a local server only:
the runtime puts the secret into every request's JSON object body, as the field the type names, and sends no auth
header; a node can't set that field, nor send a request without a JSON object body; nothing is sent otherwise; the
secret joins the run's secret index."""

import ipaddress
import json
import uuid
from typing import Any

import pytest

from dewpoint.apps.worker.network import DbConnections, Network, worker_types
from dewpoint.apps.worker.store import DbRunStore
from dewpoint.core.egress.addresses import AllowEntry
from dewpoint.sdk import InvalidRequest
from tests.support.connections import add_connection, seed_step
from tests.support.keys import FixtureKeys
from tests.support.netfakes import guard, respond, serve, tls
from tests.support.plugins.bodykit import BODYKIT, ROUTING_KEY, Post

NAMES = ("events.test",)


async def _attempt(owner: Any, worker: Any, port: int) -> tuple[Any, uuid.UUID, Any]:
    tenant = uuid.uuid4()
    await seed_step(owner, named=[None], tenant=tenant)
    cid = await add_connection(owner, tenant, type_key="bodykit", config={"url": f"https://events.test:{port}"},
                               secret={"routing_key": ROUTING_KEY})  # fmt: skip
    seeded = await seed_step(owner, named=[cid], tenant=tenant, node_type="bodykit.post@1")
    network = Network(
        guard=guard({"events.test": ["127.0.0.1"]}, [AllowEntry(ipaddress.ip_network("127.0.0.1/32"), None, tenant)]),
        connections=DbConnections(worker), sessionmaker=worker, keys=FixtureKeys(),
        ssl_context=tls(NAMES).client_context(), types=worker_types([BODYKIT]),
    )  # fmt: skip
    attempt = network.attempt(
        tenant_id=tenant, run_id=seeded.run, step_id=seeded.step, root_run_id=seeded.run, node=Post,
        simulated=False, remember=DbRunStore(worker, FixtureKeys()).remember, beat=lambda: None,
    )  # fmt: skip
    return attempt, cid, seeded


async def test_the_secret_is_the_bodys_field_and_no_header(owner_sessionmaker, worker_sessionmaker) -> None:
    async with serve(respond(202, b'{"status": "success"}'), tls_names=NAMES) as server:
        attempt, cid, seeded = await _attempt(owner_sessionmaker, worker_sessionmaker, server.port)
        try:
            answer = await (await attempt.connection(cid)).http.request("POST", "/v2/enqueue",
                                                                        json={"event_action": "trigger"})  # fmt: skip
        finally:
            await attempt.aclose()
    assert answer.status_code == 202
    [got] = server.requests
    assert json.loads(got.body) == {"event_action": "trigger", "routing_key": ROUTING_KEY}
    assert "authorization" not in got.headers
    index = await DbRunStore(worker_sessionmaker, FixtureKeys()).index(str(seeded.tenant), str(seeded.run))
    assert ROUTING_KEY in index.strings


@pytest.mark.parametrize(
    ("method", "kwargs"),
    [
        ("POST", {"json": {"event_action": "trigger", "routing_key": "s" * 32}}),  # the node's own key: never sent
        ("POST", {"json": [{"event_action": "trigger"}]}),
        ("POST", {"json": "trigger"}),
        ("POST", {"content": b'{"event_action": "trigger"}'}),
        ("POST", {"content": b"raw", "json": {"event_action": "trigger"}}),  # httpx would send the raw bytes alone
        ("POST", {}),
        ("GET", {}),
    ],
)
async def test_a_request_the_field_cant_go_into_is_refused(owner_sessionmaker, worker_sessionmaker, method: str,
                                                           kwargs: dict[str, Any]) -> None:  # fmt: skip
    async with serve(respond(202, b"{}"), tls_names=NAMES) as server:
        attempt, cid, _ = await _attempt(owner_sessionmaker, worker_sessionmaker, server.port)
        try:
            with pytest.raises(InvalidRequest):
                await (await attempt.connection(cid)).http.request(method, "/v2/enqueue", **kwargs)
        finally:
            await attempt.aclose()
    assert server.requests == [] and not attempt.uncertain
