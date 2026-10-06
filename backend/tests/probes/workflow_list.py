# SPDX-License-Identifier: Apache-2.0
"""The workflows list's cost (sub-project 4, B3), the evidence 4b ruling 5 is held on: what its run statistics read
against a tenant's run history, without an index on `workflow_id` and with a candidate one, and what hashing its
drafts costs. Run by hand, never in CI; on a disposable Postgres 16 (testcontainers), synthetic data only. From
`backend/`:

    PYTHONPATH=$PWD/src:$PWD .venv/bin/python -m tests.probes.workflow_list <part> [sizes...]

- `plans`: `workflow_summary.LAST_RUNS` and `.COUNTS_24H`, EXPLAIN (ANALYZE, BUFFERS), for a tenant of 200 workflows
  whose root runs (one in ten simulated, one in twenty failed, spread over 30 days, as many sub-runs again) number
  10k, 100k and 1M by default, beside another tenant's 1M; then the same with the candidate index `runs (workflow_id,
  mode, queued_at DESC, id DESC) WHERE kind = 'run'`, made in the disposable database only (an index in the product
  is a migration: a slot from the owner), and the per-workflow LATERAL read that index would allow;
- `hashing`: `DraftHashes.of()` for 50, 200 and 500 drafts of 30 steps: cold (each parsed), then warm (kept).

Numbers depend on the machine; record them with it."""

import asyncio
import statistics
import sys
import time
import uuid
from typing import Any

from tests.probes.ingress_load import Database, ms

WORKFLOWS = 200
SIZES = (10_000, 100_000, 1_000_000)
CANDIDATE = (
    "create index probe_runs_workflow_last on runs (workflow_id, mode, queued_at desc, id desc) where kind = 'run'"
)
LATERAL = (
    "select w.id as workflow_id, m.mode, r.status, r.at from unnest(cast(:ids as uuid[])) w(id)"
    " cross join (values ('live'), ('simulate')) m(mode) cross join lateral ("
    " select status, coalesce(ended_at, started_at, queued_at) as at from runs where tenant_id = :tenant"
    " and kind = 'run' and workflow_id = w.id and mode = m.mode order by queued_at desc, id desc limit 1) r"
)
ROOTS = (
    "with roots as (insert into runs (id, tenant_id, workflow_id, workflow_version_id, mode, status, queued_at,"
    " iterations, kind) select gen_random_uuid(), cast(:t as uuid),"
    " (cast(:w as uuid[]))[1 + g % cardinality(cast(:w as uuid[]))],"
    " (cast(:v as uuid[]))[1 + g % cardinality(cast(:w as uuid[]))],"
    " case when g % 10 = 0 then 'simulate' else 'live' end,"
    " case when g % 20 = 0 then 'failed' else 'succeeded' end, now() - make_interval(secs => g % 2592000), 0, 'run'"
    " from generate_series(cast(:a as integer), cast(:b as integer)) g"
    " returning id, workflow_id, workflow_version_id, mode, queued_at)"
    " insert into runs (id, tenant_id, workflow_id, workflow_version_id, mode, status, queued_at, iterations, kind,"
    " parent_run_id, parent_step_id) select gen_random_uuid(), cast(:t as uuid), workflow_id, workflow_version_id,"
    " mode, 'succeeded', queued_at, 0, 'subflow', id, gen_random_uuid() from roots where cast(:subs as boolean)"
)


async def tenant_with_workflows(owner: Any, count: int) -> tuple[uuid.UUID, list[uuid.UUID], list[uuid.UUID]]:
    """A tenant with `count` workflows, each with a version (a run names its workflow's own version:
    `runs_version_fk`), seeded as the table owner."""
    from tests.support.workflows import seed_workflow

    tid, wf, version = await seed_workflow(owner, name="W0")
    workflows, versions = [wf], [version]
    for i in range(1, count):
        _, wf, version = await seed_workflow(owner, tenant_id=tid, name=f"W{i}")
        workflows.append(wf)
        versions.append(version)
    return tid, workflows, versions


