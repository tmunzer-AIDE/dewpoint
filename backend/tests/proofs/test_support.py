# SPDX-License-Identifier: Apache-2.0
"""The proof environments' helpers (2b-4b M4): a test PKI, a JWT key set and its tokens, the run directory each
container mounts only its own part of, and the session policies that keep D6's and D12's credential sets apart. Fast
and without Docker; the proofs themselves (d6/, d12/) are opt-in and run only when the owner authorizes them."""

import base64
import json
import os
import stat
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from tests.proofs import environment, pki, preversioning, tokens

BUCKET, PREFIX = "dewpoint-audit", "dewpoint/"


def _san(cert: x509.Certificate) -> list[str]:
    names = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    return [str(n) for n in names.get_values_for_type(x509.DNSName)] + [
        str(n) for n in names.get_values_for_type(x509.IPAddress)
    ]


def _usage(cert: x509.Certificate) -> list[x509.ObjectIdentifier]:
    return list(cert.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value)


def test_a_server_certificate_verifies_against_its_ca_and_not_another() -> None:
    ca, other = pki.Authority.create("dewpoint-m4 test CA"), pki.Authority.create("another CA")
    leaf = ca.issue("temporal.dewpoint-m4.test", server=True, names=["temporal.dewpoint-m4.test", "localhost"],
                    ips=["127.0.0.1"])  # fmt: skip
    assert pki.verifies(leaf.cert, ca.cert) and not pki.verifies(leaf.cert, other.cert)
    assert _san(leaf.cert) == ["temporal.dewpoint-m4.test", "localhost", "127.0.0.1"]
    assert _usage(leaf.cert) == [ExtendedKeyUsageOID.SERVER_AUTH]


def test_a_client_certificate_names_its_subject() -> None:
    leaf = pki.Authority.create("dewpoint-m4 test CA").issue("proof-admin", server=False)
    assert leaf.cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value == "proof-admin"
    assert _usage(leaf.cert) == [ExtendedKeyUsageOID.CLIENT_AUTH]


def _claims(token: str, keys: tokens.KeySet) -> tuple[dict[str, object], dict[str, object]]:
    head, body, sig = token.split(".")

    def pad(part: str) -> bytes:
        return base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))

    public = keys.private.public_key()
    assert isinstance(public, rsa.RSAPublicKey)
    public.verify(pad(sig), f"{head}.{body}".encode(), padding.PKCS1v15(), hashes.SHA256())
    return json.loads(pad(head)), json.loads(pad(body))


def test_a_token_is_signed_by_its_key_set_and_expires() -> None:
    keys = tokens.KeySet.create("k1")
    [published] = keys.jwks()["keys"]
    assert published["kid"] == "k1" and published["kty"] == "RSA" and published["alg"] == "RS256"
    now = int(time.time())
    token = keys.sign({"sub": "proof-admin", "permissions": ["temporal-system:admin"], "aud": "dewpoint-temporal"},
                      lifetime=60, now=now)  # fmt: skip
    header, claims = _claims(token, keys)
    assert header == {"alg": "RS256", "typ": "JWT", "kid": "k1"}
    assert claims["exp"] == now + 60 and claims["iat"] == now - tokens.SKEW_S and claims["sub"] == "proof-admin"
    _, expired = _claims(keys.sign({"sub": "x"}, lifetime=-60, now=now), keys)
    assert expired["exp"] == now - 60


def test_a_token_from_another_key_set_doesnt_verify() -> None:
    keys, other = tokens.KeySet.create("k1"), tokens.KeySet.create("k1")
    with pytest.raises(InvalidSignature):
        _claims(other.sign({"sub": "x"}, lifetime=60), keys)


def test_the_run_directory_gives_each_container_only_its_part(tmp_path: Path) -> None:
    run = environment.prepare(tmp_path / "run")
    assert stat.S_IMODE(os.stat(run.root).st_mode) == 0o700
    assert sorted(p.name for p in (run.root / "tls").iterdir()) == [
        "ca.pem", "frontend-key.pem", "frontend.pem", "internode-ca.pem", "internode-key.pem", "internode.pem",
    ]  # fmt: skip
    assert sorted(p.name for p in (run.root / "authz").iterdir()) == ["faults", "roles.json"]
    assert list((run.root / "authz" / "faults").iterdir()) == []
    assert json.loads((run.root / "jwks" / "jwks.json").read_text())["keys"][0]["kid"] == run.keys.kid
    roles = json.loads((run.root / "authz" / "roles.json").read_text())
    # Temporal's cluster scope is temporal-system: "system" would be a namespace of that name (R3-B's lesson)
    assert roles == {"proof-admin": ["temporal-system:admin"], "dewpoint-proof": [f"{environment.NAMESPACE}:write"]}
    secrets = [run.root / "db_password", run.root / "minio" / "root_user", run.root / "minio" / "root_password"]
    assert len({p.read_text() for p in secrets}) == 3 and all(len(p.read_text()) >= 24 for p in secrets)
    # the CAs' keys and the clients' certificates stay outside every mount
    mounted = [p for d in ("tls", "authz", "jwks") for p in (run.root / d).rglob("*")]
    assert not any("ca-key" in p.name or p.name.startswith(("proof-admin", "dewpoint-proof")) for p in mounted)
    assert (run.root / "pki" / "proof-admin.pem").exists() and (run.root / "pki" / "other-ca.pem").exists()
    leaf = x509.load_pem_x509_certificate((run.root / "tls" / "frontend.pem").read_bytes())
    assert pki.verifies(leaf, run.ca.cert) and "temporal.dewpoint-m4.test" in _san(leaf)
    # Temporal presents its one internode certificate as a server and as a client, to its own services and to the
    # internal frontend: it needs both usages (R3-B's second run: serverAuth alone, "tls: bad certificate")
    internode = x509.load_pem_x509_certificate((run.root / "tls" / "internode.pem").read_bytes())
    assert _usage(internode) == [ExtendedKeyUsageOID.SERVER_AUTH, ExtendedKeyUsageOID.CLIENT_AUTH]
    assert _usage(leaf) == [ExtendedKeyUsageOID.SERVER_AUTH]  # the frontend only serves


