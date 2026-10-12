# SPDX-License-Identifier: Apache-2.0
"""`dewpoint recovery confirm` (2b-4b M4 recovery, task 6; design revision 11 §1, plan ruling 4). An operator confirms
a command under their own recovery login. The tool reaches the database only with `sslmode=verify-full` against the
deployment's pinned authority, which it alone trusts: no CA file, a weaker mode, another issuer or another name is
refused before any credential is sent. It prints the database's canonical text and digest, nothing it built itself,
and after a typed `yes` confirms with that digest. A fake server stands in for the TLS cases; the flow runs against the
suite's database, its connection made as the login (the suite's server has no TLS)."""

import asyncio
import hashlib
import ipaddress
import re
import socket
import ssl
import threading
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import asyncpg
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
from sqlalchemy import text
from typer.testing import CliRunner

from dewpoint.apps.cli import recovery
from dewpoint.apps.cli.main import app
from dewpoint.core.db import make_engine, make_sessionmaker
from tests.apps.dispatcher.test_commands import asked, operator
from tests.core.retention.support import tenant
from tests.support.recovery import PASSWORD, mapped_login

# --- a pinned authority, and a server presenting a certificate -------------------------------------------------------


def _name(common: str) -> x509.Name:
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common)])


def _authority(common: str) -> tuple[x509.Certificate, ec.EllipticCurvePrivateKey]:
    key, now = ec.generate_private_key(ec.SECP256R1()), datetime.now(UTC)
    cert = (
        x509.CertificateBuilder().subject_name(_name(common)).issuer_name(_name(common)).public_key(key.public_key())
        .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(x509.KeyUsage(digital_signature=False, content_commitment=False, key_encipherment=False,
                                     data_encipherment=False, key_agreement=False, key_cert_sign=True, crl_sign=True,
                                     encipher_only=False, decipher_only=False), critical=True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
        .sign(key, hashes.SHA256())
    )  # fmt: skip
    return cert, key


def _served(authority: tuple[x509.Certificate, ec.EllipticCurvePrivateKey], names: list[x509.GeneralName],
            folder: Path) -> tuple[Path, Path]:  # fmt: skip
    """A server certificate for `names`, signed by `authority`: its certificate and key files."""
    issuer, issuer_key = authority
    key, now = ec.generate_private_key(ec.SECP256R1()), datetime.now(UTC)
    cert = (
        x509.CertificateBuilder().subject_name(_name("db")).issuer_name(issuer.subject).public_key(key.public_key())
        .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName(names), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(issuer_key.public_key()), critical=False)
        .sign(issuer_key, hashes.SHA256())
    )  # fmt: skip
    stem = uuid.uuid4().hex[:8]
    cert_file, key_file = folder / f"{stem}.crt", folder / f"{stem}.key"
    cert_file.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_file.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                           serialization.NoEncryption()))  # fmt: skip
    return cert_file, key_file


class FakeServer:
    """Answers a client's TLS request with its certificate, and records what the client sends once the handshake is
    through (the startup message, which names the login, comes first)."""

    def __init__(self, cert_file: Path, key_file: Path) -> None:
        self.context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self.context.load_cert_chain(cert_file, key_file)
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen()
        self.port = self.sock.getsockname()[1]
        self.connections, self.received = 0, b""
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _serve(self) -> None:
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            self.connections += 1
            with conn:
                conn.settimeout(5)
                try:
                    if conn.recv(8) != bytes.fromhex("0000000804d2162f"):  # an SSLRequest, or nothing to answer
                        continue
                    conn.sendall(b"S")
                    with self.context.wrap_socket(conn, server_side=True) as tls:
                        self.received += tls.recv(4096)
                except (ssl.SSLError, OSError):
                    continue

    def close(self) -> None:
        self.sock.close()
        self.thread.join(5)


