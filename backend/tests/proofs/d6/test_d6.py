# SPDX-License-Identifier: Apache-2.0
"""D6's proof (#3; 2b-4b M4): the off-host audit anchor sink on the pinned MinIO, D6.1-D6.11 as the owner approved
them (2026-10-05), after D6.0, the credentials' separation (the owner's ruling on the run request: without it, D6
stops). Each is an automated case. Opt-in: runs only when the owner authorizes it (`DEWPOINT_PROOF=d6`).

    DEWPOINT_PROOF=d6 DEWPOINT_PROOF_OUT=<file> .venv/bin/pytest -p no:cacheprovider -n 0 tests/proofs/d6

The environment: the pinned MinIO alone from deploy/temporal/compose.yaml (project dewpoint-m4), its data on tmpfs so
compliance-locked versions vanish with the container; a bucket with Object Lock and a 435-day compliance default; and
three credential sets kept apart: the anchor writer (put under anchors/ only) and the verifier (read only), each from
STS with its session policy, and MinIO's root, held by the harness alone. The audit commands run as they do in
production (`dewpoint audit anchor|verify|monitor`), with the writer's or the verifier's credentials in the standard
AWS environment. Each case uses its own key prefix, so the bucket's history of one never touches another.

Passing doesn't prove the owner's bucket: real-target acceptance reruns D6.1-D6.4 with a canary anchor there."""

import asyncio
import base64
import json
import os
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from botocore.exceptions import ClientError
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat, PublicFormat
from sqlalchemy import text
from typer.testing import CliRunner

from dewpoint.apps.cli.main import app
from dewpoint.core.audit.anchor import signed_message
from dewpoint.core.audit.s3 import S3AnchorSink, anchor_key, bucket_problems, read_anchors
from dewpoint.core.db import make_engine, make_sessionmaker
from tests.apps.cli.test_audit_cli import _env, _seed
from tests.conftest import _url_for
from tests.proofs import environment
from tests.proofs.conftest import gate, record

pytestmark = [gate("d6")]

BUCKET, UNLOCKED_BUCKET = environment.BUCKET, "d6-no-default"
KEPT = timedelta(days=environment.RETENTION_DAYS)


class Lab:
    def __init__(self, run: environment.Run) -> None:
        self.run = run
        self.root = environment.s3(root=run)
        # each case writes under its own prefix: the writer may put under any prefix's anchors/, nothing else
        self.writer = environment.assume(run, "anchor-writer", BUCKET, "*/")
        self.verifier = environment.assume(run, "verifier", BUCKET, "")
        signing = Ed25519PrivateKey.generate()
        self.signing_b64 = base64.b64encode(signing.private_bytes(Encoding.Raw, PrivateFormat.Raw,
                                                                  NoEncryption())).decode()  # fmt: skip
        self.signing = signing
        self.public_b64 = base64.b64encode(signing.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)).decode()


@pytest.fixture(scope="module")
def lab(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Lab]:
    run = environment.prepare(tmp_path_factory.mktemp("d6") / "run")
    environment.run_compose(run, "mtls", "up", "-d", "minio")
    try:
        environment.wait_for_s3(run)
        version = environment.run_compose(run, "mtls", "exec", "-T", "minio", "minio", "--version")
        record({"environment": "d6", "minio_version": version.strip()})
        root = environment.s3(root=run)
        environment.make_bucket(root, BUCKET)
        environment.make_bucket(root, UNLOCKED_BUCKET, days=None)
        try:
            lab = Lab(run)
        except ClientError as e:
            pytest.fail(
                f"MinIO refused STS AssumeRole from its root credentials ({e.response['Error']['Code']}): "
                "the writer's and verifier's credentials need another way, a decision for the owner"
            )
        yield lab
    finally:
        environment.run_compose(run, "mtls", "down", "-v", "--remove-orphans")


def _as(monkeypatch: pytest.MonkeyPatch, credentials: dict[str, str]) -> None:
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", credentials["AccessKeyId"])
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", credentials["SecretAccessKey"])
    monkeypatch.setenv("AWS_SESSION_TOKEN", credentials["SessionToken"])


