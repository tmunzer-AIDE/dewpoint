# SPDX-License-Identifier: Apache-2.0
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from dewpoint.core.audit.service import verify_chain


def _message(scope: str, seq: int, hash_hex: str, at: str) -> bytes:
    return f"dewpoint-audit-anchor|{scope}|{seq}|{hash_hex}|{at}".encode()


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


async def anchor_all(s: AsyncSession, sink: FileAnchorSink) -> int:
    heads = (
        await s.execute(text("select distinct on (scope) scope, seq, hash from audit_log order by scope, seq desc"))
    ).all()
    written = 0
    for scope, seq, h in heads:
        exists = (
            await s.execute(text("select 1 from audit_anchors where scope=:s and seq=:q"), {"s": scope, "q": seq})
        ).first()
        if exists:
            continue
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
    public_key: Ed25519PublicKey,
    *,
    max_lag: timedelta = timedelta(hours=1),
    now: datetime | None = None,
) -> list[str]:
    """Fail closed: missing anchors, unanchored old rows, broken chains and mismatches are all problems."""
    problems: list[str] = []
    if not entries:
        problems.append("no external anchors found")
    db_scopes: set[str] = set((await s.execute(text("select distinct scope from audit_log"))).scalars())
    for sc in sorted(db_scopes | {str(e["scope"]) for e in entries}):
        rep = await verify_chain(s, sc)
        if not rep.ok:
            problems.append(f"{sc}: chain broken at seq {rep.first_bad_seq}")
    anchored: dict[str, int] = {}
    for e in entries:
        scope, seq, hash_hex, at = str(e["scope"]), int(e["seq"]), str(e["hash"]), str(e["at"])  # type: ignore[call-overload]
        try:
            public_key.verify(bytes.fromhex(str(e["sig"])), _message(scope, seq, hash_hex, at))
        except (InvalidSignature, ValueError):
            problems.append(f"{scope}:{seq}: bad anchor signature")
            continue
        row = (
            await s.execute(text("select hash from audit_log where scope=:s and seq=:q"), {"s": scope, "q": seq})
        ).first()
        if row is None:
            problems.append(f"{scope}:{seq}: anchored row missing")
        elif bytes(row[0]).hex() != hash_hex:
            problems.append(f"{scope}:{seq}: hash mismatch with external anchor")
        else:
            anchored[scope] = max(anchored.get(scope, 0), seq)
    cutoff = (now or datetime.now(UTC)) - max_lag
    old_rows = await s.execute(
        text("select scope, max(seq) from audit_log where created_at <= :c group by scope"), {"c": cutoff}
    )
    for scope, max_seq in old_rows.all():
        if anchored.get(scope, 0) < max_seq:
            problems.append(f"{scope}: rows up to seq {max_seq} older than {max_lag} are not anchored")
    return problems


async def anchor_freshness(s: AsyncSession, max_age: timedelta, now: datetime | None = None) -> list[str]:
    """Liveness, not integrity: scopes whose rows older than max_age have no anchor recorded at or after them.
    Reads the audit_anchors table the anchor job maintains; `audit verify` checks the signed external copy."""
    cutoff = (now or datetime.now(UTC)) - max_age
    rows = await s.execute(
        text(
            "select l.scope, max(l.seq) as due,"
            " (select max(a.seq) from audit_anchors a where a.scope = l.scope) as anchored"
            " from audit_log l where l.created_at <= :cutoff group by l.scope order by l.scope"
        ),
        {"cutoff": cutoff},
    )
    return [
        f"{scope}: rows up to seq {due} older than {max_age} have no anchor (latest anchored seq: {anchored or 'none'})"
        for scope, due, anchored in rows.all()
        if (anchored or 0) < due
    ]
