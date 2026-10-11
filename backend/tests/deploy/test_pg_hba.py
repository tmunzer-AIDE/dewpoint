# SPDX-License-Identifier: Apache-2.0
"""Compose's PostgreSQL admission file and TLS (2b-4b M4 recovery, task 17; design revision 9 §3, revision 11 §1): a
lint of `deploy/compose/postgres/pg_hba.conf` read as the server reads it (the first matching line decides), and of
the files around it. No server: a real connection's admission is the target qualification's (task 18).

- A recovery login (named `rcv_...`, a member of `dewpoint_recovery`) is admitted on one path alone: over SSL, to
  `dewpoint`, from the operators' addresses, by SCRAM. Every other path rejects it explicitly, before any broader line:
  TCP with or without SSL, the Unix socket, another database, replication; by its group and by its name.
- A service's login still connects as before (TCP, its password), and the socket keeps the image's own rule.
- Compose serves TLS with the deployment's certificate (`make-dev-ca.sh` makes a development authority's, never
  committed) and uses this file; CI makes that authority before Compose starts."""

import ipaddress
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

from tests.deploy.test_compose import service

ROOT = Path(__file__).parents[3]
POSTGRES = ROOT / "deploy" / "compose" / "postgres"
HBA = POSTGRES / "pg_hba.conf"
RECOVERY_GROUP = "dewpoint_recovery"


@dataclass(frozen=True)
class Line:
    kind: str  # local, host, hostssl, hostnossl
    databases: tuple[str, ...]
    users: tuple[str, ...]
    address: str | None
    method: str


def lines() -> list[Line]:
    """The file's rules, in order (comments and blank lines aside)."""
    rules = []
    for raw in HBA.read_text().splitlines():
        fields = raw.split("#", 1)[0].split()
        if not fields:
            continue
        kind, databases, users, *rest = fields
        address = None if kind == "local" else rest.pop(0)
        rules.append(Line(kind, tuple(databases.split(",")), tuple(users.split(",")), address, rest[0]))
    return rules


@dataclass(frozen=True)
class Connection:
    kind: str  # local, or tcp
    ssl: bool
    database: str  # a name, or "replication" for a replication connection
    user: str
    groups: frozenset[str]
    address: str | None  # a TCP connection's source


def _user_matches(line: Line, c: Connection) -> bool:
    for user in line.users:
        if user == "all" or user == c.user:
            return True
        if user.startswith("+") and user[1:] in c.groups:
            return True
        if user.startswith("/") and re.search(user[1:], c.user):
            return True
    return False


def _database_matches(line: Line, c: Connection) -> bool:
    if c.database == "replication":
        return "replication" in line.databases
    return "all" in line.databases or c.database in line.databases


def _kind_matches(line: Line, c: Connection) -> bool:
    if line.kind == "local" or c.kind == "local":
        return line.kind == c.kind
    return line.kind == "host" or (line.kind == "hostssl") == c.ssl


def _address_matches(line: Line, c: Connection) -> bool:
    if line.address is None or line.address == "all":
        return True
    return ipaddress.ip_address(c.address or "") in ipaddress.ip_network(line.address)


def decided(c: Connection) -> str:
    """The method of the first line matching `c` (the server's own rule), or `reject` when none does."""
    for line in lines():
        if _kind_matches(line, c) and _database_matches(line, c) and _user_matches(line, c) and _address_matches(
                line, c):  # fmt: skip
            return line.method
    return "reject"


def _operator_address() -> str:
    allowed = lines()[0]
    assert allowed.address is not None
    return str(next(ipaddress.ip_network(allowed.address).hosts()))


def recovery(kind: str, *, ssl: bool = True, database: str = "dewpoint", address: str | None = None,
             member: bool = True) -> Connection:  # fmt: skip
    return Connection(kind, ssl, database, "rcv_alice", frozenset({RECOVERY_GROUP} if member else ()),
                      None if kind == "local" else (address or _operator_address()))  # fmt: skip


def test_the_allowed_recovery_line_comes_first_ssl_to_dewpoint_by_scram() -> None:
    first = lines()[0]
    assert (first.kind, first.databases, first.users) == ("hostssl", ("dewpoint",), (f"+{RECOVERY_GROUP}",))
    assert first.method == "scram-sha-256"
    assert first.address is not None and ipaddress.ip_network(first.address).num_addresses > 0


def test_every_reject_line_is_there_for_the_group_and_the_name_and_before_any_broader_line() -> None:
    rules = lines()
    rejects = {(r.kind, r.databases, r.users) for r in rules if r.method == "reject"}
    for users in ((f"+{RECOVERY_GROUP}",), ("/^rcv_",)):
        for kind in ("host", "local"):
            for database in ("all", "replication"):
                assert (kind, (database,), users) in rejects, (kind, database, users)
    first_other = next(n for n, r in enumerate(rules) if n > 0 and r.method != "reject")
    assert all(r.method == "reject" for r in rules[1:first_other]) and len(rules[1:first_other]) == 8
    assert not any(r.method == "reject" for r in rules[first_other:])