def _configure(monkeypatch: pytest.MonkeyPatch, pg_url: str, lab: Lab, prefix: str, *, writer: bool,
               **extra: str) -> None:  # fmt: skip
    """The CLI as the anchor job (`writer`) or as the verifier/monitor: the auditor's read-only database role, the
    bucket, and only that role's credentials and key."""
    keys = (
        {"DEWPOINT_AUDIT_SIGNING_KEY_B64": lab.signing_b64}
        if writer
        else {"DEWPOINT_AUDIT_PUBLIC_KEYS": json.dumps({"audit-1": lab.public_b64})}
    )
    _env(monkeypatch, _url_for(pg_url, "dewpoint_auditor"), DEWPOINT_AUDIT_S3_BUCKET=BUCKET,
         DEWPOINT_AUDIT_S3_PREFIX=prefix, DEWPOINT_AUDIT_S3_ENDPOINT_URL=environment.S3_ENDPOINT,
         DEWPOINT_AUDIT_S3_REGION=environment.REGION, **keys, **extra)  # fmt: skip
    _as(monkeypatch, lab.writer if writer else lab.verifier)


def _anchor(monkeypatch: pytest.MonkeyPatch, pg_url: str, lab: Lab, prefix: str) -> None:
    _configure(monkeypatch, pg_url, lab, prefix, writer=True)
    done = CliRunner().invoke(app, ["audit", "anchor"])
    assert done.exit_code == 0, done.output


def _verify(monkeypatch: pytest.MonkeyPatch, pg_url: str, lab: Lab, prefix: str, **extra: str) -> Any:
    _configure(monkeypatch, pg_url, lab, prefix, writer=False, **extra)
    return CliRunner().invoke(app, ["audit", "verify"])


def _versions(lab: Lab, key: str) -> list[dict[str, Any]]:
    return [v for v in lab.root.list_object_versions(Bucket=BUCKET, Prefix=key).get("Versions", []) if v["Key"] == key]


def _only_anchor(lab: Lab, prefix: str) -> dict[str, Any]:
    [version] = lab.root.list_object_versions(Bucket=BUCKET, Prefix=prefix)["Versions"]
    return version


def _prefix() -> str:
    return f"d6-{uuid.uuid4().hex[:8]}/"


async def _sql(pg_url: str, statement: str, params: dict[str, Any] | None = None) -> None:
    """As the database's owner, audit triggers bypassed: a privileged rewrite, the kind verify must catch."""
    engine = make_engine(pg_url)
    try:
        async with make_sessionmaker(engine)() as s, s.begin():
            await s.execute(text("SET LOCAL session_replication_role = replica"))
            await s.execute(text(statement), params or {})
    finally:
        await engine.dispose()


def test_d6_0_the_writer_and_the_verifier_are_demonstrably_apart(lab: Lab) -> None:
    """The owner's ruling on the run request: if STS can't give demonstrably separate put-only and read-only
    credentials, D6 stops here. The writer puts under anchors/ and nothing else: no read, no listing, no delete, no
    write outside its prefix. The verifier reads and lists, and writes and deletes nothing."""
    writer, verifier = environment.s3(lab.writer), environment.s3(lab.verifier)
    key = f"{_prefix()}anchors/d6-0/{uuid.uuid4().hex}.json"
    writer.put_object(Bucket=BUCKET, Key=key, Body=b"{}", IfNoneMatch="*")
    refused = {
        "writer get": lambda: writer.get_object(Bucket=BUCKET, Key=key),
        "writer list": lambda: writer.list_object_versions(Bucket=BUCKET, Prefix=key),
        "writer delete": lambda: writer.delete_object(Bucket=BUCKET, Key=key),
        "writer put outside anchors/": lambda: writer.put_object(Bucket=BUCKET, Key=f"elsewhere/{uuid.uuid4().hex}",
                                                                  Body=b"{}"),
        "verifier put": lambda: verifier.put_object(Bucket=BUCKET, Key=f"{key}.forged", Body=b"{}"),
        "verifier delete": lambda: verifier.delete_object(Bucket=BUCKET, Key=key),
        # a later date than the lock already holds: MinIO checks a retention's date before its permission
        # (R2's first run: "now" answered MalformedXML), so only a valid request shows the verifier can't change it
        "verifier retention": lambda: verifier.put_object_retention(
            Bucket=BUCKET, Key=key,
            Retention={"Mode": "COMPLIANCE", "RetainUntilDate": datetime.now(UTC) + timedelta(days=500)}),
    }  # fmt: skip
    for what, call in refused.items():
        with pytest.raises(ClientError) as denied:
            call()
        assert denied.value.response["Error"]["Code"] == "AccessDenied", what
    assert verifier.get_object(Bucket=BUCKET, Key=key)["Body"].read() == b"{}"
    assert [v["Key"] for v in verifier.list_object_versions(Bucket=BUCKET, Prefix=key)["Versions"]] == [key]


