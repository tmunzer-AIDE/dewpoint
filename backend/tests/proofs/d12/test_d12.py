# SPDX-License-Identifier: Apache-2.0
"""D12's proof (2b-4b M4): the production-like Temporal target, D12.1-D12.11 as the owner approved them (2026-10-05)
plus Dewpoint's own cases DW.1-DW.4, each automated. Opt-in: runs only when the owner authorizes it
(`DEWPOINT_PROOF=d12`), after the server's and the proof client's images are built (the run request's build step):

    docker build --network none --build-context gomod=<verified module cache> --build-arg GOPROXY=off \\
        -t dewpoint-m4/temporal-server:local deploy/temporal
    docker build ... --target proofclient -t dewpoint-m4/proofclient:local deploy/temporal
    DEWPOINT_PROOF=d12 DEWPOINT_PROOF_OUT=<file> .venv/bin/pytest -p no:cacheprovider -n 0 tests/proofs/d12

Every case runs against configuration A (mutual TLS only), then B (a JWT bearer token only), each a fresh Compose
project (deploy/temporal/compose.yaml) with its own run directory: the pinned PostgreSQL with the pinned admin-tools'
schema, the server, the pinned MinIO holding D6's bucket (the authorizer's audit trail), and the JWKS server. Clients:
the Python SDK and the HTTP API from here; the `temporal` CLI from the pinned admin-tools image; and the proof client
(deploy/temporal/cmd/proofclient) for every refused RPC, AdminService's included, and for the internal frontend, which
it reaches from inside the server's network namespace with the internode certificate.

D12.9-D12.11 and DW.2 run Dewpoint's own contract tests and probe on this server (`probe_temporal`). D12.11, as the
owner ruled on the run request: the 2026-10-05 wording ("a token taken from a deleted schedule never matches a
recreated one") doesn't hold, since Temporal restarts a recreated schedule's token at 1. That observation is pinned as
a premise and doesn't count as D12.11; D12.11 passes on Dewpoint's incarnation fencing keeping the stale unpause off a
late create.

Passing doesn't prove the owner's deployment: real-target qualification reruns it there, mutating cases in an isolated
test namespace and D12.4 through the namespace-scoped fault file, never the shared bucket."""

import asyncio
import http.client
import json
import os
import ssl
import subprocess
import sys
import time
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from google.protobuf.duration_pb2 import Duration
from temporalio.api.enums.v1 import ArchivalState
from temporalio.api.namespace.v1 import NamespaceConfig, UpdateNamespaceInfo
from temporalio.api.workflowservice.v1 import (
    DescribeNamespaceRequest,
    GetSystemInfoRequest,
    RegisterNamespaceRequest,
    UpdateNamespaceRequest,
)
from temporalio.client import Client
from temporalio.service import RPCError, RPCStatusCode, TLSConfig
from temporalio.testing import WorkflowEnvironment
from typer.testing import CliRunner

from dewpoint.apps.cli.main import app
from dewpoint.core import temporal_connect
from tests.apps.cli.test_keys import _env, _recorded
from tests.proofs import environment, tokens
from tests.proofs.conftest import gate, record
from tests.support.temporal import _External, start_local

pytestmark = [gate("d12")]

SERVER_IMAGE = os.environ.get("DEWPOINT_M4_IMAGE", "dewpoint-m4/temporal-server:local")
PROOF_CLIENT = "dewpoint-m4/proofclient:local"
ADMIN_TOOLS = "temporalio/admin-tools:1.32.0@sha256:a9f84fb9a374b2374fe2e67c8efc0468ff3f1c66c8a0b14597ec86e349e62bca"
GRPC = f"127.0.0.1:{os.environ.get('DEWPOINT_M4_GRPC_PORT', '17233')}"
HTTP_PORT = int(os.environ.get("DEWPOINT_M4_HTTP_PORT", "17243"))
NETWORK, CONTAINER = f"{environment.PROJECT}_default", f"{environment.PROJECT}-temporal-1"
AUDIENCE, DAY = "dewpoint-temporal", 86400
NAMESPACE = environment.NAMESPACE
BACKEND = Path(__file__).resolve().parents[3]
REFUSED = {  # D12.1's refused class: the table (deploy/temporal/internal/policy/classes.go)
    "/temporal.api.workflowservice.v1.WorkflowService/" + m for m in
    ("DeprecateNamespace", "CreateWorkflowRule", "DeleteWorkflowRule")
} | {"/temporal.api.operatorservice.v1.OperatorService/" + m for m in
     ("AddSearchAttributes", "RemoveSearchAttributes", "DeleteNamespace", "AddOrUpdateRemoteCluster",
      "RemoveRemoteCluster", "CreateNexusEndpoint", "UpdateNexusEndpoint", "DeleteNexusEndpoint")
} | {"/temporal.server.api.adminservice.v1.AdminService/" + m for m in
     ("AddSearchAttributes", "RemoveSearchAttributes", "AddOrUpdateRemoteCluster", "RemoveRemoteCluster")}  # fmt: skip


