# SPDX-License-Identifier: Apache-2.0
"""3c-2's proof (plugins-3 D20, D21), end to end: a published workflow emailing one message and logging it to syslog
over TLS and UDP runs through admission, the dispatcher and RunGraph against local servers standing in for
`smtp.example.com` and `logs.example.com` (each vetted, pinned and TLS-checked by the guard):

- the email goes to the connection's server, over STARTTLS, signed in by the runtime with the stored password (never
  the node), from the connection's sender, to the node's recipients, as a plain-text message;
- each syslog line reaches its receiver, octet-counted over TLS, one datagram over UDP;
- no step's row holds the password, and the email's send charged its server's quota scope;
- simulated, the same workflow sends nothing."""

import asyncio
import email
import email.policy
import ipaddress
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import pytest
from sqlalchemy import text
from temporalio.testing import WorkflowEnvironment

from dewpoint.apps import dev_run
from dewpoint.apps.dispatcher.dispatch import dispatch_once
from dewpoint.apps.plugin_loader import sync_installed
from dewpoint.apps.worker.network import DbConnections, Network, worker_types
from dewpoint.apps.worker.store import DbRunStore
from dewpoint.core.db import tenant_scope
from dewpoint.core.egress.addresses import AllowEntry
from dewpoint.plugins.email import PLUGIN as EMAIL
from dewpoint.plugins.flow import PLUGIN as FLOW
from dewpoint.plugins.syslog import BOM
from dewpoint.plugins.syslog import PLUGIN as SYSLOG
from tests.apps.dispatcher.support import BUILD
from tests.apps.dispatcher.support import workers as ready_workers
from tests.apps.test_admission import KEYS, current
from tests.apps.test_workflow_ops import actor, create, publish
from tests.apps.worker.harness import workers
from tests.support.connections import add_connection
from tests.support.graphs import G
from tests.support.netfakes import guard, tls
from tests.support.smtpfakes import Script, SmtpServer, serve_smtp

pytestmark = pytest.mark.usefixtures("development_deployment")
SMTP_HOST, LOG_HOST = "smtp.example.com", "logs.example.com"
NAMES = (SMTP_HOST, LOG_HOST)
PASSWORD = "pa55-word"
MESSAGE = {"title": "db-1", "text": "Disk full on db-1", "fields": [{"label": "Free", "value": "2%"}],
           "severity": "warning"}  # fmt: skip


@dataclass
class Receivers:
    smtp: SmtpServer
    tls_port: int
    udp_port: int
    tls_frames: list[bytes] = field(default_factory=list)
    datagrams: list[bytes] = field(default_factory=list)


