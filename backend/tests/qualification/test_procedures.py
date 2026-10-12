# SPDX-License-Identifier: Apache-2.0
"""The qualification procedures' own logic (2b-4b M4 recovery, task 18), checked without any target: how admission
reads an answer and the server's rules, what the logging search finds, how the clock skew is bounded, and what the
privilege check calls excess. Running a procedure against a target is the qualification's, under its approval."""

import argparse
import asyncio
import base64
import gzip
import json
import os
import subprocess
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import asyncpg  # type: ignore[import-untyped]  # it ships no type information

from dewpoint.apps.cli import recovery
from tests.qualification import admission, clock_skew, d6, privileges
from tests.qualification import logging as log_search
from tests.qualification.approval import Record

T0 = datetime(2026, 10, 11, 12, tzinfo=UTC)
BACKEND = Path(__file__).parents[2]


def test_admission_reads_a_rejection_apart_from_a_failed_password() -> None:
    assert admission.classify(0, "") == "accepted"
    rejected = 'FATAL:  pg_hba.conf rejects connection for host "10.0.0.9", user "rcv_q"'
    assert admission.classify(2, rejected) == "rejected"
    assert admission.classify(2, 'FATAL:  no pg_hba.conf entry for host "10.0.0.9", user "rcv_q"') == "rejected"
    assert admission.classify(2, 'FATAL:  password authentication failed for user "rcv_q"') == "authenticated_wrong"
    assert admission.classify(2, "could not connect to server: Connection refused") == "unreachable"


def test_admission_expects_one_accepted_path_for_an_operator_and_none_elsewhere() -> None:
    accepted = [p for p in admission.PATHS if admission.expected(p, where="operator", login="current") == "accepted"]
    assert [p.name for p in accepted] == ["ssl to dewpoint"]
    assert all(admission.expected(p, where="elsewhere", login="current") == "rejected" for p in admission.PATHS)
    assert all(admission.expected(p, where="operator", login="revoked") == "rejected" for p in admission.PATHS)


def test_admission_finds_a_reject_line_after_a_broader_one_or_a_rule_in_error() -> None:
    rows = [  # pg_hba_file_rules: line, type, databases, users, address, method, error
        (1, "hostssl", ["dewpoint"], ["+dewpoint_recovery"], "192.0.2.0", "scram-sha-256", None),
        *((n, kind, [db], [user], None if kind == "local" else "all", "reject", None)
          for n, (kind, db, user) in enumerate(admission.REJECTS, start=2)),
        (10, "host", ["all"], ["all"], "all", "scram-sha-256", None),
    ]  # fmt: skip
    assert admission.rule_problems(rows) == []
    broader_first = [(n, *r[1:]) for n, r in enumerate([rows[0], rows[-1], *rows[1:-1]], start=1)]  # its order
    assert any("before" in p for p in admission.rule_problems(broader_first))
    missing = rows[:3] + rows[4:]
    assert any("missing" in p for p in admission.rule_problems(missing))
    in_error = [*rows, (11, "host", ["all"], ["all"], None, None, "invalid IP mask")]
    assert any("error" in p for p in admission.rule_problems(in_error))


def test_a_marker_is_the_verifiers_salt_and_the_search_finds_it_in_any_log(tmp_path: Path) -> None:
    salt, marker = log_search.marker()
    assert marker == base64.b64encode(salt).decode() and len(salt) == 16
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / "postgresql.csv").write_text(f"2026-10-11,ERROR,CREATE ROLE x PASSWORD '...{marker}...'\n")
    with gzip.open(tmp_path / "shipped.log.gz", "wt") as f:
        f.write(f"line one\nline {marker} two\n")
    hits = log_search.search({"success": marker, "unused": log_search.marker()[1]}, [tmp_path])
    assert sorted((h.path.name, h.line, h.case) for h in hits) == [("postgresql.csv", 1, "success"),
                                                                    ("shipped.log.gz", 2, "success")]  # fmt: skip
    assert log_search.search({"success": marker}, [tmp_path / "nested" / "empty.log"]) == []  # nothing there