@dataclass
class Server:
    run: environment.Run
    config: str  # mtls (configuration A) or jwt (B)
    verifier: dict[str, str] = field(default_factory=dict)
    authorizer: dict[str, str] = field(default_factory=dict)
    anchor_writer: dict[str, str] = field(default_factory=dict)

    def token(self, who: str = "proof-admin", *, lifetime: int = 3600, **claims: Any) -> str:
        return self.run.keys.sign({"sub": who, "permissions": environment.CLIENTS[who], "aud": AUDIENCE, **claims},
                                  lifetime=lifetime)  # fmt: skip

    def token_file(self, who: str, token: str | None = None) -> Path:
        path = self.run.root / "pki" / "tokens" / who
        path.parent.mkdir(exist_ok=True)
        path.write_text(token or self.token(who))
        path.chmod(0o644)
        return path

    def compose(self, *args: str) -> str:
        return environment.run_compose(self.run, self.config, *args)


def _need_images() -> None:
    for image in (SERVER_IMAGE, PROOF_CLIENT, ADMIN_TOOLS):
        found = subprocess.run(["docker", "image", "inspect", image], capture_output=True, check=False)
        if found.returncode != 0:
            pytest.fail(f"{image} isn't on this machine: the run request's build (or pin) step comes first")


async def connect(server: Server, who: str = "proof-admin", *, ca: Path | None = None, cert: bool = True,
                  token: str | None = "", namespace: str = NAMESPACE) -> Client:  # fmt: skip
    """The SDK as `who`: configuration A's client certificate (unless `cert` is False), or B's token (`token`: "" for
    a fresh valid one, None for none)."""
    ca_pem = (ca or server.run.root / "pki" / "ca.pem").read_bytes()
    kwargs: dict[str, Any] = {}
    if server.config == environment.MTLS and cert:
        cert_path, key_path = server.run.client(who)
        tls = TLSConfig(server_root_ca_cert=ca_pem, domain=environment.SERVER_NAME,
                        client_cert=cert_path.read_bytes(), client_private_key=key_path.read_bytes())  # fmt: skip
    else:
        tls = TLSConfig(server_root_ca_cert=ca_pem, domain=environment.SERVER_NAME)
    if server.config == environment.JWT and token is not None:
        kwargs["api_key"] = token or server.token(who)
    return await Client.connect(GRPC, namespace=namespace, tls=tls, **kwargs)


def _retention(days: int) -> Duration:
    return Duration(seconds=days * DAY)


async def _register(client: Client, namespace: str, days: int) -> None:
    await client.workflow_service.register_namespace(
        RegisterNamespaceRequest(namespace=namespace, workflow_execution_retention_period=_retention(days))
    )


async def _update(client: Client, namespace: str, **config: Any) -> None:
    await client.workflow_service.update_namespace(
        UpdateNamespaceRequest(namespace=namespace, config=NamespaceConfig(**config))
    )


async def _refused(call: Any) -> bool:
    try:
        await call
    except RPCError as e:
        if e.status == RPCStatusCode.PERMISSION_DENIED:
            return True
        raise
    return False


def _decisions(server: Server, namespace: str) -> list[dict[str, Any]]:
    """The authorizer's records for `namespace`, read back with the verifier's credentials."""
    client, found = environment.s3(server.verifier), []
    pages = client.get_paginator("list_objects_v2").paginate(Bucket=environment.BUCKET,
                                                              Prefix="dewpoint/temporal-authorizer/")  # fmt: skip
    for page in pages:
        for item in page.get("Contents", []):
            entry = json.loads(client.get_object(Bucket=environment.BUCKET, Key=item["Key"])["Body"].read())
            if entry["namespace"] == namespace:
                found.append(entry)
    return sorted(found, key=lambda e: e["id"])


def _outcomes(server: Server, namespace: str) -> list[tuple[str, bool]]:
    return [(d["api"].rsplit("/", 1)[1], d["allowed"]) for d in _decisions(server, namespace)]


@pytest.fixture(scope="module", params=[environment.MTLS, environment.JWT])
def server(request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory) -> Iterator[Server]:
    _need_images()
    config = request.param
    run = environment.prepare(tmp_path_factory.mktemp(f"d12-{config}") / "run")
    server = Server(run, config)
    server.compose("up", "-d", "minio")
    try:
        environment.wait_for_s3(run)
        environment.make_bucket(environment.s3(root=run), environment.BUCKET)
        server.authorizer = environment.assume(run, "authorizer", environment.BUCKET, "dewpoint/", seconds=4 * 3600)
        server.verifier = environment.assume(run, "verifier", environment.BUCKET, "", seconds=4 * 3600)
        server.anchor_writer = environment.assume(run, "anchor-writer", environment.BUCKET, "*/", seconds=4 * 3600)
        environment.write_credentials(run.root / "authz" / "credentials", server.authorizer)
        server.compose("up", "-d")
        _wait_for_frontend(server)
        asyncio.run(_register_proof_namespace(server))
        yield server
    finally:
        logs = subprocess.run(["docker", "logs", "--tail", "200", CONTAINER], capture_output=True, text=True,
                              check=False)  # fmt: skip
        (run.root.parent / "temporal.log").write_text(logs.stdout + logs.stderr)
        server.compose("down", "-v", "--remove-orphans")