def test_d6_1_a_written_anchor_is_a_locked_version(pg_url, _test_users, monkeypatch, lab: Lab) -> None:
    asyncio.run(_seed(_url_for(pg_url, "dewpoint_api")))
    prefix = _prefix()
    _anchor(monkeypatch, pg_url, lab, prefix)
    version = _only_anchor(lab, prefix)
    retention = environment.s3(lab.verifier).get_object_retention(
        Bucket=BUCKET, Key=version["Key"], VersionId=version["VersionId"]
    )["Retention"]
    assert retention["Mode"] == "COMPLIANCE"
    assert abs(retention["RetainUntilDate"] - (version["LastModified"] + KEPT)) < timedelta(days=1)


def test_d6_2_deleting_the_version_is_refused_to_the_writer_and_to_root(pg_url, _test_users, monkeypatch,
                                                                        lab: Lab) -> None:  # fmt: skip
    asyncio.run(_seed(_url_for(pg_url, "dewpoint_api")))
    prefix = _prefix()
    _anchor(monkeypatch, pg_url, lab, prefix)
    version = _only_anchor(lab, prefix)
    # the refusal is the property, and the version still there after it; the code MinIO gives is recorded, not
    # assumed (R2's rerun: a locked version's delete answered InvalidRequest, where the test had assumed AccessDenied)
    for who, client in (("writer", environment.s3(lab.writer)), ("root", lab.root)):
        with pytest.raises(ClientError) as refused:
            client.delete_object(Bucket=BUCKET, Key=version["Key"], VersionId=version["VersionId"])
        record({"environment": "d6", "case": "d6.2 refusal", "who": who,
                "code": refused.value.response["Error"]["Code"]})  # fmt: skip
    assert [v["VersionId"] for v in _versions(lab, version["Key"])] == [version["VersionId"]]


def test_d6_3_shortening_or_changing_the_lock_is_refused(pg_url, _test_users, monkeypatch, lab: Lab) -> None:
    asyncio.run(_seed(_url_for(pg_url, "dewpoint_api")))
    prefix = _prefix()
    _anchor(monkeypatch, pg_url, lab, prefix)
    version = _only_anchor(lab, prefix)
    for retention in ({"Mode": "COMPLIANCE", "RetainUntilDate": datetime.now(UTC) + timedelta(days=1)},
                      {"Mode": "GOVERNANCE", "RetainUntilDate": version["LastModified"] + KEPT}):  # fmt: skip
        with pytest.raises(ClientError):
            lab.root.put_object_retention(Bucket=BUCKET, Key=version["Key"], VersionId=version["VersionId"],
                                          Retention=retention, BypassGovernanceRetention=True)  # fmt: skip
    kept = lab.root.get_object_retention(Bucket=BUCKET, Key=version["Key"], VersionId=version["VersionId"])
    assert kept["Retention"]["Mode"] == "COMPLIANCE"


def test_d6_4_a_plain_delete_adds_a_marker_and_verify_fails(pg_url, _test_users, monkeypatch, lab: Lab) -> None:
    asyncio.run(_seed(_url_for(pg_url, "dewpoint_api")))
    prefix = _prefix()
    _anchor(monkeypatch, pg_url, lab, prefix)
    assert _verify(monkeypatch, pg_url, lab, prefix).exit_code == 0
    key = _only_anchor(lab, prefix)["Key"]
    assert lab.root.delete_object(Bucket=BUCKET, Key=key).get("DeleteMarker") is True
    failed = _verify(monkeypatch, pg_url, lab, prefix)
    assert failed.exit_code == 1 and f"{key}: deleted (a delete marker)" in failed.output


