# SPDX-License-Identifier: Apache-2.0
"""An in-memory S3 bucket with Object Lock, for the anchor sink's unit tests: just the calls the sink, the verifier
and the monitor make, with S3's documented semantics for them (versions, delete markers, compliance-mode retention,
conditional writes, paged version listings). Whether a real server behaves so is D6's proof, on the pinned MinIO."""

import io
import itertools
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from botocore.exceptions import ClientError

_ids = itertools.count(1)


def _error(code: str, status: int) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": code}, "ResponseMetadata": {"HTTPStatusCode": status}},
                       "operation")  # fmt: skip


@dataclass
class Version:
    key: str
    body: bytes | None  # None: a delete marker
    mode: str | None
    retain_until: datetime | None
    last_modified: datetime
    version_id: str = field(default_factory=lambda: f"v{next(_ids)}")


class FakeS3:
    def __init__(self, *, mode: str | None = "COMPLIANCE", days: int | None = 436, enabled: bool = True,
                 now: datetime | None = None, lock_lag: timedelta = timedelta(0)) -> None:  # fmt: skip
        """`lock_lag`: how much earlier than the version's own time the server dates its lock (a real server takes
        the two times apart, by milliseconds)."""
        self.mode, self.days, self.enabled, self.lock_lag = mode, days, enabled, lock_lag
        self.now = now or datetime(2026, 10, 9, 12, tzinfo=UTC)
        self.versions: list[Version] = []  # oldest first
        self.puts: list[dict[str, Any]] = []

    def _current(self, key: str) -> Version | None:
        found = [v for v in self.versions if v.key == key]
        return found[-1] if found else None

    def put_object(self, *, Bucket: str, Key: str, Body: bytes, IfNoneMatch: str | None = None,  # noqa: N803
                   **_: Any) -> dict[str, Any]:  # fmt: skip
        self.puts.append({"Key": Key, "IfNoneMatch": IfNoneMatch})
        current = self._current(Key)
        if IfNoneMatch == "*" and current is not None and current.body is not None:
            raise _error("PreconditionFailed", 412)
        retain = self.now + timedelta(days=self.days) - self.lock_lag if self.mode and self.days else None
        version = Version(Key, bytes(Body), self.mode if retain else None, retain, self.now)
        self.versions.append(version)
        return {"VersionId": version.version_id}

    def delete_object(self, *, Bucket: str, Key: str, VersionId: str | None = None) -> dict[str, Any]:  # noqa: N803
        if VersionId is None:
            self.versions.append(Version(Key, None, None, None, self.now))
            return {"DeleteMarker": True}
        [version] = [v for v in self.versions if v.version_id == VersionId]
        if version.mode == "COMPLIANCE" and version.retain_until and version.retain_until > self.now:
            raise _error("AccessDenied", 403)
        self.versions.remove(version)
        return {}

    def list_object_versions(self, *, Bucket: str, Prefix: str = "", KeyMarker: str = "",  # noqa: N803
                             VersionIdMarker: str = "", MaxKeys: int = 1000) -> dict[str, Any]:  # fmt: skip
        listed = sorted((v for v in self.versions if v.key.startswith(Prefix)),
                        key=lambda v: (v.key, -self.versions.index(v)))  # each key's newest first  # fmt: skip
        start = 0
        if KeyMarker:
            start = next(i for i, v in enumerate(listed) if (v.key, v.version_id) == (KeyMarker, VersionIdMarker)) + 1
        page = listed[start : start + MaxKeys]
        truncated = start + MaxKeys < len(listed)
        answer: dict[str, Any] = {
            "IsTruncated": truncated,
            "Versions": [{"Key": v.key, "VersionId": v.version_id, "LastModified": v.last_modified,
                          "IsLatest": v is self._current(v.key)} for v in page if v.body is not None],
            "DeleteMarkers": [{"Key": v.key, "VersionId": v.version_id, "LastModified": v.last_modified,
                               "IsLatest": v is self._current(v.key)} for v in page if v.body is None],
        }  # fmt: skip
        if truncated:
            answer["NextKeyMarker"], answer["NextVersionIdMarker"] = page[-1].key, page[-1].version_id
        return answer

    def get_object(self, *, Bucket: str, Key: str, VersionId: str) -> dict[str, Any]:  # noqa: N803
        [version] = [v for v in self.versions if v.version_id == VersionId]
        return {"Body": io.BytesIO(version.body or b"")}

    def get_object_retention(self, *, Bucket: str, Key: str, VersionId: str) -> dict[str, Any]:  # noqa: N803
        [version] = [v for v in self.versions if v.version_id == VersionId]
        if version.mode is None:
            raise _error("NoSuchObjectLockConfiguration", 404)
        return {"Retention": {"Mode": version.mode, "RetainUntilDate": version.retain_until}}

    def get_object_lock_configuration(self, *, Bucket: str) -> dict[str, Any]:  # noqa: N803
        if not self.enabled:
            raise _error("ObjectLockConfigurationNotFoundError", 404)
        rule = {"DefaultRetention": {"Mode": self.mode, "Days": self.days}} if self.mode else {}
        return {"ObjectLockConfiguration": {"ObjectLockEnabled": "Enabled", **({"Rule": rule} if rule else {})}}
