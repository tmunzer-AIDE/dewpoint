# SPDX-License-Identifier: Apache-2.0
"""A plugin step that reaches the network, through its activity (plugins-3 D7, D10): what each transport failure shows
(its fixed code and message) and whether it's retried, by the node's side effect: nothing sent is retried or fails, a
request that may have arrived is `outcome_unknown` for an ambiguous node."""

import asyncio
import dataclasses
import ipaddress
import uuid
from typing import Any

import pytest
from temporalio.exceptions import ApplicationError
from temporalio.testing import ActivityEnvironment

from dewpoint.apps.worker.activities import step_activity_for
from dewpoint.apps.worker.network import DbConnections, Network
from dewpoint.apps.worker.store import DbRunStore
from dewpoint.core.connections.types import CONNECTION_TYPES
from dewpoint.core.egress.addresses import AllowEntry
from dewpoint.engine.runtime.activities import MAPPED, OUTCOME_UNKNOWN, StepInput
from dewpoint.engine.runtime.ids import run_workflow_id
from tests.support.connections import TESTKIT_TYPE, add_connection, seed_step
from tests.support.keys import FixtureKeys
from tests.support.netfakes import Request, guard, respond, serve, tls
from tests.support.plugins.testkit import AmbiguousCall, HttpCall

NAMES = ("dewpoint.test",)


@pytest.fixture(autouse=True)
def testkit_type(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(CONNECTION_TYPES, "testkit", TESTKIT_TYPE)


async def _run(worker: Any, owner: Any, port: int, node: type, *, host: str = "dewpoint.test") -> Any:
    tenant = uuid.uuid4()
    await seed_step(owner, named=[None], tenant=tenant)
    cid = await add_connection(owner, tenant, config={"base_url": f"https://{host}:{port}"})
    seeded = await seed_step(owner, named=[cid], tenant=tenant, node_type=f"{node.type}@{node.version}")
    network = Network(
        guard=guard({"dewpoint.test": ["127.0.0.1"], "private.test": ["10.0.0.9"]},
                    [AllowEntry(ipaddress.ip_network("127.0.0.1/32"), None, tenant)]),  # fmt: skip
        connections=DbConnections(worker),
        sessionmaker=worker,
        keys=FixtureKeys(),
        ssl_context=tls(NAMES).client_context(),
    )
    activity = step_activity_for(node, DbRunStore(worker, FixtureKeys()), network)
    step = StepInput(
        tenant_id=str(tenant), run_id=str(seeded.run), step_id=str(seeded.step), node_key="call", iteration_key="",
        ref=f"{node.type}@{node.version}", config={"connection": str(cid), "path": "/", "method": "POST"},
        root_run_id=str(seeded.run),
    )  # fmt: skip
    env = ActivityEnvironment()
    env.info = dataclasses.replace(env.info, workflow_id=run_workflow_id(str(tenant), str(seeded.run)))
    return await env.run(activity, step)


async def _failure(*args: Any, **kwargs: Any) -> ApplicationError:
    with pytest.raises(ApplicationError) as raised:
        await _run(*args, **kwargs)
    return raised.value


async def test_a_step_calls_its_connection(owner_sessionmaker, worker_sessionmaker) -> None:
    async with serve(respond(201, b"made"), tls_names=NAMES) as server:
        result = await _run(worker_sessionmaker, owner_sessionmaker, server.port, HttpCall)
    assert result.output == {"status": 201, "body": "made"}


async def test_a_refused_destination_fails_and_isnt_retried(owner_sessionmaker, worker_sessionmaker) -> None:
    failure = await _failure(worker_sessionmaker, owner_sessionmaker, 443, HttpCall, host="private.test")
    assert (failure.type, failure.non_retryable, failure.details[0]["outcome"]) == ("egress_refused", True, None)
    assert failure.message == "The destination isn't allowed."
    assert failure.details[0][MAPPED] is True


async def test_nothing_sent_is_retried(owner_sessionmaker, worker_sessionmaker) -> None:
    async with serve(respond(), tls_names=NAMES) as server:
        port = server.port
    failure = await _failure(worker_sessionmaker, owner_sessionmaker, port, AmbiguousCall)  # the server is gone
    assert (failure.type, failure.non_retryable, failure.details[0]["outcome"]) == ("not_sent", False, None)


def _hang_up() -> Any:
    async def handler(_: Request, writer: asyncio.StreamWriter) -> None:
        writer.close()

    return handler


async def test_maybe_sent_is_retried_by_a_repeatable_node(owner_sessionmaker, worker_sessionmaker) -> None:
    async with serve(_hang_up(), tls_names=NAMES) as server:
        failure = await _failure(worker_sessionmaker, owner_sessionmaker, server.port, HttpCall)
    assert (failure.type, failure.non_retryable, failure.details[0]["outcome"]) == ("maybe_sent", False, None)


async def test_maybe_sent_is_outcome_unknown_for_an_ambiguous_node(owner_sessionmaker, worker_sessionmaker) -> None:
    async with serve(_hang_up(), tls_names=NAMES) as server:
        failure = await _failure(worker_sessionmaker, owner_sessionmaker, server.port, AmbiguousCall)
    assert (failure.type, failure.non_retryable, failure.details[0]["outcome"]) == (
        "maybe_sent", True, OUTCOME_UNKNOWN,
    )  # fmt: skip