def test_d6_5_rewriting_a_key_adds_a_version_and_verify_fails(pg_url, _test_users, monkeypatch, lab: Lab) -> None:
    asyncio.run(_seed(_url_for(pg_url, "dewpoint_api")))
    prefix = _prefix()
    _anchor(monkeypatch, pg_url, lab, prefix)
    key = _only_anchor(lab, prefix)["Key"]
    # the writer's retry after a crash between its put and the database's record: refused as already there
    written = json.loads(lab.root.get_object(Bucket=BUCKET, Key=key)["Body"].read())
    sink = S3AnchorSink(environment.s3(lab.writer), BUCKET, prefix, lab.signing, "audit-1")
    sink.write(written["scope"], written["seq"], bytes.fromhex(written["hash"]))
    assert len(_versions(lab, key)) == 1
    lab.root.put_object(Bucket=BUCKET, Key=key, Body=b'{"forged": true}')
    failed = _verify(monkeypatch, pg_url, lab, prefix)
    assert failed.exit_code == 1 and f"{key}: rewritten (2 versions)" in failed.output


def _forge(lab: Lab, prefix: str, scope: str, seq: int, hash_hex: str, *, key: Ed25519PrivateKey) -> None:
    """An anchor written with root credentials, signed by `key`."""
    at = datetime.now(UTC).isoformat()
    sig = key.sign(signed_message(scope, seq, hash_hex, at, "audit-1")).hex()
    body = {"scope": scope, "seq": seq, "hash": hash_hex, "at": at, "kid": "audit-1", "sig": sig}
    lab.root.put_object(Bucket=BUCKET, Key=anchor_key(prefix, scope, seq), Body=json.dumps(body).encode())


async def _heads(pg_url: str) -> dict[str, tuple[int, str]]:
    """Each scope's newest entry: its seq and hash."""
    engine = make_engine(pg_url)
    try:
        async with make_sessionmaker(engine)() as s:
            rows = await s.execute(text("select distinct on (scope) scope, seq, hash from audit_log "
                                        "order by scope, seq desc"))  # fmt: skip
            return {str(scope): (int(seq), bytes(h).hex()) for scope, seq, h in rows.all()}
    finally:
        await engine.dispose()


def _anchored_then_another(monkeypatch: pytest.MonkeyPatch, pg_url: str, lab: Lab, prefix: str) -> tuple[str, int, str]:
    """A scope anchored at `prefix`, then another scope's entry, not anchored: the one a forged anchor names."""
    api = _url_for(pg_url, "dewpoint_api")
    asyncio.run(_seed(api))
    _anchor(monkeypatch, pg_url, lab, prefix)
    before = asyncio.run(_heads(pg_url))
    asyncio.run(_seed(api))
    [(scope, (seq, hash_hex))] = [(k, v) for k, v in asyncio.run(_heads(pg_url)).items() if k not in before]
    return scope, seq, hash_hex


# D6.6: each tampering alone, each in its own case (the database is emptied between cases)


def test_d6_6a_verify_passes_on_an_untouched_sequence(pg_url, _test_users, monkeypatch, lab: Lab) -> None:
    asyncio.run(_seed(_url_for(pg_url, "dewpoint_api")))
    prefix = _prefix()
    _anchor(monkeypatch, pg_url, lab, prefix)
    passed = _verify(monkeypatch, pg_url, lab, prefix)
    assert passed.exit_code == 0, passed.output


def test_d6_6b_verify_fails_on_a_bad_signature(pg_url, _test_users, monkeypatch, lab: Lab) -> None:
    prefix = _prefix()
    scope, seq, hash_hex = _anchored_then_another(monkeypatch, pg_url, lab, prefix)
    _forge(lab, prefix, scope, seq, hash_hex, key=Ed25519PrivateKey.generate())
    failed = _verify(monkeypatch, pg_url, lab, prefix)
    assert failed.exit_code == 1 and f"{scope}:{seq}: bad anchor signature" in failed.output
    assert "hash mismatch" not in failed.output and "chain broken" not in failed.output


