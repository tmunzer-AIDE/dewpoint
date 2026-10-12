# SPDX-License-Identifier: Apache-2.0
"""The server check's own TLS floor (CodeQL's py/insecure-protocol on #90): every handshake the procedure makes offers
TLS 1.2 or later because it says so, never because the platform's default happens to. Its `main` runs here against
fakes only: no socket opened, no target named but a placeholder."""

import ssl
from pathlib import Path

import pytest

from dewpoint.apps.cli import recovery
from tests.proofs.pki import Authority
from tests.qualification import server_verification


@pytest.mark.filterwarnings("ignore:ssl.TLSVersion.TLSv1 is deprecated:DeprecationWarning")  # the fake's weak default
def test_every_handshake_refuses_tls_below_1_2_whatever_the_platforms_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    create = ssl.create_default_context

    def permissive(*args: object, **kwargs: object) -> ssl.SSLContext:  # a platform whose default still allows TLS 1.0
        context = create(*args, **kwargs)  # type: ignore[arg-type]
        context.minimum_version = ssl.TLSVersion.TLSv1
        return context

    floors: list[ssl.TLSVersion] = []

    def handshake(host: str, port: int, context: ssl.SSLContext, name: str) -> str:
        floors.append(context.minimum_version)
        return "refused: faked"

    def server(dsn: str) -> None:
        raise ValueError("refused")

    ca = tmp_path / "ca.crt"
    ca.write_bytes(Authority.create("Dewpoint qualification test: the deployment's authority").cert_pem())
    monkeypatch.setattr(ssl, "create_default_context", permissive)
    monkeypatch.setattr(server_verification, "handshake", handshake)
    monkeypatch.setattr(recovery, "server", server)
    monkeypatch.setenv("DEWPOINT_QUALIFICATION_APPROVED", "TQ-2026-0001")
    monkeypatch.setattr("sys.argv", ["server_verification", "--host", "db.invalid", "--ca", str(ca),
                                     "--out", str(tmp_path / "record.jsonl")])  # fmt: skip

    server_verification.main()

    assert len(floors) == 4  # the authority and name, another name, another authority, the system's store
    assert all(floor >= ssl.TLSVersion.TLSv1_2 for floor in floors), floors
