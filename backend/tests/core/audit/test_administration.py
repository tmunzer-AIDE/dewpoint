# SPDX-License-Identifier: Apache-2.0
"""The database's administration, recorded off its host (2b-4b M4 recovery, task 7; design revision 9 §1, the owner's
ruling on revision 8): D6's bucket, under `database-administration/`, written by an identity of its own (put-only on
that prefix, not the anchor writer's). Each record is one object, written once (`If-None-Match: *`), and holds no
secret: a verifier's fingerprint, never the verifier. Read back with the monitor's read-only identity, a record deleted
or rewritten is a problem. Against an in-memory bucket here; a real server is D6's proof."""

import uuid

import pytest
from botocore.exceptions import ClientError

from dewpoint.core.audit.administration import ADMINISTRATION, AdministrationSink, read_records, recorded
from tests.core.audit.fake_s3 import FakeS3

BUCKET, PREFIX = "audit-anchors", "dewpoint/"


def test_a_record_is_one_object_under_its_prefix_written_once() -> None:
    bucket = FakeS3()
    sink = AdministrationSink(bucket, BUCKET, PREFIX + ADMINISTRATION)
    action = uuid.uuid4()
    intent = recorded("recovery.operator.add", "intent", action, login="rcv_alice")
    where = sink.write(intent)
    assert where == f"s3://{BUCKET}/dewpoint/database-administration/{action}/intent.json"
    assert bucket.puts == [{"Key": f"dewpoint/database-administration/{action}/intent.json", "IfNoneMatch": "*"}]
    with pytest.raises(ClientError):  # never rewritten: a second write of it is refused, not a second version
        sink.write(intent)
    assert len(bucket.versions) == 1


@pytest.mark.parametrize(
    "fields",
    [{"verifier": "SCRAM-SHA-256$4096:c2FsdA==$a2V5:a2V5"}, {"password": "x"}, {"note": "SCRAM-SHA-256$4096:x$y:z"}],
    ids=["a verifier", "a password field", "a verifier in a value"],
)
def test_a_record_holding_a_secret_is_refused_before_any_write(fields: dict[str, str]) -> None:
    bucket = FakeS3()
    with pytest.raises(ValueError, match="secret"):
        AdministrationSink(bucket, BUCKET, PREFIX + ADMINISTRATION).write(
            recorded("recovery.operator.add", "intent", uuid.uuid4(), **fields)
        )
    assert bucket.puts == []


def test_the_records_read_back_with_a_deleted_or_rewritten_one_a_problem() -> None:
    bucket = FakeS3()
    sink = AdministrationSink(bucket, BUCKET, PREFIX + ADMINISTRATION)
    kept, gone = uuid.uuid4(), uuid.uuid4()
    sink.write(recorded("migration", "intent", kept, target="head"))
    sink.write(recorded("migration", "outcome", kept, status="succeeded", to="0056"))
    sink.write(recorded("migration", "intent", gone, target="head"))
    bucket.delete_object(Bucket=BUCKET, Key=f"dewpoint/database-administration/{gone}/intent.json")
    bucket.put_object(Bucket=BUCKET, Key=f"dewpoint/database-administration/{kept}/outcome.json", Body=b"{}")
    found = read_records(bucket, BUCKET, PREFIX + ADMINISTRATION)
    assert sorted((r["action_id"], r["phase"]) for r in found.entries) == sorted(  # a deleted one's first version stays
        [(str(kept), "intent"), (str(kept), "outcome"), (str(gone), "intent")]
    )
    assert next(r for r in found.entries if r["phase"] == "outcome")["to"] == "0056"  # its first version, of record
    assert sorted(found.problems) == sorted(
        [
            f"dewpoint/database-administration/{gone}/intent.json: deleted (a delete marker)",
            f"dewpoint/database-administration/{kept}/outcome.json: rewritten (2 versions)",
        ]
    )
