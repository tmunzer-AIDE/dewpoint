# SPDX-License-Identifier: Apache-2.0
"""Which addresses the guard refuses unless an allowlist entry covers them (plugins-3 D7, D8).

The verdict never depends on the interpreter: Python's `ipaddress` calls multicast, site-local, IPv4-compatible and
NAT64 addresses global, and its tables changed within 3.12 (3.12.4, CVE-2024-4032; CI's 3.12.3 called `::ffff:8.8.8.8`
reserved). So an IPv4-mapped address is read as its IPv4, an address in the guard's own table of IANA special-purpose
ranges is refused, and `ipaddress`'s flags (not global, multicast, reserved, site-local) can only add a refusal, as can
an embedded IPv4 address (6to4, Teredo, NAT64, compatible) that is itself refused."""

import ipaddress
import uuid
from collections.abc import Iterable
from dataclasses import dataclass

type Address = ipaddress.IPv4Address | ipaddress.IPv6Address
type Network = ipaddress.IPv4Network | ipaddress.IPv6Network

NAT64 = (ipaddress.ip_network("64:ff9b::/96"), ipaddress.ip_network("64:ff9b:1::/48"))
COMPATIBLE = ipaddress.ip_network("::/96")
# IANA's special-purpose registries, every block that isn't globally reachable, and the ranges no service listens on
# (multicast, the reserved IPv4 class E, IPv6 site-local, and the transition prefixes that reach IPv4 through relays).
SPECIAL: tuple[Network, ...] = tuple(
    ipaddress.ip_network(n)
    for n in (
        "0.0.0.0/8", "10.0.0.0/8", "100.64.0.0/10", "127.0.0.0/8", "169.254.0.0/16", "172.16.0.0/12", "192.0.0.0/24",
        "192.0.2.0/24", "192.88.99.0/24", "192.168.0.0/16", "198.18.0.0/15", "198.51.100.0/24", "203.0.113.0/24",
        "224.0.0.0/4", "240.0.0.0/4", "255.255.255.255/32",
        "::/8", "64:ff9b::/96", "64:ff9b:1::/48", "100::/64", "2001::/23", "2001:db8::/32", "2002::/16", "3fff::/20",
        "5f00::/16", "fc00::/7", "fe80::/10", "fec0::/10", "ff00::/8",
    )
)  # fmt: skip


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
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        return blocked_reason(address.ipv4_mapped)  # a mapped address is its IPv4, whatever the interpreter says
    if any(net.version == address.version and address in net for net in SPECIAL):
        return "special"
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
