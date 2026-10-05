# SPDX-License-Identifier: Apache-2.0
"""Guarded sockets for non-HTTP transports (plugins-3 D7, `ctx.net`): the same vetting and pinning as HTTP; TLS checked
against the hostname; plaintext TCP and UDP only to allowlisted addresses; reads bounded; and every failure saying
whether data may have left."""

import asyncio
import socket

import pytest

from dewpoint.core.egress.guard import EgressRefusedError, InvalidRequestError, NotSentError, TlsVerificationError
from dewpoint.core.egress.net import GuardedNet, NetLimits
from tests.support.netfakes import TENANT, guard, tls

NAMES = ("dewpoint.test",)


async def _echo_server(*, use_tls: bool) -> tuple[asyncio.Server, int, list[bytes]]:
    seen: list[bytes] = []

    async def on_connect(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        data = await reader.read(1024)
        seen.append(data)
        writer.write(b"echo:" + data)
        await writer.drain()
        writer.close()

    context = tls(NAMES).server_context() if use_tls else None
    server = await asyncio.start_server(on_connect, "127.0.0.1", 0, ssl=context)
    return server, server.sockets[0].getsockname()[1], seen


def net(answers, limits: NetLimits | None = None) -> GuardedNet:  # type: ignore[no-untyped-def]
    return GuardedNet(guard(answers), TENANT, ssl_context=tls(NAMES).client_context(), limits=limits or NetLimits())


async def test_tls_to_a_vetted_address_checks_the_hostname() -> None:
    server, port, seen = await _echo_server(use_tls=True)
    n = net({"dewpoint.test": ["127.0.0.1"]})
    try:
        stream = await n.open_tcp("dewpoint.test", port, tls=True)
        await stream.send(b"hello")
        assert await stream.receive(100) == b"echo:hello"
    finally:
        await n.aclose()
        server.close()
    assert seen == [b"hello"]


async def test_tls_with_a_certificate_for_another_name_is_refused() -> None:
    server, port, seen = await _echo_server(use_tls=True)
    n = net({"other.test": ["127.0.0.1"]})
    try:
        with pytest.raises(TlsVerificationError):
            await n.open_tcp("other.test", port, tls=True)
    finally:
        await n.aclose()
        server.close()
    assert seen == []


async def test_plaintext_tcp_needs_an_allowlist_entry() -> None:
    n = net({"public.test": ["93.184.216.34"]})
    try:
        with pytest.raises(EgressRefusedError):
            await n.open_tcp("public.test", 514, tls=False)
    finally:
        await n.aclose()


async def test_plaintext_tcp_to_an_allowlisted_address_works() -> None:
    server, port, _ = await _echo_server(use_tls=False)
    n = net({"siem.test": ["127.0.0.1"]})
    try:
        stream = await n.open_tcp("siem.test", port, tls=False)
        await stream.send(b"<14>1 - - - - - - x")
        assert (await stream.receive(100)).startswith(b"echo:")
    finally:
        await n.aclose()
        server.close()


async def test_a_refused_connection_means_nothing_was_sent() -> None:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    n = net({"siem.test": ["127.0.0.1"]})
    try:
        with pytest.raises(NotSentError):
            await n.open_tcp("siem.test", port, tls=False)
    finally:
        await n.aclose()


async def test_udp_sends_one_datagram_to_an_allowlisted_address() -> None:
    received: asyncio.Queue[bytes] = asyncio.Queue()

    class Sink(asyncio.DatagramProtocol):
        def datagram_received(self, data: bytes, addr: object) -> None:
            received.put_nowait(data)

    loop = asyncio.get_running_loop()
    transport, _ = await loop.create_datagram_endpoint(Sink, local_addr=("127.0.0.1", 0))
    port = transport.get_extra_info("sockname")[1]
    n = net({"siem.test": ["127.0.0.1"]})
    try:
        await n.send_udp("siem.test", port, b"<14>1 message")
        assert await asyncio.wait_for(received.get(), 2) == b"<14>1 message"
    finally:
        await n.aclose()
        transport.close()


async def test_udp_to_a_destination_that_isnt_allowlisted_is_refused() -> None:
    n = net({"public.test": ["93.184.216.34"]})
    try:
        with pytest.raises(EgressRefusedError):
            await n.send_udp("public.test", 514, b"x")
    finally:
        await n.aclose()


async def test_a_datagram_too_large_is_refused_before_sending() -> None:
    n = net({"siem.test": ["127.0.0.1"]})
    try:
        with pytest.raises(InvalidRequestError):
            await n.send_udp("siem.test", 514, b"x" * 70_000)
    finally:
        await n.aclose()


async def test_closing_the_net_closes_every_open_stream() -> None:
    server, port, _ = await _echo_server(use_tls=False)
    n = net({"siem.test": ["127.0.0.1"]})
    stream = await n.open_tcp("siem.test", port, tls=False)
    await n.aclose()
    server.close()
    assert stream.closed
