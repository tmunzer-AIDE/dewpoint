# SPDX-License-Identifier: Apache-2.0
"""Guarded sockets for transports other than HTTP (plugins-3 D7, `ctx.net`): TCP, TLS and UDP to an address the guard
vetted, TLS checked against the hostname, plaintext only to allowlisted addresses. One attempt's streams are closed
together. Failures say whether data may have left, and name no host or address."""

import asyncio
import ssl
import uuid
from dataclasses import dataclass

from dewpoint.core.egress.guard import (
    Guard,
    InvalidRequestError,
    MaybeSentError,
    NotSentError,
    TlsVerificationError,
)

MAX_DATAGRAM = 65_507


@dataclass(frozen=True)
class NetLimits:
    connect_s: float = 5.0
    read_s: float = 30.0


class GuardedStream:
    """A connected stream: `send` and bounded `receive`; any failure after connecting may have sent data."""

    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, limits: NetLimits) -> None:
        self._reader, self._writer, self._limits = reader, writer, limits
        self.closed = False

    async def send(self, data: bytes) -> None:
        try:
            self._writer.write(data)
            await asyncio.wait_for(self._writer.drain(), self._limits.read_s)
        except (OSError, TimeoutError, ssl.SSLError):
            raise MaybeSentError("send") from None

    async def receive(self, max_bytes: int = 65_536) -> bytes:
        """At most `max_bytes`; b"" once the peer closed."""
        try:
            return await asyncio.wait_for(self._reader.read(max_bytes), self._limits.read_s)
        except (OSError, TimeoutError, ssl.SSLError):
            raise MaybeSentError("receive") from None

    async def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        self._writer.close()
        try:
            await asyncio.wait_for(self._writer.wait_closed(), self._limits.connect_s)
        except (OSError, TimeoutError, ssl.SSLError):
            pass


class GuardedNet:
    """One attempt's sockets for one tenant."""

    def __init__(
        self,
        guard: Guard,
        tenant_id: uuid.UUID,
        *,
        ssl_context: ssl.SSLContext | None = None,
        limits: NetLimits | None = None,
    ) -> None:
        self._guard, self._tenant = guard, tenant_id
        self._context = ssl_context or ssl.create_default_context()
        self.limits = limits or NetLimits()
        self._open: list[GuardedStream] = []

    async def open_tcp(self, host: str, port: int, *, tls: bool) -> GuardedStream:
        addresses = await self._guard.vet(host, port, self._tenant, plaintext=not tls)
        for address in addresses:
            try:
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(
                        str(address),
                        port,
                        ssl=self._context if tls else None,
                        server_hostname=host.removeprefix("[").removesuffix("]") if tls else None,
                    ),
                    self.limits.connect_s,
                )
            except ssl.SSLError:
                raise TlsVerificationError() from None
            except (OSError, TimeoutError):
                continue
            stream = GuardedStream(reader, writer, self.limits)
            self._open.append(stream)
            return stream
        raise NotSentError("connect")

    async def send_udp(self, host: str, port: int, data: bytes) -> None:
        """One datagram to the first vetted address; UDP is never acknowledged."""
        if len(data) > MAX_DATAGRAM:
            raise InvalidRequestError("datagram")
        addresses = await self._guard.vet(host, port, self._tenant, plaintext=True)
        loop = asyncio.get_running_loop()
        try:
            transport, _ = await loop.create_datagram_endpoint(
                asyncio.DatagramProtocol, remote_addr=(str(addresses[0]), port)
            )
        except OSError:
            raise NotSentError("connect") from None
        try:
            transport.sendto(data)
        except OSError:
            raise NotSentError("send") from None
        finally:
            transport.close()

    async def aclose(self) -> None:
        for stream in self._open:
            await stream.close()
        self._open.clear()
