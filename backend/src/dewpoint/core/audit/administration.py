# SPDX-License-Identifier: Apache-2.0
"""The database's administration, recorded off its host (2b-4b M4 recovery, task 7; design revision 9 §1, the owner's
ruling on revision 8: the administrator's and the migration run's audit must be available outside the database they
control).

- **The writer** (`AdministrationSink`): D6's bucket, under `database-administration/` (after the deployment's audit
  prefix), with an identity of its own: put-only on that prefix, not the anchor writer's. Each action on a prescribed
  path (a recovery login provisioned, rotated or revoked; a migration) writes its intent before it acts, which stops
  it if the write fails, and its outcome after. A record is one object, written once (`If-None-Match: *`): a second
  write of it is refused, never a second version. A record holds no secret: a verifier's fingerprint, never the
  verifier.
- **The reader** (`read_records`): the monitor's read-only identity, every version under the prefix; a record deleted
  or rewritten is a problem, and each record's first version is the one of record.

A record covers a prescribed path's action only: an administrator acting outside those paths is the trusted exception
(revision 8), seen only as persistent drift (`monitor.drift`)."""

import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from botocore.exceptions import ClientError

ADMINISTRATION = "database-administration/"
PAGE = 1000
_SECRET_KEY = re.compile(r"password|secret|verifier$|token|credential", re.IGNORECASE)
_SECRET_VALUE = re.compile(r"SCRAM-SHA-256\$|^md5[0-9a-f]{32}$")


def recorded(action: str, phase: str, action_id: uuid.UUID, **fields: Any) -> dict[str, Any]:
    """One record of `action`: its `intent` or its `outcome`, `action_id` binding the two, written now."""
    return {"action": action, "phase": phase, "action_id": str(action_id), "at": datetime.now(UTC).isoformat(),
            **fields}  # fmt: skip


def _secret(record: dict[str, Any]) -> str | None:
    for key, value in record.items():
        if _SECRET_KEY.search(str(key)) or (isinstance(value, str) and _SECRET_VALUE.search(value)):
            return str(key)
    return None


class AdministrationSink:
    """The writer: put-only credentials on its prefix, held off the database host."""

    def __init__(self, client: Any, bucket: str, prefix: str) -> None:
        self._client, self.bucket, self.prefix = client, bucket, prefix

    def write(self, record: dict[str, Any]) -> str:
        """The record, once: where. Raises on any failure, a record already written included (the caller stops)."""
        held = _secret(record)
        if held is not None:
            raise ValueError(f"an administration record holds no secret: {held}")
        key = f"{self.prefix}{record['action_id']}/{record['phase']}.json"
        self._client.put_object(Bucket=self.bucket, Key=key, Body=json.dumps(record, sort_keys=True).encode(),
                                ContentType="application/json", IfNoneMatch="*")  # fmt: skip
        return f"s3://{self.bucket}/{key}"


@dataclass
class Records:
    entries: list[dict[str, Any]] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)


def read_records(client: Any, bucket: str, prefix: str, *, page: int = PAGE) -> Records:
    """Every record under `prefix`, each one's first version, and each one deleted or rewritten as a problem."""
    found = Records()
    versions: dict[str, list[dict[str, Any]]] = {}
    markers: set[str] = set()
    after: dict[str, str] = {}
    while True:
        answer = client.list_object_versions(Bucket=bucket, Prefix=prefix, MaxKeys=page, **after)
        for version in answer.get("Versions", []):
            versions.setdefault(version["Key"], []).append(version)
        markers.update(marker["Key"] for marker in answer.get("DeleteMarkers", []))
        if not answer.get("IsTruncated"):
            break
        after = {"KeyMarker": answer["NextKeyMarker"], "VersionIdMarker": answer.get("NextVersionIdMarker", "")}
    for key in sorted(versions.keys() | markers):
        if key in markers:
            found.problems.append(f"{key}: deleted (a delete marker)")
        kept = versions.get(key, [])
        if len(kept) > 1:
            found.problems.append(f"{key}: rewritten ({len(kept)} versions)")
        if not kept:
            continue
        first = min(enumerate(kept), key=lambda iv: (iv[1]["LastModified"], -iv[0]))[1]  # listed newest first
        try:
            body = client.get_object(Bucket=bucket, Key=key, VersionId=first["VersionId"])["Body"].read()
            entry = json.loads(body)
            if not isinstance(entry, dict) or not {"action", "phase", "action_id"} <= entry.keys():
                raise ValueError
        except (ClientError, ValueError):
            found.problems.append(f"{key}: not a record")
            continue
        found.entries.append(entry)
    return found
