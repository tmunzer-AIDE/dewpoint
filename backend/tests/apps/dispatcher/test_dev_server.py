# SPDX-License-Identifier: Apache-2.0
"""M5's proofs on Temporal's CLI dev server (engine 2b spec §7.4, §7.6, §12): a trustworthy absence behind a real
namespace check, and none from a namespace that doesn't exist; "already started" verified from a real history; the
reconciler's mapping of a real termination, and of a run that continued as new, to the logical run's latest
execution; and a run, then its re-run, end to end through the API, the dispatcher and the worker, with the keyring's
real keys everywhere (the owner's M4 condition for M5). The server is this module's own: no other test's builds
route its tasks."""

import asyncio
import dataclasses
import uuid
from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import text
from temporalio.client import Client
from temporalio.testing import WorkflowEnvironment

from dewpoint.apps.codec import ENCODING, data_converter
from dewpoint.apps.dispatcher import dispatch, reconcile
from dewpoint.apps.worker.store import DbRunStore
from dewpoint.core.crypto.kek import KekSet
from dewpoint.core.crypto.keyring import Keyring
from dewpoint.core.crypto.keys import KeyringKeys
from dewpoint.core.tenancy.service import ensure_tenant_keys
from dewpoint.engine.runtime.ids import run_workflow_id
from dewpoint.engine.runtime.workflow import RunGraph
from tests.apps.api.helpers import member_client
from tests.apps.dispatcher.support import BUILD, begin, state
from tests.apps.dispatcher.test_reconcile_runs import NoEndWrite
from tests.apps.test_admission import KEYS, SCHEMA, TOKEN, current, published
from tests.apps.worker.test_real_server import serving  # a versioned engine worker of a build made current
from tests.support.graphs import G, ref
from tests.support.keys import FIXTURE_CONVERTER

pytestmark = pytest.mark.usefixtures("development_deployment")
BODY = {"input": {"token": TOKEN, "site": "a"}, "mode": "live"}


@pytest.fixture(scope="module")
async def server() -> AsyncIterator[WorkflowEnvironment]:
    async with await WorkflowEnvironment.start_local(data_converter=FIXTURE_CONVERTER) as environment:
        yield environment


@pytest.fixture
async def ready(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings) -> Any:
    from tests.apps.dispatcher.support import workers as ready_workers

    ctx, wf = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings)
    await current(dispatch_sessionmaker)
    await ready_workers(owner_sessionmaker)
    return ctx, wf


async def admitted(api: Any, ctx: Any, wf: uuid.UUID, key: str) -> Any:
    from tests.apps.test_admission import admit

    return (await admit(api, ctx, wf, key=key)).request


async def starting(dispatch_sessionmaker: Any, request: Any, settings: Any) -> dispatch.Starting:
    found = await begin(dispatch_sessionmaker, request, settings)
    assert isinstance(found, dispatch.Starting), found
    return found


async def ended(owner: Any, run_id: uuid.UUID) -> tuple[Any, ...]:
    async with owner() as s:
        row = await s.execute(text("select status, error_code from runs where id = :i"), {"i": run_id})
        return tuple(row.one())


async def test_a_lost_reply_is_verified_and_a_start_that_never_arrived_found_absent(
    server, ready, owner_sessionmaker, api_sessionmaker, dispatch_sessionmaker, api_settings, monkeypatch
) -> None:
    ctx, wf = ready
    lost = await starting(dispatch_sessionmaker, await admitted(api_sessionmaker, ctx, wf, "a"), api_settings)
    never = await starting(dispatch_sessionmaker, await admitted(api_sessionmaker, ctx, wf, "b"), api_settings)
    assert (await dispatch.start(server.client, lost)).kind == "started"  # accepted; its reply never settled
    monkeypatch.setattr(reconcile, "GRACE", timedelta(0))
    counts = await reconcile.reconcile_once(dispatch_sessionmaker, server.client, KEYS, api_settings)
    assert counts == {"started": 1, "absent": 1}
    assert (await state(owner_sessionmaker, lost.request_id))["request"][0] == "started"
    assert (await state(owner_sessionmaker, never.request_id))["request"][0] == "queued"


