# SPDX-License-Identifier: Apache-2.0
"""`dewpoint platform record-namespace-boundary` (2b-4b M4; the owner's ruling on the M4 design): the local namespace
boundary (D3g) recorded through the platform admin's API (D11), tied to the actual proof and to the server's and the
namespace's identity. Before asking the API, the command checks the D12 proof record is a whole pass (its SHA-256 and
the server build both its inventories name go with the row), then asks Temporal, with this deployment's own §10.4
settings, for the namespace's id and checks it as `dewpoint temporal check` does: TLS verified, retention at most 30
days, archival disabled. Any refusal ends it before the API is asked."""

import base64
import hashlib
import json
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from google.protobuf.duration_pb2 import Duration
from temporalio.api.enums.v1 import ArchivalState
from temporalio.api.namespace.v1 import NamespaceConfig, NamespaceInfo
from temporalio.api.workflowservice.v1 import DescribeNamespaceResponse
from typer.testing import CliRunner

from dewpoint.apps.cli import main as cli
from dewpoint.core.config import get_settings
from tests.apps.cli.test_keys import _env, _recorded
from tests.core.platform.test_boundary import BUILD, PASSED, case, lines

PW = "correct-horse-battery"
SAID = "D12 passed on the local proof environment, configurations A and B."
KEK = base64.b64encode(bytes(32)).decode()
NAMESPACE_ID = "8f1d2c3b-0000-4000-8000-000000000001"


def described(days: int = 30) -> DescribeNamespaceResponse:
    disabled = ArchivalState.ARCHIVAL_STATE_DISABLED
    config = NamespaceConfig(workflow_execution_retention_ttl=Duration(seconds=days * 86400),
                             history_archival_state=disabled, visibility_archival_state=disabled)  # fmt: skip
    return DescribeNamespaceResponse(namespace_info=NamespaceInfo(name="default", id=NAMESPACE_ID), config=config)


class _Asked:
    def __init__(self, answer: DescribeNamespaceResponse) -> None:
        self.api: list[dict[str, Any]] = []
        self.temporal = 0

        async def describe_namespace(request: object) -> DescribeNamespaceResponse:
            self.temporal += 1
            return answer

        self.client = SimpleNamespace(workflow_service=SimpleNamespace(describe_namespace=describe_namespace))


def _deployment(monkeypatch: pytest.MonkeyPatch, pg_url: str, answer: DescribeNamespaceResponse, *,
                tls: bool = True) -> _Asked:  # fmt: skip
    _env(monkeypatch, pg_url, DEWPOINT_KEK_B64=KEK)
    _recorded(pg_url)
    if tls:
        monkeypatch.delenv("DEWPOINT_TEMPORAL_INSECURE_DEV", raising=False)
    get_settings.cache_clear()
    asked = _Asked(answer)

    async def connect(settings: object, environment: str, **kwargs: object) -> object:
        return asked.client

    async def via_api(_client: object, **kwargs: Any) -> dict[str, Any]:
        asked.api.append(kwargs)
        return {"id": 7, **kwargs["evidence"], "recorded_by": "admin", "lost_at": None}

    monkeypatch.setattr(cli, "temporal_connect", connect)
    monkeypatch.setattr(cli, "boundary_via_api", via_api)
    return asked


def _invoke(proof: Path) -> Any:
    return CliRunner().invoke(cli.app, ["platform", "record-namespace-boundary", "--api", "https://dewpoint.test",
                                        "--email", "ops@corp.test", "--proof", str(proof), "--name", "d12-local",
                                        "--attestation", SAID], input=f"{PW}\n123456\n")  # fmt: skip


def test_a_whole_proof_and_a_namespace_within_the_rules_are_recorded(pg_url, monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    proof = tmp_path / "proof.jsonl"
    proof.write_bytes(lines(*PASSED))
    asked = _deployment(monkeypatch, pg_url, described())
    done = _invoke(proof)
    assert done.exit_code == 0, done.output
    [sent] = asked.api
    assert (sent["email"], sent["password"], sent["code"]) == ("ops@corp.test", PW, "123456")
    assert sent["evidence"] == {
        "name": "d12-local", "namespace": "default", "namespace_id": NAMESPACE_ID, "server_build": BUILD,
        "proof_digest": "sha256:" + hashlib.sha256(proof.read_bytes()).hexdigest(), "attestation": SAID,
    }  # fmt: skip
    assert "boundary 7 recorded" in done.output


def test_a_proof_record_that_isnt_a_whole_pass_is_refused_before_temporal_or_the_api(
    pg_url, monkeypatch, tmp_path
) -> None:  # type: ignore[no-untyped-def]
    proof = tmp_path / "proof.jsonl"
    proof.write_bytes(lines(*PASSED, case("test_d12_4_x", "failed")))
    asked = _deployment(monkeypatch, pg_url, described())
    done = _invoke(proof)
    assert done.exit_code == 2 and "the proof record is refused" in done.output
    assert (asked.temporal, asked.api) == (0, [])


@pytest.mark.parametrize(("answer", "tls", "why"), [
    (described(days=31), True, "retention of 31 days, above 30"),
    (described(), False, "plaintext"),
])  # fmt: skip
def test_a_namespace_temporal_doesnt_show_within_the_rules_is_refused_before_the_api(
    pg_url, monkeypatch, tmp_path, answer: DescribeNamespaceResponse, tls: bool, why: str
) -> None:  # type: ignore[no-untyped-def]
    proof = tmp_path / "proof.jsonl"
    proof.write_bytes(lines(*PASSED))
    asked = _deployment(monkeypatch, pg_url, answer, tls=tls)
    done = _invoke(proof)
    assert done.exit_code == 1 and why in done.output, done.output
    assert asked.api == []


async def test_the_api_call_signs_in_and_records_it_as_the_admin(client, owner_sessionmaker,
                                                                 development_deployment) -> None:  # fmt: skip
    from urllib.parse import parse_qs, urlparse

    import pyotp
    from sqlalchemy import text

    from dewpoint.core.auth.users import create_user

    async with owner_sessionmaker() as s, s.begin():
        user = await create_user(s, email="ops@corp.test", password=PW)
        await s.execute(text("update users set is_platform_admin = true where id = :u"), {"u": user.id})
    csrf = (await client.post("/api/v1/auth/login", json={"email": "ops@corp.test", "password": PW})).json()[
        "csrf_token"
    ]
    uri = (await client.post("/api/v1/auth/mfa/totp/enroll", headers={"X-CSRF-Token": csrf})).json()["otpauth_uri"]
    totp = pyotp.TOTP(parse_qs(urlparse(uri).query)["secret"][0])
    await client.post("/api/v1/auth/mfa/totp/confirm", json={"code": totp.now()}, headers={"X-CSRF-Token": csrf})
    client.cookies.clear()
    evidence = {"name": "d12-local", "namespace": "default", "namespace_id": NAMESPACE_ID, "server_build": BUILD,
                "proof_digest": "sha256:" + "cd" * 32, "attestation": SAID}  # fmt: skip
    shown = await cli.boundary_via_api(client, email="ops@corp.test", password=PW, code=totp.at(time.time() + 30),
                                       evidence=evidence)  # fmt: skip
    assert shown["name"] == "d12-local" and shown["recorded_by"] == str(user.id)
    async with owner_sessionmaker() as s:
        found = await s.execute(text("select actor_id, details from audit_log "
                                     "where action = 'platform.namespace_boundary.record'"))  # fmt: skip
        assert [(actor, json.loads(json.dumps(details))) for actor, details in found] == [(user.id, evidence)]
