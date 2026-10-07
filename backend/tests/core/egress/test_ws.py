# SPDX-License-Identifier: Apache-2.0
"""The guarded websocket (plugins-3 D26): wss only, the name vetted and the socket connected by the guard's own code to
a vetted address, then handed to `websockets`, which resolves nothing, reads no proxy setting and follows no redirect;
TLS checked against the name; the handshake's headers checked; opening, a message and an attempt's bytes bounded; text
messages only; and every failure saying what happened, never the host or an address."""

import asyncio
import contextlib
import ipaddress
import logging
import socket
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

import pytest
from websockets.asyncio.server import ServerConnection, serve
from websockets.datastructures import Headers
from websockets.http11 import Request, Response

from dewpoint.core.egress.guard import (
    EgressRefusedError,
    Guard,
    InvalidRequestError,
    NotSentError,
    TlsVerificationError,
)
from dewpoint.core.egress.http import ResponseTooLargeError, ResponseUnreadableError
from dewpoint.core.egress.ws import GuardedWebsocket, HandshakeRejectedError, StreamLostError, WsLimits
from tests.support.netfakes import TENANT, Resolver, guard, tls

NAMES = ("stream.test",)
TOKEN = "Token " + "t" * 40


@dataclass
class Seen:
    headers: list[Headers] = field(default_factory=list)
    received: list[str | bytes] = field(default_factory=list)
    connections: int = 0


type Session = Callable[[ServerConnection], Awaitable[None]]


async def echo(ws: ServerConnection) -> None:
    async for message in ws:
        await ws.send(f"echo:{message!s}")


@asynccontextmanager
async def server(
    session: Session = echo, *, status: Response | None = None, names: tuple[str, ...] = NAMES
) -> AsyncIterator[tuple[int, Seen]]:
    """A wss server on 127.0.0.1 for `names`, answering each handshake with `status` when given."""
    seen = Seen()

    def process_request(conn: ServerConnection, request: Request) -> Response | None:
        seen.connections += 1
        seen.headers.append(request.headers)
        return status

    async def handler(ws: ServerConnection) -> None:
        with contextlib.suppress(Exception):  # a client gone mid-session
            await session(ws)

    async with serve(handler, "127.0.0.1", 0, ssl=tls(names).server_context(), process_request=process_request) as s:
        yield next(iter(s.sockets)).getsockname()[1], seen


def websocket(answers: dict[str, Any] | None = None, limits: WsLimits | None = None) -> GuardedWebsocket:
    return GuardedWebsocket(
        guard(answers or {"stream.test": ["127.0.0.1"]}), TENANT, ssl_context=tls(NAMES).client_context(),
        limits=limits or WsLimits(),
    )  # fmt: skip


async def test_a_text_round_trip_through_the_vetted_address_with_the_headers_given() -> None:
    async with server() as (port, seen):
        w = websocket()
        try:
            stream = await w.open(f"wss://stream.test:{port}/api-ws/v1/stream", {"Authorization": TOKEN})
            await stream.send('{"subscribe": "/x"}')
            assert await stream.receive(5) == 'echo:{"subscribe": "/x"}'
        finally:
            await w.aclose()
    assert seen.headers[0]["Authorization"] == TOKEN
    assert seen.headers[0]["Host"] == f"stream.test:{port}"


async def test_the_name_is_resolved_once_by_the_guard_and_never_by_the_library() -> None:
    resolver = Resolver({"stream.test": [["127.0.0.1"], ["10.0.0.1"]]})  # a second lookup would rebind
    async with server() as (port, _):
        w = GuardedWebsocket(Guard(resolver, guard({}).allowlist), TENANT, ssl_context=tls(NAMES).client_context())
        try:
            stream = await w.open(f"wss://stream.test:{port}/s", {})
            await stream.send("hi")
            assert await stream.receive(5) == "echo:hi"
        finally:
            await w.aclose()
    assert resolver.asked == ["stream.test"]


async def test_a_name_the_guard_refuses_connects_nowhere() -> None:
    async with server() as (port, seen):
        w = websocket({"stream.test": ["10.0.0.1"]})  # private, no allowlist entry for it
        with pytest.raises(EgressRefusedError):
            await w.open(f"wss://stream.test:{port}/s", {})
        await w.aclose()
    assert seen.connections == 0