def test_d6_6c_verify_fails_on_a_hash_mismatch(pg_url, _test_users, monkeypatch, lab: Lab) -> None:
    prefix = _prefix()
    scope, seq, _ = _anchored_then_another(monkeypatch, pg_url, lab, prefix)
    _forge(lab, prefix, scope, seq, "00" * 32, key=lab.signing)
    failed = _verify(monkeypatch, pg_url, lab, prefix)
    assert failed.exit_code == 1 and f"{scope}:{seq}: hash mismatch with external anchor" in failed.output
    assert "bad anchor signature" not in failed.output and "chain broken" not in failed.output


def test_d6_6d_verify_fails_on_a_missing_anchor(pg_url, _test_users, monkeypatch, lab: Lab) -> None:
    """The database records a checkpoint whose anchor isn't in the bucket (written elsewhere, then withheld)."""
    prefix = _prefix()
    api = _url_for(pg_url, "dewpoint_api")
    asyncio.run(_seed(api))
    _anchor(monkeypatch, pg_url, lab, prefix)
    before = asyncio.run(_heads(pg_url))
    asyncio.run(_seed(api))
    _anchor(monkeypatch, pg_url, lab, _prefix())  # the new head's checkpoint, its anchor not under `prefix`
    [scope] = [k for k in asyncio.run(_heads(pg_url)) if k not in before]
    failed = _verify(monkeypatch, pg_url, lab, prefix)
    assert failed.exit_code == 1 and f"{scope}:1: checkpoint not among the external anchors" in failed.output


def test_d6_6e_verify_fails_on_a_chain_break(pg_url, _test_users, monkeypatch, lab: Lab) -> None:
    asyncio.run(_seed(_url_for(pg_url, "dewpoint_api")))
    prefix = _prefix()
    _anchor(monkeypatch, pg_url, lab, prefix)
    [(scope, (seq, _))] = list(asyncio.run(_heads(pg_url)).items())
    asyncio.run(_sql(pg_url, "update audit_log set action = 'member.remove' where scope = :s and seq = :q",
                     {"s": scope, "q": seq}))  # fmt: skip
    failed = _verify(monkeypatch, pg_url, lab, prefix)
    assert failed.exit_code == 1 and f"{scope}: chain broken at seq {seq}" in failed.output


def test_d6_7_a_listing_longer_than_a_page_is_verified_whole(lab: Lab) -> None:
    prefix, page, count = _prefix(), 50, 120  # three pages
    sink = S3AnchorSink(environment.s3(lab.writer), BUCKET, prefix, lab.signing, "audit-1")
    for seq in range(1, count + 1):
        sink.write("platform", seq, os.urandom(32))
    clean = read_anchors(environment.s3(lab.verifier), BUCKET, prefix, kept=KEPT, page=page)
    assert len(clean.entries) == count and clean.problems == []
    last = anchor_key(prefix, "platform", count)  # on the last page
    lab.root.put_object(Bucket=BUCKET, Key=last, Body=b"{}")
    tampered = read_anchors(environment.s3(lab.verifier), BUCKET, prefix, kept=KEPT, page=page)
    assert tampered.problems == [f"{last}: rewritten (2 versions)"]


def test_d6_8_every_versions_lock_is_checked(lab: Lab) -> None:
    """An unprotected version can't come from the writer while the default applies, so from the fixture bucket (Object
    Lock, no default retention), and from root writing a governance-mode and a too-short compliance version."""
    prefix = _prefix()
    unlocked = S3AnchorSink(lab.root, UNLOCKED_BUCKET, prefix, lab.signing, "audit-1")
    unlocked.write("platform", 1, os.urandom(32))
    found = read_anchors(lab.root, UNLOCKED_BUCKET, prefix, kept=KEPT)
    assert found.problems == [f"{anchor_key(prefix, 'platform', 1)}: not locked"]
    assert bucket_problems(lab.root, UNLOCKED_BUCKET, kept=KEPT) == ["the bucket has no default retention"]
    for seq, mode, until, problem in (
        (2, "GOVERNANCE", datetime.now(UTC) + KEPT, "not in compliance mode (GOVERNANCE)"),
        (3, "COMPLIANCE", datetime.now(UTC) + timedelta(days=1), "less than 435 days"),
    ):  # fmt: skip
        lab.root.put_object(Bucket=UNLOCKED_BUCKET, Key=anchor_key(prefix, "platform", seq), Body=b"{}",
                            ObjectLockMode=mode, ObjectLockRetainUntilDate=until)  # fmt: skip
        problems = read_anchors(lab.root, UNLOCKED_BUCKET, prefix, kept=KEPT).problems
        assert any(p.startswith(anchor_key(prefix, "platform", seq)) and problem in p for p in problems), problems


