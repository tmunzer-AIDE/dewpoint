# SPDX-License-Identifier: Apache-2.0
"""A connection's mail (plugins-3 D4, D20), against a local server only: its type's declared server and sender, the
runtime signing in with the stored password, which joins the run's secret index; a token from each quota scope a
send; a definite refusal leaves the attempt as it was (nothing was delivered), a connection lost after the payload
doesn't; the connection has no HTTP; a plugin call may probe, never send; a long send heartbeats."""

import asyncio
import ipaddress
import uuid
from types import SimpleNamespace
from typing import Any

import pytest

from dewpoint.apps.worker import network as worker_network
from dewpoint.apps.worker.activities import _transport_failed
from dewpoint.apps.worker.network import DbConnections, Network, worker_types
from dewpoint.apps.worker.plugin_calls import CallNetwork
from dewpoint.apps.worker.store import DbRunStore
from dewpoint.core.egress.addresses import AllowEntry
from dewpoint.core.egress.smtp import SmtpLimits
from dewpoint.sdk import (
    AuthUnavailable,
    Cooldown,
    InvalidRequest,
    MailRefused,
    MaybeSent,
    ReadOnly,
    SimulationSendsNothing,
    TlsUnavailable,
)
from tests.support.connections import add_connection, seed_step
from tests.support.keys import FixtureKeys
from tests.support.netfakes import guard, tls
from tests.support.plugins.mailkit import MAILKIT, MESSAGE, MailSend
from tests.support.smtpfakes import Script, serve_smtp

NAMES = ("mail.test",)
PASSWORD = "pa55-word"


def network(worker: Any, tenant: uuid.UUID, limits: SmtpLimits | None = None) -> Network:
    loopback = AllowEntry(ipaddress.ip_network("127.0.0.1/32"), None, tenant)
    return Network(
        guard=guard({"mail.test": ["127.0.0.1"]}, [loopback]), connections=DbConnections(worker),
        sessionmaker=worker, keys=FixtureKeys(), ssl_context=tls(NAMES).client_context(),
        types=worker_types([MAILKIT]), smtp_limits=limits or SmtpLimits(),
    )  # fmt: skip


async def _setup(owner: Any, port: int, tenant: uuid.UUID | None = None) -> tuple[Any, uuid.UUID]:
    tenant = tenant or uuid.uuid4()
    await seed_step(owner, named=[None], tenant=tenant)
    config = {"host": "mail.test", "port": port, "security": "starttls", "from_address": "alerts@example.com",
              "username": "ops"}  # fmt: skip
    cid = await add_connection(owner, tenant, type_key="mailkit", config=config, secret={"password": PASSWORD})
    return await seed_step(owner, named=[cid], tenant=tenant, node_type="mailkit.send@1"), cid


def attempt(worker: Any, seeded: Any, *, simulated: bool = False, beat: Any = None,
            limits: SmtpLimits | None = None) -> Any:  # fmt: skip
    return network(worker, seeded.tenant, limits).attempt(
        tenant_id=seeded.tenant, run_id=seeded.run, step_id=seeded.step, root_run_id=seeded.run, node=MailSend,
        simulated=simulated, remember=DbRunStore(worker, FixtureKeys()).remember, beat=beat or (lambda: None),
    )  # fmt: skip


async def test_a_send_goes_to_the_declared_server_signed_in_by_the_runtime(owner_sessionmaker, worker_sessionmaker):
    async with serve_smtp() as server:
        seeded, cid = await _setup(owner_sessionmaker, server.port)
        a = attempt(worker_sessionmaker, seeded)
        try:
            refused = await (await a.connection(cid)).smtp.send(["ops@example.com"], MESSAGE)
        finally:
            await a.aclose()
    assert refused == [] and a.uncertain
    [got] = server.sessions
    assert got.logins == [("PLAIN", "ops", PASSWORD)] and got.mail[0].startswith("FROM:<alerts@example.com>")
    index = await DbRunStore(worker_sessionmaker, FixtureKeys()).index(str(seeded.tenant), str(seeded.run))
    assert PASSWORD in index.strings


async def test_a_definite_refusal_leaves_the_attempt_clean(owner_sessionmaker, worker_sessionmaker) -> None:
    async with serve_smtp(Script(end=554)) as server:
        seeded, cid = await _setup(owner_sessionmaker, server.port)
        a = attempt(worker_sessionmaker, seeded)
        try:
            with pytest.raises(MailRefused) as raised:
                await (await a.connection(cid)).smtp.send(["ops@example.com"], MESSAGE)
        finally:
            await a.aclose()
    assert (raised.value.stage, raised.value.reply) == ("end", 554) and not a.uncertain


@pytest.mark.parametrize(("script", "error"), [(Script(extensions=("AUTH PLAIN",)), TlsUnavailable),
                                               (Script(extensions=("STARTTLS",)), AuthUnavailable)])  # fmt: skip