def _wait_for_frontend(server: Server, deadline_s: float = 180) -> None:
    until = time.monotonic() + deadline_s
    while True:
        try:
            asyncio.run(_system_info(server))
            return
        except Exception as e:  # noqa: BLE001 - not up yet
            if time.monotonic() > until:
                pytest.fail(f"the frontend didn't answer within {deadline_s} s ({type(e).__name__}); see temporal.log")
            time.sleep(2)


async def _system_info(server: Server) -> None:
    client = await connect(server)
    await client.workflow_service.get_system_info(GetSystemInfoRequest())


async def _register_proof_namespace(server: Server) -> None:
    await _register(await connect(server), NAMESPACE, 30)
    for _ in range(30):  # the frontend's namespace cache
        try:
            await (await connect(server)).workflow_service.describe_namespace(
                DescribeNamespaceRequest(namespace=NAMESPACE)
            )
            return
        except RPCError:
            await asyncio.sleep(1)


def _fresh(prefix: str) -> str:
    return f"d12-{prefix}-{uuid.uuid4().hex[:8]}"


# ---- D12.1 ----------------------------------------------------------------------------------------------------------


def test_d12_1_the_inventory_classes_every_rpc_and_lists_every_endpoint(server: Server) -> None:
    config = environment.COMPOSE.parent / "config" / f"{server.config}.yaml"
    done = subprocess.run(["docker", "run", "--rm", "-e", "DEWPOINT_TEMPORAL_CONFIG=/etc/temporal/config.yaml",
                           "-v", f"{config}:/etc/temporal/config.yaml:ro", SERVER_IMAGE, "inventory"],
                          capture_output=True, text=True, check=True)  # fmt: skip
    inventory = json.loads(done.stdout)
    record({"environment": f"d12-{server.config}", "inventory": inventory})
    classes = {rpc["api"]: rpc["class"] for rpc in inventory["rpcs"]}
    assert "unclassed" not in classes.values()
    assert {api for api, c in classes.items() if c == "refused"} == REFUSED
    assert {api for api, c in classes.items() if c == "inspected"} == {
        "/temporal.api.workflowservice.v1.WorkflowService/RegisterNamespace",
        "/temporal.api.workflowservice.v1.WorkflowService/UpdateNamespace",
    }
    listening = {(e["service"], e["kind"]): e for e in inventory["endpoints"]}
    assert (
        listening[("frontend", "grpc")]["address"] == "0.0.0.0:7233" and listening[("frontend", "grpc")]["authorized"]
    )
    assert listening[("frontend", "http")]["address"] == "0.0.0.0:7243"
    for service in ("internal-frontend", "history", "matching", "worker"):
        assert listening[(service, "grpc")]["address"].startswith("127.0.0.1:")
    assert listening[("internal-frontend", "grpc")]["authorized"]
    assert ("internal-frontend", "http") not in listening  # the review's I1: no credential-free HTTP API there
    assert inventory["server_version"].startswith("1.32.0")


def test_d12_1_only_the_frontend_listens_on_the_network(server: Server) -> None:
    """The internode services bind loopback: from the Compose network, only the frontend (and its membership port,
    which Temporal binds on the same address) answers."""
    reached = {}
    for port in (7233, 7243, 6933, 7234, 7235, 7236, 7246, 7239, 6934, 6935, 6936, 6939):
        done = subprocess.run(["docker", "run", "--rm", "--network", NETWORK, "--entrypoint", "python",
                               "python:3.12-slim-bookworm@sha256:"
                               "34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258", "-I", "-c",
                               f"import socket; socket.create_connection(('temporal', {port}), 3)"],
                              capture_output=True, check=False)  # fmt: skip
        reached[port] = done.returncode == 0
    record({"environment": f"d12-{server.config}", "reachable_on_the_network": reached})
    # the frontend's gRPC and HTTP API answer; no internode service or internal frontend does. The frontend's own
    # membership port (6933) is recorded either way: Temporal binds it with the frontend (the owner: it needs network
    # isolation before a production deployment qualifies)
    assert reached[7233] and reached[7243]
    assert not any(ok for port, ok in reached.items() if port not in (7233, 7243, 6933)), reached


# ---- D12.2 ----------------------------------------------------------------------------------------------------------


