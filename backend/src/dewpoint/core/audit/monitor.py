# SPDX-License-Identifier: Apache-2.0
"""D6's independent monitor (#3; the owner's acceptance condition; 2b-4b M4).

Object Lock protects an anchor once it's written, not the writing of the next one: a compromised database could drop
a scope or withhold its anchors without leaving a version to find. So the monitor runs off the database host and
keeps, off it too, the expected scopes and each one's anchor cadence (its roster, a file the operator maintains) and
each scope's high-water mark (its own state file). From those, the database's scopes and the bucket's anchors, it
alerts on:

- `audit_scope_missing`: a scope the roster names, or one it saw before, that the database no longer lists (D6.10);
- `audit_anchor_overdue`: a scope's oldest unanchored entry older than its cadence (D6.10);
- `audit_high_water_rolled_back`: the bucket's newest anchor for a scope below the mark it recorded (D6.11);
- `audit_monitor_state_lost`: no state at all, other than when it's first set up (D6.11).

A new scope (a new tenant's) is adopted as it's seen. A mark only moves up, so a rollback stays alerted on until
it's explained.

It alerts on the database's administration too (`drift`; 2b-4b M4 recovery, task 7; design revision 9 §1, narrowed
by revision 10 §3): what the catalog shows of the recovery logins and the schema's revision, with no record off the
host to explain it. Its limit: it compares snapshots, so a privileged change made and reverted between two reads
isn't seen, and a record covers a prescribed path's action only, never every bypass.

This module only decides; `dewpoint audit monitor` reads the inputs, writes the state and alerts."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

Alert = tuple[str, str, str]  # (event, scope, what)


@dataclass(frozen=True)
class Roster:
    default: timedelta  # a scope's cadence unless named
    scopes: dict[str, timedelta] = field(default_factory=dict)  # the expected scopes, each with its cadence

    def cadence(self, scope: str) -> timedelta:
        return self.scopes.get(scope, self.default)


@dataclass(frozen=True)
class Scope:
    """What the database shows of a scope: its newest entry, and when its oldest entry the bucket holds no anchor for
    was written (None: every entry anchored)."""

    newest: int
    oldest_unanchored: datetime | None


def watch(roster: Roster, state: dict[str, int] | None, database: dict[str, Scope], bucket: dict[str, int],
          now: datetime, *, init: bool = False) -> tuple[list[Alert], dict[str, int]]:  # fmt: skip
    """The alerts, and the state to keep: each scope's high-water mark, the newest anchor seen for it. `bucket`: each
    scope's newest anchor in the bucket; `state`: None when its file is gone (alerted on, unless `init`)."""
    alerts: list[Alert] = []
    if state is None and not init:
        alerts.append(("audit_monitor_state_lost", "", "no high-water marks: lost, or never set up (--init)"))
    marks = dict(state or {})
    for scope in sorted(roster.scopes.keys() - database.keys()):
        alerts.append(("audit_scope_missing", scope, "the roster's scope isn't in the database"))
    for scope in sorted((marks.keys() - database.keys()) - roster.scopes.keys()):
        alerts.append(("audit_scope_missing", scope, "a scope seen before isn't in the database"))
    for scope in sorted(database.keys() | bucket.keys()):
        newest_anchor = bucket.get(scope)
        recorded = marks.get(scope)
        if recorded is not None and (newest_anchor is None or newest_anchor < recorded):
            alerts.append(("audit_high_water_rolled_back", scope,
                           f"the bucket's newest anchor is seq {newest_anchor}, after {recorded}"))  # fmt: skip
        if newest_anchor is not None:
            marks[scope] = max(recorded or 0, newest_anchor)
        seen = database.get(scope)
        if seen is not None and seen.oldest_unanchored is not None:
            cadence = roster.cadence(scope)
            if now - seen.oldest_unanchored > cadence:
                minutes = int(cadence.total_seconds() // 60)
                alerts.append(("audit_anchor_overdue", scope,
                               f"seq {seen.newest} unanchored for more than {minutes} minutes"))  # fmt: skip
    return alerts, marks


@dataclass(frozen=True)
class Login:
    """A recovery login's attributes, as the catalog shows them."""

    can_login: bool
    superuser: bool = False
    create_db: bool = False
    create_role: bool = False
    replication: bool = False
    bypass_rls: bool = False

    def elevated(self) -> list[str]:
        names = ("superuser", "create_db", "create_role", "replication", "bypass_rls")
        return [name for name in names if getattr(self, name)]


@dataclass(frozen=True)
class Catalog:
    """What the database shows of its administration."""

    members: frozenset[str]  # `dewpoint_recovery`'s members
    mappings: dict[str, bool]  # each login `recovery_operators` maps: whether it's revoked
    logins: dict[str, Login]  # every recovery login: mapped, a member, or named `rcv_`
    revision: str | None  # `alembic_version`'s


def _succeeded(records: list[dict[str, Any]], action: str) -> list[dict[str, Any]]:
    return [r for r in records if r.get("action") == action and r.get("phase") == "outcome"
            and r.get("status") == "succeeded"]  # fmt: skip


def drift(records: list[dict[str, Any]], catalog: Catalog) -> list[Alert]:
    """The administration the catalog shows that no record explains:

    - `admin_membership_unrecorded`: a member of `dewpoint_recovery` that isn't an unrevoked login provisioned on the
      record;
    - `admin_mapping_unrecorded`: a mapping no provisioning recorded, or a revocation the records and the mapping
      disagree on;
    - `admin_login_altered`: a provisioned login with an attribute it's never given, or any other recovery login able
      to sign in;
    - `admin_revision_unrecorded`: a schema revision other than the last a recorded migration reached."""
    added = {str(r.get("login")) for r in _succeeded(records, "recovery.operator.add")}
    revoked = {str(r.get("login")) for r in _succeeded(records, "recovery.operator.revoke")}
    active = {login for login, gone in catalog.mappings.items() if not gone and login in added - revoked}
    alerts: list[Alert] = []
    for member in sorted(catalog.members - active):
        alerts.append(("admin_membership_unrecorded", member, "a member of dewpoint_recovery no record explains"))
    for login, gone in sorted(catalog.mappings.items()):
        if login not in added:
            alerts.append(("admin_mapping_unrecorded", login, "mapped with no recorded provisioning"))
        elif gone and login not in revoked:
            alerts.append(("admin_mapping_unrecorded", login, "revoked with no recorded revocation"))
        elif not gone and login in revoked:
            alerts.append(("admin_mapping_unrecorded", login, "mapped again after its recorded revocation"))
    for login, attributes in sorted(catalog.logins.items()):
        elevated = attributes.elevated()
        if elevated:
            alerts.append(("admin_login_altered", login, f"given {', '.join(elevated)}"))
        if attributes.can_login and login not in active:
            alerts.append(("admin_login_altered", login, "able to sign in, not an unrevoked provisioned login"))
    migrations = sorted(_succeeded(records, "migration"), key=lambda r: str(r.get("at")))
    reached = str(migrations[-1].get("to")) if migrations else None
    if catalog.revision != reached:
        what = f"the schema is at {catalog.revision}, the last recorded migration reached {reached}"
        alerts.append(("admin_revision_unrecorded", "", what))
    return alerts
