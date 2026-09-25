# SPDX-License-Identifier: Apache-2.0
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from dewpoint.core.audit.service import record, verify_chain
from dewpoint.core.db import tenant_scope


async def test_append_and_verify(api_sessionmaker, owner_sessionmaker) -> None:
    t = uuid.uuid4()
    async with api_sessionmaker() as s, s.begin():
        await tenant_scope(s, t)
        for i in range(3):
            await record(
                s, tenant_id=t, actor_id=None, action="member.add", target_id=str(i), details={"role": "viewer"}
            )
        await record(s, tenant_id=None, actor_id=None, action="auth.login")
    async with owner_sessionmaker() as s:
        rep = await verify_chain(s, str(t))
        assert rep.ok and rep.checked == 3 and rep.head_seq is not None
        assert (await verify_chain(s, "platform")).checked == 1


async def test_service_role_cannot_mutate_or_forge(api_sessionmaker) -> None:
    t = uuid.uuid4()
    async with api_sessionmaker() as s, s.begin():
        await tenant_scope(s, t)
        await record(s, tenant_id=t, actor_id=None, action="tenant.update")
    for stmt in (
        "update audit_log set action='x'",
        "delete from audit_log",
        "insert into audit_log(scope,action,prev_hash,hash) values ('x','y','\\x00','\\x00')",
    ):
        with pytest.raises(DBAPIError):
            async with api_sessionmaker() as s, s.begin():
                await tenant_scope(s, t)
                await s.execute(text(stmt))


async def test_cannot_append_for_other_tenant(api_sessionmaker) -> None:
    with pytest.raises(DBAPIError, match="audit tenant mismatch"):
        async with api_sessionmaker() as s, s.begin():
            await tenant_scope(s, uuid.uuid4())
            await record(s, tenant_id=uuid.uuid4(), actor_id=None, action="member.add")


async def test_tamper_detected(api_sessionmaker, owner_sessionmaker) -> None:
    t = uuid.uuid4()
    async with api_sessionmaker() as s, s.begin():
        await tenant_scope(s, t)
        for i in range(3):
            await record(s, tenant_id=t, actor_id=None, action="member.add", target_id=str(i))
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(text("SET LOCAL session_replication_role = replica"))  # superuser bypasses triggers
        await s.execute(text("update audit_log set target_id='evil' where target_id='1'"))
    async with owner_sessionmaker() as s:
        rep = await verify_chain(s, str(t))
    assert not rep.ok and rep.first_bad_seq is not None


def test_secret_keys_rejected() -> None:
    import asyncio

    with pytest.raises(ValueError):
        asyncio.run(record(None, tenant_id=None, actor_id=None, action="x", details={"api_token": "t"}))  # type: ignore[arg-type]