def test_d12_2_through_the_sdk(server: Server) -> None:
    namespace = _fresh("sdk")

    async def changes() -> None:
        admin = await connect(server)
        assert await _refused(_register(admin, namespace, 31))
        await _register(admin, namespace, 30)
        await asyncio.sleep(2)  # the namespace cache
        assert await _refused(_update(admin, namespace, workflow_execution_retention_ttl=_retention(31)))
        await _update(admin, namespace, workflow_execution_retention_ttl=_retention(30))
        assert await _refused(_update(admin, namespace, history_archival_state=ArchivalState.ARCHIVAL_STATE_ENABLED))
        assert await _refused(_update(admin, namespace,
                                      visibility_archival_state=ArchivalState.ARCHIVAL_STATE_ENABLED))  # fmt: skip
        # a description alone: checked against the stored configuration, read from the server's store
        await admin.workflow_service.update_namespace(UpdateNamespaceRequest(
            namespace=namespace, update_info=UpdateNamespaceInfo(description="d12")))  # fmt: skip

    asyncio.run(changes())
    assert _outcomes(server, namespace) == [("RegisterNamespace", False), ("RegisterNamespace", True),
                                            ("UpdateNamespace", False), ("UpdateNamespace", True),
                                            ("UpdateNamespace", False), ("UpdateNamespace", False),
                                            ("UpdateNamespace", True)]  # fmt: skip
    effective = _decisions(server, namespace)[-1]["effective"]
    assert (effective["retention_seconds"], effective["history_archival"]) == (30 * DAY, "disabled")


def _cli(server: Server, *args: str) -> subprocess.CompletedProcess[str]:
    """The `temporal` CLI from the pinned admin-tools image, as the proof's admin; B's token in the environment
    (TEMPORAL_API_KEY, named on the command line, its value never)."""
    pki = server.run.root / "pki"
    argv = ["docker", "run", "--rm", "--network", NETWORK, "-v", f"{pki / 'ca.pem'}:/pki/ca.pem:ro"]
    connection = ["--address", "temporal:7233", "--tls-ca-path", "/pki/ca.pem", "--tls-server-name",
                  environment.SERVER_NAME]  # fmt: skip
    env = dict(os.environ)
    if server.config == environment.MTLS:
        cert, key = server.run.client("proof-admin")
        argv += ["-v", f"{cert}:/pki/client.pem:ro", "-v", f"{key}:/pki/client-key.pem:ro"]
        connection += ["--tls-cert-path", "/pki/client.pem", "--tls-key-path", "/pki/client-key.pem"]
    else:
        env["TEMPORAL_API_KEY"] = server.token()
        argv += ["-e", "TEMPORAL_API_KEY"]
    return subprocess.run([*argv, "--entrypoint", "temporal", ADMIN_TOOLS, *args, *connection], env=env,
                          capture_output=True, text=True, check=False, timeout=120)  # fmt: skip


def test_d12_2_through_the_temporal_cli(server: Server) -> None:
    namespace = _fresh("cli")
    create = ["operator", "namespace", "create", "--namespace", namespace, "--retention"]
    update = ["operator", "namespace", "update", "--namespace", namespace, "--retention"]
    wide = _cli(server, *create, "744h")  # 31 days, in a unit every Go duration parser reads
    said = (wide.stderr + wide.stdout).lower()  # the CLI prints Temporal's message, its code name perhaps not
    assert wide.returncode != 0 and ("permissiondenied" in said or "unauthorized" in said), wide.stderr
    created = _cli(server, *create, "720h")
    assert created.returncode == 0, created.stderr
    time.sleep(2)
    assert _cli(server, *update, "744h").returncode != 0
    assert _cli(server, *update, "720h").returncode == 0
    assert _outcomes(server, namespace) == [("RegisterNamespace", False), ("RegisterNamespace", True),
                                            ("UpdateNamespace", False), ("UpdateNamespace", True)]  # fmt: skip


def _http(server: Server, method: str, path: str, body: dict[str, Any] | None = None, *, who: str = "proof-admin",
          token: str | None = "") -> tuple[int, str]:  # fmt: skip
    context = ssl.create_default_context(cafile=str(server.run.root / "pki" / "ca.pem"))
    headers = {"Content-Type": "application/json"}
    if server.config == environment.MTLS:
        cert, key = server.run.client(who)
        context.load_cert_chain(cert, key)
    elif token is not None:
        headers["Authorization"] = f"Bearer {token or server.token(who)}"
    connection = http.client.HTTPSConnection("127.0.0.1", HTTP_PORT, context=context, timeout=30)
    try:
        connection.request(method, path, json.dumps(body) if body is not None else None, headers)
        answer = connection.getresponse()
        return answer.status, answer.read().decode(errors="replace")
    finally:
        connection.close()