@pytest.fixture(scope="module")
def pki(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    folder = tmp_path_factory.mktemp("pki")
    pinned, other = _authority("deployment CA"), _authority("another CA")
    ca_file = folder / "ca.pem"
    ca_file.write_bytes(pinned[0].public_bytes(serialization.Encoding.PEM))
    local = [x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
    return {
        "ca": ca_file,
        "good": _served(pinned, local, folder),
        "other issuer": _served(other, local, folder),
        "other name": _served(pinned, [x509.DNSName("db.other.example")], folder),
    }


@pytest.fixture
def served(pki: dict[str, Any], request: pytest.FixtureRequest) -> Iterator[FakeServer]:
    server = FakeServer(*pki[request.param])
    yield server
    server.close()


def _dsn(port: int, ca: Path | str, login: str = "rcv_alice", **extra: str) -> str:
    query = "&".join(f"{k}={v}" for k, v in {"sslmode": "verify-full", "sslrootcert": str(ca), **extra}.items() if v)
    return f"postgresql://{login}@127.0.0.1:{port}/dewpoint?{query}"


# --- refused before any connection -----------------------------------------------------------------------------------

REFUSED = {  # a DSN's change from a good one: why it's refused
    "sslmode=require": ({"sslmode": "require"}, "sslmode=verify-full"),
    "no sslmode": ({"sslmode": ""}, "sslmode=verify-full"),
    "no CA file named": ({"sslrootcert": ""}, "sslrootcert"),
    "a CA file missing": ({"sslrootcert": "/nonexistent/ca.pem"}, "sslrootcert"),
    "another parameter": ({"sslcert": "client.pem"}, "sslcert"),
}


@pytest.mark.parametrize("served", ["good"], indirect=True)
@pytest.mark.parametrize("case", REFUSED)
def test_a_weaker_or_unpinned_connection_is_refused_before_any_is_made(
    served: FakeServer, pki: dict[str, Any], case: str
) -> None:
    change, why = REFUSED[case]
    dsn = _dsn(served.port, pki["ca"], **change)
    result = CliRunner().invoke(app, ["recovery", "confirm", str(uuid.uuid4()), "--dsn", dsn], input="pw\nyes\n")
    assert result.exit_code == 2 and why in result.output, result.output
    assert served.connections == 0


@pytest.mark.parametrize("served", ["good"], indirect=True)
def test_a_password_in_the_dsn_is_refused(served: FakeServer, pki: dict[str, Any]) -> None:
    dsn = _dsn(served.port, pki["ca"]).replace("rcv_alice@", "rcv_alice:secret@")
    result = CliRunner().invoke(app, ["recovery", "confirm", str(uuid.uuid4()), "--dsn", dsn])
    assert result.exit_code == 2 and "password" in result.output, result.output
    assert served.connections == 0


# --- the server's certificate ----------------------------------------------------------------------------------------


@pytest.mark.parametrize("served", ["other issuer", "other name"], indirect=True)
def test_a_server_the_pinned_authority_doesnt_vouch_for_by_name_sees_no_startup(
    served: FakeServer, pki: dict[str, Any]
) -> None:
    target = recovery.server(_dsn(served.port, pki["ca"]))
    with pytest.raises((ssl.SSLError, OSError)):
        asyncio.run(recovery.connect(target, PASSWORD))
    assert served.connections >= 1 and served.received == b""  # no startup message, no login, no password


@pytest.mark.parametrize("served", ["good"], indirect=True)
def test_the_server_the_pinned_authority_vouches_for_is_sent_the_startup(
    served: FakeServer, pki: dict[str, Any]
) -> None:
    """The control: the same client, the server's certificate as pinned and named, goes on to sign in."""
    target = recovery.server(_dsn(served.port, pki["ca"], login="rcv_alice"))
    with pytest.raises((ConnectionError, OSError, asyncpg.PostgresError, asyncpg.InterfaceError)):
        asyncio.run(recovery.connect(target, PASSWORD))  # the fake server answers no further
    assert b"user\x00rcv_alice\x00" in served.received


# --- the confirmation ------------------------------------------------------------------------------------------------


async def _pending(pg_url: str) -> tuple[uuid.UUID, str]:
    """An unconfirmed command, and its actor's login."""
    engine = make_engine(pg_url)
    owner = make_sessionmaker(engine)
    try:
        ctx, admin = await tenant(owner), await operator(owner)
        _, command = await asked(owner, ctx, "record_lost_run", admin, confirmed=False)
        return command, await mapped_login(owner, admin)
    finally:
        await engine.dispose()


async def _read(pg_url: str, query: str, **values: Any) -> Any:
    engine = make_engine(pg_url)
    try:
        async with make_sessionmaker(engine)() as s:
            return (await s.execute(text(query), values)).scalar()
    finally:
        await engine.dispose()


def _as_the_login(monkeypatch: pytest.MonkeyPatch, pg_url: str, login: str) -> None:
    """The tool's connection, made to the suite's database as the login, with the password it was typed."""
    address = pg_url.split("@", 1)[1]

    async def connect(target: recovery.Target, password: str) -> asyncpg.Connection:
        assert target.user == login and password == PASSWORD
        return await asyncpg.connect(f"postgresql://{login}:{password}@{address}")

    monkeypatch.setattr(recovery, "connect", connect)


def test_the_tool_prints_the_databases_text_and_digest_and_confirms_with_that_digest(
    pg_url: str, pki: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    command, login = asyncio.run(_pending(pg_url))
    _as_the_login(monkeypatch, pg_url, login)
    result = CliRunner().invoke(app, ["recovery", "confirm", str(command), "--dsn", _dsn(5432, pki["ca"], login)],
                                input=f"{PASSWORD}\nyes\n")  # fmt: skip
    assert result.exit_code == 0, result.output
    canonical = asyncio.run(_read(pg_url, "select operator_command_canonical(:c)", c=command))
    printed = re.search(r"digest: sha256:([0-9a-f]{64})", result.output)
    assert canonical in result.output and printed is not None  # the database's text, exactly
    digest = bytes.fromhex(printed[1])
    assert hashlib.sha256(canonical.encode()).digest() == digest
    assert bytes(asyncio.run(_read(pg_url, "select operator_command_digest(:c)", c=command))) == digest  # the leader's
    assert bytes(asyncio.run(_read(pg_url, "select digest from operator_confirmations where command_id = :c",
                                   c=command))) == digest  # fmt: skip


def test_anything_but_yes_confirms_nothing(pg_url: str, pki: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    command, login = asyncio.run(_pending(pg_url))
    _as_the_login(monkeypatch, pg_url, login)
    result = CliRunner().invoke(app, ["recovery", "confirm", str(command), "--dsn", _dsn(5432, pki["ca"], login)],
                                input=f"{PASSWORD}\ny\n")  # fmt: skip
    assert result.exit_code == 1 and "not confirmed" in result.output, result.output
    assert asyncio.run(_read(pg_url, "select count(*) from operator_confirmations where command_id = :c",
                             c=command)) == 0  # fmt: skip
