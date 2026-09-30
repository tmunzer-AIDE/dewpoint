# SPDX-License-Identifier: Apache-2.0
"""Engine 2b spec §6.3: every tenant has a data key before anything encrypts for it. The payload codec only reads
keys, so a tenant gets one when it's created, and tenants created before 2b-1a get one from `ensure_tenant_keys`."""

import os
import uuid

from sqlalchemy import text

from dewpoint.core.auth.users import create_user
from dewpoint.core.crypto.kek import Kek, KekSet
from dewpoint.core.crypto.keyring import Keyring
from dewpoint.core.tenancy import service

KEYRING = Keyring(KekSet(Kek("k1", os.urandom(32))))


async def test_a_new_tenant_has_a_data_key(owner_sessionmaker, api_sessionmaker) -> None:
    async with owner_sessionmaker() as s, s.begin():
        owner = await create_user(s, email="owner@corp.test", password="violet-otter-canyon-42")
    async with api_sessionmaker() as s, s.begin():  # as the API creates it
        tenant = await service.create_tenant(s, KEYRING, name="Acme", slug="acme", owner_id=owner.id)
        assert (await KEYRING.read_dek(s, tenant.id))[0] == 1


async def test_tenants_without_a_key_get_one_once(owner_sessionmaker) -> None:
    older, keyed = uuid.uuid4(), uuid.uuid4()
    async with owner_sessionmaker() as s, s.begin():
        for tid, slug in ((older, "older"), (keyed, "keyed")):
            await s.execute(text("insert into tenants(id,name,slug) values (:t,'T',:s)"), {"t": tid, "s": slug})
        await KEYRING.ensure_key(s, keyed)
    async with owner_sessionmaker() as s, s.begin():  # the database owner, as the migrate step runs it
        assert await service.ensure_tenant_keys(s, KEYRING) == [older]
        assert await service.ensure_tenant_keys(s, KEYRING) == []
        assert [(await KEYRING.read_dek(s, t))[0] for t in (older, keyed)] == [1, 1]
