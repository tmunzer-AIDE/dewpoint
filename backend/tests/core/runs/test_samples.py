# SPDX-License-Identifier: Apache-2.0
"""A step's newest sample (B7; 4c-2a rulings 9, 10): which run, which row, which connections, within retention and
the tenant."""

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import text

from dewpoint.core.db import tenant_scope
from dewpoint.core.retention.cutoff import cutoff
from dewpoint.core.runs import samples
from tests.support.connections import Seeded, add_connection, seed_step
from tests.support.registry import sync_test_plugins

NOW = datetime.now(UTC)


@pytest.fixture(autouse=True)
async def synced(admin_sessionmaker) -> None:
    await sync_test_plugins(admin_sessionmaker)  # a step's connection fields come from its type (ruling 10)


async def _run(
    owner: Any, seeded: Seeded, *, status: str = "succeeded", ago: int = 0, mode: str = "live",
    parent: uuid.UUID | None = None,
) -> uuid.UUID:  # fmt: skip
    """Another run of `seeded`'s workflow and version, queued `ago` minutes back; a sub-flow's when it has a parent."""
    run = uuid.uuid4()
    async with owner() as s, s.begin():
        wf = (await s.execute(text("select workflow_id from runs where id = :r"), {"r": seeded.run})).scalar_one()
        await s.execute(
            text(
                "insert into runs (id, tenant_id, workflow_id, workflow_version_id, mode, status, queued_at, ended_at, "
                "kind, parent_run_id) values (:i, :t, :w, :v, :m, :st, :q, :e, :k, :p)"
            ),
            {"i": run, "t": seeded.tenant, "w": wf, "v": seeded.version, "m": mode, "st": status,
             "q": NOW - timedelta(minutes=ago), "e": None if status == "running" else NOW - timedelta(minutes=ago),
             "k": "run" if parent is None else "subflow", "p": parent},
        )  # fmt: skip
    return run


async def _row(
    owner: Any, seeded: Seeded, run: uuid.UUID, *, iteration: str = "", attempt: int = 1, status: str = "succeeded",
    output: Any = None, ended: datetime | None = None,
) -> None:  # fmt: skip
    async with owner() as s, s.begin():
        await s.execute(
            text(
                "insert into run_steps (tenant_id, run_id, step_id, iteration_key, attempt, node_key, status, "
                "ended_at, output_preview) values (:t, :r, :s, :i, :a, 'call', :st, :e, cast(:o as jsonb))"
            ),
            {"t": seeded.tenant, "r": run, "s": seeded.step, "i": iteration, "a": attempt, "st": status,
             "e": ended or NOW, "o": json.dumps(output if output is not None else {"n": attempt})},
        )  # fmt: skip


async def _search(api: Any, seeded: Seeded, iteration: str | None = None) -> samples.Search:
    async with api() as s, s.begin():
        await tenant_scope(s, seeded.tenant)
        wf = (await s.execute(text("select workflow_id from runs where id = :r"), {"r": seeded.run})).scalar_one()
        return await samples.newest(s, seeded.tenant, wf, seeded.step, iteration_key=iteration,
                                    at=await cutoff(s, seeded.tenant))  # fmt: skip


async def _newest(api: Any, seeded: Seeded, iteration: str | None = None) -> samples.Sample | None:
    return (await _search(api, seeded, iteration)).sample


async def test_takes_the_newest_succeeded_row_of_an_ended_run(owner_sessionmaker, api_sessionmaker) -> None:
    seeded = await seed_step(owner_sessionmaker, named=[None])  # its own run is still running: never a candidate
    old, new = await _run(owner_sessionmaker, seeded, ago=10), await _run(owner_sessionmaker, seeded, ago=5)
    failed = await _run(owner_sessionmaker, seeded, ago=1)
    await _row(owner_sessionmaker, seeded, old, output={"v": "old"})
    await _row(owner_sessionmaker, seeded, new, output={"v": "new"})
    await _row(owner_sessionmaker, seeded, failed, status="failed")
    await _row(owner_sessionmaker, seeded, seeded.run, output={"v": "running"})
    found = await _newest(api_sessionmaker, seeded)
    assert found is not None and found.run_id == new and found.output == {"v": "new"}


async def test_takes_the_first_iteration_by_number_not_by_text(owner_sessionmaker, api_sessionmaker) -> None:
    seeded = await seed_step(owner_sessionmaker, named=[None])
    run = await _run(owner_sessionmaker, seeded)
    for key in ("l:10", "l:2"):
        await _row(owner_sessionmaker, seeded, run, iteration=key, output={"k": key})
    found = await _newest(api_sessionmaker, seeded)
    assert found is not None and found.iteration_key == "l:2"
    asked = await _newest(api_sessionmaker, seeded, iteration="l:10")
    assert asked is not None and asked.output == {"k": "l:10"}


async def test_takes_the_highest_attempt(owner_sessionmaker, api_sessionmaker) -> None:
    seeded = await seed_step(owner_sessionmaker, named=[None])
    run = await _run(owner_sessionmaker, seeded)
    await _row(owner_sessionmaker, seeded, run, attempt=1, status="failed")
    await _row(owner_sessionmaker, seeded, run, attempt=2)
    found = await _newest(api_sessionmaker, seeded)
    assert found is not None and found.attempt == 2


