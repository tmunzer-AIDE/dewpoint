# SPDX-License-Identifier: Apache-2.0
"""The dispatcher's start call (the 2b-4b M4 start-check slice): every start of a request carries the start request id
recorded with it, as one SDK RPC attempt (`retry=False`), counted before it's made, at most `CAP`; the SDK builds and
seals the request as it always does, and nothing else any client sends changes."""

import contextlib
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import text
from temporalio.client import Client
from temporalio.converter import WorkflowSerializationContext

from dewpoint.apps.codec import data_converter
from dewpoint.apps.dispatcher import dispatch, start_call
from dewpoint.engine.runtime.activities import RunInput
from dewpoint.engine.runtime.ids import run_workflow_id
from tests.apps.dispatcher.support import BUILD, begin
from tests.apps.test_admission import KEYS

pytestmark = pytest.mark.usefixtures("development_deployment")
NOWHERE = "start-call-test-nowhere"  # no worker polls it: a start is created and nothing runs


@contextlib.contextmanager
def rpcs(client: Client) -> Iterator[list[tuple[str, Any, bool]]]:
    """Each RPC the SDK makes while recorded, at its lowest level: its name, its request and whether it may retry."""
    cls = type(client.service_client)
    original = cls._rpc_call
    seen: list[tuple[str, Any, bool]] = []

    async def call(self_: Any, *args: Any, **kw: Any) -> Any:
        seen.append((kw["rpc"], kw["req"], kw["retry"]))
        return await original(self_, *args, **kw)

    cls._rpc_call = call  # type: ignore[method-assign]
    try:
        yield seen
    finally:
        cls._rpc_call = original  # type: ignore[method-assign]


def _starts(seen: list[tuple[str, Any, bool]]) -> list[tuple[str, bool]]:
    return [(req.request_id, retry) for rpc, req, retry in seen if rpc == "start_workflow_execution"]


async def test_a_start_within_sending_carries_the_id_and_is_one_rpc_attempt(env) -> None:  # type: ignore[no-untyped-def]
    start_call.install(env.client)
    start_call.install(env.client)  # once is enough: installing again changes nothing
    rid = uuid.uuid4()
    with rpcs(env.client) as seen, start_call.sending(rid):
        handle = await env.client.start_workflow("Anything", id=f"t:{uuid.uuid4()}:run:{uuid.uuid4()}",
                                                 task_queue=NOWHERE)  # fmt: skip
    assert _starts(seen) == [(str(rid), False)]
    with rpcs(env.client) as seen:
        other = await env.client.start_workflow("Anything", id=f"t:{uuid.uuid4()}:run:{uuid.uuid4()}",
                                                task_queue=NOWHERE)  # fmt: skip
        await other.describe()
    [(request_id, retry)] = _starts(seen)
    assert request_id not in ("", str(rid)) and retry is True  # outside `sending`, the SDK's own
    assert all(retry for rpc, _, retry in seen if rpc == "describe_workflow_execution")
    await handle.terminate()
    await other.terminate()


async def test_another_clients_start_is_untouched_even_within_sending(env) -> None:  # type: ignore[no-untyped-def]
    start_call.install(env.client)
    other = await Client.connect(env.client.service_client.config.target_host, namespace=env.client.namespace)
    rid = uuid.uuid4()
    with rpcs(other) as seen, start_call.sending(rid):
        handle = await other.start_workflow("Anything", id=f"t:{uuid.uuid4()}:run:{uuid.uuid4()}", task_queue=NOWHERE)
    [(request_id, retry)] = _starts(seen)
    assert request_id != str(rid) and retry is True
    await handle.terminate()


async def _row(owner: Any, request_id: uuid.UUID) -> tuple[Any, ...]:
    async with owner() as s:
        return tuple((await s.execute(text("select status, start_request_id, sends from run_requests where id = :i"),
                                      {"i": request_id})).one())  # fmt: skip


