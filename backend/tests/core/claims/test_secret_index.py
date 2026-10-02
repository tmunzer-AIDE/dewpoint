# SPDX-License-Identifier: Apache-2.0
"""A run tree's secret index (engine 2b spec §3.7): every string of 4 characters or more found in a tainted claim of
the tree, in one encrypted row with a version. Admission seeds it; each tainted claim extends it, one extension at a
time; past its bounds an extension is refused, permanently, and nothing changes."""

import asyncio
import uuid
from typing import Any

import pytest
from sqlalchemy import text

from dewpoint.core.claims import secret_index
from dewpoint.core.claims.cipher import ClaimCipher
from dewpoint.core.db import tenant_scope
from tests.support.keys import FixtureKeys

CIPHER = ClaimCipher(FixtureKeys(), purpose=secret_index.PURPOSE)


async def a_tenant(owner: Any) -> uuid.UUID:
    tenant = uuid.uuid4()
    async with owner() as s, s.begin():
        await s.execute(
            text("insert into tenants(id,name,slug) values (:t,'T',:slug)"), {"t": tenant, "slug": str(tenant)}
        )
    return tenant


async def extend(sm: Any, tenant: uuid.UUID, root: uuid.UUID, strings: list[str]) -> secret_index.Index:
    async with sm() as s, s.begin():
        await tenant_scope(s, tenant)
        return await secret_index.extend(s, CIPHER, tenant, root, strings)


async def read(sm: Any, tenant: uuid.UUID, root: uuid.UUID) -> secret_index.Index:
    async with sm() as s, s.begin():
        await tenant_scope(s, tenant)
        return await secret_index.read(s, CIPHER, tenant, root)


async def test_admission_seeds_it_and_each_extension_makes_a_new_version(
    owner_sessionmaker, dispatch_sessionmaker, worker_sessionmaker
) -> None:
    tenant, root = await a_tenant(owner_sessionmaker), uuid.uuid4()
    seeded = await extend(dispatch_sessionmaker, tenant, root, ["t0ken-1", "abc", "t0ken-1"])
    assert (seeded.version, seeded.strings) == (1, ("t0ken-1",))  # unique, and never under 4 characters
    grown = await extend(worker_sessionmaker, tenant, root, ["pw-1234"])
    assert (grown.version, grown.strings) == (2, ("pw-1234", "t0ken-1"))
    assert await extend(worker_sessionmaker, tenant, root, ["t0ken-1"]) == grown  # nothing new: no new version
    assert await read(worker_sessionmaker, tenant, root) == grown
    async with owner_sessionmaker() as s:
        raw = (await s.execute(text("select ciphertext from run_secret_index"))).scalar_one()
    assert b"t0ken" not in raw


async def test_a_tree_without_an_index_reads_empty(owner_sessionmaker, worker_sessionmaker) -> None:
    tenant = await a_tenant(owner_sessionmaker)
    assert await read(worker_sessionmaker, tenant, uuid.uuid4()) == secret_index.Index(0, ())


async def test_concurrent_extensions_all_land(owner_sessionmaker, worker_sessionmaker) -> None:
    tenant, root = await a_tenant(owner_sessionmaker), uuid.uuid4()
    await extend(worker_sessionmaker, tenant, root, ["seed-0000"])
    await asyncio.gather(*(extend(worker_sessionmaker, tenant, root, [f"value-{i:04d}"]) for i in range(8)))
    final = await read(worker_sessionmaker, tenant, root)
    assert final.version == 9 and len(final.strings) == 9


@pytest.mark.parametrize("bound", ["strings", "bytes"])
async def test_past_its_bounds_an_extension_is_refused_and_nothing_changes(
    owner_sessionmaker, worker_sessionmaker, monkeypatch, bound
) -> None:
    tenant, root = await a_tenant(owner_sessionmaker), uuid.uuid4()
    monkeypatch.setattr(
        secret_index, "MAX_STRINGS" if bound == "strings" else "MAX_BYTES", 2 if bound == "strings" else 20
    )
    before = await extend(worker_sessionmaker, tenant, root, ["aaaa-1111"])
    with pytest.raises(secret_index.SecretIndexLimitError):
        await extend(worker_sessionmaker, tenant, root, ["bbbb-2222", "cccc-3333"])
    assert await read(worker_sessionmaker, tenant, root) == before


def test_the_minimum_and_the_code_are_the_engines() -> None:
    from dewpoint.engine.sensitive import MIN_SECRET, SECRET_INDEX_LIMIT

    assert (secret_index.MIN_SECRET, secret_index.SECRET_INDEX_LIMIT) == (MIN_SECRET, SECRET_INDEX_LIMIT)
