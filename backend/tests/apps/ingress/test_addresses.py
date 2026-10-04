# SPDX-License-Identifier: Apache-2.0
"""A request's client address (the owner's ruling 11): the TCP peer, unless the peer is a configured proxy, in which
case `X-Forwarded-For` is read from its trusted end: right to left, past trusted hops only. With no proxy configured
(the default), a client's own `X-Forwarded-For` is ignored."""

from ipaddress import ip_address, ip_network

import pytest

from dewpoint.apps.ingress.addresses import client_address, limiter_key, parse_proxies

NGINX = parse_proxies("172.18.0.0/16")


def test_with_no_proxy_configured_a_forwarded_header_is_ignored() -> None:
    assert client_address("198.51.100.7", ["203.0.113.9"], ()) == ip_address("198.51.100.7")


def test_a_peer_that_is_no_proxy_is_the_client_whatever_it_forwards() -> None:
    assert client_address("198.51.100.7", ["203.0.113.9"], NGINX) == ip_address("198.51.100.7")


def test_a_trusted_proxy_forwards_the_client() -> None:
    assert client_address("172.18.0.5", ["203.0.113.9"], NGINX) == ip_address("203.0.113.9")


def test_a_spoofed_entry_left_of_the_trusted_end_is_never_the_client() -> None:
    # The client sent `X-Forwarded-For: 10.9.9.9`; the proxy appended the address it saw.
    assert client_address("172.18.0.5", ["10.9.9.9, 203.0.113.9"], NGINX) == ip_address("203.0.113.9")
    assert client_address("172.18.0.5", ["10.9.9.9", "203.0.113.9"], NGINX) == ip_address("203.0.113.9")


def test_trusted_hops_are_walked_past() -> None:
    two = parse_proxies("172.18.0.0/16, 192.0.2.10")
    assert client_address("172.18.0.5", ["203.0.113.9, 192.0.2.10"], two) == ip_address("203.0.113.9")


def test_an_unparsable_entry_stops_the_walk_at_the_last_address_trusted_to_have_seen_it() -> None:
    assert client_address("172.18.0.5", ["203.0.113.9, not-an-address"], NGINX) == ip_address("172.18.0.5")
    assert client_address("172.18.0.5", [], NGINX) == ip_address("172.18.0.5")


def test_no_peer_is_no_address() -> None:
    assert client_address(None, ["203.0.113.9"], NGINX) is None
    assert client_address("not-an-address", [], ()) is None


def test_an_ipv6_client_is_limited_by_its_64_and_an_ipv4_one_by_itself() -> None:
    assert limiter_key(ip_address("2001:db8:1:2:aaaa::1")) == limiter_key(ip_address("2001:db8:1:2:bbbb::2"))
    assert limiter_key(ip_address("2001:db8:1:2::1")) != limiter_key(ip_address("2001:db8:1:3::1"))
    assert limiter_key(ip_address("203.0.113.9")) != limiter_key(ip_address("203.0.113.10"))
    assert limiter_key(ip_address("::ffff:203.0.113.9")) == limiter_key(ip_address("203.0.113.9"))
    assert limiter_key(None) == "unknown"


def test_proxies_are_parsed_strictly() -> None:
    assert parse_proxies("") == ()
    assert parse_proxies(" 10.0.0.1 ,2001:db8::/32") == (ip_network("10.0.0.1/32"), ip_network("2001:db8::/32"))
    with pytest.raises(ValueError, match="DEWPOINT_INGRESS_TRUSTED_PROXIES"):
        parse_proxies("10.0.0.0/33")
    with pytest.raises(ValueError, match="DEWPOINT_INGRESS_TRUSTED_PROXIES"):
        parse_proxies("10.0.0.1/8")  # host bits set: say what's meant


def test_an_ipv4_client_on_a_dual_stack_socket_is_its_ipv4_address() -> None:
    assert client_address("::ffff:203.0.113.9", [], ()) == ip_address("203.0.113.9")
    assert client_address("172.18.0.5", ["::ffff:203.0.113.9"], NGINX) == ip_address("203.0.113.9")
    assert client_address("::ffff:172.18.0.5", ["203.0.113.9"], NGINX) == ip_address("203.0.113.9")
