# SPDX-License-Identifier: Apache-2.0
"""A tenant's inbound keypairs (engine 2b spec §8.3, §6.4): made with the tenant and, for tenants that predate them, by
the key admin; versioned from the start. The private key is sealed with the tenant's data key, so only a role that
reads data keys (the dispatcher) opens it, through its cached key source. A version that isn't there fails closed.
Rotating makes the next version, which ingress seals new events to; `dewpoint keys reencrypt` seals the private keys
again under the active data key, and an older keypair retires once no stored event names it (2b-4)."""

import hmac
import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from dewpoint.core.claims.cipher import ClaimCipher, ClaimUnreadableError
from dewpoint.core.crypto import events
from dewpoint.core.crypto.keyring import Keyring
from dewpoint.core.crypto.keys import KeySource
from dewpoint.core.models.ingress import TenantEventKey

PURPOSE = "event.private"


class NoEventKeyError(LookupError):
    """A tenant has no inbound keypair of that version, or none at all (or row-level security hides it)."""


class EventKeyMismatchError(NoEventKeyError):
    """A keypair whose private key opens but isn't its public key's pair (rewrapped with another key): the events
    sealed to that public key can't be opened with it, through no fault of theirs (the owner's M3 review)."""


async def ensure_event_key(s: AsyncSession, keyring: Keyring, tenant_id: uuid.UUID) -> int:
    """The tenant's current keypair version, made (version 1) if it has none, in the caller's tenant scope."""
    await s.execute(
        text("select pg_advisory_xact_lock(hashtextextended(:k, 0))"), {"k": f"dewpoint:event-key:{tenant_id}"}
    )
    current = (
        await s.execute(select(func.max(TenantEventKey.version)).where(TenantEventKey.tenant_id == tenant_id))
    ).scalar_one()
    if current is not None:
        return int(current)
    private, public = events.generate_keypair()
    sealed = await keyring.encrypt(s, tenant_id=tenant_id, purpose=PURPOSE, context="1", plaintext=private)
    s.add(TenantEventKey(tenant_id=tenant_id, version=1, public_key=public, private_sealed=sealed))
    await s.flush()
    return 1


SETTLE = timedelta(minutes=10)  # a settling period: ingress reads the newest public key for each delivery


async def _lock(s: AsyncSession, tenant_id: uuid.UUID) -> None:
    await s.execute(
        text("select pg_advisory_xact_lock(hashtextextended(:k, 0))"), {"k": f"dewpoint:event-key:{tenant_id}"}
    )


async def rotate_event_key(s: AsyncSession, keyring: Keyring, tenant_id: uuid.UUID) -> int:
    """The tenant's next keypair version, its private key sealed under the active data key, in the caller's tenant
    scope (engine 2b spec §8.3): ingress seals new events to its public key. Older versions stay, for the events
    sealed to them."""
    await _lock(s, tenant_id)
    current = (
        await s.execute(select(func.max(TenantEventKey.version)).where(TenantEventKey.tenant_id == tenant_id))
    ).scalar_one()
    version = 1 if current is None else int(current) + 1
    private, public = events.generate_keypair()
    sealed = await keyring.encrypt(s, tenant_id=tenant_id, purpose=PURPOSE, context=str(version), plaintext=private)
    s.add(TenantEventKey(tenant_id=tenant_id, version=version, public_key=public, private_sealed=sealed))
    await s.flush()
    return version


async def retire_event_keys(s: AsyncSession, tenant_id: uuid.UUID, *, settle: timedelta = SETTLE) -> list[int]:
    """The tenant's older keypairs that no stored event names deleted, once a newer one has existed `settle` (by the
    database's clock): which versions. The newest is never retired (spec §8.3: every version a retained event still
    needs is kept). Under the tenant's keypair lock, which `record_inbound_events()` holds shared until it commits
    (migration 0039): an event being recorded is found once it commits, and keeps its keypair; one recorded after
    is refused (`key_retired`, a retryable 503 from ingress) for naming a keypair that's gone. `settle` only spares
    most deliveries sealed just before a rotation that refusal."""
    await _lock(s, tenant_id)
    retired = await s.execute(text(
        "DELETE FROM tenant_event_keys k WHERE k.tenant_id = :t "
        "AND EXISTS (SELECT 1 FROM tenant_event_keys n WHERE n.tenant_id = k.tenant_id AND n.version > k.version "
        "AND n.created_at <= statement_timestamp() - cast(:settle as interval)) "
        "AND NOT EXISTS (SELECT 1 FROM inbound_events e WHERE e.tenant_id = k.tenant_id AND e.key_version = k.version) "
        "RETURNING k.version"), {"t": tenant_id, "settle": settle})  # fmt: skip
    found: list[Any] = list(retired.scalars().all())
    return sorted(int(version) for version in found)


async def public_key(s: AsyncSession, tenant_id: uuid.UUID) -> tuple[int, bytes]:
    """The tenant's current version and its public key."""
    row = (
        await s.execute(
            select(TenantEventKey).where(TenantEventKey.tenant_id == tenant_id)
            .order_by(TenantEventKey.version.desc()).limit(1)
        )
    ).scalar_one_or_none()  # fmt: skip
    if row is None:
        raise NoEventKeyError(f"tenant {tenant_id} has no inbound keypair")
    return row.version, row.public_key


async def private_key(s: AsyncSession, keys: KeySource, tenant_id: uuid.UUID, version: int) -> bytes:
    """The private key of the tenant's keypair `version`, opened with its data key, and checked against the version's
    public key. Raises NoEventKeyError, EventKeyMismatchError among them."""
    row = await s.get(TenantEventKey, (tenant_id, version))
    if row is None:
        raise NoEventKeyError(f"tenant {tenant_id} has no inbound keypair {version}")
    try:
        private = await ClaimCipher(keys, purpose=PURPOSE).open(str(tenant_id), str(version), row.private_sealed)
    except ClaimUnreadableError:
        raise NoEventKeyError(f"tenant {tenant_id}'s inbound keypair {version} doesn't open") from None
    try:
        paired = hmac.compare_digest(events.public_of(private), row.public_key)  # checked at every load
    except ValueError:  # not even a key's length
        paired = False
    if not paired:
        raise EventKeyMismatchError(f"tenant {tenant_id}'s inbound keypair {version} isn't a pair")
    return private