def test_a_readings_skew_is_bounded_from_above_by_the_farther_end_of_its_window() -> None:
    """Temporal's time T, stamped at some database time inside [before, after], so its skew lies in
    [T - after, T - before]: what a maximum may rest on is the larger magnitude (the final review's finding 3)."""
    second = timedelta(seconds=1)
    assert clock_skew.bound(T0, T0 + second, T0 + 2 * second) == second  # inside the window: still up to 1 s
    assert clock_skew.bound(T0, T0 - 3 * second, T0 + second) == 4 * second  # Temporal behind
    assert clock_skew.bound(T0, T0 + 5 * second, T0 + second) == 5 * second  # Temporal ahead
    assert clock_skew.proposed([second, 3 * second, 2 * second], margin=timedelta(milliseconds=500)) == timedelta(
        seconds=3.5
    )


def test_clock_skew_never_passes_with_nothing_measured(tmp_path: Path) -> None:
    run = subprocess.run([sys.executable, "-m", "tests.qualification.clock_skew", "--dsn", "postgresql://x@h/d",
                          "--rounds", "0", "--margin-ms", "500", "--out", str(tmp_path / "out.jsonl")],
                         cwd=BACKEND, env={**os.environ, "DEWPOINT_QUALIFICATION_APPROVED": "TQ-1"},
                         capture_output=True, text=True, timeout=60, check=False)  # fmt: skip
    assert run.returncode == 2 and "--rounds" in run.stderr  # refused before any connection


def test_admission_tries_physical_replication_against_the_replication_lines_and_logical_apart() -> None:
    """A logical walsender (`replication=database`) is matched by its database's name, never by `replication`: the
    replication reject lines meet physical connections alone (the final review's finding 2)."""
    args = SimpleNamespace(host="db", port=5432, ca=Path("ca.crt"), socket_dir="/run/postgresql")
    physical = [p for p in admission.PATHS if p.replication == "physical"]
    assert {p.name for p in physical} == {"replication over ssl", "replication on the unix socket"}
    assert all(admission.connection(args, p)[0]["replication"] == "true" for p in physical)
    assert all(admission.connection(args, p)[1] == "IDENTIFY_SYSTEM" for p in physical)
    logical = next(p for p in admission.PATHS if p.replication == "logical")
    assert admission.connection(args, logical)[0]["replication"] == "database"
    assert admission.expected(logical, where="operator", login="current") == "walsender_refused"
    assert admission.expected(logical, where="elsewhere", login="current") == "rejected"
    refusal = "FATAL:  permission denied to start WAL sender\nDETAIL:  Only roles with the REPLICATION attribute"
    assert admission.classify(2, refusal) == "walsender_refused"


def test_d6s_probes_never_leave_a_stray_object_where_the_audit_is_read() -> None:
    """Should an identity be let write where it mustn't, its probe is locked for good: outside both the anchors and the
    administration records, or a well-formed record (the final review's finding 5)."""
    outside = d6.outside_key("dewpoint/", "TQ-1")
    assert not outside.startswith("dewpoint/database-administration/") and "/anchors/" not in f"/{outside}"
    key, body = d6.reader_probe("dewpoint/", "TQ-1")
    assert key.startswith("dewpoint/database-administration/")
    assert {"action", "phase", "action_id"} <= json.loads(body).keys()


def test_a_service_roles_rights_beyond_or_short_of_heads_are_drift() -> None:
    """The target's service roles against the reference taken at head: a grant the migrations never made (the API
    inserting a confirmation, say) is drift, and so is one missing (the final review's finding 6)."""
    reference = {"dewpoint_api": [["relation:r", "public.users", "SELECT"]]}
    found = {"dewpoint_api": {("relation:r", "public.users", "SELECT"),
                              ("relation:r", "public.operator_confirmations", "INSERT")}}  # fmt: skip
    assert privileges.drift(found, reference) == {
        "dewpoint_api": {"extra": [("relation:r", "public.operator_confirmations", "INSERT")], "missing": []}
    }
    assert privileges.drift({"dewpoint_api": set()}, reference) == {
        "dewpoint_api": {"extra": [], "missing": [("relation:r", "public.users", "SELECT")]}
    }
    assert privileges.drift({"dewpoint_api": {("relation:r", "public.users", "SELECT")}}, reference) == {}


