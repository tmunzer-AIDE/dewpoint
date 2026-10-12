# SPDX-License-Identifier: Apache-2.0
"""The disposable proof environment's run directory and its Compose project (2b-4b M4; deploy/temporal/compose.yaml).

`prepare` makes the run directory, 0700, before anything starts:

- `tls/`: what the server mounts: the frontend's certificate and key, the test CA's certificate, the internode CA's
  certificate and the internode certificate and key. No CA key and no client certificate is ever here.
- `authz/`: the authorizer's roles file and its fault directory (empty: no injection); its S3 credentials are written
  here once MinIO is up (`write_credentials`); with the start check on, its DSN (`start_check_dsn`): the project's own
  `dewpoint-db`, as `START_CHECK_LOGIN`.
- `jwks/`: the key set the JWKS server publishes.
- `db_password`, `dewpoint_db_password`, `minio/root_user`, `minio/root_password`: random, each read by its own
  container only; `start_check_password` (with the start check on): the harness's, to create the authorizer's login.
- `pki/`: the CAs' keys, the clients' certificates and keys, and another CA (D12.5's wrong one); never mounted.

Files are world-readable inside the 0700 directory, so each container's non-root user can read its bind mounts.
`policy` gives each S3 credential set its session policy: the anchor writer and the authorizer may only put under
their own prefixes; the verifier may only read. MinIO's root credentials stay with the harness."""

import hashlib
import json
import os
import re
import secrets
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import boto3

from tests.proofs import pki, tokens

REPO = Path(__file__).resolve().parents[3]
COMPOSE = REPO / "deploy" / "temporal" / "compose.yaml"
SERVER_CONTEXT = COMPOSE.parent  # the server image's build context: all of it (`COPY . .`, no .dockerignore)
# Its identity, as the Dockerfile's build stage computes it before anything else writes there and stamps it into the
# server binary (`-X main.source`), whose inventory reports it: every file's SHA-256 by path, in C order, hashed.
SOURCE_PIPELINE = "find . -type f -print0 | LC_ALL=C sort -z | xargs -0 sha256sum | sha256sum | cut -d' ' -f1"
PROJECT = "dewpoint-m4"  # each run's project is this and a random id of its own (revision 17.3.1)
START_CHECK_MODES = ("on", "off")  # D12's start check, as each run sets it: never left unset
START_CHECK_PROFILE = "start-check"  # compose.yaml's profile for Dewpoint's database, which only `on` needs
START_CHECK_LOGIN = "dewpoint_authz"  # the authorizer's login: a member of dewpoint_start_check, nothing else
DEWPOINT_DB = "dewpoint"  # dewpoint-db's superuser and its database (compose.yaml)
MTLS, JWT = "mtls", "jwt"  # configuration A (mutual TLS only) and B (a JWT bearer token only)
NAMESPACE = "default"  # Dewpoint's namespace on the proof server: the one its tests' recorded deployment names
SERVER_NAME = "temporal.dewpoint-m4.test"
INTERNODE_NAME = "internode.dewpoint-m4.test"
# Temporal's cluster scope is temporal-system (its JWT mapper's primitives.SystemLocalNamespace), not "system"
CLIENTS = {"proof-admin": ["temporal-system:admin"], "dewpoint-proof": [f"{NAMESPACE}:write"]}


@dataclass(frozen=True)
class Run:
    root: Path
    ca: pki.Authority  # the frontend's server certificate and every client certificate
    internode: pki.Authority
    other: pki.Authority  # a CA the server doesn't trust (D12.5)
    keys: tokens.KeySet
    project: str  # its own Compose project: `dewpoint-m4-<random>`, recorded, never another run's
    start_check: str  # D12's start check for this run's server: on or off, always explicit
    ports: dict[tuple[str, int], int] = field(default_factory=dict)  # the host ports Docker assigned, read back
    state: dict[str, Any] = field(default_factory=dict)  # whether its project was checked fresh; its last config

    def client(self, name: str) -> tuple[Path, Path]:
        return self.root / "pki" / f"{name}.pem", self.root / "pki" / f"{name}-key.pem"


