# SPDX-License-Identifier: Apache-2.0
"""2b-3a's proofs on Temporal's CLI dev server (engine 2b spec §8.1, §8.2, §12):

- a CSV start and a schedule's tick, each a run end to end through the API, the sync, the dispatcher's own admission
  worker, the dispatcher and a versioned engine worker, with the keyring's real keys everywhere; canaries in a
  sensitive CSV cell, in a file header (so in the mapping too) and in a schedule's fixed input appear in no execution's
  whole raw history, no projection, no stored row in plain and no log line;
- a server outage shorter than a schedule's catch-up window: each missed time fires when it's back, and each is
  admitted once, under its own key."""

import asyncio
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import structlog
from sqlalchemy import text
from temporalio.client import (
    Client,
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleBackfill,
    ScheduleIntervalSpec,
    ScheduleOverlapPolicy,
    SchedulePolicy,
    ScheduleSpec,
)
from temporalio.testing import WorkflowEnvironment

from dewpoint.apps import schedules
from dewpoint.apps.codec import data_converter
from dewpoint.apps.dispatcher import dispatch, main, schedule_sync, tick
from dewpoint.apps.worker.store import DbRunStore
from dewpoint.core.claims import service as claims
from dewpoint.core.claims.cipher import ClaimCipher
from dewpoint.core.crypto.kek import KekSet
from dewpoint.core.crypto.keyring import Keyring
from dewpoint.core.crypto.keys import KeyringKeys
from dewpoint.core.db import tenant_scope
from dewpoint.core.tenancy.service import ensure_tenant_keys
from dewpoint.engine.handles import StoredClaim, resolve_value
from dewpoint.engine.runtime.ids import schedule_workflow_id
from tests.apps.api.helpers import member_client
from tests.apps.dispatcher.support import BUILD, workers
from tests.apps.dispatcher.test_dev_server import until_ended
from tests.apps.test_admission import KEYS, SCHEMA, current, published
from tests.apps.test_workflow_ops import create, publish
from tests.apps.worker.test_real_server import serving
from tests.support.graphs import G, ref
from tests.support.keys import FIXTURE_CONVERTER
from tests.support.temporal import start_local

pytestmark = pytest.mark.usefixtures("development_deployment")
CELL, HEADER, FIXED = "CSVcell-c4n4ry-7Q2", "Hdr-c4n4ry-K9", "Sched-c4n4ry-3Z"
CANARIES = (CELL, HEADER, FIXED)
PSK = {"header": "PSK", "name": "psk", "type": "string", "required": True, "sensitive": True}
CSV = {"columns": [{"header": "Site", "name": "site", "type": "string", "required": True}, PSK]}
CSV_GRAPH = (
    G().node("l", "flow.loop@1", {"items": ref("trigger.rows")})
    .node("s", "testkit.echo@1", {"value": ref("item.site")}).edge("l", "s", "body")
    .node("p", "testkit.echo@1", {"value": ref("item.psk")}).edge("l", "p", "body")
).data() | {"settings": {"input_schema": {"type": "object", "properties": {}}, "csv": CSV}}  # fmt: skip
SCHEDULED_GRAPH = G().node("a", "testkit.echo@1", {"value": ref("trigger.token")}).data() | {
    "settings": {"input_schema": SCHEMA}
}


class Leading:
    async def leading(self) -> bool:
        return True


@pytest.fixture(scope="module")
async def server() -> AsyncIterator[WorkflowEnvironment]:
    async with await WorkflowEnvironment.start_local(data_converter=FIXTURE_CONVERTER) as environment:
        yield environment


async def raw_histories(client: Client) -> list[bytes]:
    """Every execution the namespace holds, each history whole, every event as the server stores it."""
    out: list[bytes] = []
    async for listed in client.list_workflows():
        history = await client.get_workflow_handle(listed.id, run_id=listed.run_id).fetch_history()
        out.append(b"".join(event.SerializeToString() for event in history.events))
    return out


async def plain_rows(owner: Any) -> str:
    """The projection and every row 2b-3a writes, as text: run requests, runs and steps, the audit log, schedules,
    uploads and run inputs (their ciphertexts included, which must not hold a canary in plain)."""
    async with owner() as s:
        tables = ("run_requests", "runs", "run_steps", "audit_log", "schedules", "csv_uploads", "csv_mappings",
                  "run_inputs", "step_outputs", "run_secret_index")  # fmt: skip
        dumped = [str((await s.execute(text(f"select * from {t}"))).all()) for t in tables]  # noqa: S608
    return "\n".join(dumped)