def test_d12_2_through_the_http_api(server: Server) -> None:
    namespace = _fresh("http")
    register = "/api/v1/namespaces"
    update = f"/api/v1/namespaces/{namespace}/update"
    assert (
        _http(server, "POST", register, {"namespace": namespace, "workflowExecutionRetentionPeriod": f"{31 * DAY}s"})[0]
        == 403
    )
    status, text = _http(
        server, "POST", register, {"namespace": namespace, "workflowExecutionRetentionPeriod": f"{30 * DAY}s"}
    )
    assert status == 200, text
    time.sleep(2)
    assert _http(server, "POST", update, {"config": {"workflowExecutionRetentionTtl": f"{31 * DAY}s"}})[0] == 403
    assert _http(server, "POST", update, {"config": {"workflowExecutionRetentionTtl": f"{30 * DAY}s"}})[0] == 200
    assert _outcomes(server, namespace) == [("RegisterNamespace", False), ("RegisterNamespace", True),
                                            ("UpdateNamespace", False), ("UpdateNamespace", True)]  # fmt: skip


# ---- D12.3 ----------------------------------------------------------------------------------------------------------


def _proof_client(server: Server, *args: str, internal: bool = False) -> list[dict[str, str]]:
    """The proof client: on the public frontend over the Compose network as the proof's admin, or (`internal`) on the
    internal frontend from inside the server's network namespace with the internode certificate."""
    tls, pki = server.run.root / "tls", server.run.root / "pki"
    if internal:
        argv = ["docker", "run", "--rm", "--network", f"container:{CONTAINER}",
                "-v", f"{tls / 'internode-ca.pem'}:/pki/ca.pem:ro", "-v", f"{tls / 'internode.pem'}:/pki/cert.pem:ro",
                "-v", f"{tls / 'internode-key.pem'}:/pki/key.pem:ro", PROOF_CLIENT, *args,
                "--address", "127.0.0.1:7236", "--ca", "/pki/ca.pem", "--server-name", environment.INTERNODE_NAME,
                "--cert", "/pki/cert.pem", "--key", "/pki/key.pem"]  # fmt: skip
    else:
        argv = ["docker", "run", "--rm", "--network", NETWORK, "-v", f"{pki / 'ca.pem'}:/pki/ca.pem:ro"]
        tail = ["--address", "temporal:7233", "--ca", "/pki/ca.pem", "--server-name", environment.SERVER_NAME]
        if server.config == environment.MTLS:
            cert, key = server.run.client("proof-admin")
            argv += ["-v", f"{cert}:/pki/cert.pem:ro", "-v", f"{key}:/pki/key.pem:ro"]
            tail += ["--cert", "/pki/cert.pem", "--key", "/pki/key.pem"]
        else:
            argv += ["-v", f"{server.token_file('proof-admin')}:/pki/token:ro"]
            tail += ["--token-file", "/pki/token"]
        argv += [PROOF_CLIENT, *args, *tail]
    done = subprocess.run(argv, capture_output=True, text=True, check=False, timeout=300)
    assert done.returncode == 0, done.stderr
    return [json.loads(line) for line in done.stdout.splitlines() if line.strip()]


def test_d12_3_every_refused_rpc_is_refused_and_audited_on_the_public_frontend(server: Server) -> None:
    answers = _proof_client(server, "sweep", "--class", "refused", "--namespace", NAMESPACE)
    record({"environment": f"d12-{server.config}", "sweep_public": answers})
    assert {a["api"] for a in answers} == REFUSED
    assert {a["code"] for a in answers} == {"PermissionDenied"}, answers
    audited = {d["api"] for d in _decisions(server, NAMESPACE) if not d["allowed"]}
    namespaced = {a for a in REFUSED if "RemoteCluster" not in a and "NexusEndpoint" not in a}
    assert namespaced <= audited


def test_d12_3_the_internal_frontend_runs_the_same_authorizer(server: Server) -> None:
    namespace = _fresh("internal")
    [wide] = _proof_client(server, "register", "--namespace", namespace, "--retention-days", "31", internal=True)
    [within] = _proof_client(server, "register", "--namespace", namespace, "--retention-days", "30", internal=True)
    assert (wide["code"], within["code"]) == ("PermissionDenied", "OK")
    time.sleep(2)
    answers = _proof_client(server, "sweep", "--class", "refused", "--namespace", namespace, internal=True)
    record({"environment": f"d12-{server.config}", "sweep_internal": answers})
    assert {a["code"] for a in answers} == {"PermissionDenied"}, answers
    temporal_internal = [d for d in _decisions(server, namespace) if d["auth_type"] == "temporal"]
    assert temporal_internal and all(d["subject"] for d in temporal_internal)


