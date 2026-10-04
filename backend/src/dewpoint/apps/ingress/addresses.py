# SPDX-License-Identifier: Apache-2.0
"""A request's client address (the owner's ruling 11). `X-Forwarded-For` is believed only from a configured proxy
(`DEWPOINT_INGRESS_TRUSTED_PROXIES`, none by default), read from its trusted end: right to left, past trusted hops
only, so an entry a client wrote itself is never its address. An IPv6 client is limited by its /64, which one host
usually holds whole."""

from collections.abc import Sequence
from ipaddress import IPv4Address, IPv4Network, IPv6Address, IPv6Network, ip_address, ip_network

type Address = IPv4Address | IPv6Address
type Network = IPv4Network | IPv6Network


def parse_proxies(raw: str) -> tuple[Network, ...]:
    """Comma- or space-separated addresses and networks. Raises ValueError, naming the setting, for any entry that isn't
    one, a network with host bits set included: a bad value must never trust the wrong peers."""
    networks = []
    for entry in raw.replace(",", " ").split():
        try:
            networks.append(ip_network(entry))
        except ValueError:
            raise ValueError(f"DEWPOINT_INGRESS_TRUSTED_PROXIES: not an address or network: {entry!r}") from None
    return tuple(networks)


def _parse(text: str) -> Address | None:
    """An address, an IPv4 client on a dual-stack socket (`::ffff:a.b.c.d`) as its IPv4 address."""
    try:
        address = ip_address(text.strip())
    except ValueError:
        return None
    if isinstance(address, IPv6Address) and address.ipv4_mapped is not None:
        return address.ipv4_mapped
    return address


def client_address(peer: str | None, forwarded: Sequence[str], trusted: Sequence[Network]) -> Address | None:
    """The client's address: the peer's, or, from a trusted peer, the rightmost forwarded entry past trusted hops. An
    entry that isn't an address stops the walk at the last address trusted to have seen it."""
    current = _parse(peer) if peer else None
    if current is None:
        return None
    entries = [entry for value in forwarded for entry in value.split(",")]
    for entry in reversed(entries):
        if not any(current in network for network in trusted):
            break
        parsed = _parse(entry)
        if parsed is None:
            break
        current = parsed
    return current


def limiter_key(address: Address | None) -> str:
    if address is None:
        return "unknown"
    if isinstance(address, IPv6Address):
        if address.ipv4_mapped is not None:
            return str(address.ipv4_mapped)
        return str(ip_network(f"{address}/64", strict=False))
    return str(address)
