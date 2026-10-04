# SPDX-License-Identifier: Apache-2.0
"""A tenant's inbound keypair (engine 2b spec §8.3, §6.4; 2b-3b task 2): made with the tenant, and by
`ensure_tenant_event_keys` for tenants that predate it, versioned from the start; its private key sealed with the
tenant's data key (purpose `event.private`, its version the context), which the dispatcher opens through its cached
key source. A version that isn't there fails closed. Ingress never reads the table: its resolver returns the public
key."""

import os
import uuid

import pytest
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from dewpoint.core.auth.users import create_user
from dewpoint.core.crypto.kek import Kek, KekSet
from dewpoint.core.crypto.keyring import Keyring
from dewpoint.core.crypto.keys import KeyringKeys
from dewpoint.core.db import tenant_scope
from dewpoint.core.ingress import keys as event_keys
from dewpoint.core.tenancy import service

KEYRING = Keyring(KekSet(Kek("k1", os.urandom(32))))


async def new_tenant(owner, api, slug: str = "acme") -> uuid.UUID:
    async with owner() as s, s.begin():
        user = await create_user(s, email=f"{slug}@corp.test", password="violet-otter-canyon-42")
    async with api() as s, s.begin():  # as the API creates it
        return (await service.create_tenant(s, KEYRING, name=slug, slug=slug, owner_id=user.id)).id


async def test_a_new_tenant_has_an_inbound_keypair_its_dispatcher_opens(
    owner_sessionmaker, api_sessionmaker, dispatch_sessionmaker
) -> None:
    tenant = await new_tenant(owner_sessionmaker, api_sessionmaker)
    async with dispatch_sessionmaker() as s, s.begin():
        await tenant_scope(s, tenant)
        version, public = await event_keys.public_key(s, tenant)
        private = await event_keys.private_key(s, KeyringKeys(dispatch_sessionmaker, KEYRING), tenant, version)
    assert version == 1
    derived = X25519PrivateKey.from_private_bytes(private).public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    assert derived == public


async def test_tenants_without_a_keypair_get_one_once_from_the_key_admin(
    owner_sessionmaker, admin_sessionmaker, api_sessionmaker
) -> None:
    older, keyed = uuid.uuid4(), await new_tenant(owner_sessionmaker, api_sessionmaker, "keyed")
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(text("insert into tenants(id,name,slug) values (:t,'T','older')"), {"t": older})
        await KEYRING.ensure_key(s, older)
    async with admin_sessionmaker() as s, s.begin():
        assert await service.ensure_tenant_event_keys(s, KEYRING) == [older]
        assert await service.ensure_tenant_event_keys(s, KEYRING) == []
    async with api_sessionmaker() as s, s.begin():
        with pytest.raises(service.NotKeyAdminError):
            await service.ensure_tenant_event_keys(s, KEYRING)
    async with owner_sessionmaker() as s:
        rows = (await s.execute(text("select tenant_id, version from tenant_event_keys order by tenant_id"))).all()
    assert sorted(rows) == sorted([(older, 1), (keyed, 1)])


async def test_a_missing_keypair_or_version_fails_closed(
    owner_sessionmaker, api_sessionmaker, dispatch_sessionmaker
) -> None:
    tenant = await new_tenant(owner_sessionmaker, api_sessionmaker)
    async with dispatch_sessionmaker() as s, s.begin():
        await tenant_scope(s, tenant)
        with pytest.raises(event_keys.NoEventKeyError):
            await event_keys.private_key(s, KeyringKeys(dispatch_sessionmaker, KEYRING), tenant, 2)
        await tenant_scope(s, uuid.uuid4())  # another tenant's scope: row-level security hides the keypair
        with pytest.raises(event_keys.NoEventKeyError):
            await event_keys.public_key(s, tenant)


async def test_the_keypairs_table_is_tenant_scoped_and_closed_to_ingress(
    owner_sessionmaker, api_sessionmaker, ingress_sessionmaker
) -> None:
    await new_tenant(owner_sessionmaker, api_sessionmaker)
    async with owner_sessionmaker() as s:
        query = text("select relrowsecurity, relforcerowsecurity from pg_class where relname = 'tenant_event_keys'")
        assert tuple((await s.execute(query)).one()) == (True, True)
    async with api_sessionmaker() as s, s.begin():
        await tenant_scope(s, uuid.uuid4())
        assert (await s.execute(text("select count(*) from tenant_event_keys"))).scalar_one() == 0
    with pytest.raises(DBAPIError, match="permission denied"):
        async with ingress_sessionmaker() as s:
            await s.execute(text("select count(*) from tenant_event_keys"))


@pytest.mark.parametrize("other", ["another valid key", "not a key's length"])
async def test_a_private_key_that_isnt_its_public_keys_pair_fails_closed(
    owner_sessionmaker, api_sessionmaker, dispatch_sessionmaker, other
) -> None:
    """The owner's M3 review: a version rewrapped with another valid private key opens, but isn't the key ingress
    seals to. Each load checks the pair, and a mismatch is the keypair's failure, never an event's."""
    from dewpoint.core.crypto import events

    tenant = await new_tenant(owner_sessionmaker, api_sessionmaker)
    other = events.generate_keypair()[0] if other == "another valid key" else b"sixteen bytes!!!"
    async with api_sessionmaker() as s, s.begin():
        await tenant_scope(s, tenant)
        rewrapped = await KEYRING.encrypt(s, tenant_id=tenant, purpose=event_keys.PURPOSE, context="1", plaintext=other)
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(text("update tenant_event_keys set private_sealed = :p where tenant_id = :t"),
                        {"p": rewrapped, "t": tenant})  # fmt: skip
    async with dispatch_sessionmaker() as s, s.begin():
        await tenant_scope(s, tenant)
        with pytest.raises(event_keys.EventKeyMismatchError) as refused:
            await event_keys.private_key(s, KeyringKeys(dispatch_sessionmaker, KEYRING), tenant, 1)
    assert isinstance(refused.value, event_keys.NoEventKeyError)
