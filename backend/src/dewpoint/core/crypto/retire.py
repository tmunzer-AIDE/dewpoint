# SPDX-License-Identifier: Apache-2.0
"""Retiring a data-key version (engine 2b spec §6.4), as the key admin: only when nothing needs it. Each check names
what it found, counts only, never a value.

A tenant's version: it isn't the active one; its **payload floor** has passed (its successor's creation + the key
cache's TTL + twice the longest maximum run duration ever recorded + the Temporal namespace's retention); no run that
could hold a payload sealed under it is open (one started before its successor reached every cache); no stored record
names it (`reencrypt`'s fields, keypairs' private keys included); no request's or upload's digest was made with it;
every schedule is synced and no live schedule's Temporal action still names it; it was made after the tick cutover;
and every run execution that could hold it is proven gone from Temporal (`run_histories`).
The platform's version (users' TOTP secrets, never a payload): not the active one, and no record names it. Retiring
deletes the version, audited, under the scope's key lock, so no rotation interleaves.

What Temporal may still hold under a version, and what covers it (the owner's M3 review: the runs table isn't every
open execution):
- a run's executions: its root's chain, and every child it started (sub-flows, failure handlers, loop batches) and
  theirs. A row isn't proof of any (one ended may still be open in Temporal, and retention deletes rows before
  Temporal deletes histories): `execution_evidence` keeps each (`apps.dispatcher.evidence`), and `run_histories`
  requires each that started before the successor reached every cache to be shown gone by Temporal, read before it
  went. `open_runs`, rows still running, stays as a cross-check;
- a schedule tick (`ScheduleTick`): nothing, since the tick contract (`apps.tick_contract`): its action carries no
  argument and its payloads are unsealed. A tick from before the contract sealed its own under whatever version was
  active, and nothing proves its history gone: `legacy_ticks` keeps every version made before the tick cutover, and
  `schedule_actions` waits while a live schedule's action, synced before, still names this one;
- what any of them sealed before closing, kept in its history for the namespace's retention: the payload floor."""

import struct
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from dewpoint.core.audit import service as audit
from dewpoint.core.crypto.keyring import lock_scope
from dewpoint.core.crypto.reencrypt import PLATFORM_FIELDS, TENANT_FIELDS
from dewpoint.core.platform.service import longest_run_duration_days

CACHE_TTL = timedelta(minutes=5)  # KeyringKeys': no process seals under a version past its successor + this


@dataclass(frozen=True)
class RunProof:
    """What Temporal showed of the run executions that could hold a version (`apps.dispatcher.evidence.prove`): how
    many are open, closed but still retained, closed but not yet read (what they started unknown so far), lost (seen,
    then gone before they were read), or pending (a start Temporal never showed: it may still land, or have landed and
    gone unseen). Each shown gone is proven, its evidence deleted."""

    open: int = 0
    retained: int = 0
    unread: int = 0
    lost: int = 0
    pending: int = 0

    @property
    def ok(self) -> bool:
        return not (self.open or self.retained or self.unread or self.lost or self.pending)

    def found(self) -> str:
        counts = {"open": self.open, "retained": self.retained, "unread": self.unread, "lost": self.lost,
                  "pending": self.pending}  # fmt: skip
        return ", ".join(f"{n} {kind}" for kind, n in counts.items() if n)


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    found: str = ""  # what blocks it: counts and names, never a value


class NotRetiredError(Exception):
    """A version something still needs: `checks` says what."""

    def __init__(self, checks: list[Check]) -> None:
        super().__init__("; ".join(f"{c.name}: {c.found}" for c in checks if not c.ok))
        self.checks = checks


async def _scalar(s: AsyncSession, sql: str, **params: object) -> object:
    return (await s.execute(text(sql), params)).scalar()


async def candidates_before(s: AsyncSession, tenant_id: uuid.UUID, version: int) -> datetime | None:
    """Run executions that started before this could hold a payload under `version`: its successor's creation + the
    key cache's TTL, + the same again, as an execution's recorded start (its history's event) can follow the seal by
    its workflow task's latency. None: no successor, every execution."""
    successor = await _scalar(s, "SELECT min(created_at) FROM data_keys WHERE tenant_id = :t AND version > :v",
                              t=tenant_id, v=version)  # fmt: skip
    return successor + 2 * CACHE_TTL if isinstance(successor, datetime) else None


