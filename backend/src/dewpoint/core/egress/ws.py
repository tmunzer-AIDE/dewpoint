# SPDX-License-Identifier: Apache-2.0
"""The guarded websocket (plugins-3 D26): wss only, to a name the guard vets, over a socket this module connects to a
vetted address (pinning) and hands to `websockets` with the name for SNI and the certificate. Given a connected socket,
`websockets` resolves nothing, reads no proxy setting and follows no redirect (17.1, `asyncio/client.py`). Opening, a
message and an attempt's bytes are bounded; only text messages are read; the handshake's own headers are the
library's. Failures say what happened, never the host, an address or the URL."""

import asyncio
import math
import re
import socket
import ssl
import urllib.parse
import uuid
from collections.abc import Mapping
from dataclasses import dataclass

import httpx
from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed, InvalidHandshake, InvalidStatus, PayloadTooBig
from websockets.frames import CloseCode

from dewpoint.core.egress.guard import Guard, InvalidRequestError, NotSentError, TlsVerificationError
from dewpoint.core.egress.http import ResponseTooLargeError, ResponseUnreadableError

MIB = 1024 * 1024
MAX_RECEIVE_WAIT_S = 3600.0  # the longest one receive may wait (a step's timeout bounds it sooner)
HEADER_NAME = re.compile(r"^[A-Za-z0-9!#$%&'*+.^_`|~-]{1,64}$")  # an RFC 9110 token
# What the opening handshake is made of, or routes it: the library's alone.
RESERVED_HEADERS = frozenset({
    "host", "upgrade", "connection", "origin", "content-length", "transfer-encoding", "te", "trailer", "keep-alive",
    "proxy-authorization", "proxy-connection",
})  # fmt: skip


@dataclass(frozen=True)
class WsLimits:
    open_s: float = 5.0  # connecting, TLS and the handshake together
    max_message_bytes: int = MIB
    max_attempt_bytes: int = 10 * MIB  # every message an attempt's streams receive
    ping_interval_s: float = 60.0  # Mist's recommendation (guides/websocket/2_best_practices)
    ping_timeout_s: float = 45.0
    close_s: float = 5.0


class HandshakeRejectedError(Exception):
    """The server answered the opening handshake with a status other than 101 (a redirect included, never followed).
    Only the handshake was sent."""

    def __init__(self, status: int, retry_after: str | None) -> None:
        super().__init__("The stream's handshake was refused.")
        self.status, self.retry_after = status, retry_after


class StreamLostError(Exception):
    """The stream closed or broke: a message being sent may have left."""

    def __init__(self) -> None:
        super().__init__("The stream was lost.")


def _target(url: str) -> tuple[str, int]:
    """A wss URL's host and port, once it's one this module may open: no credentials, no fragment."""
    try:
        parts = urllib.parse.urlsplit(url)
        port = parts.port or 443
    except ValueError:
        raise InvalidRequestError("url") from None
    if parts.scheme != "wss" or not parts.hostname or parts.username is not None or parts.password is not None:
        raise InvalidRequestError("url")
    if parts.fragment or "#" in url or any(c in url for c in "\r\n\0 "):
        raise InvalidRequestError("url")
    return parts.hostname, port


def _headers(headers: Mapping[str, str]) -> dict[str, str]:
    for name, value in headers.items():
        if not isinstance(name, str) or not isinstance(value, str) or not HEADER_NAME.match(name):
            raise InvalidRequestError("header")
        lowered = name.lower()
        if lowered in RESERVED_HEADERS or lowered.startswith("sec-websocket-") or any(c in value for c in "\r\n\0"):
            raise InvalidRequestError("header")
    return dict(headers)


def _rejected(error: InvalidStatus) -> HandshakeRejectedError:
    return HandshakeRejectedError(error.response.status_code, error.response.headers.get("Retry-After"))


