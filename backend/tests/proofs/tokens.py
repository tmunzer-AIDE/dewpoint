# SPDX-License-Identifier: Apache-2.0
"""JWT bearer tokens for configuration B's proof (2b-4b M4): an RSA key set, published as a JWKS for Temporal's JWT
claim mapper, and RS256 tokens signed with `cryptography` (no JWT library needed for this much)."""

import base64
import json
import time
from dataclasses import dataclass
from typing import Any

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _int(value: int) -> str:
    return _b64(value.to_bytes((value.bit_length() + 7) // 8, "big"))


@dataclass(frozen=True)
class KeySet:
    kid: str
    private: rsa.RSAPrivateKey

    @classmethod
    def create(cls, kid: str) -> "KeySet":
        return cls(kid, rsa.generate_private_key(public_exponent=65537, key_size=2048))

    def jwks(self) -> dict[str, Any]:
        numbers = self.private.public_key().public_numbers()
        return {"keys": [{"kty": "RSA", "kid": self.kid, "use": "sig", "alg": "RS256",
                          "n": _int(numbers.n), "e": _int(numbers.e)}]}  # fmt: skip

    def sign(self, claims: dict[str, Any], *, lifetime: int, now: int | None = None) -> str:
        """`claims` with `iat` and `exp` (`lifetime` seconds on; negative: already expired)."""
        now = int(time.time()) if now is None else now
        header = {"alg": "RS256", "typ": "JWT", "kid": self.kid}
        body = {**claims, "iat": now, "exp": now + lifetime}
        signing = f"{_b64(json.dumps(header).encode())}.{_b64(json.dumps(body).encode())}"
        signature = self.private.sign(signing.encode(), padding.PKCS1v15(), hashes.SHA256())
        return f"{signing}.{_b64(signature)}"