@pytest.mark.parametrize(
    "url",
    [
        "ws://stream.test/s",  # plain text
        "https://stream.test/s",
        "wss://user:pass@stream.test/s",  # credentials in the URL
        "wss:///s",  # no host
        "wss://stream.test/s#part",  # a fragment
        "not a url",
    ],
)
async def test_anything_but_a_plain_wss_url_is_refused_before_anything(url: str) -> None:
    resolver = Resolver({"stream.test": ["127.0.0.1"]})
    w = GuardedWebsocket(Guard(resolver, guard({}).allowlist), TENANT, ssl_context=tls(NAMES).client_context())
    with pytest.raises(InvalidRequestError):
        await w.open(url, {})
    await w.aclose()
    assert resolver.asked == []


@pytest.mark.parametrize(
    "headers",
    [
        {"Host": "elsewhere.test"},
        {"Sec-WebSocket-Key": "AAAAAAAAAAAAAAAAAAAAAA=="},
        {"Upgrade": "h2c"},
        {"Connection": "close"},
        {"Proxy-Authorization": "Basic x"},
        {"Authorization": "Token a\r\nX-Injected: 1"},
        {"Bad Name": "x"},
    ],
)
async def test_a_header_the_handshake_owns_or_a_malformed_one_is_refused(headers: dict[str, str]) -> None:
    async with server() as (port, seen):
        w = websocket()
        with pytest.raises(InvalidRequestError):
            await w.open(f"wss://stream.test:{port}/s", headers)
        await w.aclose()
    assert seen.connections == 0


async def test_a_header_name_ending_in_a_line_break_is_refused_before_anything() -> None:
    """`$` also matches before a final "\\n": the name must be a token to its very end, or the handshake would carry
    the line break."""
    resolver = Resolver({"stream.test": ["127.0.0.1"]})
    w = GuardedWebsocket(Guard(resolver, guard({}).allowlist), TENANT, ssl_context=tls(NAMES).client_context())
    with pytest.raises(InvalidRequestError) as refused:
        await w.open("wss://stream.test/s", {"X-Test\n": "x"})
    await w.aclose()
    assert refused.value.reason == "header"
    assert resolver.asked == []


async def test_a_certificate_for_another_name_fails_tls_verification() -> None:
    async with server(names=("other.test",)) as (port, seen):
        w = websocket()
        with pytest.raises(TlsVerificationError):
            await w.open(f"wss://stream.test:{port}/s", {})
        await w.aclose()
    assert seen.connections == 0


@pytest.mark.parametrize(("status", "retry_after"), [(401, None), (403, None), (429, "17"), (503, "5")])
async def test_a_refused_handshake_names_its_status_and_its_retry_after(status: int, retry_after: str | None) -> None:
    headers = Headers([("Retry-After", retry_after)] if retry_after else [])
    async with server(status=Response(status, "No", headers, b"")) as (port, _):
        w = websocket()
        with pytest.raises(HandshakeRejectedError) as raised:
            await w.open(f"wss://stream.test:{port}/s", {})
        await w.aclose()
    assert (raised.value.status, raised.value.retry_after) == (status, retry_after)


async def test_a_redirect_is_never_followed() -> None:
    moved = Response(302, "Found", Headers([("Location", "wss://elsewhere.test/s")]), b"")
    async with server(status=moved) as (port, seen):
        w = websocket()
        with pytest.raises(HandshakeRejectedError) as raised:
            await w.open(f"wss://stream.test:{port}/s", {})
        await w.aclose()
    assert raised.value.status == 302
    assert seen.connections == 1


async def test_proxy_settings_in_the_environment_are_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("https_proxy", "HTTPS_PROXY", "wss_proxy", "WSS_PROXY", "all_proxy", "ALL_PROXY"):
        monkeypatch.setenv(name, "http://127.0.0.1:9")  # nothing listens there
    async with server() as (port, _):
        w = websocket()
        try:
            stream = await w.open(f"wss://stream.test:{port}/s", {})
            await stream.send("direct")
            assert await stream.receive(5) == "echo:direct"
        finally:
            await w.aclose()


async def test_nothing_listening_is_not_sent() -> None:
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    w = websocket()
    with pytest.raises(NotSentError):
        await w.open(f"wss://stream.test:{port}/s", {})
    await w.aclose()