async def test_answers_a_sub_flows_run_of_this_workflow(owner_sessionmaker, api_sessionmaker) -> None:
    seeded = await seed_step(owner_sessionmaker, named=[None])
    parent = await _run(owner_sessionmaker, seeded, ago=20)  # any root run will do as the parent here
    child = await _run(owner_sessionmaker, seeded, parent=parent)
    await _row(owner_sessionmaker, seeded, child)
    found = await _newest(api_sessionmaker, seeded)
    assert found is not None and (found.run_id, found.run_kind) == (child, "subflow")


async def test_never_answers_from_a_run_past_retention(owner_sessionmaker, api_sessionmaker) -> None:
    seeded = await seed_step(owner_sessionmaker, named=[None])
    run = await _run(owner_sessionmaker, seeded, ago=60 * 24 * 400)  # ended 400 days ago: past any retention
    await _row(owner_sessionmaker, seeded, run)
    assert await _newest(api_sessionmaker, seeded) is None


async def test_never_answers_another_tenants_run(owner_sessionmaker, api_sessionmaker) -> None:
    mine, theirs = await seed_step(owner_sessionmaker, named=[None]), await seed_step(owner_sessionmaker, named=[None])
    await _row(owner_sessionmaker, theirs, await _run(owner_sessionmaker, theirs))
    async with owner_sessionmaker() as s:
        their_wf = (await s.execute(text("select workflow_id from runs where id = :r"), {"r": theirs.run})).scalar_one()
    async with api_sessionmaker() as s, s.begin():
        await tenant_scope(s, mine.tenant)
        at = await cutoff(s, mine.tenant)
        for tenant in (
            mine.tenant,
            theirs.tenant,
        ):  # their ids, asked from my tenant: row-level security and the filter
            assert (await samples.newest(s, tenant, their_wf, theirs.step, iteration_key=None, at=at)).sample is None
    assert await _newest(api_sessionmaker, theirs) is not None  # and from theirs, it's there


async def test_says_what_each_connection_is_now(owner_sessionmaker, api_sessionmaker) -> None:
    seeded = await seed_step(owner_sessionmaker, named=[None])
    same = await add_connection(owner_sessionmaker, seeded.tenant)
    changed = await add_connection(owner_sessionmaker, seeded.tenant)
    gone = await add_connection(owner_sessionmaker, seeded.tenant)
    run = await _run(owner_sessionmaker, seeded)
    await _row(owner_sessionmaker, seeded, run)
    async with owner_sessionmaker() as s, s.begin():
        for cid in (same, changed, gone):
            await s.execute(
                text("insert into run_step_connections (tenant_id, run_id, step_id, iteration_key, attempt, "
                     "connection_id, type, name, revision) values (:t, :r, :s, '', 1, :c, 'testkit', 'Then', 1)"),
                {"t": seeded.tenant, "r": run, "s": seeded.step, "c": cid},
            )  # fmt: skip
        await s.execute(text("update connections set revision = 2, name = 'Renamed' where id = :c"), {"c": changed})
        await s.execute(text("update connections set name = 'Renamed too' where id = :c"), {"c": same})
        await s.execute(text("delete from connections where id = :c"), {"c": gone})
    found = await _newest(api_sessionmaker, seeded)
    assert found is not None
    states = {c.connection_id: (c.state, c.name) for c in found.connections}
    assert states == {same: ("unchanged", "Renamed too"), changed: ("changed", "Renamed"), gone: ("deleted", "Then")}


async def _ended_runs(owner: Any, seeded: Seeded, n: int, *, ended: bool = True) -> None:
    """`n` newer runs of the workflow without the step: ended a second apart, or not ended at all."""
    async with owner() as s, s.begin():
        wf = (await s.execute(text("select workflow_id from runs where id = :r"), {"r": seeded.run})).scalar_one()
        await s.execute(
            text(
                "insert into runs (id, tenant_id, workflow_id, workflow_version_id, mode, status, queued_at, ended_at) "
                "select gen_random_uuid(), :t, :w, :v, 'live', 'succeeded', now(), "
                "case when :ended then now() - make_interval(secs => n) end from generate_series(1, :n) as n"
            ),
            {"t": seeded.tenant, "w": wf, "v": seeded.version, "n": n, "ended": ended},
        )


async def test_takes_the_newest_captured_row_not_the_newest_run(owner_sessionmaker, api_sessionmaker) -> None:
    """B7's "newest succeeded row": a run that ended later may hold an older row."""
    seeded = await seed_step(owner_sessionmaker, named=[None])
    later, earlier = await _run(owner_sessionmaker, seeded, ago=1), await _run(owner_sessionmaker, seeded, ago=5)
    await _row(owner_sessionmaker, seeded, later, output={"v": "older row"}, ended=NOW - timedelta(minutes=60))
    await _row(owner_sessionmaker, seeded, earlier, output={"v": "newer row"}, ended=NOW - timedelta(minutes=2))
    found = await _newest(api_sessionmaker, seeded)
    assert found is not None and found.output == {"v": "newer row"}


