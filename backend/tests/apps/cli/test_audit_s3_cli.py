# SPDX-License-Identifier: Apache-2.0
"""The audit commands with D6's S3 sink (#3; 2b-4b M4): `audit anchor` (and `prune`) write to the bucket once
`DEWPOINT_AUDIT_S3_BUCKET` is set; `audit verify` reads every version there and the bucket's default retention, with
the public keys alone (`DEWPOINT_AUDIT_PUBLIC_KEYS`, by key id), never the signing key; `audit monitor` keeps its
roster and high-water marks in files off the database host and alerts. Against an in-memory bucket here; a real
server is D6's proof."""

import asyncio
import base64
import json
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat, PublicFormat
from typer.testing import CliRunner

from dewpoint.apps.cli import main as cli
from dewpoint.apps.cli.main import app
from dewpoint.core.audit.s3 import anchor_key
from tests.apps.cli.test_audit_cli import _env, _seed
from tests.conftest import _url_for
from tests.core.audit.fake_s3 import FakeS3

BUCKET = "audit-anchors"


def keys() -> tuple[str, str]:
    private = Ed25519PrivateKey.generate()
    raw = private.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    public = private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return base64.b64encode(raw).decode(), base64.b64encode(public).decode()


def configured(monkeypatch, pg_url: str, bucket: FakeS3, **extra: str) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(cli, "_s3_client", lambda settings: bucket)
    _env(monkeypatch, _url_for(pg_url, "dewpoint_auditor"), DEWPOINT_AUDIT_S3_BUCKET=BUCKET, **extra)


def test_anchors_go_to_the_bucket_and_verify_reads_every_version(pg_url, _test_users, monkeypatch) -> None:
    asyncio.run(_seed(_url_for(pg_url, "dewpoint_api")))
    signing, public = keys()
    bucket, runner = FakeS3(), CliRunner()
    configured(monkeypatch, pg_url, bucket, DEWPOINT_AUDIT_SIGNING_KEY_B64=signing)
    anchored = runner.invoke(app, ["audit", "anchor"])
    assert anchored.exit_code == 0 and "anchored 1 scope head(s)" in anchored.output, anchored.output
    assert len(bucket.versions) == 1
    configured(monkeypatch, pg_url, bucket, DEWPOINT_AUDIT_PUBLIC_KEYS=json.dumps({"audit-1": public}))
    verified = runner.invoke(app, ["audit", "verify"])  # the verifier: public keys only, no signing key
    assert verified.exit_code == 0, verified.output
    [anchor] = bucket.versions
    bucket.delete_object(Bucket=BUCKET, Key=anchor.key)
    deleted = runner.invoke(app, ["audit", "verify"])
    assert deleted.exit_code == 1 and f"{anchor.key}: deleted (a delete marker)" in deleted.output


def test_verify_refuses_a_bucket_whose_default_retention_is_too_short(pg_url, _test_users, monkeypatch) -> None:
    asyncio.run(_seed(_url_for(pg_url, "dewpoint_api")))
    signing, _ = keys()
    bucket = FakeS3(days=30)
    configured(monkeypatch, pg_url, bucket, DEWPOINT_AUDIT_SIGNING_KEY_B64=signing)
    assert CliRunner().invoke(app, ["audit", "anchor"]).exit_code == 0
    verified = CliRunner().invoke(app, ["audit", "verify"])
    assert verified.exit_code == 1
    assert (
        "the bucket's default retention, 30 days, is less than 436 (audit retention, backups and a day for "
        "timestamp precision)"
    ) in verified.output


def test_the_monitor_is_set_up_stays_quiet_when_healthy_and_alerts(pg_url, _test_users, monkeypatch,
                                                                   tmp_path: Path) -> None:  # fmt: skip
    asyncio.run(_seed(_url_for(pg_url, "dewpoint_api")))
    signing, public = keys()
    bucket, runner = FakeS3(), CliRunner()
    configured(monkeypatch, pg_url, bucket, DEWPOINT_AUDIT_SIGNING_KEY_B64=signing)
    assert runner.invoke(app, ["audit", "anchor"]).exit_code == 0
    roster, state = tmp_path / "roster.json", tmp_path / "state.json"
    roster.write_text(json.dumps({"default_cadence_minutes": 30, "scopes": {}}))
    configured(monkeypatch, pg_url, bucket, DEWPOINT_AUDIT_PUBLIC_KEYS=json.dumps({"audit-1": public}))
    watched = ["audit", "monitor", "--roster", str(roster), "--state", str(state)]
    first = runner.invoke(app, [*watched, "--init"])
    assert first.exit_code == 0 and state.exists(), first.output
    assert runner.invoke(app, watched).exit_code == 0
    [anchor] = bucket.versions
    bucket.delete_object(Bucket=BUCKET, Key=anchor.key)
    alerted = runner.invoke(app, watched)
    assert alerted.exit_code == 1 and f"ALERT audit_verify_failed: {anchor.key}: deleted" in alerted.output
    state.unlink()
    lost = runner.invoke(app, watched)
    assert lost.exit_code == 1 and "ALERT audit_monitor_state_lost" in lost.output
    # the review's M5: it stays alerted on, the state not made afresh, until someone sets it up again knowingly
    assert not state.exists()
    still = runner.invoke(app, watched)
    assert still.exit_code == 1 and "ALERT audit_monitor_state_lost" in still.output


def test_the_monitor_needs_the_bucket(pg_url, _test_users, monkeypatch, tmp_path: Path) -> None:
    _env(monkeypatch, _url_for(pg_url, "dewpoint_auditor"))
    roster = tmp_path / "roster.json"
    roster.write_text(json.dumps({"default_cadence_minutes": 30}))
    refused = CliRunner().invoke(app, ["audit", "monitor", "--roster", str(roster), "--state", str(tmp_path / "s")])
    assert refused.exit_code == 2 and "DEWPOINT_AUDIT_S3_BUCKET" in refused.output


def test_an_anchor_key_names_its_scope_and_sequence() -> None:
    assert anchor_key("p/", "platform", 12) == "p/anchors/platform/00000000000000000012.json"
