# SPDX-License-Identifier: Apache-2.0
"""The proof environments' helpers (2b-4b M4): a test PKI, a JWT key set and its tokens, the run directory each
container mounts only its own part of, and the session policies that keep D6's and D12's credential sets apart. Fast
and without Docker; the proofs themselves (d6/, d12/) are opt-in and run only when the owner authorizes them."""

import base64
import json
import os
import stat
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from tests.proofs import environment, pki, preversioning, tokens

BUCKET, PREFIX = "dewpoint-audit", "dewpoint/"


@pytest.fixture(autouse=True)
def _no_outer_record(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """These unit tests never append to a real run's project record (a runner's DEWPOINT_PROOF_PROJECTS): a test that
    needs one names its own."""
    monkeypatch.delenv("DEWPOINT_PROOF_PROJECTS", raising=False)


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
    run = environment.prepare(tmp_path / "run", start_check="off")
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
    run = environment.prepare(tmp_path / "run", start_check="off")
    argv, env = environment.compose(run, "jwt", "up", "-d")
    compose_file = environment.REPO / "deploy" / "temporal" / "compose.yaml"
    assert argv == ["docker", "compose", "-p", run.project, "-f", str(compose_file), "up", "-d"]
    assert env["DEWPOINT_M4_START_CHECK"] == "off"
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


# --- each run isolated: its own project, its own ports, cleanup of its own (the start-check slice, revision 17.3.1) --


class _Docker:
    """`docker`, faked: each command's argv recorded, each answered from `answers` by its first words."""

    def __init__(self, answers: dict[str, str]) -> None:
        self.answers, self.ran = answers, list[list[str]]()

    def __call__(self, argv: list[str], env: dict[str, str] | None = None) -> str:
        self.ran.append(argv)
        for start, answer in self.answers.items():
            if " ".join(argv).startswith(start):
                return answer
        return ""


def test_each_run_has_a_project_of_its_own_and_names_its_start_check(tmp_path: Path) -> None:
    first = environment.prepare(tmp_path / "a", start_check="off")
    second = environment.prepare(tmp_path / "b", start_check="on")
    assert first.project != second.project
    assert all(r.project.startswith("dewpoint-m4-") and len(r.project) > len("dewpoint-m4-") for r in (first, second))
    assert environment.compose(second, "jwt", "up")[1]["DEWPOINT_M4_START_CHECK"] == "on"
    with pytest.raises(ValueError, match="on or off"):
        environment.prepare(tmp_path / "c", start_check="maybe")


def test_the_cleanup_guard_compares_the_full_recorded_project_name(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    run = environment.prepare(tmp_path / "run", start_check="off")
    listing = "docker ps -a --filter"
    monkeypatch.setattr(environment, "DOCKER", _Docker({listing: f"{run.project}\n{run.project}\n"}))
    environment.guard_own(run)
    for foreign in ("dewpoint-m4", run.project[:-1], run.project + "x", "another"):
        monkeypatch.setattr(environment, "DOCKER", _Docker({listing: f"{run.project}\n{foreign}\n"}))
        with pytest.raises(RuntimeError, match="not this run's"):
            environment.guard_own(run)


def test_a_project_already_holding_containers_or_networks_is_refused_before_up(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    run = environment.prepare(tmp_path / "run", start_check="off")
    monkeypatch.setattr(environment, "DOCKER", _Docker({}))
    environment.guard_fresh(run)
    for kind in ("docker ps -a", "docker network ls"):
        monkeypatch.setattr(environment, "DOCKER", _Docker({kind: "abc123\n"}))
        with pytest.raises(RuntimeError, match="already"):
            environment.guard_fresh(run)


def test_an_assigned_port_is_read_back_and_forgotten_when_a_service_is_recreated(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    run = environment.prepare(tmp_path / "run", start_check="off")
    docker = _Docker({"docker compose": "127.0.0.1:49153\n"})
    monkeypatch.setattr(environment, "DOCKER", docker)
    assert environment.assigned_port(run, "temporal", 7233) == 49153
    assert environment.assigned_port(run, "temporal", 7233) == 49153 and len(docker.ran) == 1  # remembered
    assert docker.ran[0][:4] == ["docker", "compose", "-p", run.project]
    assert docker.ran[0][-3:] == ["port", "temporal", "7233"]
    environment.forget_ports(run)
    assert environment.assigned_port(run, "temporal", 7233) == 49153 and len(docker.ran) == 2
    monkeypatch.setattr(environment, "DOCKER", _Docker({"docker compose": "nothing useful\n"}))
    environment.forget_ports(run)
    with pytest.raises(RuntimeError, match="no port"):
        environment.assigned_port(run, "temporal", 7233)


def test_down_checks_the_project_before_it_removes_anything(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    run = environment.prepare(tmp_path / "run", start_check="off")
    run.state["fresh"] = True  # the run brought its project up (`run_compose`'s first `up`)
    order: list[str] = []
    monkeypatch.setattr(environment, "guard_own", lambda r: order.append("guarded"))
    monkeypatch.setattr(environment, "run_compose", lambda r, config, *args, **kw: order.append(" ".join(args)) or "")
    environment.down(run, "jwt")
    assert order == ["guarded", "--profile start-check down -v --remove-orphans"]


def test_the_compose_file_binds_no_fixed_host_port_and_requires_the_start_checks_mode() -> None:
    import yaml

    spec = yaml.safe_load((environment.REPO / "deploy" / "temporal" / "compose.yaml").read_text())
    published = [p for service in spec["services"].values() for p in service.get("ports", [])]
    assert published and all(p.startswith("127.0.0.1::") for p in published), published
    temporal = spec["services"]["temporal"]["environment"]
    assert temporal["DEWPOINT_AUTHZ_START_CHECK"].startswith("${DEWPOINT_M4_START_CHECK:?")
    assert spec["services"]["dewpoint-db"]["profiles"] == ["start-check"]


def test_a_run_with_the_start_check_on_has_its_dsn_and_its_profile(tmp_path: Path) -> None:
    on = environment.prepare(tmp_path / "on", start_check="on")
    password = (on.root / "start_check_password").read_text()
    assert len(password) >= 24 and password != (on.root / "dewpoint_db_password").read_text()
    assert (on.root / "authz" / "start_check_dsn").read_text() == (
        f"postgresql://{environment.START_CHECK_LOGIN}:{password}@dewpoint-db:5432/dewpoint?sslmode=disable"
    )  # the project's own database, through its network: never another
    argv, env = environment.compose(on, "jwt", "up", "-d")
    assert env["COMPOSE_PROFILES"] == "start-check" and password not in " ".join(argv)
    off = environment.prepare(tmp_path / "off", start_check="off")
    assert not (off.root / "authz" / "start_check_dsn").exists() and not (off.root / "start_check_password").exists()
    assert environment.compose(off, "jwt", "up", "-d")[1]["COMPOSE_PROFILES"] == ""


def test_the_start_checks_deadline_leaves_the_dispatchers_call_room_to_hear_its_denial() -> None:
    """Revision 17.2's bounds: a check that can't finish is denied "check unavailable" well before the dispatcher's own
    call deadline (`START_DEADLINE`) runs out, so its answer is a denial, never a timeout."""
    import re
    from datetime import timedelta

    import yaml

    from dewpoint.apps.dispatcher.dispatch import START_DEADLINE

    spec = yaml.safe_load((environment.REPO / "deploy" / "temporal" / "compose.yaml").read_text())
    temporal = spec["services"]["temporal"]["environment"]
    deadline = re.fullmatch(r"(\d+)s", temporal["DEWPOINT_AUTHZ_START_CHECK_DEADLINE"])
    assert deadline is not None
    assert 2 * timedelta(seconds=int(deadline.group(1))) <= START_DEADLINE


def test_d12_keeps_the_authorizers_errors_unexposed_in_both_configurations() -> None:
    """Revisions 16 and 17: a denial reaches the dispatcher by its fixed reason alone; the authorizer's own errors stay
    unexposed (`frontend.exposeAuthorizerErrors: false`), in the dynamic configuration both configurations load."""
    import yaml

    config = environment.COMPOSE.parent / "config"
    assert yaml.safe_load((config / "dynamicconfig.yaml").read_text())["frontend.exposeAuthorizerErrors"] == [
        {"value": False}
    ]
    for name in ("mtls.yaml", "jwt.yaml"):
        assert "filepath: /etc/temporal/dynamicconfig.yaml" in (config / name).read_text(), name


# --- the server image's build identity: a proof refuses one built from anything but this tree (the owner, 2026-10-10)


def _shell_identity(root: Path) -> str:
    """The build context's identity as the Dockerfile's shell computes it (`SOURCE_PIPELINE`), run here."""
    done = subprocess.run(["/bin/sh", "-c", environment.SOURCE_PIPELINE], cwd=root, capture_output=True, text=True,
                          check=True)  # fmt: skip
    return done.stdout.strip()


def test_the_server_image_is_stamped_with_its_build_contexts_identity_as_the_harness_computes_it() -> None:
    dockerfile = (environment.SERVER_CONTEXT / "Dockerfile").read_text()
    assert f'identity="$({environment.SOURCE_PIPELINE})"' in dockerfile  # in the build stage, before anything writes
    assert "-X main.source=${identity}" in dockerfile  # the server binary's, which its inventory reports
    assert environment.source_identity() == _shell_identity(environment.SERVER_CONTEXT)


def test_the_identity_follows_every_file_of_the_context(tmp_path: Path) -> None:
    root = tmp_path / "context"
    (root / "internal" / "x").mkdir(parents=True)
    (root / "main.go").write_text("package main\n")
    (root / "internal" / "x" / "x.go").write_text("package x\n")
    (root / ".hidden").write_text("a dotfile")
    (root / "B.txt").write_text("upper case first, in C order")
    (root / "empty").mkdir()
    first = environment.source_identity(root)
    assert first == _shell_identity(root)  # hidden files, nesting, empty directories and C order, as the shell has them
    (root / "main.go").write_text("package main // changed\n")
    changed = environment.source_identity(root)
    (root / "internal" / "y.go").write_text("package internal\n")
    added = environment.source_identity(root)
    (root / "internal" / "y.go").rename(root / "internal" / "z.go")
    renamed = environment.source_identity(root)
    assert len({first, changed, added, renamed}) == 4 and renamed == _shell_identity(root)


def test_a_server_image_not_built_from_this_tree_is_refused_before_a_proof_uses_it(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    config = environment.SERVER_CONTEXT / "config" / "jwt.yaml"
    identity = environment.source_identity()
    docker = _Docker({"docker run": json.dumps({"binary": "sha256:x", "source": identity})})
    monkeypatch.setattr(environment, "DOCKER", docker)
    environment.check_server_image("img:local", config)
    [argv] = docker.ran
    assert argv[:5] == ["docker", "run", "--rm", "--network", "none"] and argv[-2:] == ["img:local", "inventory"]
    assert f"{config}:/etc/temporal/config.yaml:ro" in argv
    # a stale image (from before the identity), an unstamped binary, another tree's, or no inventory at all
    for answer in ("{}", '{"source": "unrecorded"}', json.dumps({"source": "0" * 64}), "not an inventory"):
        monkeypatch.setattr(environment, "DOCKER", _Docker({"docker run": answer}))
        with pytest.raises(RuntimeError, match="wasn't built from this tree"):
            environment.check_server_image("img:local", config)


def test_d12s_server_fixture_checks_the_images_identity_before_anything_starts(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from tests.proofs.d12 import test_d12

    checked: list[str] = []

    def stale(image: str, config: Path) -> None:
        checked.append(image)
        raise RuntimeError(f"{image} wasn't built from this tree")

    monkeypatch.setattr(test_d12.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0, stdout="sha256:x"))
    monkeypatch.setattr(environment, "check_server_image", stale)
    with pytest.raises(pytest.fail.Exception, match="wasn't built from this tree"):
        test_d12._need_images(test_d12)
    assert checked == [test_d12.SERVER_IMAGE]


# --- each run names its images: the start-check proof never falls back to the shared `:local` ones (the owner)

SC_SERVER, SC_CLIENT = "dewpoint-m4/temporal-server:sc-3301ec07ff71", "dewpoint-m4/proofclient:sc-3301ec07ff71"


def _imported_images(**env: str) -> list[str]:
    """test_d12's images, as a fresh process importing it with `env` sees them."""
    clean = {k: v for k, v in os.environ.items() if k not in ("DEWPOINT_M4_IMAGE", "DEWPOINT_M4_PROOF_CLIENT")}
    done = subprocess.run([sys.executable, "-c", "from tests.proofs.d12 import test_d12 as t; "
                           "print(t.SERVER_IMAGE); print(t.PROOF_CLIENT)"],
                          cwd=environment.REPO / "backend", env={**clean, **env}, capture_output=True, text=True,
                          check=True)  # fmt: skip
    return done.stdout.split()


def test_a_run_selects_its_proof_client_by_setting_and_the_default_stays_local() -> None:
    assert _imported_images() == ["dewpoint-m4/temporal-server:local", "dewpoint-m4/proofclient:local"]
    assert _imported_images(DEWPOINT_M4_IMAGE=SC_SERVER, DEWPOINT_M4_PROOF_CLIENT=SC_CLIENT) == [SC_SERVER, SC_CLIENT]


def _selected(monkeypatch, *, named: bool = True) -> tuple[Any, list[list[str]], list[str]]:  # type: ignore[no-untyped-def]
    """test_d12 with the start-check run's images selected (and, `named`, named by the run's settings); every docker
    command it runs recorded, every image there; the identity check recorded."""
    from tests.proofs.d12 import test_d12

    monkeypatch.setattr(test_d12, "SERVER_IMAGE", SC_SERVER)
    monkeypatch.setattr(test_d12, "PROOF_CLIENT", SC_CLIENT)
    for name, value in (("DEWPOINT_M4_IMAGE", SC_SERVER), ("DEWPOINT_M4_PROOF_CLIENT", SC_CLIENT)):
        if named:
            monkeypatch.setenv(name, value)
        else:
            monkeypatch.delenv(name, raising=False)
    ran: list[list[str]] = []
    checked: list[str] = []

    def run(argv: list[str], **kwargs: Any) -> Any:
        ran.append(argv)
        inspected = argv[:3] == ["docker", "image", "inspect"]
        return SimpleNamespace(returncode=0, stdout="sha256:" + "0" * 64 if inspected else "", stderr="")

    monkeypatch.setattr(test_d12.subprocess, "run", run)
    monkeypatch.setattr(environment, "check_server_image", lambda image, config: checked.append(image))
    return test_d12, ran, checked


def test_the_start_check_proofs_fixture_inspects_the_images_its_run_named(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from tests.proofs.d12 import test_start_check

    test_d12, ran, checked = _selected(monkeypatch)
    assert test_d12._need_images(test_start_check) == "sha256:" + "0" * 64  # the checked server's ID, for its runs
    inspected = [argv[-1] for argv in ran if argv[:3] == ["docker", "image", "inspect"]]
    assert inspected == [SC_SERVER, SC_CLIENT, test_d12.ADMIN_TOOLS] and checked == [SC_SERVER]


def test_the_start_check_proof_never_falls_back_to_the_local_images(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from tests.proofs.d12 import test_start_check

    assert test_start_check.EXPLICIT_IMAGES is True
    test_d12, ran, _ = _selected(monkeypatch, named=False)
    with pytest.raises(pytest.fail.Exception, match="names its images"):
        test_d12._need_images(test_start_check)
    assert ran == []  # refused before anything is inspected
    test_d12, ran, _ = _selected(monkeypatch)
    monkeypatch.setattr(test_d12, "PROOF_CLIENT", "dewpoint-m4/proofclient:local")  # not what the run named
    with pytest.raises(pytest.fail.Exception, match="not the one the run named"):
        test_d12._need_images(test_start_check)


def test_every_proof_client_invocation_uses_the_selected_image(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    test_d12, ran, _ = _selected(monkeypatch)
    for config in (environment.JWT, environment.MTLS):
        server = test_d12.Server(environment.prepare(tmp_path / config, start_check="off"), config)
        test_d12._proof_client(server, "sweep")
        test_d12._proof_client(server, "sweep", internal=True)
    assert len(ran) == 4
    assert all(SC_CLIENT in argv and "dewpoint-m4/proofclient:local" not in argv for argv in ran), ran


# --- cleanup: every project a run brings up is removed, however the run ends (the owner's review of the fixture)


class _Compose:
    """`subprocess.run` for the harness, faked: each command's argv recorded; a compose `up` fails when `failing_up`,
    and `docker logs` raises `logs_error` when set."""

    def __init__(self, *, failing_up: bool = False, logs_error: BaseException | None = None,
                 on_up: Any = None) -> None:  # fmt: skip
        self.ran: list[list[str]] = []
        self.failing_up, self.logs_error, self.on_up = failing_up, logs_error, on_up

    def __call__(self, argv: list[str], **kwargs: Any) -> Any:
        self.ran.append(argv)
        if argv[:2] == ["docker", "logs"] and self.logs_error is not None:
            raise self.logs_error
        if argv[:2] == ["docker", "compose"] and "up" in argv:
            if self.on_up is not None:
                self.on_up()
            if self.failing_up:
                return SimpleNamespace(returncode=1, stdout="", stderr="up failed")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    def downs(self) -> list[list[str]]:
        return [argv for argv in self.ran if argv[:2] == ["docker", "compose"] and "down" in argv]


def _quiet_setup(monkeypatch) -> Any:  # type: ignore[no-untyped-def]
    """test_d12, with every step after the first `up` a no-op that reaches no service."""
    from tests.proofs.d12 import test_d12

    async def registered(server: Any) -> None:
        return None

    for name in ("wait_for_s3", "make_bucket", "write_credentials"):
        monkeypatch.setattr(environment, name, lambda *a, **k: None)
    monkeypatch.setattr(environment, "s3", lambda *a, **k: None)
    monkeypatch.setattr(environment, "assume", lambda *a, **k: {})
    monkeypatch.setattr(test_d12, "_wait_for_frontend", lambda server: None)
    monkeypatch.setattr(test_d12, "_register_proof_namespace", registered)
    return test_d12


def test_a_failing_first_up_is_cleaned_up(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    test_d12 = _quiet_setup(monkeypatch)
    fake = _Compose(failing_up=True)
    monkeypatch.setattr(subprocess, "run", fake)
    monkeypatch.setattr(environment, "DOCKER", _Docker({}))  # a fresh project: nothing of it exists
    with pytest.raises(RuntimeError, match="docker compose up failed"):
        with test_d12._served(test_d12, environment.JWT, tmp_path / "run"):
            pass
    assert len(fake.downs()) == 1  # the project its first `up` may have half-made goes, all its profiles


def test_the_project_is_removed_even_when_its_logs_cant_be_kept(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    test_d12 = _quiet_setup(monkeypatch)
    monkeypatch.setattr(environment, "DOCKER", _Docker({}))
    for failure in ("logs", "write"):
        fake = _Compose(logs_error=subprocess.TimeoutExpired(["docker", "logs"], 30) if failure == "logs" else None)
        monkeypatch.setattr(subprocess, "run", fake)
        parent = tmp_path / failure
        parent.mkdir()
        with pytest.raises((subprocess.TimeoutExpired, PermissionError)):
            with test_d12._served(test_d12, environment.JWT, parent / "run"):
                if failure == "write":
                    parent.chmod(0o500)  # its log can't be written beside the run
        parent.chmod(0o700)
        assert len(fake.downs()) == 1, failure


def test_a_project_name_collision_is_never_removed(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    """A random name already in use (a collision guard_fresh refuses) belongs to someone else: the run brought nothing
    up, so its cleanup removes nothing, and records nothing for the outer runner."""
    test_d12 = _quiet_setup(monkeypatch)
    fake = _Compose()
    monkeypatch.setattr(subprocess, "run", fake)
    monkeypatch.setattr(environment, "DOCKER", _Docker({"docker ps -a": "abc123\n"}))
    projects = tmp_path / "projects"
    monkeypatch.setenv("DEWPOINT_PROOF_PROJECTS", str(projects))
    with pytest.raises(RuntimeError, match="already"):
        with test_d12._served(test_d12, environment.JWT, tmp_path / "run"):
            pass
    assert fake.ran == [] and not projects.exists()  # not even its logs: the container of that name isn't the run's


def test_the_project_is_recorded_before_its_first_up_and_after_its_guard(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    run = environment.prepare(tmp_path / "run", start_check="on")
    projects = tmp_path / "projects"
    monkeypatch.setenv("DEWPOINT_PROOF_PROJECTS", str(projects))
    seen: list[str] = []
    fake = _Compose(on_up=lambda: seen.append(projects.read_text()))
    monkeypatch.setattr(subprocess, "run", fake)
    monkeypatch.setattr(environment, "DOCKER", _Docker({}))
    environment.run_compose(run, environment.JWT, "up", "-d", "minio")
    environment.run_compose(run, environment.JWT, "up", "-d")
    assert seen == [f"{run.project}\n"] * 2  # there before the first `up` began, once


class _Listings:
    """`docker`, faked for `remove_project`: each listing answers from its own queue in turn (its last answer from then
    on); every command recorded."""

    def __init__(self, answers: dict[str, list[str]]) -> None:
        self.answers, self.ran = {k: list(v) for k, v in answers.items()}, list[list[str]]()

    def __call__(self, argv: list[str], env: dict[str, str] | None = None) -> str:
        self.ran.append(argv)
        for start, queue in self.answers.items():
            if " ".join(argv).startswith(start):
                return queue.pop(0) if len(queue) > 1 else queue[0]
        return ""


class _Processes:
    """The host's processes' command lines, faked for `remove_project`: each look answers from its queue in turn (its
    last answer from then on)."""

    def __init__(self, *answers: list[str]) -> None:
        self.answers, self.looks = list(answers) or [[]], 0

    def __call__(self) -> list[str]:
        self.looks += 1
        return self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]


def _quick(monkeypatch, processes: _Processes | None = None) -> list[float]:  # type: ignore[no-untyped-def]
    """`remove_project` without its waits (each recorded, returned), and with no compose client alive unless
    `processes` says otherwise."""
    slept: list[float] = []
    monkeypatch.setattr(environment, "SLEEP", slept.append)
    monkeypatch.setattr(environment, "PROCESSES", processes or _Processes())
    return slept


def test_a_killed_runs_project_is_removed_by_its_exact_name_only(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    project = "dewpoint-m4-0123456789ab"
    _quick(monkeypatch)
    listing = {"docker ps -a": f"c1 {project}\nc2 {project}\n", "docker volume ls": f"v1 {project}\n",
               "docker network ls": f"n1 {project}\n"}  # fmt: skip
    docker = _Listings({start: [answer, ""] for start, answer in listing.items()})  # gone once removed
    monkeypatch.setattr(environment, "DOCKER", docker)
    assert environment.remove_project(project) == ["container c1", "container c2", "volume v1", "network n1"]
    removals = [argv for argv in docker.ran if "rm" in argv]
    assert removals == [["docker", "rm", "-f", "-v", "c1", "c2"], ["docker", "volume", "rm", "v1"],
                        ["docker", "network", "rm", "n1"]]  # fmt: skip
    for listed in ("docker ps -a", "docker volume ls", "docker network ls"):
        docker = _Listings({**{k: [v] for k, v in listing.items()}, listed: [f"x1 {project}\nx2 {project}-other\n"]})
        monkeypatch.setattr(environment, "DOCKER", docker)
        with pytest.raises(RuntimeError, match="not the recorded project's"):
            environment.remove_project(project)
        assert not [argv for argv in docker.ran if "rm" in argv]  # checked whole before anything is removed
    docker = _Docker(listing)
    monkeypatch.setattr(environment, "DOCKER", docker)
    for name in ("dewpoint-m4", "dewpoint-ui4a", f"{project}x", "dewpoint-m4-0123456789AB"):
        with pytest.raises(ValueError, match="not a proof run's project"):
            environment.remove_project(name)
    assert docker.ran == []


def test_the_cleanup_command_removes_each_recorded_project_once(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    from tests.proofs import cleanup

    removed: list[str] = []
    monkeypatch.setattr(environment, "remove_project", lambda project: removed.append(project) or [])
    projects = tmp_path / "projects"
    projects.write_text("dewpoint-m4-0123456789ab\n\ndewpoint-m4-ba9876543210\ndewpoint-m4-0123456789ab\n")
    assert cleanup.main([str(projects)]) == 0
    assert removed == ["dewpoint-m4-0123456789ab", "dewpoint-m4-ba9876543210"]
    assert cleanup.main([str(tmp_path / "none")]) == 0 and removed[2:] == []  # nothing recorded: nothing to remove


def test_the_start_check_run_requires_its_project_record(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from tests.proofs.d12 import test_d12, test_start_check

    assert test_start_check.OUTER_CLEANUP is True
    monkeypatch.delenv("DEWPOINT_PROOF_PROJECTS", raising=False)
    with pytest.raises(pytest.fail.Exception, match="DEWPOINT_PROOF_PROJECTS"):
        test_d12._need_project_record(test_start_check)
    test_d12._need_project_record(test_d12)  # the other proofs don't require it
    monkeypatch.setenv("DEWPOINT_PROOF_PROJECTS", "/somewhere/projects")
    test_d12._need_project_record(test_start_check)


def test_a_container_that_appears_after_the_listing_is_removed_too_and_the_project_confirmed_empty(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """The final review's M8: a create still in flight in the daemon (compose killed mid-`up`) can land after the first
    listing. The project is listed again after each removal, and removal is confirmed only once nothing is left."""
    project = "dewpoint-m4-0123456789ab"
    _quick(monkeypatch)
    docker = _Listings({"docker ps -a": [f"c1 {project}\n", f"c3 {project}\n", ""], "docker volume ls": [""],
                        "docker network ls": [f"n1 {project}\n", ""]})  # fmt: skip
    monkeypatch.setattr(environment, "DOCKER", docker)
    assert environment.remove_project(project) == ["container c1", "network n1", "container c3"]
    last = [argv[:3] for argv in docker.ran[-3:]]  # it ended on a whole listing, found empty
    assert last == [["docker", "ps", "-a"], ["docker", "volume", "ls"], ["docker", "network", "ls"]]


def test_a_project_that_wont_go_is_never_confirmed_removed(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    project = "dewpoint-m4-0123456789ab"
    _quick(monkeypatch)
    monkeypatch.setattr(environment, "DOCKER", _Listings({"docker ps -a": [f"c1 {project}\n"]}))  # always there
    with pytest.raises(RuntimeError, match="still has"):
        environment.remove_project(project)


def test_an_empty_project_is_confirmed_only_after_a_quiet_window(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """The owner's review of the follow-up: never confirmed on one empty listing. Two whole listings, QUIET_S apart,
    both find nothing, with no compose client of the project alive at either."""
    project = "dewpoint-m4-0123456789ab"
    processes = _Processes()
    slept = _quick(monkeypatch, processes)
    docker = _Listings({"docker ps -a": [""], "docker volume ls": [""], "docker network ls": [""]})
    monkeypatch.setattr(environment, "DOCKER", docker)
    assert environment.remove_project(project) == []
    assert slept == [environment.QUIET_S]
    assert [argv[:3] for argv in docker.ran] == [["docker", "ps", "-a"], ["docker", "volume", "ls"],
                                                 ["docker", "network", "ls"]] * 2  # fmt: skip
    assert processes.looks == 2


def test_a_create_landing_after_an_empty_listing_is_removed_before_the_project_is_confirmed(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """The owner's review of the follow-up: the first listing finds nothing, then a create compose sent before it was
    killed lands. It shows in the listing after the quiet window, is removed, and the quiet window starts over."""
    project = "dewpoint-m4-0123456789ab"
    slept = _quick(monkeypatch)
    docker = _Listings({"docker ps -a": ["", f"c9 {project}\n", ""], "docker volume ls": [""],
                        "docker network ls": [""]})  # fmt: skip
    monkeypatch.setattr(environment, "DOCKER", docker)
    assert environment.remove_project(project) == ["container c9"]
    assert ["docker", "rm", "-f", "-v", "c9"] in docker.ran
    assert slept == [environment.QUIET_S, environment.SETTLE_S, environment.QUIET_S]


def test_a_live_compose_client_of_the_project_keeps_it_unconfirmed(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """A compose client of the project still alive (one SIGKILL didn't end) may create more at any time: never
    confirmed while it lives, whatever the listings say. A client of another project doesn't count."""
    project = "dewpoint-m4-0123456789ab"
    monkeypatch.setattr(environment, "DOCKER", _Listings({"docker ps -a": [""], "docker volume ls": [""],
                                                          "docker network ls": [""]}))  # fmt: skip
    client = f"/usr/local/bin/docker compose -p {project} -f compose.yml up -d"
    _quick(monkeypatch, _Processes([client]))
    with pytest.raises(RuntimeError, match="still has"):
        environment.remove_project(project)
    _quick(monkeypatch, _Processes([], [client]))  # one there at the window's end: not quiet either
    with pytest.raises(RuntimeError, match="still has"):
        environment.remove_project(project)
    _quick(monkeypatch, _Processes([client], []))  # it ends: the quiet window starts after
    assert environment.remove_project(project) == []
    _quick(monkeypatch, _Processes([client.replace(project, "dewpoint-m4-ba9876543210")]))
    assert environment.remove_project(project) == []


def _recording(monkeypatch, tmp_path: Path, name: str = "run") -> tuple[Any, Path]:  # type: ignore[no-untyped-def]
    """A run whose projects (and creates in flight) are recorded, as the outer runner has them, its listings empty."""
    run = environment.prepare(tmp_path / name, start_check="on")
    projects = tmp_path / f"{name}-projects"
    monkeypatch.setenv("DEWPOINT_PROOF_PROJECTS", str(projects))
    monkeypatch.setattr(environment, "DOCKER", _Docker({}))
    return run, projects


def test_a_create_is_in_flight_from_before_launch_until_its_client_returns(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    """The owner's review of the race fix: confirmation fails closed for an interrupted create. Its record is written
    before compose starts and cleared only once the client returns, failing or not; nothing else is recorded."""
    run, projects = _recording(monkeypatch, tmp_path)
    during: list[list[str]] = []
    fake = _Compose(on_up=lambda: during.append(environment.interrupted_creates(projects, run.project)))
    monkeypatch.setattr(subprocess, "run", fake)
    environment.run_compose(run, environment.JWT, "up", "-d", "minio")
    assert [len(d) for d in during] == [1]  # in flight while compose ran
    assert environment.interrupted_creates(projects, run.project) == []  # its client returned
    fake.failing_up = True
    with pytest.raises(RuntimeError, match="failed"):
        environment.run_compose(run, environment.JWT, "up", "-d")
    assert [len(d) for d in during] == [1, 1]
    assert environment.interrupted_creates(projects, run.project) == []  # failing, it still returned
    lines = environment.creates_record(projects).read_text().splitlines()
    for args in (("pause", "minio"), ("exec", "-T", "minio", "true"), ("down", "-v")):
        environment.run_compose(run, environment.JWT, *args)
    assert environment.creates_record(projects).read_text().splitlines() == lines and len(lines) == 4


@pytest.mark.parametrize("stopped", [KeyboardInterrupt(), subprocess.TimeoutExpired(["docker"], 300)],
                         ids=["interrupted", "timed out"])  # fmt: skip
def test_a_create_whose_client_is_stopped_stays_in_flight(monkeypatch, tmp_path: Path, stopped: BaseException) -> None:  # type: ignore[no-untyped-def]
    """Stopped mid-create (the runner's SIGINT, the harness's timeout), subprocess.run kills its client, but the daemon
    may still land what it had accepted: the record stays."""
    run, projects = _recording(monkeypatch, tmp_path)

    def killed(argv: list[str], **kwargs: Any) -> Any:
        if argv[:2] == ["docker", "compose"] and "up" in argv:
            raise stopped
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", killed)
    with pytest.raises(type(stopped)):
        environment.run_compose(run, environment.JWT, "up", "-d")
    assert len(environment.interrupted_creates(projects, run.project)) == 1


@pytest.mark.parametrize("signal_number", [9, 15, 2], ids=["SIGKILL", "SIGTERM", "SIGINT"])
def test_cleanup_never_confirms_a_project_whose_client_a_signal_ended(  # type: ignore[no-untyped-def]
    monkeypatch, tmp_path: Path, capsys, signal_number: int
) -> None:
    """The owner's review of the in-flight record: a compose client a signal ended returns to subprocess.run as a
    negative code, not as a raise. That's a stopped client, not a return: its create stays in flight, and the cleanup,
    its listings empty, reports the project NOT confirmed. An ordinary failing exit (a positive code) still returned."""
    from tests.proofs import cleanup

    run, projects = _recording(monkeypatch, tmp_path)

    def ended(argv: list[str], **kwargs: Any) -> Any:
        return SimpleNamespace(returncode=-signal_number, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", ended)
    with pytest.raises(RuntimeError, match="failed"):
        environment.run_compose(run, environment.JWT, "up", "-d")
    assert len(environment.interrupted_creates(projects, run.project)) == 1
    _quick(monkeypatch)
    empty = _Listings({"docker ps -a": [""], "docker volume ls": [""], "docker network ls": [""]})
    monkeypatch.setattr(environment, "DOCKER", empty)
    assert cleanup.main([str(projects)]) == 1
    assert "NOT confirmed" in capsys.readouterr().out


def test_a_create_is_never_launched_unrecorded(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    run, projects = _recording(monkeypatch, tmp_path)
    environment.creates_record(projects).mkdir()  # the record can't be written
    fake = _Compose()
    monkeypatch.setattr(subprocess, "run", fake)
    with pytest.raises(OSError):
        environment.run_compose(run, environment.JWT, "up", "-d")
    assert not [argv for argv in fake.ran if argv[:2] == ["docker", "compose"]]


def test_cleanup_never_confirms_a_project_whose_create_was_in_flight(monkeypatch, tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    """The owner's review: a create in flight when its client was stopped can land after the second empty listing. The
    cleanup still removes what it finds, but reports the project not confirmed while its record says so; a project
    whose creates all returned is confirmed."""
    from tests.proofs import cleanup

    run, projects = _recording(monkeypatch, tmp_path)

    def killed(argv: list[str], **kwargs: Any) -> Any:
        raise KeyboardInterrupt

    monkeypatch.setattr(subprocess, "run", killed)
    with pytest.raises(KeyboardInterrupt):
        environment.run_compose(run, environment.JWT, "up", "-d")
    _quick(monkeypatch)
    late = _Listings({"docker ps -a": ["", "", f"c9 {run.project}\n"], "docker volume ls": [""],
                      "docker network ls": [""]})  # fmt: skip  # it lands after the second empty listing
    monkeypatch.setattr(environment, "DOCKER", late)
    assert cleanup.main([str(projects)]) == 1
    assert "NOT confirmed" in capsys.readouterr().out
    assert not [argv for argv in late.ran if "rm" in argv]  # never seen: only the record knew

    returned, returned_projects = _recording(monkeypatch, tmp_path, "returned")
    monkeypatch.setattr(subprocess, "run", _Compose())
    environment.run_compose(returned, environment.JWT, "up", "-d")
    _quick(monkeypatch)
    monkeypatch.setattr(environment, "DOCKER", _Listings({"docker ps -a": [""], "docker volume ls": [""],
                                                          "docker network ls": [""]}))  # fmt: skip
    assert cleanup.main([str(returned_projects)]) == 0
    assert "NOT confirmed" not in capsys.readouterr().out


def test_the_server_that_runs_is_the_image_its_run_checked(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    """The final review's M3: the identity check resolves the tag once; every `up` that creates the server is then
    checked to run that very image ID (D12.4's recreate included), so a tag moved in between fails the run."""
    from tests.proofs.d12 import test_d12

    checked, other = "sha256:" + "a" * 64, "sha256:" + "b" * 64
    server = test_d12.Server(
        environment.prepare(tmp_path / "run", start_check="off"), environment.JWT, image_id=checked
    )
    monkeypatch.setattr(environment, "run_compose", lambda *a, **k: "")
    docker = _Docker({"docker inspect": f"{checked}\n"})
    monkeypatch.setattr(environment, "DOCKER", docker)
    server.compose("up", "-d", "minio")  # not the server: nothing to check
    server.compose("up", "-d")  # every service: the server's container checked
    server.compose("up", "-d", "--force-recreate", "temporal")  # D12.4's recreate: checked again
    inspected = [argv for argv in docker.ran if argv[:2] == ["docker", "inspect"]]
    assert [argv[-1] for argv in inspected] == [server.container] * 2
    monkeypatch.setattr(environment, "DOCKER", _Docker({"docker inspect": f"{other}\n"}))
    with pytest.raises(RuntimeError, match="not the image the run checked"):
        server.compose("up", "-d")


def test_a_fixture_whose_server_isnt_the_checked_image_fails_and_still_removes_its_project(
    monkeypatch, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    test_d12 = _quiet_setup(monkeypatch)
    fake = _Compose()
    monkeypatch.setattr(subprocess, "run", fake)
    monkeypatch.setattr(environment, "DOCKER", _Docker({"docker inspect": "sha256:" + "b" * 64 + "\n"}))
    with pytest.raises(RuntimeError, match="not the image the run checked"):
        with test_d12._served(test_d12, environment.JWT, tmp_path / "run", image_id="sha256:" + "a" * 64):
            pass
    assert len(fake.downs()) == 1
