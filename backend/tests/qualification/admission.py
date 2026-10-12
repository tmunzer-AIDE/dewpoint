# SPDX-License-Identifier: Apache-2.0
"""Admission, with real connections (design revision 9 §3 and §5.3): a test recovery login tried on every path, and on
every database the server lists; an ordinary service login still connecting; and the server's own reading of its
admission file (`pg_hba_file_rules`).

Run once from an operator's address (`--where operator`: one path accepted, every other rejected) and once from
anywhere else (`--where elsewhere`: every path rejected), each with the current test login and with a revoked one
(`--login-state revoked`: rejected everywhere, by name). The socket paths run only on the database's own host
(`--socket-dir`). Connections go through `psql`, which tells a rejection by the admission file apart from a failed
password.

    DEWPOINT_QUALIFICATION_APPROVED=<id> DEWPOINT_QUALIFICATION_LOGIN_PASSWORD=... \\
    DEWPOINT_QUALIFICATION_SERVICE_PASSWORD=... DEWPOINT_QUALIFICATION_ADMIN_PASSWORD=... \\
    python -m tests.qualification.admission --host db.example --ca ca.crt --login rcv_qualify_1 \\
      --where operator --login-state current --service-login dewpoint_api_login --admin-login postgres \\
      [--socket-dir /var/run/postgresql] --out admission.jsonl"""

import argparse
import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tests.qualification.approval import Record, approved, secret

GROUP = "dewpoint_recovery"
REJECTS = tuple((kind, database, user) for user in (f"+{GROUP}", "/^rcv_") for kind in ("host", "local")
                for database in ("all", "replication"))  # fmt: skip


@dataclass(frozen=True)
class AdmissionPath:
    name: str
    database: str
    ssl: bool = True
    replication: str | None = None  # physical (`replication=true`: the `replication` lines) or logical (a database)
    socket: bool = False


PATHS = (
    AdmissionPath("ssl to dewpoint", "dewpoint"),
    AdmissionPath("tcp without ssl", "dewpoint", ssl=False),
    AdmissionPath("replication over ssl", "dewpoint", replication="physical"),
    AdmissionPath("logical replication to dewpoint", "dewpoint", replication="logical"),
    AdmissionPath("the unix socket", "dewpoint", ssl=False, socket=True),
    AdmissionPath("replication on the unix socket", "dewpoint", ssl=False, replication="physical", socket=True),
)


def expected(path: AdmissionPath, *, where: str, login: str) -> str:
    """One path alone accepts a current login from an operator's address. A logical walsender to `dewpoint` from there
    is matched by that same line (pg_hba names its database, never `replication`), so the server refuses it after
    admission: the login has no REPLICATION. Everything else is rejected by the admission file."""
    if (where, login) == ("operator", "current"):
        if path.name == "ssl to dewpoint":
            return "accepted"
        if path.replication == "logical":
            return "walsender_refused"
    return "rejected"


def classify(returncode: int, stderr: str) -> str:
    """`psql`'s answer: accepted; rejected by the admission file (a reject line, or no line at all); admitted but its
    password refused (`authenticated_wrong`: the admission file let it through); or unreachable."""
    if returncode == 0:
        return "accepted"
    if "pg_hba.conf rejects connection" in stderr or "no pg_hba.conf entry" in stderr:
        return "rejected"
    if "permission denied to start WAL sender" in stderr:
        return "walsender_refused"
    if "authentication failed" in stderr:
        return "authenticated_wrong"
    return "unreachable"


def rule_problems(rows: list[tuple[Any, ...]]) -> list[str]:
    """What's wrong with the server's own reading of its admission file (`pg_hba_file_rules`: line, type, databases,
    users, address, method, error): a rule in error; a reject line missing; or one after a broader line."""
    problems = [f"line {line} in error: {error}" for line, *_, error in rows if error]
    found = {(kind, db, user): line for line, kind, dbs, users, _, method, _ in rows if method == "reject"
             for db in dbs or () for user in users or ()}  # fmt: skip
    problems += [
        f"reject line missing: {kind} {db} {user}" for kind, db, user in REJECTS if (kind, db, user) not in found
    ]
    allowed = [line for line, kind, dbs, users, _, method, _ in rows
               if (kind, tuple(dbs or ()), tuple(users or ()), method) == ("hostssl", ("dewpoint",), (f"+{GROUP}",),
                                                                          "scram-sha-256")]  # fmt: skip
    recovery = set(found.values()) | set(allowed)
    broader = [line for line, *_ in rows if line not in recovery]
    for (kind, db, user), line in found.items():
        if broader and line > min(broader):
            problems.append(f"{kind} {db} {user} rejects at line {line}, after the broader line {min(broader)}: every "
                            "reject line must come before it")  # fmt: skip
    return problems