async def test_the_dispatchers_start_carries_its_recorded_id_counted_and_sealed_as_the_sdk_seals(
    queued, owner_sessionmaker, dispatch_sessionmaker, api_settings, env
) -> None:
    _, _, request = queued
    start_call.install(env.client)
    starting = await begin(dispatch_sessionmaker, request, api_settings)
    assert isinstance(starting, dispatch.Starting) and starting.start_request_id is not None
    assert await _row(owner_sessionmaker, request.id) == ("starting", starting.start_request_id, 1)
    with rpcs(env.client) as seen:
        assert (await dispatch.start(env.client, starting)).kind == "started"
    [(rpc, req, retry)] = [s for s in seen if s[0] == "start_workflow_execution"]
    assert (req.request_id, retry) == (str(starting.start_request_id), False)
    workflow_id = run_workflow_id(str(request.tenant_id), str(request.id))
    context = WorkflowSerializationContext(namespace=env.client.namespace, workflow_id=workflow_id)
    [decoded] = await data_converter(KEYS).with_context(context).decode(list(req.input.payloads), [RunInput])
    assert decoded == starting.start  # the SDK's sealing, untouched: the tenant's key opens exactly what it sealed


async def test_a_request_keeps_its_id_across_sends_and_its_count_survives_a_restart(
    queued, owner_sessionmaker, dispatch_sessionmaker, api_settings
) -> None:
    _, _, request = queued
    first = await begin(dispatch_sessionmaker, request, api_settings)
    async with owner_sessionmaker() as s, s.begin():  # as a settled absence leaves it: back in the queue, due now
        await s.execute(text("delete from run_slots where run_id = :i"), {"i": request.id})
        await s.execute(text("update run_requests set status = 'queued', next_attempt_at = now() where id = :i"),
                        {"i": request.id})  # fmt: skip
    second = await begin(dispatch_sessionmaker, request, api_settings)
    assert isinstance(second, dispatch.Starting) and second.start_request_id == first.start_request_id
    assert await _row(owner_sessionmaker, request.id) == ("starting", first.start_request_id, 2)  # a new session


async def test_at_the_cap_no_send_begins(queued, owner_sessionmaker, dispatch_sessionmaker, api_settings, env) -> None:
    _, _, request = queued
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(text("update run_requests set sends = :n where id = :i"),
                        {"n": start_call.CAP, "i": request.id})  # fmt: skip
    start_call.install(env.client)
    seal = dispatch.sealer(data_converter(KEYS), "default")
    with rpcs(env.client) as seen:
        happened = await dispatch._dispatch(dispatch_sessionmaker, env.client, seal, KEYS, api_settings, BUILD,
                                            request.tenant_id, request.id)  # fmt: skip
    assert happened == dispatch.SEND_CAP and _starts(seen) == []
    status, _, sends = await _row(owner_sessionmaker, request.id)
    assert (status, sends) == ("starting", start_call.CAP)  # out of the queue, for the reconciler; not counted again
    async with owner_sessionmaker() as s:
        slots = await s.execute(text("select count(*) from run_slots where run_id = :i"), {"i": request.id})
        assert slots.scalar() == 0


async def test_the_hooks_run_after_the_starting_commit_and_after_the_call_before_settling(
    queued, owner_sessionmaker, dispatch_sessionmaker, api_settings, env, monkeypatch
) -> None:
    _, _, request = queued
    start_call.install(env.client)
    seen: list[tuple[str, tuple[Any, ...]]] = []

    async def after_commit(request_id: uuid.UUID) -> None:
        seen.append(("committed", await _row(owner_sessionmaker, request_id)))  # another session: committed state

    async def after_call(request_id: uuid.UUID) -> None:
        seen.append(("called", await _row(owner_sessionmaker, request_id)))

    monkeypatch.setattr(dispatch, "_after_starting_commit", after_commit)
    monkeypatch.setattr(dispatch, "_after_start_call", after_call)
    seal = dispatch.sealer(data_converter(KEYS), "default")
    happened = await dispatch._dispatch(dispatch_sessionmaker, env.client, seal, KEYS, api_settings, BUILD,
                                        request.tenant_id, request.id)  # fmt: skip
    assert happened == "started"
    assert [(when, row[0], row[2]) for when, row in seen] == [("committed", "starting", 1), ("called", "starting", 1)]
    assert (await _row(owner_sessionmaker, request.id))[0] == "started"
