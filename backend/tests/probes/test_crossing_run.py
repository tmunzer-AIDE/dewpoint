# SPDX-License-Identifier: Apache-2.0
"""A whole run whose crossings grant 10,000 claims, end to end on the dev server (the owner's ruling on 2b-4b's M3
checkpoint: the 1.75 s measured `test_crossing_load.py` ran the grant activity's code alone). A CSV start of `ROWS`
sites, each with its pre-shared key (sensitive: a claim each, its text in the run tree's secret index; the rows
together one claim nesting them), runs a sub-flow with its rows, which runs another with them: two crossings, the
first of claims its run owns, the second of claims its run holds by grant. Each is `claims.child_input`: the input
resolved and checked against the child's schema, split, and its handles' closure granted, within the activity's
one-minute timeout. One dispatcher pass starts the root; a real engine worker (`DbRunStore`) runs all three.

Per run: its status and its time; per crossing: its activity's time and attempts (from its parent's history) and the
claims it granted.

A probe, run by hand on a quiet machine, never in CI; bounded by `DEADLINE_S`. `DEWPOINT_PROBE_ROWS` makes it smaller,
to check the probe itself. From `backend/`:

    DEWPOINT_PROBE=1 [DEWPOINT_PROBE_ROWS=10000] [DEWPOINT_PROBE_OUT=FILE] .venv/bin/pytest -p no:cacheprovider \\
        -n 0 -s tests/probes/test_crossing_run.py

Numbers depend on the machine; record them with it."""

import asyncio
import json
import os
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text
from temporalio.testing import WorkflowEnvironment

from dewpoint.apps.dispatcher import dispatch
from dewpoint.apps.worker.store import DbRunStore
from dewpoint.engine.runtime.activities import CLAIMS_CHILD_INPUT
from dewpoint.engine.runtime.ids import run_workflow_id
from tests.apps.api.helpers import member_client
from tests.apps.dispatcher.support import BUILD, workers
from tests.apps.test_admission import KEYS, current, published
from tests.apps.test_workflow_ops import create, publish
from tests.apps.worker.test_real_server import serving
from tests.support.graphs import G, ref
from tests.support.keys import FIXTURE_CONVERTER
from tests.support.temporal import start_local

pytestmark = [
    pytest.mark.skipif(not os.environ.get("DEWPOINT_PROBE"), reason="a probe, run by hand (DEWPOINT_PROBE)"),
    pytest.mark.usefixtures("development_deployment"),
]
ROWS = int(os.environ.get("DEWPOINT_PROBE_ROWS", "10000"))
DEADLINE_S = float(os.environ.get("DEWPOINT_PROBE_DEADLINE_S", "600"))
COLUMNS = [{"header": "Site", "name": "site", "type": "string", "required": True},
           {"header": "PSK", "name": "psk", "type": "string", "required": True, "sensitive": True}]  # fmt: skip
SITES_SCHEMA = {  # a sub-flow's input: the rows, as `sites` (`rows` is a CSV's own name)
    "type": "object",
    "properties": {
        "sites": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"site": {"type": "string"}, "psk": {"type": "string", "x-sensitive": True}},
                "additionalProperties": False,
            },
        }
    },
    "required": ["sites"],
    "additionalProperties": False,
}


@pytest.fixture(scope="module")
async def server() -> AsyncIterator[WorkflowEnvironment]:
    async with await start_local(data_converter=FIXTURE_CONVERTER) as environment:
        yield environment


def calling(workflow_id: Any, sites: str) -> G:
    return G().node("s", "flow.run_workflow@1", {"workflow_id": str(workflow_id), "input": {"sites": ref(sites)}})


async def crossings(client: Any, tenant_id: str, run_id: str) -> list[dict[str, Any]]:
    """A run's `claims.child_input` activities: each one's time from its scheduling to its end, its last attempt, and
    whether it completed."""
    history = await client.get_workflow_handle(run_workflow_id(tenant_id, run_id)).fetch_history()
    found: dict[int, dict[str, Any]] = {}
    for event in history.events:
        at = event.event_time.ToDatetime()
        if event.HasField("activity_task_scheduled_event_attributes"):
            if event.activity_task_scheduled_event_attributes.activity_type.name == CLAIMS_CHILD_INPUT:
                found[event.event_id] = {"scheduled": at}
        elif event.HasField("activity_task_started_event_attributes"):
            started = event.activity_task_started_event_attributes
            if started.scheduled_event_id in found:
                found[started.scheduled_event_id]["attempt"] = started.attempt
        else:
            for kind in ("completed", "failed", "timed_out"):
                if event.HasField(f"activity_task_{kind}_event_attributes"):
                    ended = getattr(event, f"activity_task_{kind}_event_attributes")
                    if ended.scheduled_event_id in found:
                        one = found[ended.scheduled_event_id]
                        one.update(ended=kind, s=round((at - one.pop("scheduled")).total_seconds(), 2))
    return list(found.values())


