# SPDX-License-Identifier: Apache-2.0
"""A local SMTP server for the mail tests (plugins-3 D20): it answers each stage as a test scripts it, upgrades to TLS
on STARTTLS (or speaks TLS from the start) with the test CA's certificate for its names, and records what it received
and whether TLS was up when it did. No test reaches outside this host."""

import asyncio
import base64
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

from tests.support.netfakes import tls


@dataclass
class Script:
    """How the server answers. `end` None: it closes without answering the message's end."""

    greeting: int = 220
    extensions: tuple[str, ...] = ("STARTTLS", "AUTH PLAIN LOGIN", "SIZE 10485760")
    starttls: int = 220
    credentials: tuple[str, str] = ("ops", "pa55-word")
    mail: int = 250
    rcpt: dict[str, int] = field(default_factory=dict)  # by address; 250 otherwise
    data: int = 354
    end: int | None = 250
    end_delay_s: float = 0.0
    names: tuple[str, ...] = ("mail.test",)
    greeting_flood: int = 0  # continuation lines before the greeting's last
    flood_width: int = 96  # each one's text
    drip_s: float = 0.0  # the greeting one byte at a time, forever, this far apart
    end_flood: int = 0  # continuation lines before the answer to the message's end


@dataclass
class Received:
    commands: list[tuple[str, bool]] = field(default_factory=list)  # each verb, and whether TLS was up
    ehlo: list[str] = field(default_factory=list)
    logins: list[tuple[str, str, str]] = field(default_factory=list)  # mechanism, user, password
    mail: list[str] = field(default_factory=list)  # each MAIL's argument
    rcpt: list[str] = field(default_factory=list)
    payload: bytes | None = None  # as sent: dot-stuffed, before the end's "."
    quit: bool = False
    client_closed: bool = False  # the client closed while the server delayed its answer to the end


@dataclass
class SmtpServer:
    port: int
    script: Script
    sessions: list[Received] = field(default_factory=list)


async def _flood(writer: asyncio.StreamWriter, line: bytes, count: int) -> None:
    """`count` lines, yielding after each: on a TLS stream whose client is gone, `drain()` neither yields nor fails, so
    the loop would never learn of it, and the flood held the event loop the test's own send waits on (main's CI)."""
    for _ in range(count):
        writer.write(line)
        await writer.drain()
        await asyncio.sleep(0)  # the lost connection is noticed here: the next drain raises ConnectionResetError


async def _session(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, script: Script, got: Received,
                   tls_up: bool) -> None:  # fmt: skip
    def say(code: int, *lines: str) -> None:
        texts = lines or ("ok",)
        for i, text in enumerate(texts):
            writer.write(f"{code}{'-' if i < len(texts) - 1 else ' '}{text}\r\n".encode())

    if script.drip_s:
        while True:
            writer.write(b"2")
            await writer.drain()
            await asyncio.sleep(script.drip_s)
    await _flood(writer, b"220-" + b"x" * script.flood_width + b"\r\n", script.greeting_flood)
    say(script.greeting, "mail.test ESMTP")
    await writer.drain()
    if script.greeting != 220:
        return
    pending_login: str | None = None
    while True:
        line = await reader.readline()
        if not line:
            return
        text = line.decode("ascii", "replace").rstrip("\r\n")
        if pending_login is not None:  # AUTH LOGIN's password
            got.logins.append(("LOGIN", pending_login, base64.b64decode(text).decode()))
            pending_login = None
            say(235 if got.logins[-1][1:] == script.credentials else 535, "auth")
            await writer.drain()
            continue
        verb, _, argument = text.partition(" ")
        verb = verb.upper()
        got.commands.append((verb, tls_up))
        if verb == "EHLO":
            got.ehlo.append(argument)
            say(250, "mail.test", *script.extensions)
        elif verb == "STARTTLS":
            say(script.starttls, "go ahead")
            await writer.drain()
            if script.starttls == 220:
                await writer.start_tls(tls(script.names).server_context())
                tls_up = True
            continue
        elif verb == "AUTH":
            mechanism, _, initial = argument.partition(" ")
            if mechanism.upper() == "PLAIN":
                _, user, password = base64.b64decode(initial).decode().split("\0")
                got.logins.append(("PLAIN", user, password))
                say(235 if (user, password) == script.credentials else 535, "auth")
            elif mechanism.upper() == "LOGIN":
                pending_login = base64.b64decode(initial).decode()
                say(334, "UGFzc3dvcmQ6")
            else:
                say(504, "unknown mechanism")
        elif verb == "MAIL":
            got.mail.append(argument)
            say(script.mail)
        elif verb == "RCPT":
            address = argument.removeprefix("TO:").removeprefix("to:").strip("<>")
            got.rcpt.append(address)
            say(script.rcpt.get(address, 250))
        elif verb == "DATA":
            say(script.data, "go ahead")
            await writer.drain()
            if script.data != 354:
                continue
            payload = b""
            while (chunk := await reader.readline()) not in (b".\r\n", b""):
                payload += chunk
            got.payload = payload
            if script.end is None:
                writer.close()
                return
            if script.end_delay_s:
                try:
                    if await asyncio.wait_for(reader.read(1), script.end_delay_s) == b"":
                        got.client_closed = True
                        return
                except TimeoutError:
                    pass
            await _flood(writer, b"250-" + b"x" * 96 + b"\r\n", script.end_flood)
            say(script.end, "queued")
        elif verb == "QUIT":
            got.quit = True
            say(221, "bye")
            await writer.drain()
            writer.close()
            return
        else:
            say(500, "unknown")
        await writer.drain()


@asynccontextmanager
async def serve_smtp(script: Script | None = None, *, implicit_tls: bool = False) -> AsyncIterator[SmtpServer]:
    """An SMTP server on 127.0.0.1, answering as `script` says; with `implicit_tls`, TLS from the first byte."""
    state = SmtpServer(port=0, script=script or Script())

    async def on_connect(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        got = Received()
        state.sessions.append(got)
        try:
            await _session(reader, writer, state.script, got, implicit_tls)
        except (ConnectionError, OSError, asyncio.IncompleteReadError):
            pass
        finally:
            writer.close()

    context = tls(state.script.names).server_context() if implicit_tls else None
    server = await asyncio.start_server(on_connect, "127.0.0.1", 0, ssl=context)
    state.port = server.sockets[0].getsockname()[1]
    try:
        yield state
    finally:
        server.close()


@asynccontextmanager
async def delaying_tls(port: int, delay_s: float) -> AsyncIterator[int]:
    """A proxy on 127.0.0.1 to `port` that holds each chunk the server sends starting a TLS handshake record (0x16) for
    `delay_s`: a client's handshake then blocks that long, the window an abort must reach. Yields the proxy's port."""

    async def pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, hold: bool) -> None:
        try:
            while data := await reader.read(65_536):
                if hold and data[:1] == b"\x16":
                    await asyncio.sleep(delay_s)
                writer.write(data)
                await writer.drain()
        except (ConnectionError, OSError):
            pass
        finally:
            writer.close()

    async def on_connect(client_reader: asyncio.StreamReader, client_writer: asyncio.StreamWriter) -> None:
        server_reader, server_writer = await asyncio.open_connection("127.0.0.1", port)
        await asyncio.gather(pipe(client_reader, server_writer, False), pipe(server_reader, client_writer, True))

    proxy = await asyncio.start_server(on_connect, "127.0.0.1", 0)
    try:
        yield proxy.sockets[0].getsockname()[1]
    finally:
        proxy.close()