async def test_runs_that_havent_ended_never_fill_the_window(owner_sessionmaker, api_sessionmaker) -> None:
    seeded = await seed_step(owner_sessionmaker, named=[None])
    await _row(owner_sessionmaker, seeded, await _run(owner_sessionmaker, seeded, ago=10))
    await _ended_runs(owner_sessionmaker, seeded, samples.SCAN_RUNS, ended=False)  # newer, but no end recorded
    search = await _search(api_sessionmaker, seeded)
    assert search.sample is not None and search.searched == 1


async def test_says_how_many_runs_it_searched(owner_sessionmaker, api_sessionmaker) -> None:
    seeded = await seed_step(owner_sessionmaker, named=[None])
    await _row(owner_sessionmaker, seeded, await _run(owner_sessionmaker, seeded, ago=60))  # older than all below
    await _ended_runs(owner_sessionmaker, seeded, samples.SCAN_RUNS)
    search = await _search(api_sessionmaker, seeded)
    assert search.sample is None and search.searched == samples.SCAN_RUNS  # none in the window, not "never"


async def test_names_a_connection_only_through_a_field_its_type_marks(owner_sessionmaker, api_sessionmaker) -> None:
    """The worker's own rule: a connection field of the step's type. Text that happens to hold an id isn't one."""
    seeded = await seed_step(owner_sessionmaker, named=[None])
    cid = await add_connection(owner_sessionmaker, seeded.tenant)
    named = await seed_step(owner_sessionmaker, named=[cid], tenant=seeded.tenant)  # `call` names it, as http_call does
    version = uuid.uuid4()
    echo = {"id": str(seeded.step), "key": "call", "type": "testkit.echo@1", "config": {"value": str(cid)}}
    async with owner_sessionmaker() as s, s.begin():
        wf = (await s.execute(text("select workflow_id from runs where id = :r"), {"r": seeded.run})).scalar_one()
        await s.execute(
            text(
                "insert into workflow_versions (id, tenant_id, workflow_id, number, graph, node_refs, engine_abi, "
                "cel_profile, input_schema, output_schema, vars_schema, closure_version_ids, closure_workflow_ids, "
                "closure_node_refs, closure_cel_profiles, closure_depth, graph_hash, version_hash, connection_ids) "
                "select :v, tenant_id, workflow_id, 2, cast(:g as jsonb), node_refs, engine_abi, cel_profile, "
                "input_schema, output_schema, vars_schema, array[cast(:v as uuid)], closure_workflow_ids, "
                "closure_node_refs, closure_cel_profiles, closure_depth, 'h2', 'h2', array[cast(:c as uuid)] "
                "from workflow_versions where id = :old"
            ),
            {"v": version, "g": json.dumps({"graph_format": 1, "nodes": [echo], "edges": []}), "c": cid,
             "old": seeded.version},
        )  # fmt: skip
        await s.execute(text("insert into runs (id, tenant_id, workflow_id, workflow_version_id, mode, status, "
                             "ended_at) values (:r, :t, :w, :v, 'live', 'succeeded', now())"),
                        {"r": (run := uuid.uuid4()), "t": seeded.tenant, "w": wf, "v": version})  # fmt: skip
    await _row(owner_sessionmaker, seeded, run)
    found = await _newest(api_sessionmaker, seeded)
    assert found is not None and found.node is not None and not found.names_connection
    await _row(owner_sessionmaker, named, await _run(owner_sessionmaker, named))
    their = await _newest(api_sessionmaker, named)
    assert their is not None and their.names_connection


async def test_counts_the_search_in_the_same_statement_as_its_answer(owner_sessionmaker, api_sessionmaker) -> None:
    """One statement, one snapshot: a run ending between a count and a search would make them disagree (the review of
    revision 2). So exactly one statement reads the candidate runs, and it both counts and chooses."""
    from sqlalchemy import event

    seeded = await seed_step(owner_sessionmaker, named=[None])
    await _row(owner_sessionmaker, seeded, await _run(owner_sessionmaker, seeded))
    statements: list[str] = []
    async with api_sessionmaker() as s, s.begin():
        await tenant_scope(s, seeded.tenant)
        wf = (await s.execute(text("select workflow_id from runs where id = :r"), {"r": seeded.run})).scalar_one()
        at = await cutoff(s, seeded.tenant)
        connection = await s.connection()

        def seen(_c: Any, _cursor: Any, statement: str, *_: Any) -> None:
            statements.append(statement)

        event.listen(connection.sync_connection, "before_cursor_execute", seen)
        try:
            search = await samples.newest(s, seeded.tenant, wf, seeded.step, iteration_key=None, at=at)
        finally:
            event.remove(connection.sync_connection, "before_cursor_execute", seen)
    reading = [st for st in statements if "candidates" in st]
    assert len(reading) == 1 and "count(" in reading[0].lower()
    assert search.sample is not None and search.searched == 1
