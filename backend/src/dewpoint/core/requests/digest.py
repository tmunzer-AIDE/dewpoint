# SPDX-License-Identifier: Apache-2.0
"""A run request's idempotency digest (engine 2b spec §7.2): an HMAC with the tenant's request-digest key, derived from
its data key, over the canonical JSON of the source, the workflow, the mode and the input. Never an unkeyed hash of
input that may hold low-entropy secrets. A request stores the key version it was digested with, so an exact retry is
recognized whatever has changed since, a key rotation included."""

import hashlib
import hmac
import json
import uuid
from typing import Any

from dewpoint.core.crypto.keys import KeySource


def canonical(*, source: str, workflow_id: uuid.UUID, mode: str, input: Any) -> bytes:
    """Sorted keys, no whitespace, UTF-8, no NaN: equal requests always give equal bytes."""
    value = {"source": source, "workflow_id": str(workflow_id), "mode": mode, "input": input}
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


async def digest(
    keys: KeySource,
    tenant_id: str,
    *,
    source: str,
    workflow_id: uuid.UUID,
    mode: str,
    input: Any,
    version: int | None = None,
) -> tuple[int, bytes]:
    """The request's digest with the tenant's key of `version` (its active one when None), and that version."""
    found, key = await keys.digest_key(tenant_id, version)
    message = canonical(source=source, workflow_id=workflow_id, mode=mode, input=input)
    return found, hmac.new(key, message, hashlib.sha256).digest()


async def matches(
    keys: KeySource, tenant_id: str, stored: bytes, version: int, *, source: str, workflow_id: uuid.UUID, mode: str,
    input: Any,
) -> bool:  # fmt: skip
    """Whether a request is the one `stored` was computed for, with the key version it was computed with."""
    _, fresh = await digest(keys, tenant_id, source=source, workflow_id=workflow_id, mode=mode, input=input,
                            version=version)  # fmt: skip
    return hmac.compare_digest(fresh, stored)