async def checks(
    s: AsyncSession, tenant_id: uuid.UUID | None, version: int, *, namespace_retention: timedelta | None,
    run_histories: RunProof | None = None,
) -> list[Check]:  # fmt: skip
    """What retiring `version` of the tenant's data key (or the platform's, `tenant_id` None) waits on, in the
    caller's scope. `namespace_retention`: the Temporal namespace's, as it reports it; `run_histories`: what Temporal
    showed of the run executions that could hold it (`candidates_before`); None for either: unknown."""
    table, owned = ("data_keys", "tenant_id = :t AND ") if tenant_id else ("platform_keys", "")
    row = (await s.execute(text(f"SELECT active, created_at FROM {table} WHERE {owned}version = :v"),  # noqa: S608
                           {"t": tenant_id, "v": version})).one_or_none()  # fmt: skip
    if row is None:
        return [Check("not_active", False, f"no version {version}")]
    found = [Check("not_active", not row.active, "it's the active version" if row.active else "")]
    header = struct.pack(">I", version)
    fields = TENANT_FIELDS if tenant_id else PLATFORM_FIELDS
    under: list[str] = []
    for field in fields:
        n = await _scalar(s, f"SELECT count(*) FROM {field.table} WHERE {owned}{field.column} IS NOT NULL "  # noqa: S608
                          f"AND substring({field.column} from 2 for 4) = :h", t=tenant_id, h=header)  # fmt: skip
        if n:
            under.append(f"{field.table}.{field.column}={n}")
    if tenant_id is None:
        return [*found, Check("records", not under, ", ".join(under))]
    successor = await _scalar(s, "SELECT min(created_at) FROM data_keys WHERE tenant_id = :t AND version > :v",
                              t=tenant_id, v=version)  # fmt: skip
    days = await longest_run_duration_days(s)
    if successor is None:
        found.append(Check("payload_floor", False, "no successor"))
    elif days is None or namespace_retention is None:
        found.append(Check("payload_floor", False, "no maximum run duration recorded" if days is None
                           else "the namespace's retention is unknown"))  # fmt: skip
    else:
        floor = CACHE_TTL + 2 * timedelta(days=days) + namespace_retention
        passed = await _scalar(s, "SELECT statement_timestamp() >= cast(:at as timestamptz) + cast(:floor as interval)",
                               at=successor, floor=floor)  # fmt: skip
        found.append(Check("payload_floor", bool(passed), "" if passed else f"until successor + {floor}"))
    open_runs = 0 if successor is None else await _scalar(
        s, "SELECT count(*) FROM runs WHERE tenant_id = :t AND status = 'running' "
        "AND coalesce(started_at, queued_at) < cast(:at as timestamptz) + cast(:ttl as interval)",
        t=tenant_id, at=successor, ttl=CACHE_TTL,
    )  # fmt: skip
    found.append(Check("open_runs", not open_runs, f"{open_runs} run(s) started before the cache expired" if open_runs
                       else ""))  # fmt: skip
    found.append(Check("records", not under, ", ".join(under)))
    digests = [f"{t}={n}" for t in ("run_requests", "csv_uploads")
               if (n := await _scalar(s, f"SELECT count(*) FROM {t} WHERE tenant_id = :t "  # noqa: S608
                                         "AND digest_key_version = :v", t=tenant_id, v=version))]  # fmt: skip
    found.append(Check("digests", not digests, ", ".join(digests)))
    unsynced = await _scalar(
        s, "SELECT count(*) FROM schedules WHERE tenant_id = :t AND (synced_generation <> generation OR "
        "(deleted_at IS NULL AND action_key_version = :v))", t=tenant_id, v=version,
    )  # fmt: skip
    found.append(Check("schedule_actions", not unsynced, f"{unsynced} schedule(s) not synced, or whose action still "
                       "names it" if unsynced else ""))  # fmt: skip
    cutover = await _scalar(s, "SELECT at FROM tick_cutover")
    if cutover is None:
        found.append(Check("legacy_ticks", False, "the tick cutover isn't recorded (`keys tick-cutover`)"))
    else:
        after = await _scalar(s, "SELECT cast(:made as timestamptz) >= cast(:at as timestamptz)", made=row.created_at,
                              at=cutover)  # fmt: skip
        found.append(Check("legacy_ticks", bool(after), "" if after else "made before the tick cutover: a tick from "
                           "before it may still hold it"))  # fmt: skip
    found.append(Check("run_histories", run_histories is not None and run_histories.ok,
                       "Temporal couldn't be asked" if run_histories is None else run_histories.found()))  # fmt: skip
    return found


async def retire(
    s: AsyncSession, tenant_id: uuid.UUID | None, version: int, *, namespace_retention: timedelta | None,
    run_histories: RunProof | None = None,
) -> list[Check]:  # fmt: skip
    """The version deleted, audited, once every check passes, under the scope's key lock; NotRetiredError otherwise."""
    scope = str(tenant_id) if tenant_id else "platform"
    await lock_scope(s, tenant_id)
    found = await checks(s, tenant_id, version, namespace_retention=namespace_retention, run_histories=run_histories)
    if not all(c.ok for c in found):
        raise NotRetiredError(found)
    table, owned = ("data_keys", "tenant_id = :t AND ") if tenant_id else ("platform_keys", "")
    gone = text(f"DELETE FROM {table} WHERE {owned}version = :v AND NOT active")  # noqa: S608
    await s.execute(gone, {"t": tenant_id, "v": version})
    await audit.record(s, tenant_id=tenant_id, actor_id=None, action="keys.retire", target_type="data_key",
                       target_id=scope, details={"version": version})  # fmt: skip
    return found
