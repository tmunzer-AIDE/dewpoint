# SPDX-License-Identifier: Apache-2.0
"""A plugin step that reaches the network, through its activity (plugins-3 D7, D10): what each transport failure shows
(its fixed code and message) and whether it's retried, by the node's side effect: nothing sent is retried or fails, a
request that may have arrived is `outcome_unknown` for an ambiguous node."""

import asyncio
import dataclasses
import ipaddress
import socket
import uuid
from typing import Any

import pytest
from temporalio.exceptions import ApplicationError
from temporalio.testing import ActivityEnvironment

from dewpoint.apps.worker.activities import _transport_failed, step_activity_for
from dewpoint.apps.worker.network import DbConnections, Network
from dewpoint.apps.worker.store import DbRunStore
from dewpoint.core.egress.addresses import AllowEntry
from dewpoint.engine.runtime.activities import MAPPED, OUTCOME_UNKNOWN, StepInput
from dewpoint.engine.runtime.ids import run_workflow_id
from dewpoint.sdk import HandshakeRejected, StreamLost
from tests.support.connections import add_connection, seed_step, types_for_testkit
from tests.support.keys import FixtureKeys
from tests.support.netfakes import Request, guard, respond, serve, tls
from tests.support.plugins.testkit import AmbiguousCall, HttpCall, WriteThenRead

NAMES = ("dewpoint.test",)


async def _run(
    worker: Any, owner: Any, port: int, node: type, *, host: str = "dewpoint.test", extra: dict[str, Any] | None = None,
    types: Any = None,
) -> Any:  # fmt: skip
    tenant = uuid.uuid4()
    await seed_step(owner, named=[None], tenant=tenant)
    cid = await add_connection(owner, tenant, config={"base_url": f"https://{host}:{port}"})
    seeded = await seed_step(owner, named=[cid], tenant=tenant, node_type=f"{node.type}@{node.version}")
    network = Network(
        guard=guard(
            {"dewpoint.test": ["127.0.0.1"], "private.test": ["10.0.0.9"]},
            [AllowEntry(ipaddress.ip_network("127.0.0.1/32"), None, tenant)],
        ),  # fmt: skip
        connections=DbConnections(worker),
        sessionmaker=worker,
        keys=FixtureKeys(),
        ssl_context=tls(NAMES).client_context(),
        types=types or types_for_testkit(),
    )
    activity = step_activity_for(node, DbRunStore(worker, FixtureKeys()), network)
    step = StepInput(
        tenant_id=str(tenant), run_id=str(seeded.run), step_id=str(seeded.step), node_key="call", iteration_key="",
        ref=f"{node.type}@{node.version}",
        config=(
            {"connection": str(cid), **(extra or {})}
            if node is WriteThenRead
            else {"connection": str(cid), "path": "/", "method": "POST"}
        ),
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


async def test_a_failure_after_an_earlier_send_is_never_retried_for_an_ambiguous_node(
    owner_sessionmaker, worker_sessionmaker
) -> None:
    """The review's finding 1: the second call sends nothing, but the first may have arrived."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        closed = sock.getsockname()[1]
    async with serve(respond(201, b"made"), tls_names=NAMES) as server:
        failure = await _failure(worker_sessionmaker, owner_sessionmaker, server.port, WriteThenRead,
                                 extra={"read_url": f"https://dewpoint.test:{closed}/read"})  # fmt: skip
    assert [r.method for r in server.requests] == ["POST"]
    assert (failure.type, failure.non_retryable, failure.details[0]["outcome"]) == ("not_sent", True, OUTCOME_UNKNOWN)


async def test_a_cooldown_after_an_earlier_send_is_never_retried_for_an_ambiguous_node(
    owner_sessionmaker, worker_sessionmaker
) -> None:
    async with serve(respond(201, b"made"), tls_names=NAMES) as server:
        failure = await _failure(worker_sessionmaker, owner_sessionmaker, server.port, WriteThenRead,
                                 types=types_for_testkit(capacity=1, refill_per_s=0.001))  # fmt: skip
    assert [r.method for r in server.requests] == ["POST"]
    assert (failure.type, failure.non_retryable, failure.details[0]["outcome"]) == ("cooldown", True, OUTCOME_UNKNOWN)


def _slow_post(seen_post: asyncio.Event) -> Any:
    async def handler(request: Request, writer: asyncio.StreamWriter) -> None:
        if request.method == "POST":
            seen_post.set()
            await asyncio.sleep(3)  # received, its answer pending while the concurrent read fails
        await respond(201, b"made")(request, writer)

    return handler


async def test_a_failure_while_a_write_is_in_flight_is_never_retried(owner_sessionmaker, worker_sessionmaker) -> None:
    """The second review's finding 1: a write received but not yet answered, and a concurrent read that sent nothing."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        closed = sock.getsockname()[1]

    seen_post = asyncio.Event()
    async with serve(_slow_post(seen_post), tls_names=NAMES) as server:
        extra = {"read_url": f"https://dewpoint.test:{closed}/read", "concurrent": True}
        failure = await _failure(worker_sessionmaker, owner_sessionmaker, server.port, WriteThenRead, extra=extra)
    assert [r.method for r in server.requests] == ["POST"]
    assert (failure.non_retryable, failure.details[0]["outcome"]) == (True, OUTCOME_UNKNOWN)


async def test_the_nodes_own_fatal_error_after_a_write_is_of_unknown_outcome(
    owner_sessionmaker, worker_sessionmaker
) -> None:
    """The second review's ruling 4: a later failure can't establish what the earlier write did."""
    async with serve(respond(201, b"made"), tls_names=NAMES) as server:
        failure = await _failure(worker_sessionmaker, owner_sessionmaker, server.port, WriteThenRead,
                                 extra={"then_fail": True})  # fmt: skip
    assert [r.method for r in server.requests] == ["POST"]
    assert (failure.type, failure.non_retryable, failure.details[0]["outcome"]) == (
        "testkit.refused", True, OUTCOME_UNKNOWN,
    )  # fmt: skip


@pytest.mark.parametrize(
    ("error", "node", "retryable", "outcome"),
    [
        (HandshakeRejected(401), HttpCall, False, None),  # only the handshake was sent: credentials fail for good
        (HandshakeRejected(403), AmbiguousCall, False, None),
        (HandshakeRejected(429), AmbiguousCall, True, None),  # nothing a node answers for was sent
        (HandshakeRejected(503), HttpCall, True, None),
        (HandshakeRejected(302), HttpCall, False, None),  # a redirect, never followed
        (StreamLost(), HttpCall, True, None),  # a message may have left with it: a repeatable node retries
        (StreamLost(), AmbiguousCall, False, "outcome_unknown"),
    ],
)  # fmt: skip
def test_a_streams_failure_is_classified_by_what_may_have_been_sent(
    error: Exception, node: type, retryable: bool, outcome: str | None
) -> None:
    """A stream's failures escaping a node (plugins-3 D26), each with its own fixed code."""
    failed = _transport_failed(error, node)  # type: ignore[arg-type]
    assert (failed.code, failed.retryable, failed.outcome) == (type(error).code, retryable, outcome)
