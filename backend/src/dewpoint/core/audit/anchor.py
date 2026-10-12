# SPDX-License-Identifier: Apache-2.0
import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from dewpoint.core.audit.service import verify_chain


def signed_message(scope: str, seq: int, hash_hex: str, at: str, kid: str | None = None) -> bytes:
    """What an anchor's signature covers; its key's id too when it names one (D6: verifying keeps every key id, for
    rotation), so an anchor can't be passed off as another key's."""
    base = f"dewpoint-audit-anchor|{scope}|{seq}|{hash_hex}|{at}"
    return (base if kid is None else f"{base}|{kid}").encode()


_message = signed_message


class AnchorSink(Protocol):
    """Where anchors are signed to: a file (evaluation), or D6's S3 bucket (`core/audit/s3.py`)."""

    name: str

    def write(self, scope: str, seq: int, hash_: bytes) -> str: ...


class FileAnchorSink:
    """Append-only JSON-lines file, each line Ed25519-signed. Store it outside the database host
    (object storage with object lock, a SIEM, or a separate volume)."""

    name = "file"

    def __init__(self, path: Path, private_key: Ed25519PrivateKey) -> None:
        self.path, self._key = path, private_key

    def write(self, scope: str, seq: int, hash_: bytes) -> str:
        at = datetime.now(UTC).isoformat()
        hash_hex = hash_.hex()
        sig = self._key.sign(_message(scope, seq, hash_hex, at)).hex()
        entry = {"scope": scope, "seq": seq, "hash": hash_hex, "at": at, "sig": sig}
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, sort_keys=True) + "\n")
        return f"{self.path.name}:{scope}:{seq}"

    def entries(self) -> list[dict[str, object]]:
        if not self.path.exists():
            return []
        return [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines() if line.strip()]


async def _held_by_standbys(s: AsyncSession) -> None:
    """Every row `s` has read is acknowledged by the configured synchronous standbys, when any is named: a commit of
    its own, later in the WAL than theirs and writing to it (a logical message no one reads; an xid alone writes
    nothing, and waits for none), waits for them under `synchronous_commit` on, whatever the session's. A row committed
    locally only (the inventory cutover's audit entry: its commit waits for no standby) is visible before then; signed,
    then lost in a failover, it would fail `audit verify` for good, the sink being append-only (the review of the 2b-4b
    M1 checkpoint 6). It proves receipt by the standbys Postgres waits for (`synchronous_standby_names`) only, not by
    every server that could be promoted: an asynchronous replica may still lack it (the owner's review of checkpoint
    6)."""
    engine = s.bind
    if not isinstance(engine, AsyncEngine):
        raise TypeError("an anchor's session is bound to an engine")
    async with engine.connect() as c:
        await c.execute(text("SELECT set_config('synchronous_commit', 'on', true), "
                             "pg_logical_emit_message(true, 'dewpoint', 'audit anchor')"))  # fmt: skip
        await c.commit()


async def anchor_all(s: AsyncSession, sink: AnchorSink) -> int:
    """Each scope's head not anchored yet, signed to `sink` once the configured synchronous standbys acknowledge it,
    then recorded."""
    heads = (
        await s.execute(text("select distinct on (scope) scope, seq, hash from audit_log order by scope, seq desc"))
    ).all()
    due = []
    for scope, seq, h in heads:
        exists = (
            await s.execute(text("select 1 from audit_anchors where scope=:s and seq=:q"), {"s": scope, "q": seq})
        ).first()
        if not exists:
            due.append((scope, seq, h))
    if due:
        await _held_by_standbys(s)
    written = 0
    for scope, seq, h in due:
        ref = sink.write(scope, seq, bytes(h))
        await s.execute(
            text("insert into audit_anchors(scope, seq, hash, sink, sink_ref) values (:s,:q,:h,:k,:r)"),
            {"s": scope, "q": seq, "h": bytes(h), "k": sink.name, "r": ref},
        )
        written += 1
    return written