def test_the_privilege_check_reports_every_right_beyond_the_allow_list_and_any_missing() -> None:
    allowed = privileges.ALLOWED
    held = set(allowed) | {("relation:r", "public.users", "SELECT")}
    assert privileges.excess(held) == {("relation:r", "public.users", "SELECT")}
    assert privileges.missing(held - {("schema", "recovery", "USAGE")}) == {("schema", "recovery", "USAGE")}


class _Connection:
    """An administrator's or an owner's connection, as `logging exercise` uses one: its lock wait seen at once."""

    wait_seen, left_behind = True, False  # what the target shows: its lock wait, a login left after a fault

    def __init__(self, user: str) -> None:
        self.user, self.statements = user, list[str]()

    async def execute(self, statement: str, *_: object) -> None:
        self.statements.append(statement)

    async def fetchval(self, statement: str, *_: object) -> object:
        if "wait_event_type" in statement:
            return self.wait_seen
        return self.left_behind and "pg_roles" in statement  # no login left to revoke

    def get_server_pid(self) -> int:
        return 4242

    def transaction(self) -> object:
        class Transaction:
            async def __aenter__(self) -> None: ...

            async def __aexit__(self, *_: object) -> None: ...

        return Transaction()

    async def close(self) -> None: ...


def _target(monkeypatch: Any, *, duplicate_refused: bool = True, wait_seen: bool = True,
            left_behind: bool = False) -> None:  # fmt: skip
    """`logging exercise`'s dependencies: a target answering each case as a correct one does (or not)."""
    made: set[str] = set()
    monkeypatch.setattr(_Connection, "wait_seen", wait_seen)
    monkeypatch.setattr(_Connection, "left_behind", left_behind)

    async def provision(c: Any, sink: Any, login: str, user_id: Any, verifier: str, *, by: str) -> None:
        recovery.checked_verifier(verifier)  # the real check: plaintext and md5 refused before any SQL
        if login.endswith("_b"):
            raise asyncpg.CheckViolationError("qualification_fault")
        if login.endswith("_c"):
            raise asyncpg.QueryCanceledError("canceling statement due to user request")
        if login in made and duplicate_refused:
            raise ValueError("provisioned before")
        made.add(login)

    async def rotate(c: Any, sink: Any, login: str, verifier: str, *, by: str) -> None:
        recovery.checked_verifier(verifier)
        if login not in made:
            raise ValueError("not an unrevoked recovery login")
        if rotate.calls:  # type: ignore[attr-defined]  # the second rotation: cancelled
            raise asyncpg.QueryCanceledError("canceling statement due to user request")
        rotate.calls += 1  # type: ignore[attr-defined]

    rotate.calls = 0  # type: ignore[attr-defined]
    target = SimpleNamespace(user="dewpoint_owner")
    monkeypatch.setattr(recovery, "server", lambda dsn, user: target)
    monkeypatch.setattr(recovery, "connect", lambda t, p: asyncio.sleep(0, _Connection(t.user)))
    monkeypatch.setattr(recovery, "required_sink", lambda settings: None)
    monkeypatch.setattr(recovery, "provision", provision)
    monkeypatch.setattr(recovery, "rotate", rotate)
    monkeypatch.setattr(log_search, "get_settings", lambda: None)
    for name in ("ADMIN", "OWNER", "VERIFIER"):
        monkeypatch.setenv(f"DEWPOINT_QUALIFICATION_{name}_PASSWORD", "violet-otter-canyon-42")


