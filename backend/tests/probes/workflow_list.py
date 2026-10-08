# SPDX-License-Identifier: Apache-2.0
"""The workflows list's cost (sub-project 4, B3), the evidence for 4b ruling 5: what its run statistics read against
a tenant's run history, with `runs_workflow_last` (migration 0047), and what hashing its drafts costs. Run by hand,
never in CI; on a disposable Postgres 16 (testcontainers), migrated to head, synthetic data only. From `backend/`:

    PYTHONPATH=$PWD/src:$PWD .venv/bin/python -m tests.probes.workflow_list <part> [sizes...]

- `plans`: EXPLAIN (ANALYZE, BUFFERS) of the product's `LAST_RUNS` (one batched LATERAL statement, the mode a lower
  bound: ledger M5) beside the same LATERAL with the mode as an equality and the DISTINCT ON statement 0047
  replaced, and of `COUNTS_24H`, for a tenant of 200 workflows, 20 of them quiet (listed, never run). Its root runs
  number 10k, 100k and 1M by default (as many sub-runs again), beside another tenant's 1M. A run's mode and status
  follow its turn within its workflow, never the workflow: each active workflow has runs of both modes (one turn in
  ten simulated), and failures in both (one turn in seven). Its newest live runs share a timestamp, two by two, so
  the id orders them. At each size the three last-runs statements' whole results are asserted equal.
- `skew`: the history that turned the planner when the mode was an equality: a tenant of two workflows, one with live
  root runs only (100k and 1M by default), one quiet, analyzed, alone in its database. The same three statements,
  their results asserted equal.
- `hashing`: `DraftHashes.of()` for 50, 200 and 500 drafts of 30 steps: cold (each parsed), then warm (kept).

Numbers depend on the machine; record them with it."""

import asyncio
import statistics
import sys
import time
import uuid
from typing import Any

from tests.probes.ingress_load import Database, ms

WORKFLOWS, ACTIVE = 200, 180  # the last 20 are quiet
SIZES = (10_000, 100_000, 1_000_000)
SKEW_SIZES = (100_000, 1_000_000)
# The statement 0047's read replaced, and the LATERAL read with the mode as an equality (ledger M5): kept to compare.
DISTINCT_ON = (
    "select distinct on (workflow_id, mode) workflow_id, mode, status, coalesce(ended_at, started_at, queued_at) as at"
    " from runs where tenant_id = :tenant and kind = 'run' and workflow_id = any(cast(:ids as uuid[]))"
    " order by workflow_id, mode, queued_at desc, id desc"
)
LATERAL_EQUALITY = (
    "select w.id as workflow_id, m.mode, r.status, r.at"
    " from unnest(cast(:ids as uuid[])) as w(id) cross join (values ('live'), ('simulate')) as m(mode)"
    " cross join lateral (select status, coalesce(ended_at, started_at, queued_at) as at from runs"
    " where tenant_id = :tenant and kind = 'run' and workflow_id = w.id and mode = m.mode"
    " order by queued_at desc, id desc limit 1) as r"
)
# Run g is turn q = g / active of workflow g % active: simulated when q % 10 = 0, failed when q % 7 = 3; turns 2t-1
# and 2t share a timestamp (180 s apart from the next pair), so the newest live run (turn 1) ties with turn 2.
ROOTS = (
    "with roots as (insert into runs (id, tenant_id, workflow_id, workflow_version_id, mode, status, queued_at,"
    " iterations, kind) select gen_random_uuid(), cast(:t as uuid),"
    " (cast(:w as uuid[]))[1 + g % cast(:active as integer)], (cast(:v as uuid[]))[1 + g % cast(:active as integer)],"
    " case when (g / cast(:active as integer)) % 10 = 0 then 'simulate' else 'live' end,"
    " case when (g / cast(:active as integer)) % 7 = 3 then 'failed' else 'succeeded' end,"
    " now() - make_interval(secs => ((g / cast(:active as integer) + 1) / 2 * 180) % 2592000), 0, 'run'"
    " from generate_series(cast(:a as integer), cast(:b as integer)) g"
    " returning id, workflow_id, workflow_version_id, mode, queued_at)"
    " insert into runs (id, tenant_id, workflow_id, workflow_version_id, mode, status, queued_at, iterations, kind,"
    " parent_run_id, parent_step_id) select gen_random_uuid(), cast(:t as uuid), workflow_id, workflow_version_id,"
    " mode, 'succeeded', queued_at, 0, 'subflow', id, gen_random_uuid() from roots where cast(:subs as boolean)"
)
LIVE_ONLY = (
    "insert into runs (id, tenant_id, workflow_id, workflow_version_id, mode, status, queued_at, iterations, kind)"
    " select gen_random_uuid(), cast(:t as uuid), cast(:w as uuid), cast(:v as uuid), 'live', 'succeeded',"
    " now() - make_interval(secs => g % 2592000), 0, 'run'"
    " from generate_series(cast(:a as integer), cast(:b as integer)) g"
)


