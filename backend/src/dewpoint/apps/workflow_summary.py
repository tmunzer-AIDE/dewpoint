# SPDX-License-Identifier: Apache-2.0
"""What the workflows list shows of each workflow beyond its row (sub-project 4, B3): its last live root run and, apart,
its last simulated one; its root runs in the last 24 hours, live and simulated apart; whether its draft differs from
its active version; and why it needs attention. Live runs alone drive attention (4b ruling 7): a simulation is a
test, and a later successful one says nothing about the live failure before it."""

import asyncio
import uuid
from collections import OrderedDict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from dewpoint.engine.graph.model import GraphFormatError, graph_hash, parse_graph

ATTENTION_STATUSES = ("failed", "deadline_exceeded")

# Each workflow's last root run of each mode. `runs` has no index on `workflow_id` (4b ruling 5, held on the probe's
# evidence): this is one scan of the tenant's root runs, sorted, whatever the number of workflows.
LAST_RUNS = text(
    "select distinct on (workflow_id, mode) workflow_id, mode, status, coalesce(ended_at, started_at, queued_at) as at"
    " from runs where tenant_id = :tenant and kind = 'run' and workflow_id = any(cast(:ids as uuid[]))"
    " order by workflow_id, mode, queued_at desc, id desc"
)
# Each workflow's root runs queued in the last 24 hours, by the database's clock (its clock wrote the rows): a range of
# `runs_tenant_queued`.
COUNTS_24H = text(
    "select workflow_id, count(*) filter (where mode = 'live') as live,"
    " count(*) filter (where mode = 'simulate') as simulated"
    " from runs where tenant_id = :tenant and kind = 'run' and workflow_id = any(cast(:ids as uuid[]))"
    " and queued_at >= now() - interval '24 hours' group by workflow_id"
)


@dataclass(frozen=True)
class LastRun:
    status: str
    at: datetime  # when it ended, else started, else was queued


@dataclass(frozen=True)
class RunStats:
    last_live: LastRun | None
    last_simulated: LastRun | None
    live_24h: int
    simulated_24h: int


async def run_stats(
    s: AsyncSession, tenant_id: uuid.UUID, workflow_ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, RunStats]:
    """Each workflow's root runs, in two reads for any number of workflows: a sub-flow's or failure handler's run
    counts toward its parent's, never as the workflow's own."""
    ids = sorted(set(workflow_ids), key=str)
    if not ids:
        return {}
    params = {"tenant": tenant_id, "ids": ids}
    last = {(r.workflow_id, r.mode): LastRun(r.status, r.at) for r in await s.execute(LAST_RUNS, params)}
    counts = {r.workflow_id: (int(r.live), int(r.simulated)) for r in await s.execute(COUNTS_24H, params)}
    return {
        wid: RunStats(
            last_live=last.get((wid, "live")),
            last_simulated=last.get((wid, "simulate")),
            live_24h=counts.get(wid, (0, 0))[0],
            simulated_24h=counts.get(wid, (0, 0))[1],
        )
        for wid in ids
    }


def attention(stats: RunStats, *, published: bool, blocked: Sequence[str]) -> list[str]:
    """Why a workflow needs attention: its last live root run failed or ran out of time, or its active version can't
    run. Simulations never count (4b ruling 7)."""
    out: list[str] = []
    if stats.last_live is not None and stats.last_live.status in ATTENTION_STATUSES:
        out.append("last_run_failed")
    if published and blocked:
        out.append("not_executable")
    return out


def _hash(draft: Mapping[str, Any]) -> str | None:
    try:
        return graph_hash(parse_graph(draft))
    except GraphFormatError:  # every draft is format-checked when saved; one that isn't can't equal a version
        return None


class DraftHashes:
    """Each draft's graph hash as publish computes it (positions included), None for one that doesn't parse. A draft
    never changes at its revision, so its hash is kept per (workflow, revision), the newest `kept`; the rest are parsed
    together, off the event loop (parsing is CPU-bound, up to the 1 MiB body cap a draft)."""

    def __init__(self, kept: int) -> None:
        self._kept = kept
        self._hashes: OrderedDict[tuple[uuid.UUID, int], str | None] = OrderedDict()

    def __len__(self) -> int:
        return len(self._hashes)

    async def of(self, drafts: Sequence[tuple[uuid.UUID, int, Mapping[str, Any]]]) -> dict[uuid.UUID, str | None]:
        """Only for drafts read from committed rows: a revision's hash is kept, so it must be that revision's."""
        # What's kept is taken before the await: another read may evict it meanwhile.
        found = {(wid, rev): self._hashes[(wid, rev)] for wid, rev, _ in drafts if (wid, rev) in self._hashes}
        missing = [(wid, rev, draft) for wid, rev, draft in drafts if (wid, rev) not in found]
        if missing:
            computed = await asyncio.to_thread(lambda: [_hash(draft) for _, _, draft in missing])
            found.update({(wid, rev): h for (wid, rev, _), h in zip(missing, computed, strict=True)})
        for key, value in found.items():
            self._hashes[key] = value
            self._hashes.move_to_end(key)
        while len(self._hashes) > self._kept:
            self._hashes.popitem(last=False)
        return {wid: found[(wid, rev)] for wid, rev, _ in drafts}


async def hash_now(draft: Mapping[str, Any]) -> str | None:
    """One draft's hash, off the event loop, kept nowhere: for a draft not yet committed (a save in progress could
    still roll back, and a retry reuse its revision with another draft)."""
    return await asyncio.to_thread(_hash, draft)


HASHES = DraftHashes(kept=4096)  # about 150 bytes each: under 1 MB per API process