async def test_a_server_that_never_answers_the_handshake_times_out_as_not_sent() -> None:
    async def silent(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await asyncio.sleep(5)
        writer.close()

    plain = await asyncio.start_server(silent, "127.0.0.1", 0, ssl=tls(NAMES).server_context())
    port = plain.sockets[0].getsockname()[1]
    w = websocket(limits=WsLimits(open_s=0.3))
    try:
        started = asyncio.get_running_loop().time()
        with pytest.raises(NotSentError):
            await w.open(f"wss://stream.test:{port}/s", {})
        assert asyncio.get_running_loop().time() - started < 2
    finally:
        await w.aclose()
        plain.close()


async def test_a_receive_that_times_out_answers_none_and_loses_nothing() -> None:
    async def late(ws: ServerConnection) -> None:
        await ws.recv()
        await asyncio.sleep(0.4)
        await ws.send("late")
        await asyncio.sleep(1)

    async with server(late) as (port, _):
        w = websocket()
        try:
            stream = await w.open(f"wss://stream.test:{port}/s", {})
            await stream.send("go")
            assert await stream.receive(0.05) is None
            assert await stream.receive(5) == "late"
        finally:
            await w.aclose()


async def test_a_message_larger_than_the_cap_fails_too_large() -> None:
    async def big(ws: ServerConnection) -> None:
        await ws.recv()
        await ws.send("x" * 2048)
        await asyncio.sleep(1)

    async with server(big) as (port, _):
        w = websocket(limits=WsLimits(max_message_bytes=1024))
        try:
            stream = await w.open(f"wss://stream.test:{port}/s", {})
            await stream.send("go")
            with pytest.raises(ResponseTooLargeError):
                await stream.receive(5)
        finally:
            await w.aclose()


async def test_an_attempts_bytes_are_bounded_across_messages_and_streams() -> None:
    async def chatty(ws: ServerConnection) -> None:
        await ws.recv()
        for _ in range(10):
            await ws.send("y" * 300)
        await asyncio.sleep(1)

    async with server(chatty) as (port, _):
        w = websocket(limits=WsLimits(max_message_bytes=1024, max_attempt_bytes=1000))
        try:
            first = await w.open(f"wss://stream.test:{port}/s", {})
            await first.send("go")
            assert await first.receive(5) == "y" * 300
            second = await w.open(f"wss://stream.test:{port}/s", {})
            await second.send("go")
            assert await second.receive(5) == "y" * 300
            assert await first.receive(5) == "y" * 300
            with pytest.raises(ResponseTooLargeError):
                await second.receive(5)
        finally:
            await w.aclose()


async def test_a_binary_message_is_unreadable() -> None:
    async def binary(ws: ServerConnection) -> None:
        await ws.recv()
        await ws.send(b"\x00\x01")
        await asyncio.sleep(1)

    async with server(binary) as (port, _):
        w = websocket()
        try:
            stream = await w.open(f"wss://stream.test:{port}/s", {})
            await stream.send("go")
            with pytest.raises(ResponseUnreadableError):
                await stream.receive(5)
        finally:
            await w.aclose()


async def test_a_stream_the_server_closes_is_lost_on_receive_and_on_send() -> None:
    async def closing(ws: ServerConnection) -> None:
        await ws.recv()
        await ws.close()

    async with server(closing) as (port, _):
        w = websocket()
        try:
            stream = await w.open(f"wss://stream.test:{port}/s", {})
            await stream.send("go")
            with pytest.raises(StreamLostError):
                await stream.receive(5)
            with pytest.raises(StreamLostError):
                await stream.send("again")
        finally:
            await w.aclose()


async def test_a_message_sent_is_text_within_the_cap() -> None:
    async with server() as (port, seen):
        w = websocket(limits=WsLimits(max_message_bytes=16))
        try:
            stream = await w.open(f"wss://stream.test:{port}/s", {})
            with pytest.raises(InvalidRequestError):
                await stream.send("z" * 17)
            with pytest.raises(InvalidRequestError):
                await stream.send(b"bytes")  # type: ignore[arg-type]
        finally:
            await w.aclose()


async def test_closing_the_attempt_closes_its_streams() -> None:
    closed = asyncio.Event()

    async def waits(ws: ServerConnection) -> None:
        try:
            await ws.recv()
        finally:
            closed.set()

    async with server(waits) as (port, _):
        w = websocket()
        stream = await w.open(f"wss://stream.test:{port}/s", {})
        await w.aclose()
        await asyncio.wait_for(closed.wait(), 5)
        with pytest.raises(StreamLostError):
            await stream.receive(1)
        await stream.close()  # closing again changes nothing


@pytest.mark.parametrize("timeout_s", [-1, float("nan"), float("inf"), 3601, True, "5"])
async def test_a_receive_timeout_is_a_number_of_seconds_within_an_hour(timeout_s: Any) -> None:
    async with server() as (port, _):
        w = websocket()
        try:
            stream = await w.open(f"wss://stream.test:{port}/s", {})
            with pytest.raises(InvalidRequestError):
                await stream.receive(timeout_s)
        finally:
            await w.aclose()


@pytest.mark.parametrize("location", ["http://elsewhere.test/s", "ftp://elsewhere.test/s", "wss://[bad/s"])
async def test_a_redirect_anywhere_is_a_refused_handshake(location: str) -> None:
    """Review L2: websockets parses the Location before refusing to follow it; whatever it says, it's the 302."""
    moved = Response(302, "Found", Headers([("Location", location)]), b"")
    async with server(status=moved) as (port, _):
        w = websocket()
        with pytest.raises(HandshakeRejectedError) as raised:
            await w.open(f"wss://stream.test:{port}/s", {})
        await w.aclose()
    assert raised.value.status == 302


async def test_the_librarys_debug_lines_never_carry_the_credentials(caplog: pytest.LogCaptureFixture) -> None:
    """Review L3: websockets logs each handshake header at DEBUG; even with the root logger at DEBUG, none is logged."""
    caplog.set_level(logging.DEBUG)
    async with server() as (port, _):
        w = websocket()
        try:
            stream = await w.open(f"wss://stream.test:{port}/s", {"Authorization": TOKEN})
            await stream.send("hi")
            await stream.receive(5)
        finally:
            await w.aclose()
    ours = [r for r in caplog.records if not r.name.startswith("websockets.server")]  # the fake's own lines aside
    assert not any("t" * 40 in r.getMessage() for r in ours)  # the library's client lines without the fix


async def test_a_closed_attempt_opens_no_stream() -> None:
    async with server() as (port, seen):
        w = websocket()
        await w.aclose()
        with pytest.raises(InvalidRequestError):
            await w.open(f"wss://stream.test:{port}/s", {})
    assert seen.connections == 0


async def test_an_opening_under_way_when_the_attempt_closes_returns_no_live_stream() -> None:
    """The owner's review R1: closing the attempt fences openings already under way; one that completes after the
    close is closed, never returned."""
    held = asyncio.Event()
    closed = asyncio.Event()

    async def slow(conn: ServerConnection, request: Request) -> None:
        held.set()
        await asyncio.sleep(0.4)

    async def waits(ws: ServerConnection) -> None:
        try:
            await ws.recv()
        finally:
            closed.set()

    async with serve(waits, "127.0.0.1", 0, ssl=tls(NAMES).server_context(), process_request=slow) as s:
        port = next(iter(s.sockets)).getsockname()[1]
        w = websocket()
        opening = asyncio.ensure_future(w.open(f"wss://stream.test:{port}/s", {}))
        await asyncio.wait_for(held.wait(), 5)  # dialed, its handshake under way
        await w.aclose()
        with pytest.raises(InvalidRequestError):
            await opening
        await asyncio.wait_for(closed.wait(), 5)  # the late connection was closed


async def test_vetting_counts_in_the_opening_time() -> None:
    """The owner's review R2: a slow resolver or allowlist read is bounded by the same 5 s (here 80 ms)."""

    class SlowResolver:
        async def resolve(self, host: str, port: int) -> list[Any]:
            await asyncio.sleep(0.3)
            return [ipaddress.ip_address("127.0.0.1")]

    w = GuardedWebsocket(Guard(SlowResolver(), guard({}).allowlist), TENANT, ssl_context=tls(NAMES).client_context(),
                         limits=WsLimits(open_s=0.08))  # fmt: skip
    started = asyncio.get_running_loop().time()
    with pytest.raises(NotSentError):
        await w.open("wss://stream.test:443/s", {})
    assert asyncio.get_running_loop().time() - started < 0.2
    await w.aclose()
