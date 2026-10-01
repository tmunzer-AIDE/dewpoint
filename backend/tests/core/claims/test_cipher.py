# SPDX-License-Identifier: Apache-2.0
"""A claim is encrypted with its tenant's data key, bound to the tenant, the purpose `claim` and the claim's id (engine
2b spec §3.1). It goes through the codec's cached, read-only keys (§6.3), so admission (the dispatch role) and the
worker encrypt without the keyring's per-tenant lock, and in the keyring's own layout."""

import os
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dewpoint.core.claims.cipher import ClaimCipher, ClaimUnreadableError
from dewpoint.core.crypto.kek import Kek, KekSet
from dewpoint.core.crypto.keyring import Keyring
from dewpoint.core.crypto.keys import KeyringKeys
from dewpoint.core.db import tenant_scope
from tests.support.keys import FixtureKeys

KEYRING = Keyring(KekSet(Kek("k1", os.urandom(32))))
TENANT, OTHER = str(uuid.UUID(int=1)), str(uuid.UUID(int=2))
VALUE = b'{"token":"s3cret"}'


async def test_a_claim_opens_under_its_own_tenant_and_id() -> None:
    cipher, claim = ClaimCipher(FixtureKeys()), str(uuid.uuid4())
    blob = await cipher.seal(TENANT, claim, VALUE)
    assert VALUE not in blob
    assert await cipher.open(TENANT, claim, blob) == VALUE


@pytest.mark.parametrize("moved", ["another claim", "another tenant", "another format"])
async def test_a_claim_moved_anywhere_else_doesnt_open(moved: str) -> None:
    cipher, claim = ClaimCipher(FixtureKeys()), str(uuid.uuid4())
    blob = await cipher.seal(TENANT, claim, VALUE)
    tenant, where = TENANT, claim
    if moved == "another claim":
        where = str(uuid.uuid4())
    elif moved == "another tenant":
        tenant = OTHER
    else:
        blob = b"\x02" + blob[1:]
    with pytest.raises(ClaimUnreadableError) as raised:
        await cipher.open(tenant, where, blob)
    assert "s3cret" not in str(raised.value)


async def test_after_a_rotation_older_claims_still_open() -> None:
    keys = FixtureKeys(version=1)
    cipher, claim = ClaimCipher(keys), str(uuid.uuid4())
    old = await cipher.seal(TENANT, claim, VALUE)
    keys.version = 2
    new = await cipher.seal(TENANT, claim, VALUE)
    assert (old[1:5], new[1:5]) == ((1).to_bytes(4, "big"), (2).to_bytes(4, "big"))
    assert await cipher.open(TENANT, claim, old) == await cipher.open(TENANT, claim, new) == VALUE


async def test_the_dispatch_and_worker_roles_seal_what_the_keyring_opens(
    owner_sessionmaker: async_sessionmaker[AsyncSession], dispatch_sessionmaker, worker_sessionmaker
) -> None:
    """Admission claims a trigger as the dispatch role, which may only read data keys; the worker claims during a run.
    What either seals is the keyring's own layout: `Keyring.decrypt` opens it with the purpose `claim`."""
    tenant, claim = uuid.uuid4(), str(uuid.uuid4())
    async with owner_sessionmaker() as s, s.begin():
        await KEYRING.ensure_key(s, tenant)
    for role in (dispatch_sessionmaker, worker_sessionmaker):
        blob = await ClaimCipher(KeyringKeys(role, KEYRING)).seal(str(tenant), claim, VALUE)
        async with owner_sessionmaker() as s, s.begin():
            await tenant_scope(s, tenant)
            assert await KEYRING.decrypt(s, tenant_id=tenant, purpose="claim", context=claim, blob=blob) == VALUE
