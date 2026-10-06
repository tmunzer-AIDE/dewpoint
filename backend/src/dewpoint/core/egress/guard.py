# SPDX-License-Identifier: Apache-2.0
"""The guard's vetting (plugins-3 D7, D8): a destination is reachable only when every address its name resolves to is
global or covered by an allowlist entry for the tenant; plain-text protocols need an entry for every address. The
allowlist is read on every connect. Errors carry what happened to the request and never the host or an address."""

import asyncio
import ipaddress
import socket
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Protocol

from dewpoint.core.egress.addresses import Address, AllowEntry, allowed, blocked_reason

type AllowlistSource = Callable[[uuid.UUID], Awaitable[Sequence[AllowEntry]]]


class EgressRefusedError(Exception):
    """The destination isn't allowed. Nothing was sent; retrying can't change it."""

    def __init__(self, reason: str) -> None:
        super().__init__("The destination isn't allowed.")
        self.reason = reason


class NotSentError(Exception):
    """Nothing left this process (no address, no connection): a retry is safe."""

    def __init__(self, reason: str) -> None:
        super().__init__("The request wasn't sent.")
        self.reason = reason


class MaybeSentError(Exception):
    """The request may have reached the destination: its outcome is unknown."""

    def __init__(self, reason: str) -> None:
        super().__init__("The request may have been sent.")
        self.reason = reason


class InvalidRequestError(Exception):
    """The request can't be sent as given (scheme, credentials in the URL, a header with CR/LF, a datagram too large):
    nothing was sent."""

    def __init__(self, reason: str) -> None:
        super().__init__("The request is invalid.")
        self.reason = reason


class TlsVerificationError(Exception):
    """The destination's TLS didn't verify for its name: nothing was sent, and retrying won't change that."""

    def __init__(self) -> None:
        super().__init__("The destination's certificate didn't verify.")


class Resolver(Protocol):
    async def resolve(self, host: str, port: int) -> Sequence[Address]: ...


class SystemResolver:
    """The operating system's resolver, every answer kept (the guard vets them all)."""

    async def resolve(self, host: str, port: int) -> Sequence[Address]:
        infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
        found: list[Address] = []
        for *_, sockaddr in infos:
            address = ipaddress.ip_address(sockaddr[0])
            if address not in found:
                found.append(address)
        return found


def literal(host: str) -> Address | None:
    try:
        return ipaddress.ip_address(host.removeprefix("[").removesuffix("]"))
    except ValueError:
        return None


@dataclass(frozen=True)
class Guard:
    resolver: Resolver
    allowlist: AllowlistSource

    async def vet(self, host: str, port: int, tenant_id: uuid.UUID, *, plaintext: bool = False) -> list[Address]:
        """Every address `host` resolves to, once all of them pass. Raises EgressRefusedError or NotSentError."""
        fixed = literal(host)
        if fixed is not None:
            addresses: list[Address] = [fixed]
        else:
            try:
                addresses = list(await self.resolver.resolve(host, port))
            except (OSError, UnicodeError):
                raise NotSentError("dns") from None
            if not addresses:
                raise NotSentError("dns")
        entries = list(await self.allowlist(tenant_id))
        for address in addresses:
            covered = allowed(address, port, tenant_id, entries)
            if plaintext and not covered:
                raise EgressRefusedError("plaintext")
            reason = blocked_reason(address)
            if reason is not None and not covered:
                raise EgressRefusedError(reason)
        return addresses
