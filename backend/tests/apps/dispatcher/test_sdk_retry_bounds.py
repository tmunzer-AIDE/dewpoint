# SPDX-License-Identifier: Apache-2.0
"""How long one Temporal call can take, the SDK's retries included (the owner's D16 review of the 2b-4b M1 checkpoint 3:
SDK retry bounds before any budget's numbers), measured against a Temporal that stops answering and one that refuses
connections. The dispatcher makes two kinds of call:

- raw `workflow_service` calls, without retries (`retry=False`, the generated methods' default): at most their deadline;
- the SDK's own (`start_workflow`, a handle's `describe`, `cancel`, `result`, its history), sent with `retry=True`: the
  client's `RetryConfig` retries them inside its one RPC path until `max_elapsed_time_millis` has passed since the
  first attempt; each attempt keeps the call's deadline. So at most that time plus one attempt's deadline.

Measured here at a tenth of the dispatcher's numbers (a 1-second deadline, a 1-second retry limit, as `RETRY` scaled),
the bounds asserted with a margin; the dispatcher's own: 10 s raw, 20 s retried (`main.RETRY`, the 10-second
`CALL_DEADLINE`)."""

import asyncio
import contextlib
import time
from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any

import pytest
from temporalio.api.workflowservice.v1 import DescribeNamespaceRequest
from temporalio.client import Client
from temporalio.service import RetryConfig, RPCError
from temporalio.testing import WorkflowEnvironment

from dewpoint.apps.dispatcher import main
from tests.support.keys import FIXTURE_CONVERTER

DEADLINE = timedelta(seconds=1)
SCALED = RetryConfig(initial_interval_millis=100, randomization_factor=0.2, multiplier=1.5, max_interval_millis=500,
                     max_elapsed_time_millis=1_000, max_retries=10)  # fmt: skip
MARGIN_S = 0.6  # the scheduler's and the backoff's own slack


class Proxy:
    """A TCP proxy before the dev server: forwarding, frozen (it reads nothing more either way: Temporal stops
    answering), or refusing (every connection closed, none accepted)."""

    def __init__(self, target: str) -> None:
        self.host, port = target.rsplit(":", 1)
        self.port, self.frozen, self.connections = int(port), asyncio.Event(), []
        self.server: asyncio.Server | None = None

    async def _pump(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        with contextlib.suppress(ConnectionError, asyncio.CancelledError):
            while not self.frozen.is_set():
                read = asyncio.ensure_future(reader.read(65536))
                frozen = asyncio.ensure_future(self.frozen.wait())
                done, _ = await asyncio.wait({read, frozen}, return_when=asyncio.FIRST_COMPLETED)
                if read not in done:
                    read.cancel()
                    return
                frozen.cancel()
                data = read.result()
                if not data:
                    return
                writer.write(data)
                await writer.drain()

    async def _serve(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        upstream_reader, upstream_writer = await asyncio.open_connection(self.host, self.port)
        self.connections += [writer, upstream_writer]
        await asyncio.gather(self._pump(reader, upstream_writer), self._pump(upstream_reader, writer))

    async def start(self) -> str:
        self.server = await asyncio.start_server(self._serve, "127.0.0.1", 0)
        return f"127.0.0.1:{self.server.sockets[0].getsockname()[1]}"

    async def refuse(self) -> None:
        assert self.server is not None
        self.server.close()
        for writer in self.connections:
            writer.close()


@pytest.fixture(scope="module")
async def server() -> AsyncIterator[WorkflowEnvironment]:
    async with await WorkflowEnvironment.start_local(data_converter=FIXTURE_CONVERTER) as environment:
        yield environment


@pytest.fixture
async def proxied(server: WorkflowEnvironment) -> AsyncIterator[tuple[Proxy, Client]]:
    proxy = Proxy(server.client.service_client.config.target_host)
    target = await proxy.start()
    client = await Client.connect(target, namespace=server.client.namespace, retry_config=SCALED)
    try:
        yield proxy, client
    finally:
        await proxy.refuse()


async def _timed(call: Any) -> float:
    started = time.monotonic()
    with pytest.raises((RPCError, asyncio.TimeoutError, Exception)):
        await call
    return time.monotonic() - started


def _raw(client: Client) -> Any:
    return client.workflow_service.describe_namespace(DescribeNamespaceRequest(namespace=client.namespace),
                                                      timeout=DEADLINE)  # fmt: skip


def _retried(client: Client) -> Any:
    return client.get_workflow_handle("sdk-retry-bounds").describe(rpc_timeout=DEADLINE)


async def test_a_temporal_that_stops_answering_holds_a_raw_call_its_deadline_and_a_retried_one_no_more_than_its_retries_and_one_more(  # noqa: E501
    proxied,
) -> None:
    proxy, client = proxied
    proxy.frozen.set()
    raw = await _timed(_raw(client))
    retried = await _timed(_retried(client))
    elapsed = SCALED.max_elapsed_time_millis / 1000  # type: ignore[operator]
    assert DEADLINE.total_seconds() - 0.1 <= raw <= DEADLINE.total_seconds() + MARGIN_S
    assert DEADLINE.total_seconds() - 0.1 <= retried <= elapsed + DEADLINE.total_seconds() + MARGIN_S, retried


async def test_a_temporal_that_refuses_fails_a_raw_call_at_once_and_a_retried_one_within_its_retries(proxied) -> None:
    proxy, client = proxied
    await proxy.refuse()
    raw = await _timed(_raw(client))
    retried = await _timed(_retried(client))
    elapsed = SCALED.max_elapsed_time_millis / 1000  # type: ignore[operator]
    assert raw <= DEADLINE.total_seconds() + MARGIN_S
    assert retried <= elapsed + SCALED.max_interval_millis / 1000 + MARGIN_S, retried


def test_the_dispatchers_client_retries_as_these_bounds_assume() -> None:
    """The dispatcher connects with `main.RETRY`: these bounds' inputs, at ten times the scale measured here."""
    assert main.RETRY.max_elapsed_time_millis == 10 * SCALED.max_elapsed_time_millis
    assert main.RETRY.max_interval_millis == 5_000 and main.RETRY.max_retries == 10
