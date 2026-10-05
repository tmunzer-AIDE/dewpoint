# SPDX-License-Identifier: Apache-2.0
"""Migration 0041's tables (plugins-3 D8, D9, D25).

`egress_allowlist` is platform configuration: only the admin role writes it; the API and the worker read, under forced
row-level security, the entries for their tenant and those explicitly for every tenant. An entry never covers every
address, and a port range is a range. `rate_buckets` is tenant data: the worker keeps it, the API reads it (the
connection's current cooldown), each within its tenant; a bucket's tokens stay within its capacity."""

import uuid
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from dewpoint.core.db import tenant_scope


async def tenant(owner: Any) -> uuid.UUID:
    tid = uuid.uuid4()
    async with owner() as s, s.begin():
        await s.execute(
            text("insert into tenants (id, name, slug) values (:i, 't', :s)"), {"i": tid, "s": tid.hex[:12]}
        )
    return tid


async def add_entry(admin: Any, network: str, tid: uuid.UUID | None, ports: tuple[int, int] | None = None) -> uuid.UUID:
    eid = uuid.uuid4()
    async with admin() as s, s.begin():
        await s.execute(
            text(
                "insert into egress_allowlist (id, network, port_low, port_high, tenant_id, note) "
                "values (:i, cast(:n as cidr), :lo, :hi, :t, 'test')"
            ),
            {"i": eid, "n": network, "lo": ports[0] if ports else None, "hi": ports[1] if ports else None, "t": tid},
        )
    return eid


@pytest.mark.parametrize("table", ["egress_allowlist", "rate_buckets"])
async def test_tables_force_row_level_security(owner_sessionmaker, table: str) -> None:
    async with owner_sessionmaker() as s:
        query = text("select relrowsecurity, relforcerowsecurity from pg_class where relname = :t")
        assert tuple((await s.execute(query, {"t": table})).one()) == (True, True)


async def test_services_read_their_tenants_entries_and_the_shared_ones(
    owner_sessionmaker, admin_sessionmaker, api_sessionmaker, worker_sessionmaker
) -> None:
    a, b = await tenant(owner_sessionmaker), await tenant(owner_sessionmaker)
    mine = await add_entry(admin_sessionmaker, "10.1.0.0/16", a)
    theirs = await add_entry(admin_sessionmaker, "10.2.0.0/16", b)
    shared = await add_entry(admin_sessionmaker, "10.3.0.0/16", None)
    for maker in (api_sessionmaker, worker_sessionmaker):
        async with maker() as s, s.begin():
            await tenant_scope(s, a)
            seen = set((await s.execute(text("select id from egress_allowlist"))).scalars())
        assert seen == {mine, shared} and theirs not in seen


async def test_only_the_admin_role_writes_the_allowlist(
    owner_sessionmaker, admin_sessionmaker, api_sessionmaker, worker_sessionmaker
) -> None:
    a = await tenant(owner_sessionmaker)
    eid = await add_entry(admin_sessionmaker, "10.1.0.0/16", a)
    for maker in (api_sessionmaker, worker_sessionmaker):
        for statement in (
            "insert into egress_allowlist (network, tenant_id, note) values ('10.9.0.0/16', :t, 'x')",
            "update egress_allowlist set note = 'y' where id = :i",
            "delete from egress_allowlist where id = :i",
        ):
            with pytest.raises(DBAPIError, match="permission denied"):
                async with maker() as s, s.begin():
                    await tenant_scope(s, a)
                    await s.execute(text(statement), {"t": a, "i": eid})
    async with admin_sessionmaker() as s, s.begin():
        await s.execute(text("delete from egress_allowlist where id = :i"), {"i": eid})


@pytest.mark.parametrize(
    ("network", "ports"),
    [
        ("0.0.0.0/0", None),
        ("::/0", None),
        ("10.0.0.0/8", (443, 80)),
        ("10.0.0.0/8", (0, 80)),
        ("10.0.0.0/8", (1, 70000)),
    ],
)
async def test_an_entry_never_covers_everything_and_its_ports_are_a_range(
    owner_sessionmaker, admin_sessionmaker, network: str, ports: tuple[int, int] | None
) -> None:
    a = await tenant(owner_sessionmaker)
    with pytest.raises(IntegrityError):
        await add_entry(admin_sessionmaker, network, a, ports)


async def test_one_port_bound_alone_is_refused(owner_sessionmaker, admin_sessionmaker) -> None:
    a = await tenant(owner_sessionmaker)
    with pytest.raises(IntegrityError):
        async with admin_sessionmaker() as s, s.begin():
            await s.execute(
                text(
                    "insert into egress_allowlist (network, port_low, tenant_id, note) "
                    "values ('10.0.0.0/8', 80, :t, '')"
                ),
                {"t": a},
            )


BUCKET = text(
    "insert into rate_buckets (tenant_id, scope, capacity, refill_per_s, tokens, refilled_at) "
    "values (:t, :sc, 50, 1.25, :tok, now())"
)


async def test_the_worker_keeps_buckets_and_the_api_only_reads_them(
    owner_sessionmaker, api_sessionmaker, worker_sessionmaker
) -> None:
    a, b = await tenant(owner_sessionmaker), await tenant(owner_sessionmaker)
    async with worker_sessionmaker() as s, s.begin():
        await tenant_scope(s, a)
        await s.execute(BUCKET, {"t": a, "sc": "mist.org:x", "tok": 50})
        await s.execute(text("update rate_buckets set tokens = 49, blocked_until = now() where scope = 'mist.org:x'"))
    async with api_sessionmaker() as s, s.begin():
        await tenant_scope(s, a)
        assert (await s.execute(text("select count(*) from rate_buckets"))).scalar_one() == 1
    async with api_sessionmaker() as s, s.begin():
        await tenant_scope(s, b)
        assert (await s.execute(text("select count(*) from rate_buckets"))).scalar_one() == 0
    with pytest.raises(DBAPIError, match="permission denied"):
        async with api_sessionmaker() as s, s.begin():
            await tenant_scope(s, a)
            await s.execute(text("update rate_buckets set tokens = 50"))
    with pytest.raises(DBAPIError):  # another tenant's row: refused by the policy
        async with worker_sessionmaker() as s, s.begin():
            await tenant_scope(s, a)
            await s.execute(BUCKET, {"t": b, "sc": "mist.org:y", "tok": 50})


@pytest.mark.parametrize("tokens", [-1, 51])
async def test_tokens_stay_within_capacity(owner_sessionmaker, worker_sessionmaker, tokens: int) -> None:
    a = await tenant(owner_sessionmaker)
    with pytest.raises(IntegrityError):
        async with worker_sessionmaker() as s, s.begin():
            await tenant_scope(s, a)
            await s.execute(BUCKET, {"t": a, "sc": "mist.org:x", "tok": tokens})
