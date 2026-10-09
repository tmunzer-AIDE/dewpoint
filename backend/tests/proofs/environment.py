# SPDX-License-Identifier: Apache-2.0
"""The disposable proof environment's run directory and its Compose project (2b-4b M4; deploy/temporal/compose.yaml).

`prepare` makes the run directory, 0700, before anything starts:

- `tls/`: what the server mounts: the frontend's certificate and key, the test CA's certificate, the internode CA's
  certificate and the internode certificate and key. No CA key and no client certificate is ever here.
- `authz/`: the authorizer's roles file and its fault directory (empty: no injection); its S3 credentials are written
  here once MinIO is up (`write_credentials`).
- `jwks/`: the key set the JWKS server publishes.
- `db_password`, `minio/root_user`, `minio/root_password`: random, each read by its own container only.
- `pki/`: the CAs' keys, the clients' certificates and keys, and another CA (D12.5's wrong one); never mounted.

Files are world-readable inside the 0700 directory, so each container's non-root user can read its bind mounts.
`policy` gives each S3 credential set its session policy: the anchor writer and the authorizer may only put under
their own prefixes; the verifier may only read. MinIO's root credentials stay with the harness."""

import json
import os
import secrets
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import boto3

from tests.proofs import pki, tokens

REPO = Path(__file__).resolve().parents[3]
COMPOSE = REPO / "deploy" / "temporal" / "compose.yaml"
PROJECT = "dewpoint-m4"
MTLS, JWT = "mtls", "jwt"  # configuration A (mutual TLS only) and B (a JWT bearer token only)
NAMESPACE = "default"  # Dewpoint's namespace on the proof server: the one its tests' recorded deployment names
SERVER_NAME = "temporal.dewpoint-m4.test"
INTERNODE_NAME = "internode.dewpoint-m4.test"
CLIENTS = {"proof-admin": ["system:admin"], "dewpoint-proof": [f"{NAMESPACE}:write"]}


@dataclass(frozen=True)
class Run:
    root: Path
    ca: pki.Authority  # the frontend's server certificate and every client certificate
    internode: pki.Authority
    other: pki.Authority  # a CA the server doesn't trust (D12.5)
    keys: tokens.KeySet

    def client(self, name: str) -> tuple[Path, Path]:
        return self.root / "pki" / f"{name}.pem", self.root / "pki" / f"{name}-key.pem"


def _write(path: Path, data: bytes | str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data.encode() if isinstance(data, str) else data)
    path.chmod(0o644)


def prepare(root: Path) -> Run:
    root.mkdir(parents=True)
    root.chmod(0o700)
    run = Run(
        root,
        pki.Authority.create("dewpoint-m4 test CA"),
        pki.Authority.create("dewpoint-m4 internode CA"),
        pki.Authority.create("another CA"),
        tokens.KeySet.create("proof-1"),
    )
    frontend = run.ca.issue(SERVER_NAME, server=True, names=[SERVER_NAME, "localhost"], ips=["127.0.0.1"])
    # internode: one certificate serves and dials (Temporal presents the internode server certificate as a client)
    internode = run.internode.issue(INTERNODE_NAME, server=True, names=[INTERNODE_NAME, "localhost"], ips=["127.0.0.1"])
    for name, data in {
        "ca.pem": run.ca.cert_pem(),
        "frontend.pem": frontend.cert_pem(),
        "frontend-key.pem": frontend.key_pem(),
        "internode-ca.pem": run.internode.cert_pem(),
        "internode.pem": internode.cert_pem(),
        "internode-key.pem": internode.key_pem(),
    }.items():
        _write(root / "tls" / name, data)
    _write(root / "authz" / "roles.json", json.dumps(CLIENTS, indent=2))
    (root / "authz" / "faults").mkdir()
    _write(root / "jwks" / "jwks.json", json.dumps(run.keys.jwks()))
    for secret in ("db_password", "minio/root_user", "minio/root_password"):
        _write(root / secret, secrets.token_urlsafe(24))
    for name, authority in {"ca": run.ca, "internode-ca": run.internode, "other-ca": run.other}.items():
        _write(root / "pki" / f"{name}.pem", authority.cert_pem())
        _write(root / "pki" / f"{name}-key.pem", authority.key_pem())
    for name in CLIENTS:
        issued = run.ca.issue(name, server=False)
        cert, key = run.client(name)
        _write(cert, issued.cert_pem())
        _write(key, issued.key_pem())
    return run


def compose(run: Run, config: str, *args: str) -> tuple[list[str], dict[str, str]]:
    """The Compose command for this run, and its environment: the database password goes in the environment
    (Temporal's configuration template reads only that), never in the arguments a process listing shows."""
    env = {
        **os.environ,
        "DEWPOINT_M4_RUN": str(run.root),
        "DEWPOINT_M4_CONFIG": config,
        "DEWPOINT_M4_DB_PASSWORD": (run.root / "db_password").read_text(),
    }
    return ["docker", "compose", "-p", PROJECT, "-f", str(COMPOSE), *args], env


