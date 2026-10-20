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


async def test_a_draft_simulation_digests_its_draft_and_any_other_request_keeps_its_bytes() -> None:
    """B8 (the simulation design §6.3, step 1): a draft simulation's digest covers its revision, target and seeds; a
    request that isn't one is digested as before, byte for byte."""
    keys = FixtureKeys()
    assert d.canonical(**REQUEST) == (
        b'{"input":{"pin":"1234","site":"a"},"mode":"live","source":"manual",'
        b'"workflow_id":"00000000-0000-0000-0000-000000000003"}'
    )
    _, plain = await d.digest(keys, TENANT, **REQUEST)
    _, drafted = await d.digest(keys, TENANT, **REQUEST, draft={"draft_revision": 2})
    _, later = await d.digest(keys, TENANT, **REQUEST, draft={"draft_revision": 3})
    assert len({plain, drafted, later}) == 3
    assert await d.matches(keys, TENANT, drafted, 1, **REQUEST, draft={"draft_revision": 2})
    assert not await d.matches(keys, TENANT, drafted, 1, **REQUEST)


async def test_a_start_on_a_confirmed_version_digests_it_and_any_other_request_keeps_its_bytes() -> None:
    """B14 (the run form design §4.1): a start that names the version it confirmed digests it as a fifth key; one that
    names none is digested as before, byte for byte."""
    keys = FixtureKeys()
    seven, eight = str(uuid.UUID(int=7)), str(uuid.UUID(int=8))
    assert d.canonical(**REQUEST, expected_version_id=None) == d.canonical(**REQUEST)
    _, plain = await d.digest(keys, TENANT, **REQUEST)
    _, on_seven = await d.digest(keys, TENANT, **REQUEST, expected_version_id=seven)
    _, on_eight = await d.digest(keys, TENANT, **REQUEST, expected_version_id=eight)
    assert len({plain, on_seven, on_eight}) == 3
    assert await d.matches(keys, TENANT, on_seven, 1, **REQUEST, expected_version_id=seven)
    assert not await d.matches(keys, TENANT, on_seven, 1, **REQUEST)
    assert not await d.matches(keys, TENANT, plain, 1, **REQUEST, expected_version_id=seven)
