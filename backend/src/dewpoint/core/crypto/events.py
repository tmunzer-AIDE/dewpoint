# SPDX-License-Identifier: Apache-2.0
"""Sealing an inbound event to its tenant (engine 2b spec §8.3): an ephemeral X25519 key agreed with the tenant's
public key, HKDF-SHA256 (salt: the ephemeral then the tenant's public key; info `dewpoint|inbound-event|v1`), and
AES-256-GCM. Ingress holds only the public key, so it seals and never opens; the dispatcher opens with the private
key. A sealed event names its keypair's version, and its tenant, endpoint, own id and that version are its associated
data, so one moved to another row doesn't open.

Layout: `0x01`, the version (4 bytes, big-endian), the ephemeral public key (32), the nonce (12), then the ciphertext
and its tag (16)."""

import os
import struct
import uuid

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat, PublicFormat

FORMAT_V1 = b"\x01"
INFO = b"dewpoint|inbound-event|v1"
OVERHEAD = 1 + 4 + 32 + 12 + 16  # what sealing adds to a payload


def _raw_public(key: X25519PrivateKey) -> bytes:
    return key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)


def _aad(tenant_id: uuid.UUID, endpoint_id: uuid.UUID, event_id: uuid.UUID, version: int) -> bytes:
    return f"dewpoint|event|{tenant_id}|{endpoint_id}|{event_id}|{version}".encode()


def _key(shared: bytes, ephemeral_public: bytes, recipient_public: bytes) -> AESGCM:
    return AESGCM(HKDF(hashes.SHA256(), 32, ephemeral_public + recipient_public, INFO).derive(shared))


def public_of(private_key: bytes) -> bytes:
    """The raw public key of a raw X25519 private key."""
    return _raw_public(X25519PrivateKey.from_private_bytes(private_key))


def generate_keypair() -> tuple[bytes, bytes]:
    """A new keypair: its raw private and public keys, 32 bytes each."""
    private = X25519PrivateKey.generate()
    return private.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption()), _raw_public(private)


def seal_with(
    ephemeral_private: bytes, nonce: bytes, public_key: bytes, version: int, *, tenant_id: uuid.UUID,
    endpoint_id: uuid.UUID, event_id: uuid.UUID, plaintext: bytes,
) -> bytes:  # fmt: skip
    """`seal`, with the ephemeral key and the nonce given: for a known answer only. Never reuse either."""
    ephemeral = X25519PrivateKey.from_private_bytes(ephemeral_private)
    ephemeral_public = _raw_public(ephemeral)
    shared = ephemeral.exchange(X25519PublicKey.from_public_bytes(public_key))
    sealed = _key(shared, ephemeral_public, public_key).encrypt(
        nonce, plaintext, _aad(tenant_id, endpoint_id, event_id, version)
    )
    return FORMAT_V1 + struct.pack(">I", version) + ephemeral_public + nonce + sealed


def seal(
    public_key: bytes, version: int, *, tenant_id: uuid.UUID, endpoint_id: uuid.UUID, event_id: uuid.UUID,
    plaintext: bytes,
) -> bytes:  # fmt: skip
    """`plaintext` sealed to the tenant's public key of `version`, bound to its tenant, endpoint and id."""
    ephemeral = X25519PrivateKey.generate().private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    return seal_with(ephemeral, os.urandom(12), public_key, version, tenant_id=tenant_id, endpoint_id=endpoint_id,
                     event_id=event_id, plaintext=plaintext)  # fmt: skip


def version_of(blob: bytes) -> int:
    """The version of the keypair a sealed event names. Raises ValueError for another format."""
    if blob[:1] != FORMAT_V1 or len(blob) < OVERHEAD:
        raise ValueError("a sealed event in an unknown format")
    return int(struct.unpack(">I", blob[1:5])[0])


def open_sealed(
    private_key: bytes, *, tenant_id: uuid.UUID, endpoint_id: uuid.UUID, event_id: uuid.UUID, blob: bytes
) -> bytes:
    """The plaintext of a sealed event of this tenant, endpoint and id. Raises `InvalidTag` when it doesn't open."""
    version = version_of(blob)
    ephemeral_public, nonce = blob[5:37], blob[37:49]
    private = X25519PrivateKey.from_private_bytes(private_key)
    shared = private.exchange(X25519PublicKey.from_public_bytes(ephemeral_public))
    return _key(shared, ephemeral_public, _raw_public(private)).decrypt(
        nonce, blob[49:], _aad(tenant_id, endpoint_id, event_id, version)
    )
