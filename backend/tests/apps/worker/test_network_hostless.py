# SPDX-License-Identifier: Apache-2.0
"""A connection type that declares no host and no mail server (syslog's: its node sends through the step's guarded
network to the receiver its config names) opens like any other, its config the node's to read; it has no HTTP, so its
`http` refuses every request, and a type that declares a host still needs one that resolves (3c-2's proof found the
first refused as `connection_unavailable`)."""

import ipaddress
import uuid
from typing import Any

import pytest

from dewpoint.apps.worker.network import DbConnections, Network, worker_types
from dewpoint.apps.worker.store import DbRunStore
from dewpoint.core.egress.addresses import AllowEntry
from dewpoint.plugins.syslog import PLUGIN as SYSLOG
from dewpoint.plugins.syslog import SendMessage
from dewpoint.sdk import InvalidRequest
from tests.support.connections import add_connection, seed_step
from tests.support.keys import FixtureKeys
from tests.support.netfakes import guard, tls

CONFIG = {"host": "logs.example.com", "port": 6514, "transport": "tls"}


async def _attempt(owner: Any, worker: Any) -> tuple[Any, uuid.UUID]:
    tenant = uuid.uuid4()
    await seed_step(owner, named=[None], tenant=tenant)
    cid = await add_connection(owner, tenant, type_key="syslog", config=CONFIG, secret={})
    seeded = await seed_step(owner, named=[cid], tenant=tenant, node_type="syslog.send_message@1")
    network = Network(
        guard=guard({"logs.example.com": ["127.0.0.1"]}, [AllowEntry(ipaddress.ip_network("127.0.0.1/32"), None,
                                                                     tenant)]),
        connections=DbConnections(worker), sessionmaker=worker, keys=FixtureKeys(),
        ssl_context=tls(("logs.example.com",)).client_context(), types=worker_types([SYSLOG]),
    )  # fmt: skip
    attempt = network.attempt(
        tenant_id=tenant, run_id=seeded.run, step_id=seeded.step, root_run_id=seeded.run, node=SendMessage,
        simulated=False, remember=DbRunStore(worker, FixtureKeys()).remember, beat=lambda: None,
    )  # fmt: skip
    return attempt, cid


async def test_a_hostless_type_opens_and_has_no_http(owner_sessionmaker, worker_sessionmaker) -> None:
    attempt, cid = await _attempt(owner_sessionmaker, worker_sessionmaker)
    try:
        conn = await attempt.connection(cid)
        assert conn.config["host"] == "logs.example.com" and conn.config["transport"] == "tls"
        with pytest.raises(InvalidRequest):
            await conn.http.request("GET", "/")
        with pytest.raises(InvalidRequest):
            await conn.smtp.send(["ops@example.com"], b"x\r\n")
    finally:
        await attempt.aclose()
    assert not attempt.uncertain
