# SPDX-License-Identifier: Apache-2.0
"""No verifier in any log (design revision 9 §2): the administrator's provisioning run on every path with test
verifiers, each carrying its own random marker (its salt), then every log the target produces searched for each.

`exercise`, as the database administrator, through `dewpoint recovery`'s own provisioning and rotation:
1. a provisioning that succeeds;
2. refused by the verifier check: a plaintext value, an md5 value;
3. a duplicate login name, refused inside the transaction;
4. a failure after `CREATE ROLE`, on the mapping insert (a check, `NOT VALID`, on that test name alone, added by the
   schema's owner and dropped after), so the transaction rolls back;
5. cancelled mid-transaction: the audit table held by the owner, the waiting provisioning cancelled;
6. a rotation: succeeding, refused by the verifier check, of an unknown login, and cancelled.
Every test login is revoked at the end and its name retired; the markers are written to `--markers`.

`search`: every file under every path given (PostgreSQL's logs in each configured format, an audit extension's, every
pooler's and proxy's, the host's and the container runtime's, and wherever they're shipped), `.gz` included, searched
for each marker. Any hit fails, and provisioning by verifier stays disabled on that target.

    DEWPOINT_QUALIFICATION_APPROVED=<id> DEWPOINT_QUALIFICATION_ADMIN_PASSWORD=... \\
    DEWPOINT_QUALIFICATION_OWNER_PASSWORD=... DEWPOINT_QUALIFICATION_VERIFIER_PASSWORD=... \\
    python -m tests.qualification.logging exercise --admin-dsn '<verify-full DSN>' --owner-dsn '<verify-full DSN>' \\
      --user-id <a test platform admin's id> --markers markers.json --out logging.jsonl
    DEWPOINT_QUALIFICATION_APPROVED=<id> python -m tests.qualification.logging search --markers markers.json \\
      --out logging.jsonl /var/log/postgresql /var/lib/docker/containers ..."""

import argparse
import asyncio
import base64
import gzip
import json
import secrets
import uuid
from collections.abc import Awaitable, Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import asyncpg  # type: ignore[import-untyped]  # it ships no type information

from dewpoint.apps.cli import recovery
from dewpoint.core.config import get_settings
from tests.qualification.approval import Record, approved, secret

DESCRIPTION = "No verifier in any log: provisioning on every path with marked test verifiers, then a log search."
EXPECTED = {  # each case's own outcome: anything else means it didn't take its path, so its search proves nothing
    "1 provisioned": "succeeded",
    "2 plaintext refused": "ValueError",
    "2 md5 refused": "ValueError",
    "3 duplicate name": "ValueError",
    "4 failed after CREATE ROLE": "CheckViolationError",
    "5 cancelled": "QueryCanceledError",
    "6 rotated": "succeeded",
    "6 plaintext refused": "ValueError",
    "6 unknown login": "ValueError",
    "6 cancelled": "QueryCanceledError",
}


def marker() -> tuple[bytes, str]:
    """A verifier's salt, and the text it appears as in that verifier (base64): a marker unique to one case."""
    salt = secrets.token_bytes(16)
    return salt, base64.b64encode(salt).decode()


MARKER_CASES = ("1", "2 plaintext", "2 md5", "3", "4", "5", "6", "6 plaintext", "6 unknown", "6 cancelled")


@dataclass(frozen=True)
class Hit:
    path: Path
    line: int
    case: str


@dataclass
class Searched:
    hits: list[Hit] = field(default_factory=list)
    read: list[Path] = field(default_factory=list)  # every file read whole
    unreadable: list[Path] = field(default_factory=list)


def _files(paths: Sequence[Path]) -> Iterator[Path]:
    for path in paths:
        if path.is_dir():
            yield from sorted(p for p in path.rglob("*") if p.is_file())
        elif path.is_file():
            yield path