async def test_a_whole_run_whose_crossings_grant_ten_thousand_claims(
    server, app, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, worker_sessionmaker,
    api_settings,
) -> None:  # fmt: skip
    app.state.keys = KEYS
    leaf = G().node("e", "testkit.echo@1", {"value": 1}).data() | {"settings": {"input_schema": SITES_SCHEMA}}
    ctx, leaf_wf = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings, leaf)
    middle = calling(leaf_wf, "trigger.sites").data() | {"settings": {"input_schema": SITES_SCHEMA}}
    middle_wf = await create(api_sessionmaker, ctx, middle, name="middle")
    assert (await publish(api_sessionmaker, ctx, middle_wf, api_settings)).version is not None
    root_settings = {"input_schema": {"type": "object", "properties": {}}, "csv": {"columns": COLUMNS}}
    root = calling(middle_wf, "trigger.rows").data() | {"settings": root_settings}
    root_wf = await create(api_sessionmaker, ctx, root, name="root")
    assert (await publish(api_sessionmaker, ctx, root_wf, api_settings)).version is not None
    await current(dispatch_sessionmaker)
    await workers(owner_sessionmaker)

    client, _ = await member_client(app, owner_sessionmaker, api_settings, ctx.tenant_id, "operator")
    data = ("Site,PSK\n" + "".join(f"site-{i:05d},psk-{i:05d}-{os.urandom(6).hex()}\n" for i in range(ROWS))).encode()
    base = f"/api/v1/t/{ctx.tenant_id}"
    began = time.perf_counter()
    upload = await client.post(f"{base}/workflows/{root_wf}/csv-uploads", content=data,
                               headers={"Content-Type": "text/csv"})  # fmt: skip
    assert upload.status_code == 201, upload.text
    csv = {"upload_id": upload.json()["upload_id"], "mapping": {c["name"]: c["header"] for c in COLUMNS}}
    started = await client.post(f"{base}/workflows/{root_wf}/runs", headers={"Idempotency-Key": "crossing"},
                                json={"csv": csv})  # fmt: skip
    assert started.status_code == 202, started.text
    admitted_s = time.perf_counter() - began
    root_id = started.json()["id"]
    async with owner_sessionmaker() as s:
        owned = (await s.execute(text("select count(*) from run_inputs where owner_run_id = :r"),
                                 {"r": root_id})).scalar_one()  # fmt: skip

    async with serving(server.client, DbRunStore(worker_sessionmaker, KEYS)):  # type: ignore[arg-type]
        began = time.perf_counter()
        assert await dispatch.dispatch_once(dispatch_sessionmaker, server.client, KEYS, api_settings, BUILD) == {
            "started": 1
        }
        while time.perf_counter() - began < DEADLINE_S:
            found = (await client.get(f"{base}/runs/{root_id}")).json()
            if found["status"] not in ("queued", "starting", "running"):
                break
            await asyncio.sleep(0.5)
        whole_s = time.perf_counter() - began
    async with owner_sessionmaker() as s:
        runs = (await s.execute(text(
            "select id, parent_run_id, status, extract(epoch from ended_at - started_at) from runs "
            "where root_run_id = :r order by started_at"), {"r": root_id})).all()  # fmt: skip
        granted = {str(r): n for r, n in (await s.execute(text(
            "select run_id, count(*) from claim_grants where run_id in (select id from runs where root_run_id = :r) "
            "group by run_id"), {"r": root_id})).all()}  # fmt: skip
    by_parent = {str(p): str(i) for i, p, *_ in runs if p is not None}
    result = {
        "rows": ROWS, "csv_bytes": len(data), "admitted_s": round(admitted_s, 1), "root_owned_claims": owned,
        "whole_run_s": round(whole_s, 1),
        "runs": [{"depth": d, "status": st, "s": round(float(took), 1) if took is not None else None}
                 for d, (_, _, st, took) in enumerate(runs)],
        "crossings": [
            {"from_depth": d, "activity": await crossings(server.client, str(ctx.tenant_id), str(i)),
             "granted": granted.get(by_parent.get(str(i), ""), 0)}
            for d, (i, *_) in enumerate(runs[:-1])
        ],
    }  # fmt: skip
    print(json.dumps(result))
    out = os.environ.get("DEWPOINT_PROBE_OUT")
    if out:
        Path(out).write_text(json.dumps(result, indent=1))  # noqa: ASYNC240  # once, at the end
    assert [r["status"] for r in result["runs"]] == ["succeeded"] * 3, result
