# SPDX-License-Identifier: Apache-2.0
import uuid

from sqlalchemy import text

from dewpoint.core.db import tenant_scope, user_scope


async def test_scopes_are_exclusive(api_sessionmaker) -> None:
    tid, uid = uuid.uuid4(), uuid.uuid4()
    q = text("select current_setting('app.tenant_id', true), current_setting('app.user_id', true)")
    async with api_sessionmaker() as s, s.begin():
        await user_scope(s, uid)
        assert tuple((await s.execute(q)).one()) == ("", str(uid))
        await tenant_scope(s, tid)
        assert tuple((await s.execute(q)).one()) == (str(tid), "")


async def test_tenant_scope_is_transaction_local(api_sessionmaker) -> None:
    tid = uuid.uuid4()
    async with api_sessionmaker() as s:
        async with s.begin():
            await tenant_scope(s, tid)
            assert (await s.execute(text("select current_setting('app.tenant_id', true)"))).scalar_one() == str(tid)
        async with s.begin():
            value = (await s.execute(text("select current_setting('app.tenant_id', true)"))).scalar_one()
            assert value in (None, "")


async def test_group_roles_exist(owner_sessionmaker) -> None:
    async with owner_sessionmaker() as s:
        rows = (await s.execute(text("select rolname from pg_roles where rolname like 'dewpoint_%'"))).scalars().all()
    assert {"dewpoint_api", "dewpoint_ingress", "dewpoint_dispatch", "dewpoint_worker", "dewpoint_admin"} <= set(rows)
