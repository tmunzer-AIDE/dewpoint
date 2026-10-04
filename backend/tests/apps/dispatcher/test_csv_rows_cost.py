# SPDX-License-Identifier: Apache-2.0
"""What a CSV's rows cost a run once they pass 64 KiB (engine 2b spec §8.1, revision 8; the owner's ruling 3): the rows
are one claim, iterated by handle, and the page activity is deferred, so CEL over a plain cell runs in `cel.evaluate`
once per row. This counts that work, at 90 rows: one evaluation per row with a per-row condition, plus the loop's
count, against the count alone without it. It times nothing: the prototype timed 1,000 and 2,500 rows, and the plan's
10,000-row durations are estimates from those."""

from collections import Counter
from collections.abc import AsyncIterator
from typing import Any

import pytest
from sqlalchemy import text
from temporalio.testing import WorkflowEnvironment

from dewpoint.apps.dispatcher import dispatch
from dewpoint.apps.worker.store import DbRunStore
from tests.apps.api.helpers import member_client
from tests.apps.dispatcher.support import BUILD, workers
from tests.apps.dispatcher.test_dev_server import until_ended
from tests.apps.test_admission import KEYS, current, published
from tests.apps.worker.test_real_server import serving
from tests.support.graphs import G, cel, ref
from tests.support.keys import FIXTURE_CONVERTER

pytestmark = pytest.mark.usefixtures("development_deployment")
ROWS = 90  # with an 800-character note each, their list passes 64 KiB: one claim
COLUMNS = [{"header": "Site", "name": "site", "type": "string", "required": True},
           {"header": "Status", "name": "status", "type": "string", "required": True},
           {"header": "Note", "name": "note", "type": "string", "required": True}]  # fmt: skip


@pytest.fixture(scope="module")
async def server() -> AsyncIterator[WorkflowEnvironment]:
    async with await WorkflowEnvironment.start_local(data_converter=FIXTURE_CONVERTER) as environment:
        yield environment


def graph(condition: bool) -> dict[str, Any]:
    g = G().node("l", "flow.loop@1", {"items": ref("trigger.rows")})
    if condition:
        g.node("c", "flow.if@1", {"condition": cel("item.status == 'active'")}).edge("l", "c", "body")
        g.node("e", "testkit.echo@1", {"value": ref("item.site")}).edge("c", "e", "true")
    else:
        g.node("e", "testkit.echo@1", {"value": ref("item.site")}).edge("l", "e", "body")
    return g.data() | {"settings": {"input_schema": {"type": "object", "properties": {}}, "csv": {"columns": COLUMNS}}}


@pytest.mark.parametrize(("condition", "evaluations"), [(True, ROWS + 1), (False, 1)])
async def test_cel_over_a_plain_cell_of_claimed_rows_is_one_evaluation_per_row(
    server, app, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, worker_sessionmaker,
    api_settings, condition: bool, evaluations: int,
) -> None:  # fmt: skip
    app.state.keys = KEYS
    ctx, wf = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings, graph(condition))
    await current(dispatch_sessionmaker)
    await workers(owner_sessionmaker)
    client, _ = await member_client(app, owner_sessionmaker, api_settings, ctx.tenant_id, "operator")
    rows = [f"site-{i},{'active' if i % 2 else 'idle'},{'n' * 800}" for i in range(ROWS)]
    data = ("Site,Status,Note\n" + "\n".join(rows) + "\n").encode()
    base = f"/api/v1/t/{ctx.tenant_id}"
    upload = await client.post(f"{base}/workflows/{wf}/csv-uploads", content=data, headers={"Content-Type": "text/csv"})
    csv = {"upload_id": upload.json()["upload_id"], "mapping": {c["name"]: c["header"] for c in COLUMNS}}
    started = await client.post(f"{base}/workflows/{wf}/runs", headers={"Idempotency-Key": "cost"}, json={"csv": csv})
    assert started.status_code == 202, started.text
    async with owner_sessionmaker() as s:
        largest = (await s.execute(text("select max(length(ciphertext)) from run_inputs where owner_run_id = :r"),
                                   {"r": started.json()["id"]})).scalar_one()  # fmt: skip
    assert largest > 64 * 1024  # the rows are one claim
    async with serving(server.client, DbRunStore(worker_sessionmaker, KEYS)):  # type: ignore[arg-type]
        assert await dispatch.dispatch_once(dispatch_sessionmaker, server.client, KEYS, api_settings, BUILD) == {
            "started": 1
        }
        run = await until_ended(client, f"{base}/runs/{started.json()['id']}")
    assert run["status"] == "succeeded"
    counted: Counter[str] = Counter()
    async for w in server.client.list_workflows(f"WorkflowId STARTS_WITH 't:{ctx.tenant_id}:run:'"):
        for event in (await server.client.get_workflow_handle(w.id, run_id=w.run_id).fetch_history()).events:
            if event.HasField("activity_task_scheduled_event_attributes"):
                counted[event.activity_task_scheduled_event_attributes.activity_type.name] += 1
    assert counted["cel.evaluate"] == evaluations
    assert counted["testkit.echo.v1"] == (ROWS // 2 if condition else ROWS)