def policy(kind: str, bucket: str, prefix: str) -> dict[str, Any]:
    """The session policy of one credential set: `anchor-writer`, `authorizer` or `verifier`."""
    objects = f"arn:aws:s3:::{bucket}/{prefix}"
    statements = {
        "anchor-writer": [{"Action": ["s3:PutObject"], "Resource": [f"{objects}anchors/*"]}],
        "authorizer": [{"Action": ["s3:PutObject"], "Resource": [f"{objects}temporal-authorizer/*"]}],
        "verifier": [
            {
                "Action": ["s3:ListBucket", "s3:ListBucketVersions", "s3:GetBucketObjectLockConfiguration"],
                "Resource": [f"arn:aws:s3:::{bucket}"],
            },
            {"Action": ["s3:GetObject", "s3:GetObjectVersion", "s3:GetObjectRetention"], "Resource": [f"{objects}*"]},
        ],
    }[kind]
    return {"Version": "2012-10-17", "Statement": [{"Effect": "Allow", **s} for s in statements]}


def write_credentials(path: Path, credentials: dict[str, str]) -> None:
    """An AWS shared credentials file (the authorizer's), from STS's answer."""
    _write(
        path,
        "[default]\n"
        f"aws_access_key_id = {credentials['AccessKeyId']}\n"
        f"aws_secret_access_key = {credentials['SecretAccessKey']}\n"
        f"aws_session_token = {credentials['SessionToken']}\n",
    )


# ---- running it (the proofs only; never the normal suite) ----

S3_ENDPOINT = f"http://127.0.0.1:{os.environ.get('DEWPOINT_M4_S3_PORT', '19000')}"
REGION = "us-east-1"
BUCKET = "dewpoint-audit"  # compose.yaml's DEWPOINT_AUTHZ_AUDIT_BUCKET: anchors and the authorizer's records
RETENTION_DAYS = 435  # audit retention 400 + backups 35: D6.9's default
STS_ROLE = "arn:minio:iam:::role/dewpoint-proof"  # MinIO ignores the role for its own users; boto3 requires one


def run_compose(run: Run, config: str, *args: str, timeout: float = 300) -> str:
    argv, env = compose(run, config, *args)
    done = subprocess.run(argv, env=env, capture_output=True, text=True, timeout=timeout, check=False)
    if done.returncode != 0:
        # Compose's own message, not the environment: it holds the run's password
        raise RuntimeError(f"docker compose {args[0]} failed ({done.returncode}): {done.stderr[-2000:]}")
    return done.stdout


def s3(credentials: dict[str, str] | None = None, *, root: Run | None = None) -> Any:
    """An S3 client on the proof's MinIO: with STS credentials, or with the root ones (`root`)."""
    if root is not None:
        access = (root.root / "minio" / "root_user").read_text()
        secret = (root.root / "minio" / "root_password").read_text()
        token = None
    else:
        assert credentials is not None
        access, secret = credentials["AccessKeyId"], credentials["SecretAccessKey"]
        token = credentials["SessionToken"]
    return boto3.client(
        "s3",
        endpoint_url=S3_ENDPOINT,
        region_name=REGION,
        aws_access_key_id=access,
        aws_secret_access_key=secret,
        aws_session_token=token,
    )


def assume(run: Run, kind: str, bucket: str, prefix: str, seconds: int = 3600) -> dict[str, str]:
    """One credential set: STS AssumeRole from the root credentials, narrowed by `kind`'s session policy. Whether
    MinIO grants that to its root user is the run's first check; if it refuses, the proof stops (a credential decision
    for the owner)."""
    sts = boto3.client(
        "sts",
        endpoint_url=S3_ENDPOINT,
        region_name=REGION,
        aws_access_key_id=(run.root / "minio" / "root_user").read_text(),
        aws_secret_access_key=(run.root / "minio" / "root_password").read_text(),
    )
    answer = sts.assume_role(
        RoleArn=STS_ROLE,
        RoleSessionName=f"dewpoint-{kind}",
        Policy=json.dumps(policy(kind, bucket, prefix)),
        DurationSeconds=seconds,
    )
    return dict(answer["Credentials"])


def make_bucket(client: Any, bucket: str, *, days: int | None = RETENTION_DAYS) -> None:
    """A bucket with Object Lock; a compliance-mode default retention of `days`, or none (D6.8's fixture)."""
    client.create_bucket(Bucket=bucket, ObjectLockEnabledForBucket=True)
    if days is not None:
        client.put_object_lock_configuration(
            Bucket=bucket,
            ObjectLockConfiguration={
                "ObjectLockEnabled": "Enabled",
                "Rule": {"DefaultRetention": {"Mode": "COMPLIANCE", "Days": days}},
            },
        )


def wait_for_s3(run: Run, deadline_s: float = 60) -> None:
    until = time.monotonic() + deadline_s
    while True:
        try:
            s3(root=run).list_buckets()
            return
        except Exception as e:  # noqa: BLE001 - not up yet: connection refused, then MinIO's own warm-up errors
            if time.monotonic() > until:
                raise RuntimeError(f"MinIO didn't answer within {deadline_s} s ({type(e).__name__})") from None
            time.sleep(1)
