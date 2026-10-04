# SPDX-License-Identifier: Apache-2.0
"""An endpoint as ingress sees it: what `resolve_webhook_endpoint()` returns, ingress's only read of one."""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from dewpoint.apps.ingress.addresses import Network

RESOLVE = text("select * from resolve_webhook_endpoint(:e)")


@dataclass(frozen=True)
class Endpoint:
    id: uuid.UUID
    tenant_id: uuid.UUID
    enabled: bool
    tenant_active: bool
    auth_kind: str
    bearer_digest: bytes | None
    hmac_secret: bytes | None  # sealed under the ingress key
    signature_header: str | None
    timestamp_header: str | None
    tolerance_s: int
    allowlist: Sequence[Network]  # empty: any address
    body_limit: int
    id_source: str
    id_pointer: str | None
    id_header: str | None
    events_pointer: str | None
    dedupe_key: bytes  # sealed under the ingress key
    key_version: int | None  # the tenant's newest inbound key; none when it has none
    public_key: bytes | None


async def resolve(session: AsyncSession, endpoint_id: uuid.UUID) -> Endpoint | None:
    row = (await session.execute(RESOLVE, {"e": endpoint_id})).mappings().one_or_none()
    if row is None:
        return None
    return Endpoint(id=endpoint_id, **{k: v for k, v in row.items()} | {"allowlist": tuple(row["allowlist"] or ())})
