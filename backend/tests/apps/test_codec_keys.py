# SPDX-License-Identifier: Apache-2.0
"""The codec's keys from the keyring (engine 2b spec §6.3): read-only, as the worker's role, under the tenant's RLS
scope; cached in the process, bounded in size and time; a missing key is never cached."""

import os
import uuid
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dewpoint.apps.codec import KeyringKeys, TenantCodec
from dewpoint.core.crypto.kek import Kek, KekSet
from dewpoint.core.crypto.keyring import Keyring, NoKeyError
from dewpoint.core.db import tenant_scope
from tests.apps.test_codec import payload, workflow

KEYRING = Keyring(KekSet(Kek("k1", os.urandom(32))))


class Counted:
    """A sessionmaker that counts the sessions it opens: each is a read of the keyring."""

    def __init__(self, inner: async_sessionmaker[AsyncSession]) -> None:
        self.inner, self.opened = inner, 0

    def __call__(self) -> Any:
        self.opened += 1
        return self.inner()


class Down:
    """A sessionmaker whose database stops answering once `down` is set."""

    def __init__(self, inner: async_sessionmaker[AsyncSession]) -> None:
        self.inner, self.down = inner, False

    def __call__(self) -> Any:
        if self.down:
            raise ConnectionRefusedError("the database is down")
        return self.inner()


async def with_key(owner_sessionmaker: async_sessionmaker[AsyncSession], tenant: uuid.UUID) -> int:
    async with owner_sessionmaker() as s, s.begin():
        return await KEYRING.ensure_key(s, tenant)


async def test_the_worker_and_dispatch_read_a_tenants_key_for_the_codec(
    owner_sessionmaker, worker_sessionmaker, dispatch_sessionmaker
) -> None:
    """The worker, and the dev CLI's start through the dispatch role (engine 2b spec §6.3)."""
    tenant = uuid.uuid4()
    await with_key(owner_sessionmaker, tenant)
    for role in (worker_sessionmaker, dispatch_sessionmaker):
        c = TenantCodec(KeyringKeys(role, KEYRING)).with_context(workflow(str(tenant)))
        assert await c.decode(await c.encode([payload({"x": 1})])) == [payload({"x": 1})]


async def test_a_key_is_read_once_until_its_time_is_up(owner_sessionmaker, worker_sessionmaker) -> None:
    tenant, now = uuid.uuid4(), [0.0]
    await with_key(owner_sessionmaker, tenant)
    counted = Counted(worker_sessionmaker)
    keys = KeyringKeys(counted, KEYRING, ttl_s=60, clock=lambda: now[0])  # type: ignore[arg-type]
    first = await keys.active(str(tenant))
    assert (await keys.active(str(tenant)), await keys.get(str(tenant), 1)) == (first, first[1])
    assert counted.opened == 1
    async with owner_sessionmaker() as s, s.begin():
        assert await KEYRING.rotate(s, tenant) == 2
    assert (await keys.active(str(tenant)))[0] == 1  # still cached: a rotation takes effect within the ttl
    now[0] = 61
    assert (await keys.active(str(tenant)))[0] == 2
    assert counted.opened == 2


async def test_a_missing_key_is_not_cached(owner_sessionmaker, worker_sessionmaker) -> None:
    tenant = uuid.uuid4()
    keys = KeyringKeys(worker_sessionmaker, KEYRING)
    with pytest.raises(NoKeyError):
        await keys.active(str(tenant))
    await with_key(owner_sessionmaker, tenant)
    assert (await keys.active(str(tenant)))[0] == 1


async def test_the_cache_holds_at_most_its_size(owner_sessionmaker, worker_sessionmaker) -> None:
    tenants = [uuid.uuid4() for _ in range(3)]
    for t in tenants:
        await with_key(owner_sessionmaker, t)
    counted = Counted(worker_sessionmaker)
    keys = KeyringKeys(counted, KEYRING, size=4)  # type: ignore[arg-type]
    for t in tenants:  # each read caches the active key twice: as active, and by its version
        await keys.active(str(t))
    await keys.active(str(tenants[0]))  # evicted: read again
    assert counted.opened == 4


async def test_another_tenants_key_is_invisible_to_the_worker(owner_sessionmaker, worker_sessionmaker) -> None:
    """RLS: the read is scoped to the tenant it asks for, so a scope bug can't hand the codec another tenant's key."""
    a, b = uuid.uuid4(), uuid.uuid4()
    await with_key(owner_sessionmaker, a)
    async with worker_sessionmaker() as s, s.begin():
        await tenant_scope(s, b)
        with pytest.raises(NoKeyError):
            await KEYRING.read_dek(s, a)


async def test_an_expired_key_is_never_used_while_the_database_doesnt_answer(
    owner_sessionmaker, worker_sessionmaker
) -> None:
    """The owner's ruling (2b-1a review): a key is kept at most `ttl_s`, even when it can't be read again, so a rotation
    always reaches every process within it (spec §6.3) and §6.4's retirement floor holds. While the database doesn't
    answer, a payload whose key has expired fails: encoding and decoding alike."""
    tenant = uuid.uuid4()
    await with_key(owner_sessionmaker, tenant)
    now, database = [0.0], Down(worker_sessionmaker)
    keys = KeyringKeys(database, KEYRING, ttl_s=60, clock=lambda: now[0])  # type: ignore[arg-type]
    assert (await keys.active(str(tenant)))[0] == 1
    database.down = True
    assert (await keys.active(str(tenant)))[0] == 1  # still within its time
    now[0] = 61
    with pytest.raises(ConnectionRefusedError):
        await keys.active(str(tenant))
    with pytest.raises(ConnectionRefusedError):
        await keys.get(str(tenant), 1)