async def test_no_tls_or_no_sign_in_sends_nothing(owner_sessionmaker, worker_sessionmaker, script: Script,
                                                  error: type[Exception]) -> None:  # fmt: skip
    async with serve_smtp(script) as server:
        seeded, cid = await _setup(owner_sessionmaker, server.port)
        a = attempt(worker_sessionmaker, seeded)
        try:
            with pytest.raises(error):
                await (await a.connection(cid)).smtp.send(["ops@example.com"], MESSAGE)
        finally:
            await a.aclose()
    assert not a.uncertain and server.sessions[0].mail == []


async def test_a_connection_lost_after_the_payload_marks_the_attempt(owner_sessionmaker, worker_sessionmaker):
    async with serve_smtp(Script(end=None)) as server:
        seeded, cid = await _setup(owner_sessionmaker, server.port)
        a = attempt(worker_sessionmaker, seeded)
        try:
            with pytest.raises(MaybeSent):
                await (await a.connection(cid)).smtp.send(["ops@example.com"], MESSAGE)
        finally:
            await a.aclose()
    assert a.uncertain


async def test_each_send_takes_a_token_from_the_servers_scope(owner_sessionmaker, worker_sessionmaker) -> None:
    async with serve_smtp() as server:
        seeded, cid = await _setup(owner_sessionmaker, server.port)
        a = attempt(worker_sessionmaker, seeded)
        try:
            conn = await a.connection(cid)
            await conn.smtp.send(["ops@example.com"], MESSAGE)
            with pytest.raises(Cooldown):  # a burst of 1
                await conn.smtp.send(["ops@example.com"], MESSAGE)
        finally:
            await a.aclose()
    assert len(server.sessions) == 1


async def test_a_probe_in_a_step_takes_a_token_and_leaves_the_attempt_clean(owner_sessionmaker, worker_sessionmaker):
    """A probe sends no MAIL, so nothing it does is a send; it still reaches the server, so it takes a token."""
    async with serve_smtp() as server:
        seeded, cid = await _setup(owner_sessionmaker, server.port)
        a = attempt(worker_sessionmaker, seeded)
        try:
            conn = await a.connection(cid)
            await conn.smtp.probe()
            assert not a.uncertain
            with pytest.raises(Cooldown):
                await conn.smtp.send(["ops@example.com"], MESSAGE)
        finally:
            await a.aclose()
    assert [got.mail for got in server.sessions] == [[]]


async def test_a_mail_connection_has_no_http(owner_sessionmaker, worker_sessionmaker) -> None:
    seeded, cid = await _setup(owner_sessionmaker, 2525)
    a = attempt(worker_sessionmaker, seeded)
    try:
        with pytest.raises(InvalidRequest):
            await (await a.connection(cid)).http.request("GET", "/")
    finally:
        await a.aclose()


async def test_a_simulated_step_opens_no_mail_connection(owner_sessionmaker, worker_sessionmaker) -> None:
    seeded, cid = await _setup(owner_sessionmaker, 2525)
    a = attempt(worker_sessionmaker, seeded, simulated=True)
    with pytest.raises(SimulationSendsNothing):
        await a.connection(cid)


async def test_a_plugin_call_may_probe_but_never_send(owner_sessionmaker, worker_sessionmaker) -> None:
    async with serve_smtp() as server:
        seeded, cid = await _setup(owner_sessionmaker, server.port)
        net = network(worker_sessionmaker, seeded.tenant)
        stored = await net.connections.load(seeded.tenant, cid)
        assert stored is not None
        claimed = SimpleNamespace(tenant_id=seeded.tenant, connection_id=cid, revision=stored.revision)
        call = CallNetwork(net, claimed, frozenset({"mailkit"}))  # type: ignore[arg-type]
        try:
            conn = await call.connection(cid)
            await conn.smtp.probe()
            with pytest.raises(ReadOnly):
                await conn.smtp.send(["ops@example.com"], MESSAGE)
        finally:
            await call.aclose()
    [got] = server.sessions  # the send never connected
    assert got.logins == [("PLAIN", "ops", PASSWORD)] and got.mail == [] and got.quit


async def test_closing_the_attempt_aborts_a_send_left_running(owner_sessionmaker, worker_sessionmaker) -> None:
    """A node's send it didn't await ends with its attempt (the review's M1)."""
    async with serve_smtp(Script(end_delay_s=30.0)) as server:
        seeded, cid = await _setup(owner_sessionmaker, server.port)
        a = attempt(worker_sessionmaker, seeded)
        conn = await a.connection(cid)
        task = asyncio.create_task(conn.smtp.send(["ops@example.com"], MESSAGE))
        for _ in range(1000):
            if server.sessions and server.sessions[0].payload is not None:
                break
            await asyncio.sleep(0.01)
        await a.aclose()
        with pytest.raises(MaybeSent):
            await asyncio.wait_for(task, 5)
    assert server.sessions[0].client_closed


