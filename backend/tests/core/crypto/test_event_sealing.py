# SPDX-License-Identifier: Apache-2.0
"""Sealing an inbound event to its tenant (engine 2b spec §8.3; 2b-3b task 2): an ephemeral X25519 key agreed with the
tenant's public key, HKDF-SHA256 (salt: the ephemeral then the tenant's public key; info `dewpoint|inbound-event|v1`)
and AES-256-GCM. Ingress holds only the public key, so it seals and never opens. A sealed event names its keypair's
version, and its tenant, endpoint, own id and that version are its associated data: moved to another row, it doesn't
open."""

import struct
import uuid

import pytest
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from dewpoint.core.crypto import events

TENANT, ENDPOINT, EVENT = uuid.UUID(int=1), uuid.UUID(int=2), uuid.UUID(int=3)
IDS = {"tenant_id": TENANT, "endpoint_id": ENDPOINT, "event_id": EVENT}
PRIVATE, EPHEMERAL, NONCE = bytes(range(32)), bytes(range(32, 64)), bytes(range(12))
KNOWN = (  # the sealed bytes of `{"a":1}` under the inputs above
    "0100000007358072d6365880d1aeea329adf9121383851ed21a28e3b75e965d0d2cd166254000102030405060708090a0b"
    "a839c98cfc857c572099b9aa59ca2038554873e8602ac6"
)


def public_of(private: bytes) -> bytes:
    return X25519PrivateKey.from_private_bytes(private).public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)


def test_the_scheme_as_written_with_a_known_answer() -> None:
    public = public_of(PRIVATE)
    blob = events.seal_with(EPHEMERAL, NONCE, public, 7, plaintext=b'{"a":1}', **IDS)
    ephemeral_public = public_of(EPHEMERAL)
    assert blob[:1] == b"\x01" and struct.unpack(">I", blob[1:5]) == (7,)
    assert blob[5:37] == ephemeral_public and blob[37:49] == NONCE
    shared = X25519PrivateKey.from_private_bytes(EPHEMERAL).exchange(X25519PublicKey.from_public_bytes(public))
    key = HKDF(hashes.SHA256(), 32, ephemeral_public + public, b"dewpoint|inbound-event|v1").derive(shared)
    aad = f"dewpoint|event|{TENANT}|{ENDPOINT}|{EVENT}|7".encode()
    assert AESGCM(key).decrypt(NONCE, blob[49:], aad) == b'{"a":1}'  # derived here, independently
    assert blob.hex() == KNOWN  # and pinned: a change to the format is deliberate
    assert events.open_sealed(PRIVATE, blob=blob, **IDS) == b'{"a":1}'


def test_a_sealed_event_opens_with_its_tenants_private_key_only() -> None:
    private, public = events.generate_keypair()
    assert public_of(private) == public
    blob = events.seal(public, 3, plaintext=b"payload", **IDS)
    assert b"payload" not in blob and events.version_of(blob) == 3
    assert len(blob) == len(b"payload") + events.OVERHEAD
    assert events.open_sealed(private, blob=blob, **IDS) == b"payload"
    assert events.seal(public, 3, plaintext=b"payload", **IDS) != blob  # a fresh ephemeral key each time
    other, _ = events.generate_keypair()
    with pytest.raises(InvalidTag):
        events.open_sealed(other, blob=blob, **IDS)


@pytest.mark.parametrize("moved", ["tenant_id", "endpoint_id", "event_id"])
def test_a_sealed_event_moved_to_another_row_doesnt_open(moved: str) -> None:
    private, public = events.generate_keypair()
    blob = events.seal(public, 1, plaintext=b"payload", **IDS)
    with pytest.raises(InvalidTag):
        events.open_sealed(private, blob=blob, **(IDS | {moved: uuid.uuid4()}))


@pytest.mark.parametrize("at", [2, 10, 40, 60])  # its version, its ephemeral key, its nonce, its ciphertext
def test_a_tampered_sealed_event_doesnt_open(at: int) -> None:
    private, public = events.generate_keypair()
    blob = bytearray(events.seal(public, 1, plaintext=b"payload-long-enough", **IDS))
    blob[at] ^= 1
    with pytest.raises(InvalidTag):
        events.open_sealed(private, blob=bytes(blob), **IDS)


def test_an_unknown_format_is_refused() -> None:
    private, public = events.generate_keypair()
    blob = events.seal(public, 1, plaintext=b"x", **IDS)
    with pytest.raises(ValueError, match="format"):
        events.open_sealed(private, blob=b"\x02" + blob[1:], **IDS)
    with pytest.raises(ValueError, match="format"):
        events.open_sealed(private, blob=blob[:20], **IDS)