def test_d12_3_nexus_routes_are_closed(server: Server) -> None:
    """Nexus can't be turned off in v1.32.0. Of its three HTTP routes, only the dispatch by namespace and task queue
    reaches the authorizer, which refuses it (403), unaudited (the closed class). The dispatch by endpoint answers 404
    before authorizing (no endpoint can exist: creating one is refused), and the completion callback rejects a missing
    token before authorizing (no Nexus operation runs to mint one): each is recorded as unreachable, not as covered
    (the review's I2)."""
    before = len(_decisions(server, NAMESPACE))
    status, _ = _http(server, "POST", f"/namespaces/{NAMESPACE}/task-queues/q/nexus-services/s/o", {})
    record({"environment": f"d12-{server.config}", "nexus_route": "namespace and task queue", "status": status})
    assert status == 403
    assert len(_decisions(server, NAMESPACE)) == before  # closed: refused without an audit write
    for name, path, unreachable in (("endpoint", "/nexus/endpoints/e/services/s/o", 404),
                                    ("callback", f"/namespaces/{NAMESPACE}/nexus/callback", 400)):  # fmt: skip
        status, _ = _http(server, "POST", path, {})
        record({"environment": f"d12-{server.config}", "nexus_route": name, "status": status,
                "expected_from_the_source": unreachable, "reaches_the_authorizer": False})  # fmt: skip
        assert status >= 400, (name, status)  # refused before the authorizer: its exact code is recorded


# ---- D12.4 ----------------------------------------------------------------------------------------------------------


def _restart_server_with(server: Server, credentials: dict[str, str]) -> None:
    environment.write_credentials(server.run.root / "authz" / "credentials", credentials)
    server.compose("up", "-d", "--force-recreate", "temporal")
    _wait_for_frontend(server)


def test_d12_4_a_bucket_refusing_writes_refuses_every_change(server: Server) -> None:
    """The authorizer's writes answered 403 (the server restarted with the verifier's read-only credentials)."""
    namespace = _fresh("refusing")
    _restart_server_with(server, server.verifier)
    try:
        assert asyncio.run(_refused(_register_with(server, namespace, 30)))
    finally:
        _restart_server_with(server, server.authorizer)
    asyncio.run(_register_with(server, namespace, 30))


async def _register_with(server: Server, namespace: str, days: int) -> None:
    await _register(await connect(server), namespace, days)


def test_d12_4_an_unreachable_bucket_refuses_every_change(server: Server) -> None:
    namespace = _fresh("unreachable")
    server.compose("pause", "minio")  # paused, not stopped: its data is on tmpfs
    try:
        assert asyncio.run(_refused(_register_with(server, namespace, 30)))
    finally:
        server.compose("unpause", "minio")
    asyncio.run(_register_with(server, namespace, 30))


def test_d12_4_a_failure_injected_for_one_namespace_leaves_the_other_writers(server: Server) -> None:
    """Real-target qualification's form: the fault file names one namespace; its change is refused while another
    namespace's change is allowed and recorded and D6's anchor writer still writes."""
    failing, other = _fresh("faulted"), _fresh("unaffected")
    asyncio.run(_register_with(server, failing, 7))
    asyncio.run(_register_with(server, other, 7))
    time.sleep(2)
    faults = server.run.root / "authz" / "faults" / "namespaces"

    async def injected() -> None:
        admin = await connect(server)
        faults.write_text(failing + "\n")
        faults.chmod(0o644)
        try:
            assert await _refused(_update(admin, failing, workflow_execution_retention_ttl=_retention(30)))
            await _update(admin, other, workflow_execution_retention_ttl=_retention(30))
            environment.s3(server.anchor_writer).put_object(
                Bucket=environment.BUCKET, Key=f"d12/anchors/canary/{uuid.uuid4().hex}.json", Body=b"{}",
                IfNoneMatch="*")  # fmt: skip
        finally:
            faults.unlink()
        await _update(admin, failing, workflow_execution_retention_ttl=_retention(30))  # the injection ended

    asyncio.run(injected())
    assert ("UpdateNamespace", True) in _outcomes(server, other)
    # the refused change's own record couldn't be written: the failing namespace shows only the later, allowed one
    assert _outcomes(server, failing) == [("RegisterNamespace", True), ("UpdateNamespace", True)]


# ---- D12.5-D12.8 ----------------------------------------------------------------------------------------------------


def test_d12_5_the_servers_certificate_is_verified(server: Server) -> None:
    asyncio.run(_system_info(server))
    with pytest.raises(Exception):  # noqa: B017, PT011 - the SDK's connection failure, whatever its type
        asyncio.run(connect(server, ca=server.run.root / "pki" / "other-ca.pem"))


def test_d12_6_mutual_tls_only(server: Server) -> None:
    if server.config != environment.MTLS:
        pytest.skip("configuration A")
    with pytest.raises(Exception):  # noqa: B017, PT011 - the handshake fails without a certificate
        asyncio.run(_describe(server, cert=False))
    asyncio.run(_describe(server))


async def _describe(server: Server, **how: Any) -> Any:
    client = await connect(server, "dewpoint-proof", **how)
    return await client.workflow_service.describe_namespace(DescribeNamespaceRequest(namespace=NAMESPACE))


