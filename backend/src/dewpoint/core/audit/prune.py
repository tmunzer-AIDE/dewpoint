# SPDX-License-Identifier: Apache-2.0
"""Audit pruning (engine 2b spec §10.2; ruling D5), as the auditor: each scope's entries older than the retention go,
through a checkpoint at the last one, anchored off the database first, then recorded, then pruned by `audit_prune()`,
which checks all of it again and refuses outside a development deployment until an off-host sink exists (#3)."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from dewpoint.core.audit.anchor import FileAnchorSink


class PruningDisabledError(Exception):
    """Pruning is disabled outside a development deployment until an off-host anchor sink exists (#3)."""


_DUE = text(
    "SELECT scope, max(seq) FROM audit_log WHERE created_at < statement_timestamp() - make_interval(days => :d) "
    "GROUP BY scope ORDER BY scope"
)


async def prune(s: AsyncSession, sink: FileAnchorSink, *, older_than_days: int) -> dict[str, int]:
    """How many entries each scope lost. Raises PruningDisabledError before anything is anchored or deleted."""
    if not (await s.execute(text("SELECT audit_pruning_enabled()"))).scalar_one():
        raise PruningDisabledError
    pruned: dict[str, int] = {}
    for scope, seq in (await s.execute(_DUE, {"d": older_than_days})).all():
        digest = bytes((await s.execute(text("SELECT hash FROM audit_log WHERE scope = :s AND seq = :q"),
                                        {"s": scope, "q": seq})).scalar_one())  # fmt: skip
        ref = sink.write(scope, seq, digest)  # off the database before anything goes
        await s.execute(text("INSERT INTO audit_checkpoints (scope, seq, hash, sink, sink_ref) VALUES "
                             "(:s, :q, :h, :k, :r) ON CONFLICT DO NOTHING"),
                        {"s": scope, "q": seq, "h": digest, "k": sink.name, "r": ref})  # fmt: skip
        count = await s.execute(text("SELECT audit_prune(:s, :q, :d)"), {"s": scope, "q": seq, "d": older_than_days})
        pruned[scope] = int(count.scalar_one())
    return pruned
