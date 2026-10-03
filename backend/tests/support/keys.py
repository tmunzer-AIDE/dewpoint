# SPDX-License-Identifier: Apache-2.0
"""Fixture data keys for tests and golden histories: derived from the tenant and version, so a history recorded
today decrypts on any later replay. Never a real key: only tests import this module."""

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from temporalio.api.common.v1 import Payload
from temporalio.converter import WorkflowSerializationContext

from dewpoint.apps.codec import TENANT, TenantCodec, data_converter
from dewpoint.core.crypto.keys import digest_key_of
from dewpoint.engine.runtime.ids import run_workflow_id


@dataclass
class FixtureKeys:
    """A `KeySource` (`dewpoint.apps.codec`). `version`: the active one; `missing`: tenants without a key."""

    version: int = 1
    missing: set[str] = field(default_factory=set)

    async def active(self, tenant_id: str) -> tuple[int, AESGCM]:
        return self.version, await self.get(tenant_id, self.version)

    async def get(self, tenant_id: str, version: int) -> AESGCM:
        return AESGCM(self._raw(tenant_id, version))

    async def digest_key(self, tenant_id: str, version: int | None) -> tuple[int, bytes]:
        found = self.version if version is None else version
        return found, digest_key_of(self._raw(tenant_id, found), tenant_id)

    def _raw(self, tenant_id: str, version: int) -> bytes:
        if tenant_id in self.missing:
            raise LookupError(f"no key for tenant {tenant_id}")
        return hashlib.sha256(f"dewpoint-fixture-key|{tenant_id}|{version}".encode()).digest()


# Every test server, recorder and replayer of Dewpoint's workflows uses it, as every process uses the keyring's.
FIXTURE_CONVERTER = data_converter(FixtureKeys())


async def opened(payload: Payload) -> Any:
    """What a payload in a history carries, decrypted with the fixture keys and parsed: tests read what a workflow
    sent with it. It takes the tenant from the payload's metadata, which only a test may do (the codec never does)."""
    workflow_id = run_workflow_id(payload.metadata[TENANT].decode(), str(uuid.UUID(int=0)))
    codec = TenantCodec(FixtureKeys()).with_context(WorkflowSerializationContext("default", workflow_id))
    [plain] = await codec.decode([payload])
    return json.loads(plain.data)