def searched(markers: dict[str, str], paths: Sequence[Path]) -> Searched:
    """Every line of every file under `paths` holding a case's marker (as written, or with JSON's escaped slash), with
    the files read and those that couldn't be."""
    forms = {case: {m, m.replace("/", "\\/")} for case, m in markers.items()}
    found = Searched()
    for path in _files(paths):
        try:
            opened = gzip.open(path, "rt", errors="replace") if path.suffix == ".gz" else path.open(errors="replace")
            with opened as f:
                for number, line in enumerate(f, start=1):
                    found.hits += [Hit(path, number, case) for case, marks in forms.items()
                                   if any(m in line for m in marks)]  # fmt: skip
        except OSError:
            found.unreadable.append(path)
            continue
        found.read.append(path)
    return found


def search(markers: dict[str, str], paths: Sequence[Path]) -> list[Hit]:
    return searched(markers, paths).hits


async def _exercise(args: argparse.Namespace, record: Record) -> dict[str, str]:
    admin = recovery.server(args.admin_dsn, user=recovery.ADMINISTRATOR)
    owner = recovery.server(args.owner_dsn, user=recovery.ADMINISTRATOR)
    sink = recovery.required_sink(get_settings())  # the off-host record, exercised with it
    password = secret("DEWPOINT_QUALIFICATION_VERIFIER_PASSWORD")
    run = uuid.uuid4().hex[:10]
    login, faulted, cancelled = f"rcv_q{run}_a", f"rcv_q{run}_b", f"rcv_q{run}_c"
    markers: dict[str, str] = {}

    def verifier(case: str) -> str:
        salt, text = marker()
        markers[case] = text
        return recovery.scram_verifier(password, salt=salt)

    attempted: list[str] = []

    async def attempt(case: str, act: Awaitable[object]) -> None:
        attempted.append(case)
        try:
            await act
            outcome = "succeeded"
        except Exception as e:  # each failure is the case's point: its type recorded, never its message
            outcome = type(e).__name__
        record.check(outcome == EXPECTED[case], f"{case}: {EXPECTED[case]}", outcome=outcome)

    async def rolled_back(case: str, name: str) -> None:
        made = await a.fetchval("select exists (select 1 from pg_roles where rolname = $1)", name)
        record.check(not made, f"{case}: rolled back, no login left")

    a = await recovery.connect(admin, secret("DEWPOINT_QUALIFICATION_ADMIN_PASSWORD"))
    o = await recovery.connect(owner, secret("DEWPOINT_QUALIFICATION_OWNER_PASSWORD"))
    by = admin.user
    try:
        await attempt("1 provisioned", recovery.provision(a, sink, login, args.user_id, verifier("1"), by=by))
        _, plain = marker()
        markers["2 plaintext"] = plain
        await attempt("2 plaintext refused", recovery.provision(a, sink, f"rcv_q{run}_p", args.user_id,
                                                                 f"qualify-{plain}", by=by))  # fmt: skip
        salt, _ = marker()
        markers["2 md5"] = salt.hex()
        await attempt("2 md5 refused", recovery.provision(a, sink, f"rcv_q{run}_m", args.user_id, "md5" + salt.hex(),
                                                          by=by))  # fmt: skip
        await attempt("3 duplicate name", recovery.provision(a, sink, login, args.user_id, verifier("3"), by=by))
        await o.execute(f"ALTER TABLE recovery_operators ADD CONSTRAINT qualification_fault CHECK (login <> "
                        f"'{faulted}') NOT VALID")  # fmt: skip  # a generated test name
        try:
            await attempt("4 failed after CREATE ROLE",
                          recovery.provision(a, sink, faulted, args.user_id, verifier("4"), by=by))  # fmt: skip
        finally:
            await o.execute("ALTER TABLE recovery_operators DROP CONSTRAINT qualification_fault")
        await rolled_back("4", faulted)
        await attempt("5 cancelled", _cancelled(a, o, recovery.provision(a, sink, cancelled, args.user_id,
                                                                         verifier("5"), by=by)))  # fmt: skip
        await rolled_back("5", cancelled)
        await attempt("6 rotated", recovery.rotate(a, sink, login, verifier("6"), by=by))
        _, rotated_plain = marker()
        markers["6 plaintext"] = rotated_plain
        await attempt("6 plaintext refused", recovery.rotate(a, sink, login, f"qualify-{rotated_plain}", by=by))
        await attempt("6 unknown login", recovery.rotate(a, sink, f"rcv_q{run}_u", verifier("6 unknown"), by=by))
        await attempt("6 cancelled", _cancelled(a, o, recovery.rotate(a, sink, login, verifier("6 cancelled"), by=by)))
        record.check(attempted == list(EXPECTED), "every case run, in order", attempted=attempted)
    finally:
        for name in (login, faulted, cancelled):
            if await a.fetchval("select exists (select 1 from recovery_operators where login = $1 "
                                "and revoked_at is null)", name):  # fmt: skip
                await recovery.revoke(a, sink, name, by=by)
        await a.close()
        await o.close()
    return markers