def _write(path: Path, data: bytes | str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data.encode() if isinstance(data, str) else data)
    path.chmod(0o644)


def prepare(root: Path, *, start_check: str) -> Run:
    if start_check not in START_CHECK_MODES:
        raise ValueError("start_check is on or off: a run always names its server's start check")
    root.mkdir(parents=True)
    root.chmod(0o700)
    run = Run(
        root,
        pki.Authority.create("dewpoint-m4 test CA"),
        pki.Authority.create("dewpoint-m4 internode CA"),
        pki.Authority.create("another CA"),
        tokens.KeySet.create("proof-1"),
        f"{PROJECT}-{secrets.token_hex(6)}",
        start_check,
    )
    frontend = run.ca.issue(SERVER_NAME, server=True, names=[SERVER_NAME, "localhost"], ips=["127.0.0.1"])
    # internode: one certificate serves and dials (Temporal presents the internode server certificate as a client)
    internode = run.internode.issue(
        INTERNODE_NAME, server=True, client=True, names=[INTERNODE_NAME, "localhost"], ips=["127.0.0.1"]
    )
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
    for secret in ("db_password", "dewpoint_db_password", "minio/root_user", "minio/root_password"):
        _write(root / secret, secrets.token_urlsafe(24))
    if start_check == "on":  # the authorizer's DSN: the project's own database, through its network, never another
        password = secrets.token_urlsafe(24)
        _write(root / "start_check_password", password)  # the harness's, to create the login with: never mounted
        dsn = f"postgresql://{START_CHECK_LOGIN}:{password}@dewpoint-db:5432/{DEWPOINT_DB}?sslmode=disable"
        _write(root / "authz" / "start_check_dsn", dsn)
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
        "DEWPOINT_M4_START_CHECK": run.start_check,
        "COMPOSE_PROFILES": START_CHECK_PROFILE if run.start_check == "on" else "",  # its database, with the check only
    }
    return ["docker", "compose", "-p", run.project, "-f", str(COMPOSE), *args], env


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

REGION = "us-east-1"
BUCKET = "dewpoint-audit"  # compose.yaml's DEWPOINT_AUTHZ_AUDIT_BUCKET: anchors and the authorizer's records
RETENTION_DAYS = 435  # audit retention 400 + backups 35: D6.9's default, and each version's lock at least that
BUCKET_DAYS = RETENTION_DAYS + 1  # the bucket's default: a day more, as the verifier requires (timestamp precision)
STS_ROLE = "arn:minio:iam:::role/dewpoint-proof"  # MinIO ignores the role for its own users; boto3 requires one


def _docker(argv: list[str], env: dict[str, str] | None = None) -> str:
    done = subprocess.run(argv, env=env, capture_output=True, text=True, timeout=120, check=False)
    if done.returncode != 0:
        raise RuntimeError(f"docker {argv[1]} failed ({done.returncode})")  # its words can carry the run's names
    return done.stdout


DOCKER: Callable[..., str] = _docker  # the tests' fake replaces it


def _processes() -> list[str]:
    """Every process's command line on this host: where a compose client of a project shows (`-p <project>`)."""
    return subprocess.run(["ps", "-A", "-o", "args="], capture_output=True, text=True, timeout=30,
                          check=True).stdout.splitlines()  # fmt: skip


PROCESSES: Callable[[], list[str]] = _processes  # the tests' fake replaces it
SLEEP: Callable[[float], None] = time.sleep  # and this
_LABEL = "com.docker.compose.project"
PROJECT_NAME = re.compile(rf"{PROJECT}-[0-9a-f]{{12}}")  # `prepare`'s: the only names `remove_project` acts on
REMOVE_PASSES, SETTLE_S = 6, 2.0  # a project's removal: listed again after each pass, until it's found quiet
# How long a project must stay empty, no compose client of it alive, before it's found quiet: longer than a create
# the daemon had already accepted from a killed compose usually takes to land (a local image's: well under a second).
# Best effort only: an interrupted create is told by the creates' record, never by this wait
QUIET_S = 10.0
_CHANGES_PORTS = {"up", "down", "start", "stop", "restart", "rm", "kill", "create"}  # a recreated service may move


