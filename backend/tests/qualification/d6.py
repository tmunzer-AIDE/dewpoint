# SPDX-License-Identifier: Apache-2.0
"""The administration's off-host record on the target (design revision 9 §1 and §5.1; D6 passed locally only): the
target's own bucket and identities, each held apart.

- the bucket locks every version, compliance mode, by default;
- the administration writer puts a record once under `<prefix>database-administration/`, and that version is locked;
  it's refused a second write of the same record, any key outside its prefix, reading, and deleting a version;
- the monitor's reader lists and reads the prefix, every version, and is refused writing.

A qualification record is written for it (action `qualification.d6`, no secret), and stays, locked, as the record of
this run.

    DEWPOINT_QUALIFICATION_APPROVED=<id> \\
    DEWPOINT_QUALIFICATION_WRITER_KEY_ID=... DEWPOINT_QUALIFICATION_WRITER_SECRET=... \\
    DEWPOINT_QUALIFICATION_READER_KEY_ID=... DEWPOINT_QUALIFICATION_READER_SECRET=... \\
    python -m tests.qualification.d6 --bucket <D6's bucket> --prefix dewpoint/ [--endpoint-url ...] [--region ...] \\
      --out d6.jsonl"""

import argparse
import json
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import boto3
from botocore.exceptions import ClientError

from dewpoint.core.audit.administration import ADMINISTRATION, AdministrationSink, read_records, recorded
from tests.qualification.approval import Record, approved, secret

DESCRIPTION = "The administration's off-host record on the target: a locked bucket, a put-only writer, a reader."


def outside_key(prefix: str, approval: str) -> str:
    """Where the writer's refusal outside its prefix is tried: neither the anchors nor the administration records, so
    an identity wrongly let write leaves its locked probe where nothing reads it as one of theirs."""
    return f"{prefix}qualification-probes/writer-{approval}-{uuid.uuid4().hex}"


def reader_probe(prefix: str, approval: str) -> tuple[str, bytes]:
    """The reader's refused write, under the administration prefix it reads: a well-formed qualification record, so a
    reader wrongly let write leaves a record, never a stray object the monitor would flag on every read for good."""
    entry = recorded("qualification.d6.reader_probe", "outcome", uuid.uuid4(), approval=approval)
    return f"{prefix}{ADMINISTRATION}{entry['action_id']}/{entry['phase']}.json", json.dumps(entry).encode()


def refused(call: Callable[[], Any]) -> str | None:
    """The refusal's code, or None when `call` succeeded."""
    try:
        call()
    except ClientError as e:
        return str(e.response.get("Error", {}).get("Code", "refused"))
    return None


def main() -> int:
    approval = approved()
    parser = argparse.ArgumentParser(prog="python -m tests.qualification.d6", description=DESCRIPTION)
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--prefix", required=True, help="the deployment's audit prefix (DEWPOINT_AUDIT_S3_PREFIX)")
    parser.add_argument("--endpoint-url")
    parser.add_argument("--region")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    record = Record(args.out, "d6", approval)

    def client(role: str) -> Any:
        return boto3.client("s3", endpoint_url=args.endpoint_url, region_name=args.region,
                            aws_access_key_id=secret(f"DEWPOINT_QUALIFICATION_{role}_KEY_ID"),
                            aws_secret_access_key=secret(f"DEWPOINT_QUALIFICATION_{role}_SECRET"))  # fmt: skip

    writer, reader = client("WRITER"), client("READER")
    prefix = f"{args.prefix}{ADMINISTRATION}"
    record.write(bucket=args.bucket, prefix=prefix)

    lock = reader.get_object_lock_configuration(Bucket=args.bucket).get("ObjectLockConfiguration", {})
    default = lock.get("Rule", {}).get("DefaultRetention", {})
    record.check(lock.get("ObjectLockEnabled") == "Enabled" and default.get("Mode") == "COMPLIANCE",
                 "every version locked, compliance mode, by default", lock=lock)  # fmt: skip

    sink = AdministrationSink(writer, args.bucket, prefix)
    entry = recorded("qualification.d6", "outcome", uuid.uuid4(), approval=approval)
    where = sink.write(entry)
    key = where.split(f"s3://{args.bucket}/", 1)[1]
    record.check(True, "the writer puts a record under its prefix", key=key)
    head = reader.head_object(Bucket=args.bucket, Key=key)
    record.check(head.get("ObjectLockMode") == "COMPLIANCE" and bool(head.get("ObjectLockRetainUntilDate")),
                 "its version is locked", mode=head.get("ObjectLockMode"),
                 until=head.get("ObjectLockRetainUntilDate"))  # fmt: skip
    version = head.get("VersionId")

    again = refused(lambda: sink.write(entry))
    record.check(again is not None, "a second write of the record: refused", answer=again)
    elsewhere = outside_key(args.prefix, approval)
    outside = refused(lambda: writer.put_object(Bucket=args.bucket, Key=elsewhere, Body=b"{}"))
    record.check(outside is not None, "the writer outside its prefix: refused", answer=outside)
    read = refused(lambda: writer.get_object(Bucket=args.bucket, Key=key))
    record.check(read is not None, "the writer reading: refused", answer=read)
    deleted = refused(lambda: writer.delete_object(Bucket=args.bucket, Key=key, VersionId=version))
    record.check(deleted is not None, "the writer deleting the version: refused", answer=deleted)

    records = read_records(reader, args.bucket, prefix)
    record.check(any(e.get("action_id") == entry["action_id"] for e in records.entries),
                 "the reader reads it back, every version", problems=records.problems)  # fmt: skip
    probe_key, probe = reader_probe(args.prefix, approval)
    written = refused(lambda: reader.put_object(Bucket=args.bucket, Key=probe_key, Body=probe))
    record.check(written is not None, "the reader writing: refused", answer=written)
    return record.finished()


if __name__ == "__main__":
    raise SystemExit(main())