async def test_a_namespace_that_doesnt_exist_never_reads_as_an_absence(
    server, ready, owner_sessionmaker, api_sessionmaker, dispatch_sessionmaker, api_settings, monkeypatch
) -> None:
    """Its NOT_FOUND is the namespace's, not the execution's: the start stays unresolved, its slot held."""
    ctx, wf = ready
    request = await admitted(api_sessionmaker, ctx, wf, "a")
    await starting(dispatch_sessionmaker, request, api_settings)
    target = server.client.service_client.config.target_host
    ghost = await Client.connect(target, namespace=f"dewpoint-ghost-{uuid.uuid4().hex[:8]}",
                                 data_converter=FIXTURE_CONVERTER)  # fmt: skip
    monkeypatch.setattr(reconcile, "GRACE", timedelta(0))
    assert await reconcile.reconcile_once(dispatch_sessionmaker, ghost, KEYS, api_settings) == {"unresolved": 1}
    after = await state(owner_sessionmaker, request.id)
    assert (after["request"][0], after["slot"]) == ("starting", 1)


async def test_already_started_is_verified_from_the_real_history(
    server, ready, api_sessionmaker, dispatch_sessionmaker, api_settings
) -> None:
    ctx, wf = ready
    found = await starting(dispatch_sessionmaker, await admitted(api_sessionmaker, ctx, wf, "a"), api_settings)
    assert (await dispatch.start(server.client, found)).kind == "started"
    again = await dispatch.start(server.client, found)  # the same start, sent again: Temporal refuses the duplicate
    assert again.kind == "started" and again.at is not None


async def test_the_reconciler_records_a_real_termination(
    server, ready, owner_sessionmaker, api_sessionmaker, dispatch_sessionmaker, api_settings
) -> None:
    ctx, wf = ready
    found = await starting(dispatch_sessionmaker, await admitted(api_sessionmaker, ctx, wf, "a"), api_settings)
    assert await dispatch.settle(dispatch_sessionmaker, found, await dispatch.start(server.client, found)) == "started"
    await server.client.get_workflow_handle(run_workflow_id(str(ctx.tenant_id), str(found.request_id))).terminate()
    assert await reconcile.reconcile_once(dispatch_sessionmaker, server.client, KEYS, api_settings) == {"ended": 1}
    assert await ended(owner_sessionmaker, found.request_id) == ("failed", "terminated")
    assert (await state(owner_sessionmaker, found.request_id))["slot"] == 0


async def test_the_reconciler_follows_continue_as_new_to_the_latest_executions_end(
    server, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, worker_sessionmaker,
    api_settings,
) -> None:  # fmt: skip
    """The first execution closed by continuing as new, which never ends the run: the end is its successor's."""
    from tests.apps.dispatcher.support import workers as ready_workers

    graph = G().node("l", "flow.loop@1", {"items": list(range(40)), "collect": ref("steps.x.output.value")})
    graph.node("x", "testkit.echo@1", {"value": ref("item")}).edge("l", "x", "body")  # long enough to continue
    ctx, wf = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings,
                              graph.data() | {"settings": {"input_schema": SCHEMA}})  # fmt: skip
    await current(dispatch_sessionmaker)
    await ready_workers(owner_sessionmaker)
    found = await starting(dispatch_sessionmaker, await admitted(api_sessionmaker, ctx, wf, "a"), api_settings)
    eager = dispatch.Starting(
        found.request_id, found.tenant_id, dataclasses.replace(found.start, checkpoint_events=120)
    )
    workflow_id = run_workflow_id(str(ctx.tenant_id), str(found.request_id))
    async with serving(server.client, NoEndWrite(worker_sessionmaker, KEYS)):  # type: ignore[arg-type]
        outcome = await dispatch.start(server.client, eager)
        assert await dispatch.settle(dispatch_sessionmaker, eager, outcome) == "started"
        handle = server.client.get_workflow_handle_for(RunGraph.run, workflow_id)
        assert (await asyncio.wait_for(handle.result(), 60)).status == "succeeded"
    latest = (await server.client.get_workflow_handle(workflow_id).fetch_history()).events[0]
    previous = latest.workflow_execution_started_event_attributes.continued_execution_run_id
    assert previous, "the run never continued as new"
    first = server.client.get_workflow_handle(workflow_id, run_id=previous)
    assert (await first.describe()).status.name == "CONTINUED_AS_NEW"
    assert await ended(owner_sessionmaker, found.request_id) == ("running", None)  # its end write never landed
    assert await reconcile.reconcile_once(dispatch_sessionmaker, server.client, KEYS, api_settings) == {"ended": 1}
    assert await ended(owner_sessionmaker, found.request_id) == ("succeeded", None)