class GuardedSocket:
    """One open stream: text messages sent and received, bounded."""

    def __init__(self, connection: ClientConnection, owner: "GuardedWebsocket") -> None:
        self._connection, self._owner = connection, owner
        self.closed = False

    async def send(self, text: str) -> None:
        if not isinstance(text, str) or len(text.encode()) > self._owner.limits.max_message_bytes:
            raise InvalidRequestError("message")
        if self.closed:
            raise StreamLostError()
        try:
            await self._connection.send(text)
        except (ConnectionClosed, OSError):
            raise StreamLostError() from None

    async def receive(self, timeout_s: float) -> str | None:
        """The next text message, or None when none came within `timeout_s` (nothing is lost: the next call reads
        it)."""
        if (not isinstance(timeout_s, int | float) or isinstance(timeout_s, bool) or not math.isfinite(timeout_s)
                or not 0 <= timeout_s <= MAX_RECEIVE_WAIT_S):  # fmt: skip
            raise InvalidRequestError("timeout")
        if self.closed:
            raise StreamLostError()
        try:
            message = await asyncio.wait_for(self._connection.recv(), timeout_s)
        except TimeoutError:
            return None
        except ConnectionClosed as e:
            if e.sent is not None and e.sent.code == CloseCode.MESSAGE_TOO_BIG:
                raise ResponseTooLargeError() from None
            raise StreamLostError() from None
        except PayloadTooBig:
            raise ResponseTooLargeError() from None
        except OSError:
            raise StreamLostError() from None
        if not isinstance(message, str):
            await self.close()
            raise ResponseUnreadableError()
        self._owner.received += len(message.encode())
        if self._owner.received > self._owner.limits.max_attempt_bytes:
            await self.close()
            raise ResponseTooLargeError()
        return message

    async def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        try:
            await asyncio.wait_for(self._connection.close(), self._owner.limits.close_s)
        except (TimeoutError, ConnectionClosed, OSError):
            self._connection.transport.abort()


class GuardedWebsocket:
    """One attempt's streams for one tenant, closed together."""

    def __init__(
        self,
        guard: Guard,
        tenant_id: uuid.UUID,
        *,
        ssl_context: ssl.SSLContext | None = None,
        limits: WsLimits | None = None,
    ) -> None:
        self._guard, self._tenant = guard, tenant_id
        # the same trust as the HTTP client's: the bundled CAs, never SSL_CERT_FILE or SSL_CERT_DIR
        self._context = ssl_context or httpx.create_ssl_context(trust_env=False)
        self.limits = limits or WsLimits()
        self.received = 0
        self._open: list[GuardedSocket] = []

    async def open(self, url: str, headers: Mapping[str, str]) -> GuardedSocket:
        host, port = _target(url)
        sent_headers = _headers(headers)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.limits.open_s
        addresses = await self._guard.vet(host, port, self._tenant)
        for address in addresses:
            sock = await _dial(str(address), port, max(0.0, deadline - loop.time()))
            if sock is None:
                continue
            try:
                connection = await self._handshake(url, sock, host, sent_headers, max(0.01, deadline - loop.time()))
            except ssl.SSLError:
                raise TlsVerificationError() from None
            except InvalidStatus as e:
                raise _rejected(e) from None
            except ValueError as e:  # a redirect, refused since the socket was ours
                if isinstance(e.__cause__, InvalidStatus):
                    raise _rejected(e.__cause__) from None
                raise NotSentError("handshake") from None
            except (InvalidHandshake, ConnectionClosed, OSError, TimeoutError):
                raise NotSentError("handshake") from None
            stream = GuardedSocket(connection, self)
            self._open.append(stream)
            return stream
        raise NotSentError("connect")

    async def _handshake(
        self, url: str, sock: socket.socket, host: str, headers: dict[str, str], timeout_s: float
    ) -> ClientConnection:
        """The opening handshake over the connected socket: the name for SNI and the certificate, no proxy; the socket
        closed if it fails."""
        try:
            return await connect(
                url, sock=sock, ssl=self._context, server_hostname=host, proxy=None, additional_headers=headers,
                open_timeout=timeout_s, max_size=self.limits.max_message_bytes,
                ping_interval=self.limits.ping_interval_s, ping_timeout=self.limits.ping_timeout_s,
                close_timeout=self.limits.close_s,
            )  # fmt: skip
        except BaseException:
            sock.close()
            raise

    async def aclose(self) -> None:
        for stream in self._open:
            await stream.close()
        self._open.clear()


async def _dial(address: str, port: int, timeout_s: float) -> socket.socket | None:
    """A TCP socket connected to the vetted `address`, or None when it can't be within `timeout_s`."""
    family = socket.AF_INET6 if ":" in address else socket.AF_INET
    sock = socket.socket(family, socket.SOCK_STREAM)
    sock.setblocking(False)
    try:
        await asyncio.wait_for(asyncio.get_running_loop().sock_connect(sock, (address, port)), timeout_s)
    except (OSError, TimeoutError):
        sock.close()
        return None
    return sock