async def verify_anchors(
    s: AsyncSession,
    entries: list[dict[str, object]],
    public_key: Ed25519PublicKey | Mapping[str, Ed25519PublicKey],
    *,
    max_lag: timedelta = timedelta(hours=1),
    now: datetime | None = None,
) -> list[str]:
    """Fail closed: missing anchors, unanchored old rows, broken chains and mismatches are all problems. `public_key`:
    the one key, or every key by its id (D6: an anchor names its key's id; one whose id isn't known is a problem)."""
    problems: list[str] = []
    if not entries:
        problems.append("no external anchors found")
    db_scopes: set[str] = set((await s.execute(text("select distinct scope from audit_log"))).scalars())
    for sc in sorted(db_scopes | {str(e["scope"]) for e in entries}):
        rep = await verify_chain(s, sc)
        if not rep.ok:
            problems.append(f"{sc}: chain broken at seq {rep.first_bad_seq}")
    # Every checkpoint recorded must be among the signed anchors (engine 2b spec §10.2): the database's own record of
    # them could be rewritten. A pruned scope's chain starts from the one with no entry at or before it left
    # (`verify_chain`, the fix-pass review's R8): anchored entries at or before that one are gone by design.
    recorded = text("select scope, seq, hash from audit_checkpoints order by scope, seq")
    checkpoints = [(scope, seq, bytes(h).hex()) for scope, seq, h in (await s.execute(recorded)).all()]
    starts = text(
        "select distinct on (c.scope) c.scope, c.seq from audit_checkpoints c where not exists "
        "(select 1 from audit_log l where l.scope = c.scope and l.seq <= c.seq) order by c.scope, c.seq desc"
    )
    pruned_through: dict[str, int] = {scope: seq for scope, seq in (await s.execute(starts)).all()}
    signed: set[tuple[str, int, str]] = set()
    anchored: dict[str, int] = {}
    for e in entries:
        scope, seq, hash_hex, at = str(e["scope"]), int(e["seq"]), str(e["hash"]), str(e["at"])  # type: ignore[call-overload]
        kid = str(e["kid"]) if e.get("kid") is not None else None
        key = public_key.get(kid or "") if isinstance(public_key, Mapping) else public_key
        if key is None:
            problems.append(f"{scope}:{seq}: anchor signed with an unknown key ({kid})")
            continue
        try:
            key.verify(bytes.fromhex(str(e["sig"])), signed_message(scope, seq, hash_hex, at, kid))
        except (InvalidSignature, ValueError):
            problems.append(f"{scope}:{seq}: bad anchor signature")
            continue
        signed.add((scope, seq, hash_hex))
        row = (
            await s.execute(text("select hash from audit_log where scope=:s and seq=:q"), {"s": scope, "q": seq})
        ).first()
        if row is None and seq <= pruned_through.get(scope, 0):
            continue  # pruned through its checkpoint
        if row is None:
            problems.append(f"{scope}:{seq}: anchored row missing")
        elif bytes(row[0]).hex() != hash_hex:
            problems.append(f"{scope}:{seq}: hash mismatch with external anchor")
        else:
            anchored[scope] = max(anchored.get(scope, 0), seq)
    for scope, seq, hash_hex in checkpoints:
        if (scope, seq, hash_hex) not in signed:
            problems.append(f"{scope}:{seq}: checkpoint not among the external anchors")
    # audit_append stamps created_at with the database's clock, so "now" defaults to that clock, not this host's:
    # any skew between the two would move the window (a just-written row would dodge max_lag=0)
    old_rows = await s.execute(
        text(
            "select scope, max(seq) from audit_log where created_at"
            " <= coalesce(cast(:now as timestamptz), statement_timestamp()) - cast(:lag as interval) group by scope"
        ),
        {"now": now, "lag": max_lag},
    )
    for scope, max_seq in old_rows.all():
        if anchored.get(scope, 0) < max_seq:
            problems.append(f"{scope}: rows up to seq {max_seq} older than {max_lag} are not anchored")
    return problems


async def anchor_freshness(s: AsyncSession, max_age: timedelta, now: datetime | None = None) -> list[str]:
    """Liveness, not integrity: scopes whose rows older than max_age have no anchor recorded at or after them.
    Reads the audit_anchors table the anchor job maintains; `audit verify` checks the signed external copy.
    Ages are measured on the database's clock, the one audit_append stamps created_at with, unless `now` is given."""
    rows = await s.execute(
        text(
            "select l.scope, max(l.seq) as due,"
            " (select max(a.seq) from audit_anchors a where a.scope = l.scope) as anchored"
            " from audit_log l"
            " where l.created_at <= coalesce(cast(:now as timestamptz), statement_timestamp()) - cast(:lag as interval)"
            " group by l.scope order by l.scope"
        ),
        {"now": now, "lag": max_age},
    )
    return [
        f"{scope}: rows up to seq {due} older than {max_age} have no anchor (latest anchored seq: {anchored or 'none'})"
        for scope, due, anchored in rows.all()
        if (anchored or 0) < due
    ]
