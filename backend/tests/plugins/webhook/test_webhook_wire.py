# SPDX-License-Identifier: Apache-2.0
"""`webhook.send_json` on the wire, through the runtime's guarded transport to a local server: every body the node
takes, the falsy ones included, arrives as its JSON with a JSON content type, never as an empty request (a review of
1e71079, R1)."""

import ipaddress
import json
import uuid
from types import SimpleNamespace
from typing import Any

import pytest

from dewpoint.apps.worker.network import DbConnections, Network, worker_types
from dewpoint.apps.worker.store import DbRunStore
from dewpoint.core.egress.addresses import AllowEntry
from dewpoint.plugins.webhook import PLUGIN, SendJson
from tests.support.connections import add_connection, seed_step
from tests.support.keys import FixtureKeys
from tests.support.netfakes import guard, respond, serve, tls

NAMES = ("hooks.test",)


def network(worker: Any, tenant: uuid.UUID) -> Network:
    loopback = AllowEntry(ipaddress.ip_network("127.0.0.1/32"), None, tenant)
    return Network(
        guard=guard({"hooks.test": ["127.0.0.1"]}, [loopback]), connections=DbConnections(worker),
        sessionmaker=worker, keys=FixtureKeys(), ssl_context=tls(NAMES).client_context(),
        types=worker_types([PLUGIN]),
    )  # fmt: skip


@pytest.mark.parametrize("body", [0, False, "", [], {}, {"a": None}, [None]])
async def test_every_body_arrives_as_its_json(owner_sessionmaker, worker_sessionmaker, body: Any) -> None:
    async with serve(respond(204, b""), tls_names=NAMES) as server:
        tenant = uuid.uuid4()
        await seed_step(owner_sessionmaker, named=[None], tenant=tenant)
        cid = await add_connection(owner_sessionmaker, tenant, type_key="webhook", config={},
                                   secret={"url": f"https://hooks.test:{server.port}/in/alerts"})  # fmt: skip
        seeded = await seed_step(owner_sessionmaker, named=[cid], tenant=tenant, node_type="webhook.send_json@1")
        attempt = network(worker_sessionmaker, tenant).attempt(
            tenant_id=tenant, run_id=seeded.run, step_id=seeded.step, root_run_id=seeded.run, node=SendJson,
            simulated=False, remember=DbRunStore(worker_sessionmaker, FixtureKeys()).remember, beat=lambda: None,
        )  # fmt: skip
        try:
            config = SendJson.Config.model_validate({"connection": str(cid), "body": body})
            out = await SendJson().run(SimpleNamespace(connection=attempt.connection), config)  # type: ignore[arg-type]
        finally:
            await attempt.aclose()
    assert out.model_dump() == {"sent": True, "status": 204}
    [received] = server.requests
    assert received.headers.get("content-type") == "application/json"
    assert received.body and json.loads(received.body) == body
