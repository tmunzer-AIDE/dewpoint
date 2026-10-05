# SPDX-License-Identifier: Apache-2.0
"""A tenant's inbound keypairs (engine 2b spec §8.3, §6.4): made with the tenant and, for tenants that predate them, by
the key admin; versioned from the start. The private key is sealed with the tenant's data key, so only a role that
reads data keys (the dispatcher) opens it, through its cached key source. A version that isn't there fails closed:
rotating keypairs and re-wrapping them before a data key retires are 2b-4's."""

import hmac
import uuid

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
