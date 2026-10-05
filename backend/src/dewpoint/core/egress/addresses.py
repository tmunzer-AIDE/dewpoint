# SPDX-License-Identifier: Apache-2.0
"""Which addresses the guard refuses unless an allowlist entry covers them (plugins-3 D7, D8).

Python's `is_global` alone isn't enough: it calls multicast, site-local, IPv4-compatible and NAT64 addresses global,
including NAT64-wrapped loopback. An address is refused when it isn't global, is multicast or reserved, is IPv6
site-local, or carries an embedded IPv4 address (mapped, compatible, 6to4, Teredo, NAT64) that is itself refused."""

import ipaddress
import uuid
from collections.abc import Iterable
from dataclasses import dataclass

type Address = ipaddress.IPv4Address | ipaddress.IPv6Address
type Network = ipaddress.IPv4Network | ipaddress.IPv6Network

NAT64 = (ipaddress.ip_network("64:ff9b::/96"), ipaddress.ip_network("64:ff9b:1::/48"))
COMPATIBLE = ipaddress.ip_network("::/96")


@dataclass(frozen=True)
class AllowEntry:
    """A platform admin's exception (D8): a network, optionally a port range, for one tenant or, explicitly, all."""

    network: Network
    ports: tuple[int, int] | None
    tenant_id: uuid.UUID | None


def _embedded(address: ipaddress.IPv6Address) -> list[ipaddress.IPv4Address]:
    found: list[ipaddress.IPv4Address] = []
    if address.ipv4_mapped is not None:
        found.append(address.ipv4_mapped)
    if address.sixtofour is not None:
        found.append(address.sixtofour)
    if address.teredo is not None:
        found.extend(address.teredo)
    if any(address in net for net in (*NAT64, COMPATIBLE)):
        found.append(ipaddress.IPv4Address(int(address) & 0xFFFFFFFF))
    return found


def blocked_reason(address: Address) -> str | None:
    """Why the guard refuses `address` without an allowlist entry, or None when it may be reached."""
    if address.is_multicast:
        return "multicast"
    if address.is_reserved:
        return "reserved"
    if isinstance(address, ipaddress.IPv6Address):
        if address.is_site_local:
            return "site_local"
        if any(blocked_reason(inner) is not None for inner in _embedded(address)):
            return "embedded"
    if not address.is_global:
        return "not_global"
    return None


def _plain(address: Address) -> Address:
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        return address.ipv4_mapped
    return address


def allowed(address: Address, port: int, tenant_id: uuid.UUID, entries: Iterable[AllowEntry]) -> bool:
    """Whether an allowlist entry for this tenant (or for every tenant) covers `address` and `port`."""
    target = _plain(address)
    for entry in entries:
        if entry.tenant_id is not None and entry.tenant_id != tenant_id:
            continue
        if entry.network.version != target.version or target not in entry.network:
            continue
        if entry.ports is not None and not entry.ports[0] <= port <= entry.ports[1]:
            continue
        return True
    return False
