# SPDX-License-Identifier: Apache-2.0
"""The egress allowlist (plugins-3 D8): read by the guard on every connect, within the tenant, with the entries for
every tenant; written only by the platform admin's CLI, each change audited in the tenant's chain (an entry for every
tenant in the platform's). An entry is a strict network (no host
bits set), never all addresses, and an entry for every tenant must be asked for explicitly."""

import ipaddress
import uuid
from collections.abc import Sequence

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dewpoint.core.audit.service import record
from dewpoint.core.db import tenant_scope
from dewpoint.core.egress.addresses import AllowEntry
from dewpoint.core.egress.guard import AllowlistSource
from dewpoint.core.models.egress import EgressAllowEntry


def _entry(row: EgressAllowEntry) -> AllowEntry:
    ports = (row.port_low, row.port_high) if row.port_low is not None and row.port_high is not None else None
    return AllowEntry(ipaddress.ip_network(str(row.network)), ports, row.tenant_id)


async def entries(s: AsyncSession, tenant_id: uuid.UUID) -> list[AllowEntry]:
    """The tenant's entries and those for every tenant. The caller has set the tenant's scope."""
    rows = await s.execute(
        select(EgressAllowEntry).where(
            or_(EgressAllowEntry.tenant_id.is_(None), EgressAllowEntry.tenant_id == tenant_id)
        )
    )
    return [_entry(row) for row in rows.scalars()]


def source(sessionmaker: async_sessionmaker[AsyncSession]) -> AllowlistSource:
    """What the guard reads on every connect: a transaction of its own, scoped to the tenant."""

    async def read(tenant_id: uuid.UUID) -> Sequence[AllowEntry]:
        async with sessionmaker() as s, s.begin():
            await tenant_scope(s, tenant_id)
            return await entries(s, tenant_id)

    return read


SHORTEST = {4: 8, 6: 8}  # a shorter prefix covers too much to be anything but deliberate
SENSITIVE = tuple(
    ipaddress.ip_network(n)
    for n in ("127.0.0.0/8", "169.254.0.0/16", "0.0.0.0/8", "224.0.0.0/4", "::1/128", "::/128", "fe80::/10", "ff00::/8")
)  # loopback, link-local (cloud metadata), unspecified and multicast


def sensitive(network: ipaddress.IPv4Network | ipaddress.IPv6Network) -> bool:
    if network.prefixlen < SHORTEST[network.version]:
        return True
    return any(n.version == network.version and network.overlaps(n) for n in SENSITIVE)


async def add(
    s: AsyncSession,
    *,
    network: str,
    ports: tuple[int, int] | None,
    tenant_id: uuid.UUID | None,
    note: str,
    every_tenant: bool = False,
    confirm_sensitive: bool = False,
) -> uuid.UUID:
    """A new entry, audited. Raises ValueError for a network that isn't strict or covers everything, a port range
    that isn't one, an entry for every tenant not asked for as such, or a sensitive network (a short prefix, loopback,
    link-local and its cloud metadata, unspecified, multicast) not confirmed."""
    try:
        parsed = ipaddress.ip_network(network, strict=True)
    except ValueError:
        raise ValueError("The network isn't a strict CIDR (no host bits set).") from None
    if parsed.prefixlen == 0:
        raise ValueError("An entry can't cover every address.")
    if sensitive(parsed) and not confirm_sensitive:
        raise ValueError("The network is sensitive (a short prefix, loopback, link-local or metadata): confirm it.")
    if ports is not None and not 1 <= ports[0] <= ports[1] <= 65535:
        raise ValueError("The ports must be a range within 1-65535.")
    if (tenant_id is None) != every_tenant:
        raise ValueError("An entry is for one tenant, or explicitly for every tenant.")
    row = EgressAllowEntry(
        network=str(parsed),
        port_low=ports[0] if ports else None,
        port_high=ports[1] if ports else None,
        tenant_id=tenant_id,
        note=note[:200],
    )
    s.add(row)
    await s.flush()
    await tenant_scope(s, tenant_id)  # the audit chain is the tenant's (the admin role's policy reads every row)
    await record(
        s,
        tenant_id=tenant_id,
        actor_id=None,
        action="egress_allowlist.add",
        target_type="egress_allowlist",
        target_id=str(row.id),
        details={"network": str(parsed), "ports": list(ports) if ports else None, "every_tenant": every_tenant},
    )
    return row.id


async def list_all(s: AsyncSession) -> list[EgressAllowEntry]:
    rows = await s.execute(select(EgressAllowEntry).order_by(EgressAllowEntry.created_at, EgressAllowEntry.id))
    return list(rows.scalars())


async def remove(s: AsyncSession, entry_id: uuid.UUID) -> bool:
    """Deletes the entry, audited; False when there was none."""
    found = await s.get(EgressAllowEntry, entry_id)
    if found is None:
        return False
    tenant_id = found.tenant_id
    await s.execute(delete(EgressAllowEntry).where(EgressAllowEntry.id == entry_id))
    await tenant_scope(s, tenant_id)
    await record(
        s,
        tenant_id=tenant_id,
        actor_id=None,
        action="egress_allowlist.remove",
        target_type="egress_allowlist",
        target_id=str(entry_id),
    )
    return True