async def test_a_csv_start_and_a_schedules_tick_end_to_end_with_the_keyrings_real_keys_leak_no_canary(
    server, app, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, worker_sessionmaker,
    api_settings,
) -> None:  # fmt: skip
    ctx, csv_wf = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings, CSV_GRAPH)
    scheduled_wf = await create(api_sessionmaker, ctx, SCHEDULED_GRAPH, name="scheduled")
    assert (await publish(api_sessionmaker, ctx, scheduled_wf, api_settings)).version is not None
    await current(dispatch_sessionmaker)
    await workers(owner_sessionmaker)
    keyring = Keyring(KekSet.from_settings(api_settings))
    async with admin_sessionmaker() as s, s.begin():
        assert ctx.tenant_id in await ensure_tenant_keys(s, keyring)  # a real data key, wrapped by the KEK
    dispatch_keys, worker_keys = KeyringKeys(dispatch_sessionmaker, keyring), KeyringKeys(worker_sessionmaker, keyring)
    target, namespace = server.client.service_client.config.target_host, server.client.namespace
    dispatcher = await Client.connect(target, namespace=namespace, data_converter=data_converter(dispatch_keys))
    worker = await Client.connect(target, namespace=namespace, data_converter=data_converter(worker_keys))
    editor, _ = await member_client(app, owner_sessionmaker, api_settings, ctx.tenant_id, "editor")
    base = f"/api/v1/t/{ctx.tenant_id}"
    with structlog.testing.capture_logs() as logs:
        upload = await editor.post(f"{base}/workflows/{csv_wf}/csv-uploads", content=f"Site,{HEADER}\nparis,{CELL}\n",
                                   headers={"Content-Type": "text/csv"})  # fmt: skip
        assert upload.status_code == 201, upload.text
        started = await editor.post(f"{base}/workflows/{csv_wf}/runs", headers={"Idempotency-Key": "csv-1"}, json={
            "csv": {"upload_id": upload.json()["upload_id"], "mapping": {"site": "Site", "psk": HEADER}},
        })  # fmt: skip
        assert started.status_code == 202, started.text
        # Its backfilled firing, at the top of this hour, stays inside a 2-hour catch-up window.
        scheduled = await editor.post(f"{base}/workflows/{scheduled_wf}/schedules", json={
            "every_s": 3600, "catchup_window_s": 7200, "input": {"token": FIXED, "site": "lyon"},
        })  # fmt: skip
        assert scheduled.status_code == 201, scheduled.text
        schedule_id = uuid.UUID(scheduled.json()["id"])
        assert await schedule_sync.sync_one(dispatch_sessionmaker, dispatcher, Leading(), ctx.tenant_id,
                                            schedule_id) == "synced"  # fmt: skip
        hour = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
        handle = dispatcher.get_schedule_handle(schedule_workflow_id(str(ctx.tenant_id), str(schedule_id)) + "~1")
        async with (
            main.admission_worker(dispatcher, dispatch_sessionmaker, dispatch_keys),
            serving(
                worker,
                DbRunStore(worker_sessionmaker, worker_keys),  # type: ignore[arg-type]
            ),
        ):
            await handle.backfill(ScheduleBackfill(start_at=hour - timedelta(seconds=30), end_at=hour,
                                                   overlap=ScheduleOverlapPolicy.ALLOW_ALL))  # fmt: skip
            tick_request = await until_requested(owner_sessionmaker, f"sched:{schedule_id}:")
            for _ in range(20):
                done = await dispatch.dispatch_once(dispatch_sessionmaker, dispatcher, dispatch_keys, api_settings,
                                                    BUILD)  # fmt: skip
                if not done:
                    break
            csv_run = await until_ended(editor, f"{base}/runs/{started.json()['id']}")
            tick_run = await until_ended(editor, f"{base}/runs/{tick_request}")
        await handle.delete()
    assert (csv_run["status"], tick_run["status"], tick_run["request"]["source"]) == ("succeeded", "succeeded",
                                                                                       "schedule")  # fmt: skip
    # the canaries were in the data: each request's input, decrypted with the real keys, holds its canary
    csv_input = await decrypted_input(dispatch_sessionmaker, dispatch_keys, ctx.tenant_id, started.json()["id"])
    tick_input = await decrypted_input(dispatch_sessionmaker, dispatch_keys, ctx.tenant_id, tick_request)
    assert (csv_input["rows"], tick_input["token"]) == ([{"site": "paris", "psk": CELL}], FIXED)
    raws = await raw_histories(server.client)
    assert len(raws) >= 3  # the CSV run, the tick, the scheduled run
    assert all(str(ctx.tenant_id).encode() in raw for raw in raws)  # this tenant's real histories, read whole
    assert not [c for c in CANARIES for raw in raws if c.encode() in raw]
    rows = await plain_rows(owner_sessionmaker)
    assert not [c for c in CANARIES if c in rows]
    assert not [c for c in CANARIES for entry in logs if c in str(entry)]
    for run in (csv_run, tick_run):
        steps = (await editor.get(f"{base}/runs/{run['id']}")).json()["steps"]
        assert steps and not [c for c in (CELL, FIXED) if c in str(steps)]


