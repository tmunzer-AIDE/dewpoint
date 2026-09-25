# SPDX-License-Identifier: Apache-2.0
import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from dewpoint.core.db import tenant_scope, user_scope
from dewpoint.core.models.tenancy import Membership, Tenant


async def _seed(owner_sessionmaker) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    a, b, u = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(text("insert into users(id,email,password_hash) values (:u,'u@x.test','h')"), {"u": u})
        await s.execute(text("insert into tenants(id,name,slug) values (:a,'A','a'),(:b,'B','b')"), {"a": a, "b": b})
        await s.execute(
            text("insert into memberships(tenant_id,user_id,role) values (:a,:u,'editor')"), {"a": a, "u": u}
        )
    return a, b, u


async def test_no_context_sees_nothing(owner_sessionmaker, api_sessionmaker) -> None:
    await _seed(owner_sessionmaker)
    async with api_sessionmaker() as s, s.begin():
        assert (await s.execute(select(Tenant))).scalars().all() == []
        assert (await s.execute(select(Membership))).scalars().all() == []


async def test_tenant_context_isolates(owner_sessionmaker, api_sessionmaker) -> None:
    a, b, _ = await _seed(owner_sessionmaker)
    async with api_sessionmaker() as s, s.begin():
        await tenant_scope(s, b)
        assert [t.id for t in (await s.execute(select(Tenant))).scalars()] == [b]
        assert (await s.execute(select(Membership))).scalars().all() == []


async def test_user_context_lists_own_memberships(owner_sessionmaker, api_sessionmaker) -> None:
    a, _, u = await _seed(owner_sessionmaker)
    async with api_sessionmaker() as s, s.begin():
        await user_scope(s, u)
        assert [m.tenant_id for m in (await s.execute(select(Membership))).scalars()] == [a]
        assert [t.id for t in (await s.execute(select(Tenant))).scalars()] == [a]


async def test_tenant_scope_does_not_leak_callers_other_tenants(owner_sessionmaker, api_sessionmaker) -> None:
    a, b, u = await _seed(owner_sessionmaker)
    async with owner_sessionmaker() as s, s.begin():  # u belongs to BOTH tenants
        await s.execute(
            text("insert into memberships(tenant_id,user_id,role) values (:b,:u,'viewer')"), {"b": b, "u": u}
        )
    async with api_sessionmaker() as s, s.begin():
        await user_scope(s, u)
        assert len((await s.execute(select(Membership))).scalars().all()) == 2
        await tenant_scope(s, b)  # what require() does after the membership check
        assert [m.tenant_id for m in (await s.execute(select(Membership))).scalars()] == [b]
        assert [t.id for t in (await s.execute(select(Tenant))).scalars()] == [b]


async def test_cross_tenant_insert_rejected(owner_sessionmaker, api_sessionmaker) -> None:
    a, b, u = await _seed(owner_sessionmaker)
    with pytest.raises(DBAPIError, match="row-level security"):
        async with api_sessionmaker() as s, s.begin():
            await tenant_scope(s, a)
            s.add(Membership(tenant_id=b, user_id=u, role="viewer"))
