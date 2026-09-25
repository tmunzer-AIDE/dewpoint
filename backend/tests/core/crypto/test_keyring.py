# SPDX-License-Identifier: Apache-2.0
import os
import uuid

import pytest
from cryptography.exceptions import InvalidTag

from dewpoint.core.crypto.kek import Kek, KekSet, UnknownKekError
from dewpoint.core.crypto.keyring import Keyring


def _kek(kid: str = "k1") -> Kek:
    return Kek(kid, os.urandom(32))


async def test_roundtrip_and_aad_binding(owner_sessionmaker) -> None:
    kr, t = Keyring(KekSet(_kek())), uuid.uuid4()
    async with owner_sessionmaker() as s, s.begin():
        blob = await kr.encrypt(s, tenant_id=t, purpose="connection.secret", context="c1", plaintext=b"tok")
        assert b"tok" not in blob
        assert await kr.decrypt(s, tenant_id=t, purpose="connection.secret", context="c1", blob=blob) == b"tok"
        with pytest.raises(InvalidTag):
            await kr.decrypt(s, tenant_id=t, purpose="connection.secret", context="c2", blob=blob)
        with pytest.raises(InvalidTag):
            await kr.decrypt(s, tenant_id=uuid.uuid4(), purpose="connection.secret", context="c1", blob=blob)


async def test_rotation_keeps_old_ciphertext_readable(owner_sessionmaker) -> None:
    kr, t = Keyring(KekSet(_kek())), uuid.uuid4()
    async with owner_sessionmaker() as s, s.begin():
        old = await kr.encrypt(s, tenant_id=t, purpose="p", context="x", plaintext=b"a")
        assert await kr.rotate(s, t) == 2
        new = await kr.encrypt(s, tenant_id=t, purpose="p", context="x", plaintext=b"b")
        assert old[1:5] != new[1:5]  # different key version header
        assert await kr.decrypt(s, tenant_id=t, purpose="p", context="x", blob=old) == b"a"


async def test_kek_rollout_phases(owner_sessionmaker) -> None:
    """Phases from docs/operations/key-rotation.md. Old and new processes coexist in phases A and B."""
    old, new = _kek("old"), _kek("new")
    t1, t2 = uuid.uuid4(), uuid.uuid4()
    only_old = Keyring(KekSet(old))
    phase_a = Keyring(KekSet(old, previous=[new]))  # new key is read-only everywhere
    phase_b = Keyring(KekSet(new, previous=[old]))  # new key writes; old still readable
    only_new = Keyring(KekSet(new))  # phase D
    async with owner_sessionmaker() as s, s.begin():
        b1 = await only_old.encrypt(s, tenant_id=t1, purpose="p", context="x", plaintext=b"one")
        b2 = await phase_b.encrypt(s, tenant_id=t2, purpose="p", context="x", plaintext=b"two")  # new DEK, new KEK
        # a phase-A process (not yet switched) can read what a phase-B process wrote
        assert await phase_a.decrypt(s, tenant_id=t2, purpose="p", context="x", blob=b2) == b"two"
        # a process that never got the new key cannot, which is why phase A exists
        with pytest.raises(UnknownKekError):
            await only_old.decrypt(s, tenant_id=t2, purpose="p", context="x", blob=b2)
        assert await phase_b.kek_usage(s) == {"old": 1, "new": 1}
        with pytest.raises(UnknownKekError):
            await only_new.decrypt(s, tenant_id=t1, purpose="p", context="x", blob=b1)
        # phase C: rewrap in batches until nothing references the old KEK
        assert await phase_b.rewrap_batch(s, batch_size=1) == 1
        assert await phase_b.rewrap_batch(s, batch_size=1) == 0
        assert await phase_b.kek_usage(s) == {"new": 2}
        # phase D: the old KEK can be removed from configuration
        assert await only_new.decrypt(s, tenant_id=t1, purpose="p", context="x", blob=b1) == b"one"
        assert await only_new.decrypt(s, tenant_id=t2, purpose="p", context="x", blob=b2) == b"two"