def paused(monkeypatch: pytest.MonkeyPatch, where: str) -> asyncio.Event:
    """Holds a send or probe in its scope lookup (`scopes`) or its quota wait (`tokens`) until released."""
    release = asyncio.Event()
    if where == "tokens":
        real_take = worker_network.take_tokens

        async def take(*args: Any) -> None:
            await release.wait()
            await real_take(*args)

        monkeypatch.setattr(worker_network, "take_tokens", take)
    else:
        real_scopes = worker_network.ConnectionSmtp._scopes

        async def scopes(self: Any) -> Any:
            await release.wait()
            return await real_scopes(self)

        monkeypatch.setattr(worker_network.ConnectionSmtp, "_scopes", scopes)
    return release


@pytest.mark.parametrize("where", ["scopes", "tokens"])
async def test_a_send_waiting_when_the_attempt_closes_never_starts(owner_sessionmaker, worker_sessionmaker,
                                                                   monkeypatch, where: str) -> None:  # fmt: skip
    """The attempt's mail client is made lazily: closed before it was, the attempt recorded nothing, and the waiting
    send made a fresh one and delivered (the owner's review of 82ae00b)."""
    release = paused(monkeypatch, where)
    async with serve_smtp() as server:
        seeded, cid = await _setup(owner_sessionmaker, server.port)
        a = attempt(worker_sessionmaker, seeded)
        conn = await a.connection(cid)
        task = asyncio.create_task(conn.smtp.send(["ops@example.com"], MESSAGE))
        await asyncio.sleep(0.1)
        await a.aclose()
        release.set()
        with pytest.raises(InvalidRequest):
            await asyncio.wait_for(task, 5)
    assert server.sessions == [] and not a.uncertain


@pytest.mark.parametrize("where", ["scopes", "tokens"])
async def test_a_probe_waiting_when_the_call_closes_never_starts(owner_sessionmaker, worker_sessionmaker,
                                                                  monkeypatch, where: str) -> None:  # fmt: skip
    release = paused(monkeypatch, where)
    async with serve_smtp() as server:
        seeded, cid = await _setup(owner_sessionmaker, server.port)
        net = network(worker_sessionmaker, seeded.tenant)
        stored = await net.connections.load(seeded.tenant, cid)
        assert stored is not None
        claimed = SimpleNamespace(tenant_id=seeded.tenant, connection_id=cid, revision=stored.revision)
        call = CallNetwork(net, claimed, frozenset({"mailkit"}))  # type: ignore[arg-type]
        conn = await call.connection(cid)
        task = asyncio.create_task(conn.smtp.probe())
        await asyncio.sleep(0.1)
        await call.aclose()
        release.set()
        with pytest.raises(InvalidRequest):
            await asyncio.wait_for(task, 5)
    assert server.sessions == []


async def test_an_attempt_keeps_one_mail_client_so_closing_reaches_every_send(owner_sessionmaker, worker_sessionmaker):
    seeded, _ = await _setup(owner_sessionmaker, 2525)
    a = attempt(worker_sessionmaker, seeded)
    try:
        assert a.core_smtp() is a.core_smtp()
    finally:
        await a.aclose()


async def test_a_long_send_heartbeats(owner_sessionmaker, worker_sessionmaker, monkeypatch) -> None:
    monkeypatch.setattr(worker_network, "SMTP_BEAT_S", 0.05)
    beats: list[int] = []
    async with serve_smtp(Script(end_delay_s=0.5)) as server:
        seeded, cid = await _setup(owner_sessionmaker, server.port)
        a = attempt(worker_sessionmaker, seeded, beat=lambda: beats.append(1))
        try:
            await (await a.connection(cid)).smtp.send(["ops@example.com"], MESSAGE)
        finally:
            await a.aclose()
    assert len(beats) >= 3


class Ambiguous:
    side_effect = MailSend.side_effect


class Sneaky(MailRefused):
    pass


@pytest.mark.parametrize(
    ("error", "retryable"),
    [(MailRefused("end", 451), True), (MailRefused("rcpt", 421), True), (MailRefused("end", 554), False),
     (MailRefused("auth", 535), False), (TlsUnavailable(), False), (AuthUnavailable(), False)],
)  # fmt: skip
def test_a_transient_refusal_is_retried_and_none_is_unknown(error: Exception, retryable: bool) -> None:
    failed = _transport_failed(error, MailSend)  # type: ignore[arg-type]
    assert failed.retryable is retryable and failed.outcome != "outcome_unknown"


def test_a_plugins_refusal_cant_make_itself_retryable() -> None:
    sneaky = Sneaky("end", 554)
    sneaky.reply = "451"  # type: ignore[assignment]
    assert _transport_failed(sneaky, MailSend).retryable is False
