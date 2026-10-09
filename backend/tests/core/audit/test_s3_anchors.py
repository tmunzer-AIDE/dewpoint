# SPDX-License-Identifier: Apache-2.0
"""D6's off-host anchor sink (#3; 2b-4b M4): an S3 bucket with Object Lock in compliance mode. The writer, with
put-only credentials, writes one object per anchor, keyed by its scope and sequence, never twice (a conditional put:
a retried anchor adds no second version). The verifier, with read-only ones, lists every version and delete marker
across every page and refuses a deleted or rewritten anchor, one not in compliance mode, or one kept less than the
audit retention and backup periods require. Here against an in-memory bucket; a real server's behaviour is D6's
proof, on the pinned MinIO (tests/proofs/d6)."""

import json
from datetime import timedelta

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from dewpoint.core.audit.s3 import S3AnchorSink, anchor_key, bucket_problems, read_anchors
from tests.core.audit.fake_s3 import FakeS3

BUCKET, PREFIX = "audit-anchors", "dewpoint/"
KEPT = timedelta(days=435)  # the audit retention (400) and the backup period (35) by default


def written(bucket: FakeS3, *anchors: tuple[str, int]) -> S3AnchorSink:
    sink = S3AnchorSink(bucket, BUCKET, PREFIX, Ed25519PrivateKey.generate(), "audit-1")  # type: ignore[arg-type]
    for scope, seq in anchors:
        sink.write(scope, seq, bytes([seq]) * 32)
    return sink


def test_an_anchor_is_one_object_keyed_by_its_scope_and_sequence_signed_with_its_key_id() -> None:
    bucket = FakeS3()
    ref = written(bucket, ("platform", 7)).write("tenant", 3, b"\x01" * 32)
    assert ref == f"s3://{BUCKET}/{PREFIX}anchors/tenant/00000000000000000003.json"
    [_, anchor] = bucket.versions
    entry = json.loads(anchor.body or b"")
    assert (entry["scope"], entry["seq"], entry["hash"], entry["kid"]) == ("tenant", 3, "01" * 32, "audit-1")
    assert anchor.key == anchor_key(PREFIX, "tenant", 3) and all(p["IfNoneMatch"] == "*" for p in bucket.puts)


def test_a_retried_anchor_adds_no_second_version() -> None:
    """A crash between the put and the database's record of it retries the same anchor: the conditional put is
    refused, and that's taken as written, never as a rewrite verify would fail on."""
    bucket = FakeS3()
    sink = written(bucket, ("platform", 1))
    assert (
        sink.write("platform", 1, b"\x01" * 32) == f"s3://{BUCKET}/{PREFIX}anchors/platform/00000000000000000001.json"
    )
    assert len(bucket.versions) == 1
    assert read_anchors(bucket, BUCKET, PREFIX, kept=KEPT).problems == []  # type: ignore[arg-type]


def test_untouched_anchors_are_read_back_whole() -> None:
    bucket = FakeS3()
    written(bucket, ("platform", 1), ("platform", 2), ("tenant", 1))
    found = read_anchors(bucket, BUCKET, PREFIX, kept=KEPT)  # type: ignore[arg-type]
    assert found.problems == [] and sorted((e["scope"], e["seq"]) for e in found.entries) == [
        ("platform", 1), ("platform", 2), ("tenant", 1),
    ]  # fmt: skip


def test_a_deleted_anchor_leaves_a_delete_marker_verify_refuses() -> None:
    bucket = FakeS3()
    written(bucket, ("platform", 1), ("platform", 2))
    bucket.delete_object(Bucket=BUCKET, Key=anchor_key(PREFIX, "platform", 2))
    assert read_anchors(bucket, BUCKET, PREFIX, kept=KEPT).problems == [  # type: ignore[arg-type]
        f"{anchor_key(PREFIX, 'platform', 2)}: deleted (a delete marker)",
    ]


def test_a_rewritten_anchor_is_a_second_version_verify_refuses() -> None:
    bucket = FakeS3()
    written(bucket, ("platform", 1))
    bucket.put_object(Bucket=BUCKET, Key=anchor_key(PREFIX, "platform", 1), Body=b'{"forged": true}')
    assert read_anchors(bucket, BUCKET, PREFIX, kept=KEPT).problems == [  # type: ignore[arg-type]
        f"{anchor_key(PREFIX, 'platform', 1)}: rewritten (2 versions)",
    ]


@pytest.mark.parametrize(("mode", "days", "problem"), [
    ("GOVERNANCE", 435, "not in compliance mode (GOVERNANCE)"),
    (None, None, "not locked"),
    ("COMPLIANCE", 30, "kept until 2026-11-08, less than 435 days"),
])  # fmt: skip
def test_a_version_not_locked_in_compliance_mode_for_long_enough_is_refused(mode, days, problem) -> None:
    """D6.8: the bucket's default makes every write protected; an unprotected version comes from a fixture."""
    bucket = FakeS3(mode=mode, days=days)
    written(bucket, ("platform", 1))
    assert read_anchors(bucket, BUCKET, PREFIX, kept=KEPT).problems == [  # type: ignore[arg-type]
        f"{anchor_key(PREFIX, 'platform', 1)}: {problem}",
    ]


def test_a_listing_longer_than_a_page_is_verified_whole() -> None:
    """D6.7: a tampered version on a later page is caught."""
    bucket = FakeS3()
    written(bucket, *(("platform", seq) for seq in range(1, 8)))
    bucket.delete_object(Bucket=BUCKET, Key=anchor_key(PREFIX, "platform", 7))
    found = read_anchors(bucket, BUCKET, PREFIX, kept=KEPT, page=2)  # type: ignore[arg-type]
    assert found.problems == [f"{anchor_key(PREFIX, 'platform', 7)}: deleted (a delete marker)"]
    assert len(found.entries) == 7


@pytest.mark.parametrize(("bucket", "problems"), [
    (FakeS3(), []),
    (FakeS3(days=500), []),
    (FakeS3(mode="GOVERNANCE"), ["the bucket's default retention isn't in compliance mode"]),
    (FakeS3(days=400), ["the bucket's default retention, 400 days, is less than 435 (audit retention and backups)"]),
    (FakeS3(mode=None), ["the bucket has no default retention"]),
    (FakeS3(enabled=False), ["the bucket has no Object Lock"]),
])  # fmt: skip
def test_the_buckets_default_retention_covers_the_audit_retention_and_the_backups(bucket, problems) -> None:
    """D6.9: checked against the configured periods in force, not today's defaults alone."""
    assert bucket_problems(bucket, BUCKET, kept=KEPT) == problems
