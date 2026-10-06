# SPDX-License-Identifier: Apache-2.0
"""The API's side of plugin calls (plugins-3 D3): a tenant's cap on outstanding calls holds across concurrent asks in
any number of API processes (the owner's review of 3a-2, finding 2)."""

import asyncio
import uuid
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from dewpoint.core.plugins import asking, calls


async def tenant(owner: Any) -> uuid.UUID:
    tid = uuid.uuid4()
    async with owner() as s, s.begin():
        await s.execute(
            text("insert into tenants (id, name, slug) values (:i, 't', :s)"), {"i": tid, "s": tid.hex[:12]}
        )
    return tid


async def _outstanding(owner: Any, tid: uuid.UUID) -> int:
    async with owner() as s:
        found = await s.execute(text("select count(*) from plugin_calls where tenant_id = :t"), {"t": tid})
        return int(found.scalar_one())


async def test_two_asks_at_the_cap_admit_only_one(
    owner_sessionmaker, api_sessionmaker, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(asking, "MAX_PER_TENANT", 8)
    tid = await tenant(owner_sessionmaker)

    async def options(s: AsyncSession) -> uuid.UUID:
        return await calls.ask_options(
            s, tid, node_ref="demo.pick@1", field="site_id", connection_id=None, revision=None, query="",
            type_hash=None,
        )  # fmt: skip

    for _ in range(7):
        await asking._ask(api_sessionmaker, tid, options)

    async def slowly(s: AsyncSession) -> uuid.UUID:
        await asyncio.sleep(0.3)  # both asks have counted before either inserts, unless admission is serialized
        return await options(s)

    results = await asyncio.gather(
        asking._ask(api_sessionmaker, tid, slowly), asking._ask(api_sessionmaker, tid, slowly), return_exceptions=True
    )
    assert sorted(type(r).__name__ for r in results) == ["TooManyCallsError", "UUID"]
    assert await _outstanding(owner_sessionmaker, tid) == 8