async def until_ended(client: Any, url: str) -> dict[str, Any]:
    for _ in range(300):
        found = (await client.get(url)).json()
        if found["status"] not in ("queued", "starting", "running"):
            return found  # type: ignore[no-any-return]
        await asyncio.sleep(0.1)
    raise AssertionError(f"still {found['status']}")


async def test_a_run_and_its_rerun_end_to_end_with_the_keyrings_real_keys(
    server, ready, app, owner_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, worker_sessionmaker,
    api_settings,
) -> None:  # fmt: skip
    """The API admits with its keyring (no fixture keys), the dispatcher seals each start with the tenant's real data
    key, the worker opens it and the claims with its own, and the re-run rebuilds the input through the API's."""
    ctx, wf = ready
    keyring = Keyring(KekSet.from_settings(api_settings))
    async with admin_sessionmaker() as s, s.begin():
        assert ctx.tenant_id in await ensure_tenant_keys(s, keyring)  # a real data key, wrapped by the KEK
    dispatch_keys, worker_keys = KeyringKeys(dispatch_sessionmaker, keyring), KeyringKeys(worker_sessionmaker, keyring)
    target, namespace = server.client.service_client.config.target_host, server.client.namespace
    dispatcher = await Client.connect(target, namespace=namespace, data_converter=data_converter(dispatch_keys))
    worker = await Client.connect(target, namespace=namespace, data_converter=data_converter(worker_keys))
    operator, _ = await member_client(app, owner_sessionmaker, api_settings, ctx.tenant_id, "operator")
    answer = await operator.post(f"/api/v1/t/{ctx.tenant_id}/workflows/{wf}/runs", json=BODY,
                                 headers={"Idempotency-Key": "e2e-1"})  # fmt: skip
    assert answer.status_code == 202, answer.text
    request_id = answer.json()["id"]
    async with serving(worker, DbRunStore(worker_sessionmaker, worker_keys)):  # type: ignore[arg-type]
        assert await dispatch.dispatch_once(dispatch_sessionmaker, dispatcher, dispatch_keys, api_settings, BUILD) == {
            "started": 1
        }
        run = await until_ended(operator, f"/api/v1/t/{ctx.tenant_id}/runs/{request_id}")
        rerun = await operator.post(f"/api/v1/t/{ctx.tenant_id}/runs/{request_id}/rerun",
                                    headers={"Idempotency-Key": "e2e-2"})  # fmt: skip
        assert rerun.status_code == 202, rerun.text
        assert await dispatch.dispatch_once(dispatch_sessionmaker, dispatcher, dispatch_keys, api_settings, BUILD) == {
            "started": 1
        }
        again = await until_ended(operator, f"/api/v1/t/{ctx.tenant_id}/runs/{rerun.json()['id']}")
    assert (run["status"], again["status"], again["request"]["source"]) == ("succeeded", "succeeded", "rerun")
    history = server.client.get_workflow_handle(run_workflow_id(str(ctx.tenant_id), request_id))
    started_event = (await history.fetch_history()).events[0].workflow_execution_started_event_attributes
    assert started_event.input.payloads[0].metadata["encoding"] == ENCODING  # sealed, never plain JSON
    listed = (await operator.get(f"/api/v1/t/{ctx.tenant_id}/runs")).text
    assert TOKEN not in listed and TOKEN not in str(run) and TOKEN not in str(again)