def test_the_session_policies_keep_the_credentials_apart() -> None:
    def actions(kind: str) -> dict[str, set[str]]:
        found: dict[str, set[str]] = {}
        for statement in environment.policy(kind, BUCKET, PREFIX)["Statement"]:
            assert statement["Effect"] == "Allow"
            for resource in statement["Resource"]:
                found.setdefault(resource, set()).update(statement["Action"])
        return found

    assert actions("anchor-writer") == {f"arn:aws:s3:::{BUCKET}/{PREFIX}anchors/*": {"s3:PutObject"}}
    assert actions("authorizer") == {f"arn:aws:s3:::{BUCKET}/{PREFIX}temporal-authorizer/*": {"s3:PutObject"}}
    verifier = actions("verifier")
    assert verifier == {
        f"arn:aws:s3:::{BUCKET}": {"s3:ListBucket", "s3:ListBucketVersions", "s3:GetBucketObjectLockConfiguration"},
        f"arn:aws:s3:::{BUCKET}/{PREFIX}*": {"s3:GetObject", "s3:GetObjectVersion", "s3:GetObjectRetention"},
    }


def test_the_compose_command_keeps_the_password_off_its_arguments(tmp_path: Path) -> None:
    run = environment.prepare(tmp_path / "run")
    argv, env = environment.compose(run, "jwt", "up", "-d")
    compose_file = environment.REPO / "deploy" / "temporal" / "compose.yaml"
    assert argv == ["docker", "compose", "-p", "dewpoint-m4", "-f", str(compose_file), "up", "-d"]
    assert compose_file.exists()
    password = (run.root / "db_password").read_text()
    assert password not in " ".join(argv)
    assert env["DEWPOINT_M4_DB_PASSWORD"] == password and env["DEWPOINT_M4_CONFIG"] == "jwt"
    assert env["DEWPOINT_M4_RUN"] == str(run.root)


class _Visibility:
    """A client whose visibility gives these answers in turn, then the last one from then on."""

    def __init__(self, *answers: list[str]) -> None:
        self._answers, self.asked = answers, 0

    def list_workflows(self, query: str) -> object:
        answer = self._answers[min(self.asked, len(self._answers) - 1)]
        self.asked += 1

        async def executions() -> object:
            for workflow_id in answer:
                yield SimpleNamespace(id=workflow_id)

        return executions()


async def test_the_pre_versioning_querys_empty_answer_is_waited_for_never_taken_as_its_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(preversioning, "POLL_S", 0)
    visibility = _Visibility([], [], ["unversioned"])
    assert await preversioning.first_answer(visibility, "q") == ["unversioned"]  # type: ignore[arg-type]
    assert visibility.asked == 3


async def test_the_pre_versioning_querys_wrong_answer_isnt_asked_again(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(preversioning, "POLL_S", 0)
    visibility = _Visibility(["unversioned", "versioned"], ["unversioned"])
    assert await preversioning.first_answer(visibility, "q") == ["unversioned", "versioned"]  # type: ignore[arg-type]
    assert visibility.asked == 1


async def test_the_pre_versioning_query_answering_nothing_fails_at_the_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(preversioning, "POLL_S", 0)
    monkeypatch.setattr(preversioning, "VISIBILITY_DEADLINE_S", 0.05)
    with pytest.raises(AssertionError, match="listed nothing"):
        await preversioning.first_answer(_Visibility([]), "q")  # type: ignore[arg-type]


async def test_a_control_waits_for_its_run_and_fails_on_another_or_on_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(preversioning, "POLL_S", 0)
    visibility = _Visibility([], [], ["closed"])
    assert await preversioning.until_listed(visibility, "q", "closed") >= 0  # type: ignore[arg-type]
    assert visibility.asked == 3
    with pytest.raises(AssertionError, match="listed"):
        await preversioning.until_listed(_Visibility(["versioned"]), "q", "closed")  # type: ignore[arg-type]
    monkeypatch.setattr(preversioning, "VISIBILITY_DEADLINE_S", 0.05)
    with pytest.raises(AssertionError, match="didn't list closed"):
        await preversioning.until_listed(_Visibility([]), "q", "closed")  # type: ignore[arg-type]