async def tenant_with_workflows(owner: Any, count: int) -> tuple[uuid.UUID, list[uuid.UUID], list[uuid.UUID]]:
    """A tenant with `count` workflows, each with a version (a run's version is its workflow's: `runs_version_fk`),
    seeded as the table owner."""
    from tests.support.workflows import seed_workflow

    tid, wf, version = await seed_workflow(owner, name="W0")
    workflows, versions = [wf], [version]
    for i in range(1, count):
        _, wf, version = await seed_workflow(owner, tenant_id=tid, name=f"W{i}")
        workflows.append(wf)
        versions.append(version)
    return tid, workflows, versions


async def write(owner: Any, sql: str, params: dict[str, Any]) -> None:
    from sqlalchemy import text

    async with owner() as s, s.begin():
        await s.execute(text(sql), params)
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


async def answers(api: Any, tid: uuid.UUID, sql: str, params: dict[str, Any]) -> list[tuple[Any, ...]]:
    from sqlalchemy import text

    from dewpoint.core.db import tenant_scope

    async with api() as s, s.begin():
        await tenant_scope(s, tid)
        return sorted(tuple(r) for r in await s.execute(text(sql), params))


async def measured(api: Any, tid: uuid.UUID, heading: str, reads: dict[str, str], params: dict[str, Any]) -> None:
    """Each read's median of 5 and its plan; then the last-runs reads' whole results, asserted equal."""
    for label, sql in reads.items():
        took = statistics.median([(await explain(api, tid, sql, params))[0] for _ in range(5)])
        print(f"\n### {heading}: {label}, median of 5: {ms(took)}")
        print((await explain(api, tid, sql, params))[1])
    found = {label: await answers(api, tid, sql, params) for label, sql in reads.items() if label.startswith("last")}
    first = next(iter(found.values()))
    assert all(rows == first for rows in found.values()), "the last-runs reads disagree"
    modes = [row[1] for row in first]
    print(f"\n{heading}: the {len(found)} last-runs reads agree whole: {len(first)} rows,"
          f" {modes.count('live')} live and {modes.count('simulate')} simulated")  # fmt: skip


def last_runs_reads() -> dict[str, str]:
    from dewpoint.apps import workflow_summary as summary

    return {
        "last runs (product: LATERAL, mode from below)": summary.LAST_RUNS.text,
        "last runs (LATERAL, mode as an equality)": LATERAL_EQUALITY,
        "last runs (DISTINCT ON, the statement replaced)": DISTINCT_ON,
    }


async def has_index(owner: Any) -> None:
    from sqlalchemy import text

    async with owner() as s:
        found = await s.execute(text("select 1 from pg_indexes where indexname = 'runs_workflow_last'"))
        assert found.scalar_one_or_none() == 1, "migration 0047 isn't applied"


async def plans(db: Database, sizes: tuple[int, ...] = SIZES) -> None:
    from dewpoint.apps import workflow_summary as summary

    owner, api = db.sessions(), db.sessions("dewpoint_api")
    await has_index(owner)
    tid, workflows, versions = await tenant_with_workflows(owner, WORKFLOWS)
    noise, noise_workflows, noise_versions = await tenant_with_workflows(owner, WORKFLOWS)
    started = time.perf_counter()
    grow = {"active": ACTIVE, "subs": False, "a": 1, "b": max(sizes)}
    await write(owner, ROOTS, {"t": noise, "w": noise_workflows, "v": noise_versions, **grow})
    print(f"another tenant's {max(sizes):,} root runs inserted and analyzed in {time.perf_counter() - started:.1f} s")
    params = {"tenant": tid, "ids": workflows}
    reads = {**last_runs_reads(), "24 h counts": summary.COUNTS_24H.text}
    done = 0
    for size in sizes:
        started = time.perf_counter()
        grow = {"active": ACTIVE, "subs": True, "a": done + 1, "b": size}
        await write(owner, ROOTS, {"t": tid, "w": workflows, "v": versions, **grow})
        print(f"\n{size:,} root runs (and as many sub-runs) reached in {time.perf_counter() - started:.1f} s")
        done = size
        await measured(
            api, tid, f"{size:,} root runs, {WORKFLOWS - ACTIVE} of {WORKFLOWS} workflows quiet", reads, params
        )


async def skew(db: Database, sizes: tuple[int, ...] = SKEW_SIZES) -> None:
    owner, api = db.sessions(), db.sessions("dewpoint_api")
    await has_index(owner)
    tid, workflows, versions = await tenant_with_workflows(owner, 2)
    params = {"tenant": tid, "ids": workflows}  # the second is quiet
    done = 0
    for size in sizes:
        started = time.perf_counter()
        await write(owner, LIVE_ONLY, {"t": tid, "w": workflows[0], "v": versions[0], "a": done + 1, "b": size})
        print(f"\n{size:,} live root runs of one workflow reached in {time.perf_counter() - started:.1f} s")
        done = size
        await measured(api, tid, f"{size:,} live root runs, one workflow quiet", last_runs_reads(), params)


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
    probe = {"plans": plans, "skew": skew}[part]
    sizes = tuple(int(a) for a in args) or (SIZES if part == "plans" else SKEW_SIZES)
    with Database() as db:

        async def go() -> None:
            await db.prepared()
            await probe(db, sizes)

        asyncio.run(go())


if __name__ == "__main__":
    run(*sys.argv[1:])