class LockWaitUnseen(Exception):
    """The provisioning was never seen waiting on the held table: nothing was cancelled mid-transaction."""


async def _cancelled(admin: asyncpg.Connection, owner: asyncpg.Connection, act: Awaitable[object]) -> None:
    """`act`, its transaction cancelled while it waits on the audit table the owner holds; `LockWaitUnseen` (after it
    ran its course) when it was never seen waiting, so the case can't pass by a cancel that came too late."""
    waited = False
    async with owner.transaction():
        await owner.execute("LOCK TABLE audit_log IN SHARE ROW EXCLUSIVE MODE")
        task = asyncio.ensure_future(act)
        pid = admin.get_server_pid()
        for _ in range(100):
            if await owner.fetchval("select wait_event_type = 'Lock' from pg_stat_activity where pid = $1", pid):
                waited = True
                break
            await asyncio.sleep(0.1)
        if waited:
            await owner.execute("select pg_cancel_backend($1)", pid)
    if not waited:
        await asyncio.gather(task, return_exceptions=True)
        raise LockWaitUnseen
    await task


def main() -> int:
    approval = approved()
    parser = argparse.ArgumentParser(prog="python -m tests.qualification.logging", description=DESCRIPTION)
    steps = parser.add_subparsers(dest="step", required=True)
    exercise = steps.add_parser("exercise")
    exercise.add_argument("--admin-dsn", required=True, help="the administrator's, verify-full")
    exercise.add_argument("--owner-dsn", required=True, help="the schema owner's, for the injected faults")
    exercise.add_argument("--user-id", type=uuid.UUID, required=True, help="a test platform admin's id")
    exercise.add_argument("--markers", type=Path, required=True)
    exercise.add_argument("--out", type=Path, required=True)
    found = steps.add_parser("search")
    found.add_argument("--markers", type=Path, required=True)
    found.add_argument("--out", type=Path, required=True)
    found.add_argument("paths", type=Path, nargs="+")
    args = parser.parse_args()
    record = Record(args.out, f"logging {args.step}", approval)
    if args.step == "exercise":
        markers = asyncio.run(_exercise(args, record))
        record.check(set(markers) == set(MARKER_CASES), "every case's marker made", made=sorted(markers))
        args.markers.write_text(json.dumps(markers, indent=2))
        record.write(markers=sorted(markers))
        return record.finished()
    markers = json.loads(args.markers.read_text())
    lacking = [case for case in MARKER_CASES if not isinstance(markers.get(case), str) or len(markers[case]) < 16]
    record.check(not lacking, "the exercise's every marker, none empty", lacking=lacking)
    for path in args.paths:
        record.check(path.exists(), f"{path}: there to search")
    result = searched({case: markers[case] for case in MARKER_CASES if case not in lacking}, args.paths)
    record.check(bool(result.read), "at least one log file read", read=len(result.read))
    record.check(
        not result.unreadable, "every file under the paths readable", unreadable=[str(p) for p in result.unreadable]
    )
    for hit in result.hits:
        record.check(False, f"a marker in {hit.path}:{hit.line}", case=hit.case)
    record.check(not result.hits, "no marker in any log", searched=[str(p) for p in args.paths], cases=sorted(markers))
    return record.finished()


if __name__ == "__main__":
    raise SystemExit(main())
