# SPDX-License-Identifier: Apache-2.0
"""A run request's idempotency digest (engine 2b spec §7.2): an HMAC, with a key derived from the tenant's data key,
over the canonical JSON of the source, workflow, mode and input, stored with its key version. Never an unkeyed hash of
input that may hold low-entropy secrets: only a holder of the tenant's key can test a guess."""

import hashlib
import uuid

from dewpoint.core.requests import digest as d
from tests.support.keys import FixtureKeys

TENANT, OTHER = str(uuid.UUID(int=1)), str(uuid.UUID(int=2))
REQUEST = {"source": "manual", "workflow_id": uuid.UUID(int=3), "mode": "live", "input": {"pin": "1234", "site": "a"}}


async def test_the_same_request_digests_the_same_and_any_change_differently() -> None:
    keys = FixtureKeys()
    version, first = await d.digest(keys, TENANT, **REQUEST)
    assert version == 1 and len(first) == 32
    reordered = {**REQUEST, "input": {"site": "a", "pin": "1234"}}
    assert (await d.digest(keys, TENANT, **reordered))[1] == first  # canonical: key order doesn't count
    for change in ({"source": "dev"}, {"mode": "simulate"}, {"workflow_id": uuid.UUID(int=4)},
                   {"input": {"pin": "1235", "site": "a"}}):  # fmt: skip
        assert (await d.digest(keys, TENANT, **{**REQUEST, **change}))[1] != first


async def test_a_digest_is_keyed_by_the_tenant_never_an_unkeyed_hash() -> None:
    keys = FixtureKeys()
    _, mine = await d.digest(keys, TENANT, **REQUEST)
    assert mine != (await d.digest(keys, OTHER, **REQUEST))[1]
    assert mine != hashlib.sha256(d.canonical(**REQUEST)).digest()


async def test_a_stored_digest_is_compared_with_its_own_key_version_after_a_rotation() -> None:
    """An exact retry is found whatever has changed since, a key rotation included (§7.2, step 2)."""
    _, stored = await d.digest(FixtureKeys(version=1), TENANT, **REQUEST)
    rotated = FixtureKeys(version=2)
    version, fresh = await d.digest(rotated, TENANT, **REQUEST)
    assert version == 2 and fresh != stored
    assert await d.matches(rotated, TENANT, stored, 1, **REQUEST)
    assert not await d.matches(rotated, TENANT, stored, 1, **{**REQUEST, "mode": "simulate"})
