# SPDX-License-Identifier: Apache-2.0
"""A tenant's inbound keypairs (engine 2b spec §8.3, §6.4): rotating makes the next version, whose public key ingress
seals new events to; an older version is retired only when no stored event names it, and only once a newer one has
existed for a settling period, past which ingress no longer seals to the older public key. Recording and retiring are
coordinated in the database (the owner's M3 review): an event being recorded keeps its keypair, and a keypair being
retired refuses the events sealed to it, so no stored event ever names a keypair that's gone."""

import asyncio
import uuid
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import text

from dewpoint.core.crypto.keyring import Keyring
from dewpoint.core.crypto.keys import KeyringKeys
from dewpoint.core.db import tenant_scope
from dewpoint.core.ingress import keys as event_keys
from tests.core.ingress.support import KEYRING, RECORD, endpoint, record, record_params


@pytest.fixture
def keyring() -> Keyring:
    return KEYRING  # the one the endpoint helper made the tenant's data key and keypair 1 with


async def _keyed(owner: Any, admin: Any, keyring: Keyring) -> tuple[uuid.UUID, uuid.UUID]:
    """A tenant with its data key and inbound keypair 1, and an endpoint."""
    return await endpoint(owner)


async def _sql(owner: Any, sql: str, **params: Any) -> None:
    async with owner() as s, s.begin():
        await s.execute(text(sql), params)


async def _versions(owner: Any, t: uuid.UUID) -> list[int]:
    async with owner() as s:
        return list((await s.execute(text("select version from tenant_event_keys where tenant_id = :t order by 1"),
                                     {"t": t})).scalars())  # fmt: skip


async def test_rotating_makes_the_next_keypair_which_new_events_are_sealed_to(
    owner_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, keyring
) -> None:
    t, _ = await _keyed(owner_sessionmaker, admin_sessionmaker, keyring)
    async with admin_sessionmaker() as s, s.begin():
        await tenant_scope(s, t)
        assert await event_keys.rotate_event_key(s, keyring, t) == 2
    async with dispatch_sessionmaker() as s, s.begin():
        await tenant_scope(s, t)
        version, public = await event_keys.public_key(s, t)
        keys = KeyringKeys(dispatch_sessionmaker, keyring)
        assert version == 2 and event_keys.events.public_of(await event_keys.private_key(s, keys, t, 2)) == public
        assert await event_keys.private_key(s, keys, t, 1) != await event_keys.private_key(s, keys, t, 2)


@pytest.mark.usefixtures("development_deployment")
async def test_an_older_keypair_retires_only_once_no_event_names_it_and_its_successor_has_settled(
    owner_sessionmaker, admin_sessionmaker, ingress_sessionmaker, keyring
) -> None:
    t, endpoint_id = await _keyed(owner_sessionmaker, admin_sessionmaker, keyring)
    event = uuid.uuid4()
    assert (await record(ingress_sessionmaker, endpoint_id, [(None, None, b"x" * 70)], ids=[event]))["outcome"] == (
        "recorded"
    )  # sealed under keypair 1  # fmt: skip
    async with admin_sessionmaker() as s, s.begin():
        await tenant_scope(s, t)
        await event_keys.rotate_event_key(s, keyring, t)

    async def retire() -> list[int]:
        async with admin_sessionmaker() as s, s.begin():
            await tenant_scope(s, t)
            return await event_keys.retire_event_keys(s, t, settle=timedelta(minutes=10))

    assert await retire() == []  # keypair 2 is new: a delivery may still be sealing to 1
    await _sql(owner_sessionmaker, "update tenant_event_keys set created_at = now() - interval '11 minutes' "
               "where tenant_id = :t and version = 2", t=t)  # fmt: skip
    assert await retire() == []  # an event still names keypair 1
    await _sql(owner_sessionmaker, "delete from inbound_events where id = :e", e=event)
    assert await retire() == [1]
    assert await _versions(owner_sessionmaker, t) == [2]
    assert await retire() == []  # the newest is never retired