def test_a_recovery_login_is_admitted_on_one_path_alone() -> None:
    assert decided(recovery("tcp")) == "scram-sha-256"
    refused = {
        "another address": recovery("tcp", address="10.20.30.40"),
        "TCP without SSL": recovery("tcp", ssl=False),
        "the Unix socket": recovery("local"),
        "another database": recovery("tcp", database="postgres"),
        "a replication connection": recovery("tcp", database="replication"),
        "replication on the socket": recovery("local", database="replication"),
        "a revoked login, by name": recovery("tcp", address="10.20.30.40", member=False),
        "a revoked login on the socket": recovery("local", member=False),
        "a revoked login to another database": recovery("tcp", database="postgres", member=False),
    }
    assert {why: decided(c) for why, c in refused.items()} == {why: "reject" for why in refused}


def test_no_line_a_recovery_login_could_reach_trusts_it() -> None:
    databases = ("dewpoint", "postgres", "replication")
    paths = [recovery(kind, ssl=ssl, database=database, address=address, member=member)
             for kind in ("tcp", "local") for ssl in (True, False) for database in databases
             for address in (None, "10.20.30.40", "127.0.0.1") for member in (True, False)]  # fmt: skip
    assert {decided(c) for c in paths} <= {"reject", "scram-sha-256"}


def test_a_services_login_still_connects_by_its_password_and_the_socket_keeps_the_images_rule() -> None:
    for ssl in (False, True):
        api = Connection("tcp", ssl, "dewpoint", "dewpoint_api_login", frozenset({"dewpoint_api"}), "172.18.0.5")
        assert decided(api) == "scram-sha-256"
    owner = Connection("local", False, "dewpoint", "dewpoint_owner", frozenset(), None)
    assert decided(owner) == "trust"  # the image's initialization and its health check, inside the container


def test_compose_serves_tls_with_the_deployments_certificate_and_uses_this_file() -> None:
    postgres = service("postgres")
    started = " ".join(str(part) for part in postgres["entrypoint"])
    for setting in ("ssl=on", "hba_file=/etc/postgresql/pg_hba.conf",
                    "ssl_cert_file=/var/lib/postgresql/tls/server.crt",
                    "ssl_key_file=/var/lib/postgresql/tls/server.key"):  # fmt: skip
        assert f"-c {setting}" in started, setting
    assert "-m 600 /etc/postgresql/tls/server.key /var/lib/postgresql/tls/server.key" in started  # the server's own
    assert "exec docker-entrypoint.sh postgres" in started
    assert "./postgres/pg_hba.conf:/etc/postgresql/pg_hba.conf:ro" in postgres["volumes"]
    assert "${DEWPOINT_POSTGRES_TLS_DIR:-./postgres/tls}:/etc/postgresql/tls:ro" in postgres["volumes"]


def test_ci_makes_the_development_authority_before_compose_starts() -> None:
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
    made, up = ci.find("sh postgres/make-dev-ca.sh"), ci.find("docker compose up")
    assert 0 <= made < up


def test_the_development_authoritys_files_are_never_committed() -> None:
    for name in ("ca.crt", "ca.key", "server.crt", "server.key"):
        ignored = subprocess.run(["git", "-C", str(ROOT), "check-ignore", "-q", f"deploy/compose/postgres/tls/{name}"],
                                 check=False)  # fmt: skip
        assert ignored.returncode == 0, name


@pytest.mark.skipif(shutil.which("openssl") is None, reason="needs the openssl command")
def test_the_development_authority_signs_a_server_certificate_for_compose_names(tmp_path: Path) -> None:
    made = subprocess.run(["sh", str(POSTGRES / "make-dev-ca.sh"), str(tmp_path)], capture_output=True, text=True,
                          timeout=60, check=False)  # fmt: skip
    assert made.returncode == 0, made.stderr
    assert (tmp_path / "server.key").stat().st_mode & 0o077 == 0  # its owner's alone
    verified = subprocess.run(["openssl", "verify", "-CAfile", str(tmp_path / "ca.crt"), str(tmp_path / "server.crt")],
                              capture_output=True, text=True, check=False)  # fmt: skip
    assert verified.returncode == 0, verified.stdout + verified.stderr
    text = subprocess.run(["openssl", "x509", "-in", str(tmp_path / "server.crt"), "-noout", "-text"],
                          capture_output=True, text=True, check=True).stdout  # fmt: skip
    assert "DNS:postgres" in text and "DNS:localhost" in text
    before = (tmp_path / "server.key").read_bytes()
    again = subprocess.run(["sh", str(POSTGRES / "make-dev-ca.sh"), str(tmp_path)], capture_output=True, text=True,
                           timeout=60, check=False)  # fmt: skip
    assert again.returncode == 0 and (tmp_path / "server.key").read_bytes() == before  # never replaced by a rerun