def test_d6_9_the_default_retention_is_checked_against_the_configured_periods(pg_url, _test_users, monkeypatch,
                                                                              lab: Lab) -> None:  # fmt: skip
    asyncio.run(_seed(_url_for(pg_url, "dewpoint_api")))
    prefix = _prefix()
    _anchor(monkeypatch, pg_url, lab, prefix)
    assert _verify(monkeypatch, pg_url, lab, prefix).exit_code == 0  # 400 + 35 = 435: the bucket's default
    longer = _verify(monkeypatch, pg_url, lab, prefix, DEWPOINT_BACKUP_RETENTION_DAYS="40")
    assert longer.exit_code == 1
    assert "the bucket's default retention, 435 days, is less than 440" in longer.output


def _monitor(monkeypatch: pytest.MonkeyPatch, pg_url: str, lab: Lab, prefix: str, roster: dict[str, Any],
             state: Path, *, init: bool = False) -> Any:  # fmt: skip
    roster_file = state.parent / "roster.json"
    roster_file.write_text(json.dumps(roster))
    _configure(monkeypatch, pg_url, lab, prefix, writer=False)
    args = ["audit", "monitor", "--roster", str(roster_file), "--state", str(state)] + (["--init"] if init else [])
    return CliRunner().invoke(app, args)


def test_d6_10_the_monitor_alerts_on_a_missing_scope_and_a_withheld_anchor(
    pg_url, _test_users, monkeypatch, lab: Lab, tmp_path: Path
) -> None:
    asyncio.run(_seed(_url_for(pg_url, "dewpoint_api")))
    prefix, state = _prefix(), tmp_path / "state.json"
    _anchor(monkeypatch, pg_url, lab, prefix)
    healthy = {"default_cadence_minutes": 30, "scopes": {}}
    assert _monitor(monkeypatch, pg_url, lab, prefix, healthy, state, init=True).exit_code == 0
    assert _monitor(monkeypatch, pg_url, lab, prefix, healthy, state).exit_code == 0  # quiet when healthy
    missing = {"default_cadence_minutes": 30, "scopes": {"t-gone": 30}}
    alerted = _monitor(monkeypatch, pg_url, lab, prefix, missing, state)
    assert alerted.exit_code == 1 and "ALERT audit_scope_missing t-gone" in alerted.output
    asyncio.run(_seed(_url_for(pg_url, "dewpoint_api")))  # an entry the anchor job withholds
    overdue = {"default_cadence_minutes": 0, "scopes": {}}
    alerted = _monitor(monkeypatch, pg_url, lab, prefix, overdue, state)
    assert alerted.exit_code == 1 and "ALERT audit_anchor_overdue" in alerted.output


def test_d6_11_the_monitor_alerts_on_a_lost_or_rolled_back_mark(pg_url, _test_users, monkeypatch, lab: Lab,
                                                                tmp_path: Path) -> None:  # fmt: skip
    asyncio.run(_seed(_url_for(pg_url, "dewpoint_api")))
    prefix, state = _prefix(), tmp_path / "state.json"
    _anchor(monkeypatch, pg_url, lab, prefix)
    roster = {"default_cadence_minutes": 30, "scopes": {}}
    assert _monitor(monkeypatch, pg_url, lab, prefix, roster, state, init=True).exit_code == 0
    marks = json.loads(state.read_text())
    state.write_text(json.dumps({scope: seq + 5 for scope, seq in marks.items()}))  # a mark past the bucket's newest
    alerted = _monitor(monkeypatch, pg_url, lab, prefix, roster, state)
    assert alerted.exit_code == 1 and "ALERT audit_high_water_rolled_back" in alerted.output
    state.unlink()
    alerted = _monitor(monkeypatch, pg_url, lab, prefix, roster, state)
    assert alerted.exit_code == 1 and "ALERT audit_monitor_state_lost" in alerted.output
