# SPDX-License-Identifier: Apache-2.0
"""A credential's quota-scope key (plugins-3 D9): an HMAC under the tenant's scope key, so connections sharing a token
share a budget without the token, or a plain hash of it, being stored. The scope key is random, made once per tenant
and sealed under its data key: a data-key rotation, during which workers may hold either version for a while, never
splits a scope. The worker makes it; the API only reads it."""

import hashlib
import hmac
import os
import uuid
from collections.abc import Callable
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from dewpoint.core.models.egress import RateScopeKey

PURPOSE = "rate.scope"


class Sealer(Protocol):
    """The claim cipher's (worker) or the keyring's (API) seal and open for one purpose: the same layout."""

    async def seal(self, tenant_id: str, context: str, plaintext: bytes) -> bytes: ...

    async def open(self, tenant_id: str, context: str, blob: bytes) -> bytes: ...


async def scope_key(s: AsyncSession, sealer: Sealer, tenant_id: uuid.UUID, *, create: bool) -> bytes | None:
    """The tenant's scope key, made the first time when `create` (the caller has set the tenant's scope)."""
    found = (await s.execute(select(RateScopeKey.sealed).where(RateScopeKey.tenant_id == tenant_id))).scalar()
    if found is None:
        if not create:
            return None
        sealed = await sealer.seal(str(tenant_id), str(tenant_id), os.urandom(32))
        await s.execute(
            insert(RateScopeKey)
            .values(tenant_id=tenant_id, sealed=sealed)
            .on_conflict_do_nothing(index_elements=["tenant_id"])
        )
        found = (await s.execute(select(RateScopeKey.sealed).where(RateScopeKey.tenant_id == tenant_id))).scalar_one()
    return await sealer.open(str(tenant_id), str(tenant_id), found)


def credential_hasher(key: bytes) -> Callable[[str], str]:
    return lambda credential: hmac.new(key, credential.encode(), hashlib.sha256).hexdigest()[:32]
