# SPDX-License-Identifier: Apache-2.0
"""A test PKI for the proof environments (2b-4b M4): certificate authorities and the certificates they issue, made
with `cryptography`, already a dependency, rather than the host's `openssl` (LibreSSL on macOS takes other options).
ECDSA P-256 throughout; short-lived, for one disposable run."""

import ipaddress
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

LIFETIME = timedelta(days=2)


def _name(common_name: str) -> x509.Name:
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])


@dataclass(frozen=True)
class Issued:
    cert: x509.Certificate
    key: ec.EllipticCurvePrivateKey

    def cert_pem(self) -> bytes:
        return self.cert.public_bytes(serialization.Encoding.PEM)

    def key_pem(self) -> bytes:
        return self.key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
        )


@dataclass(frozen=True)
class Authority(Issued):
    @classmethod
    def create(cls, common_name: str) -> "Authority":
        key = ec.generate_private_key(ec.SECP256R1())
        now = datetime.now(UTC)
        cert = (
            x509.CertificateBuilder()
            .subject_name(_name(common_name))
            .issuer_name(_name(common_name))
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=5))
            .not_valid_after(now + LIFETIME)
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .add_extension(
                x509.KeyUsage(
                    digital_signature=False,
                    content_commitment=False,
                    key_encipherment=False,
                    data_encipherment=False,
                    key_agreement=False,
                    key_cert_sign=True,
                    crl_sign=True,
                    encipher_only=False,
                    decipher_only=False,
                ),
                critical=True,
            )
            .sign(key, hashes.SHA256())
        )
        return cls(cert, key)

    def issue(
        self,
        common_name: str,
        *,
        server: bool,
        names: Sequence[str] = (),
        ips: Sequence[str] = (),
        not_after: datetime | None = None,
    ) -> Issued:
        """A server certificate (its names and addresses as alternative names) or a client one (its common name the
        subject Temporal's interceptor maps); `not_after` in the past makes an expired one."""
        key = ec.generate_private_key(ec.SECP256R1())
        now = datetime.now(UTC)
        until = not_after or now + LIFETIME
        builder = (
            x509.CertificateBuilder()
            .subject_name(_name(common_name))
            .issuer_name(self.cert.subject)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(min(now, until) - timedelta(minutes=5))
            .not_valid_after(until)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(
                x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH if server else ExtendedKeyUsageOID.CLIENT_AUTH]),
                critical=False,
            )
        )
        alternatives: list[x509.GeneralName] = [x509.DNSName(n) for n in names]
        alternatives += [x509.IPAddress(ipaddress.ip_address(ip)) for ip in ips]
        if alternatives:
            builder = builder.add_extension(x509.SubjectAlternativeName(alternatives), critical=False)
        return Issued(builder.sign(self.key, hashes.SHA256()), key)


def verifies(cert: x509.Certificate, ca: x509.Certificate) -> bool:
    """Whether `ca` issued `cert` (its name, and its signature)."""
    try:
        cert.verify_directly_issued_by(ca)
    except (ValueError, TypeError, InvalidSignature):
        return False
    return True
