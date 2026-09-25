# SPDX-License-Identifier: Apache-2.0
import asyncio
import uuid

from sqlalchemy import select, text

from dewpoint.core.auth.users import create_user
from dewpoint.core.db import tenant_scope
from dewpoint.core.models.tenancy import Membership
from dewpoint.core.tenancy import service


async def test_concurrent_owner_removals_leave_one_owner(owner_sessionmaker, api_sessionmaker) -> None:
    tid = uuid.uuid4()
    async with owner_sessionmaker() as s, s.begin():
        a = await create_user(s, email="o1@corp.test", password="violet-otter-canyon-42")
        b = await create_user(s, email="o2@corp.test", password="violet-otter-canyon-42")
        await s.execute(text("insert into tenants(id,name,slug) values (:t,'T','race')"), {"t": tid})
        await s.execute(
            text("insert into memberships(tenant_id,user_id,role) values (:t,:a,'owner'),(:t,:b,'owner')"),
            {"t": tid, "a": a.id, "b": b.id},
        )

    async def remove(uid: uuid.UUID) -> str:
        try:
            async with api_sessionmaker() as s, s.begin():
                await tenant_scope(s, tid)
                await service.remove_member(s, tid, uid, actor_id=uid)  # each owner leaves the tenant
                await asyncio.sleep(0.2)  # hold the transaction open to force overlap
            return "removed"
        except service.LastOwnerError:
            return "last_owner"

    results = sorted(await asyncio.gather(remove(a.id), remove(b.id)))
    assert results == ["last_owner", "removed"]
    async with owner_sessionmaker() as s:
        owners = (await s.execute(select(Membership).where(Membership.role == "owner"))).scalars().all()
    assert len(owners) == 1
