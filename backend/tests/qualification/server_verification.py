# SPDX-License-Identifier: Apache-2.0
"""The target's PostgreSQL verified as the recovery tools verify it (design revision 10 §1, revision 11 §1), before
any credential: PostgreSQL's own TLS request, then the handshake against one authority, its name checked.

- the deployment's authority and the server's name: verified, over TLS 1.2 or later;
- the deployment's authority, another name: refused;
- another authority (a throwaway one, made here), the right name: refused;
- the system's store alone: refused, so the server's certificate is the private authority's, not a public one's;
- the tools' own DSN check refuses anything but `sslmode=verify-full` with that authority's file.

    DEWPOINT_QUALIFICATION_APPROVED=<id> python -m tests.qualification.server_verification --host db.example \\
      --ca ca.crt [--name db.example] --out server_verification.jsonl"""

import argparse
import socket
import ssl
import struct
from pathlib import Path

from dewpoint.apps.cli import recovery
from tests.proofs.pki import Authority
from tests.qualification.approval import Record, approved

DESCRIPTION = "The target's PostgreSQL verified as the recovery tools verify it: verify-full, its own authority alone."
SSL_REQUEST = struct.pack("!ii", 8, 80877103)  # PostgreSQL's SSLRequest


def handshake(host: str, port: int, context: ssl.SSLContext, name: str) -> str:
    """`verified <protocol>`, or why not: PostgreSQL's TLS request, then the handshake under `context`, for `name`."""
    with socket.create_connection((host, port), timeout=10) as raw:
        raw.sendall(SSL_REQUEST)
        if raw.recv(1) != b"S":
            return "refused: the server declined TLS"
        try:
            with context.wrap_socket(raw, server_hostname=name) as tls:
                return f"verified {tls.version()}"
        except ssl.SSLCertVerificationError as e:
            return f"refused: {e.verify_message}"
        except ssl.SSLError as e:
            return f"refused: {type(e).__name__}"


def _client(**trust: str) -> ssl.SSLContext:
    """A verifying client context over TLS 1.2 or later: the floor said here, never left to the platform's default."""
    context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, **trust)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    return context


def _pinned(ca: Path) -> ssl.SSLContext:
    context = _client(cafile=str(ca))
    context.check_hostname, context.verify_mode = True, ssl.CERT_REQUIRED
    return context


def main() -> int:
    approval = approved()
    parser = argparse.ArgumentParser(prog="python -m tests.qualification.server_verification", description=DESCRIPTION)
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, default=5432)
    parser.add_argument("--ca", type=Path, required=True, help="the deployment's authority's certificate")
    parser.add_argument("--name", help="the name the server's certificate is checked against (default: --host)")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    record = Record(args.out, "server_verification", approval)
    name = args.name or args.host
    record.write(target=f"{args.host}:{args.port}", name=name)

    answer = handshake(args.host, args.port, _pinned(args.ca), name)
    record.check(answer in ("verified TLSv1.2", "verified TLSv1.3"), "the deployment's authority and name: verified",
                 answer=answer)  # fmt: skip
    answer = handshake(args.host, args.port, _pinned(args.ca), "not-the-server.invalid")
    record.check(answer.startswith("refused"), "another name: refused", answer=answer)
    other = Authority.create("Dewpoint qualification: another authority")
    stranger = _client(cadata=other.cert_pem().decode())
    answer = handshake(args.host, args.port, stranger, name)
    record.check(answer.startswith("refused"), "another authority: refused", answer=answer)
    answer = handshake(args.host, args.port, _client(), name)
    record.check(answer.startswith("refused"), "the system's store alone: refused (a private authority)",
                 answer=answer)  # fmt: skip
    for weaker in ("require", "verify-ca", "prefer"):
        try:
            recovery.server(f"postgresql://rcv_q@{args.host}:{args.port}/dewpoint?sslmode={weaker}"
                            f"&sslrootcert={args.ca}")  # fmt: skip
            refused = False
        except ValueError:
            refused = True
        record.check(refused, f"the tools refuse sslmode={weaker}")
    return record.finished()


if __name__ == "__main__":
    raise SystemExit(main())
