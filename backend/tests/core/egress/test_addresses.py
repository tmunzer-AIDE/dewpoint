# SPDX-License-Identifier: Apache-2.0
"""Which destinations the guard refuses unless an allowlist entry covers them (plugins-3 D7): every non-global address,
including the ones Python's `is_global` calls global (multicast, site-local, NAT64- or compat-wrapped loopback)."""

import ipaddress
import uuid

import pytest

from dewpoint.core.egress.addresses import AllowEntry, allowed, blocked_reason

BLOCKED = [
    "127.0.0.1", "10.1.2.3", "172.16.0.1", "192.168.1.1", "169.254.169.254", "100.64.0.1", "0.0.0.0", "0.1.2.3",  # noqa: S104
    "198.18.0.1", "240.0.0.1", "255.255.255.255", "224.0.0.1", "239.1.1.1", "233.252.0.1",
    "::1", "::", "fe80::1", "fc00::1", "fd12:3456::1", "fec0::1", "ff02::1", "ff0e::1", "2001:db8::1", "100::1",
    "::ffff:127.0.0.1", "::ffff:10.0.0.1", "::127.0.0.1", "64:ff9b::7f00:1", "64:ff9b::a00:1", "64:ff9b:1::808:808",
    "2002:7f00:1::1", "2001:0:4136:e378:8000:63bf:80ff:fffe",
]  # fmt: skip
GLOBAL = ["8.8.8.8", "1.1.1.1", "34.94.226.50", "2001:4860:4860::8888", "2606:4700:4700::1111", "::ffff:8.8.8.8"]


@pytest.mark.parametrize("address", BLOCKED)
def test_non_global_addresses_are_blocked(address: str) -> None:
    assert blocked_reason(ipaddress.ip_address(address)) is not None


@pytest.mark.parametrize("address", GLOBAL)
def test_global_addresses_pass(address: str) -> None:
    assert blocked_reason(ipaddress.ip_address(address)) is None


def test_python_calls_these_global_and_the_guard_does_not() -> None:
    """The gaps that make `is_global` alone unsafe: if Python ever changes, the guard's own checks still hold."""
    for text in ("224.0.0.1", "fec0::1", "64:ff9b::7f00:1", "::127.0.0.1", "ff0e::1"):
        address = ipaddress.ip_address(text)
        assert address.is_global  # Python 3.14's answer, the reason the guard checks more
        assert blocked_reason(address) is not None


TENANT, OTHER = uuid.uuid4(), uuid.uuid4()


def _entry(network: str, ports: tuple[int, int] | None = None, tenant: uuid.UUID | None = TENANT) -> AllowEntry:
    return AllowEntry(network=ipaddress.ip_network(network), ports=ports, tenant_id=tenant)


def test_an_entry_covers_its_network_for_its_tenant_only() -> None:
    entries = [_entry("10.0.0.0/8")]
    assert allowed(ipaddress.ip_address("10.9.8.7"), 443, TENANT, entries)
    assert not allowed(ipaddress.ip_address("10.9.8.7"), 443, OTHER, entries)
    assert not allowed(ipaddress.ip_address("192.168.0.1"), 443, TENANT, entries)


def test_an_entry_for_every_tenant_is_explicit() -> None:
    entries = [_entry("10.0.0.0/8", tenant=None)]
    assert allowed(ipaddress.ip_address("10.0.0.1"), 443, OTHER, entries)


def test_a_port_range_limits_the_entry() -> None:
    entries = [_entry("10.0.0.0/8", ports=(8000, 8100))]
    assert allowed(ipaddress.ip_address("10.0.0.1"), 8080, TENANT, entries)
    assert not allowed(ipaddress.ip_address("10.0.0.1"), 443, TENANT, entries)


def test_a_mapped_address_is_matched_as_its_ipv4() -> None:
    entries = [_entry("10.0.0.0/8")]
    assert allowed(ipaddress.ip_address("::ffff:10.0.0.1"), 443, TENANT, entries)


def test_versions_never_cross() -> None:
    assert not allowed(ipaddress.ip_address("::1"), 443, TENANT, [_entry("127.0.0.0/8")])


def test_the_verdict_doesnt_depend_on_the_pythons_patch_level(monkeypatch: pytest.MonkeyPatch) -> None:
    """CI's CPython 3.12.3 called `::ffff:8.8.8.8` reserved; 3.12.4 changed how `ipaddress` classifies special ranges
    (CVE-2024-4032). The guard keeps its own table of non-global ranges and reads a mapped address as its IPv4: even an
    `ipaddress` that calls every address global and none special refuses every special one."""
    for cls in (ipaddress.IPv4Address, ipaddress.IPv6Address):
        monkeypatch.setattr(cls, "is_global", property(lambda self: True))
        for flag in ("is_multicast", "is_reserved", "is_private", "is_loopback", "is_link_local"):
            monkeypatch.setattr(cls, flag, property(lambda self: False))
    monkeypatch.setattr(ipaddress.IPv6Address, "is_site_local", property(lambda self: False))
    for address in BLOCKED:
        assert blocked_reason(ipaddress.ip_address(address)) is not None, address
    for address in GLOBAL:
        assert blocked_reason(ipaddress.ip_address(address)) is None, address


def test_a_mapped_address_is_read_as_its_ipv4() -> None:
    assert blocked_reason(ipaddress.ip_address("::ffff:8.8.8.8")) is None
    assert blocked_reason(ipaddress.ip_address("::ffff:10.0.0.1")) is not None