def _conninfo(**values: str) -> str:
    """libpq's `key='value'` form, each value quoted as libpq reads it."""
    return " ".join("{}='{}'".format(k, v.replace("\\", "\\\\").replace("'", "\\'")) for k, v in values.items())


def connection(args: Any, path: AdmissionPath) -> tuple[dict[str, str], str]:
    """The path's connection parameters (but its user), and what it asks once in: a physical walsender takes only
    replication commands (`IDENTIFY_SYSTEM`)."""
    values = {"dbname": path.database, "connect_timeout": "10", "host": args.socket_dir if path.socket else args.host}
    if not path.socket:
        values["port"] = str(args.port)
        values |= {"sslmode": "verify-full", "sslrootcert": str(args.ca)} if path.ssl else {"sslmode": "disable"}
    if path.replication:
        values["replication"] = "true" if path.replication == "physical" else "database"
    return values, "IDENTIFY_SYSTEM" if path.replication == "physical" else "select 1"


def _psql(args: argparse.Namespace, path: AdmissionPath, user: str, password: str,
          query: str | None = None) -> subprocess.CompletedProcess[str]:  # fmt: skip
    values, asked = connection(args, path)
    env = {**os.environ, "PGPASSWORD": password, "PGAPPNAME": "dewpoint-qualification"}
    return subprocess.run(["psql", _conninfo(**values, user=user), "-XAtqc", query or asked], env=env,
                          capture_output=True, text=True, timeout=60, check=False)  # fmt: skip


DESCRIPTION = "Admission, with real connections: a test recovery login on every path (design revision 9 §3)."
ADMIN = AdmissionPath("the administrator", "dewpoint")
DATABASES = "select coalesce(json_agg(datname order by datname), '[]') from pg_database where datname <> 'dewpoint'"
RULES = ("select coalesce(json_agg(json_build_array(line_number, type, database, user_name, address, auth_method, "
         "error) order by line_number), '[]') from pg_hba_file_rules")  # fmt: skip


def main() -> int:
    approval = approved()
    parser = argparse.ArgumentParser(prog="python -m tests.qualification.admission", description=DESCRIPTION)
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, default=5432)
    parser.add_argument("--ca", type=Path, required=True, help="the deployment's authority's certificate")
    parser.add_argument("--login", required=True, help="the test recovery login (rcv_...)")
    parser.add_argument("--where", choices=("operator", "elsewhere"), required=True)
    parser.add_argument("--login-state", choices=("current", "revoked"), required=True)
    parser.add_argument("--service-login", required=True, help="an ordinary service login, e.g. dewpoint_api_login")
    parser.add_argument("--admin-login", required=True, help="the database administrator's, for pg_hba_file_rules")
    parser.add_argument("--socket-dir", help="the server's socket directory: on the database's own host only")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    record = Record(args.out, "admission", approval)
    password, admin_password = (
        secret("DEWPOINT_QUALIFICATION_LOGIN_PASSWORD"),
        secret("DEWPOINT_QUALIFICATION_ADMIN_PASSWORD"),
    )
    record.write(target=f"{args.host}:{args.port}", where=args.where, login=args.login, login_state=args.login_state)

    listed = _psql(args, ADMIN, args.admin_login, admin_password, DATABASES)
    rules = _psql(args, ADMIN, args.admin_login, admin_password, RULES)
    if listed.returncode != 0 or rules.returncode != 0:
        record.check(False, "the administrator reads the databases and the rules",
                     answer=classify(listed.returncode or rules.returncode, listed.stderr + rules.stderr))  # fmt: skip
        return record.finished()
    rows = [tuple(r) for r in json.loads(rules.stdout)]
    problems = rule_problems(rows)
    record.check(bool(rows) and not problems, "pg_hba_file_rules: the recovery lines first, none in error",
                 problems=problems)  # fmt: skip

    others = tuple(AdmissionPath(f"ssl to {name}", name) for name in json.loads(listed.stdout))
    for path in (*PATHS, *others):
        if path.socket and not args.socket_dir:
            record.check(False, f"{path.name}: not run here (on the database's host, with --socket-dir)")
            continue
        run = _psql(args, path, args.login, password)
        answer, wanted = classify(run.returncode, run.stderr), expected(path, where=args.where, login=args.login_state)
        record.check(answer == wanted, f"{path.name}: {wanted}", answer=answer)

    run = _psql(args, AdmissionPath("a service login", "dewpoint"), args.service_login,
                secret("DEWPOINT_QUALIFICATION_SERVICE_PASSWORD"))  # fmt: skip
    record.check(classify(run.returncode, run.stderr) == "accepted", "an ordinary service login still connects")
    return record.finished()


if __name__ == "__main__":
    raise SystemExit(main())
