# SPDX-License-Identifier: Apache-2.0
"""Fixture data keys for tests and golden histories: derived from the tenant and version, so a history recorded
today decrypts on any later replay. Never a real key: only tests import this module."""

import hashlib
from dataclasses import dataclass, field

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


@dataclass
class FixtureKeys:
    """A `KeySource` (`dewpoint.apps.codec`). `version`: the active one; `missing`: tenants without a key."""

    version: int = 1
    missing: set[str] = field(default_factory=set)

    async def active(self, tenant_id: str) -> tuple[int, AESGCM]:
        return self.version, await self.get(tenant_id, self.version)

    async def get(self, tenant_id: str, version: int) -> AESGCM:
        if tenant_id in self.missing:
            raise LookupError(f"no key for tenant {tenant_id}")
        return AESGCM(hashlib.sha256(f"dewpoint-fixture-key|{tenant_id}|{version}".encode()).digest())