def guard_fresh(run: Run) -> None:
    """Before the run's first `up`: its project has no container and no network. A random id makes any a collision,
    reported and never removed."""
    containers = DOCKER(["docker", "ps", "-a", "--filter", f"label={_LABEL}={run.project}", "-q"])
    networks = DOCKER(["docker", "network", "ls", "--filter", f"label={_LABEL}={run.project}", "-q"])
    if containers.strip() or networks.strip():
        raise RuntimeError(f"the project {run.project} already has containers or networks: a collision, not removed")


def guard_own(run: Run) -> None:
    """Before any cleanup: every container listed under the run's project carries exactly its recorded project name
    (Compose's own label; the file adds no run-id label of its own)."""
    labels = DOCKER(["docker", "ps", "-a", "--filter", f"label={_LABEL}={run.project}",
                     "--format", '{{.Label "' + _LABEL + '"}}'])  # fmt: skip
    for label in filter(None, (line.strip() for line in labels.splitlines())):
        if label != run.project:
            raise RuntimeError("a container listed under the run's project is not this run's: nothing removed")


def source_identity(root: Path = SERVER_CONTEXT) -> str:
    """`SOURCE_PIPELINE`'s answer, computed here: what a server image built from `root` reports as its source."""
    files = [p for p in root.rglob("*") if p.is_file() and not p.is_symlink()]  # find's -type f
    named = sorted(((f"./{p.relative_to(root).as_posix()}", p) for p in files), key=lambda e: e[0].encode())
    lines = "".join(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {name}\n" for name, p in named)
    return hashlib.sha256(lines.encode()).hexdigest()


def check_server_image(image: str, config: Path) -> None:
    """Before a proof uses the server's `image`: it was built from this tree. Its inventory (run with no network)
    names the identity of the build context its binary came from; anything else is refused, a stale image's missing
    one included: a proof never runs an older server than the code it claims to test."""
    expected = source_identity()
    answer = DOCKER(["docker", "run", "--rm", "--network", "none", "-e",
                     "DEWPOINT_TEMPORAL_CONFIG=/etc/temporal/config.yaml", "-v",
                     f"{config}:/etc/temporal/config.yaml:ro", image, "inventory"])  # fmt: skip
    try:
        reported = json.loads(answer).get("source")
    except (ValueError, AttributeError):
        reported = None
    if reported != expected:
        found = reported or "unrecorded"
        raise RuntimeError(f"{image} wasn't built from this tree: its source is {found}, this tree's {expected}. "
                           "Rebuild it (the run request's build step) before the proof.")  # fmt: skip


def forget_ports(run: Run) -> None:
    run.ports.clear()


def assigned_port(run: Run, service: str, port: int) -> int:
    """The host port Docker assigned `service`'s `port` (published as `127.0.0.1::<port>`), read back once."""
    if (service, port) not in run.ports:
        # the file's required settings need a configuration: the run's last, which the port doesn't depend on
        argv, env = compose(run, run.state.get("config", "jwt"), "port", service, str(port))
        answer = DOCKER(argv, env).strip()
        found = re.fullmatch(r"127\.0\.0\.1:(\d+)", answer.splitlines()[0] if answer else "")
        if found is None:
            raise RuntimeError(f"no port assigned to {service}:{port} on 127.0.0.1")
        run.ports[(service, port)] = int(found.group(1))
    return run.ports[(service, port)]


def s3_endpoint(run: Run) -> str:
    return f"http://127.0.0.1:{assigned_port(run, 'minio', 9000)}"


def record_project(run: Run) -> None:
    """The run's project, recorded once its guard found it fresh and before its first `up`, in the file the run's outer
    runner names (DEWPOINT_PROOF_PROJECTS): a run whose pytest is killed is then still removed, by that exact name
    (`remove_project`, `python -m tests.proofs.cleanup`)."""
    path = os.environ.get("DEWPOINT_PROOF_PROJECTS")
    if path:
        with Path(path).open("a") as f:
            f.write(run.project + "\n")


# The compose commands that make a project's containers, networks or volumes: each recorded in flight
CREATES = {"up", "create", "run", "scale"}


def creates_record(projects: Path) -> Path:
    """Where a run's compose creates are recorded in flight: beside its projects' record (DEWPOINT_PROOF_PROJECTS)."""
    return projects.with_name(projects.name + ".creates")


def _record_create(line: str) -> None:
    """One line appended to the creates' record and flushed to disk before it returns: a process killed right after
    still leaves it."""
    path = creates_record(Path(os.environ["DEWPOINT_PROOF_PROJECTS"]))
    with path.open("a") as f:
        f.write(line + "\n")
        f.flush()
        os.fsync(f.fileno())


def _begin_create(run: Run) -> str | None:
    """A compose create of the run's project, recorded in flight before it launches (when the outer runner records
    projects): its token. Nothing is launched unrecorded: a record that can't be written raises."""
    if not os.environ.get("DEWPOINT_PROOF_PROJECTS"):
        return None
    token = secrets.token_hex(8)
    _record_create(f"begin {run.project} {token}")
    return token


def interrupted_creates(projects: Path, project: str) -> list[str]:
    """The project's compose creates begun and never ended: their client stopped (killed, interrupted, timed out)
    while the daemon may still have been making what it had accepted, which can land at any time after."""
    record = creates_record(projects)
    if not record.exists():
        return []
    begun: list[str] = []
    ended: set[str] = set()
    for line in record.read_text().splitlines():
        what, _, rest = line.partition(" ")
        name, _, token = rest.partition(" ")
        if name == project and what == "begin":
            begun.append(token)
        elif name == project and what == "end":
            ended.add(token)
    return [token for token in begun if token not in ended]


def remove_project(project: str) -> list[str]:
    """After a killed run, by its recorded name: the containers (with their anonymous volumes), the volumes and the
    networks labelled with exactly that project. Each listing is checked whole first, every entry carrying the full
    name, and nothing is removed if one doesn't; a name `prepare` couldn't have made is refused outright.

    Best effort, never a confirmation on its own: it returns once the project is found quiet, never on one empty
    listing. Quiet is no compose client of the project alive (one SIGKILL didn't end may create more at any time), then
    two whole listings QUIET_S apart, both finding nothing, with no client alive at either; anything found in between is
    removed, and the quiet starts over. Not quiet after REMOVE_PASSES, it raises. A create in flight when its client was
    stopped can still land after the second listing: whether one was is the creates' record's (`interrupted_creates`),
    and the cleanup never confirms such a project."""
    if not PROJECT_NAME.fullmatch(project):
        raise ValueError(f"{project!r} is not a proof run's project")
    removed: list[str] = []
    empty_since_quiet_began = False  # the last pass found nothing, with no client alive, and waited QUIET_S since
    for _ in range(REMOVE_PASSES):
        if _clients(project):
            empty_since_quiet_began = False
            SLEEP(SETTLE_S)
            continue
        found = _listed(project)
        if not any(ids for _, ids, _ in found):
            if empty_since_quiet_began:
                return removed
            empty_since_quiet_began = True
            SLEEP(QUIET_S)
            continue
        empty_since_quiet_began = False
        for kind, ids, remove in found:  # containers first: a network or volume in use can't go
            if ids:
                try:
                    DOCKER([*remove, *ids])
                except RuntimeError:  # one already being removed, say: the next listing says what's left
                    continue
                removed += [f"{kind} {entry}" for entry in ids]
        SLEEP(SETTLE_S)
    raise RuntimeError(f"{project} still has a compose client, or containers, volumes or networks, after "
                       f"{REMOVE_PASSES} passes: never found quiet")  # fmt: skip


def _clients(project: str) -> list[str]:
    """The live processes naming the project as a word of their command line: a compose client of it."""
    return [line for line in PROCESSES() if project in line.split()]


def _listed(project: str) -> list[tuple[str, list[str], list[str]]]:
    kinds = [("container", ["docker", "ps", "-a"], "{{.ID}}", ["docker", "rm", "-f", "-v"]),
             ("volume", ["docker", "volume", "ls"], "{{.Name}}", ["docker", "volume", "rm"]),
             ("network", ["docker", "network", "ls"], "{{.ID}}", ["docker", "network", "rm"])]  # fmt: skip
    found: list[tuple[str, list[str], list[str]]] = []
    for kind, listing, key, remove in kinds:
        rows = DOCKER([*listing, "--filter", f"label={_LABEL}={project}",
                       "--format", key + ' {{.Label "' + _LABEL + '"}}'])  # fmt: skip
        ids = []
        for row in filter(None, (line.strip() for line in rows.splitlines())):
            entry, _, label = row.partition(" ")
            if label != project:
                raise RuntimeError(f"a {kind} listed under {project} is not the recorded project's: nothing removed")
            ids.append(entry)
        found.append((kind, ids, remove))
    return found


def check_running_image(run: Run, service: str, image_id: str) -> None:
    """After an `up` that created `service`: its container runs exactly `image_id`, the image whose identity was
    checked (`check_server_image` resolves a tag once; a tag moved since must never run under that record)."""
    container = f"{run.project}-{service}-1"
    running = DOCKER(["docker", "inspect", "--format", "{{.Image}}", container]).strip()
    if running != image_id:
        raise RuntimeError(f"{container} runs {running or 'nothing'}, not the image the run checked ({image_id})")


def down(run: Run, config: str) -> None:
    """The run's own project removed, after checking it's the run's: every profile's services, their volumes. Only a
    project the run brought up itself: a name its guard found taken (a collision) is someone else's, never removed."""
    if not run.state.get("fresh"):
        return
    guard_own(run)
    run_compose(run, config, "--profile", START_CHECK_PROFILE, "down", "-v", "--remove-orphans")


def run_compose(run: Run, config: str, *args: str, timeout: float = 300) -> str:
    run.state["config"] = config
    if "up" in args and not run.state.get("fresh"):
        guard_fresh(run)
        record_project(run)
        run.state["fresh"] = True  # from here on, the project is the run's own: `down` removes it
    if _CHANGES_PORTS & set(args):
        forget_ports(run)
    argv, env = compose(run, config, *args)
    # A create is recorded in flight before compose launches, and cleared only once its client returns (failing or
    # not): a client stopped mid-create leaves the record, and the cleanup never confirms the project then (the owner's
    # reviews of the race fix). Stopped is a timeout or an interruption (subprocess.run kills the client and raises),
    # or a signal that ended it (a negative code: no return of its own)
    create = _begin_create(run) if CREATES & set(args) else None
    done = subprocess.run(argv, env=env, capture_output=True, text=True, timeout=timeout, check=False)
    if create is not None and done.returncode >= 0:
        _record_create(f"end {run.project} {create}")
    if done.returncode != 0:
        # Compose's own message, not the environment: it holds the run's password
        raise RuntimeError(f"docker compose {args[0]} failed ({done.returncode}): {done.stderr[-2000:]}")
    return done.stdout


def s3(credentials: dict[str, str] | None = None, *, root: Run | None = None) -> Any:
    """An S3 client on the proof's MinIO: with STS credentials (which carry the endpoint `assume` found), or with the
    root ones (`root`)."""
    if root is not None:
        endpoint = s3_endpoint(root)
        access = (root.root / "minio" / "root_user").read_text()
        secret = (root.root / "minio" / "root_password").read_text()
        token = None
    else:
        assert credentials is not None
        access, secret = credentials["AccessKeyId"], credentials["SecretAccessKey"]
        token, endpoint = credentials["SessionToken"], credentials["Endpoint"]
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        region_name=REGION,
        aws_access_key_id=access,
        aws_secret_access_key=secret,
        aws_session_token=token,
    )


def assume(run: Run, kind: str, bucket: str, prefix: str, seconds: int = 3600) -> dict[str, str]:
    """One credential set: STS AssumeRole from the root credentials, narrowed by `kind`'s session policy. Whether
    MinIO grants that to its root user is the run's first check; if it refuses, the proof stops (a credential decision
    for the owner)."""
    endpoint = s3_endpoint(run)
    sts = boto3.client(
        "sts",
        endpoint_url=endpoint,
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
    return {**answer["Credentials"], "Endpoint": endpoint}  # the run's MinIO, which `s3` needs


def make_bucket(client: Any, bucket: str, *, days: int | None = BUCKET_DAYS) -> None:
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
