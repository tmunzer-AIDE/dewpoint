# SPDX-License-Identifier: Apache-2.0
"""The monitor's administration drift (2b-4b M4 recovery, task 7; design revision 9 §1, narrowed by revision 10 §3).
The database's administrator and the migration run are trusted exceptions (the owner's ruling on revision 8): what
they do on the prescribed paths is recorded off the host, and the independent monitor alerts on what the database shows
with no record to match. Its limit: it compares snapshots, so a change made and reverted between two reads isn't seen,
and a record covers a prescribed path's action only, never every bypass."""

import uuid

from dewpoint.core.audit.administration import recorded
from dewpoint.core.audit.monitor import Catalog, Login, drift

ACTIVE = Login(can_login=True)
REVOKED = Login(can_login=False)


def _done(action: str, **fields: str) -> list[dict[str, object]]:
    """A prescribed path's intent and its successful outcome."""
    action_id = uuid.uuid4()
    return [recorded(action, "intent", action_id, **fields),
            recorded(action, "outcome", action_id, status="succeeded", **fields)]  # fmt: skip


RECORDS = [*_done("recovery.operator.add", login="rcv_alice"), *_done("recovery.operator.add", login="rcv_bob"),
           *_done("recovery.operator.revoke", login="rcv_bob"), *_done("migration", to="0056")]  # fmt: skip
HEALTHY = Catalog(members=frozenset({"rcv_alice"}), mappings={"rcv_alice": False, "rcv_bob": True},
                  logins={"rcv_alice": ACTIVE, "rcv_bob": REVOKED}, revision="0056")  # fmt: skip


def _changed(**changes: object) -> Catalog:
    fields = {"members": HEALTHY.members, "mappings": HEALTHY.mappings, "logins": HEALTHY.logins,
              "revision": HEALTHY.revision, **changes}  # fmt: skip
    return Catalog(**fields)  # type: ignore[arg-type]


def test_what_the_records_explain_raises_nothing() -> None:
    assert drift(RECORDS, HEALTHY) == []


def test_a_membership_added_directly_is_alerted() -> None:
    catalog = _changed(members=frozenset({"rcv_alice", "rcv_mallory"}),
                       logins={**HEALTHY.logins, "rcv_mallory": ACTIVE})  # fmt: skip
    assert ("admin_membership_unrecorded", "rcv_mallory") in [a[:2] for a in drift(RECORDS, catalog)]


def test_a_revoked_login_given_its_membership_back_is_alerted() -> None:
    catalog = _changed(members=frozenset({"rcv_alice", "rcv_bob"}))
    assert ("admin_membership_unrecorded", "rcv_bob") in [a[:2] for a in drift(RECORDS, catalog)]


def test_a_mapping_written_or_unrevoked_without_a_record_is_alerted() -> None:
    added = _changed(mappings={**HEALTHY.mappings, "rcv_carol": False})
    assert ("admin_mapping_unrecorded", "rcv_carol") in [a[:2] for a in drift(RECORDS, added)]
    unrevoked = _changed(mappings={"rcv_alice": False, "rcv_bob": False})
    assert ("admin_mapping_unrecorded", "rcv_bob") in [a[:2] for a in drift(RECORDS, unrevoked)]


def test_a_recovery_logins_attributes_changed_are_alerted() -> None:
    elevated = _changed(logins={**HEALTHY.logins, "rcv_alice": Login(can_login=True, create_role=True)})
    assert ("admin_login_altered", "rcv_alice") in [a[:2] for a in drift(RECORDS, elevated)]
    relogged = _changed(logins={**HEALTHY.logins, "rcv_bob": ACTIVE})  # a revoked login able to sign in again
    assert ("admin_login_altered", "rcv_bob") in [a[:2] for a in drift(RECORDS, relogged)]
    stray = _changed(logins={**HEALTHY.logins, "rcv_eve": ACTIVE})  # a recovery-named login nobody provisioned
    assert ("admin_login_altered", "rcv_eve") in [a[:2] for a in drift(RECORDS, stray)]


def test_a_revision_no_recorded_migration_reached_is_alerted() -> None:
    assert [a[0] for a in drift(RECORDS, _changed(revision="0057"))] == ["admin_revision_unrecorded"]
    failed = [*RECORDS, *_done("migration", to="0057")[:1]]  # an intent with no outcome: not a recorded migration
    assert [a[0] for a in drift(failed, _changed(revision="0057"))] == ["admin_revision_unrecorded"]
    assert drift([*RECORDS, *_done("migration", to="0057")], _changed(revision="0057")) == []
