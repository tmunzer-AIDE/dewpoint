# SPDX-License-Identifier: Apache-2.0
"""The summary a run's page polls costs the same few statements whatever the run's size (the runs design §4.4): a run
of 100,000 instances is summarized in three, its counts grouped by the database, never read row by row."""

import uuid
from typing import Any

import pytest
from sqlalchemy import event, text
from sqlalchemy.engine import Engine

from dewpoint.apps import step_summary
from dewpoint.core.db import tenant_scope
from dewpoint.core.runs import service
from tests.support.graphs import nid
from tests.support.workflows import seed_workflow

pytestmark = pytest.mark.usefixtures("development_deployment")
INSTANCES = 100_000
NODES = [{"id": str(nid("l")), "key": "l", "type": "flow.loop@1"},
         {"id": str(nid("x")), "key": "x", "type": "testkit.echo@1"}]  # fmt: skip


async def test_a_run_of_100000_instances_is_summarized_in_three_statements(
    owner_sessionmaker, dispatch_sessionmaker, api_sessionmaker
) -> None:
    tenant, wf, version = await seed_workflow(owner_sessionmaker)
    run_id = uuid.uuid4()
    async with dispatch_sessionmaker() as s, s.begin():
        await tenant_scope(s, tenant)
        await service.insert_run(s, run_id=run_id, tenant_id=tenant, workflow_id=wf, version_id=version, mode="live")
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(text(
            "insert into run_steps (tenant_id, run_id, step_id, iteration_key, attempt, node_key, status, started_at, "
            "ended_at, outcome) select :t, :r, :x, 'l:' || g, 1, 'x', 'succeeded', now(), now(), 'applied' "
            "from generate_series(0, :n - 1) g"
        ), {"t": tenant, "r": run_id, "x": nid("x"), "n": INSTANCES})  # fmt: skip
        await s.execute(text("insert into run_steps (tenant_id, run_id, step_id, iteration_key, attempt, node_key, "
                             "status, started_at, ended_at) "
                             "values (:t, :r, :l, '', 1, 'l', 'succeeded', now(), now())"),
                        {"t": tenant, "r": run_id, "l": nid("l")})  # fmt: skip
    seen: list[str] = []

    def on(conn: Any, cursor: Any, statement: str, parameters: Any, context: Any, executemany: bool) -> None:
        if "run_steps" in statement:
            seen.append(statement)

    async with api_sessionmaker() as s, s.begin():
        await tenant_scope(s, tenant)
        event.listen(Engine, "before_cursor_execute", on)
        try:
            summarized = await step_summary.summarize(s, run_id, NODES, ended=True, error_code=None, live=True)
        finally:
            event.remove(Engine, "before_cursor_execute", on)
    counted = {x.key: (x.instances, x.origin, x.final is not None) for x in summarized}
    assert counted == {"l": (1, None, True), "x": (INSTANCES, "sent", False)}
    assert len(seen) == 3  # the counts, the first starts, the single instances' final attempts
