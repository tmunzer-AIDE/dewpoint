# SPDX-License-Identifier: Apache-2.0
"""The `StepContext` a plugin step receives (spec §3)."""

import hashlib
import uuid
from dataclasses import dataclass
from typing import Any

from temporalio import activity

from dewpoint.apps.worker.logs import Literals, StepLog
from dewpoint.sdk import Connection, ConnectionUnavailable, EgressRefused, HttpClient, Net, StepContext, StepLogger


def idempotency_key(run_id: str, step_id: str, iteration_key: str) -> str:
    """Derived from (run_id, step_id, iteration_key): the same for every attempt of a step in one iteration."""
    return hashlib.sha256(f"{run_id}\x1f{step_id}\x1f{iteration_key}".encode()).hexdigest()


class _NoNetwork:
    """A worker without a network (plugins-3 D7): nothing leaves it."""

    async def connection(self, connection_id: uuid.UUID) -> Connection:
        raise ConnectionUnavailable()

    async def request(self, *args: Any, **kwargs: Any) -> Any:
        raise EgressRefused()

    async def open_tcp(self, *args: Any, **kwargs: Any) -> Any:
        raise EgressRefused()

    async def send_udp(self, *args: Any, **kwargs: Any) -> None:
        raise EgressRefused()

    @property
    def http(self) -> Any:
        return self

    @property
    def net(self) -> Any:
        return self


@dataclass(frozen=True)
class Context:
    tenant_id: uuid.UUID
    run_id: uuid.UUID
    step_id: uuid.UUID
    iteration_key: str
    attempt: int
    log: StepLogger
    network: Any = None  # the attempt's `AttemptNetwork` (plugins-3 D4, D7); None: nothing leaves this worker

    @property
    def cancelled(self) -> bool:
        return activity.is_cancelled()

    def idempotency_key(self) -> str:
        return idempotency_key(str(self.run_id), str(self.step_id), self.iteration_key)

    def heartbeat(self, *details: object) -> None:
        activity.heartbeat()  # never the details: a plugin's own data, which a timeout writes into history (§12)

    def _network(self) -> Any:
        return self.network if self.network is not None else _NoNetwork()

    async def connection(self, connection_id: uuid.UUID) -> Connection:
        found: Connection = await self._network().connection(connection_id)
        return found

    @property
    def http(self) -> HttpClient:
        client: HttpClient = self._network().http
        return client

    @property
    def net(self) -> Net:
        sockets: Net = self._network().net
        return sockets


def context(
    tenant_id: str,
    run_id: str,
    step_id: str,
    iteration_key: str,
    attempt: int,
    known: Literals = frozenset(),
    network: Any = None,
) -> StepContext:
    """`known`: the constants of the node's plugin, all its log may hold (engine 2b spec §6.7); `network`: the attempt's
    (plugins-3 D4, D7)."""
    log = StepLog(known, run_id=run_id, step_id=step_id, iteration_key=iteration_key)
    return Context(uuid.UUID(tenant_id), uuid.UUID(run_id), uuid.UUID(step_id), iteration_key, attempt, log, network)
