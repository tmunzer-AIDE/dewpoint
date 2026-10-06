# SPDX-License-Identifier: Apache-2.0
import hashlib
import json
import re
import uuid
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_FORBIDDEN = re.compile(r"password|secret|token|code|credential", re.IGNORECASE)
ZERO = bytes(32)


def _check_details(d: object) -> None:
    if isinstance(d, dict):
        for k, v in d.items():
            if _FORBIDDEN.search(str(k)):
                raise ValueError(f"audit details must not contain secret-like key: {k}")
            _check_details(v)
    elif isinstance(d, list):
        for v in d:
            _check_details(v)


async def record(
    s: AsyncSession,
    *,
    tenant_id: uuid.UUID | None,
    actor_id: uuid.UUID | None,
    action: str,
    target_type: str = "",
    target_id: str = "",
    details: dict[str, object] | None = None,
) -> int:
    _check_details(details or {})
    res = await s.execute(
        text("select audit_append(:t, :a, :act, :tt, :tid, cast(:d as jsonb))"),
        {
            "t": tenant_id,
            "a": actor_id,
            "act": action,
            "tt": target_type,
            "tid": target_id,
            "d": json.dumps(details or {}),
        },
    )
    return int(res.scalar_one())


@dataclass(frozen=True)
class ChainReport:
    ok: bool
    checked: int
    first_bad_seq: int | None
    head_seq: int | None
    head_hash: bytes | None


_ROWS = text("""
select seq, audit_canonical(seq, scope, actor_id, action, target_type, target_id, details, created_at) as canon,
       prev_hash, hash
from audit_log where scope = :scope and seq > :after order by seq
""")
# the latest checkpoint with no entry at or before it left: one still followed by unpruned entries starts nothing (M4)
_CHECKPOINT = text("""
select c.seq, c.hash from audit_checkpoints c
where c.scope = :scope and not exists (select 1 from audit_log l where l.scope = :scope and l.seq <= c.seq)
order by c.seq desc limit 1
""")


async def verify_chain(s: AsyncSession, scope: str) -> ChainReport:
    """Recompute every hash in Python. Uses the DB only to render the canonical text, not to judge it. A pruned chain
    starts from its checkpoint, the last entry pruned (engine 2b spec §10.2), which `verify_anchors` checks against the
    signed external anchors; a checkpoint with entries still at or before it is no start (the final review's M4), so
    every entry left is verified."""
    checkpoint = (await s.execute(_CHECKPOINT, {"scope": scope})).first()
    prev, after = (bytes(checkpoint.hash), checkpoint.seq) if checkpoint else (ZERO, 0)
    checked, head_seq, head_hash = 0, None, None
    for seq, canon, prev_hash, h in (await s.execute(_ROWS, {"scope": scope, "after": after})).all():
        expected = hashlib.sha256(prev + canon.encode()).digest()
        if bytes(prev_hash) != prev or bytes(h) != expected:
            return ChainReport(False, checked, seq, head_seq, head_hash)
        prev, head_seq, head_hash, checked = expected, seq, expected, checked + 1
    return ChainReport(True, checked, None, head_seq, head_hash)