async def _settled(owner: Any, admin: Any, keyring: Keyring) -> tuple[uuid.UUID, uuid.UUID]:
    """A tenant whose keypair 2 has existed past the settling period, no event naming its keypair 1: 1 may retire."""
    t, endpoint_id = await _keyed(owner, admin, keyring)
    async with admin() as s, s.begin():
        await tenant_scope(s, t)
        await event_keys.rotate_event_key(s, keyring, t)
    await _sql(owner, "update tenant_event_keys set created_at = now() - interval '11 minutes' where tenant_id = :t "
               "and version = 2", t=t)  # fmt: skip
    return t, endpoint_id


WAITING = text(
    "select count(*) from pg_locks where not granted and locktype = 'advisory' "
    "and database = (select oid from pg_database where datname = current_database())"
)


async def _waits(owner: Any, task: asyncio.Task[Any]) -> bool:
    """Whether `task` is seen waiting for an advisory lock (within 5 s) before it finishes."""
    for _ in range(500):
        if task.done():
            return False
        async with owner() as s:
            if (await s.execute(WAITING)).scalar_one():
                return True
        await asyncio.sleep(0.01)
    return False


async def _events(owner: Any, t: uuid.UUID) -> list[int]:
    async with owner() as s:
        return list((await s.execute(text("select key_version from inbound_events where tenant_id = :t"),
                                     {"t": t})).scalars())  # fmt: skip


@pytest.mark.usefixtures("development_deployment")
async def test_an_event_being_recorded_keeps_its_keypair_from_a_retirement_that_waits_for_it(
    owner_sessionmaker, admin_sessionmaker, ingress_sessionmaker, keyring
) -> None:
    """The owner's M3 review: a delivery sealed to keypair 1 before the rotation, recorded as 1 is being retired: the
    retirement waits for the recording to commit, then finds the event, and keeps 1."""
    t, endpoint_id = await _settled(owner_sessionmaker, admin_sessionmaker, keyring)

    async def retire() -> list[int]:
        async with admin_sessionmaker() as s, s.begin():
            await tenant_scope(s, t)
            return await event_keys.retire_event_keys(s, t)

    retiring: asyncio.Task[list[int]] | None = None
    try:
        async with ingress_sessionmaker() as s, s.begin():
            outcome = await s.execute(RECORD, record_params(endpoint_id, [(None, None, b"x" * 70)], versions=[1]))
            assert dict(outcome.scalar_one())["outcome"] == "recorded"
            retiring = asyncio.create_task(retire())
            waited = await _waits(owner_sessionmaker, retiring)
        retired = await asyncio.wait_for(retiring, 10)
    finally:
        if retiring is not None and not retiring.done():
            retiring.cancel()
    assert (waited, retired) == (True, [])
    assert await _versions(owner_sessionmaker, t) == [1, 2]
    assert await _events(owner_sessionmaker, t) == [1]


@pytest.mark.usefixtures("development_deployment")
async def test_a_keypair_being_retired_refuses_an_event_sealed_to_it_once_retired(
    owner_sessionmaker, admin_sessionmaker, ingress_sessionmaker, keyring
) -> None:
    """The owner's M3 review: a delivery sealed to keypair 1, recorded while 1 is being retired, waits for the
    retirement and is refused (`key_retired`, which ingress answers with a retryable 503): nothing names a keypair
    that's gone."""
    t, endpoint_id = await _settled(owner_sessionmaker, admin_sessionmaker, keyring)
    recording: asyncio.Task[dict[str, Any]] | None = None
    try:
        async with admin_sessionmaker() as s, s.begin():
            await tenant_scope(s, t)
            assert await event_keys.retire_event_keys(s, t) == [1]
            recording = asyncio.create_task(record(ingress_sessionmaker, endpoint_id, [(None, None, b"x" * 70)],
                                                   versions=[1]))  # fmt: skip
            waited = await _waits(owner_sessionmaker, recording)
        recorded = await asyncio.wait_for(recording, 10)
    finally:
        if recording is not None and not recording.done():
            recording.cancel()
    assert (waited, recorded) == (True, {"outcome": "key_retired"})
    assert await _versions(owner_sessionmaker, t) == [2]
    assert await _events(owner_sessionmaker, t) == []
