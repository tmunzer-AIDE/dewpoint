# SPDX-License-Identifier: Apache-2.0
"""D6's off-host anchor sink (#3; 2b-4b M4): an S3 bucket with Object Lock in compliance mode.

- **The writer** (`S3AnchorSink`), with the anchor service's own put-only credentials, held off the database host:
  one object per anchor, keyed by its scope and sequence (`anchor_key`), written once. Its put is conditional
  (`If-None-Match: *`), so an anchor retried after a crash between the put and the database's record of it is refused
  as already there, and adds no second version. It sets no retention: the bucket's compliance-mode default applies.
- **The reader** (`read_anchors`), with read-only credentials: every version and delete marker under the anchors'
  prefix, across every page of the listing. A delete marker, a second version, a version not in compliance mode or
  kept less than the audit retention and backup periods require are each a problem. Each anchor's first version is
  the anchor of record.
- **The bucket** (`bucket_problems`): Object Lock on, its default retention in compliance mode and at least those
  periods plus a day (D6.9, against the settings in force): a server dates a version's lock and its write apart by
  milliseconds, and each version's lock is checked exactly against the periods.

Whether a real server behaves so is D6's proof (tests/proofs/d6), on the pinned MinIO, and on the owner's bucket
before readiness."""

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from botocore.exceptions import ClientError
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from dewpoint.core.audit.anchor import signed_message

ANCHORS = "anchors/"
PAGE = 1000  # S3's own maximum keys a listing page
# A server dates a version's lock and its last-modified time apart (by milliseconds, at the write), and a bucket's
# default retention is in whole days: the bucket keeps this much more than the periods, so the exact check below holds
MARGIN_DAYS = 1


def anchor_key(prefix: str, scope: str, seq: int) -> str:
    return f"{prefix}{ANCHORS}{scope}/{seq:020d}.json"


class S3AnchorSink:
    """The writer: put-only credentials, a signing key and its id, both held off the database host."""

    name = "s3"

    def __init__(self, client: Any, bucket: str, prefix: str, private_key: Ed25519PrivateKey, key_id: str) -> None:
        self._client, self.bucket, self.prefix, self._key, self.key_id = client, bucket, prefix, private_key, key_id

    def write(self, scope: str, seq: int, hash_: bytes) -> str:
        at = datetime.now(UTC).isoformat()
        hash_hex = hash_.hex()
        sig = self._key.sign(signed_message(scope, seq, hash_hex, at, self.key_id)).hex()
        entry = {"scope": scope, "seq": seq, "hash": hash_hex, "at": at, "kid": self.key_id, "sig": sig}
        key = anchor_key(self.prefix, scope, seq)
        try:
            self._client.put_object(Bucket=self.bucket, Key=key, Body=json.dumps(entry, sort_keys=True).encode(),
                                    ContentType="application/json", IfNoneMatch="*")  # fmt: skip
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") != "PreconditionFailed":
                raise
            # written by an earlier attempt of this anchor: the version of record stays the first
        return f"s3://{self.bucket}/{key}"


@dataclass
class Listing:
    entries: list[dict[str, Any]] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)


def _versions(client: Any, bucket: str, prefix: str, page: int) -> tuple[dict[str, list[dict[str, Any]]], set[str]]:
    versions: dict[str, list[dict[str, Any]]] = {}
    markers: set[str] = set()
    after: dict[str, str] = {}
    while True:
        answer = client.list_object_versions(Bucket=bucket, Prefix=prefix + ANCHORS, MaxKeys=page, **after)
        for version in answer.get("Versions", []):
            versions.setdefault(version["Key"], []).append(version)
        markers.update(marker["Key"] for marker in answer.get("DeleteMarkers", []))
        if not answer.get("IsTruncated"):
            return versions, markers
        after = {"KeyMarker": answer["NextKeyMarker"], "VersionIdMarker": answer.get("NextVersionIdMarker", "")}


def _lock_problem(client: Any, bucket: str, key: str, version: dict[str, Any], kept: timedelta) -> str | None:
    try:
        retention = client.get_object_retention(Bucket=bucket, Key=key, VersionId=version["VersionId"])["Retention"]
    except ClientError:
        return "not locked"
    if retention.get("Mode") != "COMPLIANCE":
        return f"not in compliance mode ({retention.get('Mode')})"
    until: datetime = retention["RetainUntilDate"]
    if until < version["LastModified"] + kept:  # exact: the invariant (the owner's ruling), the margin is the bucket's
        return f"kept until {until.date().isoformat()}, less than {kept.days} days"
    return None


def read_anchors(client: Any, bucket: str, prefix: str, *, kept: timedelta, page: int = PAGE) -> Listing:
    """Every anchor under `prefix`, its versions and delete markers across every page, each problem found; `kept`: the
    audit retention plus the backup period, each version's lock at least that from its writing."""
    found = Listing()
    versions, markers = _versions(client, bucket, prefix, page)
    for key in sorted(versions.keys() | markers):
        if key in markers:
            found.problems.append(f"{key}: deleted (a delete marker)")
        kept_versions = versions.get(key, [])
        if len(kept_versions) > 1:
            found.problems.append(f"{key}: rewritten ({len(kept_versions)} versions)")
        for version in kept_versions:
            problem = _lock_problem(client, bucket, key, version, kept)
            if problem:
                found.problems.append(f"{key}: {problem}")
        if not kept_versions:
            continue
        # the oldest: S3 lists a key's versions newest first, so on a tie of times the last listed
        first = min(enumerate(kept_versions), key=lambda iv: (iv[1]["LastModified"], -iv[0]))[1]
        body = client.get_object(Bucket=bucket, Key=key, VersionId=first["VersionId"])["Body"].read()
        try:
            entry = json.loads(body)
            scope, seq = str(entry["scope"]), int(entry["seq"])
        except (ValueError, KeyError, TypeError):
            found.problems.append(f"{key}: not an anchor")
            continue
        if anchor_key(prefix, scope, seq) != key:
            found.problems.append(f"{key}: holds another anchor ({scope}:{seq})")
            continue
        found.entries.append(entry)
    return found


def bucket_problems(client: Any, bucket: str, *, kept: timedelta) -> list[str]:
    """Whether the bucket locks every anchor long enough by default (D6.9): Object Lock on, a default retention in
    compliance mode of at least `kept`."""
    try:
        config = client.get_object_lock_configuration(Bucket=bucket)["ObjectLockConfiguration"]
    except ClientError:
        return ["the bucket has no Object Lock"]
    if config.get("ObjectLockEnabled") != "Enabled":
        return ["the bucket has no Object Lock"]
    retention = config.get("Rule", {}).get("DefaultRetention")
    if not retention:
        return ["the bucket has no default retention"]
    if retention.get("Mode") != "COMPLIANCE":
        return ["the bucket's default retention isn't in compliance mode"]
    days = int(retention.get("Days") or 365 * int(retention.get("Years") or 0))
    if days < kept.days + MARGIN_DAYS:
        return [
            f"the bucket's default retention, {days} days, is less than {kept.days + MARGIN_DAYS} (audit "
            "retention, backups and a day for timestamp precision)"
        ]
    return []