@pytest.fixture
async def receivers() -> AsyncIterator[Receivers]:
    tls_frames: list[bytes] = []
    datagrams: list[bytes] = []

    async def on_tls(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        tls_frames.append(await reader.read())  # the whole connection: one octet-counted frame
        writer.close()

    class Datagrams(asyncio.DatagramProtocol):
        def datagram_received(self, data: bytes, addr: Any) -> None:
            datagrams.append(data)

    script = Script(names=NAMES, credentials=("alerts@example.com", PASSWORD))  # one test CA for both hosts
    tls_server = await asyncio.start_server(on_tls, "127.0.0.1", 0, ssl=tls(NAMES).server_context())
    transport, _ = await asyncio.get_running_loop().create_datagram_endpoint(Datagrams, local_addr=("127.0.0.1", 0))
    try:
        async with serve_smtp(script) as smtp:
            state = Receivers(smtp, tls_server.sockets[0].getsockname()[1], transport.get_extra_info("sockname")[1])
            state.tls_frames, state.datagrams = tls_frames, datagrams
            yield state
    finally:
        tls_server.close()
        transport.close()


async def _published(owner: Any, api: Any, admin: Any, dispatch: Any, settings: Any,
                     rx: Receivers) -> tuple[Any, uuid.UUID]:  # fmt: skip
    async with admin() as s, s.begin():
        await sync_installed(s, [FLOW, EMAIL, SYSLOG])
    ctx = await actor(owner)
    mail = await add_connection(owner, ctx.tenant_id, type_key="email", config={
        "host": SMTP_HOST, "port": rx.smtp.port, "security": "starttls", "from_address": "alerts@example.com",
        "from_name": "Dewpoint", "username": "alerts@example.com"}, secret={"password": PASSWORD})  # fmt: skip
    over_tls = await add_connection(owner, ctx.tenant_id, type_key="syslog", secret={},
                                    config={"host": LOG_HOST, "port": rx.tls_port, "transport": "tls"})  # fmt: skip
    over_udp = await add_connection(owner, ctx.tenant_id, type_key="syslog", secret={},
                                    config={"host": LOG_HOST, "port": rx.udp_port, "transport": "udp",
                                            "facility": 16, "format": "cef"})  # fmt: skip
    g = G()
    g.node("mail", "email.send_message@1", {"connection": str(mail), "to": ["ops@example.com"], **MESSAGE})
    g.node("log_tls", "syslog.send_message@1", {"connection": str(over_tls), **MESSAGE})
    g.node("log_udp", "syslog.send_message@1", {"connection": str(over_udp), **MESSAGE})
    g.edge("mail", "log_tls")
    g.edge("log_tls", "log_udp")
    wf = await create(api, ctx, g.data())
    published = await publish(api, ctx, wf, settings)
    assert published.version is not None, published
    await current(dispatch)
    await ready_workers(owner)
    return ctx, wf


async def _run(env: Any, ctx: Any, wf: Any, dispatch: Any, worker: Any, settings: Any, *, simulate: bool) -> Any:
    loopback = AllowEntry(ipaddress.ip_network("127.0.0.1/32"), None, ctx.tenant_id)  # UDP is plaintext: an entry
    plugins = (EMAIL, SYSLOG)
    network = Network(
        guard=guard({name: ["127.0.0.1"] for name in NAMES}, [loopback]),
        connections=DbConnections(worker),
        sessionmaker=worker,
        keys=KEYS,
        ssl_context=tls(NAMES).client_context(),
        types=worker_types(list(plugins)),
    )
    request = await dev_run.admit(dispatch, KEYS, tenant_id=ctx.tenant_id, workflow_id=wf, input={},
                                  simulate=simulate, idempotency_key=f"ms-{simulate}")  # fmt: skip
    async with workers(env.client, DbRunStore(worker, KEYS), plugins=plugins, network=network):
        assert await dispatch_once(dispatch, env.client, KEYS, settings, BUILD) == {"started": 1}
        return request, await dev_run.wait_for_end(dispatch, ctx.tenant_id, request.id, within=90, poll=0.1)


async def test_one_message_is_mailed_and_logged_over_tls_and_udp(
    env: WorkflowEnvironment, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker,
    worker_sessionmaker, api_settings, receivers,
) -> None:  # fmt: skip
    ctx, wf = await _published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker,
                               api_settings, receivers)  # fmt: skip
    _, ended = await _run(env, ctx, wf, dispatch_sessionmaker, worker_sessionmaker, api_settings, simulate=False)
    assert ended == dev_run.Ended("run", "succeeded", None, None), ended
    [got] = receivers.smtp.sessions
    assert dict(got.commands)["AUTH"] is True and got.logins == [("PLAIN", "alerts@example.com", PASSWORD)]
    assert got.mail[0].startswith("FROM:<alerts@example.com>") and got.rcpt == ["ops@example.com"]
    mail = email.message_from_bytes(got.payload or b"", policy=email.policy.SMTP)
    assert (mail["From"], mail["Subject"], mail["Auto-Submitted"]) == ("Dewpoint <alerts@example.com>", "db-1",
                                                                       "auto-generated")  # fmt: skip
    [framed] = receivers.tls_frames
    length, _, line = framed.partition(b" ")
    assert int(length) == len(line) and line.startswith(b"<12>1 ") and BOM + b"db-1 | Disk full on db-1" in line
    for _ in range(100):  # a datagram may still be in flight when the run ends
        if receivers.datagrams:
            break
        await asyncio.sleep(0.01)
    [datagram] = receivers.datagrams
    assert (
        datagram.startswith(b"<132>1 ") and b" - - - CEF:0|Dewpoint|Dewpoint|1.0.0|dewpoint.message|db-1|6|" in datagram
    )
    async with worker_sessionmaker() as s, s.begin():
        await tenant_scope(s, ctx.tenant_id)
        rows = (await s.execute(text("select node_key, output_preview::text, input_preview::text, status "
                                     "from run_steps"))).all()  # fmt: skip
        scopes = [k for (k,) in (await s.execute(text("select scope from rate_buckets"))).all()]
    assert sorted((r[0], r[3]) for r in rows) == [("log_tls", "succeeded"), ("log_udp", "succeeded"),
                                                  ("mail", "succeeded")]  # fmt: skip
    assert all(PASSWORD not in (r[1] or "") + (r[2] or "") for r in rows)
    assert [k.split(":", 1)[0] for k in scopes] == ["email.server"]


async def test_a_simulated_mail_and_syslog_workflow_sends_nothing(
    env: WorkflowEnvironment, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker,
    worker_sessionmaker, api_settings, receivers,
) -> None:  # fmt: skip
    ctx, wf = await _published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker,
                               api_settings, receivers)  # fmt: skip
    _, ended = await _run(env, ctx, wf, dispatch_sessionmaker, worker_sessionmaker, api_settings, simulate=True)
    assert ended is not None and ended.status == "succeeded", ended
    await asyncio.sleep(0.2)
    assert receivers.smtp.sessions == [] and receivers.tls_frames == [] and receivers.datagrams == []