def test_d12_7_a_bearer_token_only(server: Server) -> None:
    if server.config != environment.JWT:
        pytest.skip("configuration B")
    asyncio.run(_describe(server))
    other_keys = tokens.KeySet.create(server.run.keys.kid)
    for name, token in {
        "expired": server.token("dewpoint-proof", lifetime=-60),
        "wrongly signed": other_keys.sign({"sub": "dewpoint-proof", "permissions": [f"{NAMESPACE}:write"],
                                           "aud": AUDIENCE}, lifetime=600),
        "another audience": server.token("dewpoint-proof", aud="someone-else"),
        "missing": None,
    }.items():  # fmt: skip
        try:
            asyncio.run(_describe(server, token=token))
        except RPCError as e:
            assert e.status in (RPCStatusCode.PERMISSION_DENIED, RPCStatusCode.UNAUTHENTICATED), (name, e.status)
        except RuntimeError as e:  # refused while connecting: the SDK's connect sends the token too
            assert any(w in str(e) for w in ("PermissionDenied", "unauthorized", "Unauthenticated")), (name, str(e))
        else:
            raise AssertionError(f"a {name} token was accepted")


def test_d12_8_describe_namespace_reports_retention_and_archival(server: Server) -> None:
    answer = asyncio.run(_describe(server))
    config = answer.config
    assert config.workflow_execution_retention_ttl.seconds == 30 * DAY
    assert config.history_archival_state == ArchivalState.ARCHIVAL_STATE_DISABLED
    assert config.visibility_archival_state == ArchivalState.ARCHIVAL_STATE_DISABLED


# ---- D12.9-D12.11, DW.2: Dewpoint's own tests on this server -------------------------------------------------------


def _dewpoint_settings(server: Server) -> dict[str, str]:
    """§10.4's settings for Dewpoint's processes on this server, as the dewpoint-proof identity."""
    env = {"DEWPOINT_TEMPORAL_TLS_CA": str(server.run.root / "pki" / "ca.pem"),
           "DEWPOINT_TEMPORAL_TLS_SERVER_NAME": environment.SERVER_NAME}  # fmt: skip
    if server.config == environment.MTLS:
        cert, key = server.run.client("dewpoint-proof")
        env |= {"DEWPOINT_TEMPORAL_TLS_CERT": str(cert), "DEWPOINT_TEMPORAL_TLS_KEY": str(key)}
    else:
        env["DEWPOINT_TEMPORAL_BEARER_TOKEN_FILE"] = str(server.token_file("dewpoint-proof"))
    return env