def _exercised(tmp_path: Path) -> Record:
    record = Record(tmp_path / "logging.jsonl", "logging exercise", "TQ-1")
    args = argparse.Namespace(admin_dsn="a", owner_dsn="o", user_id=uuid.uuid4())
    markers = asyncio.run(log_search._exercise(args, record))
    assert set(markers) >= {"1", "3", "4", "5", "6"}
    return record


def test_logging_exercise_passes_only_when_each_case_took_its_own_path(tmp_path: Path, monkeypatch: Any) -> None:
    _target(monkeypatch)
    assert _exercised(tmp_path).finished() == 0


def test_logging_exercise_fails_when_a_case_didnt_take_its_path(tmp_path: Path, monkeypatch: Any) -> None:
    """The final review's finding 1: a duplicate provisioned twice never reached its refusal, so the search after
    would prove nothing about that path."""
    _target(monkeypatch, duplicate_refused=False)
    record = _exercised(tmp_path)
    assert record.finished() == 1 and any("3 duplicate name" in f for f in record.failures)


def test_a_cancellation_counts_only_once_the_lock_wait_was_seen(tmp_path: Path, monkeypatch: Any) -> None:
    _target(monkeypatch, wait_seen=False)
    record = _exercised(tmp_path)
    assert record.finished() == 1 and {"5 cancelled: QueryCanceledError", "6 cancelled: QueryCanceledError"} <= set(
        record.failures
    )


def test_a_fault_that_left_its_login_behind_fails(tmp_path: Path, monkeypatch: Any) -> None:
    _target(monkeypatch, left_behind=True)
    record = _exercised(tmp_path)
    assert record.finished() == 1 and "4: rolled back, no login left" in record.failures


def _search(tmp_path: Path, markers: dict[str, str], *paths: Path) -> subprocess.CompletedProcess[str]:
    (tmp_path / "markers.json").write_text(json.dumps(markers))
    return subprocess.run([sys.executable, "-m", "tests.qualification.logging", "search", "--markers",
                           str(tmp_path / "markers.json"), "--out", str(tmp_path / "out.jsonl"), *map(str, paths)],
                          cwd=BACKEND, env={**os.environ, "DEWPOINT_QUALIFICATION_APPROVED": "TQ-1"},
                          capture_output=True, text=True, timeout=60, check=False)  # fmt: skip


def test_the_log_search_passes_only_with_every_marker_and_a_log_actually_read(tmp_path: Path) -> None:
    """The owner's final-gate ruling: an empty or partial markers file, a path that isn't there, or nothing readable
    under the paths given never pass."""
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "postgresql.log").write_text("LOG:  connection received\n")
    complete = {case: log_search.marker()[1] for case in log_search.MARKER_CASES}
    assert _search(tmp_path, complete, logs).returncode == 0
    assert _search(tmp_path, {}, logs).returncode == 1  # no marker: nothing searched for
    partial = dict(list(complete.items())[1:])
    assert _search(tmp_path, partial, logs).returncode == 1
    assert _search(tmp_path, complete, logs, tmp_path / "not-there").returncode == 1  # a path missing
    (tmp_path / "empty").mkdir()
    assert _search(tmp_path, complete, tmp_path / "empty").returncode == 1  # no readable file
    complete["5"] = ""
    assert _search(tmp_path, complete, logs).returncode == 1  # an empty marker matches everything: refused


def test_clock_skew_refuses_a_negative_margin(tmp_path: Path) -> None:
    run = subprocess.run([sys.executable, "-m", "tests.qualification.clock_skew", "--dsn", "postgresql://x@h/d",
                          "--rounds", "3", "--margin-ms", "-1", "--out", str(tmp_path / "out.jsonl")],
                         cwd=BACKEND, env={**os.environ, "DEWPOINT_QUALIFICATION_APPROVED": "TQ-1"},
                         capture_output=True, text=True, timeout=60, check=False)  # fmt: skip
    assert run.returncode == 2 and "--margin-ms" in run.stderr
