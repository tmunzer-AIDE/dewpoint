# SPDX-License-Identifier: Apache-2.0
"""The guard's vetting (plugins-3 D7): every resolved address is checked, one refused address refuses the destination,
plain http needs an allowlist entry for every address, and the allowlist is read on every connect."""

import ipaddress
import uuid
from collections.abc import Sequence

import pytest

from dewpoint.core.egress.addresses import Address, AllowEntry
from dewpoint.core.egress.guard import EgressRefusedError, Guard, NotSentError

TENANT = uuid.uuid4()
LAST: list[list[uuid.UUID]] = []  # the allowlist reads of the guard made last


class FakeResolver:
    def __init__(self, answers: dict[str, list[str]], fail: bool = False) -> None:
        self.answers, self.fail, self.asked = answers, fail, []

    async def resolve(self, host: str, port: int) -> Sequence[Address]:
        self.asked.append(host)
        if self.fail:
            raise OSError("no such host")
        return [ipaddress.ip_address(a) for a in self.answers.get(host, [])]


def _guard(answers: dict[str, list[str]], entries: list[AllowEntry] | None = None, fail: bool = False) -> Guard:
    reads: list[uuid.UUID] = []

    async def allowlist(tenant_id: uuid.UUID) -> list[AllowEntry]:
        reads.append(tenant_id)
        return list(entries or [])

    guard = Guard(resolver=FakeResolver(answers, fail), allowlist=allowlist)
    LAST.clear()
    LAST.append(reads)
    return guard


async def test_a_public_name_passes_with_all_its_addresses() -> None:
    guard = _guard({"api.example.com": ["93.184.216.34", "2606:2800:220:1::1"]})
    found = await guard.vet("api.example.com", 443, TENANT)
    assert [str(a) for a in found] == ["93.184.216.34", "2606:2800:220:1::1"]


async def test_one_private_answer_refuses_the_whole_name() -> None:
    guard = _guard({"mixed.example.com": ["93.184.216.34", "10.0.0.5"]})
    with pytest.raises(EgressRefusedError):
        await guard.vet("mixed.example.com", 443, TENANT)


async def test_literal_addresses_are_vetted_without_resolving() -> None:
    guard = _guard({})
    with pytest.raises(EgressRefusedError):
        await guard.vet("169.254.169.254", 80, TENANT)
    with pytest.raises(EgressRefusedError):
        await guard.vet("[::1]", 443, TENANT)
    assert guard.resolver.asked == []  # type: ignore[attr-defined]


async def test_an_allowlist_entry_lets_a_private_destination_through() -> None:
    entry = AllowEntry(ipaddress.ip_network("10.0.0.0/8"), None, TENANT)
    guard = _guard({"llm.internal": ["10.0.0.5"]}, [entry])
    assert [str(a) for a in await guard.vet("llm.internal", 8443, TENANT)] == ["10.0.0.5"]


async def test_the_allowlist_is_read_on_every_connect() -> None:
    guard = _guard({"api.example.com": ["93.184.216.34"]})
    await guard.vet("api.example.com", 443, TENANT)
    await guard.vet("api.example.com", 443, TENANT)
    assert LAST[0] == [TENANT, TENANT]


async def test_no_answer_or_a_resolver_failure_means_nothing_was_sent() -> None:
    with pytest.raises(NotSentError):
        await _guard({}).vet("nowhere.example.com", 443, TENANT)
    with pytest.raises(NotSentError):
        await _guard({}, fail=True).vet("api.example.com", 443, TENANT)


async def test_plain_http_needs_every_address_allowlisted() -> None:
    guard = _guard({"api.example.com": ["93.184.216.34"]})
    with pytest.raises(EgressRefusedError):
        await guard.vet("api.example.com", 80, TENANT, plaintext=True)
    entry = AllowEntry(ipaddress.ip_network("93.184.216.0/24"), (80, 80), TENANT)
    guard = _guard({"api.example.com": ["93.184.216.34"]}, [entry])
    assert await guard.vet("api.example.com", 80, TENANT, plaintext=True)


async def test_a_refusal_names_no_host_or_address() -> None:
    guard = _guard({"secret-host.example.com": ["10.0.0.5"]})
    with pytest.raises(EgressRefusedError) as raised:
        await guard.vet("secret-host.example.com", 443, TENANT)
    assert "secret-host" not in str(raised.value) and "10.0.0.5" not in str(raised.value)