def _pytest_on_this_server(server: Server, *selection: str, probe: bool = False) -> None:
    env = {**os.environ, **_dewpoint_settings(server), "DEWPOINT_PROBE_TEMPORAL_ADDRESS": GRPC,
           "DEWPOINT_PROBE_TEMPORAL_NAMESPACE": NAMESPACE}  # fmt: skip
    env.pop("DEWPOINT_TEMPORAL_INSECURE_DEV", None)
    env.pop("DEWPOINT_PROOF", None)
    if probe:
        env["DEWPOINT_PROBE"] = "1"
    done = subprocess.run([sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-n", "0", "-q", *selection],
                          cwd=BACKEND, env=env, capture_output=True, text=True, check=False, timeout=1800)  # fmt: skip
    record({"environment": f"d12-{server.config}", "selection": selection, "exit": done.returncode,
            "tail": done.stdout[-3000:]})  # fmt: skip
    assert done.returncode == 0, done.stdout[-3000:]


ERASURE = "tests/apps/worker/test_temporal_erasure_contract.py"
CONTRACT = "tests/apps/worker/test_temporal_contract.py"


def test_d12_9_and_10_deletion_reads_back_not_found_and_the_prefix_query_finds_a_tenant(server: Server) -> None:
    _pytest_on_this_server(server, f"{ERASURE}::test_a_deleted_execution_running_or_closed_reads_back_not_found_and"
                                   "_visibility_finds_a_tenants_by_prefix")  # fmt: skip


def test_d12_11_a_paused_schedule_fires_nothing_and_a_stale_update_is_discarded(server: Server) -> None:
    _pytest_on_this_server(
        server,
        f"{ERASURE}::test_a_paused_schedules_due_firings_are_neither_caught_up_nor_counted_but_matching_times_count_them",
        f"{CONTRACT}::test_a_stale_schedule_update_is_discarded_and_the_describe_after_it_shows_it",
    )


def test_d12_11_premise_temporal_restarts_a_recreated_schedules_token(server: Server) -> None:
    """Observed, not D12.11: a deleted and recreated schedule's conflict token restarts at 1, so a token taken before
    the deletion matches the recreated one and a stale unpause lands on it. Pinned on this server as the premise the
    incarnation fencing answers; it proves no protection by itself."""
    _pytest_on_this_server(
        server, f"{ERASURE}::test_a_deleted_and_recreated_schedule_restarts_its_token_so_a_stale_unpause_lands_on_it"
    )


def test_d12_11_incarnation_fencing_keeps_a_stale_unpause_off_a_late_create(server: Server) -> None:
    """D12.11 as the owner ruled: with an incarnation per create, recorded before the call, the late create lands
    under an id no describe showed, the stale unpause targets another, the late one stays paused, and the erasure,
    covering every incarnation, deletes it (tests/apps/erasure/test_incarnations.py, on this server)."""
    _pytest_on_this_server(server, "tests/apps/erasure/test_incarnations.py")


def test_dw_2_dewpoints_runs_start_and_complete_here(server: Server) -> None:
    """Dewpoint's run workflow on its worker (the real-server contract tests), then the dispatcher's ingress probe at
    its first case: a backlog matched, its runs started and ended."""
    _pytest_on_this_server(server, "tests/apps/worker/test_real_server.py", "-k", "terminated")
    cases = subprocess.run([sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "--collect-only", "-q",
                            "tests/probes/test_ingress_starts.py"], cwd=BACKEND, capture_output=True, text=True,
                           env={**os.environ, "DEWPOINT_PROBE": "1"}, check=True)  # fmt: skip
    first = next(line for line in cases.stdout.splitlines() if "::" in line)
    _pytest_on_this_server(server, first, probe=True)


# ---- DW.1, DW.3, DW.4 -----------------------------------------------------------------------------------------------


def test_dw_1_plaintext_is_refused_outside_development_and_isnt_served(server: Server) -> None:
    settings = temporal_connect.TemporalConnection(temporal_insecure_dev=True)
    with pytest.raises(temporal_connect.TemporalConfigError):
        temporal_connect.options(settings, "production")
    with pytest.raises(Exception):  # noqa: B017, PT011 - plaintext against the TLS frontend fails
        asyncio.run(Client.connect(GRPC, namespace=NAMESPACE, tls=False))


def test_dw_3_a_replaced_token_is_picked_up_without_a_restart(server: Server) -> None:
    if server.config != environment.JWT:
        pytest.skip("configuration B")

    async def scenario() -> None:
        path = server.token_file("dewpoint-proof", server.token("dewpoint-proof", lifetime=15))
        settings = _External(
            temporal_address=GRPC, temporal_namespace=NAMESPACE, temporal_bearer_token_file=str(path),
            temporal_tls_ca=str(server.run.root / "pki" / "ca.pem"),
            temporal_tls_server_name=environment.SERVER_NAME)  # fmt: skip
        client = await temporal_connect.connect(settings, "production")
        request = DescribeNamespaceRequest(namespace=NAMESPACE)
        await client.workflow_service.describe_namespace(request)
        await asyncio.sleep(35)  # the token has expired, with room for Docker's clock lagging the host's
        with pytest.raises(RPCError):
            await client.workflow_service.describe_namespace(request)
        path.write_text(server.token("dewpoint-proof"))
        assert await temporal_connect.refresh_token(client, str(path))  # what keep_token_fresh does every minute
        await client.workflow_service.describe_namespace(request)  # the same client: no reconnect

    asyncio.run(scenario())


def test_dw_4_the_check_passes_here(server: Server, pg_url, _test_users, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    import base64

    _env(monkeypatch, pg_url, DEWPOINT_KEK_B64=base64.b64encode(bytes(32)).decode())
    _recorded(pg_url, NAMESPACE)
    monkeypatch.delenv("DEWPOINT_TEMPORAL_INSECURE_DEV", raising=False)
    for name, value in {**_dewpoint_settings(server), "DEWPOINT_TEMPORAL_ADDRESS": GRPC,
                        "DEWPOINT_TEMPORAL_NAMESPACE": NAMESPACE}.items():  # fmt: skip
        monkeypatch.setenv(name, value)
    from dewpoint.core.config import get_settings

    get_settings.cache_clear()
    done = CliRunner().invoke(app, ["temporal", "check"])
    assert done.exit_code == 0, done.output


def test_dw_4_the_check_fails_on_a_wide_namespace_elsewhere(pg_url, _test_users, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """A namespace above 30 days, made on a separate dev server without the authorizer, never on the proof's own."""
    import base64

    async def wide() -> WorkflowEnvironment:
        local = await start_local(namespace="wide")
        await local.client.workflow_service.update_namespace(UpdateNamespaceRequest(
            namespace="wide", config=NamespaceConfig(workflow_execution_retention_ttl=_retention(31))))  # fmt: skip
        return local

    local = asyncio.run(wide())
    try:
        _env(monkeypatch, pg_url, DEWPOINT_KEK_B64=base64.b64encode(bytes(32)).decode())
        _recorded(pg_url, "wide")
        monkeypatch.setenv("DEWPOINT_TEMPORAL_ADDRESS", local.client.service_client.config.target_host)
        monkeypatch.setenv("DEWPOINT_TEMPORAL_NAMESPACE", "wide")
        from dewpoint.core.config import get_settings

        get_settings.cache_clear()
        done = CliRunner().invoke(app, ["temporal", "check"])
        assert done.exit_code == 1 and "retention of 31 days, above 30" in done.output, done.output
    finally:
        asyncio.run(local.shutdown())