async def grow(
    owner: Any, tid: uuid.UUID, workflows: list[uuid.UUID], versions: list[uuid.UUID], a: int, b: int, *, subs: bool
) -> None:
    from sqlalchemy import text

    async with owner() as s, s.begin():
        await s.execute(text(ROOTS), {"t": tid, "w": workflows, "v": versions, "a": a, "b": b, "subs": subs})
    async with owner() as s, s.begin():
        await s.execute(text("analyze runs"))


async def explain(api: Any, tid: uuid.UUID, sql: str, params: dict[str, Any]) -> tuple[float, str]:
    """The statement's plan, executed as the list runs it: the API's role, in the tenant's scope, under row-level
    security (the owner's session would bypass it). Answers (execution time in seconds, the plan's text)."""
    from sqlalchemy import text

    from dewpoint.core.db import tenant_scope

    async with api() as s, s.begin():
        await tenant_scope(s, tid)
        rows = [r[0] for r in await s.execute(text(f"explain (analyze, buffers) {sql}"), params)]
    took = next(float(r.split(":")[1].split()[0]) for r in rows if r.startswith("Execution Time"))
    return took / 1000, "\n".join(rows)


async def plans(db: Database, sizes: tuple[int, ...] = SIZES) -> None:
    from dewpoint.apps import workflow_summary as summary

    owner, api = db.sessions(), db.sessions("dewpoint_api")
    tid, workflows, versions = await tenant_with_workflows(owner, WORKFLOWS)
    noise, noise_workflows, noise_versions = await tenant_with_workflows(owner, WORKFLOWS)
    started = time.perf_counter()
    await grow(owner, noise, noise_workflows, noise_versions, 1, max(sizes), subs=False)
    print(f"another tenant's {max(sizes):,} root runs inserted and analyzed in {time.perf_counter() - started:.1f} s")
    params = {"tenant": tid, "ids": workflows}
    reads = {"last runs (DISTINCT ON)": summary.LAST_RUNS.text, "24 h counts": summary.COUNTS_24H.text}
    done = 0
    for size in sizes:
        started = time.perf_counter()
        await grow(owner, tid, workflows, versions, done + 1, size, subs=True)
        print(f"\n{size:,} root runs (and as many sub-runs) reached in {time.perf_counter() - started:.1f} s")
        done = size
        for label, sql in reads.items():
            took = statistics.median([(await explain(api, tid, sql, params))[0] for _ in range(5)])
            print(f"\n### {size:,} root runs, no index: {label}, median of 5: {ms(took)}")
            print((await explain(api, tid, sql, params))[1])
    from sqlalchemy import text

    async with owner() as s, s.begin():
        await s.execute(text(CANDIDATE))
        await s.execute(text("analyze runs"))
    for label, sql in {**reads, "last runs (LATERAL)": LATERAL}.items():
        took = statistics.median([(await explain(api, tid, sql, params))[0] for _ in range(5)])
        print(f"\n### {done:,} root runs, candidate index: {label}, median of 5: {ms(took)}")
        print((await explain(api, tid, sql, params))[1])


async def hashing() -> None:
    from dewpoint.apps.workflow_summary import DraftHashes
    from tests.support.graphs import G

    def draft(n: int) -> dict[str, Any]:
        g = G()
        for i in range(n):
            g.node(f"s{i}", "flow.transform@1", {"fields": {"v": i}})
            if i:
                g.edge(f"s{i - 1}", f"s{i}")
        return g.data()

    print("| drafts of 30 steps | cold | warm |\n|---|---|---|")
    for count in (50, 200, 500):
        drafts = [(uuid.uuid4(), 1, draft(30)) for _ in range(count)]
        hashes = DraftHashes(kept=4096)
        start = time.perf_counter()
        await hashes.of(drafts)
        cold = time.perf_counter() - start
        start = time.perf_counter()
        await hashes.of(drafts)
        print(f"| {count} | {ms(cold)} | {ms(time.perf_counter() - start)} |")


def run(part: str, *args: str) -> None:
    if part == "hashing":
        asyncio.run(hashing())
        return
    sizes = tuple(int(a) for a in args) or SIZES
    with Database() as db:

        async def go() -> None:
            await db.prepared()
            await plans(db, sizes)

        asyncio.run(go())


if __name__ == "__main__":
    run(*sys.argv[1:])
