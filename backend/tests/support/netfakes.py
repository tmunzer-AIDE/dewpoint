# SPDX-License-Identifier: Apache-2.0
"""Local network fakes for the egress tests (plugins-3 D7): raw HTTP/1.1 servers on 127.0.0.1, plain or TLS with a
test CA, whose handlers control every byte (a close mid-answer, a slow answer, an oversized body), and a resolver that
answers what a test says. No test reaches outside this host."""

import asyncio
import datetime
import ipaddress
import ssl
import tempfile
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from dewpoint.core.egress.addresses import Address, AllowEntry
from dewpoint.core.egress.guard import Guard

TENANT = uuid.UUID("00000000-0000-4000-8000-0000000000aa")
LOOPBACK_ENTRY = AllowEntry(ipaddress.ip_network("127.0.0.1/32"), None, TENANT)


@dataclass
class Request:
    method: str
    target: str
    headers: dict[str, str]
    body: bytes


type Handler = Callable[[Request, asyncio.StreamWriter], Awaitable[None]]


@dataclass
class Server:
    port: int
    requests: list[Request] = field(default_factory=list)


@dataclass(frozen=True)
class Tls:
    ca_pem: bytes
    cert_file: str
    key_file: str

    def client_context(self) -> ssl.SSLContext:
        ctx = ssl.create_default_context(cadata=self.ca_pem.decode())
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2  # as the platform's own context (httpx's)
        return ctx

    def server_context(self) -> ssl.SSLContext:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(self.cert_file, self.key_file)
        return ctx


@cache
def tls(names: tuple[str, ...] = ("dewpoint.test",)) -> Tls:
    """A CA and a server certificate for `names`, written once per session to a temporary directory."""
    now = datetime.datetime.now(datetime.UTC)
    ca_key = ec.generate_private_key(ec.SECP256R1())
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "dewpoint test CA")])
    ca = (
        x509.CertificateBuilder().subject_name(ca_name).issuer_name(ca_name).public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=30))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(x509.KeyUsage(False, False, False, False, False, True, True, False, False), critical=True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), critical=False)
        .sign(ca_key, hashes.SHA256())
    )  # fmt: skip
    key = ec.generate_private_key(ec.SECP256R1())
    cert = (
        x509.CertificateBuilder().subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, names[0])]))
        .issuer_name(ca_name).public_key(key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1)).not_valid_after(now + datetime.timedelta(days=30))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(n) for n in names]), critical=False)
        .add_extension(x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
        .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
        .sign(ca_key, hashes.SHA256())
    )  # fmt: skip
    folder = Path(tempfile.mkdtemp(prefix="dewpoint-tls-"))
    (folder / "cert.pem").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    (folder / "key.pem").write_bytes(
        key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    )
    return Tls(ca.public_bytes(serialization.Encoding.PEM), str(folder / "cert.pem"), str(folder / "key.pem"))


async def _read_request(reader: asyncio.StreamReader) -> Request | None:
    head = await reader.readuntil(b"\r\n\r\n")
    lines = head.decode("latin-1").split("\r\n")
    method, target, _ = lines[0].split(" ", 2)
    headers = {k.strip().lower(): v.strip() for k, _, v in (line.partition(":") for line in lines[1:] if line)}
    body = await reader.readexactly(int(headers.get("content-length", "0")))
    return Request(method, target, headers, body)


def respond(status: int = 200, body: bytes = b"ok", headers: Sequence[tuple[str, str]] = ()) -> Handler:
    async def handler(_: Request, writer: asyncio.StreamWriter) -> None:
        extra = "".join(f"{k}: {v}\r\n" for k, v in headers)
        writer.write(f"HTTP/1.1 {status} X\r\ncontent-length: {len(body)}\r\n{extra}\r\n".encode() + body)
        await writer.drain()

    return handler


@asynccontextmanager
async def serve(handler: Handler, *, tls_names: tuple[str, ...] | None = None) -> AsyncIterator[Server]:
    """A server on 127.0.0.1 answering each request with `handler` (keep-alive), TLS when `tls_names` is given."""
    server_state = Server(port=0)

    async def on_connect(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            while True:
                request = await _read_request(reader)
                if request is None:
                    break
                server_state.requests.append(request)
                await handler(request, writer)
                if writer.is_closing():
                    break
        except (asyncio.IncompleteReadError, ConnectionError, ssl.SSLError):
            pass
        finally:
            writer.close()

    context = tls(tls_names).server_context() if tls_names else None
    server = await asyncio.start_server(on_connect, "127.0.0.1", 0, ssl=context)
    server_state.port = server.sockets[0].getsockname()[1]
    try:
        yield server_state
    finally:
        server.close()


class Resolver:
    """Answers per name, in order: a list of answer lists is consumed one per lookup (rebinding)."""

    def __init__(self, answers: dict[str, list[str] | list[list[str]]]) -> None:
        self.answers, self.asked = answers, []

    async def resolve(self, host: str, port: int) -> Sequence[Address]:
        self.asked.append(host)
        found = self.answers.get(host, [])
        if found and isinstance(found[0], list):
            current = found.pop(0) if len(found) > 1 else found[0]
            return [ipaddress.ip_address(a) for a in current]  # type: ignore[union-attr]
        return [ipaddress.ip_address(a) for a in found]  # type: ignore[arg-type]


def guard(answers: dict[str, list[str] | list[list[str]]], entries: Sequence[AllowEntry] = (LOOPBACK_ENTRY,)) -> Guard:
    async def allowlist(_: uuid.UUID) -> list[AllowEntry]:
        return list(entries)

    return Guard(resolver=Resolver(answers), allowlist=allowlist)