async def decrypted_input(dispatch: Any, keys: Any, tenant_id: uuid.UUID, request_id: str) -> Any:
    """A request's whole input, its envelope read and its claims resolved with `keys`, in memory only."""
    cipher = ClaimCipher(keys)
    async with dispatch() as s, s.begin():
        await tenant_scope(s, tenant_id)

        async def fetch(claim_id: str) -> StoredClaim:
            got = await claims.read_request_claim(s, cipher, tenant_id, request_id=uuid.UUID(request_id),
                                                  claim_id=uuid.UUID(claim_id))  # fmt: skip
            return StoredClaim(got.value, got.sensitive_pointers)

        envelope = await claims.read_envelope(s, cipher, tenant_id, request_id=uuid.UUID(request_id))
        return (await resolve_value(envelope, fetch)).value


async def until_requested(owner: Any, prefix: str) -> str:
    for _ in range(150):
        async with owner() as s:
            found = (await s.execute(text("select id from run_requests where idempotency_key like :p"),
                                     {"p": f"{prefix}%"})).scalar_one_or_none()  # fmt: skip
        if found is not None:
            return str(found)
        await asyncio.sleep(0.2)
    raise AssertionError("the tick admitted nothing")


async def test_a_short_outage_fires_each_missed_time_and_admits_each_once(
    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings, tmp_path: Path
) -> None:
    """Within the catch-up window, no tick is dropped: the times missed while the server was down fire when it's back,
    each with its own nominal time, and each is admitted once, under its own key. (The Temporal Schedule fires every
    2 s here, past the product's 60 s floor, to keep the outage short.)"""
    ctx, wf = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings)
    await current(dispatch_sessionmaker)
    async with api_sessionmaker() as s, s.begin():
        await tenant_scope(s, ctx.tenant_id)
        created = await schedules.create(
            s, KEYS, tenant_id=ctx.tenant_id, actor_id=ctx.user.id, workflow_id=wf,
            timing={"cron": None, "every_s": 60, "offset_s": 0, "time_zone": "UTC", "catchup_window_s": 600},
            mode="live", input={"token": "t0ken-value-1", "site": "a"}, enabled=True,
        )  # fmt: skip
    temporal_id = schedule_workflow_id(str(ctx.tenant_id), str(created.id))
    args = ["--db-filename", str(tmp_path / "temporal.db")]
    async with await start_local(data_converter=FIXTURE_CONVERTER, dev_server_extra_args=args) as env:
        async with main.admission_worker(env.client, dispatch_sessionmaker, KEYS):
            await env.client.create_schedule(temporal_id, Schedule(
                action=ScheduleActionStartWorkflow("ScheduleTick", id=temporal_id, task_queue=tick.ADMISSION_QUEUE),
                spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=timedelta(seconds=2))]),
                policy=SchedulePolicy(catchup_window=timedelta(minutes=1), overlap=ScheduleOverlapPolicy.ALLOW_ALL),
            ))  # fmt: skip
            await admitted(owner_sessionmaker, 2)
    down = datetime.now(UTC)
    await asyncio.sleep(7)  # about three firings missed, well within the window
    async with await start_local(data_converter=FIXTURE_CONVERTER, dev_server_extra_args=args) as env:
        async with main.admission_worker(env.client, dispatch_sessionmaker, KEYS):
            times = await admitted(owner_sessionmaker, 0, after=down, at_least=3)
            handle = env.client.get_schedule_handle(temporal_id)
            await handle.pause()  # it fires no more: every tick it fired is admitted before the worker stops
            await admitted(owner_sessionmaker, (await handle.describe()).info.num_actions)
            await handle.delete()
    stamps = await nominal_times(owner_sessionmaker)
    assert len(stamps) == len(set(stamps))  # each time admitted once
    gaps = {(b - a).total_seconds() for a, b in zip(stamps, stamps[1:], strict=False)}
    assert gaps == {2.0}, stamps  # every time fired, the missed ones included: no gap
    assert len([t for t in times if t > down]) >= 3


async def nominal_times(owner: Any) -> list[datetime]:
    async with owner() as s:
        keys = (await s.execute(text("select idempotency_key from run_requests"))).scalars().all()
    stamps = [key.split(":", 2)[2] for key in keys]  # `sched:<schedule id>:<nominal time>`
    return sorted(datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC) for stamp in stamps)


async def admitted(owner: Any, n: int, *, after: datetime | None = None, at_least: int = 0) -> list[datetime]:
    """Until `n` requests exist, or `at_least` of them have nominal times after `after`."""
    for _ in range(150):
        times = await nominal_times(owner)
        if (after is None and len(times) >= n) or (
            after is not None and len([t for t in times if t > after]) >= at_least
        ):
            return times
        await asyncio.sleep(0.2)
    raise AssertionError(f"admitted only {await nominal_times(owner)}")
