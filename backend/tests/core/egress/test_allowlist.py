# SPDX-License-Identifier: Apache-2.0
"""The allowlist as the guard reads it (plugins-3 D8): from the database on every connect, within the tenant, with the
entries for every tenant; and as the platform admin manages it, audited."""

import ipaddress
import uuid

import pytest
from sqlalchemy import text

from dewpoint.core.egress import allowlist
from dewpoint.core.egress.addresses import AllowEntry


async def tenant(owner) -> uuid.UUID:  # type: ignore[no-untyped-def]
    tid = uuid.uuid4()
    async with owner() as s, s.begin():
        await s.execute(
            text("insert into tenants (id, name, slug) values (:i, 't', :s)"), {"i": tid, "s": tid.hex[:12]}
        )
    return tid


async def test_the_source_reads_the_tenants_and_the_shared_entries(
    owner_sessionmaker, admin_sessionmaker, worker_sessionmaker
) -> None:
    a, b = await tenant(owner_sessionmaker), await tenant(owner_sessionmaker)
    async with admin_sessionmaker() as s, s.begin():
        await allowlist.add(s, network="10.1.0.0/16", ports=(443, 443), tenant_id=a, note="llm")
        await allowlist.add(s, network="10.2.0.0/16", ports=None, tenant_id=b, note="other")
        await allowlist.add(s, network="fd00::/8", ports=None, tenant_id=None, note="shared", every_tenant=True)
    source = allowlist.source(worker_sessionmaker)
    found = set(await source(a))
    assert found == {
        AllowEntry(ipaddress.ip_network("10.1.0.0/16"), (443, 443), a),
        AllowEntry(ipaddress.ip_network("fd00::/8"), None, None),
    }


async def test_a_shared_entry_must_be_asked_for_explicitly(admin_sessionmaker) -> None:
    async with admin_sessionmaker() as s, s.begin():
        with pytest.raises(ValueError, match="every tenant"):
            await allowlist.add(s, network="10.0.0.0/8", ports=None, tenant_id=None, note="")


@pytest.mark.parametrize("network", ["10.0.0.1/8", "not-a-network", "0.0.0.0/0"])
async def test_an_entry_is_a_strict_network_that_isnt_everything(
    owner_sessionmaker, admin_sessionmaker, network
) -> None:  # type: ignore[no-untyped-def]
    a = await tenant(owner_sessionmaker)
    async with admin_sessionmaker() as s, s.begin():
        with pytest.raises(ValueError):
            await allowlist.add(s, network=network, ports=None, tenant_id=a, note="")


async def test_adding_and_removing_are_audited_and_listed(owner_sessionmaker, admin_sessionmaker) -> None:
    a = await tenant(owner_sessionmaker)
    async with admin_sessionmaker() as s, s.begin():
        entry_id = await allowlist.add(s, network="10.1.0.0/16", ports=None, tenant_id=a, note="llm")
    async with admin_sessionmaker() as s, s.begin():
        listed = await allowlist.list_all(s)
        assert [(e.id, str(e.network), e.tenant_id, e.note) for e in listed] == [(entry_id, "10.1.0.0/16", a, "llm")]
        assert await allowlist.remove(s, entry_id) is True
        assert await allowlist.remove(s, entry_id) is False
    async with owner_sessionmaker() as s:
        actions = (
            await s.execute(
                text("select action from audit_log where target_id = :i order by seq"), {"i": str(entry_id)}
            )
        ).scalars()
        assert list(actions) == ["egress_allowlist.add", "egress_allowlist.remove"]


@pytest.mark.parametrize(
    "network", ["0.0.0.0/1", "::/1", "127.0.0.0/8", "169.254.169.254/32", "fe80::/10", "10.0.0.0/7", "::1/128"]
)
async def test_a_sensitive_entry_must_be_confirmed(owner_sessionmaker, admin_sessionmaker, network) -> None:  # type: ignore[no-untyped-def]
    """The review's finding 7: broad networks, loopback, link-local and cloud metadata need an explicit confirmation."""
    a = await tenant(owner_sessionmaker)
    async with admin_sessionmaker() as s, s.begin():
        with pytest.raises(ValueError, match="sensitive"):
            await allowlist.add(s, network=network, ports=None, tenant_id=a, note="")
    async with admin_sessionmaker() as s, s.begin():
        await allowlist.add(s, network=network, ports=None, tenant_id=a, note="", confirm_sensitive=True)
