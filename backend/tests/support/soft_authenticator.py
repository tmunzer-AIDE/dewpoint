# SPDX-License-Identifier: Apache-2.0
"""A minimal software WebAuthn authenticator (ES256, "none" attestation) for real end-to-end verification."""

import hashlib
import json
import os
import struct
from base64 import urlsafe_b64decode, urlsafe_b64encode
from typing import Any

import cbor2
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec

FLAG_UP, FLAG_UV, FLAG_AT = 0x01, 0x04, 0x40


def b64u(data: bytes) -> str:
    return urlsafe_b64encode(data).rstrip(b"=").decode()


def unb64u(data: str) -> bytes:
    return urlsafe_b64decode(data + "=" * (-len(data) % 4))


class SoftAuthenticator:
    def __init__(self, rp_id: str, origin: str, *, user_verified: bool = True) -> None:
        self.rp_id, self.origin, self.user_verified = rp_id, origin, user_verified
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.credential_id = os.urandom(16)
        self.sign_count = 0

    def _flags(self, extra: int = 0) -> int:
        return FLAG_UP | (FLAG_UV if self.user_verified else 0) | extra

    def _client_data(self, kind: str, challenge_b64u: str, origin: str | None) -> bytes:
        return json.dumps(
            {"type": kind, "challenge": challenge_b64u, "origin": origin or self.origin, "crossOrigin": False}
        ).encode()

    def register(self, options: dict[str, Any], *, origin: str | None = None) -> dict[str, Any]:
        numbers = self.key.public_key().public_numbers()
        cose_key = {1: 2, 3: -7, -1: 1, -2: numbers.x.to_bytes(32, "big"), -3: numbers.y.to_bytes(32, "big")}
        attested = bytes(16) + struct.pack(">H", len(self.credential_id)) + self.credential_id + cbor2.dumps(cose_key)
        auth_data = (
            hashlib.sha256(self.rp_id.encode()).digest()
            + bytes([self._flags(FLAG_AT)])
            + struct.pack(">I", self.sign_count)
            + attested
        )
        client_data = self._client_data("webauthn.create", options["challenge"], origin)
        return {
            "id": b64u(self.credential_id),
            "rawId": b64u(self.credential_id),
            "type": "public-key",
            "response": {
                "clientDataJSON": b64u(client_data),
                "attestationObject": b64u(cbor2.dumps({"fmt": "none", "attStmt": {}, "authData": auth_data})),
                "transports": ["internal"],
            },
            "clientExtensionResults": {},
        }

    def authenticate(self, options: dict[str, Any], *, origin: str | None = None) -> dict[str, Any]:
        self.sign_count += 1
        auth_data = (
            hashlib.sha256(self.rp_id.encode()).digest() + bytes([self._flags()]) + struct.pack(">I", self.sign_count)
        )
        client_data = self._client_data("webauthn.get", options["challenge"], origin)
        signature = self.key.sign(auth_data + hashlib.sha256(client_data).digest(), ec.ECDSA(hashes.SHA256()))
        return {
            "id": b64u(self.credential_id),
            "rawId": b64u(self.credential_id),
            "type": "public-key",
            "response": {
                "clientDataJSON": b64u(client_data),
                "authenticatorData": b64u(auth_data),
                "signature": b64u(signature),
                "userHandle": None,
            },
            "clientExtensionResults": {},
        }
