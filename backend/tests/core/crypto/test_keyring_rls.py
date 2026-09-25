# SPDX-License-Identifier: Apache-2.0
import asyncio
import os
import uuid

import pytest
from cryptography.exceptions import InvalidTag
from sqlalchemy import func, select
from sqlalchemy.exc import DBAPIError

from dewpoint.core.crypto.kek import Kek, KekSet
from dewpoint.core.crypto.keyring import Keyring
from dewpoint.core.db import tenant_scope
from dewpoint.core.models.keys import DataKey, PlatformKey

KR = Keyring(KekSet(Kek("k1", os.urandom(32))))


async def test_concurrent_first_use_creates_one_key(api_sessionmaker, owner_sessionmaker) -> None:
    t = uuid.uuid4()

    async def first_use(i: int) -> bytes:
        async with api_sessionmaker() as s, s.begin():
            await tenant_scope(s, t)
            blob = await KR.encrypt(s, tenant_id=t, purpose="p", context=str(i), plaintext=b"x")
            await asyncio.sleep(0.1)  # keep transactions overlapping
            return blob

    blobs = await asyncio.gather(*(first_use(i) for i in range(5)))
    async with owner_sessionmaker() as s:
        assert (
            await s.execute(select(func.count()).select_from(DataKey).where(DataKey.tenant_id == t))
        ).scalar_one() == 1
    async with api_sessionmaker() as s, s.begin():
        await tenant_scope(s, t)
        for i, b in enumerate(blobs):
            assert await KR.decrypt(s, tenant_id=t, purpose="p", context=str(i), blob=b) == b"x"


async def test_concurrent_rotations_serialize(api_sessionmaker) -> None:
    t = uuid.uuid4()

    async def rotate() -> int:
        async with api_sessionmaker() as s, s.begin():
            await tenant_scope(s, t)
            v = await KR.rotate(s, t)
            await asyncio.sleep(0.1)
            return v

    assert sorted(await asyncio.gather(rotate(), rotate(), rotate())) == [2, 3, 4]


async def test_tenant_keys_are_rls_scoped(api_sessionmaker) -> None:
    a, b = uuid.uuid4(), uuid.uuid4()
    async with api_sessionmaker() as s, s.begin():
        await tenant_scope(s, a)
        blob = await KR.encrypt(s, tenant_id=a, purpose="p", context="c", plaintext=b"secret")
    async with api_sessionmaker() as s, s.begin():  # no tenant context: nothing visible
        assert (await s.execute(select(DataKey))).scalars().all() == []
    async with api_sessionmaker() as s, s.begin():  # other tenant's context: key invisible, decrypt fails
        await tenant_scope(s, b)
        assert (await s.execute(select(DataKey))).scalars().all() == []
        with pytest.raises(InvalidTag):
            await KR.decrypt(s, tenant_id=a, purpose="p", context="c", blob=blob)
    with pytest.raises(DBAPIError, match="row-level security"):  # can't create a key for another tenant
        async with api_sessionmaker() as s, s.begin():
            await tenant_scope(s, b)
            await KR.encrypt(s, tenant_id=a, purpose="p", context="c", plaintext=b"x")


async def test_platform_key_path_is_narrow(api_sessionmaker, worker_sessionmaker) -> None:
    async with api_sessionmaker() as s, s.begin():
        blob = await KR.encrypt(s, tenant_id=None, purpose="user.totp", context="u1", plaintext=b"totp")
        assert await KR.decrypt(s, tenant_id=None, purpose="user.totp", context="u1", blob=blob) == b"totp"
        assert (await s.execute(select(func.count()).select_from(PlatformKey))).scalar_one() == 1
    with pytest.raises(DBAPIError, match="permission denied"):
        async with worker_sessionmaker() as s, s.begin():
            await s.execute(select(PlatformKey))


async def test_admin_role_sees_all_keys(api_sessionmaker, admin_sessionmaker) -> None:
    for t in (uuid.uuid4(), uuid.uuid4()):
        async with api_sessionmaker() as s, s.begin():
            await tenant_scope(s, t)
            await KR.encrypt(s, tenant_id=t, purpose="p", context="c", plaintext=b"x")
    async with api_sessionmaker() as s, s.begin():
        await KR.encrypt(s, tenant_id=None, purpose="p", context="c", plaintext=b"x")
    async with admin_sessionmaker() as s, s.begin():
        assert await KR.kek_usage(s) == {"k1": 3}
