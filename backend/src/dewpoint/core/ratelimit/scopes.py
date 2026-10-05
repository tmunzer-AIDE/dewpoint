# SPDX-License-Identifier: Apache-2.0
"""A credential's quota-scope key (plugins-3 D9): an HMAC under a key derived from the tenant's request-digest key,
so connections sharing a token share a budget without the token, or a plain hash of it, being stored. The worker and
the API derive the same key; a data-key rotation starts fresh buckets."""

import hashlib
import hmac
import uuid
from collections.abc import Callable

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


def credential_hasher(digest_key: bytes, tenant_id: uuid.UUID) -> Callable[[str], str]:
    info = f"dewpoint|{tenant_id}|rate-scope".encode()
    key = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=info).derive(digest_key)
    return lambda credential: hmac.new(key, credential.encode(), hashlib.sha256).hexdigest()[:32]
